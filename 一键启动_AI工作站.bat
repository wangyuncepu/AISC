@echo off
chcp 65001 >nul

set IMAGE=super-claude:latest
set TITLE=Super Claude AI 工作站
REM 容器名加唯一后缀，避免多开（项目+临时并行）时同名容器互相挤掉
set NAME=super-claude-station-%RANDOM%

echo.
echo ╔══════════════════════════════════════════╗
echo ║     🚀 Super Claude AI 工作站          ║
echo ║        cs 一键切换 · 插件内置           ║
echo ╚══════════════════════════════════════════╝
echo.
echo 💡 容器内可用 cs ark / cs deepseek / cs show 切换模型后端
echo.

REM 已在 Windows Terminal 内 → 不重开新窗口，直接在当前标签运行 (修 4a)
if defined WT_SESSION goto run

REM 不在 wt：装了 wt 就以本脚本开新标签；docker run 在重启实例内执行，
REM 不把命令塞进 wt 解析器，避免嵌套引号被拆导致丢参 (修 4b)
where wt >nul 2>nul
if errorlevel 1 goto run
echo ✅ 检测到 Windows Terminal，新标签启动 UTF-8 友好终端...
wt -d "%cd%" --title "%TITLE%" cmd /k ""%~f0""
exit /b

:run
REM 仅清理已退出的旧工作站容器（不影响正在运行的，支持多开并行）
for /f %%i in ('docker ps -aq -f "name=super-claude-station" -f "status=exited" 2^>nul') do docker rm %%i >nul 2>nul

REM ── 检查镜像是否存在 ──
docker image inspect %IMAGE% >nul 2>nul
if %errorlevel%==0 goto imgexists

echo 🔍 未找到镜像 %IMAGE%，开始构建...
call :build
goto runcontainer

:imgexists
REM ── 防止悬空镜像：同名镜像已存在，提示用户处理 ──
echo ⚠️  已存在同名镜像: %IMAGE%
echo    [1] 直接运行现有镜像（默认）
echo    [2] 删除旧镜像并重新构建（避免悬空 ^<none^> 镜像）
echo    [3] 用新镜像名构建运行（保留旧镜像）
set "choice="
set /p choice=请选择 [1/2/3，默认 1]:
if "%choice%"=="2" goto rebuild
if "%choice%"=="3" goto newname
echo ▶️  使用现有镜像。
goto runcontainer

:rebuild
echo 🗑️  删除旧镜像 %IMAGE% ...
docker rmi -f %IMAGE% >nul 2>nul
call :build
goto runcontainer

:newname
set "NEWIMG="
set /p NEWIMG=输入新镜像名 ^(如 super-claude:v2^):
if not "%NEWIMG%"=="" set IMAGE=%NEWIMG%
call :build
goto runcontainer

:build
echo 📦 正在构建镜像: %IMAGE% ...
docker build -t %IMAGE% "%~dp0."
echo ✅ 构建完成: %IMAGE%
goto :eof

:runcontainer
echo.
echo 📦 正在启动容器...
docker run -it --rm --name %NAME% -v "%cd%:/app" %IMAGE%
