/**
 * Stage 11 (11d): extension → file-type icon mapping (02 §5).
 *
 * Icons are a VISUAL hint only — name, tooltip, selection state and a11y
 * labels remain the semantic carriers. Every unknown extension falls back to
 * the generic file icon (D11-08: generic fallback mandatory).
 */

export type FileIconKind =
  | "typescript"
  | "javascript"
  | "python"
  | "rust"
  | "json"
  | "markdown"
  | "image"
  | "archive"
  | "config"
  | "generic-file";

const EXT_KIND: Record<string, FileIconKind> = {
  ts: "typescript",
  tsx: "typescript",
  mts: "typescript",
  cts: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  py: "python",
  pyw: "python",
  pyi: "python",
  rs: "rust",
  json: "json",
  jsonc: "json",
  md: "markdown",
  markdown: "markdown",
  mdx: "markdown",
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  svg: "image",
  ico: "image",
  bmp: "image",
  zip: "archive",
  tar: "archive",
  gz: "archive",
  tgz: "archive",
  bz2: "archive",
  xz: "archive",
  "7z": "archive",
  rar: "archive",
  toml: "config",
  yaml: "config",
  yml: "config",
  ini: "config",
  cfg: "config",
  conf: "config",
  env: "config",
};

/** Icon kind for a file basename (case-insensitive extension). */
export function fileIconKind(name: string): FileIconKind {
  const idx = name.lastIndexOf(".");
  if (idx <= 0 || idx === name.length - 1) return "generic-file";
  const ext = name.slice(idx + 1).toLowerCase();
  return EXT_KIND[ext] ?? "generic-file";
}
