/**
 * Stage 11 (11c): frontend mirror of the Rust `validate_basename` gate.
 * Gives the inline name input instant feedback; Rust re-validates on every
 * mutation regardless (06 §2). Rules are identical and enforced on all
 * platforms so a workspace stays Windows-portable (D11-22).
 */

export type BasenameError =
  | "empty"
  | "dot"
  | "separator"
  | "control"
  | "trailing"
  | "reserved";

/** Windows reserved device stems, invalid in any extension form. */
const RESERVED_STEMS = new Set([
  "CON", "PRN", "AUX", "NUL",
  "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
  "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
]);

/** Validate a single basename. Returns null when the name is acceptable. */
export function validateBasename(name: string): BasenameError | null {
  if (name.length === 0 || name.trim().length === 0) return "empty";
  if (name === "." || name === "..") return "dot";
  if (name.includes("/") || name.includes("\\")) return "separator";
  if (name.includes("\0") || Array.from(name).some((c) => {
    const code = c.charCodeAt(0);
    return code < 0x20 || code === 0x7f;
  })) {
    return "control";
  }
  if (name.endsWith(".") || name.endsWith(" ")) return "trailing";
  const stem = name.split(".")[0] ?? "";
  if (RESERVED_STEMS.has(stem.toUpperCase())) return "reserved";
  return null;
}
