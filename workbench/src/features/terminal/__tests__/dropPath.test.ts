/**
 * Stage 11 (11d): terminal drop-path assembly + shell quoting.
 *
 * Tests assert GENERATED TOKENS only — no shell is executed anywhere
 * (04 §1 quoting 测试要求).
 */
import { describe, expect, it } from "vitest";
import {
  CONTAINER_WORKSPACE_ROOT,
  containerPathFor,
  quoteCmd,
  quoteForHost,
  quoteForTerminal,
  quotePosix,
  quotePowerShell,
} from "../dropPath";

describe("containerPathFor (D11-15)", () => {
  it("maps workspace-relative paths onto the container mount", () => {
    expect(CONTAINER_WORKSPACE_ROOT).toBe("/root/app");
    expect(containerPathFor("a.md")).toBe("/root/app/a.md");
    expect(containerPathFor("src/lib/main.ts")).toBe("/root/app/src/lib/main.ts");
    expect(containerPathFor("报告 (终稿).md")).toBe("/root/app/报告 (终稿).md");
  });

  it("normalizes separators and leading slashes", () => {
    expect(containerPathFor("src\\x.ts")).toBe("/root/app/src/x.ts");
    expect(containerPathFor("/a.md")).toBe("/root/app/a.md");
    expect(containerPathFor("")).toBe("/root/app");
  });
});

describe("quotePosix (current terminal host, D11-14)", () => {
  it("wraps plain and spaced paths in single quotes", () => {
    expect(quotePosix("/root/app/a.md")).toBe("'/root/app/a.md'");
    expect(quotePosix("/root/app/my file.md")).toBe("'/root/app/my file.md'");
  });

  it("keeps $, backslash, double quotes, parens and unicode literal", () => {
    expect(quotePosix("/root/app/$HOME (x).md")).toBe("'/root/app/$HOME (x).md'");
    expect(quotePosix("/root/app/a\\b")).toBe("'/root/app/a\\b'");
    expect(quotePosix('/root/app/say "hi"')).toBe(`'/root/app/say "hi"'`);
    expect(quotePosix("/root/app/中文 名.md")).toBe("'/root/app/中文 名.md'");
  });

  it("escapes embedded single quotes with the standard splice", () => {
    expect(quotePosix("/root/app/it's.md")).toBe(`'/root/app/it'\\''s.md'`);
  });

  it("keeps trailing backslashes and newlines literal", () => {
    expect(quotePosix("/root/app/trail\\")).toBe("'/root/app/trail\\'");
    expect(quotePosix("a\nb")).toBe("'a\nb'");
  });
});

describe("quotePowerShell / quoteCmd (implemented for contract completeness)", () => {
  it("powershell doubles embedded single quotes", () => {
    expect(quotePowerShell("/root/app/a b.md")).toBe("'/root/app/a b.md'");
    expect(quotePowerShell("/root/app/it's.md")).toBe("'/root/app/it''s.md'");
  });

  it("cmd doubles embedded double quotes", () => {
    expect(quoteCmd("C:\\my file\\a.md")).toBe('"C:\\my file\\a.md"');
    expect(quoteCmd('C:\\say "hi"')).toBe('"C:\\say ""hi"""');
  });

  it("quoteForHost dispatches per host; the terminal always uses posix", () => {
    expect(quoteForHost("a b", "posix")).toBe("'a b'");
    expect(quoteForHost("a b", "powershell")).toBe("'a b'");
    expect(quoteForHost('a "b"', "cmd")).toBe('"a ""b"""');
    expect(quoteForTerminal("/root/app/a b.md")).toBe("'/root/app/a b.md'");
  });
});
