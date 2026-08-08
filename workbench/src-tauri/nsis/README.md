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
- Dependency detection (`CheckDocker` / `CheckPython`): Docker Desktop is
  detected by executable presence (per-user `%LOCALAPPDATA%` or machine-wide
  `Program Files\Docker\Docker`) with the uninstaller registry entry
  `InstallLocation` as a non-standard-path fallback; Python enumerates the
  `PythonCore\<version>\InstallPath` subkeys (HKLM 64/32-bit views + HKCU)
  and verifies `python.exe` exists - the old check read the empty default
  value of `PythonCore` itself and never matched. winget runs through
  `nsExec::ExecToStack` (hidden console - `ExecWait` popped a console
  window, and `ExecToLog` misdecodes winget's UTF-8 piped output as the ANSI
  codepage, producing mojibake in the log), so the wizard shows its own
  localized status lines instead; a non-zero exit is verified by re-running
  the check because winget exits non-zero for "already installed".

Source: `https://crates.io/crates/tauri-bundler` 2.9.4,
`src/bundle/windows/nsis/installer.nsi`.

## Bundled AISC CLI bundle (aisc-bundle)

The installer ships the full AISC CLI bundle (`aisc-bundle\`) next to the
sidecar exe so CLI root discovery works on an installed Workbench without a
repository checkout (`resources.py` frozen-bundle branch). The bundle is
**not** committed: CI stages it via `python packaging/artifact.py stage --root . --output workbench/src-tauri/nsis/bundle` before `tauri build` (fails fast on verification), and `tauri.conf.json` maps it into `$INSTDIR` with `bundle.resources` (`nsis/bundle/aisc-bundle` -> `aisc-bundle`, recursive directory copy rendered as one `File /a "/oname=..."` per file by the NSIS template). Locally, `tauri build` requires the staging step to have run first — same friction class as the externalBin sidecar.

## Languages

`bundle.windows.nsis.languages: ["English", "SimpChinese"]` + `displayLanguageSelector:
true` in `tauri.conf.json`: the rendered installer shows the MUI language picker
(remembered in `HKCU\Software\cn.aisc.workbench\...\Installer Language`, so it
appears only on the first install; silent `/S` skips it). The MUI page strings
come from tauri-bundler's embedded language files; the custom S4.1.b strings are
`LangString DEP_*` definitions in `installer.nsi` right after the
`{{#each language_files}}` include block. The file must stay **UTF-8 without
BOM** - tauri-bundler writes the rendered script with a UTF-8 BOM and compiles
with `-INPUTCHARSET UTF8`, which is what makes the CJK strings render correctly
on any locale. `$(DEP_*)` references in code earlier in the file are fine
(makensis resolves LangStrings at the end of the compile pass, same as the
template's own `$(older)`/`$(alreadyInstalled)` references).

## Maintenance

When upgrading tauri-bundler (via `@tauri-apps/cli`), diff this file against
the new default template and re-apply the S4.1.b additions:

1. `Var Deps*` declarations in the header var block.
2. The dependency page + functions between `MUI_PAGE_STARTMENU` and
   `MUI_PAGE_INSTFILES`.
3. `Section Dependencies` between `Section EarlyChecks` and `Section WebView2`.
4. The `LangString DEP_*` block after the `{{#each language_files}}` include
   (keep it in sync with the strings used by 2. and 3.; `${LANG_SIMPCHINESE}`
   requires `SimpChinese` to stay in the `languages` config array).
5. The dependency checks (`CheckDocker`, `CheckPythonCore`,
   `CheckPython`). `check-deps-test.nsi` in this directory holds these
   functions verbatim: after changing them, compile and run the test
   installer to verify detection against the local machine -
   `makensis check-deps-test.nsi && %TEMP%\aisc-check-test.exe /S` then read
   `%TEMP%\aisc-check-result.txt` (expect `docker_installed=1` /
   `python_installed=1` when the tools are present). The test installer is
   not part of the tauri build.

Keep all other `{{handlebars}}` placeholders intact - they are required by the
renderer. Do not delete or renumber the page comments; the template depends on
the MUI page order.
