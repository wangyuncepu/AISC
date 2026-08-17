//! G-10 window geometry save/restore (02 §A-G10-1..5).
//!
//! Two Tauri commands:
//! - `restore_window_geometry`: called on startup; reads `window.geometry`
//!   from settings and applies it with monitor clamping.
//! - `capture_window_geometry`: called on debounced resize/move and before
//!   shutdown; writes the current logical rect + maximized to settings.
//!
//! All units are **logical** (DPI-independent). The frontend does NOT add a
//! generic position/size capability - Rust owns the window API, clamping,
//! and unit conversion (06 §十).

use tauri::{AppHandle, LogicalPosition, LogicalSize, Manager, WebviewWindow};

use crate::error::WorkbenchError;
use crate::settings::{save_with_replay, Settings, SettingsPatch, WindowGeometry};

const MIN_WIDTH: u32 = 800;
const MIN_HEIGHT: u32 = 600;
const VISIBLE_PX: i32 = 64; // at least 64×64 logical px must be on-screen

fn config_dir(app: &AppHandle) -> Result<std::path::PathBuf, WorkbenchError> {
    // Stage 7 (DATA-04): <data-root>/config (legacy app_config_dir is the
    // adoption source / fallback). See session::config_dir.
    let legacy = app.path().app_config_dir().ok();
    Ok(crate::data_root::app_state_dir(legacy.as_deref()))
}

fn main_window(app: &AppHandle) -> Result<WebviewWindow, WorkbenchError> {
    app.get_webview_window("main")
        .ok_or_else(|| WorkbenchError::cli_protocol().with_detail("main window not found"))
}

/// Check whether at least `VISIBLE_PX`×`VISIBLE_PX` of the rect `(x, y, w, h)`
/// intersects any available monitor (A-G10-4). Returns the clamped geometry
/// if visible, or `None` if off-screen (caller falls back to OS default).
fn clamp_to_monitor(app: &AppHandle, geo: &WindowGeometry) -> Option<WindowGeometry> {
    let mut clamped = geo.clone();
    clamped.width = clamped.width.max(MIN_WIDTH);
    clamped.height = clamped.height.max(MIN_HEIGHT);

    let monitors = app.available_monitors().unwrap_or_default();
    if monitors.is_empty() {
        return Some(clamped); // can't clamp - trust the OS
    }

    let scale = monitors[0].scale_factor();
    for m in &monitors {
        let mpos = m.position();
        let msize = m.size();
        // Monitor physical -> logical.
        let mx = mpos.x as f64 / scale;
        let my = mpos.y as f64 / scale;
        let mw = msize.width as f64 / scale;
        let mh = msize.height as f64 / scale;

        // Intersection.
        let ix0 = (clamped.x as f64).max(mx);
        let iy0 = (clamped.y as f64).max(my);
        let ix1 = (clamped.x as f64 + clamped.width as f64).min(mx + mw);
        let iy1 = (clamped.y as f64 + clamped.height as f64).min(my + mh);
        if ix1 - ix0 >= VISIBLE_PX as f64 && iy1 - iy0 >= VISIBLE_PX as f64 {
            // Clamp size to monitor work area.
            let max_w = (mx + mw - clamped.x as f64).max(MIN_WIDTH as f64) as u32;
            let max_h = (my + mh - clamped.y as f64).max(MIN_HEIGHT as f64) as u32;
            clamped.width = clamped.width.min(max_w).max(MIN_WIDTH);
            clamped.height = clamped.height.min(max_h).max(MIN_HEIGHT);
            return Some(clamped);
        }
    }
    None // off-screen
}

#[tauri::command]
pub fn restore_window_geometry(app: AppHandle) -> Result<bool, WorkbenchError> {
    let dir = config_dir(&app)?;
    let settings = Settings::load(&dir)
        .map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
    let doc = settings.document();
    if !doc.window.remember_geometry {
        return Ok(false); // A-G10-1: user opted out
    }
    let geo = match &doc.window.geometry {
        Some(g) => g,
        None => return Ok(false), // no saved geometry - OS default
    };

    let geo = match clamp_to_monitor(&app, geo) {
        Some(g) => g,
        None => {
            eprintln!("[geometry] saved rect off-screen, using OS default");
            return Ok(false);
        }
    };

    let win = main_window(&app)?;
    if geo.maximized {
        win.maximize()
            .map_err(|e| WorkbenchError::settings_error().with_detail(format!("maximize: {e}")))?;
    } else {
        win.set_position(LogicalPosition::new(geo.x, geo.y))
            .map_err(|e| WorkbenchError::settings_error().with_detail(format!("position: {e}")))?;
        win.set_size(LogicalSize::new(geo.width, geo.height))
            .map_err(|e| WorkbenchError::settings_error().with_detail(format!("size: {e}")))?;
    }
    Ok(true)
}

#[tauri::command]
pub fn capture_window_geometry(app: AppHandle) -> Result<bool, WorkbenchError> {
    let dir = config_dir(&app)?;
    let settings = Settings::load(&dir)
        .map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
    let doc = settings.document();
    if !doc.window.remember_geometry {
        return Ok(false);
    }

    let win = main_window(&app)?;
    // Don't capture while fullscreen or minimized (A-G10-2).
    if win.is_fullscreen().unwrap_or(false) {
        return Ok(false);
    }

    let maximized = win.is_maximized().unwrap_or(false);
    let pos = win
        .outer_position()
        .map_err(|e| WorkbenchError::settings_error().with_detail(format!("position: {e}")))?;
    let size = win
        .outer_size()
        .map_err(|e| WorkbenchError::settings_error().with_detail(format!("size: {e}")))?;
    let scale = win.scale_factor().unwrap_or(1.0);

    let geo = WindowGeometry {
        x: (pos.x as f64 / scale).round() as i32,
        y: (pos.y as f64 / scale).round() as i32,
        width: (size.width as f64 / scale).round() as u32,
        height: (size.height as f64 / scale).round() as u32,
        maximized,
    };

    let patch = SettingsPatch {
        window: Some(crate::settings::WindowSettings {
            remember_geometry: doc.window.remember_geometry,
            close_behavior: doc.window.close_behavior.clone(),
            geometry: Some(geo),
        }),
        ..Default::default()
    };
    save_with_replay(&dir, doc.revision, &patch)
        .map_err(|e| WorkbenchError::settings_error().with_detail(e.to_string()))?;
    Ok(true)
}
