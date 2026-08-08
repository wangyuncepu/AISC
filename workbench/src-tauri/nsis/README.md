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
