/**
 * Stage 11 (11c): inline name-input validation (frontend mirror of the Rust
 * basename gate, D11-22).
 */
import { describe, expect, it } from "vitest";
import { validateBasename } from "../basename";

describe("validateBasename", () => {
  it("accepts plain, unicode, spaced and bracketed basenames", () => {
    expect(validateBasename("a.md")).toBeNull();
    expect(validateBasename("报告 (终稿).md")).toBeNull();
    expect(validateBasename("文件 名字.txt")).toBeNull();
    expect(validateBasename("a(b)c.rs")).toBeNull();
    expect(validateBasename("日本語メモ.md")).toBeNull();
    expect(validateBasename(".hidden")).toBeNull();
  });

  it("rejects empty and whitespace-only names", () => {
    expect(validateBasename("")).toBe("empty");
    expect(validateBasename("   ")).toBe("empty");
  });

  it("rejects dot names", () => {
    expect(validateBasename(".")).toBe("dot");
    expect(validateBasename("..")).toBe("dot");
  });

  it("rejects path separators", () => {
    expect(validateBasename("a/b")).toBe("separator");
    expect(validateBasename("a\\b")).toBe("separator");
  });

  it("rejects control characters", () => {
    expect(validateBasename("a\u{0}b")).toBe("control");
    expect(validateBasename("a\u{7}b")).toBe("control");
    expect(validateBasename("a\u{7f}b")).toBe("control");
  });

  it("rejects trailing dots and spaces (Windows-illegal)", () => {
    expect(validateBasename("name.")).toBe("trailing");
    expect(validateBasename("name ")).toBe("trailing");
  });

  it("rejects Windows reserved device stems in any extension form", () => {
    expect(validateBasename("CON")).toBe("reserved");
    expect(validateBasename("con")).toBe("reserved");
    expect(validateBasename("CON.txt")).toBe("reserved");
    expect(validateBasename("NUL.bin")).toBe("reserved");
    expect(validateBasename("com1")).toBe("reserved");
    expect(validateBasename("LPT9.log")).toBe("reserved");
    // `console` is a normal name — only the exact stem is reserved.
    expect(validateBasename("console.log")).toBeNull();
  });
});
