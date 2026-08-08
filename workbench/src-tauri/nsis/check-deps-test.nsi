; Standalone syntax + behavior test for the S4.1.b dependency check
; functions (CheckDocker / CheckPythonCore / CheckPython). Compiled with
; the real makensis and run silently - the installed process is a 32-bit
; NSIS exe, same as the production installer, so SetRegView handling is
; exercised for real. Not part of the tauri build.
Unicode true
!include MUI2.nsh
!include x64.nsh

Var DepsDockerInstalled
Var DepsDockerExe
Var DepsPythonInstalled

Name "aisc-check-test"
OutFile "$%TEMP%\aisc-check-test.exe"
InstallDir "$TEMP\aisc-check-test"

; ===== verbatim from installer.nsi =====
Function CheckDocker
  ; Docker Desktop installs machine-wide to "Program Files\Docker\Docker"
  ; (MSI) or per-user to %LOCALAPPDATA% (winget). Detect by executable
  ; presence and remember the path so the Start-Docker buttons can use it.
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

; Enumerate PythonCore version subkeys (e.g. 3.12, 3.14) under REGROOT\KEYPATH
; and check that the registered InstallPath actually contains python.exe.
!macro CheckPythonCore REGROOT KEYPATH
  StrCpy $0 0
  ${Do}
    EnumRegKey $1 "${REGROOT}" "${KEYPATH}" $0
    ${If} $1 != ""
      ReadRegStr $2 "${REGROOT}" "${KEYPATH}\$1\InstallPath" ""
      ${If} $2 != ""
      ${AndIf} ${FileExists} "$2\python.exe"
        StrCpy $DepsPythonInstalled 1
      ${EndIf}
    ${EndIf}
    IntOp $0 $0 + 1
  ${LoopUntil} $1 == ""
!macroend

Function CheckPython
  ; Python 3 registers PythonCore\<version>\InstallPath in HKLM (machine-wide,
  ; 32/64-bit views) or HKCU (per-user, e.g. winget Python.Python.3.12). The
  ; default value of PythonCore itself is empty, so the version keys must be
  ; enumerated. Restore the 32-bit view afterwards - the installer process is
  ; 32-bit and the rest of the template relies on the default (redirected) view.
  StrCpy $DepsPythonInstalled 0
  SetRegView 64
  !insertmacro CheckPythonCore HKLM "SOFTWARE\Python\PythonCore"
  ${If} $DepsPythonInstalled = 0
    SetRegView 32
    !insertmacro CheckPythonCore HKLM "SOFTWARE\WOW6432Node\Python\PythonCore"
  ${EndIf}
  ${If} $DepsPythonInstalled = 0
    ; HKCU\SOFTWARE is never WOW64-redirected
    !insertmacro CheckPythonCore HKCU "SOFTWARE\Python\PythonCore"
  ${EndIf}
  SetRegView 32
FunctionEnd
; ===== end verbatim =====

Section
  Call CheckDocker
  Call CheckPython
  FileOpen $0 "$TEMP\aisc-check-result.txt" w
  FileWrite $0 "docker_installed=$DepsDockerInstalled$\r$\ndocker_exe=$DepsDockerExe$\r$\npython_installed=$DepsPythonInstalled$\r$\n"
  FileClose $0
SectionEnd
