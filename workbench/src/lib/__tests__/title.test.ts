/**
 * Window title pure-function tests (G-15, Step 14; A-G15-1/2/3).
 */
import { describe, expect, it } from "vitest";
import {
  PRODUCT_TITLE,
  computeWindowTitle,
  truncateGraphemes,
  workspaceBasename,
} from "../title";

describe("workspaceBasename (A-G15-1)", () => {
  it("handles POSIX and Windows separators", () => {
    expect(workspaceBasename("/home/user/project")).toBe("project");
    expect(workspaceBasename("C:\\Users\\VE111\\Downloads\\test")).toBe("test");
    expect(workspaceBasename("C:\\Users\\VE111\\Documents\\AISC")).toBe("AISC");
  });

  it("strips trailing separators before taking the basename", () => {
    expect(workspaceBasename("/home/user/project/")).toBe("project");
    expect(workspaceBasename("C:\\Users\\VE111\\Downloads\\test\\")).toBe("test");
    expect(workspaceBasename("/a/")).toBe("a");
  });

  it("drive root keeps a sensible basename", () => {
    expect(workspaceBasename("C:\\")).toBe("C:");
    expect(workspaceBasename("C:/")).toBe("C:");
  });

  it("empty / blank workspace yields empty basename", () => {
    expect(workspaceBasename("")).toBe("");
    expect(workspaceBasename("   ")).toBe("");
  });
});

describe("computeWindowTitle (A-G15-2 priority)", () => {
  it("active session -> workspace · Session type · product", () => {
    expect(
      computeWindowTitle({ workspace: "/ws/proj", sessionType: "bash" })
    ).toBe("proj · Bash · AISC Workbench");
    expect(
      computeWindowTitle({ workspace: "C:\\ws\\proj", sessionType: "claude" })
    ).toBe("proj · Claude · AISC Workbench");
  });

  it("workspace without a session leaf -> workspace · product (no stale type)", () => {
    expect(computeWindowTitle({ workspace: "/ws/proj", sessionType: null })).toBe(
      "proj · AISC Workbench"
    );
  });

  it("no workspace at all -> product only", () => {
    expect(computeWindowTitle({ workspace: "", sessionType: null })).toBe(PRODUCT_TITLE);
    expect(computeWindowTitle({ workspace: "", sessionType: "codex" })).toBe(
      "Codex · AISC Workbench"
    );
  });
});

describe("truncateGraphemes (A-G15-3)", () => {
  it("keeps short names untouched", () => {
    expect(truncateGraphemes("project")).toBe("project");
  });

  it("truncates long names to first/last 18 graphemes with …", () => {
    const long = "a".repeat(60);
    const t = truncateGraphemes(long);
    expect(t.length).toBe(18 + 1 + 18);
    expect(t.startsWith("a".repeat(18))).toBe(true);
    expect(t.endsWith("a".repeat(18))).toBe(true);
    expect(t[18]).toBe("…");
  });

  it("does not split CJK / emoji grapheme clusters", () => {
    // 50 CJK chars (>40 limit) + 30 emoji (multi-codepoint ZWJ/combining).
    const cjk = "汉".repeat(50);
    const emoji = "👩‍💻".repeat(50); // ZWJ sequence = 1 grapheme, 5 codepoints
    expect(truncateGraphemes(cjk).replace(/[^…]/g, "").length).toBe(1);
    expect(truncateGraphemes(emoji)).toBe(`${"👩‍💻".repeat(18)}…${"👩‍💻".repeat(18)}`);
    // No lone combining characters / partial ZWJ sequences.
    expect(truncateGraphemes(emoji).includes("\u200d")).toBe(true); // ZWJ kept inside clusters
    expect(truncateGraphemes(emoji).match(/[\u200d…]/g)?.length).toBe(18 + 18 + 1);
  });
});
