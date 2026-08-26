Unicode true
ManifestDPIAware true
; Add in `dpiAwareness` `PerMonitorV2` to manifest for Windows 10 1607+ (note this should not affect lower versions since they should be able to ignore this and pick up `dpiAware` `true` set by `ManifestDPIAware true`)
; Currently undocumented on NSIS's website but is in the Docs folder of source tree, see
; https://github.com/kichik/nsis/blob/5fc0b87b819a9eec006df4967d08e522ddd651c9/Docs/src/attributes.but#L286-L300
; https://github.com/tauri-apps/tauri/pull/10106
ManifestDPIAwareness PerMonitorV2

!if "{{compression}}" == "none"
  SetCompress off
!else
  ; Set the compression algorithm. We default to LZMA.
  SetCompressor /SOLID "{{compression}}"
!endif

; Keep above !include to stay ahead of any plugin command
; see https://github.com/tauri-apps/tauri/pull/15422#discussion_r3289239624
{{#if signed_plugins_path}}
!addplugindir "{{signed_plugins_path}}"
{{/if}}

!include MUI2.nsh
!include FileFunc.nsh
!include x64.nsh
!include WordFunc.nsh
!include "utils.nsh"
!include "FileAssociation.nsh"
!include "Win\COM.nsh"
!include "Win\Propkey.nsh"
!include "StrFunc.nsh"
${StrCase}
${StrLoc}

{{#if installer_hooks}}
!include "{{installer_hooks}}"
{{/if}}

!define WEBVIEW2APPGUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

!define MANUFACTURER "{{manufacturer}}"
!define PRODUCTNAME "{{product_name}}"
!define VERSION "{{version}}"
!define VERSIONWITHBUILD "{{version_with_build}}"
!define HOMEPAGE "{{homepage}}"
!define INSTALLMODE "{{install_mode}}"
!define LICENSE "{{license}}"
!define INSTALLERICON "{{installer_icon}}"
!define SIDEBARIMAGE "{{sidebar_image}}"
!define HEADERIMAGE "{{header_image}}"
!define UNINSTALLERICON "{{uninstaller_icon}}"
!define UNINSTALLERHEADERIMAGE "{{uninstaller_header_image}}"
!define MAINBINARYNAME "{{main_binary_name}}"
!define MAINBINARYSRCPATH "{{main_binary_path}}"
!define BUNDLEID "{{bundle_id}}"
!define COPYRIGHT "{{copyright}}"
!define OUTFILE "{{out_file}}"
!define ARCH "{{arch}}"
!define ADDITIONALPLUGINSPATH "{{additional_plugins_path}}"
!define ALLOWDOWNGRADES "{{allow_downgrades}}"
!define DISPLAYLANGUAGESELECTOR "{{display_language_selector}}"
!define INSTALLWEBVIEW2MODE "{{install_webview2_mode}}"
!define WEBVIEW2INSTALLERARGS "{{webview2_installer_args}}"
!define WEBVIEW2BOOTSTRAPPERPATH "{{webview2_bootstrapper_path}}"
!define WEBVIEW2INSTALLERPATH "{{webview2_installer_path}}"
!define MINIMUMWEBVIEW2VERSION "{{minimum_webview2_version}}"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCTNAME}"
!define MANUKEY "Software\${MANUFACTURER}"
!define MANUPRODUCTKEY "${MANUKEY}\${PRODUCTNAME}"
!define UNINSTALLERSIGNCOMMAND "{{uninstaller_sign_cmd}}"
!define ESTIMATEDSIZE "{{estimated_size}}"
!define STARTMENUFOLDER "{{start_menu_folder}}"

Var PassiveMode
Var UpdateMode
Var NoShortcutMode
Var WixMode
Var OldMainBinaryName

; Docker Desktop host integration (see Section Docker + RunFinishApp):
; install-time detection state + the winget exit code (saved before any
; CheckDocker call clobbers $0).
Var DepsDockerInstalled
Var DepsDockerExe
Var DepsWingetInstalled
Var DockerWingetExit

Name "${PRODUCTNAME}"
BrandingText "${COPYRIGHT}"
OutFile "${OUTFILE}"

; We don't actually use this value as default install path,
; it's just for nsis to append the product name folder in the directory selector
; https://nsis.sourceforge.io/Reference/InstallDir
!define PLACEHOLDER_INSTALL_DIR "placeholder\${PRODUCTNAME}"
InstallDir "${PLACEHOLDER_INSTALL_DIR}"

VIProductVersion "${VERSIONWITHBUILD}"
VIAddVersionKey "ProductName" "${PRODUCTNAME}"
VIAddVersionKey "FileDescription" "${PRODUCTNAME}"
VIAddVersionKey "LegalCopyright" "${COPYRIGHT}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"

# additional plugins
!addplugindir "${ADDITIONALPLUGINSPATH}"

; Uninstaller signing command
!if "${UNINSTALLERSIGNCOMMAND}" != ""
  !uninstfinalize '${UNINSTALLERSIGNCOMMAND}'
!endif

; Handle install mode, `perUser`, `perMachine` or `both`
!if "${INSTALLMODE}" == "perMachine"
  RequestExecutionLevel admin
!endif

!if "${INSTALLMODE}" == "currentUser"
  RequestExecutionLevel user
!endif

!if "${INSTALLMODE}" == "both"
  !define MULTIUSER_MUI
  !define MULTIUSER_INSTALLMODE_INSTDIR "${PRODUCTNAME}"
  !define MULTIUSER_INSTALLMODE_COMMANDLINE
  !if "${ARCH}" == "x64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !else if "${ARCH}" == "arm64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !endif
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_KEY "${UNINSTKEY}"
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_VALUENAME "CurrentUser"
  !define MULTIUSER_INSTALLMODEPAGE_SHOWUSERNAME
  !define MULTIUSER_INSTALLMODE_FUNCTION RestorePreviousInstallLocation
  !define MULTIUSER_EXECUTIONLEVEL Highest
  !include MultiUser.nsh
!endif

; Installer icon
!if "${INSTALLERICON}" != ""
  !define MUI_ICON "${INSTALLERICON}"
!endif

; Installer sidebar image
!if "${SIDEBARIMAGE}" != ""
  !define MUI_WELCOMEFINISHPAGE_BITMAP "${SIDEBARIMAGE}"
!endif

; Enable header images for installer and uninstaller pages when either image is configured.
!if "${HEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE
!else if "${UNINSTALLERHEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE
!endif

; Installer header image
!if "${HEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE_BITMAP "${HEADERIMAGE}"
!endif

; Uninstaller header image
!if "${UNINSTALLERHEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE_UNBITMAP "${UNINSTALLERHEADERIMAGE}"
!endif

; Uninstaller icon
!if "${UNINSTALLERICON}" != ""
  !define MUI_UNICON "${UNINSTALLERICON}"
!endif

; Define registry key to store installer language
!define MUI_LANGDLL_REGISTRY_ROOT "HKCU"
!define MUI_LANGDLL_REGISTRY_KEY "${MANUPRODUCTKEY}"
!define MUI_LANGDLL_REGISTRY_VALUENAME "Installer Language"

; Installer pages, must be ordered as they appear
; 1. Welcome Page
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_WELCOME

; 2. License Page (if defined)
!if "${LICENSE}" != ""
  !define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
  !insertmacro MUI_PAGE_LICENSE "${LICENSE}"
!endif

; 3. Install mode (if it is set to `both`)
!if "${INSTALLMODE}" == "both"
  !define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
  !insertmacro MULTIUSER_PAGE_INSTALLMODE
!endif

; 4. Custom page to ask user if he wants to reinstall/uninstall
;    only if a previous installation was detected
Var ReinstallPageCheck
Page custom PageReinstall PageLeaveReinstall
Function PageReinstall
  ; Uninstall previous WiX installation if exists.
  ;
  ; A WiX installer stores the installation info in registry
  ; using a UUID and so we have to loop through all keys under
  ; `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall`
  ; and check if `DisplayName` and `Publisher` keys match ${PRODUCTNAME} and ${MANUFACTURER}
  ;
  ; This has a potential issue that there maybe another installation that matches
  ; our ${PRODUCTNAME} and ${MANUFACTURER} but wasn't installed by our WiX installer,
  ; however, this should be fine since the user will have to confirm the uninstallation
  ; and they can chose to abort it if doesn't make sense.
  StrCpy $0 0
  wix_loop:
    EnumRegKey $1 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" $0
    StrCmp $1 "" wix_loop_done ; Exit loop if there is no more keys to loop on
    IntOp $0 $0 + 1
    ReadRegStr $R0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "DisplayName"
    ReadRegStr $R1 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "Publisher"
    StrCmp "$R0$R1" "${PRODUCTNAME}${MANUFACTURER}" 0 wix_loop
    ReadRegStr $R0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1" "UninstallString"
    ${StrCase} $R1 $R0 "L"
    ${StrLoc} $R0 $R1 "msiexec" ">"
    StrCmp $R0 0 0 wix_loop_done
    StrCpy $WixMode 1
    StrCpy $R6 "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$1"
    Goto compare_version
  wix_loop_done:

  ; Check if there is an existing installation, if not, abort the reinstall page
  ReadRegStr $R0 SHCTX "${UNINSTKEY}" ""
  ReadRegStr $R1 SHCTX "${UNINSTKEY}" "UninstallString"
  ${IfThen} "$R0$R1" == "" ${|} Abort ${|}

  ; Compare this installar version with the existing installation
  ; and modify the messages presented to the user accordingly
  compare_version:
  StrCpy $R4 "$(older)"
  ${If} $WixMode = 1
    ReadRegStr $R0 HKLM "$R6" "DisplayVersion"
  ${Else}
    ReadRegStr $R0 SHCTX "${UNINSTKEY}" "DisplayVersion"
  ${EndIf}
  ${IfThen} $R0 == "" ${|} StrCpy $R4 "$(unknown)" ${|}

  nsis_tauri_utils::SemverCompare "${VERSION}" $R0
  Pop $R0
  ; Reinstalling the same version
  ${If} $R0 = 0
    StrCpy $R1 "$(alreadyInstalledLong)"
    StrCpy $R2 "$(addOrReinstall)"
    StrCpy $R3 "$(uninstallApp)"
    !insertmacro MUI_HEADER_TEXT "$(alreadyInstalled)" "$(chooseMaintenanceOption)"
  ; Upgrading
  ${ElseIf} $R0 = 1
    StrCpy $R1 "$(olderOrUnknownVersionInstalled)"
    StrCpy $R2 "$(uninstallBeforeInstalling)"
    StrCpy $R3 "$(dontUninstall)"
    !insertmacro MUI_HEADER_TEXT "$(alreadyInstalled)" "$(choowHowToInstall)"
  ; Downgrading
  ${ElseIf} $R0 = -1
    StrCpy $R1 "$(newerVersionInstalled)"
    StrCpy $R2 "$(uninstallBeforeInstalling)"
    !if "${ALLOWDOWNGRADES}" == "true"
      StrCpy $R3 "$(dontUninstall)"
    !else
      StrCpy $R3 "$(dontUninstallDowngrade)"
    !endif
    !insertmacro MUI_HEADER_TEXT "$(alreadyInstalled)" "$(choowHowToInstall)"
  ${Else}
    Abort
  ${EndIf}

  ; Skip showing the page if passive
  ;
  ; Note that we don't call this earlier at the begining
  ; of this function because we need to populate some variables
  ; related to current installed version if detected and whether
  ; we are downgrading or not.
  ${If} $PassiveMode = 1
    Call PageLeaveReinstall
  ${Else}
    nsDialogs::Create 1018
    Pop $R4
    ${IfThen} $(^RTL) = 1 ${|} nsDialogs::SetRTL $(^RTL) ${|}

    ${NSD_CreateLabel} 0 0 100% 24u $R1
    Pop $R1

    ${NSD_CreateRadioButton} 30u 50u -30u 8u $R2
    Pop $R2
    ${NSD_OnClick} $R2 PageReinstallUpdateSelection

    ${NSD_CreateRadioButton} 30u 70u -30u 8u $R3
    Pop $R3
    ; Disable this radio button if downgrading and downgrades are disabled
    !if "${ALLOWDOWNGRADES}" == "false"
      ${IfThen} $R0 = -1 ${|} EnableWindow $R3 0 ${|}
    !endif
    ${NSD_OnClick} $R3 PageReinstallUpdateSelection

    ; Check the first radio button if this the first time
    ; we enter this page or if the second button wasn't
    ; selected the last time we were on this page
    ${If} $ReinstallPageCheck <> 2
      SendMessage $R2 ${BM_SETCHECK} ${BST_CHECKED} 0
    ${Else}
      SendMessage $R3 ${BM_SETCHECK} ${BST_CHECKED} 0
    ${EndIf}

    ${NSD_SetFocus} $R2
    nsDialogs::Show
  ${EndIf}
FunctionEnd
Function PageReinstallUpdateSelection
  ${NSD_GetState} $R2 $R1
  ${If} $R1 == ${BST_CHECKED}
    StrCpy $ReinstallPageCheck 1
  ${Else}
    StrCpy $ReinstallPageCheck 2
  ${EndIf}
FunctionEnd
Function PageLeaveReinstall
  ${NSD_GetState} $R2 $R1

  ; If migrating from Wix, always uninstall
  ${If} $WixMode = 1
    Goto reinst_uninstall
  ${EndIf}

  ; In update mode, always proceeds without uninstalling
  ${If} $UpdateMode = 1
    Goto reinst_done
  ${EndIf}

  ; $R0 holds whether same(0)/upgrading(1)/downgrading(-1) version
  ; $R1 holds the radio buttons state:
  ;   1 => first choice was selected
  ;   0 => second choice was selected
  ${If} $R0 = 0 ; Same version, proceed
    ${If} $R1 = 1              ; User chose to add/reinstall
      Goto reinst_done
    ${Else}                    ; User chose to uninstall
      Goto reinst_uninstall
    ${EndIf}
  ${ElseIf} $R0 = 1 ; Upgrading
    ${If} $R1 = 1              ; User chose to uninstall
      Goto reinst_uninstall
    ${Else}
      Goto reinst_done         ; User chose NOT to uninstall
    ${EndIf}
  ${ElseIf} $R0 = -1 ; Downgrading
    ${If} $R1 = 1              ; User chose to uninstall
      Goto reinst_uninstall
    ${Else}
      Goto reinst_done         ; User chose NOT to uninstall
    ${EndIf}
  ${EndIf}

  reinst_uninstall:
    HideWindow
    ClearErrors

    ${If} $WixMode = 1
      ReadRegStr $R1 HKLM "$R6" "UninstallString"
      ExecWait '$R1' $0
    ${Else}
      ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
      ReadRegStr $R1 SHCTX "${UNINSTKEY}" "UninstallString"
      ${IfThen} $UpdateMode = 1 ${|} StrCpy $R1 "$R1 /UPDATE" ${|} ; append /UPDATE
      ${IfThen} $PassiveMode = 1 ${|} StrCpy $R1 "$R1 /P" ${|} ; append /P
      StrCpy $R1 "$R1 _?=$4" ; append uninstall directory
      ExecWait '$R1' $0
    ${EndIf}

    BringToFront

    ${IfThen} ${Errors} ${|} StrCpy $0 2 ${|} ; ExecWait failed, set fake exit code

    ${If} $0 <> 0
    ${OrIf} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
      ; User cancelled wix uninstaller? return to select un/reinstall page
      ${If} $WixMode = 1
      ${AndIf} $0 = 1602
        Abort
      ${EndIf}

      ; User cancelled NSIS uninstaller? return to select un/reinstall page
      ${If} $0 = 1
        Abort
      ${EndIf}

      ; Other erros? show generic error message and return to select un/reinstall page
      MessageBox MB_ICONEXCLAMATION "$(unableToUninstall)"
      Abort
    ${EndIf}
  reinst_done:
FunctionEnd

; 5. Choose install directory page
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_DIRECTORY

; 6. Start menu shortcut page
Var AppStartMenuFolder
!if "${STARTMENUFOLDER}" != ""
  !define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
  !define MUI_STARTMENUPAGE_DEFAULTFOLDER "${STARTMENUFOLDER}"
!else
  !define MUI_PAGE_CUSTOMFUNCTION_PRE Skip
!endif
!insertmacro MUI_PAGE_STARTMENU Application $AppStartMenuFolder

; 7. Installation page
!insertmacro MUI_PAGE_INSTFILES

; 8. Finish page
;
; Don't auto jump to finish page after installation page,
; because the installation page has useful info that can be used debug any issues with the installer.
!define MUI_FINISHPAGE_NOAUTOCLOSE
; Use show readme button in the finish page as a button create a desktop shortcut
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "$(createDesktop)"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION CreateOrUpdateDesktopShortcut
; Show run app after installation.
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "$(DEP_FINISH_RUN)"
!define MUI_FINISHPAGE_RUN_FUNCTION RunFinishApp
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_FINISH

Function RunFinishApp
  ; Host integration: ensure Docker Desktop is up before the first runtime
  ; start. Three cases: installed + running -> no-op; installed + stopped ->
  ; silently launch it; not installed -> inform and offer the download page
  ; (a missing Docker Desktop still lets the Workbench launch - its own
  ; preflight reports the real engine state).
  Call CheckDocker
  ${If} $DepsDockerInstalled = 1
    Call StartDockerDesktop
  ${Else}
    MessageBox MB_ICONINFORMATION|MB_YESNO "$(DOCKER_MISSING_LAUNCH)" IDNO skip_docker
      ExecShell "open" "https://www.docker.com/products/docker-desktop/"
    skip_docker:
  ${EndIf}
  nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
FunctionEnd

Function CheckDocker
  ; Docker Desktop installs machine-wide to "Program Files\Docker\Docker"
  ; (MSI) or per-user to %LOCALAPPDATA% (winget). Detect by executable
  ; presence and remember the path so StartDockerDesktop can use it.
  StrCpy $DepsDockerExe ""
  ${If} ${FileExists} "$PROGRAMFILES64\Docker\Docker\Docker Desktop.exe"
    StrCpy $DepsDockerExe "$PROGRAMFILES64\Docker\Docker\Docker Desktop.exe"
    StrCpy $DepsDockerInstalled 1
    Return
  ${EndIf}
  ${If} ${FileExists} "$LOCALAPPDATA\Docker\Docker Desktop\Docker Desktop.exe"
    StrCpy $DepsDockerExe "$LOCALAPPDATA\Docker\Docker Desktop\Docker Desktop.exe"
    StrCpy $DepsDockerInstalled 1
    Return
  ${EndIf}
  ; Non-standard install location: read the uninstaller registry entry
  ; (64-bit view first - Docker Desktop is a 64-bit app - then per-user HKCU).
  SetRegView 64
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Docker Desktop" "InstallLocation"
  ${If} $0 == ""
    ReadRegStr $0 HKCU "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Docker Desktop" "InstallLocation"
  ${EndIf}
  SetRegView 32
  ${If} $0 == ""
    ReadRegStr $0 HKLM "SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Docker Desktop" "InstallLocation"
  ${EndIf}
  ${If} $0 != ""
  ${AndIf} ${FileExists} "$0\Docker Desktop.exe"
    StrCpy $DepsDockerExe "$0\Docker Desktop.exe"
    StrCpy $DepsDockerInstalled 1
    Return
  ${EndIf}
  StrCpy $DepsDockerInstalled 0
FunctionEnd

Function CheckWinget
  ; winget (App Installer) is installed if the WindowsApps alias exists on PATH
  ClearErrors
  nsExec::ExecToStack '"where" winget'
  Pop $0 ; exit code (0 = found)
  ${If} $0 = 0
    StrCpy $DepsWingetInstalled 1
  ${Else}
    StrCpy $DepsWingetInstalled 0
  ${EndIf}
FunctionEnd

Function StartDockerDesktop
  ; Silently start Docker Desktop when it is installed but not running.
  ; nsis_tauri_utils FindProcess* returns 0 when the process exists; check the
  ; per-user session first (matches INSTALLMODE=currentUser), then broaden to
  ; a machine-wide check in case Docker runs elevated.
  nsis_tauri_utils::FindProcessCurrentUser "Docker Desktop.exe"
  Pop $0
  ${If} $0 <> 0
    nsis_tauri_utils::FindProcess "Docker Desktop.exe"
    Pop $0
    ${If} $0 <> 0
      ${If} $DepsDockerExe != ""
        ExecShell "open" "$DepsDockerExe"
      ${EndIf}
    ${EndIf}
  ${EndIf}
FunctionEnd

; Uninstaller Pages
; 1. Confirm uninstall page
Var DeleteAppDataCheckbox
Var DeleteAppDataCheckboxState
; KI-4 (2026-08-18): optional Docker companion cleanup checkbox + engine state
Var DeleteDockerCheckbox
Var DeleteDockerCheckboxState
Var DockerExe
Var DockerCleanupSkipped
; docker-resource-lifecycle C1: installer-side lifecycle plumbing.
Var KeepDockerMode          ; /KEEPDOCKER skips Docker cleanup even if checked
Var AiscCliExe              ; bundled sidecar (found by pattern, never hardcoded)
Var ToolchainCheckbox       ; third uninstall option: persistent toolchains
Var ToolchainCheckboxState
Var OldImageId              ; captured pre-overwrite; rebuild handoff
Var RebuildPending          ; upgrade rebuild failed/unavailable -> note
Var HadPreviousInstall      ; manual reinstall-over counts as an upgrade too
!define /ifndef WS_EX_LAYOUTRTL         0x00400000
!define MUI_PAGE_CUSTOMFUNCTION_SHOW un.ConfirmShow
Function un.ConfirmShow ; Add add a `Delete app data` check box
  ; $1 inner dialog HWND
  ; $2 window DPI
  ; $3 style
  ; $4 x
  ; $5 y
  ; $6 width
  ; $7 height
  FindWindow $1 "#32770" "" $HWNDPARENT ; Find inner dialog
  System::Call "user32::GetDpiForWindow(p r1) i .r2"
  ${If} $(^RTL) = 1
    StrCpy $3 "${__NSD_CheckBox_EXSTYLE} | ${WS_EX_LAYOUTRTL}"
    IntOp $4 50 * $2
  ${Else}
    StrCpy $3 "${__NSD_CheckBox_EXSTYLE}"
    IntOp $4 0 * $2
  ${EndIf}
  IntOp $5 100 * $2
  IntOp $6 400 * $2
  IntOp $7 25 * $2
  IntOp $4 $4 / 96
  IntOp $5 $5 / 96
  IntOp $6 $6 / 96
  IntOp $7 $7 / 96
  System::Call 'user32::CreateWindowEx(i r3, w "${__NSD_CheckBox_CLASS}", w "$(deleteAppData)", i ${__NSD_CheckBox_STYLE}, i r4, i r5, i r6, i r7, p r1, i0, i0, i0) i .s'
  Pop $DeleteAppDataCheckbox
  ; KI-4: capture the dialog font into $8 — the stock code reused $1 for it,
  ; which CLOBBERS the inner-dialog HWND the second checkbox still needs as
  ; its parent (CreateWindowEx with a font-handle parent fails silently, so
  ; the Docker checkbox never appeared in the 2026-08-18 manual test).
  SendMessage $HWNDPARENT ${WM_GETFONT} 0 0 $8
  SendMessage $DeleteAppDataCheckbox ${WM_SETFONT} $8 1
  ; KI-4: second checkbox — Docker containers + image (default unchecked).
  ; Same dialog ($1 is STILL the inner dialog HWND), one row below.
  IntOp $5 125 * $2
  IntOp $5 $5 / 96
  System::Call 'user32::CreateWindowEx(i r3, w "${__NSD_CheckBox_CLASS}", w "$(DOCKER_CLEANUP_CHECKBOX)", i ${__NSD_CheckBox_STYLE}, i r4, i r5, i r6, i r7, p r1, i0, i0, i0) i .s'
  Pop $DeleteDockerCheckbox
  SendMessage $DeleteDockerCheckbox ${WM_SETFONT} $8 1
  ; docker-resource C1: third checkbox — persistent project toolchains
  ; (02 §3.1: independent of the container/image cleanup AND of app data;
  ; default unchecked).
  IntOp $5 150 * $2
  IntOp $5 $5 / 96
  System::Call 'user32::CreateWindowEx(i r3, w "${__NSD_CheckBox_CLASS}", w "$(TOOLCHAIN_CLEANUP_CHECKBOX)", i ${__NSD_CheckBox_STYLE}, i r4, i r5, i r6, i r7, p r1, i0, i0, i0) i .s'
  Pop $ToolchainCheckbox
  SendMessage $ToolchainCheckbox ${WM_SETFONT} $8 1
  ; docker-resource C1: README uninstall contract — Docker resources are
  ; cleaned BY DEFAULT (opt-out: uncheck or /KEEPDOCKER); toolchain and
  ; app-data remain opt-in. 2026-08-26 R3 smoke finding: with no BM_SETCHECK
  ; every checkbox shipped unchecked, contradicting the documented default.
  ${NSD_Check} $DeleteDockerCheckbox
FunctionEnd
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE un.ConfirmLeave
Function un.ConfirmLeave
  SendMessage $DeleteAppDataCheckbox ${BM_GETCHECK} 0 0 $DeleteAppDataCheckboxState
  SendMessage $DeleteDockerCheckbox ${BM_GETCHECK} 0 0 $DeleteDockerCheckboxState
  SendMessage $ToolchainCheckbox ${BM_GETCHECK} 0 0 $ToolchainCheckboxState
FunctionEnd
!define MUI_PAGE_CUSTOMFUNCTION_PRE un.SkipIfPassive
!insertmacro MUI_UNPAGE_CONFIRM

; 2. Uninstalling Page
!insertmacro MUI_UNPAGE_INSTFILES

;Languages
{{#each languages}}
!insertmacro MUI_LANGUAGE "{{this}}"
{{/each}}
!insertmacro MUI_RESERVEFILE_LANGDLL
{{#each language_files}}
  !include "{{this}}"
{{/each}}

LangString DEP_FINISH_RUN ${LANG_ENGLISH} "Start AISC Workbench"
LangString DEP_FINISH_RUN ${LANG_SIMPCHINESE} "启动 AISC Workbench"
LangString DOCKER_PRESENT ${LANG_ENGLISH} "Docker Desktop detected."
LangString DOCKER_PRESENT ${LANG_SIMPCHINESE} "已检测到 Docker Desktop。"
LangString DOCKER_MISSING_DEFERRED ${LANG_ENGLISH} "Docker Desktop not found - it will be offered for installation in the Workbench first-run wizard."
LangString DOCKER_MISSING_DEFERRED ${LANG_SIMPCHINESE} "未检测到 Docker Desktop——将在 Workbench 首次引导中提示安装。"
LangString DOCKER_MISSING_LAUNCH ${LANG_ENGLISH} "AISC Workbench needs Docker Desktop, which was not found on this PC. Open the Docker Desktop download page? (You can also install it later from the Start menu or Microsoft Store.)"
LangString DOCKER_MISSING_LAUNCH ${LANG_SIMPCHINESE} "AISC Workbench 需要 Docker Desktop，但未在本机找到。是否打开 Docker Desktop 下载页？（也可以稍后从开始菜单或 Microsoft Store 安装。）"
; KI-4 (2026-08-18): uninstall-time Docker companion cleanup. NOTE: literal
; double braces are FORBIDDEN in this file (it is a handlebars template), so
; docker CLI calls never use --format.
LangString DOCKER_CLEANUP_CHECKBOX ${LANG_ENGLISH} "Also delete AISC Docker containers and image (about 2 GB+, needs Docker running)"
LangString DOCKER_CLEANUP_CHECKBOX ${LANG_SIMPCHINESE} "同时删除 AISC 的 Docker 容器与镜像（约 2GB+，需 Docker 正在运行）"
LangString TOOLCHAIN_CLEANUP_CHECKBOX ${LANG_ENGLISH} "Also delete persistent project toolchains (user-level npm/pip/cargo tools installed by agents)"
LangString TOOLCHAIN_CLEANUP_CHECKBOX ${LANG_SIMPCHINESE} "同时删除各工作区的持久工具链（Agent 安装的 npm/pip/cargo 用户级工具）"
LangString DOCKER_CLEAN_START ${LANG_ENGLISH} "Cleaning AISC Docker resources..."
LangString DOCKER_CLEAN_START ${LANG_SIMPCHINESE} "正在清理 AISC 的 Docker 资源…"
LangString DOCKER_CLEAN_UNREACHABLE ${LANG_ENGLISH} "Docker engine not reachable"
LangString DOCKER_CLEAN_UNREACHABLE ${LANG_SIMPCHINESE} "Docker 引擎不可达"
LangString DOCKER_CLEAN_DONE ${LANG_ENGLISH} "AISC Docker resources cleaned."
LangString DOCKER_CLEAN_DONE ${LANG_SIMPCHINESE} "AISC Docker 资源已清理。"
LangString DOCKER_CLEANUP_SKIPPED ${LANG_ENGLISH} "Docker was not reachable, so the AISC containers and image were kept. To clean them up later: reinstall AISC and uninstall with the cleanup box checked, or run 'docker ps -a --filter label=io.aisc.managed=true' and 'docker rm -f <id>' for each container, then 'docker rmi -f super-claude:latest'."
LangString DOCKER_CLEANUP_SKIPPED ${LANG_SIMPCHINESE} "Docker 引擎不可达，AISC 容器与镜像已保留。稍后清理：重新安装 AISC 并勾选清理后卸载，或执行 docker ps -a --filter label=io.aisc.managed=true 查看容器，逐个执行 docker rm -f <容器ID>，再执行 docker rmi -f super-claude:latest。"
LangString UPGRADE_CLEAN_START ${LANG_ENGLISH} "Stopping AISC containers before update..."
LangString UPGRADE_CLEAN_START ${LANG_SIMPCHINESE} "更新前停止 AISC 容器…"
LangString UPGRADE_REBUILD_START ${LANG_ENGLISH} "Rebuilding the workstation image without cache (this can take several minutes)..."
LangString UPGRADE_REBUILD_START ${LANG_SIMPCHINESE} "正在无缓存重建工作站镜像（可能需要几分钟）…"
LangString REBUILD_PENDING ${LANG_ENGLISH} "The workstation image was not rebuilt (Docker unavailable or build failed). The Workbench will offer to build it on next start, or run the installer's bundled CLI: aisc maintenance docker-rebuild --root <install-dir>\aisc-bundle --tag super-claude:latest"
LangString REBUILD_PENDING ${LANG_SIMPCHINESE} "工作站镜像未重建（Docker 不可用或构建失败）。Workbench 下次启动时会提示构建，或手动执行安装目录内 CLI：aisc maintenance docker-rebuild --root <安装目录>\aisc-bundle --tag super-claude:latest"

Function .onInit
  ${GetOptions} $CMDLINE "/P" $PassiveMode
  ${IfNot} ${Errors}
    StrCpy $PassiveMode 1
  ${EndIf}

  ${GetOptions} $CMDLINE "/NS" $NoShortcutMode
  ${IfNot} ${Errors}
    StrCpy $NoShortcutMode 1
  ${EndIf}

  ${GetOptions} $CMDLINE "/UPDATE" $UpdateMode
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
  ${EndIf}

  !if "${DISPLAYLANGUAGESELECTOR}" == "true"
    !insertmacro MUI_LANGDLL_DISPLAY
  !endif

  !insertmacro SetContext

  ${If} $INSTDIR == "${PLACEHOLDER_INSTALL_DIR}"
    ; Set default install location
    !if "${INSTALLMODE}" == "perMachine"
      ${If} ${RunningX64}
        !if "${ARCH}" == "x64"
          StrCpy $INSTDIR "$PROGRAMFILES64\${PRODUCTNAME}"
        !else if "${ARCH}" == "arm64"
          StrCpy $INSTDIR "$PROGRAMFILES64\${PRODUCTNAME}"
        !else
          StrCpy $INSTDIR "$PROGRAMFILES\${PRODUCTNAME}"
        !endif
      ${Else}
        StrCpy $INSTDIR "$PROGRAMFILES\${PRODUCTNAME}"
      ${EndIf}
    !else if "${INSTALLMODE}" == "currentUser"
      StrCpy $INSTDIR "$LOCALAPPDATA\${PRODUCTNAME}"
    !endif

    Call RestorePreviousInstallLocation
  ${EndIf}


  !if "${INSTALLMODE}" == "both"
    !insertmacro MULTIUSER_INIT
  !endif
FunctionEnd


Section EarlyChecks
  ; Abort silent installer if downgrades is disabled
  !if "${ALLOWDOWNGRADES}" == "false"
  ${If} ${Silent}
    ; If downgrading
    ${If} $R0 = -1
      System::Call 'kernel32::AttachConsole(i -1)i.r0'
      ${If} $0 <> 0
        System::Call 'kernel32::GetStdHandle(i -11)i.r0'
        System::call 'kernel32::SetConsoleTextAttribute(i r0, i 0x0004)' ; set red color
        FileWrite $0 "$(silentDowngrades)"
      ${EndIf}
      Abort
    ${EndIf}
  ${EndIf}
  !endif

SectionEnd

Section WebView2
  ; Check if Webview2 is already installed and skip this section
  ${If} ${RunningX64}
    ReadRegStr $4 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${Else}
    ReadRegStr $4 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}
  ${If} $4 == ""
    ReadRegStr $4 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}

  ${If} $4 == ""
    ; Webview2 installation
    ;
    ; Skip if updating
    ${If} $UpdateMode <> 1
      !if "${INSTALLWEBVIEW2MODE}" == "downloadBootstrapper"
        Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        DetailPrint "$(webview2Downloading)"
        NSISdl::download "https://go.microsoft.com/fwlink/p/?LinkId=2124703" "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        Pop $0
        ${If} $0 == "success"
          DetailPrint "$(webview2DownloadSuccess)"
        ${Else}
          DetailPrint "$(webview2DownloadError)"
          Abort "$(webview2AbortError)"
        ${EndIf}
        StrCpy $6 "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        Goto install_webview2
      !endif

      !if "${INSTALLWEBVIEW2MODE}" == "embedBootstrapper"
        Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        File "/oname=$TEMP\MicrosoftEdgeWebview2Setup.exe" "${WEBVIEW2BOOTSTRAPPERPATH}"
        DetailPrint "$(installingWebview2)"
        StrCpy $6 "$TEMP\MicrosoftEdgeWebview2Setup.exe"
        Goto install_webview2
      !endif

      !if "${INSTALLWEBVIEW2MODE}" == "offlineInstaller"
        Delete "$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe"
        File "/oname=$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe" "${WEBVIEW2INSTALLERPATH}"
        DetailPrint "$(installingWebview2)"
        StrCpy $6 "$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe"
        Goto install_webview2
      !endif

      Goto webview2_done

      install_webview2:
        DetailPrint "$(installingWebview2)"
        ; $6 holds the path to the webview2 installer
        ExecWait "$6 ${WEBVIEW2INSTALLERARGS} /install" $1
        ${If} $1 = 0
          DetailPrint "$(webview2InstallSuccess)"
        ${Else}
          DetailPrint "$(webview2InstallError)"
          Abort "$(webview2AbortError)"
        ${EndIf}
      webview2_done:
    ${EndIf}
  ${Else}
    !if "${MINIMUMWEBVIEW2VERSION}" != ""
      ${VersionCompare} "${MINIMUMWEBVIEW2VERSION}" "$4" $R0
      ${If} $R0 = 1
        update_webview:
          DetailPrint "$(installingWebview2)"
          ${If} ${RunningX64}
            ReadRegStr $R1 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate" "path"
          ${Else}
            ReadRegStr $R1 HKLM "SOFTWARE\Microsoft\EdgeUpdate" "path"
          ${EndIf}
          ${If} $R1 == ""
            ReadRegStr $R1 HKCU "SOFTWARE\Microsoft\EdgeUpdate" "path"
          ${EndIf}
          ${If} $R1 != ""
            ; Chromium updater docs: https://source.chromium.org/chromium/chromium/src/+/main:docs/updater/user_manual.md
            ; Modified from "HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Microsoft EdgeWebView\ModifyPath"
            ExecWait `"$R1" /install appguid=${WEBVIEW2APPGUID}&needsadmin=true` $1
            ${If} $1 = 0
              DetailPrint "$(webview2InstallSuccess)"
            ${Else}
              MessageBox MB_ICONEXCLAMATION|MB_ABORTRETRYIGNORE "$(webview2InstallError)" IDIGNORE ignore IDRETRY update_webview
              Quit
              ignore:
            ${EndIf}
          ${EndIf}
      ${EndIf}
    !endif
  ${EndIf}
SectionEnd

; --- G-18: user PATH management (05 §5.2) ---
; Only ever touches the single owned directory entry in HKCU\Environment\Path.
; Never overwrites the whole value, never removes entries it does not own,
; preserves the registry value type (REG_EXPAND_SZ), and broadcasts
; WM_SETTINGCHANGE("Environment") after every write so new terminals pick it up.
LangString PATH_CONFLICT ${LANG_ENGLISH} "PATH already contains another aisc executable ($PathHit). To keep the existing environment intact, AISC Workbench was not added to PATH. The Workbench keeps using its bundled CLI internally."
LangString PATH_CONFLICT ${LANG_SIMPCHINESE} "PATH 中已存在其他 aisc 可执行文件（$PathHit）。为避免破坏现有环境，未将 AISC Workbench 加入 PATH。Workbench 内部仍使用自带 CLI。"
; KI-5 (2026-08-19): same-origin takeover ask. The user decision: an older
; aisc of OUR product family (aisc.cli/v1 envelope + older semver) may be
; offered to be shadowed BY the Workbench install dir (prepended to the user
; PATH; the old entry and files are left untouched — reversible). Everything
; else keeps the never-shadow behavior (05 §5.2.5).
LangString PATH_TAKEOVER_ASK ${LANG_ENGLISH} "An older AISC CLI (v$PathVer) was found on PATH:$\r$\n$PathHit$\r$\n$\r$\nLet AISC Workbench take over PATH? Its bundled CLI will then answer the aisc command first; the old installation is left untouched."
LangString PATH_TAKEOVER_ASK ${LANG_SIMPCHINESE} "检测到旧版 AISC CLI（v$PathVer）：$\r$\n$PathHit$\r$\n$\r$\n是否让 AISC Workbench 接管 PATH？之后 aisc 命令将优先使用 Workbench 自带的新版 CLI，旧安装保持原样不动。"
LangString PATH_TAKEOVER_DONE ${LANG_ENGLISH} "AISC Workbench took over PATH (prepended; the old entry is untouched)."
LangString PATH_TAKEOVER_DONE ${LANG_SIMPCHINESE} "AISC Workbench 已接管 PATH（条目前置；旧条目未改动）。"
LangString PATH_TAKEOVER_SYSTEM ${LANG_ENGLISH} "An older AISC CLI is shadowing this install from the SYSTEM PATH:$\r$\n$PathHit$\r$\n$\r$\nA per-user install cannot override the system PATH. Remove or reorder that entry manually if you want the Workbench CLI to answer the aisc command. The Workbench itself keeps using its bundled CLI."
LangString PATH_TAKEOVER_SYSTEM ${LANG_SIMPCHINESE} "系统 PATH 中存在旧版 AISC CLI 遮挡本安装：$\r$\n$PathHit$\r$\n$\r$\n当前为按用户安装，无法覆盖系统 PATH。如需 aisc 命令使用 Workbench 自带 CLI，请手动删除或调整该系统条目。Workbench 内部不受影响。"

Var PathType
Var PathRaw
Var PathNorm
Var PathHit
Var PathVer
Var PathOk

; $0 in/out: normalize a directory entry - trim spaces, strip one matching
; quote pair, remove trailing backslashes, lowercase (Windows compare).
!macro G18_PATH_FUNCS UN
Function ${UN}PathNormalizeDir
  Push $1
  Push $2
  Push $3
  Push $4
  StrCpy $1 $0
  ${Do}
    StrCpy $2 $1 1
    ${If} $2 == " "
      StrCpy $1 $1 "" 1
    ${Else}
      ${Break}
    ${EndIf}
  ${Loop}
  ${Do}
    StrCpy $2 $1 1 -1
    ${If} $2 == " "
      StrCpy $1 $1 -1
    ${Else}
      ${Break}
    ${EndIf}
  ${Loop}
  StrCpy $2 $1 1
  ${If} $2 == `"`
    StrCpy $2 $1 1 -1
    ${If} $2 == `"`
      StrCpy $1 $1 -1 1
    ${EndIf}
  ${EndIf}
  ${Do}
    StrCpy $2 $1 1 -1
    ${If} $2 == "\"
      StrCpy $1 $1 -1
    ${Else}
      ${Break}
    ${EndIf}
  ${Loop}
  ; Lowercase (ASCII + locale). ${StrCase} from StrFunc cannot be invoked
  ; from inside a macro (STRFUNC_CALL limitation), so use CharLowerBuffW.
  StrCpy $2 $1
  StrCpy $1 ""
  ${Do}
    StrCpy $3 $2 1
    ${If} $3 == ""
      ${Break}
    ${EndIf}
    System::Call 'user32::CharLowerBuffW(w r3 .r3, i 1) i .r4'
    StrCpy $1 "$1$3"
    StrCpy $2 $2 "" 1
  ${Loop}
  StrCpy $0 $1
  Pop $4
  Pop $3
  Pop $2
  Pop $1
FunctionEnd

; Read HKCU\Environment\Path into $PathRaw and its value type into $PathType
; (2 = REG_EXPAND_SZ, else REG_SZ); missing value -> $PathRaw = "", type SZ.
; 2026-08-26 R4 smoke: registry HANDLE parameters must ride pointer-sized
; (p) System::Call slots. `i` truncates the 64-bit HKEY on x64 NSIS, the
; RegQueryValueExW call then always failed, and every caller rewrote the
; resulting empty string - wiping the user's entire PATH (as empty REG_SZ).
; $PathOk=1 only when the query succeeded; callers MUST NOT write on 0.
Function ${UN}PathRead
  Push $1
  Push $2
  Push $3
  Push $4
  Push $5
  StrCpy $PathType 1
  StrCpy $PathOk 0
  StrCpy $PathRaw ""
  System::Call 'advapi32::RegOpenKeyExW(p 0x80000001, w "Environment", i 0, i 0x20019, *p .r1) i .r2'
  ${If} $2 = 0
    System::Call 'advapi32::RegQueryValueExW(p r1, w "Path", i 0, *i .r3, p 0, p 0) i .r5'
    ${If} $5 = 0
      StrCpy $PathType $3
      StrCpy $PathOk 1
      ReadRegStr $PathRaw HKCU "Environment" "Path"
    ${EndIf}
    System::Call 'advapi32::RegCloseKey(p r1)'
  ${EndIf}
  ${If} $PathRaw == ""
    StrCpy $PathType 1
  ${EndIf}
  Pop $5
  Pop $4
  Pop $3
  Pop $2
  Pop $1
FunctionEnd

; Write $PathRaw back preserving $PathType, then broadcast WM_SETTINGCHANGE.
Function ${UN}PathWrite
  ${If} $PathType = 2
    WriteRegExpandStr HKCU "Environment" "Path" $PathRaw
  ${Else}
    WriteRegStr HKCU "Environment" "Path" $PathRaw
  ${EndIf}
  System::Call 'user32::SendMessageTimeout(i 0xFFFF, i 0x1A, i 0, w "Environment", i 0x2, i 5000, *i .r0)'
FunctionEnd

; Remove every PATH entry whose normalized form equals $1 (caller passes the
; normalized directory). Rewrites the value and broadcasts.
Function ${UN}RemovePathEntryExact
  Call ${UN}PathRead
  ; Never rewrite after a failed read: an empty $PathRaw here would WIPE
  ; the whole user PATH (2026-08-26 R4 smoke - see PathRead).
  ${If} $PathOk <> 1
    Return
  ${EndIf}
  StrCpy $2 $PathRaw
  StrCpy $3 ""
  ${Do}
    ${If} $2 == ""
      ${Break}
    ${EndIf}
    StrCpy $5 $2 1
    ${If} $5 == ";"
      StrCpy $2 $2 "" 1
      ${Continue}
    ${EndIf}
    StrCpy $6 ""
    ${Do}
      StrCpy $5 $2 1
      ${If} $5 == ";"
      ${OrIf} $5 == ""
        ${Break}
      ${EndIf}
      StrCpy $6 "$6$5"
      StrCpy $2 $2 "" 1
    ${Loop}
    StrCpy $0 $6
    Call ${UN}PathNormalizeDir
    ${If} $0 != $1
      ${If} $3 == ""
        StrCpy $3 $6
      ${Else}
        StrCpy $3 "$3;$6"
      ${EndIf}
    ${EndIf}
  ${Loop}
  StrCpy $PathRaw $3
  Call ${UN}PathWrite
FunctionEnd

; Install: ensure $INSTDIR is a PATH entry (05 §5.2 algorithm).
Function ${UN}AddInstDirToPath
  ; Install dir moved? Remove the old owned entry first (exact match only).
  ReadRegDWORD $0 HKCU "${MANUPRODUCTKEY}" "PathEntryOwned"
  ${If} $0 = 1
    ReadRegStr $1 HKCU "${MANUPRODUCTKEY}" "PathEntry"
    ${If} $1 != ""
      StrCpy $0 $1
      Call ${UN}PathNormalizeDir
      StrCpy $1 $0
      StrCpy $0 $INSTDIR
      Call ${UN}PathNormalizeDir
      ${If} $1 != $0
        Call ${UN}RemovePathEntryExact
      ${EndIf}
    ${EndIf}
  ${EndIf}

  Call ${UN}PathRead
  ; Failed read: leave the PATH strictly untouched (see PathRead) - writing
  ; would replace the whole value with just $INSTDIR.
  ${If} $PathOk <> 1
    DetailPrint "PATH read failed; $INSTDIR not added (value left untouched)"
    Return
  ${EndIf}
  StrCpy $0 $INSTDIR
  Call ${UN}PathNormalizeDir
  StrCpy $PathNorm $0
  StrCpy $6 0                ; $INSTDIR already present?
  StrCpy $PathHit ""
  StrCpy $1 $PathRaw
  ${Do}
    ${If} $1 == ""
      ${Break}
    ${EndIf}
    StrCpy $5 $1 1
    ${If} $5 == ";"
      StrCpy $1 $1 "" 1
      ${Continue}
    ${EndIf}
    StrCpy $3 ""
    ${Do}
      StrCpy $5 $1 1
      ${If} $5 == ";"
      ${OrIf} $5 == ""
        ${Break}
      ${EndIf}
      StrCpy $3 "$3$5"
      StrCpy $1 $1 "" 1
    ${Loop}
    ${If} $3 != ""
      StrCpy $0 $3
      Call ${UN}PathNormalizeDir
      ${If} $0 == $PathNorm
        StrCpy $6 1
        ${Break}
      ${EndIf}
    ${EndIf}
  ${Loop}

  ${If} $6 = 1
    ; Already present: no duplicate append. Keep the marker (or leave a
    ; manually-added entry untouched - only owned entries are removed later).
    ReadRegDWORD $0 HKCU "${MANUPRODUCTKEY}" "PathEntryOwned"
    ${If} $0 = 1
      WriteRegStr HKCU "${MANUPRODUCTKEY}" "PathEntry" $INSTDIR
    ${EndIf}
    Return
  ${EndIf}

  ; KI-5 (2026-08-19): effective-resolution conflict probe. $INSTDIR is not on
  ; the user PATH — check whether ANY aisc.exe resolves first (system PATH,
  ; then user PATH, exactly how a fresh terminal resolves). Installer scope
  ; ONLY (un.AddInstDirToPath is never called; it merely has to compile), and
  ; deliberately RAW NSIS (StrCmp/IntCmp/relative jumps): LogicLib's generated
  ; labels do not survive this macro's !if stripping (unresolved
  ; _LogicLib_ElseLabel in the 2026-08-19 build).
!if "${UN}" == ""
  Call WhereAiscProbe
  StrCmp $PathHit "" ki5_append 0
  Call PathConflictOlderSameOrigin
  IntCmp $R0 1 ki5_maybe_ask 0 0
  Goto ki5_legacy
ki5_maybe_ask:
  Call UserPathContainsHitDir
  IntCmp $R0 1 ki5_user_ask ki5_system ki5_system
ki5_user_ask:
  ; Older same-origin CLI shadowing from the USER PATH: offer takeover.
  ; Takeover = PREPEND $INSTDIR (old entry and files untouched — reversible);
  ; a per-user prepend does win over later user entries.
  StrCmp $PassiveMode 1 ki5_ask_quiet
  IfSilent ki5_ask_quiet
  MessageBox MB_ICONQUESTION|MB_YESNO "$(PATH_TAKEOVER_ASK)" IDNO ki5_declined
  StrCmp $PathRaw "" 0 +3
  StrCpy $PathRaw $INSTDIR
  Goto +2
  StrCpy $PathRaw "$INSTDIR;$PathRaw"
  Call ${UN}PathWrite
  WriteRegDWORD HKCU "${MANUPRODUCTKEY}" "PathEntryOwned" 1
  WriteRegStr HKCU "${MANUPRODUCTKEY}" "PathEntry" $INSTDIR
  DetailPrint "$(PATH_TAKEOVER_DONE)"
  Return
ki5_ask_quiet:
  DetailPrint "PATH conflict: older same-origin aisc at $PathHit; not added (passive/silent)"
  Return
ki5_declined:
  DetailPrint "PATH takeover declined; $INSTDIR not added"
  Return
ki5_system:
  ; System-PATH shadow: a per-user prepend cannot override it.
  StrCmp $PassiveMode 1 ki5_system_quiet
  IfSilent ki5_system_quiet
  MessageBox MB_OK|MB_ICONINFORMATION "$(PATH_TAKEOVER_SYSTEM)"
  Return
ki5_system_quiet:
  DetailPrint "PATH conflict: older same-origin aisc at $PathHit (system PATH); not added"
  Return
ki5_legacy:
!endif
    ; Any other aisc shadows us: never overwrite, reorder or append (05 §5.2.5).
    ${If} $PathHit != ""
      ${If} $PassiveMode = 1
      ${OrIf} ${Silent}
        DetailPrint "PATH conflict: aisc already at $PathHit; $INSTDIR not added"
      ${Else}
        MessageBox MB_OK|MB_ICONINFORMATION "$(PATH_CONFLICT)"
      ${EndIf}
      Return
    ${EndIf}
ki5_append:

  ; Append once.
  ${If} $PathRaw == ""
    StrCpy $PathRaw $INSTDIR
  ${Else}
    StrCpy $PathRaw "$PathRaw;$INSTDIR"
  ${EndIf}
  Call ${UN}PathWrite
  WriteRegDWORD HKCU "${MANUPRODUCTKEY}" "PathEntryOwned" 1
  WriteRegStr HKCU "${MANUPRODUCTKEY}" "PathEntry" $INSTDIR
FunctionEnd

; Uninstall: remove the owned entry only when the marker path matches $INSTDIR
; (normalized); never touches other entries or other aisc installs.
Function ${UN}RemoveInstDirFromPath
  ReadRegDWORD $0 HKCU "${MANUPRODUCTKEY}" "PathEntryOwned"
  ${If} $0 <> 1
    Return
  ${EndIf}
  ReadRegStr $1 HKCU "${MANUPRODUCTKEY}" "PathEntry"
  ${If} $1 == ""
    Return
  ${EndIf}
  StrCpy $0 $1
  Call ${UN}PathNormalizeDir
  StrCpy $1 $0
  StrCpy $0 $INSTDIR
  Call ${UN}PathNormalizeDir
  ${If} $1 != $0
    Return
  ${EndIf}
  Call ${UN}RemovePathEntryExact
  DeleteRegValue HKCU "${MANUPRODUCTKEY}" "PathEntryOwned"
  DeleteRegValue HKCU "${MANUPRODUCTKEY}" "PathEntry"
FunctionEnd

!macroend

; installer-scope helpers (called from Section Install)
!insertmacro G18_PATH_FUNCS ""
; uninstaller-scope helpers (called from Section Uninstall; NSIS
; requires un. functions in the uninstall section)
!insertmacro G18_PATH_FUNCS "un."

; --- KI-5 (2026-08-19): same-origin takeover ask (user decision) ---
; Three installer-scope probes backing AddInstDirToPath's KI-5 branch.

; Effective-resolution conflict probe (pure registry scan, no subprocess):
; walks the SYSTEM PATH entries then the USER PATH entries — the exact order
; a fresh terminal resolves — and reports the first directory containing
; aisc.exe that is not $INSTDIR. `where` is deliberately NOT used: the
; installer's inherited process PATH (CI toolchains, setup-python Scripts
; dirs) is not what a user terminal ever sees. Sets $PathHit to that dir's
; aisc.exe ("" when we already resolve first or no aisc exists anywhere).
Function WhereAiscProbe
  StrCpy $PathHit ""
  ReadRegStr $6 HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path"
  ${If} $6 == ""
    StrCpy $6 $PathRaw
  ${Else}
    StrCpy $6 "$6;$PathRaw"
  ${EndIf}
  ${Do}
    ${If} $6 == ""
      ${Break}
    ${EndIf}
    StrCpy $3 ""
    ${Do}
      StrCpy $5 $6 1
      ${If} $5 == ";"
      ${OrIf} $5 == ""
        ${Break}
      ${EndIf}
      StrCpy $3 "$3$5"
      StrCpy $6 $6 "" 1
    ${Loop}
    StrCpy $5 $6 1
    ${IfThen} $5 == ";" ${|} StrCpy $6 $6 "" 1 ${|}
    ${If} $3 == ""
      ${Continue}
    ${EndIf}
    ; skip UNC/network dirs (same as the legacy probe); expand %VAR% forms
    StrCpy $4 $3 2
    ${If} $4 == "\\"
      ${Continue}
    ${EndIf}
    ExpandEnvStrings $4 $3
    ${IfNot} ${FileExists} "$4\aisc.exe"
      ${Continue}
    ${EndIf}
    StrCpy $0 $4
    Call PathNormalizeDir
    ${If} $0 == $PathNorm
      StrCpy $PathHit ""   ; our own dir resolves first — no conflict
    ${Else}
      StrCpy $PathHit "$4\aisc.exe"
    ${EndIf}
    ${Break}               ; the first hit decides the effective resolution
  ${Loop}
FunctionEnd

; Is $PathHit an OLDER release of our own CLI? Two probes: (1) the envelope —
; `version --format json` must exit 0, carry the aisc.cli/v1 marker and a
; parseable cli_version; (2) fallback for pre-envelope builds — `--version`
; prose like "aisc 2.1.4" / "aisc, version 2.1.4". Either way the version
; must rank strictly below this installer (SemverCompare). Sets $R0=1 when
; the takeover ask is warranted; $PathVer carries the parsed version for the
; prompt. NOTE the envelope parser is separator-AGNOSTIC (skips to the
; value's opening quote): the 2026-08-19 VM repro failed because a hardcoded
; +15 offset assumed `":"` while json.dumps emits `": "` — the parsed
; "version" was a single space and the ask silently degraded to never-shadow.
; No --format braces here — double braces are handlebars in this file.
Function PathConflictOlderSameOrigin
  StrCpy $R0 0
  StrCpy $PathVer ""
  nsExec::ExecToStack '"$PathHit" version --format json'
  Pop $0
  Pop $1
  ${If} $0 = 0
    ${StrLoc} $2 $1 "aisc.cli/v1" ">"
    ${If} $2 != ""
      ${StrLoc} $2 $1 '"cli_version"' ">"
      ${If} $2 != ""
        IntOp $2 $2 + 13
        StrCpy $3 $1 "" $2
        ; skip to the value's opening quote; ,/}/end mean null or a number
        ${Do}
          StrCpy $4 $3 1
          ${If} $4 == '"'
            ${Break}
          ${EndIf}
          ${If} $4 == ","
          ${OrIf} $4 == "}"
          ${OrIf} $4 == ""
            StrCpy $3 ""
            ${Break}
          ${EndIf}
          StrCpy $3 $3 "" 1
        ${Loop}
        ${If} $3 != ""
          StrCpy $3 $3 "" 1
          ${Do}
            StrCpy $4 $3 1
            ${If} $4 == '"'
            ${OrIf} $4 == ""
              ${Break}
            ${EndIf}
            StrCpy $PathVer "$PathVer$4"
            StrCpy $3 $3 "" 1
          ${Loop}
        ${EndIf}
      ${EndIf}
    ${EndIf}
  ${EndIf}
  ${If} $PathVer == ""
    ; pre-envelope fallback: `--version` prose, first digit onward
    nsExec::ExecToStack '"$PathHit" --version'
    Pop $0
    Pop $1
    ${If} $0 = 0
      ${StrCase} $1 $1 "L"
      ${StrLoc} $2 $1 "aisc" ">"
      ${If} $2 != ""
        IntOp $2 $2 + 4
        StrCpy $3 $1 "" $2
      ki5v_scan:
        StrCpy $4 $3 1
        ${If} $4 == ""
          Goto ki5v_done
        ${EndIf}
        ${If} $4 == "0"
        ${OrIf} $4 == "1"
        ${OrIf} $4 == "2"
        ${OrIf} $4 == "3"
        ${OrIf} $4 == "4"
        ${OrIf} $4 == "5"
        ${OrIf} $4 == "6"
        ${OrIf} $4 == "7"
        ${OrIf} $4 == "8"
        ${OrIf} $4 == "9"
          Goto ki5v_digit
        ${EndIf}
        StrCpy $3 $3 "" 1
        Goto ki5v_scan
      ki5v_digit:
        ${Do}
          StrCpy $4 $3 1
          ${If} $4 == " "
          ${OrIf} $4 == "\r"
          ${OrIf} $4 == "\n"
          ${OrIf} $4 == ""
            ${Break}
          ${EndIf}
          StrCpy $PathVer "$PathVer$4"
          StrCpy $3 $3 "" 1
        ${Loop}
      ki5v_done:
      ${EndIf}
    ${EndIf}
  ${EndIf}
  ${If} $PathVer == ""
    Return
  ${EndIf}
  nsis_tauri_utils::SemverCompare "${VERSION}" $PathVer
  Pop $2
  ${IfThen} $2 = 1 ${|} StrCpy $R0 1 ${|}
FunctionEnd

; Does the DIRECTORY of $PathHit appear as an entry in the user PATH
; ($PathRaw)? If not, the shadow lives in the system PATH and a per-user
; prepend can never override it. Sets $R0=1 when user-scoped. Entries are
; compared normalized; %VAR% forms are expanded for the compare too.
Function UserPathContainsHitDir
  StrCpy $R0 0
  StrCpy $0 $PathHit
  Call PathNormalizeDir
  StrCpy $5 $0
  StrCpy $6 "\aisc.exe"
  StrLen $7 $6
  StrLen $8 $5
  ${If} $8 < $7
    Return
  ${EndIf}
  IntOp $8 $8 - $7
  StrCpy $5 $5 $8              ; normalized dir of the hit
  StrCpy $1 $PathRaw
  ${Do}
    ${If} $1 == ""
      ${Break}
    ${EndIf}
    StrCpy $3 ""
    ${Do}
      StrCpy $2 $1 1
      ${If} $2 == ";"
      ${OrIf} $2 == ""
        ${Break}
      ${EndIf}
      StrCpy $3 "$3$2"
      StrCpy $1 $1 "" 1
    ${Loop}
    StrCpy $2 $1 1
    ${IfThen} $2 == ";" ${|} StrCpy $1 $1 "" 1 ${|}
    ${If} $3 != ""
      StrCpy $0 $3
      Call PathNormalizeDir
      ${If} $0 == $5
        StrCpy $R0 1
        ${Break}
      ${EndIf}
      ExpandEnvStrings $4 $3
      ${If} $4 != $3
        StrCpy $0 $4
        Call PathNormalizeDir
        ${If} $0 == $5
          StrCpy $R0 1
          ${Break}
        ${EndIf}
      ${EndIf}
    ${EndIf}
  ${Loop}
FunctionEnd

Section Install
  SetOutPath $INSTDIR

  !ifmacrodef NSIS_HOOK_PREINSTALL
    !insertmacro NSIS_HOOK_PREINSTALL
  !endif

  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"

  ; docker-resource C1: capture the current default-image ID BEFORE any
  ; File overwrites the previous sidecar — the post-install rebuild hands
  ; it off (01 §3 upgrade ordering). No-op on a fresh install (no
  ; aisc-*.exe on disk yet) and when the old CLI predates the
  ; maintenance commands (scan fails -> empty id -> rebuild skips handoff).
  Call CaptureOldImageId

  ; Copy main executable
  File "${MAINBINARYSRCPATH}"

  ; Copy resources
  {{#each resources_dirs}}
    CreateDirectory "$INSTDIR\\{{this}}"
  {{/each}}
  {{#each resources}}
    File /a "/oname={{this.[1]}}" "{{no-escape @key}}"
  {{/each}}

  ; Copy external binaries
  {{#each binaries}}
    File /a "/oname={{this}}" "{{no-escape @key}}"
  {{/each}}

  ; Create file associations
  {{#each file_associations as |association| ~}}
    {{#each association.ext as |ext| ~}}
       !insertmacro APP_ASSOCIATE "{{ext}}" "{{or association.name ext}}" "{{association-description association.description ext}}" "$INSTDIR\${MAINBINARYNAME}.exe,0" "Open with ${PRODUCTNAME}" "$INSTDIR\${MAINBINARYNAME}.exe $\"%1$\""
    {{/each}}
  {{/each}}

  ; Register deep links
  {{#each deep_link_protocols as |protocol| ~}}
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}" "URL Protocol" ""
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}" "" "URL:${BUNDLEID} protocol"
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}\DefaultIcon" "" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\",0"
    WriteRegStr SHCTX "Software\Classes\\{{protocol}}\shell\open\command" "" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\" $\"%1$\""
  {{/each}}

  ; Create uninstaller
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Save $INSTDIR in registry for future installations
  WriteRegStr SHCTX "${MANUPRODUCTKEY}" "" $INSTDIR

  ; Stage 5 (A-INS01/A-ONB08): installer → Workbench non-sensitive handoff.
  ; Only facts the Workbench re-checks anyway (D5-07): source, installed
  ; version, first-run marker, Docker hint. NEVER secrets or the installer
  ; locale-dependent path beyond $INSTDIR. The Workbench reads these to decide
  ; whether to show first-run onboarding and to surface dependency hints, but
  ; re-queries CLI/Docker itself (handoff is not a fact).
  WriteRegStr SHCTX "${MANUPRODUCTKEY}" "InstallerSource" "nsis"
  WriteRegStr SHCTX "${MANUPRODUCTKEY}" "InstalledVersion" "${VERSION}"
  WriteRegDWORD SHCTX "${MANUPRODUCTKEY}" "FirstRun" 1
  WriteRegStr SHCTX "${MANUPRODUCTKEY}" "DockerHint" "installer_checked"

  ; G-18: expose the sidecar to user terminals via the user PATH (05 §5.2).
  Call AddInstDirToPath

  !if "${INSTALLMODE}" == "both"
    ; Save install mode to be selected by default for the next installation such as updating
    ; or when uninstalling
    WriteRegStr SHCTX "${UNINSTKEY}" $MultiUser.InstallMode 1
  !endif

  ; Remove old main binary if it doesn't match new main binary name
  ReadRegStr $OldMainBinaryName SHCTX "${UNINSTKEY}" "MainBinaryName"
  ${If} $OldMainBinaryName != ""
  ${AndIf} $OldMainBinaryName != "${MAINBINARYNAME}.exe"
    Delete "$INSTDIR\$OldMainBinaryName"
  ${EndIf}

  ; Save current MAINBINARYNAME for future updates
  WriteRegStr SHCTX "${UNINSTKEY}" "MainBinaryName" "${MAINBINARYNAME}.exe"

  ; Registry information for add/remove programs
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${PRODUCTNAME}"
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayIcon" "$\"$INSTDIR\${MAINBINARYNAME}.exe$\""
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr SHCTX "${UNINSTKEY}" "Publisher" "${MANUFACTURER}"
  WriteRegStr SHCTX "${UNINSTKEY}" "InstallLocation" "$\"$INSTDIR$\""
  WriteRegStr SHCTX "${UNINSTKEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoModify" "1"
  WriteRegDWORD SHCTX "${UNINSTKEY}" "NoRepair" "1"

  ${GetSize} "$INSTDIR" "/M=uninstall.exe /S=0K /G=0" $0 $1 $2
  IntOp $0 $0 + ${ESTIMATEDSIZE}
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD SHCTX "${UNINSTKEY}" "EstimatedSize" "$0"

  !if "${HOMEPAGE}" != ""
    WriteRegStr SHCTX "${UNINSTKEY}" "URLInfoAbout" "${HOMEPAGE}"
    WriteRegStr SHCTX "${UNINSTKEY}" "URLUpdateInfo" "${HOMEPAGE}"
    WriteRegStr SHCTX "${UNINSTKEY}" "HelpLink" "${HOMEPAGE}"
  !endif

  ; Create start menu shortcut
  !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    Call CreateOrUpdateStartMenuShortcut
  !insertmacro MUI_STARTMENU_WRITE_END

  ; Create desktop shortcut for silent and passive installers
  ; because finish page will be skipped
  ${If} $PassiveMode = 1
  ${OrIf} ${Silent}
    Call CreateOrUpdateDesktopShortcut
  ${EndIf}

  !ifmacrodef NSIS_HOOK_POSTINSTALL
    !insertmacro NSIS_HOOK_POSTINSTALL
  !endif

  ; docker-resource C1: upgrade lifecycle — stop AISC containers (the
  ; tagged image survives until the rebuild succeeds), then no-cache
  ; rebuild with the captured old-ID handoff. Fresh installs never build
  ; (01 §2.2.7); best-effort — failures only set the pending note.
  Call UpgradeDockerLifecycle

  ; Auto close this page for passive mode
  ${If} $PassiveMode = 1
    SetAutoClose true
  ${EndIf}
SectionEnd

Section Docker
  ; Host integration: detect Docker Desktop so the finish-page launcher can
  ; start it when present. Install is DEFERRED to the Workbench first-run
  ; wizard ("Install and start Docker", A-ONB02/B) — the installer must stay
  ; fast and light, and the user decides in-app when Docker is needed. Never
  ; auto-installs via winget here (silent/passive installs skip anyway).
  ${If} ${Silent}
    Goto docker_done
  ${EndIf}
  ${If} $PassiveMode = 1
    Goto docker_done
  ${EndIf}

  Call CheckDocker
  ${If} $DepsDockerInstalled = 1
    DetailPrint "$(DOCKER_PRESENT)"
  ${Else}
    DetailPrint "$(DOCKER_MISSING_DEFERRED)"
  ${EndIf}
docker_done:
SectionEnd

; docker-resource C1: locate the bundled sidecar by pattern (the rendered
; externalBin name carries an arch suffix — never hardcode it).
Function FindAiscCli
  StrCpy $AiscCliExe ""
  ClearErrors
  FindFirst $0 $1 "$INSTDIR\aisc*.exe"
  ${DoUntil} ${Errors}
    ${If} $1 != ""
    ${AndIf} $AiscCliExe == ""
      StrCpy $AiscCliExe "$INSTDIR\$1"
    ${EndIf}
    FindNext $0 $1
  ${Loop}
  FindClose $0
FunctionEnd

Function CaptureOldImageId
  StrCpy $OldImageId ""
  StrCpy $HadPreviousInstall 0
  Call FindAiscCli
  ${If} $AiscCliExe == ""
    Return
  ${EndIf}
  StrCpy $HadPreviousInstall 1
  ; Text-mode scan: stable "kind ownership id name" lines (JSON is not
  ; parseable in NSIS). Any failure leaves the id empty.
  nsExec::ExecToStack /TIMEOUT=60000 '"$AiscCliExe" maintenance docker-scan --context upgrade --format text'
  Pop $0
  Pop $1
  ${If} $0 != 0
    Return
  ${EndIf}
  Push $1
  Call ExtractDefaultImageId
  Pop $OldImageId
  ${If} $OldImageId != ""
    DetailPrint "old image: $OldImageId"
  ${EndIf}
FunctionEnd

; Stack: scan text -> default-image id ("" when absent). Line shape:
; "image owned <id> super-claude:latest" / "image legacy_owned <id> ...".
Function ExtractDefaultImageId
  Pop $R0            ; remaining text
  StrCpy $R1 ""      ; result
  ${Do}
    ${If} $R0 == ""
      ${Break}
    ${EndIf}
    StrCpy $R2 ""    ; current line
    ${Do}
      StrCpy $R3 $R0 1
      ${If} $R3 == "$\r"
      ${OrIf} $R3 == "$\n"
      ${OrIf} $R3 == ""
        ${Break}
      ${EndIf}
      StrCpy $R2 "$R2$R3"
      StrCpy $R0 $R0 "" 1
    ${Loop}
    StrCpy $R3 $R0 1
    ${IfThen} $R3 == "$\r" ${|} StrCpy $R0 $R0 "" 1 ${|}
    StrCpy $R3 $R0 1
    ${IfThen} $R3 == "$\n" ${|} StrCpy $R0 $R0 "" 1 ${|}
    ; prefix: "image owned " (12) or "image legacy_owned " (19)
    StrCpy $R4 0
    StrCpy $R5 $R2 12
    ${If} $R5 == "image owned "
      StrCpy $R4 12
    ${Else}
      StrCpy $R5 $R2 19
      ${If} $R5 == "image legacy_owned "
        StrCpy $R4 19
      ${EndIf}
    ${EndIf}
    ${If} $R4 <> 0
      StrLen $R6 $R2
      IntOp $R7 $R6 - 20          ; start of the 20-char suffix
      ${If} $R7 > $R4
        StrCpy $R5 $R2 "" $R7     ; last 20 chars
        ${If} $R5 == " super-claude:latest"
          IntOp $R6 $R7 - $R4     ; id length
          StrCpy $R1 $R2 $R6 $R4
          ${Break}
        ${EndIf}
      ${EndIf}
    ${EndIf}
  ${Loop}
  Push $R1
FunctionEnd

Function UpgradeDockerLifecycle
  StrCpy $RebuildPending 0
  ; Upgrade = /UPDATE (Tauri self-update) OR a manual reinstall over an
  ; existing install (2026-08-26 smoke finding: the maintenance page's
  ; reinstall path never sets UpdateMode). Fresh installs skip entirely.
  ${If} $UpdateMode <> 1
  ${AndIf} $HadPreviousInstall <> 1
    Return
  ${EndIf}
  Call FindAiscCli
  ${If} $AiscCliExe == ""
    StrCpy $RebuildPending 1
    Return
  ${EndIf}
  ; 1) Upgrade-context cleanup = containers ONLY (02 §3 upgrade ordering:
  ; the tagged image must survive a failed rebuild).
  DetailPrint "$(UPGRADE_CLEAN_START)"
  nsExec::ExecToLog /TIMEOUT=180000 '"$AiscCliExe" maintenance docker-cleanup --context upgrade --format json'
  Pop $0
  Pop $1
  ${If} $0 == 3
    StrCpy $RebuildPending 1
    Return
  ${EndIf}
  ; 2) No-cache rebuild with the old-ID handoff (minutes; 30min budget).
  ; 2026-08-26 R2 smoke: an EMPTY $OldImageId must be omitted entirely — a
  ; bare --old-image-id is an argparse usage error that aborts the rebuild.
  DetailPrint "$(UPGRADE_REBUILD_START)"
  ${If} $OldImageId == ""
    nsExec::ExecToLog /TIMEOUT=1800000 '"$AiscCliExe" maintenance docker-rebuild --root "$INSTDIR\aisc-bundle" --tag super-claude:latest'
  ${Else}
    nsExec::ExecToLog /TIMEOUT=1800000 '"$AiscCliExe" maintenance docker-rebuild --root "$INSTDIR\aisc-bundle" --tag super-claude:latest --old-image-id $OldImageId'
  ${EndIf}
  Pop $0
  Pop $1
  ${If} $0 != 0
    StrCpy $RebuildPending 1
  ${EndIf}
FunctionEnd

Function .onInstSuccess
  ; docker-resource C1: upgrade rebuild did not complete (Docker down or
  ; build failed) — interactive finish note with the manual command.
  ${If} $RebuildPending = 1
  ${AndIfNot} ${Silent}
  ${AndIf} $PassiveMode <> 1
    MessageBox MB_ICONINFORMATION "$(REBUILD_PENDING)"
  ${EndIf}

  ; Check for `/R` flag only in silent and passive installers because
  ; GUI installer has a toggle for the user to (re)start the app
  ${If} $PassiveMode = 1
  ${OrIf} ${Silent}
    ${GetOptions} $CMDLINE "/R" $R0
    ${IfNot} ${Errors}
      ; /R auto-start: bring Docker Desktop up first if installed (silent
      ; installs never ran Section Docker, and CI does not pass /R).
      Call CheckDocker
      ${If} $DepsDockerInstalled = 1
        Call StartDockerDesktop
      ${EndIf}
      ${GetOptions} $CMDLINE "/ARGS" $R0
      nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" "$R0"
    ${EndIf}
  ${EndIf}
FunctionEnd

Function un.onInit
  !insertmacro SetContext

  !if "${INSTALLMODE}" == "both"
    !insertmacro MULTIUSER_UNINIT
  !endif

  !insertmacro MUI_UNGETLANGUAGE

  ${GetOptions} $CMDLINE "/P" $PassiveMode
  ${IfNot} ${Errors}
    StrCpy $PassiveMode 1
  ${EndIf}

  ${GetOptions} $CMDLINE "/UPDATE" $UpdateMode
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
  ${EndIf}

  ; docker-resource C1: explicit Docker-resource keep for scripted
  ; uninstalls (same force level as unchecking the box).
  StrCpy $KeepDockerMode 0
  ${GetOptions} $CMDLINE "/KEEPDOCKER" $0
  ${IfNot} ${Errors}
    StrCpy $KeepDockerMode 1
  ${EndIf}
FunctionEnd

Section Uninstall
  !ifmacrodef NSIS_HOOK_PREUNINSTALL
    !insertmacro NSIS_HOOK_PREUNINSTALL
  !endif

  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"

  ; docker-resource C1: the lifecycle cleanup runs BEFORE any file deletion
  ; — the bundled sidecar performs it and must still exist (02 §3/C1).
  ; /KEEPDOCKER and /UPDATE skip; best-effort, never blocks the uninstall.
  StrCpy $DockerCleanupSkipped 0
  ${If} $DeleteDockerCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
  ${AndIf} $KeepDockerMode <> 1
    Call un.CleanDockerResources
  ${EndIf}

  ; Third option (independent of Docker cleanup AND of app data): delete
  ; the persistent per-workspace toolchains (host_bind backend = plain
  ; dirs under the data root). Default unchecked (02 §3.1).
  ${If} $ToolchainCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    Call un.DeleteToolchains
  ${EndIf}

  ; Delete the app directory and its content from disk
  ; Copy main executable
  Delete "$INSTDIR\${MAINBINARYNAME}.exe"

  ; Delete resources
  {{#each resources}}
    Delete "$INSTDIR\\{{this.[1]}}"
  {{/each}}

  ; Delete external binaries
  {{#each binaries}}
    Delete "$INSTDIR\\{{this}}"
  {{/each}}

  ; Delete app associations
  {{#each file_associations as |association| ~}}
    {{#each association.ext as |ext| ~}}
      !insertmacro APP_UNASSOCIATE "{{ext}}" "{{or association.name ext}}"
    {{/each}}
  {{/each}}

  ; Delete deep links
  {{#each deep_link_protocols as |protocol| ~}}
    ReadRegStr $R7 SHCTX "Software\Classes\\{{protocol}}\shell\open\command" ""
    ${If} $R7 == "$\"$INSTDIR\${MAINBINARYNAME}.exe$\" $\"%1$\""
      DeleteRegKey SHCTX "Software\Classes\\{{protocol}}"
    ${EndIf}
  {{/each}}


  ; Delete uninstaller
  Delete "$INSTDIR\uninstall.exe"

  {{#each resources_ancestors}}
  RMDir /REBOOTOK "$INSTDIR\\{{this}}"
  {{/each}}
  RMDir "$INSTDIR"

  ; Remove shortcuts if not updating
  ${If} $UpdateMode <> 1
    !insertmacro DeleteAppUserModelId

    ; Remove start menu shortcut
    !insertmacro MUI_STARTMENU_GETFOLDER Application $AppStartMenuFolder
    !insertmacro IsShortcutTarget "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 = 1
      !insertmacro UnpinShortcut "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"
      Delete "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"
      RMDir "$SMPROGRAMS\$AppStartMenuFolder"
    ${EndIf}
    !insertmacro IsShortcutTarget "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 = 1
      !insertmacro UnpinShortcut "$SMPROGRAMS\${PRODUCTNAME}.lnk"
      Delete "$SMPROGRAMS\${PRODUCTNAME}.lnk"
    ${EndIf}

    ; Remove desktop shortcuts
    !insertmacro IsShortcutTarget "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 = 1
      !insertmacro UnpinShortcut "$DESKTOP\${PRODUCTNAME}.lnk"
      Delete "$DESKTOP\${PRODUCTNAME}.lnk"
    ${EndIf}
  ${EndIf}

  ; Remove registry information for add/remove programs
  !if "${INSTALLMODE}" == "both"
    DeleteRegKey SHCTX "${UNINSTKEY}"
  !else if "${INSTALLMODE}" == "perMachine"
    DeleteRegKey HKLM "${UNINSTKEY}"
  !else
    DeleteRegKey HKCU "${UNINSTKEY}"
  !endif

  ; Removes the Autostart entry for ${PRODUCTNAME} from the HKCU Run key if it exists.
  ; This ensures the program does not launch automatically after uninstallation if it exists.
  ; If it doesn't exist, it does nothing.
  ; We do this when not updating (to preserve the registry value on updates)
  ${If} $UpdateMode <> 1
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${PRODUCTNAME}"
  ${EndIf}

  ; G-18: remove the owned PATH entry (exact match only); /UPDATE keeps it so
  ; a reinstall restores the same entry instead of removing+re-adding (05 §5.2).
  ${If} $UpdateMode <> 1
    Call un.RemoveInstDirFromPath
  ${EndIf}

  ; Delete app data if the checkbox is selected
  ; and if not updating
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    ; Clear the install location $INSTDIR from registry
    DeleteRegKey SHCTX "${MANUPRODUCTKEY}"
    DeleteRegKey /ifempty SHCTX "${MANUKEY}"

    ; Clear the install language from registry
    DeleteRegValue HKCU "${MANUPRODUCTKEY}" "Installer Language"
    DeleteRegKey /ifempty HKCU "${MANUPRODUCTKEY}"
    DeleteRegKey /ifempty HKCU "${MANUKEY}"

    SetShellVarContext current
    RmDir /r "$APPDATA\${BUNDLEID}"
    RmDir /r "$LOCALAPPDATA\${BUNDLEID}"
    ; KI-4 (2026-08-18): the REAL data root (Stage 7 layout): settings,
    ; workbench history, onboarding state and per-workspace agent state live
    ; under %LOCALAPPDATA%\AISC — the two Tauri paths above only cover the
    ; pre-Stage-7 layout, which is how a "fully cleaned" uninstall used to
    ; leave the product dir (and a stale CLI pin) behind.
    ${If} "$LOCALAPPDATA" != ""
      RmDir /r "$LOCALAPPDATA\AISC"
    ${EndIf}
  ${EndIf}

  !ifmacrodef NSIS_HOOK_POSTUNINSTALL
    !insertmacro NSIS_HOOK_POSTUNINSTALL
  !endif

  ; Auto close if passive mode or updating
  ${If} $PassiveMode = 1
  ${OrIf} $UpdateMode = 1
    SetAutoClose true
  ${EndIf}
SectionEnd

; docker-resource C1: locate the bundled sidecar WITHOUT hardcoding the
; rendered externalBin name (the arch suffix varies) — pattern search only.
; Writes the absolute path to $AiscCliExe, "" if none.
Function un.FindAiscCli
  StrCpy $AiscCliExe ""
  ClearErrors
  FindFirst $0 $1 "$INSTDIR\aisc*.exe"
  ${DoUntil} ${Errors}
    ${If} $1 != ""
    ${AndIf} $AiscCliExe == ""
      StrCpy $AiscCliExe "$INSTDIR\$1"
    ${EndIf}
    FindNext $0 $1
  ${Loop}
  FindClose $0
FunctionEnd

; docker-resource C1 (02 §3): the centralized lifecycle service does the
; classification + removal (three-tier ownership, containers before images,
; ID dedup) — this installer never reimplements the filter rules, and the
; duplicated KI-4 docker-CLI discovery/ps/rm/rmi chain is deleted. Exit
; codes (frozen): 0 ok · 3 Docker unavailable · 1 partial (logged by the
; CLI). Best-effort: the uninstall never fails here.
Function un.CleanDockerResources
  Call un.FindAiscCli
  ${If} $AiscCliExe == ""
    DetailPrint "$(DOCKER_CLEAN_UNREACHABLE): aisc CLI not found"
    StrCpy $DockerCleanupSkipped 1
    Return
  ${EndIf}

  DetailPrint "$(DOCKER_CLEAN_START)"
  nsExec::ExecToLog '"$AiscCliExe" maintenance docker-cleanup --context uninstall --format json'
  Pop $0
  Pop $1
  ${If} $0 == 3
    DetailPrint "$(DOCKER_CLEAN_UNREACHABLE)"
    StrCpy $DockerCleanupSkipped 1
  ${Else}
    ; 0 = clean, 1 = partial failures (already logged by the CLI) — the
    ; shared note only fires for the fully-unreachable case.
    DetailPrint "$(DOCKER_CLEAN_DONE)"
  ${EndIf}
FunctionEnd

; docker-resource C1: third uninstall option — persistent project
; toolchains (host_bind backend = plain directories under the data root).
; Independent of the container/image cleanup; workspace files, agent
; configs and everything else under the data root are untouched.
Function un.DeleteToolchains
  ${If} "$LOCALAPPDATA" == ""
    Return
  ${EndIf}
  ClearErrors
  FindFirst $0 $1 "$LOCALAPPDATA\AISC\data\workspaces\*"
  ${DoUntil} ${Errors}
    ${If} $1 != ""
    ${AndIf} ${FileExists} "$LOCALAPPDATA\AISC\data\workspaces\$1\toolchain\*"
      DetailPrint "toolchain: $1"
      RmDir /r "$LOCALAPPDATA\AISC\data\workspaces\$1\toolchain"
    ${EndIf}
    FindNext $0 $1
  ${Loop}
  FindClose $0
FunctionEnd

; KI-4: finish note when Docker cleanup was requested but the engine was not
; reachable — names the kept resources and the manual commands. No popup in
; passive/silent runs (there is no UI to show it on).
Function un.onUnInstSuccess
  ${If} $DockerCleanupSkipped = 1
  ${AndIf} $PassiveMode <> 1
    MessageBox MB_ICONINFORMATION "$(DOCKER_CLEANUP_SKIPPED)"
  ${EndIf}
FunctionEnd

Function RestorePreviousInstallLocation
  ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
  StrCmp $4 "" +2 0
    StrCpy $INSTDIR $4
FunctionEnd

Function Skip
  Abort
FunctionEnd

Function SkipIfPassive
  ${IfThen} $PassiveMode = 1  ${|} Abort ${|}
FunctionEnd
Function un.SkipIfPassive
  ${IfThen} $PassiveMode = 1  ${|} Abort ${|}
FunctionEnd

Function CreateOrUpdateStartMenuShortcut
  ; We used to use product name as MAINBINARYNAME
  ; migrate old shortcuts to target the new MAINBINARYNAME
  StrCpy $R0 0

  !insertmacro IsShortcutTarget "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\$OldMainBinaryName"
  Pop $0
  ${If} $0 = 1
    !insertmacro SetShortcutTarget "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    StrCpy $R0 1
  ${EndIf}

  !insertmacro IsShortcutTarget "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\$OldMainBinaryName"
  Pop $0
  ${If} $0 = 1
    !insertmacro SetShortcutTarget "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    StrCpy $R0 1
  ${EndIf}

  ${If} $R0 = 1
    Return
  ${EndIf}

  ; Skip creating shortcut if in update mode or no shortcut mode
  ; but always create if migrating from wix
  ${If} $WixMode = 0
    ${If} $UpdateMode = 1
    ${OrIf} $NoShortcutMode = 1
      Return
    ${EndIf}
  ${EndIf}

  !if "${STARTMENUFOLDER}" != ""
    CreateDirectory "$SMPROGRAMS\$AppStartMenuFolder"
    CreateShortcut "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    !insertmacro SetLnkAppUserModelId "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"
  !else
    CreateShortcut "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    !insertmacro SetLnkAppUserModelId "$SMPROGRAMS\${PRODUCTNAME}.lnk"
  !endif
FunctionEnd

Function CreateOrUpdateDesktopShortcut
  ; We used to use product name as MAINBINARYNAME
  ; migrate old shortcuts to target the new MAINBINARYNAME
  !insertmacro IsShortcutTarget "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\$OldMainBinaryName"
  Pop $0
  ${If} $0 = 1
    !insertmacro SetShortcutTarget "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Return
  ${EndIf}

  ; Skip creating shortcut if in update mode or no shortcut mode
  ; but always create if migrating from wix
  ${If} $WixMode = 0
    ${If} $UpdateMode = 1
    ${OrIf} $NoShortcutMode = 1
      Return
    ${EndIf}
  ${EndIf}

  CreateShortcut "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
  !insertmacro SetLnkAppUserModelId "$DESKTOP\${PRODUCTNAME}.lnk"
FunctionEnd
