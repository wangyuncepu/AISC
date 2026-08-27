/**
 * Stage 1 (S1.5, F-A05): snapshot freshness + late-response handling.
 *
 * applyRuntimeSnapshot keeps monotonic seq: an older response never overwrites
 * a newer snapshot (F-R04/F-R05). markStale preserves the last-known snapshot
 * while reporting "stale"; an operation error never clears the fact state.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useRuntimeStore } from "../runtime";
import type { RuntimeSnapshot } from "../../types";

vi.mock("../../lib/ipc", () => ({}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ confirm: vi.fn(), open: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ Channel: class {} }));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => ({}) }));
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
}));

function snap(state: string, observedAt: string): RuntimeSnapshot {
  return {
    runtime_id: "r1",
    state: state as RuntimeSnapshot["state"],
    config: { workspace: "/w", image: "img", network: "direct", scope: "project" },
    owner: "workbench",
    config_fingerprint: "fp",
    container_name: "c",
    container_id: "cid",
    registry_state: "registered",
    observed_at: observedAt,
    stale: false,
  };
}

describe("runtime snapshot freshness (S1.5)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("applies snapshots in order, latest wins", () => {
    const store = useRuntimeStore();
    store.applyRuntimeSnapshot(snap("starting", "t1"), 1);
    expect(store.runtimeState).toBe("starting");
    expect(store.freshness).toBe("fresh");
    expect(store.runtimeSnapshot?.observed_at).toBe("t1");

    store.applyRuntimeSnapshot(snap("running", "t2"), 2);
    expect(store.runtimeState).toBe("running");
    expect(store.runtimeSnapshot?.observed_at).toBe("t2");
  });

  it("drops a late (lower-seq) response without touching newer state", () => {
    const store = useRuntimeStore();
    store.applyRuntimeSnapshot(snap("running", "t2"), 2);
    expect(store.runtimeState).toBe("running");

    store.applyRuntimeSnapshot(snap("stopped", "t1"), 1); // late stale response
    expect(store.runtimeState).toBe("running");
    expect(store.runtimeSnapshot?.observed_at).toBe("t2");
  });

  it("markStale keeps the last snapshot while reporting stale", () => {
    const store = useRuntimeStore();
    store.applyRuntimeSnapshot(snap("running", "t2"), 1);
    store.markStale();
    expect(store.freshness).toBe("stale");
    expect(store.runtimeState).toBe("running"); // fact preserved
  });

  it("stale state remains stale until a fresh snapshot lands", () => {
    const store = useRuntimeStore();
    store.applyRuntimeSnapshot(snap("running", "t2"), 1);
    store.markStale();
    store.markStale();
    expect(store.freshness).toBe("stale");

    store.applyRuntimeSnapshot(snap("running", "t3"), 2);
    expect(store.freshness).toBe("fresh");
  });
});

describe("poll value-gate (v2.1.7 S5 / #28)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("a semantically identical snapshot keeps object identity (no re-render)", () => {
    const store = useRuntimeStore();
    store.applyRuntimeSnapshot(snap("running", "t1"), 1);
    const applied = store.runtimeSnapshot;
    // Identical content, only observed_at moved (the every-poll case).
    store.applyRuntimeSnapshot(snap("running", "t2"), 2);
    expect(store.runtimeSnapshot).toBe(applied); // SAME reference — no churn
    expect(store.freshness).toBe("fresh"); // freshness semantics preserved
    expect(store.runtimeSnapshot?.observed_at).toBe("t1"); // kept the old object
  });

  it("a genuinely different snapshot replaces the object", () => {
    const store = useRuntimeStore();
    store.applyRuntimeSnapshot(snap("running", "t1"), 1);
    const applied = store.runtimeSnapshot;
    store.applyRuntimeSnapshot(snap("stopped", "t2"), 2);
    expect(store.runtimeSnapshot).not.toBe(applied);
    expect(store.runtimeState).toBe("stopped");
  });
});
