//! Packaging identity constants (05 §5.3).
//!
//! Fixed identity: `manufacturer=aisc`, `productName=AISC Workbench`, full
//! product key `HKCU\Software\aisc\AISC Workbench`. The NSIS installer renders
//! `MANUFACTURER`/`PRODUCTNAME` from the same tauri.conf.json values; the
//! `identity_matches_tauri_config` test pins them together so the Rust registry
//! reads and the installer registry writes can never drift (Step 4 reads the
//! `Installer Language` value under this key; G-18 reads/writes the PATH
//! ownership markers under it).

pub const MANUFACTURER: &str = "aisc";
pub const PRODUCT_NAME: &str = "AISC Workbench";
/// HKCU registry key written by the NSIS installer.
pub const PRODUCT_REGISTRY_KEY: &str = "Software\\aisc\\AISC Workbench";

/// NSIS writes the language selector here (`Installer Language`, 1033/2052).
pub const INSTALLER_LANGUAGE_VALUE: &str = "Installer Language";

/// G-18 PATH ownership markers (05 §5.2).
pub const PATH_OWNED_VALUE: &str = "PathEntryOwned";
pub const PATH_ENTRY_VALUE: &str = "PathEntry";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identity_matches_tauri_config() {
        // The NSIS defines and the Rust constants are both derived from
        // tauri.conf.json; parse the config and assert they agree so a rename
        // in either place fails CI (05 §5.3 / A-G18).
        let conf_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tauri.conf.json");
        let raw = std::fs::read_to_string(&conf_path).expect("tauri.conf.json");
        let conf: serde_json::Value =
            serde_json::from_str(&raw).expect("tauri.conf.json must be valid JSON");
        let publisher = conf["bundle"]["publisher"].as_str().expect("bundle.publisher");
        let product = conf["productName"].as_str().expect("productName");
        assert_eq!(publisher, MANUFACTURER);
        assert_eq!(product, PRODUCT_NAME);
        // The product registry key must be exactly the join of both.
        assert_eq!(
            PRODUCT_REGISTRY_KEY,
            format!("Software\\{MANUFACTURER}\\{PRODUCT_NAME}")
        );
    }
}
