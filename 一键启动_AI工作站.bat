@echo off
chcp 65001 >nul
REM Super Claude AI workstation launcher (ASCII wrapper).
REM Chinese UI lives in launcher.ps1 (cmd .bat has DBCS parse bugs with CJK).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"
