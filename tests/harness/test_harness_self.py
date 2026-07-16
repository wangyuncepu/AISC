"""Self-tests for ``tests.harness.test_runner`` — RFC ``aisc.cli/v1`` protocol.

Uses real subprocess calls for CliRunner and real RFC schema samples for
JSON envelope / JSONL stream assertions.

Protocol reference: ``docs/rfc/aisc-cli-v1.md``.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest

from tests.harness.test_runner import (
    CliRunner,
    RunResult,
    assert_json_envelope,
    assert_jsonl_protocol,
    parse_json,
    parse_json_envelope,
    parse_jsonl,
)


# ============================================================================
# RFC sample data — kept inline so the contract is self-documenting
# ============================================================================

_RFC_SUCCESS_ENVELOPE = """\
{
  "meta": {
    "protocol": "aisc.cli/v1",
    "command": "version",
    "exit_code": 0,
    "timestamp": "2026-07-17T12:00:00Z",
    "version": "3.0.0",
    "run_id": "550e8400-e29b-41d4-a716-446655440000"
  },
  "data": {
    "cli_version": "3.0.0",
    "bundle_version": "3.0.0",
    "contract_version": "1",
    "image_version": "3.0.0",
    "claude_version": "1.0.37",
    "python_version": "3.11.10"
  },
  "errors": []
}"""

_RFC_ERROR_ENVELOPE = """\
{
  "meta": {
    "protocol": "aisc.cli/v1",
    "command": "build",
    "exit_code": 3,
    "timestamp": "2026-07-17T12:00:00Z",
    "version": "3.0.0",
    "run_id": "550e8400-e29b-41d4-a716-446655440000"
  },
  "data": null,
  "errors": [
    {
      "code": "AISC_ERR_DOCKER_UNAVAILABLE",
      "message": "Docker daemon is not running. Start Docker and retry.",
      "hint": "systemctl start docker"
    }
  ]
}"""

# RFC §3.5 complete build stream (6 events, terminal = build.complete)
_RFC_BUILD_STREAM_LINES = [
    {"protocol": "aisc.cli/v1", "command": "build",
     "run_id": "550e8400-e29b-41d4-a716-446655440000",
     "seq": 1, "type": "build.start",
     "ts": "2026-07-17T12:00:00Z",
     "data": {"image_name": "aisc:3.0.0"}},
    {"protocol": "aisc.cli/v1", "command": "build",
     "run_id": "550e8400-e29b-41d4-a716-446655440000",
     "seq": 2, "type": "build.step.start",
     "ts": "2026-07-17T12:00:01Z",
     "data": {"step": "pull_base_image"}},
    {"protocol": "aisc.cli/v1", "command": "build",
     "run_id": "550e8400-e29b-41d4-a716-446655440000",
     "seq": 3, "type": "build.step.complete",
     "ts": "2026-07-17T12:00:45Z",
     "data": {"step": "pull_base_image", "status": "ok",
              "digest": "sha256:abc123..."}},
    {"protocol": "aisc.cli/v1", "command": "build",
     "run_id": "550e8400-e29b-41d4-a716-446655440000",
     "seq": 4, "type": "build.step.start",
     "ts": "2026-07-17T12:00:45Z",
     "data": {"step": "build_context"}},
    {"protocol": "aisc.cli/v1", "command": "build",
     "run_id": "550e8400-e29b-41d4-a716-446655440000",
     "seq": 5, "type": "build.step.complete",
     "ts": "2026-07-17T12:04:00Z",
     "data": {"step": "build_context", "status": "ok"}},
    {"protocol": "aisc.cli/v1", "command": "build",
     "run_id": "550e8400-e29b-41d4-a716-446655440000",
     "seq": 6, "type": "build.complete",
     "ts": "2026-07-17T12:04:01Z",
     "data": {"image_tag": "aisc:3.0.0", "exit_code": 0}},
]


# ============================================================================
# CliRunner basic execution  (unchanged semantics, kept from S1)
# ============================================================================

class CliRunnerBasicTest(unittest.TestCase):
    """Success / non-zero / stderr / env / cwd / stdin / timeout / env_clear."""

    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_success_exit_zero(self) -> None:
        result = self.runner.run([sys.executable, "-c", "print('hello')"])
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(result.timed_out)
        self.assertIn("hello", result.stdout)

    def test_nonzero_exit(self) -> None:
        result = self.runner.run(
            [sys.executable, "-c", "import sys; sys.exit(42)"]
        )
        self.assertEqual(result.exit_code, 42)
        self.assertFalse(result.timed_out)

    def test_stderr_capture(self) -> None:
        result = self.runner.run(
            [
                sys.executable,
                "-c",
                "import sys; print('out'); print('err', file=sys.stderr)",
            ]
        )
        self.assertIn("out", result.stdout)
        self.assertIn("err", result.stderr)

    def test_env_injection(self) -> None:
        result = self.runner.run(
            [
                sys.executable,
                "-c",
                "import os; print(os.environ.get('AISC_H_TESTVAR', 'MISSING'))",
            ],
            env={"AISC_H_TESTVAR": "set-by-harness"},
        )
        self.assertIn("set-by-harness", result.stdout)

    def test_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.runner.run(
                [sys.executable, "-c", "import os; print(os.getcwd())"],
                cwd=tmpdir,
            )
            self.assertEqual(
                os.path.realpath(result.stdout.strip()),
                os.path.realpath(tmpdir),
            )

    def test_stdin_input(self) -> None:
        result = self.runner.run(
            [sys.executable, "-c", "import sys; print('got:', sys.stdin.read())"],
            input_text="hello-stdin",
        )
        self.assertIn("hello-stdin", result.stdout)

    def test_timeout(self) -> None:
        result = self.runner.run(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            timeout=0.1,
        )
        self.assertTrue(result.timed_out)
        self.assertEqual(result.exit_code, -1)

    def test_env_clear_isolation(self) -> None:
        os.environ["AISC_H_LEAK_VAR"] = "should-not-appear"
        try:
            result = self.runner.run(
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ.get('AISC_H_LEAK_VAR', 'CLEAN'))",
                ],
                env_clear=True,
            )
            self.assertIn("CLEAN", result.stdout)
        finally:
            del os.environ["AISC_H_LEAK_VAR"]

    def test_env_clear_keeps_path(self) -> None:
        result = self.runner.run(
            [
                sys.executable,
                "-c",
                "import os; print('OK' if os.environ.get('PATH') else 'NO_PATH')",
            ],
            env_clear=True,
        )
        self.assertIn("OK", result.stdout)

    def test_env_clear_with_explicit_env(self) -> None:
        result = self.runner.run(
            [
                sys.executable,
                "-c",
                "import os; print(os.environ.get('AISC_H_MYVAR', 'X'))",
            ],
            env={"AISC_H_MYVAR": "explicit"},
            env_clear=True,
        )
        self.assertIn("explicit", result.stdout)


# ============================================================================
# JSON Envelope — strict RFC §2 / §7.1
# ============================================================================

class JsonEnvelopeTest(unittest.TestCase):
    """parse_json / parse_json_envelope / assert_json_envelope (RFC)."""

    # -- parse_json (unchanged) -----------------------------------------------

    def test_parse_json_valid(self) -> None:
        self.assertEqual(parse_json('{"a": 1}'), {"a": 1})

    def test_parse_json_invalid(self) -> None:
        self.assertIsNone(parse_json("not json"))

    # -- parse_json_envelope — strict mode ------------------------------------

    def test_parse_envelope_valid_pure_json(self) -> None:
        result = parse_json_envelope(_RFC_SUCCESS_ENVELOPE)
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("meta", {}).get("protocol"), "aisc.cli/v1")  # type: ignore[union-attr]

    def test_parse_envelope_rejects_mixed_prefix(self) -> None:
        """RFC: stdout must be pure JSON — prefix text rejected."""
        text = 'prefix noise\n' + _RFC_SUCCESS_ENVELOPE
        self.assertIsNone(parse_json_envelope(text))

    def test_parse_envelope_rejects_mixed_suffix(self) -> None:
        text = _RFC_SUCCESS_ENVELOPE + '\nsuffix noise'
        self.assertIsNone(parse_json_envelope(text))

    def test_parse_envelope_rejects_array_toplevel(self) -> None:
        """Top-level must be object, not array."""
        self.assertIsNone(parse_json_envelope("[1, 2, 3]"))

    def test_parse_envelope_returns_none_for_string(self) -> None:
        self.assertIsNone(parse_json_envelope('"just a string"'))

    # -- assert_json_envelope — success path ----------------------------------

    def test_rfc_success_envelope_passes(self) -> None:
        r = RunResult(stdout=_RFC_SUCCESS_ENVELOPE, stderr="", exit_code=0)
        data = assert_json_envelope(r)
        self.assertEqual(data["meta"]["command"], "version")

    def test_rfc_error_envelope_passes(self) -> None:
        r = RunResult(stdout=_RFC_ERROR_ENVELOPE, stderr="", exit_code=3)
        data = assert_json_envelope(r)
        self.assertEqual(len(data["errors"]), 1)
        self.assertEqual(data["errors"][0]["code"], "AISC_ERR_DOCKER_UNAVAILABLE")

    def test_expected_fields_top_level_extra_check(self) -> None:
        r = RunResult(stdout=_RFC_SUCCESS_ENVELOPE, stderr="", exit_code=0)
        # expected_fields is retained for top-level additional assertions
        data = assert_json_envelope(r, expected_fields={"data": json.loads(_RFC_SUCCESS_ENVELOPE)["data"]})
        self.assertIn("cli_version", data["data"])

    # -- assert_json_envelope — meta validation -------------------------------

    def test_rejects_missing_meta(self) -> None:
        r = RunResult(stdout='{"data":{},"errors":[]}', stderr="", exit_code=0)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    def test_rejects_wrong_protocol(self) -> None:
        d = json.loads(_RFC_SUCCESS_ENVELOPE)
        d["meta"]["protocol"] = "aisc.cli/v2"
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=0)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    def test_rejects_empty_command(self) -> None:
        d = json.loads(_RFC_SUCCESS_ENVELOPE)
        d["meta"]["command"] = ""
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=0)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    def test_rejects_exit_code_mismatch(self) -> None:
        """meta.exit_code must equal RunResult.exit_code."""
        d = json.loads(_RFC_SUCCESS_ENVELOPE)
        d["meta"]["exit_code"] = 0
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=1)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    def test_rejects_empty_timestamp(self) -> None:
        d = json.loads(_RFC_SUCCESS_ENVELOPE)
        d["meta"]["timestamp"] = ""
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=0)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    def test_rejects_empty_version(self) -> None:
        d = json.loads(_RFC_SUCCESS_ENVELOPE)
        d["meta"]["version"] = ""
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=0)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    def test_rejects_empty_run_id(self) -> None:
        d = json.loads(_RFC_SUCCESS_ENVELOPE)
        d["meta"]["run_id"] = ""
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=0)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    # -- assert_json_envelope — errors semantics ------------------------------

    def test_rejects_success_with_nonempty_errors(self) -> None:
        """exit_code=0 → errors must be []."""
        d = json.loads(_RFC_ERROR_ENVELOPE)
        d["meta"]["exit_code"] = 0
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=0)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    def test_rejects_failure_with_empty_errors(self) -> None:
        """exit_code != 0 → errors must have ≥ 1 item."""
        d = json.loads(_RFC_SUCCESS_ENVELOPE)
        d["meta"]["exit_code"] = 1
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=1)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    def test_rejects_error_missing_code(self) -> None:
        d = json.loads(_RFC_ERROR_ENVELOPE)
        del d["errors"][0]["code"]
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=3)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    def test_rejects_error_missing_message(self) -> None:
        d = json.loads(_RFC_ERROR_ENVELOPE)
        del d["errors"][0]["message"]
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=3)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    def test_accepts_error_hint_none(self) -> None:
        """hint may be None (null in JSON)."""
        d = json.loads(_RFC_ERROR_ENVELOPE)
        d["errors"][0]["hint"] = None
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=3)
        assert_json_envelope(r)  # must not raise

    def test_rejects_data_wrong_type(self) -> None:
        """data must be dict or None."""
        d = json.loads(_RFC_SUCCESS_ENVELOPE)
        d["data"] = "not an object"
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=0)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)

    def test_rejects_errors_not_list(self) -> None:
        d = json.loads(_RFC_SUCCESS_ENVELOPE)
        d["errors"] = "not a list"
        r = RunResult(stdout=json.dumps(d), stderr="", exit_code=0)
        with self.assertRaises(AssertionError):
            assert_json_envelope(r)


# ============================================================================
# JSONL Event Stream — strict RFC §3 / §7.2
# ============================================================================

class JsonlStreamTest(unittest.TestCase):
    """parse_jsonl / assert_jsonl_protocol (RFC)."""

    # -- parse_jsonl ----------------------------------------------------------

    def test_parse_jsonl_valid(self) -> None:
        lines = parse_jsonl('{"seq":1}\n{"seq":2}\n{"seq":3}\n')
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], {"seq": 1})

    def test_parse_jsonl_skips_blank(self) -> None:
        lines = parse_jsonl('{"a":1}\n\n{"b":2}\n   \n{"c":3}')
        self.assertEqual(len(lines), 3)

    def test_parse_jsonl_marks_invalid(self) -> None:
        lines = parse_jsonl('{"a":1}\nnot-json\n{"c":3}')
        self.assertEqual(len(lines), 3)
        self.assertIsNone(lines[1])

    # -- RFC stream: full build example ---------------------------------------

    def test_rfc_build_stream_passes(self) -> None:
        assert_jsonl_protocol(list(_RFC_BUILD_STREAM_LINES), expect_exit_code=0)

    def test_rfc_build_failed_terminal(self) -> None:
        lines = list(_RFC_BUILD_STREAM_LINES)
        # Replace terminal with build.failed
        lines[5] = {
            "protocol": "aisc.cli/v1", "command": "build",
            "run_id": "550e8400-e29b-41d4-a716-446655440000",
            "seq": 6, "type": "build.failed",
            "ts": "2026-07-17T12:04:01Z",
            "data": {"reason": "build error", "exit_code": 4},
        }
        assert_jsonl_protocol(lines, expect_exit_code=4)

    def test_rfc_build_cancelled_terminal(self) -> None:
        lines = list(_RFC_BUILD_STREAM_LINES)
        lines[5] = {
            "protocol": "aisc.cli/v1", "command": "build",
            "run_id": "550e8400-e29b-41d4-a716-446655440000",
            "seq": 6, "type": "build.cancelled",
            "ts": "2026-07-17T12:04:01Z",
            "data": {"signal": "SIGINT", "exit_code": 130},
        }
        assert_jsonl_protocol(lines, expect_exit_code=130)

    # -- 7 required fields ---------------------------------------------------

    _REQUIRED = ["protocol", "command", "run_id", "seq", "type", "ts", "data"]

    def test_missing_each_required_field(self) -> None:
        for field in self._REQUIRED:
            with self.subTest(missing=field):
                obj = dict(_RFC_BUILD_STREAM_LINES[0])
                del obj[field]
                with self.assertRaises(AssertionError):
                    assert_jsonl_protocol([obj])

    # -- seq rules (start at 1, increment by 1) ------------------------------

    def test_rejects_seq_starting_at_zero(self) -> None:
        lines = list(_RFC_BUILD_STREAM_LINES)
        for i in range(len(lines)):
            lines[i] = dict(lines[i])
            lines[i]["seq"] = i  # 0, 1, 2, ...
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    def test_rejects_seq_skip(self) -> None:
        """seq must increment by exactly 1."""
        lines = list(_RFC_BUILD_STREAM_LINES)
        lines[2] = dict(lines[2])
        lines[2]["seq"] = 4  # skip 3
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    # -- command / run_id consistency -----------------------------------------

    def test_rejects_command_change_midstream(self) -> None:
        lines = list(_RFC_BUILD_STREAM_LINES)
        lines[3] = dict(lines[3])
        lines[3]["command"] = "run"
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    def test_rejects_run_id_change_midstream(self) -> None:
        lines = list(_RFC_BUILD_STREAM_LINES)
        lines[3] = dict(lines[3])
        lines[3]["run_id"] = "different-uuid"
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    # -- terminal rules -------------------------------------------------------

    def test_rejects_step_complete_as_terminal(self) -> None:
        """build.step.complete is NOT a terminal — only build.complete is."""
        # Remove the real terminal so only step.complete events remain
        lines = list(_RFC_BUILD_STREAM_LINES[:5])  # lines 0-4, no terminal
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    def test_rejects_terminal_not_last_line(self) -> None:
        """Terminal must be the very last event."""
        lines = list(_RFC_BUILD_STREAM_LINES)
        # Swap terminal (idx 5) with previous line (idx 4)
        lines[4], lines[5] = lines[5], lines[4]
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    def test_rejects_multiple_terminals(self) -> None:
        lines = list(_RFC_BUILD_STREAM_LINES)
        # Append a second terminal
        lines.append({
            "protocol": "aisc.cli/v1", "command": "build",
            "run_id": "550e8400-e29b-41d4-a716-446655440000",
            "seq": 7, "type": "build.complete",
            "ts": "2026-07-17T12:05:00Z",
            "data": {"exit_code": 0},
        })
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    def test_rejects_no_terminal(self) -> None:
        # Stream without any terminal type
        lines: list = [
            {"protocol": "aisc.cli/v1", "command": "build",
             "run_id": "r1", "seq": 1, "type": "build.start",
             "ts": "t1", "data": {}},
            {"protocol": "aisc.cli/v1", "command": "build",
             "run_id": "r1", "seq": 2, "type": "build.step.start",
             "ts": "t2", "data": {}},
        ]
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    # -- terminal exit_code ---------------------------------------------------

    def test_rejects_terminal_missing_exit_code(self) -> None:
        lines = copy.deepcopy(_RFC_BUILD_STREAM_LINES)
        del lines[5]["data"]["exit_code"]
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    def test_rejects_terminal_exit_code_not_int(self) -> None:
        lines = copy.deepcopy(_RFC_BUILD_STREAM_LINES)
        lines[5]["data"]["exit_code"] = "0"
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    def test_rejects_terminal_exit_code_mismatch(self) -> None:
        """data.exit_code must match expect_exit_code."""
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(
                list(_RFC_BUILD_STREAM_LINES), expect_exit_code=1
            )

    # -- data must be dict ----------------------------------------------------

    def test_rejects_data_not_dict(self) -> None:
        lines = list(_RFC_BUILD_STREAM_LINES)
        lines[2] = dict(lines[2])
        lines[2]["data"] = "not a dict"
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    # -- invalid entry --------------------------------------------------------

    def test_rejects_none_entry(self) -> None:
        lines: list = [
            _RFC_BUILD_STREAM_LINES[0],
            None,
            _RFC_BUILD_STREAM_LINES[5],
        ]
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)

    def test_rejects_non_dict_entry(self) -> None:
        lines: list = [
            _RFC_BUILD_STREAM_LINES[0],
            ["not", "a", "dict"],
            _RFC_BUILD_STREAM_LINES[5],
        ]
        with self.assertRaises(AssertionError):
            assert_jsonl_protocol(lines)


# ============================================================================
# RunResult dataclass  (unchanged)
# ============================================================================

class RunResultTest(unittest.TestCase):
    def test_defaults(self) -> None:
        r = RunResult(stdout="o", stderr="e", exit_code=0)
        self.assertFalse(r.timed_out)

    def test_timed_out_field(self) -> None:
        r = RunResult(stdout="", stderr="", exit_code=-1, timed_out=True)
        self.assertTrue(r.timed_out)
        self.assertEqual(r.exit_code, -1)

    def test_equality(self) -> None:
        a = RunResult("a", "b", 0)
        b = RunResult("a", "b", 0)
        self.assertEqual(a, b)
        c = RunResult("a", "b", 1)
        self.assertNotEqual(a, c)


if __name__ == "__main__":
    unittest.main()
