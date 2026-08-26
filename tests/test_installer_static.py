"""docker-resource-lifecycle C3: installer static contracts.

The installers must route every Docker mutation through the centralized
maintenance service — no reimplemented filter rules, no direct docker
rm/rmi chains (02 §2/§5). These tests pin the structural facts the plan
freezes so a regression reads as a red test, not as a shipped installer.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NSIS = REPO / "workbench" / "src-tauri" / "nsis" / "installer.nsi"
INNO = REPO / "packaging" / "windows" / "installer.iss"
INSTALL_PS1 = REPO / "packaging" / "install.ps1"
INSTALL_SH = REPO / "packaging" / "install.sh"
UNINSTALL_PS1 = REPO / "packaging" / "uninstall.ps1"
UNINSTALL_SH = REPO / "packaging" / "uninstall.sh"


def _lines(path: Path) -> list:
    return path.read_text(encoding="utf-8").splitlines()


class NsisStaticTests(unittest.TestCase):
    """C1: the Tauri NSIS main installer path."""

    def setUp(self):
        self.lines = _lines(NSIS)
        self.text = "\n".join(self.lines)

    def test_routes_cleanup_through_the_maintenance_service(self):
        self.assertIn("maintenance docker-cleanup --context uninstall", self.text)
        self.assertIn("maintenance docker-cleanup --context upgrade", self.text)
        self.assertIn("maintenance docker-rebuild", self.text)
        self.assertIn("maintenance docker-scan --context upgrade --format text", self.text)

    def test_no_direct_docker_mutation_commands(self):
        """The KI-4 duplicate discovery/ps/rm/rmi chain is gone. Manual
        commands inside user-facing LangStrings are fine (they quote the
        docker CLI for the USER to run); executable lines are not."""
        forbidden = ("docker ps -aq", "docker rm -f", "docker rmi -f",
                     "'where docker'", "un.FindDockerCli")
        for i, line in enumerate(self.lines, 1):
            if line.strip().startswith("LangString"):
                continue  # user-facing manual instructions
            for pat in forbidden:
                self.assertNotIn(
                    pat, line, f"line {i} reintroduces direct docker mutation: {pat}"
                )

    def test_cleanup_runs_before_any_file_deletion(self):
        """The sidecar performs the cleanup — it must still exist when the
        call runs (02 §3/C1: cleanup moved ahead of the File deletes)."""
        un_start = self.text.index("Section Uninstall")
        cleanup = self.text.index("Call un.CleanDockerResources")
        first_delete = self.text.index('Delete "$INSTDIR\\${MAINBINARYNAME}.exe"')
        self.assertTrue(un_start < cleanup < first_delete)

    def test_keepdocker_and_update_gates(self):
        self.assertIn("/KEEPDOCKER", self.text)
        self.assertIn("$KeepDockerMode <> 1", self.text)
        # /UPDATE never runs the uninstall-style image deletion.
        cleanup_block = self.text[self.text.index("StrCpy $DockerCleanupSkipped 0"):]
        self.assertIn("${AndIf} $UpdateMode <> 1", cleanup_block[:600])

    def test_toolchain_option_is_independent(self):
        self.assertIn("TOOLCHAIN_CLEANUP_CHECKBOX", self.text)
        self.assertIn("$ToolchainCheckboxState", self.text)
        self.assertIn("Call un.DeleteToolchains", self.text)
        # never folded into the container/image cleanup path: the cleanup
        # function BODY (to its FunctionEnd) never calls the toolchain path
        body = self.text[self.text.index("Function un.CleanDockerResources"):]
        body = body[: body.index("FunctionEnd")]
        self.assertNotIn("DeleteToolchains", body)

    def test_upgrade_capture_precedes_file_overwrite(self):
        capture = self.text.index("Call CaptureOldImageId")
        first_file = self.text.index('File "${MAINBINARYSRCPATH}')
        self.assertLess(capture, first_file)

    def test_upgrade_rebuild_after_install(self):
        rebuild = self.text.index("Call UpgradeDockerLifecycle")
        post_hook = self.text.index("NSIS_HOOK_POSTINSTALL")
        self.assertGreater(rebuild, post_hook)

    def test_manual_reinstall_counts_as_upgrade(self):
        """2026-08-26 smoke finding: the maintenance page's reinstall path
        never sets /UPDATE — the lifecycle must also fire when a previous
        install existed (fresh installs still skip)."""
        self.assertIn("$HadPreviousInstall", self.text)

    def test_sidecar_referenced_by_pattern_not_hardcoded_name(self):
        # aisc*.exe matches the observed plain aisc.exe install name AND
        # any arch-suffixed variant (2026-08-26 smoke finding).
        self.assertIn('FindFirst $0 $1 "$INSTDIR\\aisc*.exe"', self.text)
        self.assertNotIn("aisc-x86_64-pc-windows-msvc", self.text)

    def test_scan_parser_compares_real_control_chars(self):
        """2026-08-26 R2 smoke: "\\r"/"\\n" are literal backslash+letter in
        NSIS and never match a real line break — the whole scan collapsed
        into one unparsed line and the old-image id came back empty. The
        real chars are $-prefixed ($\r / $\n)."""
        body = self.text[self.text.index("Function ExtractDefaultImageId"):]
        body = body[: body.index("FunctionEnd")]
        self.assertIn('== "$\\r"', body)
        self.assertIn('== "$\\n"', body)
        self.assertNotIn('== "\\r"', body)
        self.assertNotIn('== "\\n"', body)

    def test_rebuild_omits_old_image_id_when_capture_failed(self):
        """A bare --old-image-id is an argparse usage error — the rebuild
        must have a no-old-id variant (the branch without the flag)."""
        self.assertIn(
            'maintenance docker-rebuild --root "$INSTDIR\\aisc-bundle" '
            "--tag super-claude:latest'",
            self.text,
        )

    def test_uninstall_docker_checkbox_defaults_on(self):
        """README 卸载契约: Docker 资源默认清理(预勾选, 取消勾选或
        /KEEPDOCKER 才保留); toolchain 与 app-data 默认保留。2026-08-26
        R3 smoke: 无 BM_SETCHECK 时全部默认未勾选, 与文档相反。"""
        self.assertIn("${NSD_Check} $DeleteDockerCheckbox", self.text)
        self.assertNotIn("${NSD_Check} $ToolchainCheckbox", self.text)
        self.assertNotIn("${NSD_Check} $DeleteAppDataCheckbox", self.text)

    def test_path_handles_are_pointer_sized(self):
        """2026-08-26 R4 smoke (critical): `i` System::Call slots truncate
        the 64-bit HKEY on x64 NSIS - RegQueryValueExW then always failed
        and every PATH rewrite wrote the empty fallback, wiping the user's
        entire PATH as an empty REG_SZ. Handles must ride pointer-sized
        (p) slots."""
        body = self.text[self.text.index("Function ${UN}PathRead"):]
        body = body[: body.index("FunctionEnd")]
        self.assertIn("*p .r1", body)
        self.assertIn("p 0x80000001", body)
        self.assertIn("(p r1,", body)
        self.assertNotIn("(i r1", body)
        self.assertNotIn("*i .r1", body)

    def test_path_never_written_after_failed_read(self):
        """Defense in depth: both PATH mutation paths (add + remove) bail
        when the registry read failed - an empty $PathRaw must never reach
        PathWrite."""
        self.assertIn("Var PathOk", self.text)
        self.assertGreaterEqual(self.text.count("${If} $PathOk <> 1"), 2)

    def test_no_docker_format_flag_in_nsis(self):
        """KI-5 lesson: literal docker CLI calls in this template can never
        use --format (double braces are handlebars). All docker argv now
        ride the sidecar, so no nsExec line may carry a docker CLI call at
        all — the maintenance commands are the only Docker surface."""
        for i, line in enumerate(self.lines, 1):
            if "nsExec::" not in line:
                continue
            self.assertNotIn(
                '" docker', line,
                f"line {i} shells out to docker directly instead of the sidecar",
            )


class InnoStaticTests(unittest.TestCase):
    """C2: the secondary Inno installer rides the same service."""

    def setUp(self):
        if not INNO.exists():
            self.skipTest("installer.iss not present")
        self.text = INNO.read_text(encoding="utf-8")

    def test_routes_through_the_maintenance_service(self):
        self.assertIn("maintenance docker-scan", self.text)
        self.assertIn("maintenance docker-cleanup", self.text)
        self.assertIn("maintenance docker-rebuild", self.text)

    def test_staged_helper_not_the_old_exe(self):
        """02 §C2.1: the NEW helper is extracted from THIS installer —
        the old aisc.exe may predate the maintenance commands."""
        self.assertIn("ExtractTemporaryFile('aisc-new.exe')", self.text)
        self.assertIn("dontcopy", self.text)

    def test_uninstall_cleanup_before_file_removal(self):
        """usUninstall fires before file deletion (usPostUninstall is too
        late) — the CALL inside the handler must sit between them."""
        handler = self.text.index("CurUninstallStepChanged")
        us = self.text.index("= usUninstall then", handler)
        cleanup = self.text.index("UninstallDockerCleanup", handler)
        post = self.text.index("= usPostUninstall then", handler)
        self.assertTrue(us < cleanup < post)


class PortableScriptStaticTests(unittest.TestCase):
    """D: portable install/uninstall scripts never reimplement filters."""

    def test_uninstall_ps1_routes_through_maintenance(self):
        if not UNINSTALL_PS1.exists():
            self.skipTest("portable scripts not present")
        text = UNINSTALL_PS1.read_text(encoding="utf-8")
        self.assertIn("maintenance docker-cleanup", text)
        self.assertNotIn("docker ps -aq --filter", text)
        self.assertNotIn("docker rmi -f", text)

    def test_uninstall_sh_routes_through_maintenance(self):
        if not UNINSTALL_SH.exists():
            self.skipTest("portable scripts not present")
        text = UNINSTALL_SH.read_text(encoding="utf-8")
        self.assertIn("maintenance docker-cleanup", text)
        self.assertNotIn("docker ps -aq --filter", text)
        self.assertNotIn("docker rmi -f", text)

    def test_keep_docker_flag_exists(self):
        """PowerShell switch is unhyphenated, POSIX uses hyphens — either
        spelling satisfies the keep option contract (01 §6)."""
        for path in (UNINSTALL_PS1, UNINSTALL_SH):
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8").lower().replace("-", "")
            self.assertIn("keepdockerresources", text,
                          f"{path.name} must honor the keep option")


if __name__ == "__main__":
    unittest.main()
