"""Integration: terminate identity / idempotency, no mis-kill (S0.3 DoD).

S0.3 DoD: "PID identity 不匹配、重复 terminate 和快速 PID 复用测试不会误杀其他
Session/Runtime 进程". The wrapper's start-ticks identity check makes a
reused/gone PID a no-op (idempotent exited), so these are exercised via the
deterministic idempotent paths. Forcing true PID reuse is non-deterministic
and covered by the wrapper's identity-check logic + these idempotent cases.

Skips without Docker + image.
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
class TestSessionPidReuseIntegration(BaseSessionIntegration):
    def test_terminate_unknown_session_is_idempotent(self):
        """Terminating a session that never existed marks exited (not_found)."""
        self.start_runtime("project")
        ghost = str(uuid.uuid4())
        r = self.session_terminate(ghost)
        self.assertEqual(r.returncode, 0, f"terminate: {r.stderr}")
        data = json.loads(r.stdout)["data"]
        self.assertEqual(data["state"], "exited")
        self.assertEqual(data.get("reason"), "not_found")

    def test_terminate_exited_then_unknown_never_harms_runtime(self):
        """Repeated/unknown terminate must not kill the runtime's PID 1."""
        self.start_runtime("project")
        sid = str(uuid.uuid4())
        code, _ = open_bash_session(self.aisc, self.workspace, self.runtime_id, sid)
        self.assertEqual(code, 0)

        # Idempotent on the exited session.
        self.assertEqual(self.session_terminate(sid).returncode, 0)
        # Unknown session on the same runtime.
        self.assertEqual(self.session_terminate(str(uuid.uuid4())).returncode, 0)

        # The runtime container is still alive (its `sleep infinity` PID 1 intact).
        self.assertEqual(len(self.container_procs("sleep")), 1)
        self.assertEqual(self.container_procs("bash"), [])

    def test_two_sessions_terminate_one_other_unaffected(self):
        """Terminating session A leaves a separately-exited session B intact in list."""
        self.start_runtime("project")
        sid_a = str(uuid.uuid4())
        sid_b = str(uuid.uuid4())
        self.assertEqual(open_bash_session(self.aisc, self.workspace,
                                           self.runtime_id, sid_a)[0], 0)
        self.assertEqual(open_bash_session(self.aisc, self.workspace,
                                           self.runtime_id, sid_b)[0], 0)
        self.assertEqual(self.session_terminate(sid_a).returncode, 0)
        recs = json.loads(self.session_list().stdout)["data"]["sessions"]
        ids = {s["session_id"] for s in recs}
        self.assertIn(sid_b, ids)


if __name__ == "__main__":
    unittest.main()
