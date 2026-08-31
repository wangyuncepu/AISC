---
name: artifact
description: |
  Classify and register Agent-generated deliverable files so the Workbench can
  surface them. Use when you create, modify, delete, or rename a file the user
  will want to open — reports, docs, data exports, generated configs. This
  skill provides the classification semantics and the registration call; it is
  NOT itself a fact database (the `aisc artifact record` call is the
  authoritative fact).
allowed-tools:
  - Bash
---

# Artifact

When you finish a task that produced files, decide whether each is worth
surfacing and classify it, then register it with `aisc artifact record`.

## Classification

| kind | What it is | Examples |
|---|---|---|
| `deliverable` | A file the user asked for or will want to open | report.md, summary.pdf, analysis.json, chart.png |
| `source_change` | An edit to project source the user maintains | src/foo.py, workbench/App.vue |
| `generated_output` | A reproducible build/cache artifact | build/out.txt, dist/bundle.js, coverage/ |

Rule of thumb: if you'd mention it in your final answer as something the user
should look at, it's a `deliverable`.

## Register

The session environment already knows your identity — `AISC_AGENT`,
`AISC_TERMINAL_SESSION_ID` and `AISC_RUNTIME_ID` are set in every Workbench
terminal — and `aisc artifact record` reads them as defaults. The minimal
registration is therefore:

```sh
aisc artifact record \
  --path <relative/path> \
  --kind deliverable \
  --action created \
  --media-type text/markdown \
  --label "<short human label>"
```

- `--path` MUST be relative to the workspace root, never absolute, using
  `/` separators (no leading `/`, no `..`, no backslashes). A
  `/root/app/...` prefix is tolerated and stripped, but relative is
  preferred.
- `--agent` / `--session-id` / `--runtime-id` default from the session env
  (`AISC_AGENT`, `AISC_TERMINAL_SESSION_ID`, `AISC_RUNTIME_ID`). Pass flags
  only when the env is missing — never hardcode another agent's name.
- `--action` is `created` | `modified` | `deleted` | `renamed`
  (`renamed` requires `--previous-path`).
- `--media-type` uses `type/subtype` (e.g. `text/markdown`, `application/pdf`).
- Registration is idempotent per (path, action, kind): re-recording the same
  fact updates it instead of duplicating.
- If `aisc` is genuinely unavailable (`command not found`), do NOT fake a
  registry — list the relative paths in your final answer and say the
  registration could not run; the Workbench watcher will show the change as
  unattributed.

## Output in your final answer

Always list deliverable paths as **workspace-relative** paths (e.g.
`reports/result.md`), NOT container-absolute (`/root/app/reports/result.md`)
and NOT host-absolute. The workspace is bind-mounted with the same relative
structure in the container and on the host, so a relative path resolves
correctly on both — the Workbench turns it into the host absolute path when
the user opens/copies it. Never print a container absolute path: it cannot be
resolved on the host. Keep the list human-readable — the GUI does not parse
this as a fact source.
