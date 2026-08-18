/**
 * Stage 0 (S0.2): TypeScript consumer of the shared `aisc.cli/v1` fixtures.
 *
 * B-A03: Python/Rust/TS all parse the same files under tests/fixtures/cli/.
 * These tests assert the envelope shapes match the TS domain types and that
 * unknown fields / unsupported-protocol behavior hold in the fixture set.
 */
import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Capabilities, VersionInfo } from "../../types";

// Locate the repo-root fixtures from the vitest cwd (workbench/). `..` from
// workbench/ reaches the repo root directly; the repo-root case is kept for
// direct `vitest` invocations.
function fixtureRoot(): string {
  const candidates = [
    resolve(process.cwd(), "../tests/fixtures/cli"),
    resolve(process.cwd(), "tests/fixtures/cli"),
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  throw new Error(`cli fixtures not found under: ${process.cwd()}`);
}
const FIXTURES = fixtureRoot();

function read(name: string): string {
  return readFileSync(resolve(FIXTURES, name), "utf-8");
}

/** The repo VERSION the CLI reports (mirrors the Python contract test: the
 * version fixture moves with every bump — read it, don't hardcode). */
function repoVersion(): string {
  for (const root of [resolve(FIXTURES, "../.."), resolve(FIXTURES, "../../..")]) {
    const p = resolve(root, "VERSION");
    if (existsSync(p)) return readFileSync(p, "utf-8").trim();
  }
  throw new Error("VERSION not found relative to fixtures");
}

interface Envelope {
  meta: {
    protocol: string;
    command: string;
    exit_code: number;
    timestamp: string;
    version: string;
    run_id: string;
  };
  data: unknown;
  errors: Array<{ code: string; message: string; hint: string | null }>;
}

describe("aisc.cli/v1 fixture set (TS consumer)", () => {
  it("version envelope matches the TS VersionInfo/Capabilities shapes", () => {
    const env = JSON.parse(read("envelope-version.json")) as Envelope;
    expect(env.meta.protocol).toBe("aisc.cli/v1");
    expect(env.meta.command).toBe("version");
    expect(env.meta.exit_code).toBe(0);
    expect(env.errors).toEqual([]);

    const vi = env.data as VersionInfo & { capabilities: Capabilities };
    expect(vi.cli_version).toBe(repoVersion());
    expect(env.meta.version).toBe(repoVersion());
    expect(vi.capabilities.runtime).toBe("aisc.runtime/v1");
    expect(vi.capabilities.session).toBe("aisc.session/v1");
    expect(vi.capabilities.providerStatus).toBe("aisc.provider-status/v1");
    expect(vi.capabilities.buildEvents).toBe("aisc.build-events/v1");
  });

  it("error envelopes carry stable codes and matching exit codes", () => {
    const invalid = JSON.parse(read("envelope-error-invalid-runtime-id.json")) as Envelope;
    expect(invalid.meta.exit_code).toBe(15);
    expect(invalid.errors[0].code).toBe("AISC_ERR_INVALID_RUNTIME_ID");

    const usage = JSON.parse(read("envelope-error-usage.json")) as Envelope;
    expect(usage.meta.exit_code).toBe(2);
    expect(usage.errors[0].code).toBe("AISC_ERR_USAGE");
  });

  it("unknown fields survive a JSON round-trip", () => {
    const env = JSON.parse(read("envelope-unknown-field.json")) as Record<string, unknown>;
    const again = JSON.parse(JSON.stringify(env)) as Record<string, unknown>;
    expect((again["x_future_top_level"] as { kept: boolean }).kept).toBe(true);
    expect(again["x_data_future_note"]).toBeDefined();
  });

  it("unsupported protocol fixture is the negative case", () => {
    const env = JSON.parse(read("envelope-unsupported-protocol.json")) as Envelope;
    expect(env.meta.protocol).toBe("aisc.cli/v2");
    expect(env.meta.protocol).not.toBe("aisc.cli/v1");
  });

  it("build events JSONL is parseable and sequential", () => {
    const lines = read("events-build.jsonl").split(/\r?\n/).filter((l) => l.trim().length > 0);
    expect(lines).toHaveLength(5);
    lines.forEach((line, i) => {
      const ev = JSON.parse(line) as {
        protocol: string;
        seq: number;
        type: string;
        data: Record<string, unknown>;
      };
      expect(ev.protocol).toBe("aisc.cli/v1");
      expect(ev.seq).toBe(i + 1);
    });
    const last = JSON.parse(lines[4]) as { type: string; data: { exit_code: number } };
    expect(last.type).toBe("build.complete");
    expect(last.data.exit_code).toBe(0);
  });

  it("error-codes manifest lists the required stable codes", () => {
    const codes = JSON.parse(read("error-codes.json")) as Record<
      string,
      { exit_code: number; retryable: boolean; action: string }
    >;
    for (const code of [
      "AISC_ERR_USAGE",
      "AISC_ERR_INVALID_RUNTIME_ID",
      "AISC_ERR_CLI_NOT_FOUND",
      "AISC_ERR_DOCKER_UNAVAILABLE",
      "AISC_ERR_IMAGE_MISSING",
      "AISC_ERR_BUILD_FAILED",
    ]) {
      expect(codes[code]).toBeDefined();
      expect(typeof codes[code].exit_code).toBe("number");
      expect(typeof codes[code].action).toBe("string");
    }
  });
});
