// AISC Workbench - Tauri backend.
//
// S1.2: structured CLI runner (discovery/pinning, capability negotiation).
// S1.3: PTY supervisor + session data-plane commands.
// See docs/gui-planning/06-implementation-plan.md §四.

pub mod cache;
pub mod cli;
pub mod conversation;
pub mod data_root;
pub mod docker_ownership;
pub mod doctor;
pub mod host_mcp;
pub mod lease;
pub mod env;
pub mod error;
pub mod history;
pub mod identity;
pub mod installer;
pub mod logging;
pub mod onboarding;
pub mod locale;
pub mod pty;
pub mod runtime;
pub mod session;
pub mod settings;
pub mod subscription;
pub mod docker_api;
pub mod sync;
pub mod artifact;
pub mod storage;
pub mod trace;
pub mod tray;
pub mod watcher;
pub mod web_services;
pub mod window;
pub mod workspace;

/// 2.1.9 hotfix r3 (nairong #61): force Python UTF-8 mode for every sidecar
/// spawn. On zh-CN Windows the PyInstaller CLI defaults to GBK for files
/// third-party code opens without an explicit encoding (docker-py's context
/// meta.json), which crashed every terminal session with a bare
/// UnicodeDecodeError. Must run before the first child spawn; set_var races
/// are avoided by calling this once at startup, pre-async-runtime.
pub fn ensure_sidecar_utf8() {
    // set_default (not overwrite): an explicit PYTHONUTF8=0 from a power user
    // is respected... except 0 still disables UTF-8 mode, so treat any
    // existing value as intentional.
    if std::env::var_os("PYTHONUTF8").is_none() {
        std::env::set_var("PYTHONUTF8", "1");
    }
}

use artifact::{artifact_inspect, artifact_list, artifact_refresh};
use cli::{cli_clear_pin, cli_discover, cli_pin, negotiate_capabilities, CliArg};
use watcher::{workspace_rescan, workspace_watch_start, workspace_watch_stop, WatcherState};
use workspace::{
    workspace_copy_entry, workspace_copy_path, workspace_create_dir, workspace_create_file,
    workspace_forget, workspace_forget_preview, workspace_history_remove, workspace_list,
    workspace_open, workspace_path_exists, workspace_preview, workspace_rename, workspace_reveal,
    workspace_reveal_data_file,
};
use doctor::{diagnostic_bundle, logs_tail, run_doctor};
use logging::log_ui_event;
use history::{load_history, save_history};
use trace::op_traces;
use locale::resolve_locale;
use env::{env_poll_engine, env_readiness};
use installer::installer_handoff;
use conversation::{
    conversation_delete, conversation_list, conversation_preflight, conversation_rename,
};
use onboarding::{onboarding_load, onboarding_update};
use runtime::{
    build_image, cancel_build, cancel_runtime_start, cc_switch_add, cc_switch_delete,
    cc_switch_edit, cc_switch_fetch_models, cc_switch_providers, cc_switch_switch,
    get_provider_status, list_runtimes,
    network_subscription_clear, network_subscription_import, network_subscription_import_file,
    network_subscription_refresh, network_subscription_show, usage_overview,
    open_runtime_service_url, remove_runtime, runtime_inspect, runtime_preflight, runtime_status,
    runtime_reconcile, runtime_restart, runtime_services, start_docker, start_runtime,
    stop_runtime,
    BuildOps, OpMutexes, StartOps,
};
use lease::{lease_claim, lease_release, lease_supervisor_info, LeaseSupervisor};
use session::{
    ack_session_exit, close_session, open_session, resize_session, session_read_spool,
    shutdown_workbench, shutdown_workbench_v2, write_session, SessionRegistry,
};
use cache::{cache_cleanup, cache_usage};
use settings::{load_settings, reset_gui_settings, save_settings};
use tray::{build_tray, tray_available, tray_remove};
use window::{capture_window_geometry, restore_window_geometry};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run(cli_arg: Option<String>) {
    // 2.1.9 hotfix r3 (nairong #61, user VM repro): the PyInstaller sidecar
    // inherits the Windows locale; on zh-CN systems Python's default text
    // encoding is GBK, which corrupts UTF-8 files third-party code opens
    // without an explicit encoding (docker-py's context meta.json →
    // UnicodeDecodeError → "exit 1, zero output"). Force Python UTF-8 mode
    // for every sidecar spawn — env is set before any thread that might
    // race a child spawn, and it is inherited by all aisc.exe children.
    ensure_sidecar_utf8();

    let cli_arg_state = CliArg(std::sync::Arc::new(std::sync::Mutex::new(cli_arg)));
    tauri::Builder::default()
        .manage(WatcherState::default())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_notification::init())
        .manage(cli_arg_state)
        .manage(SessionRegistry::default())
        .manage(StartOps::default())
        .manage(BuildOps::default())
        .manage(OpMutexes::default())
        .manage(LeaseSupervisor::default())
        // F2 (D-10): host-tools MCP — the backend's first local listener.
        .manage(std::sync::Arc::new(host_mcp::HostMcpState::new()))
        .invoke_handler(tauri::generate_handler![
            cli_discover,
            cli_pin,
            cli_clear_pin,
            negotiate_capabilities,
            open_session,
            conversation_list,
            conversation_preflight,
            conversation_delete,
            conversation_rename,
            write_session,
            resize_session,
            session_read_spool,
            cache_usage,
            cache_cleanup,
            close_session,
            ack_session_exit,
            shutdown_workbench,
            shutdown_workbench_v2,
            start_runtime,
            stop_runtime,
            runtime_preflight,
            runtime_inspect,
            runtime_status,
            runtime::runtime_poll_light,
            runtime_reconcile,
            runtime_restart,
            cancel_runtime_start,
            list_runtimes,
            remove_runtime,
            get_provider_status,
            runtime_services,
            open_runtime_service_url,
            lease_claim,
            lease_release,
            lease_supervisor_info,
            cc_switch_providers,
            cc_switch_add,
            cc_switch_edit,
            cc_switch_switch,
            cc_switch_delete,
            cc_switch_fetch_models,
            network_subscription_import,
            network_subscription_import_file,
            network_subscription_refresh,
            network_subscription_clear,
            network_subscription_show,
            usage_overview,
            load_history,
            save_history,
            build_image,
            cancel_build,
            start_docker,
            load_settings,
            save_settings,
            reset_gui_settings,
            sync::ssh_workspace_create,
            sync::ssh_browse,
            sync::ssh_browse_workspace,
            sync::ssh_pull_file,
            sync::sync_session_start,
            sync::sync_session_status,
            sync::sync_session_cancel,
            sync::sync_session_enable,
            sync::sync_session_pause,
            sync::sync_session_resume,
            sync::sync_session_terminate,
            resolve_locale,
            restore_window_geometry,
            capture_window_geometry,
            run_doctor,
            diagnostic_bundle,
            logs_tail,
            log_ui_event,
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
            workspace_forget_preview,
            workspace_forget,
            workspace_history_remove,
            workspace_path_exists,
            workspace_reveal_data_file,
            workspace_copy_path,
            workspace_create_file,
            workspace_create_dir,
            workspace_copy_entry,
            workspace_rename,
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
            // lifecycle-logging P1: app start opens the shared JSONL timeline
            // (best-effort — never blocks startup). v2.1.7 S1 (A-21714): the
            // version is the Tauri package info (tauri.conf.json) logged once
            // per process — Cargo's package version is a dev-local 0.1.0 and
            // is NOT the shipped version.
            logging::append_event(
                "info",
                "app",
                "app_start",
                None,
                serde_json::json!({ "app_version": app.package_info().version.to_string() }),
            );
            // G-10: restore window geometry on startup (before the window
            // is shown, so the user sees the saved position immediately).
            let app_handle = app.handle().clone();
            if let Err(e) = restore_window_geometry(app_handle) {
                eprintln!("[geometry] restore failed: {:?}", e);
            }
            // F2 (D-10): start the host-tools MCP listener (127.0.0.1 dynamic
            // port, per-process token). Purely additive: a bind failure only
            // means "no endpoint" — the app never depends on this service.
            // The whitelist is pre-seeded from settings so a container that
            // connects before any settings round-trip still sees the gate.
            {
                use tauri::Manager;
                let state = app.state::<std::sync::Arc<host_mcp::HostMcpState>>().inner().clone();
                if let Ok(dir) = crate::session::config_dir(app.handle()) {
                    if let Ok(doc) = settings::load_settings_document(&dir) {
                        state.set_whitelist(doc.host_tools);
                    }
                }
                tauri::async_runtime::spawn(host_mcp::serve(state));
                // F1: record the bundle resource dir — the mutagen agents
                // tarball rides bundle.resources, which on deb/DMG installs
                // lands away from the externalBin binary dir.
                if let Ok(res) = app.path().resource_dir() {
                    let _ = sync::MUTAGEN_RESOURCE_DIR.set(res);
                }
            }
            // O2 (D-11): sweep orphaned output spools. Spools are deleted with
            // their registry entry (ack/close/evict); only a killed process
            // leaves them behind. No session can ever reference a spool from
            // a previous process (session ids are fresh uuids), so anything
            // older than 24h is garbage — off-thread, never blocking startup.
            std::thread::spawn(|| {
                if let Some(dir) = crate::data_root::sessions_dir() {
                    if let Ok(entries) = std::fs::read_dir(&dir) {
                        let cutoff = std::time::SystemTime::now()
                            .checked_sub(std::time::Duration::from_secs(24 * 3600));
                        for e in entries.flatten() {
                            let p = e.path();
                            if p.extension().and_then(|x| x.to_str()) != Some("spool") {
                                continue;
                            }
                            let stale = e
                                .metadata()
                                .and_then(|m| m.modified())
                                .ok()
                                .zip(cutoff)
                                .map(|(mtime, cutoff)| mtime < cutoff)
                                .unwrap_or(false);
                            if stale {
                                let _ = std::fs::remove_file(&p);
                            }
                        }
                    }
                }
            });
            // G-16: optional tray; init failure falls back to quit-only.
            if let Err(e) = build_tray(app.handle()) {
                eprintln!("[tray] init failed, falling back to quit-only: {e}");
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod utf8_env_tests {
    // 2.1.9 hotfix r3 (#61): the sidecar env must force Python UTF-8 mode
    // (zh-CN GBK crashes in docker-py's context loading) and respect an
    // explicit user override. One test, sequential phases — env vars are
    // process-global and parallel #[test]s would race on the same key.
    #[test]
    fn ensure_sidecar_utf8_sets_when_unset_and_respects_override() {
        let key = "PYTHONUTF8";
        let prev = std::env::var_os(key);

        std::env::remove_var(key);
        super::ensure_sidecar_utf8();
        assert_eq!(std::env::var(key).unwrap(), "1");

        std::env::set_var(key, "0");
        super::ensure_sidecar_utf8();
        assert_eq!(std::env::var(key).unwrap(), "0");

        match prev {
            Some(v) => std::env::set_var(key, v),
            None => std::env::remove_var(key),
        }
    }
}
