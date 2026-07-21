@echo off
chcp 65001 >nul
REM Super Claude AI workstation launcher (ASCII wrapper).
REM Chinese UI lives in scripts\run.ps1 pipeline (cmd .bat has DBCS parse bugs with CJK).

REM Save current directory as default workspace
set AISC_WORKSPACE=%CD%

REM Parse --workspace argument
:parse
if "%~1"=="" goto run
if "%~1"=="--workspace" (
    set "AISC_WORKSPACE=%~2"
    shift
    shift
    goto parse
)
echo Unknown option: %~1
echo Usage: start.bat [--workspace PATH]
exit /b 1

:run
REM Verify scripts\run.ps1 exists in current directory
set "RUN_SCRIPT=%CD%\scripts\run.ps1"
if not exist "%RUN_SCRIPT%" (
    echo Error: scripts\run.ps1 not found at: %RUN_SCRIPT%
    echo Please run start.bat from the AISC repository root directory.
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%RUN_SCRIPT%"
