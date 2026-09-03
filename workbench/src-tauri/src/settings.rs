//! `settings.json` persistence: typed GUI preferences (ui/terminal/window) +
//! the pinned AISC CLI path.
//!
//! Spec: 02-startup-flow.md §三.4 (fields/defaults/bounds, per-field fallback)
//! + §九 (atomic write, schema mismatch preserves file, save protocol).
//!
//! Invariants:
//! - Typed defaults live ONLY here (Rust `Default`); the frontend receives
//!   them via `load_settings` and never hardcodes a second copy.
//! - Unknown fields (top-level and inside ui/terminal/window) survive
//!   round-trips: saves deep-merge typed values over the raw document
//!   (A-INFRA-5).
//! - Invalid fields fall back to their default per-field and are reported as
//!   validation issues; other valid fields are kept.
//! - GUI saves run under the cross-process lock with expected-revision
//!   conflict replay (max 3). Pin writes reuse the same locked save without a
//!   revision check (single-window startup contention, low risk).
//! - Unsupported schema_version: load errors, file untouched, saves refused
//!   (read-only). Corrupt JSON is isolated to `settings.json.corrupt`; the
//!   app runs on defaults and writes only after an explicit reset.

use std::fs;
use std::io;
use std::path::Path;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::AppHandle;

use fs4::fs_std::FileExt;

use crate::error::WorkbenchError;
use crate::storage;

pub const SCHEMA_VERSION: u64 = 1;
const SETTINGS_FILE: &str = "settings.json";
const LOCK_FILE: &str = "settings.lock";
const CORRUPT_SUFFIX: &str = ".corrupt";
const LOCK_TIMEOUT: Duration = Duration::from_secs(5);
const LOCK_POLL: Duration = Duration::from_millis(50);
const MAX_REPLAY: u32 = 3;

/// A per-field validation issue. Invalid fields fall back to their default;
/// other fields keep their values (02 §三.4).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ValidationIssue {
    pub field: String,
    pub reason: String,
}

// --- typed sections (02 §三.4 table) ---

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", default)]
pub struct UiSettings {
    /// auto | zh-CN | en-US
    pub language: String,
    /// 0.80..=1.50
    pub font_scale: f64,
    /// system | dark | light (G-04)
    pub theme: String,
    /// User-configured Explorer ignore names (WX-01). Complements the built-in
    /// dependency/build list; matched against a directory/file name at any depth.
    pub explorer_ignore: Vec<String>,
    /// claude | codex | bash | cc-switch — the tab the tab-bar + split button
    /// creates directly (IDEA-1, Windows Terminal-style default profile).
    pub default_tab_agent: String,
    /// IDEA-3 (3f round 3): the workspace-bar `+` default target page.
    /// workspace | settings (future feature pages extend this list).
    pub default_new_page: String,
}

impl Default for UiSettings {
    fn default() -> Self {
        Self {
            language: "auto".into(),
            font_scale: 1.0,
            theme: "system".into(),
            explorer_ignore: Vec::new(),
            default_tab_agent: "bash".into(),
            default_new_page: "workspace".into(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", default)]
pub struct TerminalSettings {
    /// non-empty, <=256 chars
    pub font_family: String,
    /// 10..=24
    pub font_size: u32,
    /// 1.0..=1.6
    pub line_height: f64,
    /// -1..=3
    pub letter_spacing: i32,
    /// 1000..=50000
    pub scrollback: u32,
    /// auto | default | webgl (Workbench addon strategy, not an xterm option)
    pub renderer: String,
    /// 0..=500 ms
    pub smooth_scroll_duration: u32,
}

impl Default for TerminalSettings {
    fn default() -> Self {
        Self {
            // v2.1.8 T2 (D-3): Nerd Font first so yazi/terminal icons work
            // out of the box; machines without it fall through to Cascadia.
            font_family: "JetBrainsMono Nerd Font Mono, JetBrainsMono Nerd Font, Cascadia Mono, Cascadia Code, Consolas, monospace".into(),
            font_size: 14,
            line_height: 1.2,
            letter_spacing: 0,
            scrollback: 5000,
            renderer: "auto".into(),
            smooth_scroll_duration: 100,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", default)]
pub struct WindowGeometry {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub maximized: bool,
}

impl Default for WindowGeometry {
    fn default() -> Self {
        Self {
            x: 0,
            y: 0,
            width: 800,
            height: 600,
            maximized: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", default)]
pub struct WindowSettings {
    pub remember_geometry: bool,
    /// quit | minimize-to-tray
    pub close_behavior: String,
    /// G-10 reads/writes this; schema fixed here so Step 10 only adds commands.
    pub geometry: Option<WindowGeometry>,
}

impl Default for WindowSettings {
    fn default() -> Self {
        Self {
            remember_geometry: true,
            close_behavior: "quit".into(),
            geometry: None,
        }
    }
}

/// Document handed to the frontend (camelCase).
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SettingsDocument {
    pub schema_version: u64,
    pub revision: u64,
    pub aisc_cli_path: Option<String>,
    pub ui: UiSettings,
    pub terminal: TerminalSettings,
    pub window: WindowSettings,
    /// F2 (D-10): host-tools MCP whitelist. EMPTY = the host-exec tool set
    /// is empty and every container call is refused.
    pub host_tools: Vec<crate::host_mcp::HostToolEntry>,
    pub issues: Vec<ValidationIssue>,
    /// On-disk file was corrupt and isolated; app runs on defaults and
    /// nothing is written until the user confirms reset.
    pub corrupted: bool,
    /// On-disk schema_version is newer than supported: read-only.
    pub read_only: bool,
}

/// Section-level GUI patch from the frontend. Omitted sections stay unchanged.
#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct SettingsPatch {
    pub ui: Option<UiSettings>,
    pub terminal: Option<TerminalSettings>,
    pub window: Option<WindowSettings>,
    /// F2: wholesale replacement (an array, not a mergeable section).
    pub host_tools: Option<Vec<crate::host_mcp::HostToolEntry>>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SaveOutcome {
    pub revision: u64,
    pub issues: Vec<ValidationIssue>,
}

#[derive(Debug)]
pub enum SettingsError {
    Io(String),
    /// File exists but is not valid JSON. Isolated to `settings.json.corrupt`.
    Corrupt(String),
    /// File schema_version is missing or unsupported. Original file untouched;
    /// saves are refused (read-only) so a newer Workbench's file survives.
    UnsupportedSchema { found: Option<u64> },
    /// Could not acquire the cross-process lock within the timeout.
    LockTimeout,
    /// `expected_revision` did not match the on-disk revision (concurrent
    /// write). Caller reloads and replays the patch (bounded).
    Conflict { current_revision: u64 },
}

impl std::fmt::Display for SettingsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(m) => write!(f, "settings io error: {m}"),
            Self::Corrupt(m) => write!(f, "settings.json corrupted: {m}"),
            Self::UnsupportedSchema { found } => match found {
                Some(v) => write!(f, "unsupported settings schema_version: {v}"),
                None => write!(f, "settings.json missing schema_version"),
            },
            Self::LockTimeout => write!(f, "settings lock timeout"),
            Self::Conflict { current_revision } => {
                write!(f, "settings revision conflict (current={current_revision})")
            }
        }
    }
}

impl std::error::Error for SettingsError {}

/// Backing store is the raw JSON document so unknown fields survive round-trips.
#[derive(Debug, Clone)]
pub struct Settings {
    raw: Value,
    revision: u64,
    issues: Vec<ValidationIssue>,
    corrupted: bool,
    read_only: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            raw: serde_json::json!({
                "schema_version": SCHEMA_VERSION,
                "revision": 0,
                "aisc_cli_path": null,
            }),
            revision: 0,
            issues: Vec::new(),
            corrupted: false,
            read_only: false,
        }
    }
}

fn default_document() -> SettingsDocument {
    SettingsDocument {
        schema_version: SCHEMA_VERSION,
        revision: 0,
        aisc_cli_path: None,
        ui: UiSettings::default(),
        terminal: TerminalSettings::default(),
        window: WindowSettings::default(),
        host_tools: Vec::new(),
        issues: Vec::new(),
        corrupted: false,
        read_only: false,
    }
}

// --- per-field validation with fallback (02 §三.4) ---

fn issue(field: &str, reason: impl Into<String>) -> ValidationIssue {
    ValidationIssue {
        field: field.into(),
        reason: reason.into(),
    }
}

fn valid_language(v: &Value) -> Option<String> {
    v.as_str().filter(|s| ["auto", "zh-CN", "en-US"].contains(s)).map(String::from)
}

fn valid_theme(v: &Value) -> Option<String> {
    v.as_str().filter(|s| ["system", "dark", "light"].contains(s)).map(String::from)
}

fn valid_tab_agent(v: &Value) -> Option<String> {
    v.as_str()
        .filter(|s| ["claude", "codex", "bash", "cc-switch"].contains(s))
        .map(String::from)
}

fn valid_new_page(v: &Value) -> Option<String> {
    v.as_str()
        .filter(|s| ["workspace", "settings"].contains(s))
        .map(String::from)
}

fn valid_renderer(v: &Value) -> Option<String> {
    v.as_str().filter(|s| ["auto", "default", "webgl"].contains(s)).map(String::from)
}

fn valid_close_behavior(v: &Value) -> Option<String> {
    v.as_str().filter(|s| ["quit", "minimize-to-tray"].contains(s)).map(String::from)
}

fn valid_geometry(v: &Value) -> Option<WindowGeometry> {
    serde_json::from_value::<WindowGeometry>(v.clone()).ok()
}

fn validate_ui(raw: &Value) -> (UiSettings, Vec<ValidationIssue>) {
    let mut out = UiSettings::default();
    let mut issues = Vec::new();
    let sec = raw.get("ui");
    if let Some(sec) = sec {
        if let Some(lang) = sec.get("language").and_then(valid_language) {
            out.language = lang;
        } else if sec.get("language").is_some() {
            issues.push(issue("ui.language", "非法值，回退 auto（合法：auto|zh-CN|en-US）"));
        }
        if let Some(s) = sec.get("font_scale").and_then(|v| v.as_f64()) {
            if (0.80..=1.50).contains(&s) {
                out.font_scale = s;
            } else {
                issues.push(issue("ui.font_scale", "超出 0.80..1.50，回退 1.0"));
            }
        } else if sec.get("font_scale").is_some() {
            issues.push(issue("ui.font_scale", "非法类型，回退 1.0"));
        }
        if let Some(t) = sec.get("theme").and_then(valid_theme) {
            out.theme = t;
        } else if sec.get("theme").is_some() {
            issues.push(issue("ui.theme", "非法值，回退 system（合法：system|dark|light）"));
        }
        if let Some(list) = sec.get("explorer_ignore") {
            if let Some(names) = list.as_array() {
                for item in names {
                    if let Some(name) = item.as_str() {
                        let name = name.trim();
                        if valid_ignore_name(name) && !out.explorer_ignore.iter().any(|x| x == name) {
                            out.explorer_ignore.push(name.to_string());
                        }
                    }
                    // invalid entries (empty, path-like, NUL, too long, dupes)
                    // are silently dropped — the safe fallback is "not ignored".
                }
            } else {
                issues.push(issue("ui.explorer_ignore", "非法类型，回退空列表"));
            }
        }
        if let Some(a) = sec.get("default_tab_agent").and_then(valid_tab_agent) {
            out.default_tab_agent = a;
        } else if sec.get("default_tab_agent").is_some() {
            issues.push(issue(
                "ui.default_tab_agent",
                "非法值，回退 bash（合法：claude|codex|bash|cc-switch）",
            ));
        }
        if let Some(a) = sec.get("default_new_page").and_then(valid_new_page) {
            out.default_new_page = a;
        } else if sec.get("default_new_page").is_some() {
            issues.push(issue(
                "ui.default_new_page",
                "非法值，回退 workspace（合法：workspace|settings）",
            ));
        }
    }
    (out, issues)
}

/// A valid Explorer ignore entry: a bare name — no `/`, `\`, NUL, leading
/// dot-empty, `.`/`..`, and bounded length. Path-like entries are rejected so
/// the ignore can never hide a whole subtree by accident (R3-04).
fn valid_ignore_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name != "."
        && name != ".."
        && !name.contains('/')
        && !name.contains('\\')
        && !name.contains('\0')
}

fn validate_terminal(raw: &Value) -> (TerminalSettings, Vec<ValidationIssue>) {
    let mut out = TerminalSettings::default();
    let mut issues = Vec::new();
    let sec = raw.get("terminal");
    if let Some(sec) = sec {
        if let Some(f) = sec.get("font_family").and_then(|v| v.as_str()) {
            let t = f.trim();
            if !t.is_empty() && t.chars().count() <= 256 {
                out.font_family = t.to_string();
            } else {
                issues.push(issue("terminal.font_family", "非法值，回退默认字体（非空 ≤256 字符）"));
            }
        } else if sec.get("font_family").is_some() {
            issues.push(issue("terminal.font_family", "非法类型，回退默认字体"));
        }
        if let Some(v) = sec.get("font_size").and_then(|v| v.as_u64()) {
            if (10..=24).contains(&v) {
                out.font_size = v as u32;
            } else {
                issues.push(issue("terminal.font_size", "超出 10..24，回退 14"));
            }
        } else if sec.get("font_size").is_some() {
            issues.push(issue("terminal.font_size", "非法类型，回退 14"));
        }
        if let Some(v) = sec.get("line_height").and_then(|v| v.as_f64()) {
            if (1.0..=1.6).contains(&v) {
                out.line_height = v;
            } else {
                issues.push(issue("terminal.line_height", "超出 1.0..1.6，回退 1.2"));
            }
        } else if sec.get("line_height").is_some() {
            issues.push(issue("terminal.line_height", "非法类型，回退 1.2"));
        }
        if let Some(v) = sec.get("letter_spacing").and_then(|v| v.as_i64()) {
            if (-1..=3).contains(&v) {
                out.letter_spacing = v as i32;
            } else {
                issues.push(issue("terminal.letter_spacing", "超出 -1..3，回退 0"));
            }
        } else if sec.get("letter_spacing").is_some() {
            issues.push(issue("terminal.letter_spacing", "非法类型，回退 0"));
        }
        if let Some(v) = sec.get("scrollback").and_then(|v| v.as_u64()) {
            if (1000..=50_000).contains(&v) {
                out.scrollback = v as u32;
            } else {
                issues.push(issue("terminal.scrollback", "超出 1000..50000，回退 5000"));
            }
        } else if sec.get("scrollback").is_some() {
            issues.push(issue("terminal.scrollback", "非法类型，回退 5000"));
        }
        if let Some(r) = sec.get("renderer").and_then(valid_renderer) {
            out.renderer = r;
        } else if sec.get("renderer").is_some() {
            issues.push(issue("terminal.renderer", "非法值，回退 auto（合法：auto|default|webgl）"));
        }
        if let Some(v) = sec.get("smooth_scroll_duration").and_then(|v| v.as_u64()) {
            if v <= 500 {
                out.smooth_scroll_duration = v as u32;
            } else {
                issues.push(issue("terminal.smooth_scroll_duration", "超出 0..500，回退 100"));
            }
        } else if sec.get("smooth_scroll_duration").is_some() {
            issues.push(issue("terminal.smooth_scroll_duration", "非法类型，回退 100"));
        }
    }
    (out, issues)
}

fn validate_window(raw: &Value) -> (WindowSettings, Vec<ValidationIssue>) {
    let mut out = WindowSettings::default();
    let mut issues = Vec::new();
    let sec = raw.get("window");
    if let Some(sec) = sec {
        if let Some(v) = sec.get("remember_geometry").and_then(|v| v.as_bool()) {
            out.remember_geometry = v;
        } else if sec.get("remember_geometry").is_some() {
            issues.push(issue("window.remember_geometry", "非法类型，回退 true"));
        }
        if let Some(c) = sec.get("close_behavior").and_then(valid_close_behavior) {
            out.close_behavior = c;
        } else if sec.get("close_behavior").is_some() {
            issues.push(issue("window.close_behavior", "非法值，回退 quit（合法：quit|minimize-to-tray）"));
        }
        match sec.get("geometry") {
            // Explicit null = no saved record (G-10), not an error.
            Some(g) if g.is_null() => {}
            Some(g) => match valid_geometry(g) {
                Some(geo) => out.geometry = Some(geo),
                None => issues.push(issue("window.geometry", "非法结构，按无记录处理")),
            },
            None => {}
        }
    }
    (out, issues)
}

impl Settings {
    /// Load from `dir/settings.json`. Missing file -> default. Corrupt JSON ->
    /// isolate to `settings.json.corrupt` and return defaults (nothing written).
    /// Unsupported schema -> `UnsupportedSchema` (caller must not overwrite).
    pub fn load(dir: &Path) -> Result<Self, SettingsError> {
        let path = dir.join(SETTINGS_FILE);
        match fs::read(&path) {
            Ok(bytes) => match serde_json::from_slice::<Value>(&bytes) {
                Ok(raw) => {
                    let found = raw.get("schema_version").and_then(|v| v.as_u64());
                    if found != Some(SCHEMA_VERSION) {
                        return Err(SettingsError::UnsupportedSchema { found });
                    }
                    let mut s = Self {
                        raw,
                        revision: 0,
                        issues: Vec::new(),
                        corrupted: false,
                        read_only: false,
                    };
                    s.validate();
                    Ok(s)
                }
                Err(e) => {
                    // Isolate the corrupt file so a fresh default can be
                    // written only on an explicit reset (02 §三.4).
                    let _ = fs::rename(&path, dir.join(format!("{SETTINGS_FILE}{CORRUPT_SUFFIX}")));
                    Err(SettingsError::Corrupt(e.to_string()))
                }
            },
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(Self::default()),
            Err(e) => Err(SettingsError::Io(e.to_string())),
        }
    }

    /// Re-validate all typed sections from `raw` (field-level fallback).
    fn validate(&mut self) {
        self.revision = self.raw.get("revision").and_then(|v| v.as_u64()).unwrap_or(0);
        let mut issues = Vec::new();
        let (ui, i) = validate_ui(&self.raw);
        issues.extend(i);
        let (terminal, i) = validate_terminal(&self.raw);
        issues.extend(i);
        let (window, i) = validate_window(&self.raw);
        issues.extend(i);
        // Merge validated values into the raw doc - the saved document must
        // carry BOTH the typed (fallback-applied) values AND unknown subfields
        // (A-INFRA-5). Plain replacement would drop unknowns.
        self.raw["ui"] = merge_section(self.raw.get("ui"), &ui);
        self.raw["terminal"] = merge_section(self.raw.get("terminal"), &terminal);
        self.raw["window"] = merge_section(self.raw.get("window"), &window);
        self.issues = issues;
    }

    /// Frontend document (validated sections + meta). Read-only mode is only
    /// reachable for unsupported schema, which `load` rejects; callers that
    /// must surface it build the document themselves.
    pub fn document(&self) -> SettingsDocument {
        SettingsDocument {
            schema_version: SCHEMA_VERSION,
            revision: self.revision,
            aisc_cli_path: self.aisc_cli_path().map(String::from),
            ui: serde_json::from_value(self.raw.get("ui").cloned().unwrap_or(Value::Null))
                .unwrap_or_default(),
            terminal: serde_json::from_value(
                self.raw.get("terminal").cloned().unwrap_or(Value::Null),
            )
            .unwrap_or_default(),
            window: serde_json::from_value(self.raw.get("window").cloned().unwrap_or(Value::Null))
                .unwrap_or_default(),
            host_tools: sanitize_host_tools(self.raw.get("host_tools")),
            issues: self.issues.clone(),
            corrupted: self.corrupted,
            read_only: self.read_only,
        }
    }

    pub fn aisc_cli_path(&self) -> Option<&str> {
        self.raw
            .get("aisc_cli_path")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
    }

    pub fn set_aisc_cli_path(&mut self, path: Option<&str>) {
        match path {
            Some(p) => {
                self.raw["aisc_cli_path"] = Value::String(p.to_string());
            }
            None => {
                self.raw["aisc_cli_path"] = Value::Null;
            }
        }
    }

    /// Deep-merge a GUI section patch over the raw document, then re-validate.
    /// Unknown fields (top-level and inside sections) survive (A-INFRA-5).
    pub fn apply_gui_patch(&mut self, patch: &SettingsPatch) {
        if let Some(s) = &patch.ui {
            self.raw["ui"] = merge_section(self.raw.get("ui"), s);
        }
        if let Some(s) = &patch.terminal {
            self.raw["terminal"] = merge_section(self.raw.get("terminal"), s);
        }
        if let Some(s) = &patch.window {
            self.raw["window"] = merge_section(self.raw.get("window"), s);
        }
        if let Some(entries) = &patch.host_tools {
            // F2: an array node — wholesale replacement (entries are
            // sanitized through the same read path).
            let encoded = serde_json::to_value(entries).unwrap_or(Value::Array(Vec::new()));
            let cleaned = sanitize_host_tools(Some(&encoded));
            self.raw["host_tools"] =
                serde_json::to_value(&cleaned).unwrap_or(Value::Array(Vec::new()));
        }
        self.validate();
    }

    /// Reset GUI sections to defaults; `aisc_cli_path`, history, workspace and
    /// Runtime are untouched (A-G01-4). Unknown subfields of a section survive
    /// the reset (A-INFRA-5).
    pub fn reset_gui(&mut self) {
        self.apply_gui_patch(&SettingsPatch {
            ui: Some(UiSettings::default()),
            terminal: Some(TerminalSettings::default()),
            window: Some(WindowSettings::default()),
            host_tools: None, // F2: the whitelist is NOT GUI décor — reset never clears it
        });
    }

    /// Atomically write to `dir/settings.json` (temp + fsync + replace) under
    /// the cross-process lock, bumping `revision` so GUI saves can detect
    /// concurrent writers. Does not check `expected_revision` (pin writes are
    /// single-window startup operations; GUI saves use `save_patch`).
    pub fn save(&self, dir: &Path) -> Result<(), SettingsError> {
        let lock_file = acquire_lock(dir)?;
        let mut s = self.clone();
        s.revision += 1;
        let result = s.save_locked(dir);
        let _ = lock_file.unlock();
        result
    }

    /// Write the raw doc exactly as-is (caller has already bumped `revision`).
    fn save_locked(&self, dir: &Path) -> Result<(), SettingsError> {
        fs::create_dir_all(dir).map_err(|e| SettingsError::Io(e.to_string()))?;
        let mut raw = self.raw.clone();
        raw["schema_version"] = Value::from(SCHEMA_VERSION);
        raw["revision"] = Value::from(self.revision);
        let bytes = serde_json::to_vec_pretty(&raw)
            .map_err(|e| SettingsError::Corrupt(e.to_string()))?;
        storage::atomic_replace(&dir.join(SETTINGS_FILE), &bytes)
            .map_err(|e| SettingsError::Io(e.to_string()))
    }
}

/// F2: whitelist sanitation on read — every entry needs a non-empty name +
/// program and a known read-only preset (unknown presets are dropped to
/// None-but-kept? No: dropped ENTIRELY — an unknown preset would silently
/// widen what "read-only" gates).
fn sanitize_host_tools(v: Option<&Value>) -> Vec<crate::host_mcp::HostToolEntry> {
    let mut out = Vec::new();
    let Some(arr) = v.and_then(Value::as_array) else {
        return out;
    };
    for item in arr {
        let Ok(entry) = serde_json::from_value::<crate::host_mcp::HostToolEntry>(item.clone())
        else {
            continue;
        };
        if entry.name.trim().is_empty() || entry.program.trim().is_empty() {
            continue;
        }
        match entry.read_only_preset.as_deref() {
            None | Some(crate::host_mcp::GIT_RO_PRESET) => out.push(entry),
            Some(_) => continue,
        }
    }
    out
}

/// Merge a typed section into the raw section, keeping unknown subfields.
fn merge_section(old: Option<&Value>, typed: &impl Serialize) -> Value {
    let mut out = serde_json::to_value(typed).unwrap_or(Value::Object(Default::default()));
    if let (Some(old_obj), Some(out_obj)) = (old.and_then(|v| v.as_object()), out.as_object_mut()) {
        // Old unknown keys (not present in the typed struct) survive.
        for (k, v) in old_obj {
            if !out_obj.contains_key(k) {
                out_obj.insert(k.clone(), v.clone());
            }
        }
    }
    out
}

/// Save a GUI patch under the cross-process lock: reload on-disk, verify
/// `expected_revision`, deep-merge, re-validate, bump revision, atomic write.
/// Returns `Conflict` when the on-disk revision moved (caller replays).
pub fn save_patch(
    dir: &Path,
    expected_revision: u64,
    patch: &SettingsPatch,
) -> Result<SaveOutcome, SettingsError> {
    let lock_file = acquire_lock(dir)?;
    let result = save_patch_locked(dir, expected_revision, patch);
    let _ = lock_file.unlock();
    result
}

/// Same as `save_patch` but the GUI sections are replaced with defaults
/// (reset). `aisc_cli_path` and unknown fields survive.
pub fn reset_gui_locked(
    dir: &Path,
    expected_revision: u64,
) -> Result<SaveOutcome, SettingsError> {
    let lock_file = acquire_lock(dir)?;
    let result = reset_locked(dir, expected_revision);
    let _ = lock_file.unlock();
    result
}

fn save_patch_locked(
    dir: &Path,
    expected_revision: u64,
    patch: &SettingsPatch,
) -> Result<SaveOutcome, SettingsError> {
    fs::create_dir_all(dir).map_err(|e| SettingsError::Io(e.to_string()))?;
    let mut s = load_disk(dir)?;
    if s.revision != expected_revision {
        return Err(SettingsError::Conflict {
            current_revision: s.revision,
        });
    }
    s.apply_gui_patch(patch);
    let issues = s.issues.clone();
    s.revision += 1;
    let revision = s.revision;
    s.save_locked(dir)?;
    Ok(SaveOutcome { revision, issues })
}

fn reset_locked(dir: &Path, expected_revision: u64) -> Result<SaveOutcome, SettingsError> {
    fs::create_dir_all(dir).map_err(|e| SettingsError::Io(e.to_string()))?;
    let mut s = load_disk(dir)?;
    if s.revision != expected_revision {
        return Err(SettingsError::Conflict {
            current_revision: s.revision,
        });
    }
    s.reset_gui();
    let issues = s.issues.clone();
    s.revision += 1;
    let revision = s.revision;
    s.save_locked(dir)?;
    Ok(SaveOutcome { revision, issues })
}

/// Load the on-disk doc for an in-lock save: missing -> default, corrupt ->
/// isolate + default, unsupported schema -> error (read-only, refused).
fn load_disk(dir: &Path) -> Result<Settings, SettingsError> {
    match Settings::load(dir) {
        Ok(mut s) => {
            s.corrupted = false;
            Ok(s)
        }
        Err(SettingsError::Corrupt(_)) => Ok(Settings::default()), // already isolated
        Err(e) => Err(e),
    }
}

fn acquire_lock(dir: &Path) -> Result<fs::File, SettingsError> {
    fs::create_dir_all(dir).map_err(|e| SettingsError::Io(e.to_string()))?;
    let lock_path = dir.join(LOCK_FILE);
    let lock_file = fs::OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .open(&lock_path)
        .map_err(|e| SettingsError::Io(e.to_string()))?;
    let deadline = Instant::now() + LOCK_TIMEOUT;
    loop {
        match lock_file.try_lock_exclusive() {
            Ok(true) => return Ok(lock_file),
            Ok(false) => {
                if Instant::now() >= deadline {
                    return Err(SettingsError::LockTimeout);
                }
                std::thread::sleep(LOCK_POLL);
            }
            Err(e) => return Err(SettingsError::Io(e.to_string())),
        }
    }
}

/// Replay a save on revision conflict, bounded by `MAX_REPLAY` (02 §三.4).
/// Returns the outcome or the final conflict after exhausting retries.
pub fn save_with_replay(
    dir: &Path,
    expected_revision: u64,
    patch: &SettingsPatch,
) -> Result<SaveOutcome, SettingsError> {
    let mut expected = expected_revision;
    let mut last_conflict = None;
    for _ in 0..=MAX_REPLAY {
        match save_patch(dir, expected, patch) {
            Ok(outcome) => return Ok(outcome),
            Err(SettingsError::Conflict { current_revision }) => {
                expected = current_revision;
                last_conflict = Some(current_revision);
            }
            Err(e) => return Err(e),
        }
    }
    Err(SettingsError::Conflict {
        current_revision: last_conflict.unwrap_or(expected),
    })
}

/// Reset with the same bounded replay.
pub fn reset_with_replay(
    dir: &Path,
    expected_revision: u64,
) -> Result<SaveOutcome, SettingsError> {
    let mut expected = expected_revision;
    let mut last_conflict = None;
    for _ in 0..=MAX_REPLAY {
        match reset_gui_locked(dir, expected) {
            Ok(outcome) => return Ok(outcome),
            Err(SettingsError::Conflict { current_revision }) => {
                expected = current_revision;
                last_conflict = Some(current_revision);
            }
            Err(e) => return Err(e),
        }
    }
    Err(SettingsError::Conflict {
        current_revision: last_conflict.unwrap_or(expected),
    })
}

// --- Tauri commands ---

/// Load settings for the frontend. Corrupt file: defaults + `corrupted` flag
/// (already isolated). Unsupported schema: defaults + `read_only` (file left
/// untouched, saves refused).
pub fn load_settings_document(dir: &Path) -> Result<SettingsDocument, SettingsError> {
    match Settings::load(dir) {
        Ok(s) => Ok(s.document()),
        Err(SettingsError::Corrupt(_)) => {
            let mut doc = default_document();
            doc.corrupted = true;
            Ok(doc)
        }
        Err(SettingsError::UnsupportedSchema { .. }) => {
            let mut doc = default_document();
            doc.read_only = true;
            Ok(doc)
        }
        Err(e) => Err(e),
    }
}

/// Save a GUI patch with bounded conflict replay. Read-only documents (newer
/// schema on disk) refuse to save, carrying the original error.
pub fn save_settings_document(
    dir: &Path,
    expected_revision: u64,
    patch: &SettingsPatch,
) -> Result<SaveOutcome, SettingsError> {
    match Settings::load(dir) {
        Err(e @ SettingsError::UnsupportedSchema { .. }) => Err(e),
        _ => save_with_replay(dir, expected_revision, patch),
    }
}

/// Reset GUI settings with bounded conflict replay. Read-only refuses.
pub fn reset_settings_document(
    dir: &Path,
    expected_revision: u64,
) -> Result<SaveOutcome, SettingsError> {
    match Settings::load(dir) {
        Err(e @ SettingsError::UnsupportedSchema { .. }) => Err(e),
        _ => reset_with_replay(dir, expected_revision),
    }
}

/// Map a settings error to the frontend contract. Conflicts are retryable;
/// everything else is a generic settings error with detail.
pub fn map_settings_error(e: SettingsError) -> WorkbenchError {
    match e {
        SettingsError::Conflict { current_revision } => WorkbenchError::settings_conflict()
            .with_detail(format!("settings revision conflict (current={current_revision})")),
        other => WorkbenchError::settings_error().with_detail(other.to_string()),
    }
}

// --- Tauri commands (Step 3: typed settings shell; G-01 wiring lands in Step 7) ---

#[tauri::command]
pub async fn load_settings(app: AppHandle) -> Result<SettingsDocument, WorkbenchError> {
    let dir = crate::session::config_dir(&app)?;
    let doc = load_settings_document(&dir).map_err(map_settings_error)?;
    sync_host_mcp_whitelist(&app, &doc);
    Ok(doc)
}

#[tauri::command]
pub async fn save_settings(
    app: AppHandle,
    expected_revision: u64,
    patch: SettingsPatch,
) -> Result<SaveOutcome, WorkbenchError> {
    let dir = crate::session::config_dir(&app)?;
    let outcome = save_settings_document(&dir, expected_revision, &patch).map_err(map_settings_error)?;
    // F2: keep the live host-tools MCP whitelist in lockstep with settings.
    if let Ok(doc) = load_settings_document(&dir) {
        sync_host_mcp_whitelist(&app, &doc);
    }
    Ok(outcome)
}

/// Push the sanitized whitelist into the host MCP executor state (no-op when
/// the service is unavailable — the tool set just stays as it was).
fn sync_host_mcp_whitelist(app: &AppHandle, doc: &SettingsDocument) {
    use tauri::Manager;
    if let Some(state) = app.try_state::<std::sync::Arc<crate::host_mcp::HostMcpState>>() {
        state.set_whitelist(doc.host_tools.clone());
    }
}

#[tauri::command]
pub async fn reset_gui_settings(
    app: AppHandle,
    expected_revision: u64,
) -> Result<SaveOutcome, WorkbenchError> {
    let dir = crate::session::config_dir(&app)?;
    reset_settings_document(&dir, expected_revision).map_err(map_settings_error)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn raw_doc() -> Value {
        serde_json::json!({
            "schema_version": 1,
            "revision": 0,
            "aisc_cli_path": null,
            "ui": { "language": "auto", "font_scale": 1.0, "theme": "system", "default_tab_agent": "bash", "default_new_page": "workspace" },
            "terminal": {
                "font_family": "JetBrainsMono Nerd Font Mono, JetBrainsMono Nerd Font, Cascadia Mono, Cascadia Code, Consolas, monospace",
                "font_size": 14, "line_height": 1.2, "letter_spacing": 0,
                "scrollback": 5000, "renderer": "auto", "smooth_scroll_duration": 100
            },
            "window": { "remember_geometry": true, "close_behavior": "quit", "geometry": null }
        })
    }

    fn write(dir: &Path, doc: &Value) {
        fs::write(dir.join(SETTINGS_FILE), serde_json::to_vec(doc).unwrap()).unwrap();
    }

    #[test]
    fn load_missing_file_yields_defaults() {
        let dir = tempdir().unwrap();
        let s = Settings::load(dir.path()).unwrap();
        let doc = s.document();
        assert_eq!(doc.schema_version, SCHEMA_VERSION);
        assert_eq!(doc.revision, 0);
        assert_eq!(doc.aisc_cli_path, None);
        assert_eq!(doc.ui.language, "auto");
        assert_eq!(doc.ui.font_scale, 1.0);
        assert_eq!(doc.terminal.font_size, 14);
        assert_eq!(doc.terminal.scrollback, 5000);
        assert_eq!(doc.window.close_behavior, "quit");
        assert!(doc.window.geometry.is_none());
        assert!(doc.issues.is_empty());
    }

    #[test]
    fn round_trip_gui_fields_and_pin() {
        let dir = tempdir().unwrap();
        let mut s = Settings::load(dir.path()).unwrap();
        s.set_aisc_cli_path(Some("C:\\bin\\aisc.exe"));
        s.apply_gui_patch(&SettingsPatch {
            terminal: Some(TerminalSettings {
                font_size: 16,
                scrollback: 20000,
                renderer: "webgl".into(),
                ..TerminalSettings::default()
            }),
            ..Default::default()
        });
        s.save(dir.path()).unwrap();

        let loaded = Settings::load(dir.path()).unwrap();
        let doc = loaded.document();
        assert_eq!(doc.aisc_cli_path.as_deref(), Some("C:\\bin\\aisc.exe"));
        assert_eq!(doc.terminal.font_size, 16);
        assert_eq!(doc.terminal.scrollback, 20000);
        assert_eq!(doc.terminal.renderer, "webgl");
        assert_eq!(doc.terminal.font_family, TerminalSettings::default().font_family);
        assert!(doc.issues.is_empty());
    }

    /// REL-03: a settings.json written by a PREVIOUS release (same schema 1,
    /// missing the newer optional fields) must load with defaults and round-trip
    /// the unknowns — upgrade keeps the user's pin and any future fields.
    #[test]
    fn previous_version_settings_load_with_defaults_and_keep_pin() {
        let dir = tempdir().unwrap();
        // "Previous" shape: no ui.explorer_ignore / ui.theme / window.geometry,
        // but carries the pinned CLI path and an unknown future field.
        let prev = serde_json::json!({
            "schema_version": 1,
            "revision": 3,
            "aisc_cli_path": "C:\\prev\\aisc.exe",
            "ui": { "language": "zh-CN", "font_scale": 1.2 },
            "terminal": { "font_size": 16 },
            "window": { "remember_geometry": true, "close_behavior": "quit" },
            "future_top_field": "kept"
        });
        write(dir.path(), &prev);

        let s = Settings::load(dir.path()).unwrap();
        // Newer optional fields default in.
        assert_eq!(s.aisc_cli_path(), Some("C:\\prev\\aisc.exe"));
        assert_eq!(s.document().ui.explorer_ignore, Vec::<String>::new());
        assert_eq!(s.document().ui.theme, UiSettings::default().theme);
        assert_eq!(s.document().ui.default_tab_agent, "bash");
        assert!(s.document().window.geometry.is_none());
        // Unknowns survive a save (round-trip keeps them for a future rollback).
        let mut s = s;
        s.save(dir.path()).unwrap();
        let reloaded = Settings::load(dir.path()).unwrap();
        assert_eq!(reloaded.document().ui.language, "zh-CN");
        assert_eq!(reloaded.document().terminal.font_size, 16);
        assert_eq!(reloaded.aisc_cli_path(), Some("C:\\prev\\aisc.exe"));
        assert!(reloaded.raw.get("future_top_field").is_some());
    }

    #[test]
    fn unknown_fields_preserved_through_patch_and_pin_saves() {
        let dir = tempdir().unwrap();
        let mut doc = raw_doc();
        doc["custom_future_field"] = Value::Number(42.into());
        doc["ui"]["future_ui_flag"] = Value::Bool(true);
        write(dir.path(), &doc);

        let mut s = Settings::load(dir.path()).unwrap();
        s.apply_gui_patch(&SettingsPatch {
            ui: Some(UiSettings { language: "en-US".into(), ..UiSettings::default() }),
            ..Default::default()
        });
        s.save(dir.path()).unwrap();

        let loaded = Settings::load(dir.path()).unwrap();
        assert_eq!(loaded.raw.get("custom_future_field").and_then(|v| v.as_u64()), Some(42));
        assert_eq!(
            loaded.raw.get("ui").and_then(|v| v.get("future_ui_flag")).and_then(|v| v.as_bool()),
            Some(true)
        );
        let doc = loaded.document();
        assert_eq!(doc.ui.language, "en-US");
    }

    #[test]
    fn theme_invalid_falls_back_to_system_valid_accepted() {
        let dir = tempdir().unwrap();
        let mut doc = raw_doc();
        doc["ui"]["theme"] = Value::String("neon".into());
        write(dir.path(), &doc);
        let s = Settings::load(dir.path()).unwrap();
        let d = s.document();
        assert_eq!(d.ui.theme, "system");
        assert!(d.issues.iter().any(|i| i.field == "ui.theme"));

        let mut ok = raw_doc();
        ok["ui"]["theme"] = Value::String("light".into());
        write(dir.path(), &ok);
        let s2 = Settings::load(dir.path()).unwrap();
        assert_eq!(s2.document().ui.theme, "light");
        assert!(s2.document().issues.is_empty());
    }

    #[test]
    fn default_tab_agent_valid_accepted_invalid_falls_back() {
        let dir = tempdir().unwrap();
        let mut doc = raw_doc();
        doc["ui"]["default_tab_agent"] = Value::String("cc-switch".into());
        write(dir.path(), &doc);
        let s = Settings::load(dir.path()).unwrap();
        let d = s.document();
        assert_eq!(d.ui.default_tab_agent, "cc-switch");
        assert!(d.issues.is_empty());

        // A patch save round-trips a different valid agent (and reports no issue).
        let mut s = s;
        s.apply_gui_patch(&SettingsPatch {
            ui: Some(UiSettings {
                default_tab_agent: "codex".into(),
                ..UiSettings::default()
            }),
            ..Default::default()
        });
        assert!(s.issues.iter().all(|i| i.field != "ui.default_tab_agent"));
        s.save(dir.path()).unwrap();
        let reloaded = Settings::load(dir.path()).unwrap();
        assert_eq!(reloaded.document().ui.default_tab_agent, "codex");

        let mut bad = raw_doc();
        bad["ui"]["default_tab_agent"] = Value::String("powershell".into());
        write(dir.path(), &bad);
        let s2 = Settings::load(dir.path()).unwrap();
        let d2 = s2.document();
        assert_eq!(d2.ui.default_tab_agent, "bash");
        assert!(d2.issues.iter().any(|i| i.field == "ui.default_tab_agent"));
    }

    #[test]
    fn default_new_page_valid_accepted_invalid_falls_back() {
        let dir = tempdir().unwrap();
        let mut doc = raw_doc();
        doc["ui"]["default_new_page"] = Value::String("settings".into());
        write(dir.path(), &doc);
        let s = Settings::load(dir.path()).unwrap();
        assert_eq!(s.document().ui.default_new_page, "settings");
        assert!(s.document().issues.is_empty());

        let mut bad = raw_doc();
        bad["ui"]["default_new_page"] = Value::String("terminal".into());
        write(dir.path(), &bad);
        let s2 = Settings::load(dir.path()).unwrap();
        assert_eq!(s2.document().ui.default_new_page, "workspace");
        assert!(s2
            .document()
            .issues
            .iter()
            .any(|i| i.field == "ui.default_new_page"));
    }

    #[test]
    fn explorer_ignore_parses_valid_names_and_drops_path_like_ones() {
        let dir = tempdir().unwrap();
        let mut doc = raw_doc();
        doc["ui"]["explorer_ignore"] = serde_json::json!([
            "scratch",
            "vendor/out",   // path-like -> dropped silently
            "",
            "..",
            "build",        // built-in name is still accepted (dup harmless)
            "scratch",      // dup -> deduped
            "a/b",
            "cache",
        ]);
        write(dir.path(), &doc);
        let s = Settings::load(dir.path()).unwrap();
        let d = s.document();
        assert_eq!(
            d.ui.explorer_ignore,
            vec!["scratch", "build", "cache"]
        );
        // Path-like/empty/dot entries are silently dropped, no issue noise.
        assert!(d.issues.iter().all(|i| i.field != "ui.explorer_ignore"));
    }

    #[test]
    fn explorer_ignore_wrong_type_falls_back_empty_with_issue() {
        let dir = tempdir().unwrap();
        let mut doc = raw_doc();
        doc["ui"]["explorer_ignore"] = Value::String("scratch".into());
        write(dir.path(), &doc);
        let s = Settings::load(dir.path()).unwrap();
        let d = s.document();
        assert!(d.ui.explorer_ignore.is_empty());
        assert!(d.issues.iter().any(|i| i.field == "ui.explorer_ignore"));
    }

    #[test]
    fn invalid_fields_fall_back_per_field_others_kept() {
        let dir = tempdir().unwrap();
        let mut doc = raw_doc();
        doc["ui"]["language"] = Value::String("fr-FR".into());
        doc["ui"]["font_scale"] = Value::from(3.5);
        doc["terminal"]["font_size"] = Value::Number(99.into());
        doc["terminal"]["line_height"] = Value::String("high".into());
        doc["terminal"]["scrollback"] = Value::Number(5.into());
        doc["terminal"]["renderer"] = Value::String("canvas".into());
        doc["window"]["close_behavior"] = Value::String("hide".into());
        doc["terminal"]["smooth_scroll_duration"] = Value::Number(9999.into());
        write(dir.path(), &doc);

        let s = Settings::load(dir.path()).unwrap();
        let doc = s.document();
        assert_eq!(doc.ui.language, "auto");
        assert_eq!(doc.ui.font_scale, 1.0);
        assert_eq!(doc.terminal.font_size, 14);
        assert_eq!(doc.terminal.line_height, 1.2);
        assert_eq!(doc.terminal.scrollback, 5000);
        assert_eq!(doc.terminal.renderer, "auto");
        assert_eq!(doc.window.close_behavior, "quit");
        assert_eq!(doc.terminal.smooth_scroll_duration, 100);
        // Valid fields survive alongside the fallbacks.
        assert_eq!(doc.terminal.font_family, TerminalSettings::default().font_family);
        assert_eq!(doc.window.remember_geometry, true);
        assert_eq!(doc.issues.len(), 8);
        assert!(doc.issues.iter().any(|i| i.field == "terminal.font_size"));
        assert!(doc.issues.iter().any(|i| i.field == "ui.language"));
    }

    #[test]
    fn bounds_min_max_accepted() {
        let dir = tempdir().unwrap();
        let mut doc = raw_doc();
        doc["terminal"]["font_size"] = Value::Number(10.into());
        doc["terminal"]["scrollback"] = Value::Number(50000.into());
        doc["terminal"]["letter_spacing"] = Value::Number((-1).into());
        doc["ui"]["font_scale"] = Value::from(1.5);
        doc["terminal"]["smooth_scroll_duration"] = Value::Number(500.into());
        write(dir.path(), &doc);
        let s = Settings::load(dir.path()).unwrap();
        let d = s.document();
        assert_eq!(d.terminal.font_size, 10);
        assert_eq!(d.terminal.scrollback, 50000);
        assert_eq!(d.terminal.letter_spacing, -1);
        assert_eq!(d.ui.font_scale, 1.5);
        assert_eq!(d.terminal.smooth_scroll_duration, 500);
        assert!(d.issues.is_empty());
    }

    #[test]
    fn corrupt_json_isolated_not_overwritten() {
        let dir = tempdir().unwrap();
        fs::write(dir.path().join(SETTINGS_FILE), b"{not json").unwrap();
        let doc = load_settings_document(dir.path()).unwrap();
        assert!(doc.corrupted);
        assert_eq!(doc.ui.language, "auto");
        // Original file moved aside, no default written yet.
        assert!(!dir.path().join(SETTINGS_FILE).exists());
        assert!(dir.path().join(format!("{SETTINGS_FILE}{CORRUPT_SUFFIX}")).exists());
    }

    #[test]
    fn unsupported_schema_read_only_file_untouched() {
        let dir = tempdir().unwrap();
        let bad = serde_json::json!({"schema_version": 999, "aisc_cli_path": "/x"});
        write(dir.path(), &bad);
        let doc = load_settings_document(dir.path()).unwrap();
        assert!(doc.read_only);
        // Saves refused.
        assert!(save_settings_document(dir.path(), 0, &SettingsPatch::default()).is_err());
        assert!(reset_settings_document(dir.path(), 0).is_err());
        let on_disk: Value =
            serde_json::from_slice(&fs::read(dir.path().join(SETTINGS_FILE)).unwrap()).unwrap();
        assert_eq!(on_disk.get("schema_version").and_then(|v| v.as_u64()), Some(999));
    }

    #[test]
    fn save_patch_conflict_and_replay() {
        let dir = tempdir().unwrap();
        // Seed revision 1 (one save).
        let mut s = Settings::load(dir.path()).unwrap();
        s.set_aisc_cli_path(Some("/x/aisc"));
        s.save(dir.path()).unwrap();
        assert_eq!(Settings::load(dir.path()).unwrap().revision, 1);

        // Stale expectation -> conflict; replay with the fresh revision wins.
        let patch = SettingsPatch {
            ui: Some(UiSettings { language: "en-US".into(), ..UiSettings::default() }),
            ..Default::default()
        };
        assert!(matches!(
            save_patch(dir.path(), 0, &patch),
            Err(SettingsError::Conflict { current_revision: 1 })
        ));
        let outcome = save_patch(dir.path(), 1, &patch).unwrap();
        assert_eq!(outcome.revision, 2);
        assert!(outcome.issues.is_empty());
        assert_eq!(Settings::load(dir.path()).unwrap().document().ui.language, "en-US");
    }

    #[test]
    fn save_with_replay_converges_on_stale_expectation() {
        let dir = tempdir().unwrap();
        let mut s = Settings::load(dir.path()).unwrap();
        s.set_aisc_cli_path(Some("/x/aisc"));
        s.save(dir.path()).unwrap();
        // A stale expectation is replayed against the fresh on-disk revision
        // and converges (bounded retries in save_with_replay).
        let patch = SettingsPatch {
            ui: Some(UiSettings { language: "zh-CN".into(), ..UiSettings::default() }),
            ..Default::default()
        };
        let outcome = save_with_replay(dir.path(), 0, &patch).unwrap();
        assert_eq!(outcome.revision, 2);
        let d = Settings::load(dir.path()).unwrap().document();
        assert_eq!(d.ui.language, "zh-CN");
        assert_eq!(d.aisc_cli_path.as_deref(), Some("/x/aisc"));
    }

    #[test]
    fn reset_keeps_pin_and_unknowns() {
        let dir = tempdir().unwrap();
        let mut doc = raw_doc();
        doc["custom_future_field"] = Value::Number(7.into());
        doc["ui"]["future_ui_flag"] = Value::Bool(false);
        write(dir.path(), &doc);
        let mut s = Settings::load(dir.path()).unwrap();
        s.set_aisc_cli_path(Some("/p/aisc"));
        s.apply_gui_patch(&SettingsPatch {
            ui: Some(UiSettings { language: "en-US".into(), font_scale: 1.3, ..UiSettings::default() }),
            terminal: Some(TerminalSettings { font_size: 20, ..TerminalSettings::default() }),
            ..Default::default()
        });
        s.save(dir.path()).unwrap();
        let rev = Settings::load(dir.path()).unwrap().revision;

        let outcome = reset_settings_document(dir.path(), rev).unwrap();
        let d = Settings::load(dir.path()).unwrap().document();
        assert_eq!(d.ui.language, "auto");
        assert_eq!(d.ui.font_scale, 1.0);
        assert_eq!(d.terminal.font_size, 14);
        assert_eq!(d.aisc_cli_path.as_deref(), Some("/p/aisc"));
        assert_eq!(d.revision, outcome.revision);
        assert_eq!(
            Settings::load(dir.path()).unwrap().raw.get("custom_future_field").and_then(|v| v.as_u64()),
            Some(7)
        );
    }

    #[test]
    fn revision_bumps_every_save() {
        let dir = tempdir().unwrap();
        assert_eq!(Settings::load(dir.path()).unwrap().revision, 0);
        let mut s = Settings::load(dir.path()).unwrap();
        s.save(dir.path()).unwrap();
        assert_eq!(Settings::load(dir.path()).unwrap().revision, 1);
        // Reload between saves: a stale in-memory copy writes its own +1.
        let mut s = Settings::load(dir.path()).unwrap();
        s.save(dir.path()).unwrap();
        assert_eq!(Settings::load(dir.path()).unwrap().revision, 2);
    }

    #[test]
    fn pin_save_preserves_gui_fields() {
        let dir = tempdir().unwrap();
        let mut s = Settings::load(dir.path()).unwrap();
        s.apply_gui_patch(&SettingsPatch {
            terminal: Some(TerminalSettings { font_size: 18, ..TerminalSettings::default() }),
            ..Default::default()
        });
        s.save(dir.path()).unwrap();
        // Pin update later (cli.rs path) must not clobber the GUI fields.
        let mut s2 = Settings::load(dir.path()).unwrap();
        s2.set_aisc_cli_path(Some("/y/aisc"));
        s2.save(dir.path()).unwrap();
        let d = Settings::load(dir.path()).unwrap().document();
        assert_eq!(d.terminal.font_size, 18);
        assert_eq!(d.aisc_cli_path.as_deref(), Some("/y/aisc"));
    }

    #[test]
    fn geometry_schema_round_trips() {
        let dir = tempdir().unwrap();
        let mut s = Settings::load(dir.path()).unwrap();
        s.apply_gui_patch(&SettingsPatch {
            window: Some(WindowSettings {
                remember_geometry: true,
                close_behavior: "quit".into(),
                geometry: Some(WindowGeometry {
                    x: 100, y: 80, width: 1200, height: 800, maximized: false,
                }),
            }),
            ..Default::default()
        });
        s.save(dir.path()).unwrap();
        let d = Settings::load(dir.path()).unwrap().document();
        let g = d.window.geometry.expect("geometry saved");
        assert_eq!((g.x, g.y, g.width, g.height), (100, 80, 1200, 800));
    }
}
