"""Workflow path-filter contract (06-implementation-plan.md §0.3 / A-INFRA-4).

Bundle/NSIS/workbench CI must trigger on frontend, package, Tauri and CLI
changes. Parse the workflow YAML and assert the required path filters, so a
missing `paths` entry fails the test instead of silently skipping CI.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

REQUIRED_PATHS = [
    "workbench/src/**",
    "workbench/package.json",
    "workbench/package-lock.json",
    "workbench/vite.config.*",
    "workbench/tsconfig*.json",
    "workbench/src-tauri/**",
    "src/aisc/**",
]

WORKFLOWS_REQUIRING_PATHS = {
    "bundle-linux-macos.yml",
    "nsis-installer.yml",
    "workbench-ci.yml",
}


def _triggers(data) -> dict:
    # PyYAML 1.1 parses the `on:` key as boolean True; accept both spellings.
    triggers = data.get("on", data.get(True, {}))
    if isinstance(triggers, str):  # legacy single-trigger shorthand
        return {"push": triggers}
    return triggers


def _push_paths(name: str) -> set[str]:
    path = WORKFLOW_DIR / name
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    push = _triggers(data).get("push", {})
    return set(push.get("paths", []))


@pytest.mark.parametrize("name", sorted(WORKFLOWS_REQUIRING_PATHS))
def test_push_path_filters_cover_required_paths(name):
    paths = _push_paths(name)
    missing = [p for p in REQUIRED_PATHS if p not in paths]
    assert not missing, f"{name} push.paths missing: {missing}"


@pytest.mark.parametrize("name", sorted(WORKFLOWS_REQUIRING_PATHS))
def test_workflow_has_required_triggers(name):
    path = WORKFLOW_DIR / name
    assert path.is_file(), f"workflow {name} missing"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = _triggers(data)
    assert "push" in triggers, f"{name} must have a push trigger"
    if name == "workbench-ci.yml":
        assert "pull_request" in triggers, "workbench-ci.yml must run on PRs"
