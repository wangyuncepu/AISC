// AISC Workbench - Tauri backend.
//
// S1.2: structured CLI runner (discovery/pinning, capability negotiation).
// S1.3: PTY supervisor + session data-plane commands.
// See docs/gui-planning/06-implementation-plan.md §四.

pub mod cli;
pub mod error;
pub mod history;
pub mod identity;
pub mod locale;
pub mod pty;
pub mod runtime;
pub mod session;
pub mod settings;
pub mod storage;
pub mod window;

use cli::{cli_clear_pin, cli_discover, cli_pin, negotiate_capabilities, CliArg};
use history::{load_history, save_history};
use locale::resolve_locale;
use runtime::{
    build_image, cancel_build, cancel_runtime_start, get_provider_status, list_runtimes,
    remove_runtime, runtime_inspect, runtime_preflight, runtime_restart, start_docker,
    start_runtime, stop_runtime, BuildOp, OpMutexes, StartOp,
};
use session::{
    ack_session_exit, close_session, open_session, resize_session, shutdown_workbench,
    write_session, SessionRegistry,
};
use settings::{load_settings, reset_gui_settings, save_settings};
use window::{capture_window_geometry, restore_window_geometry};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run(cli_arg: Option<String>) {
    let cli_arg_state = CliArg(std::sync::Arc::new(std::sync::Mutex::new(cli_arg)));
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
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
        ])
        .setup(|app| {
            // G-10: restore window geometry on startup (before the window
            // is shown, so the user sees the saved position immediately).
            let app_handle = app.handle().clone();
            if let Err(e) = restore_window_geometry(app_handle) {
                eprintln!("[geometry] restore failed: {:?}", e);
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
