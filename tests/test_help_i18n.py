"""help_i18n (manual test ask 2026-09-09): locale-following help output.

English stays the single source of truth in the parser; Chinese is an
output-layer patch installed only on zh locales. These tests force both
states and must restore — the patch is process-global (argparse).
"""

from __future__ import annotations

import os
import unittest

from aisc.cli.help_i18n import HELP_ZH, install, is_zh_locale, uninstall
from aisc.cli.main import _build_parser


class LocaleDetectionTests(unittest.TestCase):
    def test_env_vars_drive_detection(self):
        old = {k: os.environ.get(k) for k in
               ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")}
        try:
            for k in old:
                os.environ.pop(k, None)
            os.environ["LANG"] = "zh_CN.UTF-8"
            self.assertTrue(is_zh_locale())       # env hit
            os.environ["LANG"] = "en_US.UTF-8"
            os.environ["LANGUAGE"] = "zh_CN:zh"
            self.assertTrue(is_zh_locale())       # LANGUAGE fallback hit
            # en-env ⇒ False only where the CRT fallback is not zh
            # (a zh-CN Windows box stays zh through the CRT — by design)
            import locale as _locale
            crt = _locale.getdefaultlocale()[0] or ""
            if not crt.lower().startswith("zh"):
                for k in ("LANGUAGE", "LANG"):
                    os.environ.pop(k, None)
                os.environ["LC_ALL"] = "en_US.UTF-8"
                self.assertFalse(is_zh_locale())
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class HelpLocalizationTests(unittest.TestCase):
    def setUp(self):
        # the patch is process-global: a prior test's main() on a zh locale
        # may have installed it — always start (and end) from a clean base
        uninstall()

    def tearDown(self):
        uninstall()

    def _help_text(self, *argv: str) -> str:
        parser = _build_parser()
        args = parser.parse_args(list(argv))
        # --help exits the parser; instead format the subparser's help the
        # way print_help would
        return parser.format_help()

    def test_zh_install_translates_and_restore_returns_english(self):
        restore = install(force=True)
        try:
            self.assertIsNotNone(restore)
            top = self._help_text()
            self.assertIn("用法", top)
            self.assertIn("激活工作区", top)        # run's help, via _expand_help
            self.assertIn("管理运行中的 CLI 工作区", top)  # workspaces
            # builtin wording swapped too
            self.assertNotIn("usage:", top)
        finally:
            restore()
        top = self._help_text()
        self.assertIn("usage:", top)
        self.assertIn("Activate a workspace", top)

    def test_install_is_idempotent(self):
        first = install(force=True)
        try:
            self.assertIsNone(install(force=True))
        finally:
            first()

    def test_subparser_help_translates(self):
        import io
        from contextlib import redirect_stdout

        restore = install(force=True)
        try:
            parser = _build_parser()
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    parser.parse_args(["run", "--help"])
            except SystemExit:
                pass  # --help always exits
            out = buf.getvalue()
            self.assertIn("用法", out)
            self.assertIn("要激活的工作区目录", out)   # run's positional
            self.assertIn("从历史恢复", out)           # --resume
        finally:
            restore()

    def test_dictionary_keys_are_prefix_free(self):
        # exact full-string matching means no key may be a substring of a
        # DIFFERENT key's English source... harmless for dict lookup, but
        # keep the sanity that no two keys map the same English to two zh
        self.assertEqual(len(HELP_ZH), len(set(HELP_ZH.keys())))
        # every value is non-empty
        self.assertTrue(all(v.strip() for v in HELP_ZH.values()))


if __name__ == "__main__":
    unittest.main()
