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

import unittest

from aisc.cli.tutorial import session_bash_prelude


class TutorialPreludeTests(unittest.TestCase):
    def setUp(self):
        self.prelude = session_bash_prelude()

    def test_defines_and_exports_help_then_execs_interactive_bash(self):
        self.assertIn("help()", self.prelude)
        self.assertIn("export -f help", self.prelude)
        self.assertIn("exec bash", self.prelude)
        # The prelude must END with the exec — nothing runs after it.
        self.assertTrue(self.prelude.rstrip().endswith("exec bash"))

    def test_bare_help_prints_tutorial_with_args_delegating_to_builtin(self):
        # No-argument branch prints the tutorial…
        self.assertIn("if [ $# -eq 0 ]", self.prelude)
        self.assertIn("AISC Workbench 教学", self.prelude)
        # …while `help foo` must delegate to the builtin verbatim.
        self.assertIn('builtin help "$@"', self.prelude)

    def test_tutorial_covers_three_sections_and_exercise(self):
        for section in ("Claude Code", "Codex", "Workbench"):
            self.assertIn(section, self.prelude)
        self.assertIn("互动练习", self.prelude)
        self.assertIn('claude -p', self.prelude)

    def test_no_persistent_writes_in_prelude(self):
        # A-21766: the injection must not touch any file (no >, >> or tee).
        for forbidden in (">>", " > ", "tee "):
            self.assertNotIn(forbidden, self.prelude)


if __name__ == "__main__":
    unittest.main()
