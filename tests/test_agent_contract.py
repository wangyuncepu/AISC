"""svc-3 (container web-service access): agent instruction contract tests.

`container/global-claude.md` ships as both CLAUDE.md (Claude) and AGENTS.md
(Codex, via the Dockerfile sed). These static checks pin the web-service
checklist so it cannot silently regress, and guard against examples that hand
a container-local URL to the user (the exact failure mode this feature fixes).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "container" / "global-claude.md"


class AgentGuideWebServicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = GUIDE.read_text(encoding="utf-8")

    def test_documents_all_three_helpers(self):
        for tool in ("aisc-web-expose", "aisc-web-unexpose", "aisc-web-list"):
            self.assertIn(tool, self.text, f"helper {tool} missing from agent guide")

    def test_checklist_orders_start_expose_verify_then_tell_user(self):
        expose_at = self.text.index("aisc-web-expose <port>")
        verify_at = self.text.index("aisc-web-list")
        self.assertLess(expose_at, verify_at)

    def test_forbids_container_localhost_as_user_url(self):
        self.assertIn("NOT reachable", self.text)

    def test_names_the_cli_url_source(self):
        self.assertIn("aisc runtime services", self.text)
        self.assertIn("--runtime-id", self.text)

    def test_no_copyable_container_localhost_example(self):
        """No literal `http://localhost:<digits>` example the user could copy.

        The guide needs the *word* localhost to explain the trap; what it must
        never contain is a concrete clickable container URL.
        """
        offenders = re.findall(r"http://(?:localhost|127\.0\.0\.1):[0-9]+", self.text)
        self.assertEqual(offenders, [])

    def test_helper_usage_matches_frozen_contract(self):
        """The guide's example must use the frozen flag spelling (--name)."""
        self.assertIn('--name "<short label>"', self.text)


if __name__ == "__main__":
    unittest.main()
