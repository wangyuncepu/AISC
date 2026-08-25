/**
 * Stage 1 (S1.1, F-A01): front-end layering dependency contract.
 *
 * Vue components must not own Runtime/Provider/Docker facts. This test scans
 * every `.vue` file and asserts that direct `lib/ipc` imports are limited to a
 * small allowlist of host/data-plane calls; anything that mutates runtime,
 * provider, docker, history or settings must go through a store.
 */
import { describe, expect, it } from "vitest";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

// Commands only stores/App-shell may call; a component referencing any of
// these (by name import or `ipc.<name>`) violates the layering contract.
const FORBIDDEN_IN_COMPONENTS = new Set([
  "startRuntime",
  "stopRuntime",
  "removeRuntime",
  "runtimePreflight",
  "runtimeInspect",
  "runtimeRestart",
  "listRuntimes",
  "startDocker",
  "cancelRuntimeStart",
  "negotiateCapabilities",
  "cliDiscover",
  "cliPin",
  "cliClearPin",
  "buildImage",
  "cancelBuild",
  "getProviderStatus",
  "openSession",
  "closeSession",
  "ackSessionExit",
  "loadHistory",
  "saveHistory",
  "loadSettings",
  "saveSettings",
  "resetGuiSettings",
  "runDoctor",
]);

// Host / terminal data-plane calls a component may legitimately make.
const ALLOWED_IN_COMPONENTS = new Set([
  "writeSession",
  "resizeSession",
  "captureWindowGeometry",
  "resolveLocale",
  "shutdownWorkbenchV2",
  "trayRemove",
  "trayAvailable",
]);

function srcRoot(): string {
  const candidates = [resolve(process.cwd(), "workbench/src"), resolve(process.cwd(), "src")];
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  throw new Error(`workbench/src not found under: ${process.cwd()}`);
}

function collectVueFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...collectVueFiles(full));
    } else if (entry.endsWith(".vue")) {
      out.push(full);
    }
  }
  return out;
}

/** Names imported directly from `lib/ipc` in a component. */
function directIpcImports(source: string): Set<string> {
  const names = new Set<string>();
  const named = /import\s*\{([^}]+)\}\s*from\s*["'][^"']*lib\/ipc["']/g;
  for (const match of source.matchAll(named)) {
    for (const part of match[1].split(",")) {
      const cleaned = part.trim();
      if (!cleaned) continue;
      // Contract keys on the underlying ipc command name, not a local alias.
      names.add(cleaned.split(" as ")[0].trim());
    }
  }
  const wildcard = /import\s*\*\s*as\s+(\w+)\s*from\s*["'][^"']*lib\/ipc["']/g;
  for (const match of source.matchAll(wildcard)) {
    const alias = match[1];
    const call = new RegExp(`\\b${alias}\\.(\\w+)`, "g");
    for (const c of source.matchAll(call)) {
      names.add(c[1]);
    }
  }
  return names;
}

describe("front-end layer contract (F-A01)", () => {
  it("components never import forbidden fact commands from lib/ipc", () => {
    const files = collectVueFiles(srcRoot());
    expect(files.length).toBeGreaterThan(0);
    for (const file of files) {
      const source = readFileSync(file, "utf-8");
      const names = directIpcImports(source);
      const banned = [...names].filter((n) => FORBIDDEN_IN_COMPONENTS.has(n));
      expect(banned, `${file} references forbidden ipc: ${banned.join(", ")}`).toEqual([]);
      for (const n of names) {
        expect(
          ALLOWED_IN_COMPONENTS.has(n),
          `${file}: ipc import "${n}" must be routed through a store`,
        ).toBe(true);
      }
    }
  });

  it("session open/close stays in the store, not in a component", () => {
    const files = collectVueFiles(srcRoot());
    for (const file of files) {
      const source = readFileSync(file, "utf-8");
      for (const banned of ["openSession", "closeSession", "ackSessionExit"]) {
        expect(
          directIpcImports(source).has(banned),
          `${file} must not import ${banned} directly`,
        ).toBe(false);
      }
    }
  });
});
