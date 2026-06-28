@echo off
chcp 65001 >nul

set IMAGE=super-claude:latest
set TITLE=Super Claude AI 工作站

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

where wt >nul 2>nul
if %errorlevel%==0 (
    echo ✅ 检测到 Windows Terminal，使用 UTF-8 友好终端启动...
    wt --title "%TITLE%" cmd /k "chcp 65001 ^>nul && docker run -it --rm -v ""%cd%:/app"" %IMAGE%"
) else (
    echo ⚠️ 未检测到 Windows Terminal，使用当前终端启动；如中文乱码，请安装 Windows Terminal。
    docker run -it --rm -v "%cd%:/app" %IMAGE%
)
