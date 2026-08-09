/**
 * i18n bootstrap (Step 4, G-09). Two full dictionaries (zh-CN/en-US); the
 * active locale is resolved by the backend (`resolve_locale`): explicit
 * ui.language wins, else installer, else system, else zh-CN (02 §3.1).
 */
import { createI18n } from "vue-i18n";
import { zhCN } from "./zh-CN";
import { enUS } from "./en-US";

export const i18n = createI18n({
  legacy: false,
  locale: "zh-CN", // replaced as soon as resolve_locale returns
  fallbackLocale: "zh-CN",
  messages: {
    "zh-CN": zhCN,
    "en-US": enUS,
  },
});

export const SUPPORTED_LOCALES = ["zh-CN", "en-US"] as const;
export type AppLocale = (typeof SUPPORTED_LOCALES)[number];

/** Apply a resolved locale (runtime switching, A-G09-3). */
export function applyLocale(locale: string): void {
  const l = SUPPORTED_LOCALES.includes(locale as AppLocale) ? (locale as AppLocale) : "zh-CN";
  i18n.global.locale.value = l;
}
