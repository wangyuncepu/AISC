@echo off
chcp 65001 >nul

set IMAGE=super-claude:latest
set TITLE=Super Claude AI Workstation
REM Unique container name suffix so parallel runs (project + temporary) don't evict each other
set NAME=super-claude-station-%RANDOM%

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
set "uc="
set /p uc=Use build cache? [Y/n] (n = --no-cache):
if /i "%uc%"=="n" set "CACHE_FLAG=--no-cache"
set "um="
set /p um=Use China mirrors (apt tuna / npm taobao)? [Y/n]:
if /i "%um%"=="n" set "MIRROR_ARG=USE_CN_MIRROR=0"
echo Building image: %IMAGE%  (%MIRROR_ARG%) %CACHE_FLAG% ...
docker build %CACHE_FLAG% --build-arg %MIRROR_ARG% -t %IMAGE% "%~dp0."
echo Build done: %IMAGE%
goto :eof

:runcontainer
echo.
echo Starting container...
docker run -it --rm --name %NAME% -v "%cd%:/app" %IMAGE%
