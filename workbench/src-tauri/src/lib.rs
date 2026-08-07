// AISC Workbench - Tauri backend.
//
// S1.2: structured CLI runner (discovery/pinning, capability negotiation).
// S1.3: PTY supervisor + session data-plane commands.
// See docs/gui-planning/06-implementation-plan.md §四.

pub mod cli;
pub mod error;
pub mod pty;
pub mod session;
pub mod settings;

use cli::{cli_clear_pin, cli_discover, cli_pin, negotiate_capabilities};
use session::{close_session, open_session, resize_session, write_session, SessionRegistry};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(SessionRegistry::default())
        .invoke_handler(tauri::generate_handler![
            cli_discover,
            cli_pin,
            cli_clear_pin,
            negotiate_capabilities,
            open_session,
            write_session,
            resize_session,
            close_session,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
