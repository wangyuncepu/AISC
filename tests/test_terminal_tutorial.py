"""v2.1.7 S6 (Gate-S6/D10): the interactive-bash tutorial prelude.

Contract pins:
- rides ONLY the session-open argv (``bash -c <prelude>``); no image,
  profile, or workspace writes;
- defines a bare ``help`` that prints the tutorial; ``help <args>`` must
  delegate to the shell builtin (A-21765);
- ``export -f`` + ``exec bash`` so the interactive shell re-imports it;
- non-interactive behavior untouched (nothing here runs outside -it exec).
"""

from __future__ import annotations

import subprocess
import unittest

from aisc.cli.tutorial import help_function_env


class TutorialEnvTests(unittest.TestCase):
    def setUp(self):
        self.env = help_function_env()

    def test_encodes_help_as_a_bash_function_env_var(self):
        self.assertEqual(list(self.env), ["BASH_FUNC_help%%"])
        value = self.env["BASH_FUNC_help%%"]
        self.assertTrue(value.startswith("() {"), "bash function-serial form")
        # Bare help prints the tutorial; args delegate to the builtin.
        self.assertIn("AISC Workbench 教学", value)
        self.assertIn('builtin help "$@"', value)

    def test_tutorial_covers_three_sections_and_free_exercises(self):
        value = self.env["BASH_FUNC_help%%"]
        for section in ("Claude Code", "Codex", "Workbench"):
            self.assertIn(section, value)
        # A-21768: exercises are FREE by default — the billed one-shot
        # (claude -p) is clearly marked as optional/post-configuration.
        self.assertIn("上手练习", value)
        self.assertIn("claude --version", value)
        self.assertIn("产生用量", value)

    def test_no_pager_no_fake_quit_hint(self):
        # 2026-08-28 manual test: there is NO pager — the "退出教学: q" hint
        # promised an interaction that does not exist. It must never return.
        value = self.env["BASH_FUNC_help%%"]
        self.assertNotIn("退出教学", value)
        self.assertNotIn("q", value.split("上手练习")[1].split("\n")[0])

    def test_no_persistent_writes_in_the_function_body(self):
        # A-21766: the injection must not touch any file (no >, >> or tee).
        value = self.env["BASH_FUNC_help%%"]
        for forbidden in (">>", " > ", "tee "):
            self.assertNotIn(forbidden, value)

    def test_real_bash_imports_and_delegates(self):
        """Live proof (skipped when no bash exists): a bash that inherits the
        env var re-imports `help` as a function; `help cd` still reaches the
        builtin (A-21765)."""
        bash = None
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            "/bin/bash",
            "/usr/bin/bash",
        ):
            try:
                subprocess.run(
                    [candidate, "-c", "true"], capture_output=True, timeout=10
                )
                bash = candidate
                break
            except (OSError, subprocess.SubprocessError):
                continue
        if bash is None:
            self.skipTest("no bash available")

        probe = (
            "type -t help; "
            'help | head -1; '
            "help cd 2>&1 | head -1"
        )
        result = subprocess.run(
            [bash, "-c", probe],
            capture_output=True,
            timeout=15,
            env={"PATH": "/usr/bin:/bin", **self.env},
        )
        lines = result.stdout.decode("utf-8", errors="replace").splitlines()
        self.assertIn(lines[0], ("function", "file"))
        self.assertIn("AISC Workbench 教学", lines[1])
        self.assertIn("cd", lines[2])  # builtin help output, not the tutorial


if __name__ == "__main__":
    unittest.main()
