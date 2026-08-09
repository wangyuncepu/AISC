/**
 * Dictionary integrity tests (Step 4, A-G09-2): zh-CN/en-US key sets are
 * identical, no empty translations, interpolation placeholders match per key,
 * missing keys fail loudly (return the key, never a silent empty string),
 * and applyLocale clamps invalid values to zh-CN.
 */
import { describe, expect, it } from "vitest";
import { enUS } from "../en-US";
import { zhCN } from "../zh-CN";
import { applyLocale, i18n } from "../index";

const zh = zhCN as Record<string, string>;
const en = enUS as Record<string, string>;

function placeholders(s: string): string[] {
  const out: string[] = [];
  const re = /\{(\w+)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s)) !== null) out.push(m[1]);
  return out.sort();
}

describe("dictionary parity (A-G09-2)", () => {
  it("zh-CN and en-US have exactly the same keys", () => {
    const zhKeys = Object.keys(zh).sort();
    const enKeys = Object.keys(en).sort();
    expect(zhKeys).toEqual(enKeys);
  });

  it("no empty or whitespace-only translation in either locale", () => {
    for (const [k, v] of Object.entries(zh)) {
      expect(v.trim(), `zh-CN[${k}] is empty`).not.toBe("");
    }
    for (const [k, v] of Object.entries(en)) {
      expect(v.trim(), `en-US[${k}] is empty`).not.toBe("");
    }
  });

  it("interpolation placeholders match per key across locales", () => {
    for (const k of Object.keys(zh)) {
      expect(placeholders(en[k]), `en-US[${k}] placeholders`).toEqual(
        placeholders(zh[k])
      );
    }
  });

  it("missing keys fail loudly (return the key, never a silent string)", () => {
    expect(i18n.global.t("definitely.not.a.key")).toBe("definitely.not.a.key");
    expect(i18n.global.t("terminal.sessionError", { code: "X", message: "m" })).not.toBe("");
  });

  it("applyLocale clamps unknown values to zh-CN", () => {
    applyLocale("fr-FR");
    expect(i18n.global.locale.value).toBe("zh-CN");
    applyLocale("en-US");
    expect(i18n.global.locale.value).toBe("en-US");
  });
});
