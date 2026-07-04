@echo off
chcp 65001 >nul
REM Super Claude AI workstation launcher (ASCII wrapper).
REM Chinese UI lives in scripts\run.ps1 pipeline (cmd .bat has DBCS parse bugs with CJK).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1"
