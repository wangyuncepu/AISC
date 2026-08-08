# NSIS installer template

`installer.nsi` is a **Handlebars template** rendered by tauri-bundler at build
time (`bundle.windows.nsis.template`). It is a copy of the tauri-bundler 2.9.4
default template with S4.1.b additions:

- `PageDepsCheck` (custom page after the Start Menu page): detects Docker
  Desktop / Python 3 / winget / WebView2 and lets the user install the missing
  ones, start Docker Desktop, or open the Microsoft Store for winget.
- `Section Dependencies` (runs before the WebView2 section): installs Docker
  Desktop (`Docker.DockerDesktop`) and Python 3.12 (`Python.Python.3.12`) via
  winget when the user opted in. Failures do not abort the install; the
  Workbench preflight reports missing dependencies at first launch.

Source: `https://crates.io/crates/tauri-bundler` 2.9.4,
`src/bundle/windows/nsis/installer.nsi`.

## Bundled AISC CLI bundle (aisc-bundle)

The installer ships the full AISC CLI bundle (`aisc-bundle\`) next to the
sidecar exe so CLI root discovery works on an installed Workbench without a
repository checkout (`resources.py` frozen-bundle branch). The bundle is
**not** committed: CI stages it via `python packaging/artifact.py stage --root . --output workbench/src-tauri/nsis/bundle` before `tauri build` (fails fast on verification), and `tauri.conf.json` maps it into `$INSTDIR` with `bundle.resources` (`nsis/bundle/aisc-bundle` -> `aisc-bundle`, recursive directory copy rendered as one `File /a "/oname=..."` per file by the NSIS template). Locally, `tauri build` requires the staging step to have run first — same friction class as the externalBin sidecar.

## Maintenance

When upgrading tauri-bundler (via `@tauri-apps/cli`), diff this file against
the new default template and re-apply the S4.1.b additions:

1. `Var Deps*` declarations in the header var block.
2. The dependency page + functions between `MUI_PAGE_STARTMENU` and
   `MUI_PAGE_INSTFILES`.
3. `Section Dependencies` between `Section EarlyChecks` and `Section WebView2`.

Keep all other `{{handlebars}}` placeholders intact - they are required by the
renderer. Do not delete or renumber the page comments; the template depends on
the MUI page order.
