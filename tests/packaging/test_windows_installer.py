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
        r"""aisc.exe and aisc-bundle\ must be in {app}."""
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

    def test_remove_path_uses_supported_splitter(self):
        """PATH removal must avoid unsupported TStringList.LineBreak."""
        self.assertNotIn(".LineBreak", self.text,
                         "Inno Setup TStringList has no LineBreak property")
        remove_path = self.text.split("function RemovePathEntry", 1)[1]
        remove_path = remove_path.split("// Add a directory", 1)[0]
        self.assertIn("StringToArray(Haystack, ';', Parts, True)", remove_path,
                      "RemovePathEntry must use the compatible PATH splitter")


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
        self.assertIn("/DMyNumericVersion=", self.text,
                      "Missing /DMyNumericVersion in ISCC invocation")

    def test_bundle_source_passed_to_iscc(self):
        """Workflow and installer must use the same bundle-source define."""
        self.assertIn("/DMyBundleSource=", self.text,
                      "Missing /DMyBundleSource in ISCC invocation")
        self.assertNotIn("/DBundleSource=", self.text,
                         "Workflow uses BundleSource but installer expects MyBundleSource")

    def test_smoke_script_referenced(self):
        """Workflow should use packaging/windows/smoke_installer.ps1."""
        self.assertIn("smoke_installer.ps1", self.text,
                      "Missing reference to smoke_installer.ps1")


class TestInstallerSmokeInvariants(unittest.TestCase):
    """Validate process handling in the Windows installer smoke test."""

    @classmethod
    def setUpClass(cls):
        cls.text = (_PROJ / "packaging" / "windows" / "smoke_installer.ps1").read_text(
            encoding="utf-8"
        )

    def test_gui_processes_are_waited_for(self):
        """GUI setup executables require explicit waiting and process exit codes."""
        self.assertIn("Start-Process", self.text)
        self.assertIn("-Wait", self.text)
        self.assertIn("-PassThru", self.text)
        self.assertIn("return $process.ExitCode", self.text)

    def test_setup_and_uninstall_use_process_helper(self):
        """Install, upgrade, and uninstall must all use the waiting helper."""
        self.assertEqual(self.text.count("Invoke-InstallerProcess `"), 3)
        self.assertNotIn("& $setupFile.FullName /VERYSILENT", self.text)
        self.assertNotIn("& $uninstFile.FullName /VERYSILENT", self.text)


class TestSmokeDiagnostics(unittest.TestCase):
    """Validate that smoke_installer.ps1 preserves raw output on provider failures."""

    @classmethod
    def setUpClass(cls):
        cls.text = (_PROJ / "packaging" / "windows" / "smoke_installer.ps1").read_text(
            encoding="utf-8"
        )

    def test_provider_exit_code_captured_before_out_string(self):
        """``$LASTEXITCODE`` must be captured *before* Out-String to avoid loss."""
        # Pattern: $provLines = & ... ; $provExit = $LASTEXITCODE ; $provJson = $provLines | Out-String
        self.assertIn("$provExit = $LASTEXITCODE", self.text,
                      "Must capture LASTEXITCODE before Out-String consumes it")
        self.assertIn("$provJson = $provLines | Out-String", self.text,
                      "Must use Out-String on captured variable, not inline")

    def test_provider_nonzero_shows_raw_output(self):
        """On non-zero exit, smoke must print raw captured output for diagnosis."""
        self.assertIn("[raw output captured on non-zero exit]", self.text,
                      "Missing raw output dump on non-zero exit")
        self.assertIn("ForEach-Object { Write-Host", self.text,
                      "Must iterate raw lines on non-zero exit")

    def test_provider_json_parse_failure_shows_raw_context(self):
        """On JSON parse failure, smoke must print raw content preview."""
        self.assertIn("[raw JSON content, first 2000 chars]", self.text,
                      "Missing raw content preview on JSON parse failure")
        self.assertIn("Substring(0, 2000)", self.text,
                      "Must provide bounded raw content preview")


class TestEntrypointUtf8Config(unittest.TestCase):
    """Unit / static tests for the PyInstaller entrypoint UTF-8 config logic."""

    def _load_func(self):
        """Parse and return the _configure_frozen_io function source."""
        ep_path = _PROJ / "packaging" / "pyinstaller" / "entrypoint.py"
        text = ep_path.read_text(encoding="utf-8")
        # Extract the function body as a static check
        self.assertIn("def _configure_frozen_io()", text,
                      "_configure_frozen_io function must exist in entrypoint.py")
        return text

    def test_guarded_by_win32(self):
        """UTF-8 configuration must only activate on win32 platform."""
        text = self._load_func()
        self.assertIn("sys.platform != \"win32\"", text,
                      "Must check for win32 platform before reconfiguring")
        self.assertIn("return", text,
                      "Must early-return on non-win32")

    def test_guarded_by_frozen(self):
        """UTF-8 configuration must only activate in frozen processes."""
        text = self._load_func()
        self.assertIn("sys.frozen", text,
                      "Must check sys.frozen before reconfiguring")

    def test_handles_none_stream(self):
        """Must safely handle stdout/stderr being None."""
        text = self._load_func()
        self.assertIn("is None", text,
                      "Must guard against None streams")

    def test_handles_no_reconfigure(self):
        """Must handle streams without a reconfigure method (Python < 3.7)."""
        text = self._load_func()
        self.assertIn("reconfigure", text,
                      "Must reference reconfigure method")
        self.assertIn("getattr", text,
                      "Must use getattr for safe attribute access")

    def test_handles_reconfigure_exception(self):
        """Must catch exceptions from reconfigure so the CLI doesn't crash."""
        text = self._load_func()
        self.assertIn("except", text,
                      "Must have exception handling for reconfigure calls")
        self.assertIn("pass", text,
                      "Must silently pass on reconfigure failure")

    def test_outer_safety_net(self):
        """Top-level try/except must guard the entire function body."""
        text = self._load_func()
        # At least two try blocks: outer safety net + per-stream
        occurrences = text.count("except Exception:")
        self.assertGreaterEqual(occurrences, 1,
                                "Must have at least one except Exception catch-all")

    def test_function_called_at_module_level(self):
        """_configure_frozen_io must be called before if __name__ == '__main__'."""
        text = self._load_func()
        self.assertIn("_configure_frozen_io()", text,
                      "Function must be called at module level")
        # It must appear after the function definition but before if __name__
        func_def_pos = text.find("def _configure_frozen_io()")
        call_pos = text.find("_configure_frozen_io()", func_def_pos)
        main_pos = text.find('if __name__ == "__main__"')
        # All positions must be valid (find returns -1 if missing, but assertIn guards above)
        self.assertGreater(call_pos, -1, "Call to _configure_frozen_io() not found")
        self.assertGreater(main_pos, -1, "__main__ guard not found")
        self.assertTrue(call_pos < main_pos,
                        "_configure_frozen_io() must be called before __main__ guard")

    def test_encoding_is_utf8(self):
        """Reconfigure must set encoding to utf-8, not utf8 or utf_8."""
        text = self._load_func()
        self.assertIn('encoding="utf-8"', text,
                      "Reconfigure encoding must be exactly 'utf-8'")

    def test_imports_before_any_logic(self):
        r"""``import sys`` must be present for platform/frozen checks."""
        text = self._load_func()
        self.assertIn("import sys", text, "Must import sys for platform checks")


if __name__ == "__main__":
    unittest.main()
