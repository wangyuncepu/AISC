"""Static validation of macOS .pkg build script, uninstaller, and workflow.
Linux-only — does not require macOS or pkgbuild.
"""

import os
import re
import sys
import unittest
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJ))


class TestMacOSBuildScript(unittest.TestCase):
    """Validate packaging/macos/build_pkg.sh invariants."""

    @classmethod
    def setUpClass(cls):
        p = _PROJ / "packaging" / "macos" / "build_pkg.sh"
        if not p.is_file():
            raise unittest.SkipTest(f"build_pkg.sh not found: {p}")
        cls.text = p.read_text(encoding="utf-8")

    def test_identifier_stable(self):
        """Identifier must be com.aisc.cli — do not change after first release."""
        self.assertIn('IDENTIFIER="com.aisc.cli"', self.text,
                      "Missing or wrong IDENTIFIER")

    def test_relative_symlink(self):
        """Symlink creation command must use relative target: ../lib/aisc/aisc."""
        # The ln -sf command must use a relative path (not absolute)
        self.assertTrue(
            ".." in self.text and "lib/aisc/aisc" in self.text,
            "Symlink target must be relative (../lib/aisc/aisc)"
        )
        # The actual ln command must create a relative link
        self.assertIn("ln -sf ../lib/aisc/aisc", self.text,
                      "ln command must use relative symlink target")

    def test_layout_usr_local(self):
        """Payload must use /usr/local/lib/aisc and /usr/local/bin."""
        self.assertIn("usr/local/lib/aisc", self.text,
                      "Missing /usr/local/lib/aisc in payload layout")
        self.assertIn("usr/local/bin", self.text,
                      "Missing /usr/local/bin in payload layout")

    def test_version_normalisation(self):
        """pkgbuild version must be extracted X.Y.Z from display version."""
        self.assertIn("sed -nE", self.text,
                      "Version normalisation using sed not found")
        self.assertIn("receipt_version", self.text,
                      "Missing receipt_version variable")

    def test_input_validation(self):
        """Must validate executable, bundle, and required files."""
        self.assertIn("-x", self.text,
                      "Must check executable is executable")
        self.assertIn("container/Dockerfile", self.text,
                      "Must verify container/Dockerfile in bundle")
        self.assertIn("config/versions.env", self.text,
                      "Must verify config/versions.env in bundle")

    def test_pkgbuild_command(self):
        """Must use pkgbuild with --identifier, --version, --root, --install-location."""
        self.assertIn("pkgbuild", self.text)
        self.assertIn("--identifier", self.text)
        self.assertIn("--version", self.text)
        self.assertIn("--root", self.text)
        self.assertIn('--install-location "/"', self.text)

    def test_no_productbuild(self):
        """Must use pkgbuild (component package), not productbuild."""
        self.assertNotIn("productbuild", self.text,
                         "Do not use productbuild — pkgbuild is sufficient")

    def test_output_naming(self):
        """Output must be AISC-{version}-macos-arm64.pkg."""
        self.assertIn('PKG_NAME="AISC-${VERSION}-macos-arm64"', self.text,
                      "PKG naming must follow AISC-{version}-macos-arm64")

    def test_sha256_sidecar(self):
        """Must generate .sha256 sidecar."""
        self.assertIn(".sha256", self.text,
                      "Missing .sha256 sidecar generation")

    def test_trap_cleanup(self):
        """Must trap EXIT for temp dir cleanup and cover BOTH ROOT_DIR and SCRIPTS_DIR."""
        self.assertIn("trap cleanup EXIT", self.text,
                      "Missing EXIT trap for temp dir cleanup")
        self.assertIn('"$ROOT_DIR" "$SCRIPTS_DIR"', self.text,
                      "cleanup must remove BOTH ROOT_DIR and SCRIPTS_DIR")

    def test_tmpdir_respected(self):
        """Build script must use TMPDIR env var for temp dirs."""
        self.assertIn('${TMPDIR:-/tmp}', self.text,
                      "Must use TMPDIR with /tmp default for temp directories")


class TestMacOSUninstallScript(unittest.TestCase):
    """Validate the runtime uninstall.sh embedded in the .pkg payload."""

    @classmethod
    def setUpClass(cls):
        p = _PROJ / "packaging" / "macos" / "build_pkg.sh"
        if not p.is_file():
            raise unittest.SkipTest(f"build_pkg.sh not found: {p}")
        cls.text = p.read_text(encoding="utf-8")

    def test_uninstall_root_check(self):
        """Uninstall must require root (sudo)."""
        self.assertIn('id -u', self.text,
                      "Uninstall must check for root")
        self.assertIn('-ne 0', self.text,
                      "Uninstall must exit if not root")

    def test_uninstall_symlink_check(self):
        """Uninstall must verify symlink target before removing."""
        self.assertIn("readlink", self.text,
                      "Uninstall must check symlink target with readlink")
        self.assertIn("expected", self.text,
                      "Uninstall must compare against expected symlink target")

    def test_uninstall_preserves_home(self):
        """Uninstall must NOT delete ~/.aisc or ~/.cc-config."""
        self.assertNotIn("rm -rf ~/.aisc", self.text,
                         "Uninstall must NOT delete ~/.aisc")
        self.assertNotIn("rm -rf ~/.cc-config", self.text,
                         "Uninstall must NOT delete ~/.cc-config")

    def test_uninstall_forgets_receipt(self):
        """Uninstall should call pkgutil --forget."""
        self.assertIn("pkgutil --forget", self.text,
                      "Uninstall must forget pkg receipt")

    def test_uninstall_no_paths_d(self):
        """Uninstall must NOT use /etc/paths.d."""
        self.assertNotIn("/etc/paths.d", self.text,
                         "Do not use /etc/paths.d — symlink is sufficient")

    def test_preinstall_target_volume(self):
        """Preinstall must use $3 (DSTROOT) for target volume safety."""
        # The preinstall script (embedded in build_pkg.sh) uses DSTROOT="${3:-/}"
        self.assertIn('DSTROOT="${3:-', self.text,
                      "Preinstall must use DSTROOT ($3) for alternate root safety")


class TestWorkflowMacOSInvariants(unittest.TestCase):
    """Validate .github/workflows/artifact.yml macOS .pkg invariants."""

    @classmethod
    def setUpClass(cls):
        wf = _PROJ / ".github" / "workflows" / "artifact.yml"
        if not wf.is_file():
            raise unittest.SkipTest(f"workflow not found: {wf}")
        cls.text = wf.read_text(encoding="utf-8")

    def test_pkg_only_on_macos(self):
        """pkg build must be guarded by matrix.platform == 'macos'."""
        pkg_guards = re.findall(
            r"if:\s*matrix\.platform\s*==\s*'macos'", self.text
        )
        # At minimum: build step and upload step are gated
        self.assertGreaterEqual(len(pkg_guards), 2,
                                "Need at least 2 macos-platform guards (build + upload)")

    def test_pkg_artifact_name(self):
        """macOS pkg artifact must be named pkg-macos-arm64."""
        self.assertIn("pkg-macos-arm64", self.text,
                      "Missing pkg-macos-arm64 artifact name")

    def test_pkg_not_in_archive_pattern(self):
        """pkg must NOT be in archive-* pattern (would break aggregate parser)."""
        # archive-* upload should NOT contain .pkg
        # Find the archive upload block
        arch_upload = re.search(
            r"name:\s*archive-\$\{\{.*?\}\}.*?path:\s*\|(.*?)(?=\n\s*- name:|\n\s*if:|\Z)",
            self.text, re.DOTALL
        )
        if arch_upload:
            self.assertNotIn(".pkg", arch_upload.group(1),
                             ".pkg must NOT be in archive-* upload")

    def test_aggregate_downloads_pkg(self):
        """Aggregate must download pkg-macos-arm64 artifact."""
        self.assertIn("pkg-macos-arm64", self.text,
                      "Aggregate must download pkg-macos-arm64")

    def test_aggregate_includes_pkg_in_upload(self):
        """Final aggregate upload must include .pkg files."""
        # The upload aggregated artifact step should have pkg files
        self.assertIn("pkg/", self.text,
                      "Aggregate upload must include pkg directory")

    def test_build_pkg_script_referenced(self):
        """Workflow must call packaging/macos/build_pkg.sh."""
        self.assertIn("packaging/macos/build_pkg.sh", self.text,
                      "Workflow must reference build_pkg.sh")

    def test_permissions_read_only(self):
        """Top-level workflow permissions must be contents: read.
        Job-level permissions may request contents: write (e.g. release job)."""
        # Check top-level permissions block (before jobs:)
        top_perm = self.text.split("jobs:")[0]
        self.assertIn("contents: read", top_perm)
        self.assertNotIn("contents: write", top_perm)

    def test_macos_sha256_sidecar_verified(self):
        """Workflow must verify pkg SHA256 via shasum -c."""
        self.assertIn("shasum -a 256 -c", self.text,
                      "Missing shasum -c sidecar verification for pkg")

    def test_workflow_bom_no_head_pipe(self):
        """Workflow must write BOM to file first, not pipe to head (avoid SIGPIPE 141)."""
        self.assertIn("bom.txt", self.text,
                      "Missing bom.txt — BOM must be written to file before display")

    def test_workflow_symlink_target_verified(self):
        """Workflow must verify symlink target via readlink or BOM grep."""
        self.assertTrue(
            "readlink" in self.text or "grep" in self.text,
            "Workflow must verify symlink target is ../lib/aisc/aisc"
        )

    def test_aggregate_no_bogus_cp(self):
        """Aggregate pkg step must NOT have bogus self-copy."""
        self.assertNotIn('cp "$f" "../pkg/$(basename "$f")"',
                         self.text,
                         "Remove bogus self-copy in aggregate pkg step")


class TestReadmeMacOSInvariants(unittest.TestCase):
    """Validate README_USER.md macOS .pkg documentation."""

    @classmethod
    def setUpClass(cls):
        p = _PROJ / "README_USER.md"
        if not p.is_file():
            raise unittest.SkipTest(f"README_USER.md not found: {p}")
        cls.text = p.read_text(encoding="utf-8")

    def test_pkg_recommended_method(self):
        """macOS section must recommend .pkg as primary method."""
        self.assertIn(".pkg", self.text,
                      "README must mention .pkg installer")

    def test_apple_silicon_only(self):
        """README must state Apple Silicon only for .pkg."""
        self.assertTrue(
            "arm64" in self.text.lower() or "Apple Silicon" in self.text,
            "README must mention arm64 / Apple Silicon"
        )

    def test_gatekeeper_instructions(self):
        """README must explain Gatekeeper bypass via Settings, not recommend global disable."""
        self.assertIn("隐私与安全性", self.text,
                      "README must reference 系统设置 → 隐私与安全性")
        # "spctl --master-disable" may appear in a negative context
        # (i.e. warning against it).  Verify it exists only as a warning.
        idx = self.text.find("spctl --master-disable")
        if idx >= 0:
            context = self.text[max(0,idx-50):idx+60]
            self.assertIn("不要", context,
                          f"spctl --master-disable must only appear as a warning, not a recommendation. Context: ...{context}...")

    def test_admin_password_mentioned(self):
        """README must state that .pkg requires administrator password."""
        self.assertIn("管理员", self.text,
                      "README must mention administrator password requirement")

    def test_uninstall_command(self):
        """README must show sudo uninstall command."""
        self.assertIn("sudo", self.text,
                      "README must show sudo for uninstall")
        self.assertIn("/usr/local/lib/aisc/uninstall.sh", self.text,
                      "README must show correct uninstall path")

    def test_portable_backup_mentioned(self):
        """README must mention tar.gz + install.sh as portable backup option."""
        self.assertIn("install.sh", self.text,
                      "README must mention install.sh as portable backup")

    def test_config_preserved_mentioned(self):
        """README must state user config is preserved on uninstall."""
        self.assertIn("~/.aisc", self.text,
                      "README must mention ~/.aisc preservation")

    def test_no_global_gatekeeper_disable_recommended(self):
        """README must warn against spctl --master-disable, not recommend it."""
        idx = self.text.find("spctl --master-disable")
        if idx >= 0:
            context = self.text[max(0,idx-50):idx+60]
            self.assertIn("不要", context,
                          f"spctl --master-disable must be in a warning context. Found: ...{context}...")


if __name__ == "__main__":
    unittest.main()
