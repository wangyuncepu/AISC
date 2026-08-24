/**
 * Stage 11 (11d): terminal drop-path assembly + shell quoting (02 §4).
 *
 * Pure functions only — no shell is ever executed and no host shell is
 * guessed from locale or UI language (06 §6). Tests assert generated tokens.
 *
 * Path model (D11-15): every Workbench terminal is a Linux container shell
 * (`aisc session open` → `docker exec`), and the workspace is bind-mounted
 * at /root/app (CLI RunPlan `-v <workspace>:/root/app`,
 * src/aisc/domain/models.py). The HOST path does not exist inside the
 * container, so the drop token is built from the container mount.
 */

/** Container mount point of the workspace (single source of the mapping). */
export const CONTAINER_WORKSPACE_ROOT = "/root/app";

/** Map a workspace-relative path to the container-absolute path. */
export function containerPathFor(relativePath: string): string {
  const rel = relativePath.replace(/\\/g, "/").replace(/^\/+/, "");
  return rel === "" ? CONTAINER_WORKSPACE_ROOT : `${CONTAINER_WORKSPACE_ROOT}/${rel}`;
}

export type ShellHost = "posix" | "powershell" | "cmd";

/**
 * POSIX single-quote wrapping: everything between the quotes is literal;
 * an embedded `'` is closed, escaped and reopened (`'\''`).
 */
export function quotePosix(path: string): string {
  return `'${path.replace(/'/g, "'\\''")}'`;
}

/**
 * PowerShell single-quote wrapping: the only special character inside single
 * quotes is the quote itself, doubled to escape.
 */
export function quotePowerShell(path: string): string {
  return `'${path.replace(/'/g, "''")}'`;
}

/**
 * cmd.exe double-quote wrapping: internal double quotes are doubled. % and ^
 * expansion nuances are out of scope for the token itself (documented
 * best-effort per the Stage 11 quoting table).
 */
export function quoteCmd(path: string): string {
  return `"${path.replace(/"/g, '""')}"`;
}

export function quoteForHost(path: string, host: ShellHost): string {
  switch (host) {
    case "posix":
      return quotePosix(path);
    case "powershell":
      return quotePowerShell(path);
    case "cmd":
      return quoteCmd(path);
  }
}

/**
 * Quote for a Workbench terminal drop. The current session contract has no
 * PowerShell/cmd hosts — every session is a Linux container shell — so the
 * POSIX strategy is always selected (D11-14). The other strategies stay
 * implemented and tested for contract completeness.
 */
export function quoteForTerminal(path: string): string {
  return quotePosix(path);
}
