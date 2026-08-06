"""Integration: session terminate leaves no residue (S0.3 DoD).

S0.3 DoD: "terminate 后宿主与容器内均无残留进程". Covers:
- clean exit -> record is exited, no container residue
- terminate a live bash session (sleep) -> SIGTERM/SIGKILL, no residue
- terminate is idempotent on an already-exited session

Skips without Docker + image.
"""

import json
import os
import time
import unittest
import uuid

from tests.integration.docker._session_helpers import (
    BaseSessionIntegration,
    integration_ready,
    open_bash_session,
    start_session_bg,
)


@unittest.skipUnless(integration_ready(), "requires Docker + super-claude:latest with aisc-session-wrapper")
class TestSessionTerminationIntegration(BaseSessionIntegration):
    def test_clean_exit_no_residue(self):
        self.start_runtime("project")
        sid = str(uuid.uuid4())
        code, _ = open_bash_session(self.aisc, self.workspace, self.runtime_id, sid)
        self.assertEqual(code, 0)
        # No bash process lingers in the container (idle runtime runs sleep infinity).
        self.assertEqual(self.container_procs("bash"), [])

    def test_terminate_live_session_no_residue(self):
        self.start_runtime("project")
        sid = str(uuid.uuid4())
        proc, master = start_session_bg(
            self.aisc, self.workspace, self.runtime_id, sid,
            send="sleep 300\n", settle=2.0,
        )
        try:
            time.sleep(1.0)  # let the sleep child start
            recs = json.loads(self.session_list().stdout)["data"]["sessions"]
            self.assertTrue(
                any(s["session_id"] == sid and s["state"] == "running" for s in recs),
                f"expected running session {sid}: {recs}",
            )

            r = self.session_terminate(sid, grace=3.0)
            self.assertEqual(r.returncode, 0, f"terminate failed: {r.stderr}")
            self.assertEqual(json.loads(r.stdout)["data"]["state"], "exited")

            # The aisc open client exits once the container process group is gone.
            proc.wait(timeout=15)
            # No bash residue; only the runtime's PID 1 (sleep infinity) remains.
            self.assertEqual(self.container_procs("bash"), [])
            self.assertEqual(self.container_procs("sleep"), ["1"])
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            try:
                os.close(master)
            except OSError:
                pass

    def test_terminate_already_exited_is_idempotent(self):
        self.start_runtime("project")
        sid = str(uuid.uuid4())
        code, _ = open_bash_session(self.aisc, self.workspace, self.runtime_id, sid)
        self.assertEqual(code, 0)
        # First terminate on an already-exited session succeeds (idempotent).
        r = self.session_terminate(sid)
        self.assertEqual(r.returncode, 0, f"terminate(1): {r.stderr}")
        self.assertEqual(json.loads(r.stdout)["data"]["state"], "exited")
        # Second terminate returns the same terminal fact.
        r = self.session_terminate(sid)
        self.assertEqual(r.returncode, 0, f"terminate(2): {r.stderr}")
        self.assertEqual(json.loads(r.stdout)["data"]["state"], "exited")


if __name__ == "__main__":
    unittest.main()
