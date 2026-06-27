@echo off
chcp 65001 >nul

echo.
echo ╔══════════════════════════════════════════╗
echo ║     🚀 Super Claude AI 工作站          ║
echo ║        v1.1.0 · cs 一键切换       ║
echo ╚══════════════════════════════════════════╝
echo.
echo 📦 正在启动容器...
echo 💡 容器内可用 cs ark / cs deepseek / cs show 切换模型后端
echo 💡 也可 docker run ... cs ark 切换后自动进入 Claude
echo.
echo ── 准备进入 Claude Code ──
echo.

docker run -it --rm -v "%cd%:/app" super-claude:v1.1.2