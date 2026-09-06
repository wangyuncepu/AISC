//! PERF P8 (D-13): low-spec mode — detection, auto-enable, `.wslconfig`
//! merge. User ruling 2026-09-05: AUTO-APPLY + notify (the only retained
//! confirmation is the `.wslconfig` write — `wsl --shutdown` stops every
//! WSL instance and running container, a destructive step the user clicks).

use serde::Serialize;
use tauri::AppHandle;

use crate::settings::{
    load_settings_document, save_settings_document, PerformanceSettings, SettingsPatch,
};

/// Doctor parity (O6 wsl-memory): the low-spec band is physical RAM
/// ≤ 8.5 GB (8 GB machines report slightly over 8.0 due to reserved-mem
/// accounting).
pub const LOW_SPEC_RAM_BYTES: u64 = 8_589_934_592; // 8 GiB + 512 MiB

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LowSpecStatus {
    /// Physical RAM in bytes (None when unprobeable — treated as not-low).
    pub total_ram: Option<u64>,
    pub low_spec: bool,
    /// True when this call is what flipped the setting on (drives the
    /// one-time notification).
    pub just_enabled: bool,
}

/// Total physical RAM via GlobalMemoryStatusEx (Windows) / sysconf (POSIX).
pub fn total_physical_ram() -> Option<u64> {
    #[cfg(windows)]
    {
        use windows_sys::Win32::System::SystemInformation::{
            GlobalMemoryStatusEx, MEMORYSTATUSEX,
        };
        let mut stat: MEMORYSTATUSEX = unsafe { std::mem::zeroed() };
        stat.dwLength = std::mem::size_of::<MEMORYSTATUSEX>() as u32;
        let ok = unsafe { GlobalMemoryStatusEx(&mut stat) };
        (ok != 0).then(|| stat.ullTotalPhys as u64)
    }
    #[cfg(not(windows))]
    {
        // POSIX: sysconf(_SC_PHYS_PAGES) * _SC_PAGESIZE
        extern "C" {
            fn sysconf(name: i32) -> i64;
        }
        const SC_PHYS_PAGES: i32 = 85;
        const SC_PAGESIZE: i32 = 30;
        let pages = unsafe { sysconf(SC_PHYS_PAGES) };
        let size = unsafe { sysconf(SC_PAGESIZE) };
        if pages > 0 && size > 0 {
            Some((pages as u64) * (size as u64))
        } else {
            None
        }
    }
}

/// One-shot at startup: when the host is low-spec and the auto-decision has
/// not run yet, flip `performance.lowSpec` on and persist. The decision
/// marker lives OUTSIDE settings.json so an explicit later user OFF sticks
/// (the auto path fires exactly once per install).
pub fn maybe_auto_enable(app: &AppHandle) -> LowSpecStatus {
    use tauri::Manager;
    let ram = total_physical_ram();
    let low = ram.map(|r| r <= LOW_SPEC_RAM_BYTES).unwrap_or(false);
    let mut just_enabled = false;
    if low {
        if let Some(dir) = crate::session::config_dir(app).ok() {
            if !raw_has_auto_decided(&dir) {
                if let Ok(doc) = load_settings_document(&dir) {
                    let perf = PerformanceSettings {
                        low_spec: true,
                        ..doc.performance.clone()
                    };
                    let revision = doc.revision;
                    let patch = SettingsPatch {
                        performance: Some(perf),
                        ..Default::default()
                    };
                    let dir2 = dir.clone();
                    let saved = tauri::async_runtime::block_on(async move {
                        save_settings_document(&dir2, revision, &patch)
                    });
                    if saved.is_ok() {
                        let _ = std::fs::write(dir.join("low-spec-decided"), b"1");
                        just_enabled = true;
                    }
                }
            }
        }
    }
    LowSpecStatus {
        total_ram: ram,
        low_spec: low,
        just_enabled,
    }
}

/// The decision marker lives OUTSIDE settings.json — settings survives
/// GUI resets and manual edits, but the auto-decide must fire exactly once
/// per install (an explicit later user OFF then sticks).
fn raw_has_auto_decided(dir: &std::path::Path) -> bool {
    dir.join("low-spec-decided").is_file()
}

// ---------------------------------------------------------------------------
// .wslconfig merge (INI, key-preserving)
// ---------------------------------------------------------------------------

/// Merge `memory=`/`processors=` into `[wsl2]` — user lines never touched:
/// an existing key is only written when `force` (the user explicitly changed
/// the value in our UI); auto mode only ADDS missing keys.
pub fn merge_wslconfig(current: &str, memory: &str, processors: u32, force: bool) -> Option<String> {
    Some(block_aware_merge(current, memory, processors, force))
}

/// Block-aware: parse into (pre, wsl2-lines, post) then merge keys.
fn block_aware_merge(current: &str, memory: &str, processors: u32, force: bool) -> String {
    let lines: Vec<&str> = current.lines().collect();
    let mut wsl2_start = None;
    let mut wsl2_end = lines.len(); // exclusive
    for (i, line) in lines.iter().enumerate() {
        let t = line.trim();
        if t.eq_ignore_ascii_case("[wsl2]") {
            wsl2_start = Some(i);
        } else if t.starts_with('[') && t.ends_with(']') && wsl2_start.is_some() {
            wsl2_end = i;
            break;
        }
    }

    let (start, end) = match wsl2_start {
        Some(s) => (s, wsl2_end),
        None => (lines.len(), lines.len()),
    };

    let mut block: Vec<String> = Vec::new();
    let mut have_memory = false;
    let mut have_processors = false;
    for line in &lines[start..end] {
        let t = line.trim();
        let lower = t.to_ascii_lowercase();
        if lower.starts_with("memory") && lower.contains('=') {
            have_memory = true;
            block.push(if force {
                format!("memory={memory}")
            } else {
                (*line).to_string()
            });
            continue;
        }
        if lower.starts_with("processors") && lower.contains('=') {
            have_processors = true;
            block.push(if force {
                format!("processors={processors}")
            } else {
                (*line).to_string()
            });
            continue;
        }
        block.push((*line).to_string());
    }
    if !have_memory {
        block.push(format!("memory={memory}"));
    }
    if !have_processors {
        block.push(format!("processors={processors}"));
    }

    let mut out: Vec<String> = Vec::new();
    if wsl2_start.is_none() {
        out.extend(lines.iter().map(|s| s.to_string()));
        if !out.is_empty() && !out.last().map(|s| s.is_empty()).unwrap_or(true) {
            out.push(String::new());
        }
        out.push("[wsl2]".into());
    } else {
        out.extend(lines[..start].iter().map(|s| s.to_string()));
    }
    out.extend(block);
    if wsl2_start.is_some() && end < lines.len() {
        out.extend(lines[end..].iter().map(|s| s.to_string()));
    }
    out.join("\n") + "\n"
}

/// The Tauri command: reads `%USERPROFILE%\.wslconfig`, merges missing keys
/// (auto) or forces values (explicit), writes atomically. The CALLER owns
/// the destructive `wsl --shutdown` confirmation; this command only writes.
#[tauri::command]
pub async fn wslconfig_merge(
    memory: String,
    processors: u32,
    force: bool,
) -> Result<bool, crate::error::WorkbenchError> {
    #[cfg(windows)]
    {
        let home = dirs::home_dir().ok_or_else(|| {
            crate::error::WorkbenchError::usage("cannot resolve home dir")
        })?;
        let path = home.join(".wslconfig");
        let current = std::fs::read_to_string(&path).unwrap_or_default();
        let merged = merge_wslconfig(&current, &memory, processors, force);
        let Some(merged) = merged else {
            return Ok(false);
        };
        if merged == current {
            return Ok(false);
        }
        std::fs::write(&path, merged.as_bytes()).map_err(|e| {
            crate::error::WorkbenchError::usage(format!("write .wslconfig: {e}"))
        })?;
        Ok(true)
    }
    #[cfg(not(windows))]
    {
        let _ = (memory, processors, force);
        Ok(false)
    }
}

/// The startup probe (called from lib.rs setup).
#[tauri::command]
pub async fn low_spec_status() -> LowSpecStatus {
    let ram = total_physical_ram();
    LowSpecStatus {
        total_ram: ram,
        low_spec: ram.map(|r| r <= LOW_SPEC_RAM_BYTES).unwrap_or(false),
        just_enabled: false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ram_probe_returns_plausible() {
        let ram = total_physical_ram();
        // Any real host: > 1 GiB and < 2 TiB.
        if let Some(r) = ram {
            assert!(r > 1 << 30 && r < 1 << 41);
        }
    }

    #[test]
    fn wslconfig_merge_adds_missing_keys_only() {
        // Existing user keys survive (auto mode never overwrites).
        let cur = "[wsl2]\nprocessors=14\n";
        let out = block_aware_merge(cur, "4GB", 4, false);
        assert!(out.contains("processors=14"), "user key kept: {out}");
        assert!(out.contains("memory=4GB"), "missing key added: {out}");

        // No [wsl2] section: appended.
        let out = block_aware_merge("user=stuff\n", "5GB", 6, false);
        assert!(out.contains("[wsl2]"));
        assert!(out.contains("memory=5GB"));
        assert!(out.contains("processors=6"));
        assert!(out.contains("user=stuff"));

        // [wsl2] mid-file: keys land INSIDE the block, later sections intact.
        let cur = "[user]\na=1\n\n[wsl2]\nswap=0\n\n[other]\nb=2\n";
        let out = block_aware_merge(cur, "4GB", 4, false);
        let w2 = out.find("[wsl2]").unwrap();
        let other = out.find("[other]").unwrap();
        let mem = out.find("memory=4GB").unwrap();
        assert!(w2 < mem && mem < other, "key inside block: {out}");
        assert!(out.contains("swap=0"));
        assert!(out.contains("b=2"));

        // Force mode overwrites.
        let out = block_aware_merge("[wsl2]\nmemory=99GB\n", "4GB", 4, true);
        assert!(out.contains("memory=4GB"));
        assert!(!out.contains("99GB"));
    }
}
