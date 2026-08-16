//! Installer handoff (Stage 5, A-INS01/A-ONB08).
//!
//! The NSIS installer writes non-sensitive facts under the product registry key
//! (`HKCU\Software\aisc\AISC Workbench`): installer source, installed version,
//! first-run marker and a Docker dependency hint. The Workbench reads these to
//! decide first-run onboarding and surface dependency hints, but **re-checks
//! CLI/Docker itself** — handoff is not a fact (D5-07). Never secrets.

use serde::Serialize;

use crate::identity::{PRODUCT_REGISTRY_KEY, PRODUCT_NAME};

/// Non-sensitive handoff facts written by the installer.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InstallerHandoff {
    /// "nsis" when the NSIS installer set this (else "").
    pub installer_source: String,
    /// Installed version string (e.g. "2.4.0"). "" when unset.
    pub installed_version: String,
    /// 1 = installer set a first-run marker for this install.
    pub first_run: bool,
    /// Dependency hint the installer recorded ("installer_checked" | "").
    pub docker_hint: String,
    /// Whether the product registry key exists at all (Windows read outcome).
    pub present: bool,
    /// The product name constant (for display only; never a decision input).
    pub product_name: String,
}

impl Default for InstallerHandoff {
    fn default() -> Self {
        Self {
            installer_source: String::new(),
            installed_version: String::new(),
            first_run: false,
            docker_hint: String::new(),
            present: false,
            // Fixed identity constant, always populated — never a decision input.
            product_name: PRODUCT_NAME.to_string(),
        }
    }
}

const INSTALLER_SOURCE_VALUE: &str = "InstallerSource";
const INSTALLED_VERSION_VALUE: &str = "InstalledVersion";
const FIRST_RUN_VALUE: &str = "FirstRun";
const DOCKER_HINT_VALUE: &str = "DockerHint";

/// Read the installer handoff from the Windows registry.
///
/// Windows: reads `HKCU\Software\aisc\AISC Workbench`. Missing key/values →
/// defaults (empty, first_run=false, present=false). Never errors: a broken
/// registry read must not block startup.
#[cfg(windows)]
pub fn read_handoff() -> InstallerHandoff {
    use winreg::enums::{HKEY_CURRENT_USER, KEY_READ};
    use winreg::RegKey;

    let mut handoff = InstallerHandoff {
        product_name: PRODUCT_NAME.to_string(),
        ..Default::default()
    };
    let key = RegKey::predef(HKEY_CURRENT_USER)
        .open_subkey_with_flags(PRODUCT_REGISTRY_KEY, KEY_READ)
        .ok();
    if let Some(key) = key {
        handoff.present = true;
        handoff.installer_source =
            key.get_value::<String, _>(INSTALLER_SOURCE_VALUE).unwrap_or_default();
        handoff.installed_version =
            key.get_value::<String, _>(INSTALLED_VERSION_VALUE).unwrap_or_default();
        handoff.docker_hint =
            key.get_value::<String, _>(DOCKER_HINT_VALUE).unwrap_or_default();
        handoff.first_run = key
            .get_value::<u32, _>(FIRST_RUN_VALUE)
            .map(|v| v != 0)
            .unwrap_or(false);
    }
    handoff
}

#[cfg(not(windows))]
pub fn read_handoff() -> InstallerHandoff {
    InstallerHandoff {
        product_name: PRODUCT_NAME.to_string(),
        ..Default::default()
    }
}

/// Tauri command: surface the installer handoff to the frontend so onboarding
/// can show a source/version hint and a first-run gate. The frontend still
/// re-checks CLI/Docker itself (D5-07).
#[tauri::command]
pub async fn installer_handoff() -> InstallerHandoff {
    read_handoff()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_handoff_is_non_fact() {
        // Non-Windows / missing-key default: no source, no first-run, absent.
        let h = InstallerHandoff::default();
        assert_eq!(h.installer_source, "");
        assert_eq!(h.installed_version, "");
        assert!(!h.first_run);
        assert!(!h.present);
    }

    #[test]
    fn product_name_is_fixed_identity() {
        let h = InstallerHandoff::default();
        assert_eq!(h.product_name, PRODUCT_NAME);
    }

    #[test]
    fn serializes_camel_case_for_frontend() {
        let h = InstallerHandoff {
            installer_source: "nsis".into(),
            installed_version: "2.4.0".into(),
            first_run: true,
            docker_hint: "installer_checked".into(),
            present: true,
            product_name: PRODUCT_NAME.into(),
        };
        let v = serde_json::to_value(&h).unwrap();
        assert_eq!(v["installerSource"], "nsis");
        assert_eq!(v["installedVersion"], "2.4.0");
        assert_eq!(v["firstRun"], true);
        assert_eq!(v["dockerHint"], "installer_checked");
        assert_eq!(v["present"], true);
    }
}
