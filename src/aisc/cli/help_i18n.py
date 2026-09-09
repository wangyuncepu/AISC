"""Help-text localization: follow the OS locale (manual test ask 2026-09-09).

The parser keeps English help strings as the single source of truth —
zero per-flag maintenance, zero risk to non-Chinese environments. When the
user's locale is Chinese, we translate at the OUTPUT layer by patching
argparse: builtin wording (``usage:``/``options``/error phrasing) via the
module-level ``_`` hook, and per-argument help via a wrapper around
``HelpFormatter._expand_help`` (exact full-string match — a miss keeps
English, nothing is partially rewritten).

Encoding safety: the translated text is plain Han Chinese + ASCII, which
zh-CN Windows GBK consoles encode fine; the CLI's existing
``sys.stdout.reconfigure(errors="replace")`` remains the last-resort guard
for anything exotic (emoji degrade to ``?`` instead of crashing).
"""

from __future__ import annotations

import os
from typing import Callable, Dict, Optional

# ---------------------------------------------------------------------------
# Locale detection
# ---------------------------------------------------------------------------

def is_zh_locale() -> bool:
    """True when the OS/user locale is Chinese (zh*, e.g. zh_CN.UTF-8)."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = os.environ.get(var)
        if val and val.split(".", 1)[0].split("@", 1)[0].lower().startswith("zh"):
            return True
    # Windows often has none of the POSIX vars set — ask the CRT.
    try:
        import locale as _locale

        pref = _locale.getdefaultlocale()[0]
        if pref and pref.lower().startswith("zh"):
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Dictionaries (exact full-string keys; miss ⇒ English passes through)
# ---------------------------------------------------------------------------

# argparse builtin wording and error templates
_BUILTIN: Dict[str, str] = {
    "usage: ": "用法: ",
    "options": "选项",
    "optional arguments": "选项",
    "positional arguments": "位置参数",
    "show this help message and exit": "显示此帮助信息并退出",
    "unrecognized arguments: %s": "无法识别的参数: %s",
    "invalid choice: %r (choose from %s)": "无效选择: %r（可选: %s）",
    "the following arguments are required: %s": "缺少必填参数: %s",
    "expected one argument": "缺少参数值",
    "expected at least one argument": "至少需要一个参数",
    "not allowed with argument %s": "不能与参数 %s 同时使用",
    "argument %s: %s": "参数 %s: %s",
}

# per-argument help strings (exact match against the expanded help text)
HELP_ZH: Dict[str, str] = {
    # --- global flags ---
    "Output format (default: text)": "输出格式（默认: text）",
    "Disable ANSI color output": "禁用 ANSI 彩色输出",
    "Path to AISC repository root": "AISC 仓库根目录路径",
    "Enable JSONL event stream output (build/run commands)":
        "启用 JSONL 事件流输出（build/run 命令）",
    # --- version / doctor / serve / build ---
    "Show version information": "显示版本信息",
    "Run environment diagnostics": "运行环境诊断",
    "Serve remote callers: newline-delimited JSON frames on stdio":
        "服务远端调用方：stdio 换行分隔 JSON 帧",
    "speak the frame protocol on stdin/stdout (the only transport in this version)":
        "在 stdin/stdout 上讲帧协议（本版本唯一传输）",
    "Build Docker image": "构建 Docker 镜像",
    "Image tag (default: super-claude:latest)": "镜像标签（默认: super-claude:latest）",
    "Disable Docker build cache": "禁用 Docker 构建缓存",
    "Always pull the base image": "始终拉取基础镜像",
    "Plan the build without executing": "只规划构建不执行",
    "cc-switch version: 'latest' (default) or vX.Y.Z ":
        "cc-switch 版本: 'latest'（默认）或 vX.Y.Z ",
    "cc-switch release channel (default: stable; ":
        "cc-switch 发布通道（默认: stable; ",
    "Build from a resolver manifest file (offline / ":
        "从解析清单文件构建（离线 / ",
    "Fail the build when the cc-switch version cannot be ":
        "cc-switch 版本无法确定时使构建失败 ",
    # --- run ---
    "Activate a workspace (detached container)": "激活工作区（detached 容器）",
    "Workspace directory to activate (e.g. ./ or /home/user/proj)":
        "要激活的工作区目录（如 ./ 或 /home/user/proj）",
    "Re-activate from history (see `aisc runs`); explicit flags win":
        "从历史恢复（见 `aisc runs`）；显式参数优先",
    "Docker image (default: super-claude:latest)":
        "Docker 镜像（默认: super-claude:latest）",
    "Workspace alias — also the container name prefix; ":
        "工作区别名—兼作容器名前缀; ",
    "Network mode: direct or proxy (default: direct)":
        "网络模式: direct 或 proxy（默认: direct）",
    "Compatibility alias for --network proxy (prefer --network proxy)":
        "--network proxy 的兼容别名（建议直接用 --network proxy）",
    "Plan the activation without executing": "只规划激活不执行",
    "Container label for multi-container addressing (optional)":
        "多容器寻址用标签（可选）",
    # --- agent sugar (f-strings expand to per-agent text) ---
    "Open claude in the active workspace": "在活跃工作区容器内打开 claude",
    "Open codex in the active workspace": "在活跃工作区容器内打开 codex",
    "Target a registered workspace instead of the active one":
        "指定已注册工作区（而非当前活跃工作区）",
    "Container name (overrides registry discovery)": "容器名（覆盖注册表发现）",
    "Args passed to claude verbatim (use -- first: aisc claude -- -c)":
        "原样透传给 claude 的参数（-- 开头: aisc claude -- -c）",
    "Args passed to codex verbatim (use -- first: aisc codex -- -c)":
        "原样透传给 codex 的参数（-- 开头: aisc codex -- -c）",
    # --- runs / workspaces ---
    "Activation history (aisc run records)": "激活历史（aisc run 记录）",
    "Manage running CLI workspaces": "管理运行中的 CLI 工作区",
    "Stop & remove every RUNNING CLI-owned workspace":
        "停删全部运行中的 CLI 工作区",
    # --- config ---
    "Config management": "配置管理",
    "Validate config files": "校验配置文件",
    "Explicit user config file path": "显式用户配置文件路径",
    "Workspace root path": "工作区根路径",
    "Show effective config": "显示生效配置",
    "Alias for 'config effective' (compatibility name)":
        "'config effective' 的兼容别名",
    # --- profile ---
    "Profile management": "Profile 管理",
    "List available profiles": "列出可用 profile",
    "Show profile details": "显示 profile 详情",
    "Profile name (default: safe)": "profile 名（默认: safe）",
    # --- status / stop / restart / shell / switch ---
    "Show container status": "显示容器状态",
    "Target container by label": "按标签指定容器",
    "Stop & remove the active workspace container": "停删当前活跃工作区容器",
    "Stop & remove EVERY CLI-owned container (Workbench runtimes untouched)":
        "停删全部 CLI 容器（Workbench 运行时不碰）",
    "Restart the container": "重启容器",
    "Open a bash shell in the container": "在容器内打开 bash shell",
    "One-shot command in the container (use -- first: aisc shell -- ls -la)":
        "容器内单发命令（-- 开头: aisc shell -- ls -la）",
    "Switch AI provider in the container": "切换容器内 AI provider",
    "Provider id or alias for quick switch (e.g. deepseek)":
        "快速切换用 provider id 或别名（如 deepseek）",
    # --- provider ---
    "Manage AI provider configuration": "管理 AI provider 配置",
    "Open the secure interactive editor for a provider":
        "打开 provider 的安全交互编辑器",
    "Provider ID (e.g., deepseek, zhipu, kimi)": "provider ID（如 deepseek、zhipu、kimi）",
    "Target agent (default: claude)": "目标 agent（默认: claude）",
    "Show the current provider status for an agent (Workbench)":
        "显示 agent 当前 provider 状态（Workbench 用）",
    "Runtime ID (UUID v4)": "运行时 ID（UUID v4）",
    "Agent (claude|codex)": "agent（claude|codex）",
    "Workspace path (default: current directory)": "工作区路径（默认: 当前目录）",
    # --- cc-switch ---
    "Manage cc-switch providers (list/add/edit/delete)":
        "管理 cc-switch provider（增删改查）",
    "List providers (secret-free snapshot)": "列出 provider（无密钥快照）",
    "Add a provider (request JSON on stdin)": "添加 provider（stdin 收 JSON 请求）",
    "simple = preset provider + api key; custom = full ":
        "simple = 预置 provider + api key; custom = 完整 ",
    "Preset provider id (simple mode, e.g. deepseek)":
        "预置 provider id（simple 模式，如 deepseek）",
    "Provider id to create (default: preset id / name slug)":
        "要创建的 provider id（默认: 预置 id / 名字 slug）",
    "Edit a provider (patch JSON on stdin)": "编辑 provider（stdin 收 patch JSON）",
    "Provider ID to edit": "要编辑的 provider ID",
    "Activate a provider (make it current)": "激活 provider（设为当前）",
    "Provider ID to activate": "要激活的 provider ID",
    "Delete a provider": "删除 provider",
    "Provider ID to delete": "要删除的 provider ID",
    "Required confirmation flag": "必需的确认开关",
    "Fetch the remote model list for a provider": "拉取 provider 的远端模型列表",
    "Provider ID to query": "要查询的 provider ID",
    # --- network ---
    "Network management (mihomo subscription for container TUN)":
        "网络管理（容器 TUN 的 mihomo 订阅）",
    "Manage the proxy subscription (IDEA-2)": "管理代理订阅（IDEA-2）",
    "Import a subscription (URL on stdin — a credential, ":
        "导入订阅（stdin 收 URL—凭据, ",
    "Import manually supplied subscription content ":
        "导入手动提供的订阅内容 ",
    "Re-fetch the stored subscription URL": "重新拉取已存的订阅 URL",
    "Persist a Rust-side download ({url, content_b64, userinfo} JSON ":
        "持久化 Rust 侧下载（{url, content_b64, userinfo} JSON ",
    "Show subscription status (secret-free)": "显示订阅状态（无密钥）",
    "Remove the stored subscription": "删除已存的订阅",
    # --- usage ---
    "Provider token usage statistics (all workspaces)":
        "provider token 用量统计（全部工作区）",
    "Subscription status + per-provider token usage":
        "订阅状态 + 各 provider token 用量",
    "Time window (default: 7d)": "时间窗（默认: 7d）",
    "Limit to one workspace path (default: all)": "限定单个工作区（默认: 全部）",
    # --- logs ---
    "Lifecycle event log (full-flow debugging timeline)":
        "生命周期事件日志（全流程调试时间线）",
    "Show recent lifecycle events (secret-free by construction)":
        "显示近期生命周期事件（构造上无密钥）",
    "Number of recent events (default: 200; current file only)":
        "近期事件条数（默认: 200; 仅当前文件）",
    "Filter by writer (default: all)": "按写入方过滤（默认: 全部）",
    "Print the log file path (for scripts and the Workbench)":
        "打印日志文件路径（脚本与 Workbench 用）",
    # --- ps / maintenance ---
    "List all registered containers": "列出全部已注册容器",
    "Installer-facing Docker lifecycle ops": "面向安装器的 Docker 生命周期操作",
    "Read-only ownership classification": "只读所有权分类",
    "Install context drives legacy-image evidence rules":
        "安装上下文决定旧镜像证据规则",
    "Upgrade-captured old image ID (temporary evidence; repeatable)":
        "升级时捕获的旧镜像 ID（临时证据; 可重复）",
    "Remove owned/legacy containers+images": "清除自有/旧版容器与镜像",
    "No-cache rebuild with old-ID handoff": "无缓存重建（旧 ID 交接）",
    "Bundle root (contains Dockerfile)": "bundle 根目录（含 Dockerfile）",
    "Read-only docker system df summary": "只读 docker system df 摘要",
    "Prune builder cache + dangling images (until-filtered)":
        "清理构建缓存与悬空镜像（until 过滤）",
    "Only clear cache entries older than this (default 24)":
        "仅清理超过此时长的缓存（默认 24）",
    # --- runtime ---
    "Runtime control plane (Workbench Phase 0)": "运行时控制面（Workbench Phase 0）",
    "Preflight checks for runtime start": "运行时启动前置检查",
    "Runtime ID (UUID v4, provided by Workbench)":
        "运行时 ID（UUID v4, Workbench 提供）",
    "Network mode (default: direct)": "网络模式（默认: direct）",
    "Runtime scope (default: project)": "运行时作用域（默认: project）",
    "Owner identifier (default: workbench)": "所有者标识（默认: workbench）",
    "Start a Workbench runtime": "启动 Workbench 运行时",
    "Host path to mihomo config.yaml to mount for --network proxy ":
        "--network proxy 挂载的宿主 mihomo config.yaml 路径 ",
    "F2 (D-10): full host-tools MCP URL incl. token query; forwarded ":
        "F2 (D-10): 宿主工具 MCP 完整 URL（含 token query）; 转发 ",
    "PERF P8 (D-13): container memory limit (docker --memory, e.g. 3g)":
        "PERF P8 (D-13): 容器内存上限（docker --memory, 如 3g）",
    "PERF P8 (D-13): container CPU limit (docker --cpus, e.g. 1.5)":
        "PERF P8 (D-13): 容器 CPU 上限（docker --cpus, 如 1.5）",
    "List runtimes with Docker reconciliation": "列出运行时（含 Docker 对账）",
    "Filter by owner (e.g. workbench)": "按所有者过滤（如 workbench）",
    "Show a single runtime": "显示单个运行时",
    "Snapshot + services in one call (poll path)": "快照 + 服务一次拿（轮询路径）",
    "Stop a runtime (keep container + metadata)": "停止运行时（保留容器与元数据）",
    "docker stop grace period in seconds (1..600; default 10)":
        "docker stop 宽限秒数（1..600; 默认 10）",
    "Restart a runtime with original config": "按原配置重启运行时",
    "Remove a runtime (container + registry)": "移除运行时（容器 + 注册表）",
    "Remove even if the runtime is running": "运行中亦强制移除",
    "Web service gateway info + registered services": "Web 服务网关信息 + 已注册服务",
    "List registered services (default)": "列出已注册服务（默认）",
    "Register a service port (ops/test entry)": "注册服务端口（运维/测试入口）",
    "Container service port (1024..65535)": "容器内服务端口（1024..65535）",
    "Display label (safe short text)": "显示名（安全短文本）",
    "Unregister a service port": "注销服务端口",
    "Classify + auto-recycle stale runtimes for a workspace":
        "分类并自动回收工作区的陈旧运行时",
    "This Workbench instance's UUID v4": "本 Workbench 实例的 UUID v4",
    "Optional cross-check: expected sha256 workspace key":
        "可选交叉校验: 期望的 sha256 工作区键",
    "Workspace lease claim/heartbeat/release/inspect":
        "工作区租约（领取/心跳/释放/查看）",
    "Lease ID (heartbeat/release match guard)": "租约 ID（心跳/释放匹配保护）",
    # --- session ---
    "Session data plane (Workbench Phase 0)": "会话数据面（Workbench Phase 0）",
    "Open an interactive agent session": "打开交互 agent 会话",
    "Session ID (UUID v4)": "会话 ID（UUID v4）",
    "Agent type (claude|codex|bash|cc-switch)": "agent 类型（claude|codex|bash|cc-switch）",
    "Provider conversation ID to resume (claude|codex only, v2.1.8 T4)":
        "要续接的 provider 会话 ID（仅 claude|codex, v2.1.8 T4）",
    "List sessions in a runtime": "列出运行时内会话",
    "Terminate a session": "终止会话",
    "Grace period in seconds before SIGKILL (default: 5.0)":
        "SIGKILL 前宽限秒数（默认: 5.0）",
    # --- conversation ---
    "Agent conversation discovery (Workbench v2.1.8)":
        "agent 会话发现（Workbench v2.1.8）",
    "List agent history conversations in a workspace":
        "列出工作区 agent 历史会话",
    "Validate a conversation is resumable (captured, JSON)":
        "校验会话可续接（captured, JSON）",
    "Provider-native conversation ID (UUID)": "provider 原生会话 ID（UUID）",
    "Agent type (claude|codex)": "agent 类型（claude|codex）",
    "Delete a conversation's session file": "删除会话的 session 文件",
    "Set a conversation's display title": "设置会话显示标题",
    "New display title (sanitized, ≤80 chars)":
        "新显示标题（净化, ≤80 字符）",
    # --- artifact ---
    "Agent Artifact fact protocol (Stage 3)": "agent 产物事实协议（Stage 3）",
    "Record an agent artifact fact": "记录 agent 产物事实",
    "Runtime ID (UUID v4; default: env AISC_RUNTIME_ID)":
        "运行时 ID（UUID v4; 默认: 环境变量 AISC_RUNTIME_ID）",
    "Session ID (UUID v4; default: env AISC_TERMINAL_SESSION_ID)":
        "会话 ID（UUID v4; 默认: 环境变量 AISC_TERMINAL_SESSION_ID）",
    "Producer agent (default: env AISC_AGENT)":
        "产出 agent（默认: 环境变量 AISC_AGENT）",
    "Workspace-relative path of the artifact": "产物的 workspace 相对路径",
    "media type, e.g. text/markdown": "媒体类型, 如 text/markdown",
    "Human label (<=256 chars)": "人类可读标签（<=256 字符）",
    "previous relative path (required for renamed)": "原相对路径（renamed 时必填）",
    "List artifact records": "列出产物记录",
    "Filter by session id": "按会话 id 过滤",
    "Filter by kind": "按 kind 过滤",
    "Inspect one artifact by id": "按 id 查看单个产物",
    "Artifact ID (UUID)": "产物 ID（UUID）",
    "Remove a session's registry": "清除某会话的注册数据",
    # --- data-root ---
    "Data root diagnostics and legacy migration": "数据根诊断与旧布局迁移",
    "Resolve + legacy findings + manifest state": "解析 + 旧布局发现 + 清单状态",
    "Migrate legacy layout into the data root": "旧布局迁入数据根",
    "Report the plan without touching anything": "只报告计划不做改动",
    "Execute the migration (default when --dry-run is absent)":
        "执行迁移（无 --dry-run 时默认）",
    "Move unknown files to the migration quarantine ":
        "未知文件移入迁移隔离区 ",
    "Undo one migration via its manifest": "按清单回滚一次迁移",
    "Manifest path (default: this workspace's manifest)":
        "清单路径（默认: 本工作区清单）",
}


# ---------------------------------------------------------------------------
# Installation (output-layer patches; restore returned for tests)
# ---------------------------------------------------------------------------

_active_restore: Optional[Callable[[], None]] = None


def install(force: bool = False) -> Optional[Callable[[], None]]:
    """Patch argparse for Chinese help output when the locale says so.

    Returns a restore callable (tests), or None when nothing was installed
    (non-Chinese locale, or already active — the patch is process-global,
    e.g. a prior main() on a zh locale). Idempotent.
    """
    if not force and not is_zh_locale():
        return None

    import argparse

    if getattr(argparse.HelpFormatter._expand_help, "_aisc_zh", False):
        return None  # already installed

    saved_gettext = argparse._
    saved_expand = argparse.HelpFormatter._expand_help

    def _zh_builtin(s: str) -> str:
        return _BUILTIN.get(s, saved_gettext(s))

    def _expand_zh(self, action):  # type: ignore[no-untyped-def]
        text = saved_expand(self, action)
        return HELP_ZH.get(text) or _BUILTIN.get(text, text)

    _expand_zh._aisc_zh = True  # type: ignore[attr-defined]

    argparse._ = _zh_builtin
    argparse.HelpFormatter._expand_help = _expand_zh

    def restore() -> None:
        argparse._ = saved_gettext
        argparse.HelpFormatter._expand_help = saved_expand

    global _active_restore
    _active_restore = restore
    return restore


def uninstall() -> None:
    """Tear down an active install (idempotent; test hygiene)."""
    global _active_restore
    if _active_restore is not None:
        _active_restore()
        _active_restore = None


def maybe_install() -> None:
    """Convenience entry for main(): locale check inside, never raises."""
    try:
        install()
    except Exception:
        pass  # localization is cosmetic — never take the CLI down
