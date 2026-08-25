/**
 * svc-0 (container web-service access): TypeScript consumer of the shared
 * fixtures under tests/fixtures/web-services/.
 *
 * Python (tests/test_web_services.py) and Rust
 * (workbench/src-tauri/tests/web_services.rs) parse the same files — the
 * svc-0 stage gate is all three decoding identically. See
 * docs/plans/container-service-access/decisions.md.
 */
import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { RuntimeServicesResult } from "../../types";
import {
  GATEWAY_HOST_SUFFIX,
  RUNTIME_SERVICES_SCHEMA_V1,
  WEB_GATEWAY_CONTAINER_PORT,
  WEB_GATEWAY_HOST_BIND,
  WEB_GATEWAY_HOST_PORT_MAX,
  WEB_GATEWAY_HOST_PORT_MIN,
  WEB_SERVICE_PORT_MAX,
  WEB_SERVICE_PORT_MIN,
  WEB_SERVICE_PROTOCOL,
  WEB_SERVICE_SCHEMA_V1,
  buildServiceUrl,
  isExposablePort,
  isRuntimeServicesPayload,
  parseExposePort,
  parseGatewayHost,
} from "../webServices";

function fixtureRoot(): string {
  const candidates = [
    resolve(process.cwd(), "../tests/fixtures/web-services"),
    resolve(process.cwd(), "tests/fixtures/web-services"),
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  throw new Error(`web-services fixtures not found under: ${process.cwd()}`);
}
const FIXTURES = fixtureRoot();

function readJson(name: string): unknown {
  return JSON.parse(readFileSync(resolve(FIXTURES, name), "utf-8"));
}

describe("svc-0 frozen constants", () => {
  it("mirror the Python authoritative values", () => {
    expect(WEB_GATEWAY_CONTAINER_PORT).toBe(45871);
    expect([WEB_GATEWAY_HOST_PORT_MIN, WEB_GATEWAY_HOST_PORT_MAX]).toEqual([47000, 47999]);
    expect([WEB_SERVICE_PORT_MIN, WEB_SERVICE_PORT_MAX]).toEqual([1024, 65535]);
    expect(WEB_GATEWAY_HOST_BIND).toBe("127.0.0.1");
    expect(WEB_SERVICE_SCHEMA_V1).toBe("aisc.web-service/v1");
    expect(RUNTIME_SERVICES_SCHEMA_V1).toBe("aisc.runtime-services/v1");
    expect(WEB_SERVICE_PROTOCOL).toBe("http");
    expect(GATEWAY_HOST_SUFFIX).toBe(".localhost");
  });
});

describe("parseExposePort", () => {
  it("accepts decimal strings in range", () => {
    expect(parseExposePort("1024")).toBe(1024);
    expect(parseExposePort("3000")).toBe(3000);
    expect(parseExposePort("65535")).toBe(65535);
  });

  it("rejects non-decimal and out-of-range", () => {
    for (const bad of ["", " 3000", "3000x", "3.5", "-1", "+3000", "0", "1023", "65536"]) {
      expect(parseExposePort(bad), bad).toBeNull();
    }
  });
});

describe("isExposablePort", () => {
  it("bounds 1024..65535", () => {
    expect(isExposablePort(1023)).toBe(false);
    expect(isExposablePort(1024)).toBe(true);
    expect(isExposablePort(65535)).toBe(true);
    expect(isExposablePort(65536)).toBe(false);
    expect(isExposablePort(3000.5)).toBe(false);
  });
});

describe("buildServiceUrl", () => {
  it("builds the canonical p<port>.localhost URL", () => {
    expect(buildServiceUrl(3000, 47831)).toBe("http://p3000.localhost:47831/");
    expect(buildServiceUrl(5173, 47000)).toBe("http://p5173.localhost:47000/");
  });

  it("throws on out-of-range ports", () => {
    expect(() => buildServiceUrl(80, 47831)).toThrow(RangeError);
    expect(() => buildServiceUrl(3000, 0)).toThrow(RangeError);
  });
});

describe("parseGatewayHost", () => {
  it("accepts canonical forms", () => {
    expect(parseGatewayHost("p3000.localhost")).toBe(3000);
    expect(parseGatewayHost("p3000.localhost:47831")).toBe(3000);
    expect(parseGatewayHost("P3000.LocalHost:45871")).toBe(3000);
    expect(parseGatewayHost("p3000.localhost.")).toBe(3000);
  });

  it("rejects foreign hosts", () => {
    for (const bad of [
      "localhost", "p3000", "p3000.example.com", "foo.localhost",
      "p3000..localhost", "p.localhost", "p3000.localhost:abc", "",
    ]) {
      expect(parseGatewayHost(bad), bad).toBeNull();
    }
  });

  it("does not range-check the parsed port", () => {
    expect(parseGatewayHost("p80.localhost")).toBe(80);
  });
});

describe("svc-0 shared fixtures", () => {
  const raw = readJson("runtime-services.sample.json") as RuntimeServicesResult;

  it("decodes the runtime-services payload", () => {
    expect(isRuntimeServicesPayload(raw)).toBe(true);
    expect(raw.runtime_id).toBe("0e7b7e3b-0000-4000-8000-000000000001");
    expect(raw.gateway.state).toBe("ready");
    expect(raw.gateway.host_port).toBe(47831);
    expect(raw.gateway.container_port).toBe(45871);
    expect(raw.gateway.host).toBe("127.0.0.1");
    expect(raw.services.map((s) => s.port)).toEqual([3000, 5173]);
    expect(raw.services[1].name).toBe("");
    expect(raw.observed_at).toBe("2026-08-25T00:00:00Z");
  });

  it("fixture URLs match the URL builder", () => {
    for (const svc of raw.services) {
      expect(svc.url).toBe(buildServiceUrl(svc.port, raw.gateway.host_port));
    }
  });

  it("fail-closes on a foreign schema version", () => {
    const foreign = { ...raw, schema_version: "aisc.runtime-services/v2" };
    expect(isRuntimeServicesPayload(foreign)).toBe(false);
    expect(isRuntimeServicesPayload(null)).toBe(false);
    expect(isRuntimeServicesPayload(42)).toBe(false);
  });

  it("decodes the web-service record sample", () => {
    const rec = readJson("web-service-record.sample.json") as Record<string, unknown>;
    expect(rec.schema_version).toBe(WEB_SERVICE_SCHEMA_V1);
    expect(rec.port).toBe(3000);
    expect(rec.state).toBe("registered");
    expect(rec.pid).toBeNull();
  });
});
