/**
 * Stage 11 (11d): extension → icon-kind mapping (02 §5).
 */
import { describe, expect, it } from "vitest";
import { fileIconKind } from "../iconKind";

describe("fileIconKind", () => {
  it("maps known extensions (case-insensitive)", () => {
    expect(fileIconKind("main.ts")).toBe("typescript");
    expect(fileIconKind("App.TSX")).toBe("typescript");
    expect(fileIconKind("index.js")).toBe("javascript");
    expect(fileIconKind("app.mjs")).toBe("javascript");
    expect(fileIconKind("cli.py")).toBe("python");
    expect(fileIconKind("lib.rs")).toBe("rust");
    expect(fileIconKind("package.json")).toBe("json");
    expect(fileIconKind("README.md")).toBe("markdown");
    expect(fileIconKind("logo.svg")).toBe("image");
    expect(fileIconKind("photo.JPG")).toBe("image");
    expect(fileIconKind("bundle.tar.gz")).toBe("archive");
    expect(fileIconKind("Cargo.toml")).toBe("config");
    expect(fileIconKind("ci.yaml")).toBe("config");
  });

  it("falls back to the generic file icon", () => {
    expect(fileIconKind("data.bin")).toBe("generic-file");
    expect(fileIconKind("noext")).toBe("generic-file");
    expect(fileIconKind("trailing.")).toBe("generic-file");
    expect(fileIconKind(".hidden")).toBe("generic-file");
  });
});
