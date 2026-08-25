"""svc-0 (container web-service access): contract unit tests, Python consumer.

Validates the pure contract module and that Python decodes the shared
fixtures under ``tests/fixtures/web-services/`` identically to the Rust and
TypeScript consumers (the svc-0 stage gate; see
docs/plans/container-service-access/decisions.md).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from aisc.domain.web_services import (
    RUNTIME_SERVICES_SCHEMA_V1,
    WEB_GATEWAY_CONTAINER_PORT,
    WEB_GATEWAY_HOST_PORT_MAX,
    WEB_GATEWAY_HOST_PORT_MIN,
    WEB_GATEWAY_HOST_BIND,
    WEB_SERVICE_SCHEMA_V1,
    WEB_SERVICE_PORT_MAX,
    WEB_SERVICE_PORT_MIN,
    WebGatewayInfo,
    WebServiceInfo,
    WebServiceRecord,
    RuntimeServicesResult,
    build_service_url,
    is_exposable_port,
    parse_expose_port,
    parse_gateway_host,
    sanitize_service_name,
    web_access_unavailable,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "web-services"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ConstantsTests(unittest.TestCase):
    def test_frozen_constants(self):
        self.assertEqual(WEB_GATEWAY_CONTAINER_PORT, 45871)
        self.assertEqual((WEB_GATEWAY_HOST_PORT_MIN, WEB_GATEWAY_HOST_PORT_MAX), (47000, 47999))
        self.assertEqual((WEB_SERVICE_PORT_MIN, WEB_SERVICE_PORT_MAX), (1024, 65535))
        self.assertEqual(WEB_GATEWAY_HOST_BIND, "127.0.0.1")
        self.assertEqual(WEB_SERVICE_SCHEMA_V1, "aisc.web-service/v1")
        self.assertEqual(RUNTIME_SERVICES_SCHEMA_V1, "aisc.runtime-services/v1")

    def test_host_range_is_sane(self):
        self.assertLess(WEB_GATEWAY_HOST_PORT_MIN, WEB_GATEWAY_HOST_PORT_MAX)
        for p in (WEB_GATEWAY_HOST_PORT_MIN, WEB_GATEWAY_HOST_PORT_MAX):
            self.assertTrue(1 <= p <= 65535)


class ParseExposePortTests(unittest.TestCase):
    def test_accepts_decimal_strings_in_range(self):
        self.assertEqual(parse_expose_port("1024"), 1024)
        self.assertEqual(parse_expose_port("3000"), 3000)
        self.assertEqual(parse_expose_port("65535"), 65535)

    def test_rejects_non_decimal(self):
        for bad in ("", " 3000", "3000 ", "3000x", "x3000", "3.5", "-1", "+3000", "0x0BB8", "٣", None, 3000):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_expose_port(bad)

    def test_rejects_out_of_range(self):
        for bad in ("0", "1", "1023", "65536", "99999"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_expose_port(bad)

    def test_is_exposable_port(self):
        self.assertFalse(is_exposable_port(1023))
        self.assertTrue(is_exposable_port(1024))
        self.assertTrue(is_exposable_port(65535))
        self.assertFalse(is_exposable_port(65536))
        self.assertFalse(is_exposable_port(True))  # bool is an int subclass


class SanitizeServiceNameTests(unittest.TestCase):
    def test_strips_and_allows_empty(self):
        self.assertEqual(sanitize_service_name("  docs preview \n"), "docs preview")
        self.assertEqual(sanitize_service_name(""), "")
        self.assertEqual(sanitize_service_name(None), "")

    def test_rejects_control_characters(self):
        for bad in ("a\tb", "a\x00b", "line\nbreak", "del\x7f"):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(ValueError):
                    sanitize_service_name(bad)

    def test_rejects_over_64_chars(self):
        with self.assertRaises(ValueError):
            sanitize_service_name("x" * 65)

    def test_accepts_64_chars(self):
        self.assertEqual(sanitize_service_name("x" * 64), "x" * 64)


class BuildServiceUrlTests(unittest.TestCase):
    def test_canonical_shape(self):
        self.assertEqual(build_service_url(3000, 47831), "http://p3000.localhost:47831/")
        self.assertEqual(build_service_url(5173, 47000), "http://p5173.localhost:47000/")

    def test_rejects_bad_ports(self):
        with self.assertRaises(ValueError):
            build_service_url(80, 47831)      # privileged container port
        with self.assertRaises(ValueError):
            build_service_url(3000, 0)        # invalid host port
        with self.assertRaises(ValueError):
            build_service_url(3000, 65536)


class ParseGatewayHostTests(unittest.TestCase):
    def test_accepts_canonical_forms(self):
        self.assertEqual(parse_gateway_host("p3000.localhost"), 3000)
        self.assertEqual(parse_gateway_host("p3000.localhost:47831"), 3000)
        self.assertEqual(parse_gateway_host("P3000.LocalHost:45871"), 3000)
        self.assertEqual(parse_gateway_host("p3000.localhost."), 3000)   # FQDN dot
        self.assertEqual(parse_gateway_host(" p3000.localhost "), 3000)  # tolerant trim

    def test_rejects_foreign_hosts(self):
        for bad in ("localhost", "p3000", "p3000.example.com", "foo.localhost",
                    "localhost:47831", "p3000..localhost", "p.localhost",
                    "xp3000.localhost", "p3000.localhost:abc", "", None):
            with self.subTest(bad=bad):
                self.assertIsNone(parse_gateway_host(bad))

    def test_parse_does_not_range_check(self):
        # Port validation is the caller's job (PORT_INVALID comes after
        # BAD_HOST in the gateway's decision order).
        self.assertEqual(parse_gateway_host("p80.localhost"), 80)
        self.assertEqual(parse_gateway_host("p70000.localhost"), 70000)


class WebServiceRecordTests(unittest.TestCase):
    def test_fixture_round_trip(self):
        raw = _load("web-service-record.sample.json")
        rec = WebServiceRecord.from_dict(raw)
        self.assertEqual(rec.port, 3000)
        self.assertEqual(rec.name, "docs preview")
        self.assertEqual(rec.state, "registered")
        self.assertIsNone(rec.pid)
        self.assertEqual(rec.to_dict(), raw)

    def test_from_dict_fail_closed(self):
        good = _load("web-service-record.sample.json")
        cases = {
            "wrong schema": {**good, "schema_version": "aisc.web-service/v2"},
            "bad port": {**good, "port": 80},
            "port type": {**good, "port": "3000"},
            "bad state": {**good, "state": "ready"},
            "bad pid": {**good, "pid": "123"},
            "not an object": [good],
        }
        for label, bad in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    WebServiceRecord.from_dict(bad)

    def test_constructor_validates(self):
        with self.assertRaises(ValueError):
            WebServiceRecord(port=80)
        with self.assertRaises(ValueError):
            WebServiceRecord(port=3000, state="ready")


class WebGatewayInfoTests(unittest.TestCase):
    def test_ready_omits_reason(self):
        gw = WebGatewayInfo(state="ready", host_port=47831)
        self.assertEqual(gw.to_dict(), {
            "state": "ready",
            "container_port": 45871,
            "host_port": 47831,
            "host": "127.0.0.1",
        })

    def test_unavailable_carries_known_reason(self):
        gw = web_access_unavailable("legacy_runtime")
        self.assertEqual(gw.to_dict()["reason"], "legacy_runtime")
        with self.assertRaises(ValueError):
            WebGatewayInfo(state="unavailable", reason="made_up")
        with self.assertRaises(ValueError):
            WebGatewayInfo(state="ready", reason="legacy_runtime")
        with self.assertRaises(ValueError):
            WebGatewayInfo(state="bogus")

    def test_default_is_unavailable_silent(self):
        gw = WebGatewayInfo()
        self.assertEqual(gw.state, "unavailable")
        self.assertNotIn("reason", gw.to_dict())


class RuntimeServicesFixtureTests(unittest.TestCase):
    """svc-0 stage gate: Python decodes the shared fixture exactly."""

    def test_fixture_decodes(self):
        raw = _load("runtime-services.sample.json")
        result = RuntimeServicesResult.from_dict(raw)
        self.assertEqual(result.runtime_id, "0e7b7e3b-0000-4000-8000-000000000001")
        self.assertEqual(result.gateway.state, "ready")
        self.assertEqual(result.gateway.host_port, 47831)
        self.assertEqual(result.gateway.container_port, 45871)
        self.assertEqual([s.port for s in result.services], [3000, 5173])
        self.assertEqual(result.services[1].name, "")
        self.assertEqual(result.observed_at, "2026-08-25T00:00:00Z")

    def test_fixture_round_trips_byte_equal(self):
        raw = _load("runtime-services.sample.json")
        self.assertEqual(RuntimeServicesResult.from_dict(raw).to_dict(), raw)

    def test_fixture_urls_match_url_builder(self):
        raw = _load("runtime-services.sample.json")
        for svc in raw["services"]:
            self.assertEqual(
                svc["url"],
                build_service_url(svc["port"], raw["gateway"]["host_port"]),
            )

    def test_from_dict_fail_closed(self):
        raw = _load("runtime-services.sample.json")
        with self.assertRaises(ValueError):
            RuntimeServicesResult.from_dict({**raw, "schema_version": "aisc.runtime-services/v2"})
        with self.assertRaises(ValueError):
            RuntimeServicesResult.from_dict({**raw, "gateway": {**raw["gateway"], "state": "bogus"}})


if __name__ == "__main__":
    unittest.main()
