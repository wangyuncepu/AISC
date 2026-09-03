#!/usr/bin/env python3
"""F2 (D-10): register the host-tools MCP server with both agents.

Runs from the entrypoint on EVERY start (idempotent):
- ``AISC_HOST_MCP_URL`` set   -> write the registration (the URL carries the
  per-process token as a query param; both agents register a plain URL).
- ``AISC_HOST_MCP_URL`` unset -> REMOVE our registration (feature off, or a
  stale endpoint from a previous Workbench process whose token no longer
  matches — the server would 401 anyway).

Registration targets:
- claude: project-level ``/root/app/.mcp.json`` ``mcpServers.aisc-host``
  (``enableAllProjectMcpServers`` is on in the factory settings). Read-merge-
  write: any OTHER project MCP servers the user configured survive.
- codex: ``config.toml`` top-level ``[mcp_servers.aisc-host]`` table, spliced
  line-level (drop ours, re-append) — the same ownership pattern as
  ``model_catalog_json``. NEVER touches settings.json (provider switch
  replaces that file wholesale).

Never raises: failures print to stderr and exit non-zero so the entrypoint
can warn, but the container still starts.
"""
from __future__ import annotations

import json
import os
import re
import sys

SERVER_KEY = "aisc-host"
CLAUDE_MCP_JSON = "/root/app/.mcp.json"


def register_claude(url: str | None) -> None:
    data: dict = {}
    try:
        with open(CLAUDE_MCP_JSON, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    if url:
        servers[SERVER_KEY] = {"type": "http", "url": url}
    else:
        servers.pop(SERVER_KEY, None)
    if servers:
        data["mcpServers"] = servers
    else:
        data.pop("mcpServers", None)
    if data:
        tmp = CLAUDE_MCP_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, CLAUDE_MCP_JSON)
    elif os.path.exists(CLAUDE_MCP_JSON):
        os.remove(CLAUDE_MCP_JSON)


def register_codex(url: str | None) -> None:
    cfg_dir = os.environ.get("CODEX_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".codex"
    )
    path = os.path.join(cfg_dir, "config.toml")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        text = ""
    # Drop any previous table of ours (idempotent rewrite; other tables stay).
    table_re = re.compile(
        r"(?ms)^\[mcp_servers\.aisc-host\]\n.*?(?=^\[|\Z)"
    )
    text = table_re.sub("", text).rstrip("\n") + "\n"
    if url:
        text += (
            f"\n[mcp_servers.{SERVER_KEY}]\n"
            f'url = "{url}"\n'
        )
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def main() -> int:
    url = os.environ.get("AISC_HOST_MCP_URL", "").strip() or None
    try:
        register_claude(url)
    except Exception as exc:  # noqa: BLE001 — entrypoint warns, never blocks
        print(f"host-mcp claude registration failed: {exc}", file=sys.stderr)
        return 1
    try:
        register_codex(url)
    except Exception as exc:  # noqa: BLE001
        print(f"host-mcp codex registration failed: {exc}", file=sys.stderr)
        return 1
    if url:
        print(f"✅ host-tools MCP 已注册 ({SERVER_KEY})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
