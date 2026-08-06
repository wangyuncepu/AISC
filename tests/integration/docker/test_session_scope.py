"""Integration: session open/list across project & temporary scope (S0.3 DoD).

S0.3 DoD: "四种 Session 在 project/temporary scope 均可启动". Bash is the
deterministic agent (no provider config required); Claude/Codex/cc-switch
interactive launches are covered by the Phase 1 实机 smoke gate. Skips without
Docker + image.
"""

import json
import unittest
import uuid

from tests.integration.docker._session_helpers import (
    BaseSessionIntegration,
    integration_ready,
    open_bash_session,
)


@unittest.skipUnless(integration_ready(), "requires Docker + super-claude:latest with aisc-session-wrapper")
class TestSessionScopeIntegration(BaseSessionIntegration):
    def test_empty_list_on_fresh_runtime(self):
        self.start_runtime("project")
        data = json.loads(self.session_list().stdout)["data"]
        self.assertEqual(data["sessions"], [])
        self.assertEqual(data["count"], 0)

    def test_bash_open_project_scope(self):
        self.start_runtime("project")
        sid = str(uuid.uuid4())
        code, _ = open_bash_session(self.aisc, self.workspace, self.runtime_id, sid)
        self.assertEqual(code, 0)
        recs = json.loads(self.session_list().stdout)["data"]["sessions"]
        match = [s for s in recs if s["session_id"] == sid]
        self.assertTrue(match, f"session {sid} not in list: {recs}")
        self.assertEqual(match[0]["agent"], "bash")
        self.assertEqual(match[0]["state"], "exited")
        self.assertEqual(match[0]["runtime_id"], self.runtime_id)

    def test_bash_open_temporary_scope(self):
        self.start_runtime("temporary")
        sid = str(uuid.uuid4())
        code, _ = open_bash_session(self.aisc, self.workspace, self.runtime_id, sid)
        self.assertEqual(code, 0)
        recs = json.loads(self.session_list().stdout)["data"]["sessions"]
        self.assertTrue(any(s["session_id"] == sid for s in recs))


if __name__ == "__main__":
    unittest.main()
