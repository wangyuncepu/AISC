"""Static validation of the Inno Setup installer script and workflow.
Linux-only — does not require Inno Setup or Windows.
Checks critical invariants that, if violated, would cause user-visible bugs.
"""

import os
import re
import sys
import unittest
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJ))


class TestInstallerIssInvariants(unittest.TestCase):
    """Validate packaging/windows/installer.iss key invariants."""

    @classmethod
    def setUpClass(cls):
        iss_path = _PROJ / "packaging" / "windows" / "installer.iss"
        if not iss_path.is_file():
            raise unittest.SkipTest(f"installer.iss not found: {iss_path}")
        cls.text = iss_path.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    # ------------------------------------------------------------------
    # Security invariants
    # ------------------------------------------------------------------

    def test_privileges_required_lowest(self):
        """Must be per-user install — no admin required."""
        self.assertIn("PrivilegesRequired=lowest", self.text,
                      "Missing PrivilegesRequired=lowest")

    def test_no_uninsdeletevalue(self):
        """Must NOT use uninsdeletevalue — would wipe entire PATH on uninstall."""
        active_lines = [l for l in self.lines
                        if l.strip() and not l.strip().startswith(";")
                        and not l.strip().startswith("//")]
        active_text = "\n".join(active_lines).lower()
        self.assertNotIn("uninsdeletevalue", active_text,
                         "uninsdeletevalue found in active code — would destroy PATH on uninstall")

    # ------------------------------------------------------------------
    # Layout invariants
    # ------------------------------------------------------------------

    def test_adjacent_layout(self):
        """aisc.exe and aisc-bundle\ must be in {app}."""
        self.assertIn('DestDir: "{app}"', self.text,
                      "aisc.exe must go to {app}")
        self.assertIn('DestDir: "{app}\\aisc-bundle"', self.text,
                      "aisc-bundle must go to {app}\\aisc-bundle")

    def test_stable_appid(self):
        """AppId must be present and contain a valid UUID-like GUID."""
        self.assertIn("AppId=", self.text, "Missing AppId declaration")
        # AppId format: {{DF3B7C42-...}} which renders to {DF3B7C42-...}
        self.assertIn("DF3B7C42", self.text,
                      "AppId does not contain expected GUID")
        self.assertIn("{{", self.text,
                      "AppId must use ISPP double-brace escaping")
        # Must NOT contain extra text before the GUID
        self.assertIn("{{DF3B7C42", self.text,
                      "AppId must be a clean GUID, not AISC-GUID hybrid")

    # ------------------------------------------------------------------
    # Architecture
    # ------------------------------------------------------------------

    def test_x64_only(self):
        """Windows installer targets x64 only."""
        self.assertIn("ArchitecturesAllowed=x64compatible", self.text)
        self.assertIn("ArchitecturesInstallIn64BitMode=x64compatible", self.text)

    # ------------------------------------------------------------------
    # PATH safety invariants
    # ------------------------------------------------------------------

    def test_path_helper_functions_present(self):
        """PATH manipulation helpers must be implemented in [Code]."""
        self.assertTrue(
            any("NormalisePathEntry" in l for l in self.lines),
            "NormalisePathEntry function missing"
        )
        self.assertTrue(
            any("PathContains" in l for l in self.lines),
            "PathContains function missing"
        )
        self.assertTrue(
            any("AddToPath" in l for l in self.lines),
            "AddToPath function missing"
        )
        self.assertTrue(
            any("RemoveFromPath" in l for l in self.lines),
            "RemoveFromPath function missing"
        )

    def test_path_uses_regwriteexpandstringvalue(self):
        """Must use RegWriteExpandStringValue to preserve REG_EXPAND_SZ."""
        self.assertIn("RegWriteExpandStringValue", self.text,
                      "PATH writes must use RegWriteExpandStringValue")

    def test_path_case_insensitive(self):
        """PATH comparison must be case-insensitive."""
        self.assertIn("LowerCase", self.text,
                      "PATH comparison must use LowerCase for case-insensitivity")

    def test_cleanup_on_upgrade(self):
        """Upgrade must clean old aisc.exe and aisc-bundle before installing."""
        self.assertIn("DeleteFile(ExpandConstant('{app}\\", self.text,
                      "Missing pre-install cleanup of old aisc.exe")
        self.assertIn("DelTree(ExpandConstant('{app}\\aisc-bundle')",
                      self.text,
                      "Missing pre-install cleanup of old aisc-bundle")

    # ------------------------------------------------------------------
    # No unwanted shortcuts
    # ------------------------------------------------------------------

    def test_no_desktop_shortcut(self):
        """No desktop shortcut for a CLI tool."""
        for line in self.lines:
            if line.strip().startswith(";") or line.strip() == "":
                continue
            if "desktop" in line.lower() and "name:" in line.lower():
                self.fail(f"Desktop shortcut found: {line.strip()}")

    # ------------------------------------------------------------------
    # ISPP defines — build must be parameterised
    # ------------------------------------------------------------------

    def test_ispp_defines(self):
        """ISPP defines for version, exe source, bundle source must exist."""
        self.assertIn('MyAppVersion', self.text,
                      "Missing {#MyAppVersion} define")
        self.assertIn('MyExeSource', self.text,
                      "Missing {#MyExeSource} define")
        self.assertIn('MyBundleSource', self.text,
                      "Missing {#MyBundleSource} define")
        self.assertIn('MyNumericVersion', self.text,
                      "Missing {#MyNumericVersion} define for VersionInfoVersion")

    def test_version_info_numeric(self):
        """VersionInfoVersion must use numeric define, not raw display version."""
        self.assertIn('VersionInfoVersion={#MyNumericVersion}', self.text,
                      "VersionInfoVersion must use MyNumericVersion")

    def test_string_to_array_before_use(self):
        """StringToArray must be defined before PathContains calls it."""
        lines = self.text.splitlines()
        st_idx = None
        pc_idx = None
        for i, l in enumerate(lines):
            if 'procedure StringToArray' in l:
                st_idx = i
            if 'function PathContains' in l:
                pc_idx = i
        self.assertIsNotNone(st_idx, "StringToArray not found")
        self.assertIsNotNone(pc_idx, "PathContains not found")
        self.assertLess(st_idx, pc_idx,
                        "StringToArray must be defined BEFORE PathContains")


class TestWorkflowSetupInvariants(unittest.TestCase):
    """Validate .github/workflows/artifact.yml setup-related invariants."""

    @classmethod
    def setUpClass(cls):
        wf_path = _PROJ / ".github" / "workflows" / "artifact.yml"
        if not wf_path.is_file():
            raise unittest.SkipTest(f"workflow not found: {wf_path}")
        cls.text = wf_path.read_text(encoding="utf-8")

    def test_setup_only_on_windows(self):
        """ISCC build must be guarded by 'if: matrix.platform == ''windows'''."""
        # Count ISCC occurrences and verify each has a windows guard nearby
        iscc_lines = [i for i, l in enumerate(self.text.splitlines())
                      if "ISCC" in l and "name:" not in l]
        self.assertGreater(len(iscc_lines), 0,
                           "No ISCC reference found in workflow")

        # The step should have a condition
        windows_conditions = len(re.findall(
            r"if:\s*matrix\.platform\s*==\s*'windows'", self.text))
        self.assertGreaterEqual(windows_conditions, 1,
                                "Missing 'if: matrix.platform == windows' guards")

    def test_setup_naming(self):
        """Setup output must follow AISC-{version}-windows-x86_64-setup.exe pattern."""
        self.assertIn("-setup", self.text,
                      "Setup filename must end with -setup.exe")

    def test_permissions_read_only(self):
        """Workflow must NOT have contents: write."""
        self.assertIn("contents: read", self.text,
                      "Missing contents: read permission")
        self.assertNotIn("contents: write", self.text,
                         "contents: write found — release capability not allowed")

    def test_setup_artifact_uploaded(self):
        """Setup artifact must be uploaded as a separate artifact."""
        self.assertIn("setup-windows-x86_64", self.text,
                      "Missing setup-windows-x86_64 artifact upload")

    def test_sha256sups_includes_setup(self):
        """Aggregate SHA256SUMS must include the setup exe hash."""
        self.assertIn("setup/AISC-*-setup.exe", self.text,
                      "Aggregate upload must include setup exe")

    def test_numeric_version_passed_to_iscc(self):
        """Workflow must pass /DMyNumericVersion= to ISCC."""
        self.assertIn("MyNumericVersion", self.text,
                      "Missing /DMyNumericVersion in ISCC invocation")

    def test_smoke_script_referenced(self):
        """Workflow should use packaging/windows/smoke_installer.ps1."""
        self.assertIn("smoke_installer.ps1", self.text,
                      "Missing reference to smoke_installer.ps1")


if __name__ == "__main__":
    unittest.main()
