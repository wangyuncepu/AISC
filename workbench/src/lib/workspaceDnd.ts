/**
 * Stage 11 (11d): the single controlled drag-drop contract between the
 * Workspace Explorer and the Terminal (02 §4).
 *
 * The payload carries ONLY the workspace-relative path — never an absolute
 * path, file content or OS file URL. The container-path mapping happens at
 * the terminal drop boundary (D11-15).
 */
export const WORKSPACE_PATH_MIME = "application/x-aisc-workspace-path";
