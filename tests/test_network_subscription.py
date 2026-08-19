"""Tests for IDEA-2 2b: mihomo subscription data plane.

Covers ``aisc.application.network_subscription`` (transport classification,
userinfo parsing, storage, legacy adoption, masking), the CLI wrappers
(``aisc.cli.commands.network`` — stdin discipline, --confirm), the
fingerprint subscription-hash extension (D1: direct stays byte-identical)
and ``plan_run``'s data-root proxy resolution.
"""

from __future__ import annotations

import hashlib
import io
import base64
import json
import os
import shutil
import ssl
import tempfile
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock

from aisc.application import network_subscription as ns
from aisc.domain.models import CliError


def _fake_transport(responses: List[Any]) -> "FakeTransport":
    return FakeTransport(responses)


class FakeTransport:
    """Scripted transport: pops one (status, headers, body) or exception per call."""

    def __init__(self, responses: List[Any]):
        self.responses = list(responses)
        self.calls: List[Tuple[str, Dict[str, str], float]] = []

    def __call__(self, url: str, headers: Dict[str, str], timeout: float):
        self.calls.append((url, dict(headers), timeout))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class HermeticDataRoot:
    """Context manager: hermetic AISC_DATA_ROOT (+ optional legacy root)."""

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aisc-ns-test-"))
        self.legacy = self.tmp / "legacy-root"
        self.legacy.mkdir()
        self.env = {"AISC_DATA_ROOT": str(self.tmp / "data")}
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    @property
    def config_path(self) -> Path:
        return Path(self.env["AISC_DATA_ROOT"]) / "config" / "mihomo" / "subscription.yaml"

    @property
    def snapshot_path(self) -> Path:
        return Path(self.env["AISC_DATA_ROOT"]) / "config" / "network-subscription.json"


class ParseUserinfoTests(unittest.TestCase):
    def test_full_header(self):
        info = ns.parse_userinfo("upload=1638257504; download=13418441583; "
                                 "total=1073839341568; expire=1750000000")
        self.assertEqual(info, {"upload": 1638257504, "download": 13418441583,
                                "total": 1073839341568, "expire": 1750000000})

    def test_total_zero_and_missing_expire_survive(self):
        info = ns.parse_userinfo("upload=5; download=6; total=0")
        self.assertEqual(info, {"upload": 5, "download": 6, "total": 0})

    def test_whitespace_and_garbage_pairs_skipped(self):
        info = ns.parse_userinfo(" upload = 10 ;;; foo=1; =2; download=x; download=20 ;")
        self.assertEqual(info, {"upload": 10, "download": 20})

    def test_empty_is_none(self):
        self.assertIsNone(ns.parse_userinfo(""))
        self.assertIsNone(ns.parse_userinfo("   ; ; "))


class NodeNameUsageFallbackTests(unittest.TestCase):
    """挂账②: no userinfo header → the facts ride as fake proxy nodes."""

    REAL_WORLD = (
        "proxies:\n"
        "  - { name: 认准官网地址, type: ss, server: a.example, port: 1 }\n"
        "  - { name: '剩余流量：9999995.97 GB', type: ss, server: a.example, port: 1 }\n"
        "  - { name: '已用流量：4.03 GB', type: ss, server: a.example, port: 1 }\n"
        "  - { name: '套餐总量：10000000 GB', type: ss, server: a.example, port: 1 }\n"
        "  - { name: '套餐到期：永久有效', type: ss, server: a.example, port: 1 }\n"
    )

    def test_real_world_shape(self):
        info = ns.parse_node_name_userinfo(self.REAL_WORLD)
        self.assertEqual(info, {
            "upload": 0,
            "download": int(4.03 * 1e9),
            "total": int(10000000 * 1e9),
            # permanent plan → no expire key
        })

    def test_derives_total_from_used_and_remaining(self):
        info = ns.parse_node_name_userinfo(
            "已用: 1.5GB\n剩余流量：500MB\n")
        self.assertEqual(info["download"], int(1.5e9))
        self.assertEqual(info["total"], int(1.5e9) + int(500e6))

    def test_date_expiry_becomes_epoch(self):
        info = ns.parse_node_name_userinfo(
            "已用流量：1 GB\n套餐总量：10 GB\n到期时间：2027-01-15\n")
        self.assertEqual(info["expire"],
                         int(datetime(2027, 1, 15).timestamp()))

    def test_used_alone_without_denominator_is_none(self):
        # Conservative: without total/remaining there is nothing displayable
        # beyond a bare "used" number — keep the no-info contract.
        self.assertIsNone(ns.parse_node_name_userinfo("已用流量：1 GB\n"))

    def test_nothing_recognizable_is_none(self):
        self.assertIsNone(ns.parse_node_name_userinfo(
            "proxies:\n  - { name: 香港节点01, type: ss }\n"))
        self.assertIsNone(ns.parse_node_name_userinfo(""))

    def test_import_content_stores_node_derived_userinfo(self):
        with HermeticDataRoot() as hr:
            data = ns.import_subscription_content(
                self.REAL_WORLD.encode("utf-8"), env=hr.env)
            self.assertEqual(data["userinfo_source"], "node-names")
            self.assertEqual(data["userinfo"]["download"], int(4.03e9))
            shown = ns.show_subscription(env=hr.env)
            self.assertEqual(shown["userinfo_source"], "node-names")
            self.assertEqual(shown["userinfo"]["total"], int(10000000e9))

    def test_header_wins_over_node_names(self):
        with HermeticDataRoot() as hr:
            body = self.REAL_WORLD.encode("utf-8")
            t = _fake_transport([(200, {"subscription-userinfo": "total=10"},
                                      body)])
            data = ns.import_subscription(
                "https://sub.example/api", transport=t, env=hr.env)
            self.assertEqual(data["userinfo_source"], "header")
            self.assertEqual(data["userinfo"], {"total": 10})
            shown = ns.show_subscription(env=hr.env)
            self.assertEqual(shown["userinfo_source"], "header")


class StoreDownloadedTests(unittest.TestCase):
    """挂账①: the persistence endpoint behind the Rust reqwest downloader."""

    def _stdin(self, payload: str):
        s = mock.Mock()
        s.read.return_value = payload
        return s

    def test_header_path_persists_and_masks(self):
        from aisc.cli.commands import network as nw
        body = b"proxies: [ ]\n"
        payload = json.dumps({
            "url": "https://sub.example/api?token=SECRET",
            "content_b64": base64.b64encode(body).decode(),
            "userinfo": "upload=100; download=900; total=1000",
        })
        with HermeticDataRoot() as hr, \
                mock.patch("sys.stdin", self._stdin(payload)), \
                mock.patch.dict(os.environ, hr.env, clear=False):
            data = nw.cmd_network_subscription_store_downloaded(mock.Mock())
        self.assertEqual(data["source"], "download")
        self.assertEqual(data["userinfo_source"], "header")
        self.assertEqual(data["userinfo"]["total"], 1000)
        self.assertEqual(data["url_masked"], "https://sub.example/api?****")

    def test_node_name_fallback_when_header_absent(self):
        from aisc.cli.commands import network as nw
        body = NodeNameUsageFallbackTests.REAL_WORLD.encode("utf-8")
        payload = json.dumps({
            "url": None, "content_b64": base64.b64encode(body).decode(),
            "userinfo": None,
        })
        with HermeticDataRoot() as hr, \
                mock.patch("sys.stdin", self._stdin(payload)), \
                mock.patch.dict(os.environ, hr.env, clear=False):
            data = nw.cmd_network_subscription_store_downloaded(mock.Mock())
        self.assertEqual(data["userinfo_source"], "node-names")
        self.assertEqual(data["userinfo"]["download"], int(4.03e9))
        self.assertIsNone(data["url_masked"])

    def test_bad_base64_and_empty_content(self):
        from aisc.cli.commands import network as nw
        with mock.patch("sys.stdin", self._stdin(
                json.dumps({"url": None, "content_b64": "!!!not-b64!!!"}))):
            with self.assertRaises(CliError) as ctx:
                nw.cmd_network_subscription_store_downloaded(mock.Mock())
            self.assertEqual(ctx.exception.error_code, "AISC_ERR_USAGE")
        with mock.patch("sys.stdin", self._stdin(
                json.dumps({"url": None, "content_b64": ""}))):
            with self.assertRaises(CliError) as ctx:
                nw.cmd_network_subscription_store_downloaded(mock.Mock())
            self.assertEqual(ctx.exception.error_code, ns.ERROR_EMPTY)

    def test_parser_accepts_store_downloaded(self):
        from aisc.cli.main import _build_parser
        args = _build_parser().parse_args(
            ["network", "subscription", "store-downloaded"])
        self.assertEqual(args.subscription_command, "store-downloaded")


class MaskUrlTests(unittest.TestCase):
    def test_query_masked_path_truncated(self):
        masked = ns.mask_url("https://provider.example/api/v1/client/subscribe?token=S3CRET")
        self.assertEqual(masked, "https://provider.example/api/v1/…?****")

    def test_short_path_and_no_query(self):
        self.assertEqual(ns.mask_url("http://h.io/sub?x=1"), "http://h.io/sub?****")
        self.assertEqual(ns.mask_url("http://h.io"), "http://h.io/")

    def test_invalid_is_none(self):
        self.assertIsNone(ns.mask_url("not a url"))
        self.assertIsNone(ns.mask_url("//nope"))


class ImportTests(unittest.TestCase):
    def test_import_success_writes_files_and_snapshot(self):
        with HermeticDataRoot() as hr:
            body = b"proxies:\n  - name: n1\n"
            t = _fake_transport([(200, {"subscription-userinfo":
                                        "upload=100; download=900; total=100000"},
                                  body)])
            data = ns.import_subscription(
                "https://sub.example/api?token=SECRET", transport=t, env=hr.env)
            self.assertEqual(t.calls[0][0], "https://sub.example/api?token=SECRET")
            # Clash-family UA rides the request (payload-format gating).
            self.assertEqual(t.calls[0][1]["User-Agent"], ns.USER_AGENT)
            self.assertTrue(data["configured"])
            self.assertEqual(data["source"], "download")
            self.assertEqual(data["url_masked"], "https://sub.example/api?****")
            self.assertEqual(data["userinfo"], {"upload": 100, "download": 900,
                                                "total": 100000})
            self.assertEqual(hr.config_path.read_bytes(), body)
            snap = json.loads(hr.snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(snap["schema"], ns.SUBSCRIPTION_SCHEMA)
            self.assertEqual(snap["url"], "https://sub.example/api?token=SECRET")
            self.assertEqual(snap["source"], "download")
            self.assertEqual(snap["userinfo"], {"upload": 100, "download": 900,
                                                "total": 100000})

    def test_tls_handshake_kill_is_classified_and_not_retried(self):
        with HermeticDataRoot() as hr:
            t = _fake_transport([urllib.error.URLError(
                ssl.SSLEOFError("UNEXPECTED_EOF_WHILE_READING"))])
            with self.assertRaises(CliError) as ctx:
                ns.import_subscription("https://sub.example/api", transport=t,
                                       env=hr.env)
            self.assertEqual(ctx.exception.error_code, ns.ERROR_TLS_REJECTED)
            self.assertEqual(len(t.calls), 1)  # deterministic — no retry
            self.assertFalse(hr.config_path.exists())

    def test_connection_reset_is_tls_rejected(self):
        with HermeticDataRoot() as hr:
            t = _fake_transport([urllib.error.URLError(ConnectionResetError(10054))])
            with self.assertRaises(CliError) as ctx:
                ns.import_subscription("https://sub.example/api", transport=t,
                                       env=hr.env)
            self.assertEqual(ctx.exception.error_code, ns.ERROR_TLS_REJECTED)

    def test_http_4xx_never_retries(self):
        with HermeticDataRoot() as hr:
            t = _fake_transport([(404, {}, b"")])
            with self.assertRaises(CliError) as ctx:
                ns.import_subscription("https://sub.example/api", transport=t,
                                       env=hr.env)
            self.assertEqual(ctx.exception.error_code, ns.ERROR_HTTP)
            self.assertEqual(len(t.calls), 1)

    def test_http_5xx_retries_once_then_fetch_error(self):
        with HermeticDataRoot() as hr:
            t = _fake_transport([(503, {}, b""), (503, {}, b"")])
            with self.assertRaises(CliError) as ctx:
                ns.import_subscription("https://sub.example/api", transport=t,
                                       env=hr.env)
            self.assertEqual(ctx.exception.error_code, ns.ERROR_FETCH)
            self.assertEqual(len(t.calls), 2)

    def test_http_5xx_retry_succeeds(self):
        with HermeticDataRoot() as hr:
            t = _fake_transport([(503, {}, b""), (200, {}, b"proxies: []")])
            data = ns.import_subscription("https://sub.example/api", transport=t,
                                          env=hr.env)
            self.assertTrue(data["configured"])
            self.assertIsNone(data["userinfo"])
            self.assertEqual(len(t.calls), 2)

    def test_empty_body_is_rejected(self):
        with HermeticDataRoot() as hr:
            t = _fake_transport([(200, {}, b"")])
            with self.assertRaises(CliError) as ctx:
                ns.import_subscription("https://sub.example/api", transport=t,
                                       env=hr.env)
            self.assertEqual(ctx.exception.error_code, ns.ERROR_EMPTY)

    def test_invalid_urls(self):
        for bad in ("", "notaurl", "ftp://example.com/x", "http://"):
            with self.assertRaises(CliError) as ctx:
                ns.import_subscription(bad, transport=_fake_transport([]))
            self.assertEqual(ctx.exception.error_code, ns.ERROR_INVALID_URL)


class ImportFileTests(unittest.TestCase):
    def test_manual_content_import(self):
        with HermeticDataRoot() as hr:
            data = ns.import_subscription_content(b"proxies: [ ]\n", env=hr.env)
            self.assertTrue(data["configured"])
            self.assertEqual(data["source"], "manual")
            self.assertIsNone(data["url_masked"])
            self.assertIsNone(data["userinfo"])
            self.assertEqual(hr.config_path.read_bytes(), b"proxies: [ ]\n")

    def test_empty_content_rejected(self):
        with HermeticDataRoot() as hr:
            with self.assertRaises(CliError) as ctx:
                ns.import_subscription_content(b"  \n", env=hr.env)
            self.assertEqual(ctx.exception.error_code, ns.ERROR_EMPTY)


class RefreshShowClearTests(unittest.TestCase):
    def test_refresh_without_snapshot(self):
        with HermeticDataRoot() as hr:
            with self.assertRaises(CliError) as ctx:
                ns.refresh_subscription(env=hr.env)
            self.assertEqual(ctx.exception.error_code, ns.ERROR_NOT_CONFIGURED)

    def test_refresh_uses_stored_url(self):
        with HermeticDataRoot() as hr:
            ns.import_subscription("https://sub.example/api?token=T",
                                   transport=_fake_transport(
                                       [(200, {}, b"old-content")]), env=hr.env)
            data = ns.refresh_subscription(
                transport=_fake_transport([(200, {}, b"new-content")]), env=hr.env)
            self.assertTrue(data["configured"])
            self.assertEqual(hr.config_path.read_bytes(), b"new-content")

    def test_show_empty_then_populated_then_cleared(self):
        with HermeticDataRoot() as hr:
            empty = ns.show_subscription(env=hr.env, legacy_root=hr.legacy)
            self.assertFalse(empty["configured"])
            self.assertFalse(empty["has_config_file"])

            ns.import_subscription("https://sub.example/api?token=T",
                                   transport=_fake_transport(
                                       [(200, {"subscription-userinfo": "total=10"},
                                        b"c1")]), env=hr.env)
            shown = ns.show_subscription(env=hr.env, legacy_root=hr.legacy)
            self.assertTrue(shown["configured"])
            self.assertEqual(shown["source"], "download")
            self.assertEqual(shown["url_masked"], "https://sub.example/api?****")
            self.assertEqual(shown["userinfo"], {"total": 10})

            cleared = ns.clear_subscription(env=hr.env)
            self.assertEqual(cleared, {"configured": False})
            self.assertFalse(hr.config_path.exists())
            self.assertFalse(hr.snapshot_path.exists())
            self.assertFalse(ns.show_subscription(
                env=hr.env, legacy_root=hr.legacy)["configured"])

    def test_show_survives_corrupt_snapshot(self):
        with HermeticDataRoot() as hr:
            ns.import_subscription_content(b"c1", env=hr.env)
            hr.snapshot_path.write_text("{not json", encoding="utf-8")
            shown = ns.show_subscription(env=hr.env, legacy_root=hr.legacy)
            self.assertTrue(shown["configured"])
            self.assertEqual(shown["source"], "manual")
            self.assertIsNone(shown["url_masked"])


class LegacyAdoptionTests(unittest.TestCase):
    def _make_legacy(self, hr: HermeticDataRoot, content: bytes) -> Path:
        legacy = hr.legacy / ".claude" / "mihomo" / "config.yaml"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(content)
        return legacy

    def test_adopt_copies_once_and_keeps_source(self):
        with HermeticDataRoot() as hr:
            legacy = self._make_legacy(hr, b"legacy-config")
            resolved = ns.resolve_subscription_config_path(
                env=hr.env, legacy_root=hr.legacy, adopt_legacy=True)
            self.assertEqual(resolved, str(hr.config_path))
            self.assertEqual(hr.config_path.read_bytes(), b"legacy-config")
            self.assertTrue(legacy.exists())  # source untouched
            # Idempotent: second resolve hits the target directly.
            again = ns.resolve_subscription_config_path(
                env=hr.env, legacy_root=hr.legacy, adopt_legacy=True)
            self.assertEqual(again, str(hr.config_path))

    def test_no_adopt_returns_legacy_path_readonly(self):
        with HermeticDataRoot() as hr:
            self._make_legacy(hr, b"legacy-config")
            resolved = ns.resolve_subscription_config_path(
                env=hr.env, legacy_root=hr.legacy, adopt_legacy=False)
            self.assertEqual(
                resolved, str(hr.legacy / ".claude" / "mihomo" / "config.yaml"))
            self.assertFalse(hr.config_path.exists())

    def test_explicit_wins_without_checks(self):
        with HermeticDataRoot() as hr:
            self._make_legacy(hr, b"legacy-config")
            self.assertEqual(
                ns.resolve_subscription_config_path(
                    "C:/explicit/path.yaml", env=hr.env, legacy_root=hr.legacy),
                "C:/explicit/path.yaml")

    def test_show_adopts_legacy(self):
        with HermeticDataRoot() as hr:
            self._make_legacy(hr, b"legacy-config")
            shown = ns.show_subscription(env=hr.env, legacy_root=hr.legacy)
            self.assertTrue(shown["configured"])
            self.assertEqual(shown["source"], "manual")

    def test_nothing_anywhere_is_none(self):
        with HermeticDataRoot() as hr:
            self.assertIsNone(ns.resolve_subscription_config_path(
                env=hr.env, legacy_root=hr.legacy))


class FingerprintTests(unittest.TestCase):
    """D1: direct fingerprints are byte-identical to the pre-IDEA-2 shape;
    proxy fingerprints distinguish no-config / content / changed content."""

    IMG, SCOPE = "super-claude:latest", "project"

    def _old_shape(self, network: str, ws: Path) -> str:
        canonical = json.dumps(
            {"image": self.IMG, "network": network, "scope": self.SCOPE,
             "workspace": str(ws.resolve())},
            sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    def test_direct_ignores_sha_and_matches_legacy_shape(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            from aisc.application.runtime import compute_config_fingerprint as fp
            expected = self._old_shape("direct", ws)
            self.assertEqual(fp(self.IMG, "direct", self.SCOPE, str(ws)), expected)
            self.assertEqual(
                fp(self.IMG, "direct", self.SCOPE, str(ws),
                   proxy_config_sha256="sha256:whatever"), expected)

    def test_proxy_sha_variants_differ(self):
        with tempfile.TemporaryDirectory() as td:
            ws = str(Path(td))
            from aisc.application.runtime import compute_config_fingerprint as fp
            no_cfg = fp(self.IMG, "proxy", self.SCOPE, ws)
            sha1 = fp(self.IMG, "proxy", self.SCOPE, ws, proxy_config_sha256="sha256:a")
            sha2 = fp(self.IMG, "proxy", self.SCOPE, ws, proxy_config_sha256="sha256:b")
            self.assertEqual(len({no_cfg, sha1, sha2}), 3)
            self.assertNotEqual(no_cfg, self._old_shape("proxy", Path(td)))

    def test_proxy_sha_helper_reads_resolved_file(self):
        from aisc.application.runtime import _proxy_config_sha256
        with HermeticDataRoot() as hr:
            with mock.patch.dict(os.environ, hr.env, clear=False):
                self.assertEqual(_proxy_config_sha256("direct", None), "")
                self.assertEqual(_proxy_config_sha256("proxy", None), "")
                hr.config_path.parent.mkdir(parents=True, exist_ok=True)
                hr.config_path.write_bytes(b"cfg-v1")
                want = f"sha256:{hashlib.sha256(b'cfg-v1').hexdigest()}"
                self.assertEqual(_proxy_config_sha256("proxy", None), want)
                # Explicit path wins over auto-resolution.
                self.assertEqual(
                    _proxy_config_sha256("proxy", str(hr.config_path)), want)
                # Unreadable explicit file degrades to "" (no fingerprint crash).
                self.assertEqual(
                    _proxy_config_sha256("proxy", str(hr.tmp / "missing.yaml")), "")


class PlanRunProxyResolutionTests(unittest.TestCase):
    def test_plan_run_resolves_data_root_subscription(self):
        from aisc.cli.commands.run import plan_run
        with HermeticDataRoot() as hr:
            hr.config_path.parent.mkdir(parents=True, exist_ok=True)
            hr.config_path.write_bytes(b"cfg")
            with tempfile.TemporaryDirectory() as td, \
                    mock.patch.dict(os.environ, hr.env, clear=False):
                plan = plan_run(image="super-claude:latest", workspace=td,
                                network="proxy")
                self.assertEqual(plan.proxy_config, str(hr.config_path))

    def test_plan_run_explicit_wins_and_absent_stays_empty(self):
        from aisc.cli.commands.run import plan_run
        with HermeticDataRoot() as hr:
            with tempfile.TemporaryDirectory() as td, \
                    mock.patch.dict(os.environ, hr.env, clear=False):
                plan = plan_run(image="super-claude:latest", workspace=td,
                                network="proxy", proxy_config="C:/x/y.yaml")
                self.assertEqual(plan.proxy_config, "C:/x/y.yaml")
                plan2 = plan_run(image="super-claude:latest", workspace=td,
                                 network="proxy")
                self.assertEqual(plan2.proxy_config, "")


class CliWrapperTests(unittest.TestCase):
    """Stdin discipline + --confirm for the ``aisc network subscription``
    command wrappers (transport faked at module level)."""

    def _text_stdin(self, payload: str):
        s = mock.Mock()
        s.read.return_value = payload
        return s

    def _bytes_stdin(self, payload: bytes):
        s = mock.Mock()
        s.buffer = io.BytesIO(payload)
        return s

    def test_import_reads_url_from_stdin(self):
        from aisc.cli.commands import network as nw
        with HermeticDataRoot() as hr:
            t = _fake_transport([(200, {}, b"cfg")])
            with mock.patch.object(ns, "default_transport", t), \
                    mock.patch("sys.stdin", self._text_stdin("https://h.io/s?token=T")), \
                    mock.patch.dict(os.environ, hr.env, clear=False):
                data = nw.cmd_network_subscription_import(mock.Mock())
            self.assertTrue(data["configured"])
            self.assertEqual(t.calls[0][0], "https://h.io/s?token=T")

    def test_import_empty_stdin_is_usage_error(self):
        from aisc.cli.commands import network as nw
        with mock.patch("sys.stdin", self._text_stdin("  ")):
            with self.assertRaises(CliError) as ctx:
                nw.cmd_network_subscription_import(mock.Mock())
            self.assertEqual(ctx.exception.error_code, "AISC_ERR_USAGE")

    def test_import_file_reads_content_from_stdin(self):
        from aisc.cli.commands import network as nw
        with HermeticDataRoot() as hr:
            with mock.patch("sys.stdin", self._bytes_stdin(b"proxies: []")), \
                    mock.patch.dict(os.environ, hr.env, clear=False):
                data = nw.cmd_network_subscription_import_file(mock.Mock())
            self.assertEqual(data["source"], "manual")
            self.assertEqual(hr.config_path.read_bytes(), b"proxies: []")

    def test_clear_requires_confirm(self):
        from aisc.cli.commands import network as nw
        with self.assertRaises(CliError) as ctx:
            nw.cmd_network_subscription_clear(mock.Mock(confirm=False))
        self.assertEqual(ctx.exception.error_code, "AISC_ERR_USAGE")

    def test_clear_with_confirm_removes(self):
        from aisc.cli.commands import network as nw
        with HermeticDataRoot() as hr:
            ns.import_subscription_content(b"cfg", env=hr.env)
            with mock.patch.dict(os.environ, hr.env, clear=False):
                data = nw.cmd_network_subscription_clear(mock.Mock(confirm=True))
            self.assertEqual(data, {"configured": False})
            self.assertFalse(hr.config_path.exists())

    def test_parser_accepts_network_group(self):
        from aisc.cli.main import _build_parser, _detect_command
        parser = _build_parser()
        args = parser.parse_args(["network", "subscription", "show"])
        self.assertEqual(args.command, "network")
        self.assertEqual(args.network_command, "subscription")
        self.assertEqual(args.subscription_command, "show")
        # 2a fix: _detect_command must recognize the new group (and the
        # pre-existing cc-switch omission).
        self.assertEqual(_detect_command(["aisc", "network", "subscription"]),
                         "network")
        self.assertEqual(_detect_command(["aisc", "cc-switch", "list"]), "cc-switch")


if __name__ == "__main__":
    unittest.main()
