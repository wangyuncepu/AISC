"""Integration: aisc provider current (S0.4 DoD: 3 fixtures).

Skips without Docker + image + the aisc-provider-inspect script (S0.4+ image).
"""

import json
import subprocess
import unittest

from tests.integration.docker._session_helpers import (
    BaseSessionIntegration,
    docker_ready,
    integration_ready,
    script_present,
)

PROVIDER_READY = integration_ready() and script_present("aisc-provider-inspect")


@unittest.skipUnless(PROVIDER_READY,
                     "requires Docker + super-claude:latest with aisc-provider-inspect")
class TestProviderCurrentIntegration(BaseSessionIntegration):
    def _provider_current(self, agent):
        r = subprocess.run(
            [self.aisc, "provider", "current", "--runtime-id", self.runtime_id,
             "--agent", agent, "--workspace", self.workspace, "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"provider current {agent} failed: {r.stderr}"
        return json.loads(r.stdout)["data"]

    def _exec_py(self, script):
        r = subprocess.run(
            ["docker", "exec", self.container_name, "python3", "-c", script],
            capture_output=True, text=True, timeout=20,
        )
        assert r.returncode == 0, f"exec failed: {r.stderr}"

    def test_fresh_no_provider(self):
        self.start_runtime("project")
        claude = self._provider_current("claude")
        assert claude["route_mode"] == "cc-switch-proxy"
        assert claude["auth_status"] == "not_configured"
        codex = self._provider_current("codex")
        assert codex["provider_id"] == "codex-official"
        assert codex["route_mode"] == "official-direct"
        assert codex["auth_status"] == "login_required"

    def test_claude_proxy_configured(self):
        self.start_runtime("project")
        self._exec_py(
            "import sqlite3,json\n"
            "db='/root/app/.cc-switch/cc-switch.db'\n"
            "c=sqlite3.connect(db)\n"
            "c.execute(\"UPDATE providers SET is_current=0 WHERE app_type='claude'\")\n"
            "c.execute(\"UPDATE providers SET is_current=1 WHERE app_type='claude' AND id='deepseek'\")\n"
            "r=c.execute(\"SELECT settings_config FROM providers WHERE app_type='claude' AND id='deepseek'\").fetchone()\n"
            "sc=json.loads(r[0]); sc.setdefault('env',{})['ANTHROPIC_API_KEY']='sk-real-secret'\n"
            "c.execute(\"UPDATE providers SET settings_config=? WHERE app_type='claude' AND id='deepseek'\",(json.dumps(sc),))\n"
            "c.commit(); c.close()\n"
        )
        claude = self._provider_current("claude")
        assert claude["provider_id"] == "deepseek"
        assert claude["route_mode"] == "cc-switch-proxy"
        assert claude["auth_status"] == "configured"
        assert "sk-real-secret" not in json.dumps(claude)  # secret scan

    def test_codex_official_configured(self):
        self.start_runtime("project")
        subprocess.run(
            ["docker", "exec", self.container_name, "sh", "-c",
             "mkdir -p /root/app/.codex && echo '{}' > /root/app/.codex/auth.json"],
            capture_output=True, text=True, timeout=15,
        )
        codex = self._provider_current("codex")
        assert codex["provider_id"] == "codex-official"
        assert codex["route_mode"] == "official-direct"
        assert codex["auth_status"] == "configured"


if __name__ == "__main__":
    unittest.main()
