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
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1"
