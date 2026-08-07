"""Unit tests for the container-side aisc-session-wrapper (S0.3).

Imports the wrapper as a module and exercises its pure logic directly:
UUID validation, /proc start-ticks parsing, env rebuild, atomic 0600 record
I/O, ``list`` aggregation, and ``terminate`` identity/idempotency. No Docker,
no image build required. The interactive ``open`` spawn path is covered by
tests/integration/docker/test_session_*.py.
"""

import importlib.util
import importlib.machinery
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_WRAPPER_PATH = Path(__file__).resolve().parents[1] / "container" / "aisc-session-wrapper"

_loader = importlib.machinery.SourceFileLoader("aisc_session_wrapper", str(_WRAPPER_PATH))
_spec = importlib.util.spec_from_loader("aisc_session_wrapper", _loader)
wrapper = importlib.util.module_from_spec(_spec)
_loader.exec_module(wrapper)

RT = "550e8400-e29b-41d4-a716-446655440000"
SID = "660e8400-e29b-41d4-a716-446655440000"

# The wrapper runs inside the Linux container; some logic uses /proc start-ticks
# and POSIX signals (os.killpg) that don't exist on Windows. Skip those on
# non-POSIX - Linux CI covers them fully.
posix_only = unittest.skipUnless(
    os.name == "posix", "aisc-session-wrapper uses /proc + POSIX signals (Linux container only)"
)


class TestUuidValidation(unittest.TestCase):
    def test_valid(self):
        assert wrapper._is_uuid_v4(SID)
        assert wrapper._is_uuid_v4("f47ac10b-58cc-4372-a567-0e02b2c3d479")

    def test_invalid(self):
        assert not wrapper._is_uuid_v4("not-a-uuid")
        assert not wrapper._is_uuid_v4("../../etc/passwd")
        assert not wrapper._is_uuid_v4("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # v1
        assert not wrapper._is_uuid_v4("")


@posix_only
class TestStartTicks(unittest.TestCase):
    def test_self_has_start_ticks(self):
        ticks = wrapper._read_start_ticks(os.getpid())
        assert isinstance(ticks, int) and ticks >= 0

    def test_dead_pid_returns_none(self):
        # A very high PID is effectively guaranteed not to exist.
        assert wrapper._read_start_ticks(4_000_000) is None


@posix_only
class TestIdentityMatch(unittest.TestCase):
    def test_matches_self(self):
        assert wrapper._identity_matches(os.getpid(), wrapper._read_start_ticks(os.getpid()))

    def test_mismatch_is_not_live(self):
        # A recorded ticks value that does not match the live process -> not live.
        assert not wrapper._identity_matches(os.getpid(), wrapper._read_start_ticks(os.getpid()) + 1)

    def test_dead_pid_not_live(self):
        assert not wrapper._identity_matches(4_000_000, 123)


class TestRebuildEnv(unittest.TestCase):
    def test_rebuilds_all_four_dirs(self):
        ctx = {
            "claude_config_dir": "/root/app/.claude",
            "codex_config_dir": "/root/app/.codex",
            "cc_switch_config_dir": "/root/app/.cc-switch",
        }
        env = wrapper._rebuild_env(ctx)
        assert env["CLAUDE_CONFIG_DIR"] == "/root/app/.claude"
        assert env["CODEX_CONFIG_DIR"] == "/root/app/.codex"
        assert env["CODEX_HOME"] == "/root/app/.codex"  # derived == CODEX_CONFIG_DIR
        assert env["CC_SWITCH_CONFIG_DIR"] == "/root/app/.cc-switch"

    def test_missing_fields_default_empty(self):
        env = wrapper._rebuild_env({})
        assert env["CLAUDE_CONFIG_DIR"] == ""
        assert env["CODEX_HOME"] == ""


class TestOpenContextCheck(unittest.TestCase):
    def test_open_rejects_context_runtime_id_mismatch(self):
        # The wrapper is a security boundary: a context whose runtime_id does
        # not match the request must be rejected before spawning any agent.
        import argparse
        args = argparse.Namespace(session_id=SID, runtime_id=RT, agent="bash")
        other = "ffffffff-ffff-4fff-8fff-ffffffffffff"
        with patch.object(wrapper, "_load_context", return_value={"runtime_id": other}):
            with self.assertRaises(SystemExit):
                wrapper._cmd_open(args)


class TestRecordIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aisc-wrap-io-")
        self.sessions_dir = os.path.join(self.tmp, "sessions")
        patcher = patch.object(wrapper, "SESSIONS_DIR", self.sessions_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_write_read_roundtrip(self):
        rec = {"schema_version": wrapper.SCHEMA_VERSION, "session_id": SID,
               "state": "running", "pid": 123, "start_ticks": 999}
        wrapper._write_record(rec, SID)
        out = wrapper._read_record(SID)
        assert out == rec

    @posix_only
    def test_record_file_is_0600(self):
        wrapper._write_record({"session_id": SID, "state": "running"}, SID)
        path = wrapper._record_path(SID)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600, f"expected 0600, got {oct(mode)}"

    def test_read_missing_returns_none(self):
        assert wrapper._read_record(SID) is None

    def test_no_other_record_corrupted(self):
        # Concurrent sessions must not corrupt each other (per-session tmp files).
        a = {"session_id": "a", "state": "running", "pid": 1}
        b = {"session_id": "b", "state": "running", "pid": 2}
        sid_a, sid_b = SID, "770e8400-e29b-41d4-a716-446655440000"
        wrapper._write_record(a, sid_a)
        wrapper._write_record(b, sid_b)
        assert wrapper._read_record(sid_a) == a
        assert wrapper._read_record(sid_b) == b


class TestList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aisc-wrap-list-")
        self.sessions_dir = os.path.join(self.tmp, "sessions")
        os.makedirs(self.sessions_dir)
        patcher = patch.object(wrapper, "SESSIONS_DIR", self.sessions_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _capture_list(self):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert wrapper._cmd_list(None) == 0
        return json.loads(buf.getvalue())

    def test_empty_dir(self):
        assert self._capture_list() == []

    def test_aggregates_records_skips_non_json(self):
        for sid, agent in [(SID, "claude"), ("770e8400-e29b-41d4-a716-446655440000", "bash")]:
            wrapper._write_record({"session_id": sid, "agent": agent, "state": "running"}, sid)
        # A non-JSON file must be skipped, not crash the listing.
        with open(os.path.join(self.sessions_dir, "garbage.json"), "w") as f:
            f.write("{not json")
        out = self._capture_list()
        agents = {r["agent"] for r in out}
        assert agents == {"claude", "bash"}


@posix_only
class TestTerminate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aisc-wrap-term-")
        self.sessions_dir = os.path.join(self.tmp, "sessions")
        os.makedirs(self.sessions_dir)
        patcher = patch.object(wrapper, "SESSIONS_DIR", self.sessions_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _capture_terminate(self, sid, grace=5.0):
        import argparse, contextlib, io
        args = argparse.Namespace(session_id=sid, runtime_id=RT, grace=grace)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert wrapper._cmd_terminate(args) == 0
        return json.loads(buf.getvalue())

    def test_unknown_session_is_not_found(self):
        out = self._capture_terminate(SID)
        assert out["state"] == "exited"
        assert out["reason"] == "not_found"

    def test_already_terminal_is_idempotent(self):
        rec = {"session_id": SID, "state": "exited", "exit_code": 0, "pid": 12345,
               "pgid": 12345, "start_ticks": 1, "reason": "process_exit"}
        wrapper._write_record(rec, SID)
        out = self._capture_terminate(SID)
        # Idempotent: returns the same terminal fact unchanged.
        assert out["state"] == "exited"
        assert out["reason"] == "process_exit"

    def test_identity_mismatch_marks_exited_without_signaling(self):
        # A "running" record whose PID/start-ticks no longer match (dead or reused)
        # must be marked exited WITHOUT sending any signal (no killpg call).
        rec = {"session_id": SID, "state": "running", "pid": 4_000_000,
               "pgid": 4_000_000, "start_ticks": 1, "reason": ""}
        wrapper._write_record(rec, SID)
        with patch("os.killpg") as killpg:
            out = self._capture_terminate(SID)
            killpg.assert_not_called()  # never signal a mismatched identity
        assert out["state"] == "exited"
        assert out["reason"] == "user_close"

    def test_live_session_signals_then_marks_exited(self):
        # Own process as the "live agent": identity matches, so TERM is sent.
        # No sid recorded -> fallback path signals the agent's own pgid.
        me = os.getpid()
        rec = {"session_id": SID, "state": "running", "pid": me,
               "pgid": me,
               "start_ticks": wrapper._read_start_ticks(me), "reason": ""}
        wrapper._write_record(rec, SID)
        sent = []
        with patch("os.killpg", side_effect=lambda p, s: sent.append((p, s))):
            out = self._capture_terminate(SID, grace=0.1)
        assert out["state"] == "exited"
        # At least SIGTERM was sent to the agent's process group.
        assert any(s == wrapper.signal.SIGTERM for _, s in sent)

    def test_signal_targets_spares_session_leader(self):
        """The open wrapper (pgrp == sid) is spared so it can reap the agent;
        the agent's group and job-child groups are signalled."""
        sent = []
        with patch.object(wrapper, "_pgrps_in_session", return_value={167, 173, 174}):
            with patch("os.killpg", side_effect=lambda p, s: sent.append((p, s))):
                wrapper._signal_targets(167, 173, wrapper.signal.SIGTERM)
        pgrps = {p for p, _ in sent}
        assert 173 in pgrps and 174 in pgrps  # agent + job child signalled
        assert 167 not in pgrps  # session leader (open wrapper) spared
        assert all(s == wrapper.signal.SIGTERM for _, s in sent)


if __name__ == "__main__":
    unittest.main()
