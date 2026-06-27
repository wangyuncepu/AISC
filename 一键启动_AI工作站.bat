@echo off
chcp 65001 >nul

echo.
echo ╔══════════════════════════════════════════╗
echo ║     🚀 Super Claude AI 工作站          ║
echo ║        v1.1.0 · 5 平台 15+ 模型       ║
echo ╚══════════════════════════════════════════╝
echo.
echo 📦 正在启动容器...
echo 💡 首次使用会弹出 claude-switch 菜单引导配置
echo 💡 配置过的 Key 会缓存到 .claude_keys，下次自动加载
echo.
echo ── 准备进入 Claude Code ──
echo.

docker run -it --rm -v "%cd%:/app" super-claude:v1