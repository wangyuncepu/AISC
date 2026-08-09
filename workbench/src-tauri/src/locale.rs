//! Locale resolution (02-startup-flow.md §3.1/§3.2; A-G09-1).
//!
//! Priority: explicit `ui.language` (`zh-CN` | `en-US`) wins; `auto` or any
//! other value falls back to the NSIS installer language
//! (`HKCU\Software\aisc\AISC Workbench\Installer Language`, 1033 -> en-US,
//! 2052 -> zh-CN, unknown -> next), then the system locale, then zh-CN.
//! Resolution never blocks CLI negotiation (frontend calls it in parallel).

use crate::identity::{INSTALLER_LANGUAGE_VALUE, PRODUCT_REGISTRY_KEY};

pub const LANG_ZH: &str = "zh-CN";
pub const LANG_EN: &str = "en-US";

/// Pure resolution matrix (A-G09-1). `language` is the raw `ui.language`
/// value (auto | zh-CN | en-US); `installer`/`system` are optional probes.
pub fn resolve(language: Option<&str>, installer: Option<&str>, system: Option<&str>) -> String {
    match language {
        Some("zh-CN") => return LANG_ZH.to_string(),
        Some("en-US") => return LANG_EN.to_string(),
        _ => {}
    }
    if let Some(v) = installer {
        match v.trim() {
            "1033" => return LANG_EN.to_string(),
            "2052" => return LANG_ZH.to_string(),
            _ => {}
        }
    }
    if let Some(s) = system {
        let s = s.to_ascii_lowercase();
        if s.starts_with("zh") {
            return LANG_ZH.to_string();
        }
        if s.starts_with("en") {
            return LANG_EN.to_string();
        }
    }
    LANG_ZH.to_string()
}

/// NSIS installer language (Windows only). The value may be stored as a
/// string ("2052") or a DWORD; unknown/missing -> None.
#[cfg(windows)]
pub fn installer_language() -> Option<String> {
    use winreg::enums::{HKEY_CURRENT_USER, KEY_READ};
    use winreg::RegKey;
    let key = RegKey::predef(HKEY_CURRENT_USER)
        .open_subkey_with_flags(PRODUCT_REGISTRY_KEY, KEY_READ)
        .ok()?;
    key.get_value::<String, _>(INSTALLER_LANGUAGE_VALUE)
        .ok()
        .or_else(|| key.get_value::<u32, _>(INSTALLER_LANGUAGE_VALUE).ok().map(|v| v.to_string()))
}

#[cfg(not(windows))]
pub fn installer_language() -> Option<String> {
    None
}

/// System locale via `sys-locale` (Windows: GetUserDefaultLocaleName, POSIX:
/// LC_ALL/LC_MESSAGES/LANG).
pub fn system_locale() -> Option<String> {
    sys_locale::get_locale()
}

/// Frontend entry: resolve the final locale given the raw `ui.language` value.
#[tauri::command]
pub async fn resolve_locale(language: Option<String>) -> String {
    resolve(
        language.as_deref(),
        installer_language().as_deref(),
        system_locale().as_deref(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_language_wins_over_everything() {
        assert_eq!(resolve(Some("zh-CN"), Some("1033"), Some("en-US")), LANG_ZH);
        assert_eq!(resolve(Some("en-US"), Some("2052"), Some("zh-CN")), LANG_EN);
    }

    #[test]
    fn auto_uses_installer_language() {
        assert_eq!(resolve(Some("auto"), Some("1033"), Some("zh-CN")), LANG_EN);
        assert_eq!(resolve(Some("auto"), Some("2052"), Some("en-US")), LANG_ZH);
        // Whitespace tolerated.
        assert_eq!(resolve(Some("auto"), Some(" 2052 "), Some("en-US")), LANG_ZH);
    }

    #[test]
    fn unknown_installer_falls_through_to_system() {
        assert_eq!(resolve(Some("auto"), Some("9999"), Some("zh-TW")), LANG_ZH);
        assert_eq!(resolve(Some("auto"), Some("9999"), Some("en-GB")), LANG_EN);
    }

    #[test]
    fn missing_everything_falls_back_to_chinese() {
        assert_eq!(resolve(None, None, None), LANG_ZH);
        assert_eq!(resolve(Some("auto"), None, Some("fr-FR")), LANG_ZH);
        assert_eq!(resolve(Some("auto"), None, None), LANG_ZH);
    }

    #[test]
    fn invalid_explicit_value_behaves_like_auto() {
        // A value outside the enum is not "explicit"; fall back through the chain.
        assert_eq!(resolve(Some("fr-FR"), Some("1033"), Some("zh-CN")), LANG_EN);
        assert_eq!(resolve(Some("fr-FR"), None, Some("zh-CN")), LANG_ZH);
    }

    #[test]
    fn system_locale_probe_returns_something_or_none() {
        // Just pin the contract: never panics, and if it returns a value it is
        // non-empty (used only as a fallback probe).
        if let Some(l) = system_locale() {
            assert!(!l.is_empty());
        }
    }
}
