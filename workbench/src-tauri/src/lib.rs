// AISC Workbench - Tauri backend.
//
// S1.2 exposes the structured CLI runner: discovery/pinning, capability
// negotiation. See docs/gui-planning/06-implementation-plan.md §四 S1.2.

pub mod cli;
pub mod error;
pub mod settings;

use cli::{cli_clear_pin, cli_discover, cli_pin, negotiate_capabilities};


#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            cli_discover,
            cli_pin,
            cli_clear_pin,
            negotiate_capabilities,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
