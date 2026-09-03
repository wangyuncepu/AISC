"""F2 (D-10): the container-side host-MCP registration script.

T-F2c contract:
- URL set    -> claude .mcp.json gains mcpServers.aisc-host (merge, other
  servers survive) + codex config.toml gains the [mcp_servers.aisc-host]
  table (idempotent rewrite, other tables survive).
- URL unset  -> BOTH registrations are removed (stale endpoints 401).
- settings.json is never touched.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "container" / "lib" / "register_host_mcp.py"


def load_script():
    spec = importlib.util.spec_from_file_location("register_host_mcp", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RegisterHostMcpTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # The claude registration path is a fixed /root/app constant — point
        # it at the temp dir via chdir? No: the script hardcodes the path for
        # the container. For testability we patch the module constant.
        self.mod = load_script()

    def _run(self, url: str | None):
        os.environ["AISC_HOST_MCP_URL"] = url or ""
        os.environ["CODEX_CONFIG_DIR"] = str(self.dir / ".codex")
        (self.dir / ".codex").mkdir(exist_ok=True)
        # Redirect the claude path into the temp dir.
        claude_json = self.dir / "app" / ".mcp.json"
        claude_json.parent.mkdir(exist_ok=True)
        self.mod.CLAUDE_MCP_JSON = str(claude_json)
        return claude_json, self.dir / ".codex" / "config.toml"

    def test_register_merges_and_survives_other_servers(self):
        claude_json, codex_toml = self._run("http://host.docker.internal:3999/mcp?token=t1")
        claude_json.write_text(json.dumps({
            "mcpServers": {"user-own": {"type": "stdio", "command": "x"}},
        }), encoding="utf-8")
        codex_toml.write_text(
            'model = "glm-5.3"\n\n[mcp_servers.other]\nurl = "http://x"\n',
            encoding="utf-8",
        )
        self.assertEqual(self.mod.main(), 0)
        data = json.loads(claude_json.read_text(encoding="utf-8"))
        self.assertEqual(data["mcpServers"]["user-own"]["command"], "x")
        self.assertEqual(data["mcpServers"]["aisc-host"]["url"],
                         "http://host.docker.internal:3999/mcp?token=t1")
        toml = codex_toml.read_text(encoding="utf-8")
        self.assertIn('[mcp_servers.aisc-host]', toml)
        self.assertIn('url = "http://host.docker.internal:3999/mcp?token=t1"', toml)
        self.assertIn('[mcp_servers.other]', toml)  # others survive
        self.assertIn('model = "glm-5.3"', toml)

    def test_reregister_is_idempotent(self):
        claude_json, codex_toml = self._run("http://host.docker.internal:3999/mcp?token=t1")
        self.assertEqual(self.mod.main(), 0)
        self.assertEqual(self.mod.main(), 0)  # second run: same single table
        toml = codex_toml.read_text(encoding="utf-8")
        self.assertEqual(toml.count("[mcp_servers.aisc-host]"), 1)
        data = json.loads(claude_json.read_text(encoding="utf-8"))
        self.assertEqual(list(data["mcpServers"].keys()), ["aisc-host"])

    def test_unset_removes_both_registrations(self):
        claude_json, codex_toml = self._run("http://host.docker.internal:3999/mcp?token=t1")
        self.assertEqual(self.mod.main(), 0)
        claude_json2, codex_toml2 = self._run(None)
        self.assertEqual((claude_json, codex_toml), (claude_json2, codex_toml2))
        self.assertEqual(self.mod.main(), 0)
        # Feature off -> our registration is gone; the file disappears when
        # it holds nothing else.
        self.assertFalse(claude_json.exists())
        toml = codex_toml.read_text(encoding="utf-8")
        self.assertNotIn("aisc-host", toml)

    def test_unset_keeps_user_servers(self):
        claude_json, _ = self._run("http://host.docker.internal:3999/mcp?token=t1")
        claude_json.write_text(json.dumps({
            "mcpServers": {
                "user-own": {"type": "stdio", "command": "x"},
                "aisc-host": {"type": "http", "url": "http://x"},
            },
        }), encoding="utf-8")
        self.assertEqual(self.mod.main(), 0)
        claude_json2, _ = self._run(None)
        self.assertEqual(self.mod.main(), 0)
        data = json.loads(claude_json2.read_text(encoding="utf-8"))
        self.assertEqual(list(data.get("mcpServers", {}).keys()), ["user-own"])


if __name__ == "__main__":
    unittest.main()
