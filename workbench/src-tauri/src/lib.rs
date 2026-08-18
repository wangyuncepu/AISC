// AISC Workbench - Tauri backend.
//
// S1.2: structured CLI runner (discovery/pinning, capability negotiation).
// S1.3: PTY supervisor + session data-plane commands.
// See docs/gui-planning/06-implementation-plan.md §四.

pub mod cli;
pub mod data_root;
pub mod doctor;
pub mod env;
pub mod error;
pub mod history;
pub mod identity;
pub mod installer;
pub mod onboarding;
pub mod locale;
pub mod pty;
pub mod runtime;
pub mod session;
pub mod settings;
pub mod artifact;
pub mod storage;
pub mod trace;
pub mod tray;
pub mod watcher;
pub mod window;
pub mod workspace;

use artifact::{artifact_inspect, artifact_list, artifact_refresh};
use cli::{cli_clear_pin, cli_discover, cli_pin, negotiate_capabilities, CliArg};
use watcher::{workspace_rescan, workspace_watch_start, workspace_watch_stop, WatcherState};
use workspace::{workspace_copy_path, workspace_list, workspace_open, workspace_preview, workspace_reveal};
use doctor::{diagnostic_bundle, run_doctor};
use history::{load_history, save_history};
use trace::op_traces;
use locale::resolve_locale;
use env::{env_poll_engine, env_readiness};
use installer::installer_handoff;
use onboarding::{onboarding_load, onboarding_update};
use runtime::{
    build_image, cancel_build, cancel_runtime_start, cc_switch_add, cc_switch_delete,
    cc_switch_edit, cc_switch_providers, cc_switch_switch, get_provider_status, list_runtimes,
    remove_runtime, runtime_inspect, runtime_preflight, runtime_restart, start_docker,
    start_runtime, stop_runtime, BuildOp, OpMutexes, StartOp,
};
use session::{
    ack_session_exit, close_session, open_session, resize_session, shutdown_workbench,
    write_session, SessionRegistry,
};
use settings::{load_settings, reset_gui_settings, save_settings};
use tray::{build_tray, tray_available, tray_remove};
use window::{capture_window_geometry, restore_window_geometry};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run(cli_arg: Option<String>) {
    let cli_arg_state = CliArg(std::sync::Arc::new(std::sync::Mutex::new(cli_arg)));
    tauri::Builder::default()
        .manage(WatcherState::default())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_notification::init())
        .manage(cli_arg_state)
        .manage(SessionRegistry::default())
        .manage(StartOp::default())
        .manage(BuildOp::default())
        .manage(OpMutexes::default())
        .invoke_handler(tauri::generate_handler![
            cli_discover,
            cli_pin,
            cli_clear_pin,
            negotiate_capabilities,
            open_session,
            write_session,
            resize_session,
            close_session,
            ack_session_exit,
            shutdown_workbench,
            start_runtime,
            stop_runtime,
            runtime_preflight,
            runtime_inspect,
            runtime_restart,
            cancel_runtime_start,
            list_runtimes,
            remove_runtime,
            get_provider_status,
            cc_switch_providers,
            cc_switch_add,
            cc_switch_edit,
            cc_switch_delete,
            load_history,
            save_history,
            build_image,
            cancel_build,
            start_docker,
            load_settings,
            save_settings,
            reset_gui_settings,
            resolve_locale,
            restore_window_geometry,
            capture_window_geometry,
            run_doctor,
            diagnostic_bundle,
            op_traces,
            tray_available,
            tray_remove,
            artifact_list,
            artifact_inspect,
            artifact_refresh,
            workspace_list,
            workspace_open,
            workspace_preview,
            workspace_reveal,
            workspace_copy_path,
            workspace_rescan,
            workspace_watch_start,
            workspace_watch_stop,
            onboarding_load,
            onboarding_update,
            installer_handoff,
            env_readiness,
            env_poll_engine,
        ])
        .on_window_event(|window, event| {
            // G-16: intercept CloseRequested on the main window. Both behaviors
            // prevent the default close (quit goes through the frontend confirm
            // + shutdown coordinator; tray mode hides). Tray unavailable falls
            // back to quit (A-G16-4).
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                tray::on_window_close_requested(window, &api);
            }
        })
        .setup(|app| {
            // G-10: restore window geometry on startup (before the window
            // is shown, so the user sees the saved position immediately).
            let app_handle = app.handle().clone();
            if let Err(e) = restore_window_geometry(app_handle) {
                eprintln!("[geometry] restore failed: {:?}", e);
            }
            // G-16: optional tray; init failure falls back to quit-only.
            if let Err(e) = build_tray(app.handle()) {
                eprintln!("[tray] init failed, falling back to quit-only: {e}");
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
