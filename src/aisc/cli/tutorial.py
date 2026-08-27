"""v2.1.7 S6: interactive-bash tutorial (Gate-S6 / D10 decision).

The Workbench's bash sessions open as ``docker exec -it <name> bash``. To
make a bare ``help`` answer INSIDE that shell (without touching the image,
the user's workspace, or any persistent profile — A-21766), the session
argv is rewritten to::

    bash -c '<define help() + export -f it>; exec bash'

``export -f`` serializes the function into the environment; the exec'd
interactive bash re-imports it at startup. ``help`` with NO arguments prints
the tutorial; ``help foo`` delegates to the shell builtin so nothing else
changes (A-21765). Non-interactive shells never see any of this — the
injection rides ONLY the interactive session-open path.

The tutorial text lives here (content SSOT); the Workbench UI cards carry
their own short i18n summaries.
"""

from __future__ import annotations

_TUTORIAL = """\
╔══════════════ AISC Workbench 教学 ══════════════
║ 三、五分钟核心用法
║
║ [Claude Code]
║   claude              开始交互对话
║   claude -c           继续最近一次会话
║   claude -p "问题"     单次提问，直接返回答案
║   claude --resume     挑选历史会话恢复
║   会话内: /help 命令列表 · /clear 清空 · /compact 压缩上下文
║
║ [Codex]
║   codex               开始交互对话
║   codex e "任务"      单次执行任务
║   会话内: /help · /new 新会话 · Ctrl+C 中断
║
║ [Workbench]
║   左侧栏  文件/产物/服务 三个页签（顶部可搜索）
║   右上 ⓘ 运行时状态抽屉 · Ctrl+, 设置 · + 号新建页
║   关闭工作区 = 自动清理临时容器（数据不丢）
║
║ 互动练习（可选）：
║   1. claude -p "用一句话介绍你自己"     ← 单次问答，试试
║   2. 在 + ▾ 菜单打开 claude 页签，输入 /help 浏览命令
║   3. 左侧切到「产物」页签，点分组标题收拢/展开
║
║ 再次查看: help    退出教学: q
╚═══════════════════════════════════════════════"""

# Shell fragment executed via `bash -c`. NOTE: kept POSIX-simple on purpose —
# it runs before any profile, on the image's stock bash.
_SESSION_BASH_PRELUDE_TEMPLATE = """\
__aisc_tutorial() {
  cat <<'__AISC_TUTORIAL_EOF__'
__AISC_TUTORIAL_TEXT__
__AISC_TUTORIAL_EOF__
}
help() {
  if [ $# -eq 0 ]; then
    __aisc_tutorial
  else
    builtin help "$@"
  fi
}
export -f help __aisc_tutorial
exec bash
"""


def session_bash_prelude() -> str:
    """The ``bash -c`` script for interactive session opens (test seam)."""
    # Plain replace — .format would need every shell brace escaped.
    return _SESSION_BASH_PRELUDE_TEMPLATE.replace("__AISC_TUTORIAL_TEXT__", _TUTORIAL)
