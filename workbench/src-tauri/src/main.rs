// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

/// Parse `--aisc-cli <path>` from the process args (S4.1.a): an explicit CLI
/// path that outranks the saved pin and the bundled sidecar (02 §四.3).
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let mut cli_arg: Option<String> = None;
    let mut i = 1;
    while i < args.len() {
        if args[i] == "--aisc-cli" && i + 1 < args.len() {
            cli_arg = Some(args[i + 1].clone());
            i += 2;
        } else {
            i += 1;
        }
    }
    workbench_lib::run(cli_arg)
}
