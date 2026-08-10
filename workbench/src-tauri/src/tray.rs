//! Optional system tray (G-16, Step 15; 03 §A-G16).
//!
//! `close_behavior=minimize-to-tray` hides the main window on close while
//! sessions keep running; the tray menu offers 显示 (show/focus) and 退出
//! (same frontend confirm + `shutdown_workbench` as a window close, A-G16-3).
//! `quit` (the default) is unchanged. If the tray cannot be initialized the
//! runtime falls back to quit-only (A-G16-4) - the last window is never hidden
//! without a tray to restore it from.

use std::sync::Mutex;

use tauri::{
    image::Image,
    menu::{Menu, MenuItem},
    tray::{TrayIcon, TrayIconBuilder},
    AppHandle, Emitter, Manager,
};

use crate::session::config_dir;
use crate::settings::Settings;

/// Owns the tray so it is not dropped (a dropped `TrayIcon` disappears).
/// Absent (or empty) when the tray could not be created -> quit-only fallback.
pub struct TrayState(pub Mutex<Option<TrayIcon>>);

/// Whether a tray is live in this process (A-G16-4 gate).
pub fn tray_available(app: &AppHandle) -> bool {
    app.try_state::<TrayState>()
        .map(|s| s.0.lock().map(|g| g.is_some()).unwrap_or(false))
        .unwrap_or(false)
}

/// Persisted `window.close_behavior` ("quit" default; "minimize-to-tray").
fn close_behavior(app: &AppHandle) -> String {
    Settings::load(&config_dir(app).unwrap_or_default())
        .map(|s| s.document().window.close_behavior.clone())
        .unwrap_or_else(|_| "quit".into())
}

/// Create the tray with 显示/退出 menu. On failure the caller logs and the app
/// keeps running quit-only (A-G16-4); on success the owner is stored in state.
pub fn build_tray(app: &AppHandle) -> Result<(), tauri::Error> {
    let lang = Settings::load(&config_dir(app).unwrap_or_default())
        .map(|s| s.document().ui.language)
        .unwrap_or_default();
    let en = lang.starts_with("en");
    let (show_label, exit_label) = if en { ("Show", "Exit") } else { ("显示", "退出") };

    let show_item = MenuItem::with_id(app, "tray-show", show_label, true, None::<&str>)?;
    let exit_item = MenuItem::with_id(app, "tray-exit", exit_label, true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &exit_item])?;

    // The bundled window icon doubles as the tray icon; a 1x1 RGBA fallback
    // keeps the tray buildable even if no embedded icon were present.
    let icon = match app.default_window_icon().cloned() {
        Some(i) => i,
        None => Image::new(&[0u8; 4], 1, 1),
    };

    let tray = TrayIconBuilder::with_id("main-tray")
        .icon(icon)
        .tooltip("AISC Workbench")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "tray-show" => {
                if let Some(win) = app.get_webview_window("main") {
                    let _ = win.show();
                    let _ = win.set_focus();
                }
            }
            "tray-exit" => {
                // Route through the frontend: it runs the SAME confirm gate as
                // a window close (A-G16-3), then shutdown_workbench exits.
                let _ = app.emit("exit-requested", ());
            }
            _ => {}
        })
        .build(app)?;
    app.manage(TrayState(Mutex::new(Some(tray))));
    Ok(())
}

/// Effective close behavior at close time. When the tray is unavailable, a
/// stored `minimize-to-tray` value falls back to quit at runtime (A-G16-4) so
/// the last window is never hidden without a tray to restore it.
pub fn effective_close_behavior(app: &AppHandle) -> &'static str {
    if close_behavior(app) == "minimize-to-tray" && tray_available(app) {
        "minimize-to-tray"
    } else {
        "quit"
    }
}

/// Rust-side close interception (03 §A-G16): both modes prevent the default
/// close; tray mode additionally hides (the frontend skips its shutdown flow
/// when it sees tray mode + tray available), quit mode lets the frontend run
/// the confirm + shutdown coordinator.
pub fn on_window_close_requested(window: &tauri::Window, api: &tauri::CloseRequestApi) {
    api.prevent_close();
    if window.label() != "main" {
        return;
    }
    let app = window.app_handle();
    if effective_close_behavior(app) == "minimize-to-tray" {
        let _ = window.hide();
    }
    // quit: nothing more here - the frontend confirms and calls shutdown.
}

#[tauri::command]
pub fn tray_available_command(app: AppHandle) -> bool {
    tray_available(&app)
}
