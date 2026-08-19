"""IDEA-2 2c: host-side usage aggregation (``aisc.application.usage``).

Hermetic data root with fabricated workspace registries; a FakeExecutor
answers docker ``inspect`` (running state) and ``exec`` (scripted adapter
envelopes). Covers live/cache/none sources, cache write-back, range
semantics (today = local midnight), workspace filtering and totals.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest import mock

from aisc.application import usage as U


def _adapter_envelope(providers: List[Dict[str, Any]],
                      models: Optional[List[Dict[str, Any]]] = None) -> str:
    return json.dumps({
        "schema": U.PROTOCOL,
        "operation_id": "op",
        "op": "usage",
        "ok": True,
        "usage": {
            "available": True, "providers": providers,
            "models": models or [], "since": 0, "unit": "s",
            "generated_at": "2026-08-19T00:00:00Z",
        },
    })


class FakeExecutor:
    """Answers docker inspect + docker exec (usage adapter) calls."""

    def __init__(self, *, running: Dict[str, bool], envelopes: Dict[str, str]):
        self.running = running          # container name → is running
        self.envelopes = envelopes      # container name → adapter stdout
        self.exec_calls: List[List[str]] = []
        self.inspect_calls: List[List[str]] = []

    def run_captured(self, argv: List[str], timeout: float = 30.0,
                     input_text: Optional[str] = None):
        if argv and argv[0] == "inspect":
            self.inspect_calls.append(argv)
            name = argv[-1]
            is_running = self.running.get(name, False)
            return SimpleNamespace(exit_code=0 if name in self.running else 1,
                                   stdout="true" if is_running else "false",
                                   stderr="")
        if argv and argv[0] == "exec":
            self.exec_calls.append(argv)
            name = argv[2]
            out = self.envelopes.get(name)
            if out is None:
                return SimpleNamespace(exit_code=1, stdout="", stderr="gone")
            return SimpleNamespace(exit_code=0, stdout=out, stderr="")
        return SimpleNamespace(exit_code=1, stdout="", stderr="unexpected")


def _make_workspace(data_root: Path, ws_hash: str, ws_path: str,
                    container: str) -> Path:
    ws_dir = data_root / "workspaces" / ws_hash
    (ws_dir / "runtime").mkdir(parents=True, exist_ok=True)
    registry = {
        "containers": {
            container: {
                "runtime_id": "11111111-2222-4333-8444-555555555555",
                "workspace": ws_path,
                "scope": "project",
                "owner": "workbench",
                "container_id": "abc123",
                "config_fingerprint": "sha256:x",
                "network": "direct",
                "image": "super-claude:latest",
            }
        }
    }
    (ws_dir / "runtime" / "containers.json").write_text(
        json.dumps(registry), encoding="utf-8")
    return ws_dir


class HermeticRoot:
    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aisc-usage-test-"))
        self.data = self.tmp / "data"
        self.env = {"AISC_DATA_ROOT": str(self.data)}
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


PROVIDERS_A = [
    {"app": "claude", "provider_id": "deepseek", "provider_name": "DeepSeek",
     "requests": 10, "success": 9, "failed": 1, "tokens_total": 1234,
     "cost_estimate": 0.5, "currency": "USD"},
]
PROVIDERS_B = [
    {"app": "claude", "provider_id": "deepseek", "provider_name": "DeepSeek",
     "requests": 5, "success": 5, "failed": 0, "tokens_total": 100,
     "cost_estimate": 0.25, "currency": "USD"},
    {"app": "codex", "provider_id": "kimi", "provider_name": "Kimi",
     "requests": 2, "success": 2, "failed": 0, "tokens_total": 50,
     "cost_estimate": 0.1, "currency": "USD"},
]


class SinceEpochTests(unittest.TestCase):
    def test_today_is_local_midnight(self):
        now = datetime(2026, 8, 19, 15, 30, 0)
        self.assertEqual(U.since_epoch_for("today", now=now),
                         datetime(2026, 8, 19, 0, 0, 0).timestamp())

    def test_days_subtract(self):
        now = datetime(2026, 8, 19, 15, 30, 0)
        self.assertAlmostEqual(U.since_epoch_for("7d", now=now),
                               now.timestamp() - 7 * 86400)

    def test_invalid_range_rejected(self):
        from aisc.domain.models import CliError
        with self.assertRaises(CliError):
            U.since_epoch_for("90d")


class UsageOverviewTests(unittest.TestCase):
    def test_live_fetch_aggregates_and_writes_cache(self):
        with HermeticRoot() as hr:
            _make_workspace(hr.data, "sha256-v1-aaa", "C:\\wsA", "ct-a")
            ex = FakeExecutor(
                running={"ct-a": True},
                envelopes={"ct-a": _adapter_envelope(PROVIDERS_A)})
            with mock.patch.dict("os.environ", hr.env, clear=False), \
                    mock.patch("aisc.application.network_subscription.show_subscription",
                               return_value={"configured": False}):
                data = U.usage_overview(range_key="7d", executor=ex)
            self.assertEqual(len(data["workspaces"]), 1)
            ws = data["workspaces"][0]
            self.assertTrue(ws["running"])
            self.assertEqual(ws["source"], "live")
            self.assertTrue(ws["available"])
            # Exec argv carries the host-computed epoch cutoff.
            self.assertIn("--since", ex.exec_calls[0])
            # Cache written for stopped-workspace reuse.
            cache = hr.data / "cache" / "usage" / "sha256-v1-aaa.json"
            self.assertTrue(cache.is_file())
            cached = json.loads(cache.read_text(encoding="utf-8"))
            self.assertEqual(cached["range"], "7d")
            self.assertEqual(cached["usage"]["providers"], PROVIDERS_A)
            # Totals reflect the single live workspace.
            self.assertEqual(data["totals"]["requests"], 10)
            self.assertEqual(data["totals"]["tokens_total"], 1234)

    def test_stopped_workspace_uses_cache_then_none(self):
        with HermeticRoot() as hr:
            _make_workspace(hr.data, "sha256-v1-aaa", "C:\\wsA", "ct-a")
            ex = FakeExecutor(running={"ct-a": False}, envelopes={})
            with mock.patch.dict("os.environ", hr.env, clear=False), \
                    mock.patch("aisc.application.network_subscription.show_subscription",
                               return_value={"configured": False}):
                data = U.usage_overview(range_key="7d", executor=ex)
            self.assertEqual(data["workspaces"][0]["source"], "none")
            self.assertEqual(ex.exec_calls, [])  # no exec against stopped ct

            # Seed a cache → source flips to cache.
            cache = hr.data / "cache" / "usage" / "sha256-v1-aaa.json"
            cache.parent.mkdir(parents=True)
            cache.write_text(json.dumps({
                "schema": U.CACHE_SCHEMA, "range": "7d",
                "fetched_at": "2026-08-19T10:00:00+08:00",
                "usage": {"available": True, "providers": PROVIDERS_B,
                          "models": []},
            }), encoding="utf-8")
            with mock.patch.dict("os.environ", hr.env, clear=False), \
                    mock.patch("aisc.application.network_subscription.show_subscription",
                               return_value={"configured": False}):
                data = U.usage_overview(range_key="7d", executor=ex)
            ws = data["workspaces"][0]
            self.assertEqual(ws["source"], "cache")
            self.assertEqual(len(ws["providers"]), 2)
            self.assertEqual(data["totals"]["requests"], 7)

    def test_today_cache_from_yesterday_is_not_reused(self):
        with HermeticRoot() as hr:
            _make_workspace(hr.data, "sha256-v1-aaa", "C:\\wsA", "ct-a")
            ex = FakeExecutor(running={"ct-a": False}, envelopes={})
            cache = hr.data / "cache" / "usage" / "sha256-v1-aaa.json"
            cache.parent.mkdir(parents=True)
            cache.write_text(json.dumps({
                "schema": U.CACHE_SCHEMA, "range": "today",
                "fetched_at": "2020-01-01T10:00:00+08:00",
                "usage": {"available": True, "providers": PROVIDERS_A,
                          "models": []},
            }), encoding="utf-8")
            with mock.patch.dict("os.environ", hr.env, clear=False), \
                    mock.patch("aisc.application.network_subscription.show_subscription",
                               return_value={"configured": False}):
                data = U.usage_overview(range_key="today", executor=ex)
            self.assertEqual(data["workspaces"][0]["source"], "none")

    def test_two_workspaces_totals_merge_by_provider(self):
        with HermeticRoot() as hr:
            _make_workspace(hr.data, "sha256-v1-aaa", "C:\\wsA", "ct-a")
            _make_workspace(hr.data, "sha256-v1-bbb", "C:\\wsB", "ct-b")
            ex = FakeExecutor(
                running={"ct-a": True, "ct-b": True},
                envelopes={"ct-a": _adapter_envelope(PROVIDERS_A),
                           "ct-b": _adapter_envelope(PROVIDERS_B)})
            with mock.patch.dict("os.environ", hr.env, clear=False), \
                    mock.patch("aisc.application.network_subscription.show_subscription",
                               return_value={"configured": False}):
                data = U.usage_overview(range_key="30d", executor=ex)
            self.assertEqual(len(data["workspaces"]), 2)
            totals = {(p["app"], p["provider_id"]): p
                      for p in data["totals"]["providers"]}
            ds = totals[("claude", "deepseek")]
            self.assertEqual(ds["requests"], 15)
            self.assertEqual(ds["tokens_total"], 1334)
            self.assertAlmostEqual(ds["cost_estimate"], 0.75, places=6)
            self.assertEqual(data["totals"]["tokens_total"], 1384)

    def test_workspace_filter_and_subscription_section(self):
        with HermeticRoot() as hr:
            _make_workspace(hr.data, "sha256-v1-aaa", "C:\\wsA", "ct-a")
            _make_workspace(hr.data, "sha256-v1-bbb", "C:\\wsB", "ct-b")
            ex = FakeExecutor(
                running={"ct-a": True},
                envelopes={"ct-a": _adapter_envelope(PROVIDERS_A)})
            sub = {"configured": True, "source": "manual",
                   "url_masked": None, "fetched_at": "x",
                   "config_sha256": "y", "has_config_file": True,
                   "userinfo": None}
            with mock.patch.dict("os.environ", hr.env, clear=False), \
                    mock.patch("aisc.application.network_subscription.show_subscription",
                               return_value=sub):
                data = U.usage_overview(range_key="7d",
                                        workspace="C:\\wsA", executor=ex)
            self.assertEqual(len(data["workspaces"]), 1)
            self.assertEqual(data["workspaces"][0]["workspace_path"], "C:\\wsA")
            self.assertTrue(data["subscription"]["configured"])

    def test_registry_corruption_is_skipped_not_fatal(self):
        with HermeticRoot() as hr:
            ws_dir = hr.data / "workspaces" / "sha256-v1-bad"
            (ws_dir / "runtime").mkdir(parents=True)
            (ws_dir / "runtime" / "containers.json").write_text("[]",
                                                                encoding="utf-8")
            ex = FakeExecutor(running={}, envelopes={})
            with mock.patch.dict("os.environ", hr.env, clear=False), \
                    mock.patch("aisc.application.network_subscription.show_subscription",
                               return_value={"configured": False}):
                data = U.usage_overview(range_key="7d", executor=ex)
            self.assertEqual(data["workspaces"], [])

    def test_cli_parser_accepts_usage_group(self):
        from aisc.cli.main import _build_parser, _detect_command
        parser = _build_parser()
        args = parser.parse_args(["usage", "overview", "--range", "today"])
        self.assertEqual(args.command, "usage")
        self.assertEqual(args.usage_command, "overview")
        self.assertEqual(args.range, "today")
        self.assertEqual(_detect_command(["aisc", "usage", "overview"]), "usage")


if __name__ == "__main__":
    unittest.main()
