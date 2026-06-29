@echo off
chcp 65001 >nul

set IMAGE=super-claude:latest
set TITLE=Super Claude AI Workstation
REM Unique container name suffix so parallel runs (project + temporary) don't evict each other
set NAME=super-claude-station-%RANDOM%

REM Per-project named volume for /app/.claude. Windows bind mounts don't propagate
REM inotify -> Claude Code can't hot-reload settings (cs ds not live) and HUD/statusLine
REM breaks. A named volume is real Linux FS in the Docker VM -> inotify works.
REM Code stays bind-mounted/editable on host; only .claude lives in the volume.
set "VOL=%CD%"
set "VOL=%VOL::=%"
set "VOL=%VOL:\=_%"
set "VOL=%VOL:/=_%"
set "VOL=%VOL: =_%"
set "VOL=sc-claude-%VOL%"

echo.
echo ==========================================
echo    Super Claude AI Workstation
echo    cs backend switch . plugins built-in
echo ==========================================
echo.
echo Tip: inside container use  cs ark / cs deepseek / cs show
echo.

REM Already inside Windows Terminal -> run in current tab, no new window
if defined WT_SESSION goto run

REM Not in wt: if wt installed, open a new tab and run docker there
where wt >nul 2>nul
if errorlevel 1 goto run
echo Windows Terminal detected, opening UTF-8 friendly tab...
wt -d "%cd%" --title "%TITLE%" cmd /k ""%~f0""
exit /b

:run
REM Clean only EXITED old station containers (keep running ones; supports parallel)
for /f %%i in ('docker ps -aq -f "name=super-claude-station" -f "status=exited" 2^>nul') do docker rm %%i >nul 2>nul

REM ---- Check if image exists ----
docker image inspect %IMAGE% >nul 2>nul
if %errorlevel%==0 goto imgexists

echo Image %IMAGE% not found, building...
call :build
goto runcontainer

:imgexists
REM ---- Same-name image exists: prompt to avoid dangling images ----
echo Image already exists: %IMAGE%
echo    [1] Run existing image (default)
echo    [2] Delete old image and rebuild (avoid dangling ^<none^> images)
echo    [3] Build under a NEW image name (keep old image)
set "choice="
set /p choice=Choose [1/2/3, default 1]:
if "%choice%"=="2" goto rebuild
if "%choice%"=="3" goto newname
echo Using existing image.
goto runcontainer

:rebuild
echo Deleting old image %IMAGE% ...
docker rmi -f %IMAGE% >nul 2>nul
call :build
goto runcontainer

:newname
set "NEWIMG="
set /p NEWIMG=Enter new image name (e.g. super-claude:v2):
if not "%NEWIMG%"=="" set IMAGE=%NEWIMG%
call :build
goto runcontainer

:build
set "CACHE_FLAG="
set "MIRROR_ARG=USE_CN_MIRROR=1"
REM China mirror also pulls base node image from daocloud (bypass docker.io timeout)
set "NODE_ARG=NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim"
set "uc="
set /p uc=Use build cache? [Y/n] (n = --no-cache):
if /i "%uc%"=="n" set "CACHE_FLAG=--no-cache"
set "um="
set /p um=Use China mirrors (base daocloud / apt tuna / npm taobao)? [Y/n]:
if /i "%um%"=="n" set "MIRROR_ARG=USE_CN_MIRROR=0"
if /i "%um%"=="n" set "NODE_ARG=NODE_IMAGE=node:20-slim"
echo Building image: %IMAGE%  (%MIRROR_ARG%) %CACHE_FLAG% ...
docker build %CACHE_FLAG% --build-arg %MIRROR_ARG% --build-arg %NODE_ARG% -t %IMAGE% "%~dp0."
echo Build done: %IMAGE%
goto :eof

:runcontainer
echo.
echo Starting container...
docker run -it --rm -e TERM=xterm-256color --name %NAME% -v "%cd%:/app" -v "%VOL%:/app/.claude" %IMAGE%
