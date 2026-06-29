@echo off
chcp 65001 >nul

set IMAGE=super-claude:latest
set TITLE=Super Claude AI 工作站
set NAME=super-claude-station

echo.
echo ╔══════════════════════════════════════════╗
echo ║     🚀 Super Claude AI 工作站          ║
echo ║        v1.1.3 · cs 一键切换            ║
echo ╚══════════════════════════════════════════╝
echo.
echo 📦 正在启动容器...
echo 💡 容器内可用 cs ark / cs deepseek / cs show 切换模型后端
echo 💡 单次运行示例：docker run -it --rm -v "%%cd%%:/app" %IMAGE% claude -p "解释这个项目"
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
REM 清理上次窗口被强制关闭后残留的同名容器，避免堆积 (no.3)
docker rm -f %NAME% >nul 2>nul
docker run -it --rm --name %NAME% -v "%cd%:/app" %IMAGE%
