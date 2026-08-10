; Standalone syntax + behavior test for the installer Docker host-integration
; functions (CheckDocker / CheckWinget). Compiled with the real makensis and
; run silently - the installed process is a 32-bit NSIS exe, same as the
; production installer, so SetRegView handling is exercised for real.
; StartDockerDesktop is NOT covered here: nsis_tauri_utils only exists in the
; real tauri build. Not part of the tauri build.
Unicode true
!include MUI2.nsh
!include x64.nsh

Var DepsDockerInstalled
Var DepsDockerExe
Var DepsWingetInstalled

Name "aisc-check-test"
OutFile "$%TEMP%\aisc-check-test.exe"
InstallDir "$TEMP\aisc-check-test"

; ===== verbatim from installer.nsi =====
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
; ===== end verbatim =====

Section
  Call CheckDocker
  Call CheckWinget
  FileOpen $0 "$TEMP\aisc-check-result.txt" w
  FileWrite $0 "docker_installed=$DepsDockerInstalled$\r$\ndocker_exe=$DepsDockerExe$\r$\nwinget_installed=$DepsWingetInstalled$\r$\n"
  FileClose $0
SectionEnd
