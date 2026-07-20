"""Fake GitHub transport for deterministic, network-free testing.

Provides in-memory transport simulating GitHub API with realistic
mode/type support for object-type rejection tests.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass
class FakeGitHubTransport:
    """In-memory fake GitHub transport for testing.

    Configuration:
      - repos: dict of slug -> dict of commit_sha -> {path: bytes}
      - refs: dict of slug -> dict of ref_name -> commit_sha
      - error_hook: optional callable (url, method) -> Exception
      - entry_modes: dict of path -> mode string override (e.g. "100755")
      - entry_types: dict of path -> type string override (e.g. "commit")
    """

    repos: Dict[str, Dict[str, Dict[str, bytes]]] = field(default_factory=dict)
    refs: Dict[str, Dict[str, str]] = field(default_factory=dict)
    error_hook: Optional[Callable[[str, str], Optional[Exception]]] = None
    entry_modes: Dict[str, str] = field(default_factory=dict)
    entry_types: Dict[str, str] = field(default_factory=dict)
    _blob_cache: Dict[bytes, str] = field(default_factory=dict)

    def _blob_sha(self, content: bytes) -> str:
        if content not in self._blob_cache:
            self._blob_cache[content] = hashlib.sha256(content).hexdigest()
        return self._blob_cache[content]

    def add_repo(self, owner: str, repo: str, commit_sha: str,
                 files: Dict[str, bytes]) -> None:
        slug = f"{owner}/{repo}"
        self.repos.setdefault(slug, {})[commit_sha] = dict(files)

    def add_ref(self, owner: str, repo: str, ref: str, commit_sha: str) -> None:
        slug = f"{owner}/{repo}"
        self.refs.setdefault(slug, {})[ref] = commit_sha

    def get_files(self, owner: str, repo: str, commit_sha: str) -> Dict[str, bytes]:
        slug = f"{owner}/{repo}"
        return self.repos.get(slug, {}).get(commit_sha, {})

    # --- Protocol methods ---

    def get(self, url: str, *, headers=None, timeout=30.0):
        from aisc.adapters.github_client import GitHubResponse
        if self.error_hook:
            exc = self.error_hook(url, "get")
            if exc:
                raise exc
        return GitHubResponse(status=200, body=b"{}", url=url)

    def resolve_ref(self, owner: str, repo: str, ref: str) -> str:
        from aisc.adapters.github_client import GitHubError
        if self.error_hook:
            exc = self.error_hook(f"resolve:{owner}/{repo}/{ref}", "resolve_ref")
            if exc:
                raise exc

        if _SHA40_RE.match(ref):
            slug = f"{owner}/{repo}"
            if ref in self.repos.get(slug, {}):
                return ref
            raise GitHubError(
                f"Commit {ref[:7]} not found",
                error_code="GITHUB_ERR_NOT_FOUND",
                status=404,
            )

        slug = f"{owner}/{repo}"
        ref_map = self.refs.get(slug, {})
        for ref_prefix in [f"heads/{ref}", f"tags/{ref}", ref]:
            if ref_prefix in ref_map:
                return ref_map[ref_prefix]

        raise GitHubError(
            f"Ref {ref!r} not found in {owner}/{repo}",
            error_code="GITHUB_ERR_NOT_FOUND",
            status=404,
        )

    def get_tree(self, owner: str, repo: str, commit_sha: str,
                 directory: str) -> List[Dict[str, Any]]:
        from aisc.adapters.github_client import GitHubError
        if self.error_hook:
            exc = self.error_hook(
                f"tree:{owner}/{repo}/{commit_sha}/{directory}", "get_tree"
            )
            if exc:
                raise exc

        files = self.get_files(owner, repo, commit_sha)
        if not files:
            raise GitHubError(
                f"No files at commit {commit_sha[:7]}",
                error_code="GITHUB_ERR_NOT_FOUND",
                status=404,
            )

        dir_prefix = directory.rstrip("/") + "/" if directory else ""
        entries: List[Dict[str, Any]] = []
        for rel_path, content in sorted(files.items()):
            if directory and not rel_path.startswith(dir_prefix):
                continue
            mode = self.entry_modes.get(rel_path, "100644")
            etype = self.entry_types.get(rel_path, "blob")
            entries.append({
                "path": rel_path,
                "mode": mode,
                "type": etype,
                "sha": self._blob_sha(content) if etype == "blob" else "0" * 40,
                "size": len(content) if etype == "blob" else 0,
            })

        if not entries:
            raise GitHubError(
                f"Directory {directory!r} not found",
                error_code="GITHUB_ERR_NOT_FOUND",
                status=404,
            )

        return entries

    def get_blob(self, owner: str, repo: str, blob_sha: str) -> bytes:
        from aisc.adapters.github_client import GitHubError
        if self.error_hook:
            exc = self.error_hook(
                f"blob:{owner}/{repo}/{blob_sha}", "get_blob"
            )
            if exc:
                raise exc

        slug = f"{owner}/{repo}"
        for commit_sha, file_set in self.repos.get(slug, {}).items():
            for rel_path, content in file_set.items():
                if self._blob_sha(content) == blob_sha:
                    return content

        raise GitHubError(
            f"Blob {blob_sha[:7]} not found",
            error_code="GITHUB_ERR_NOT_FOUND",
            status=404,
        )

    def get_repo_root_files(self, owner: str, repo: str,
                            commit_sha: str) -> List[Dict[str, Any]]:
        return []


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def make_skill_fixture(
    name: str = "test-skill",
    skill_md_content: Optional[str] = None,
    extra_files: Optional[Dict[str, object]] = None,
    entry_modes: Optional[Dict[str, str]] = None,
    entry_types: Optional[Dict[str, str]] = None,
) -> Tuple[FakeGitHubTransport, str, str]:
    """Create a minimal skill fixture with fake transport.

    Returns (transport, commit_sha, owner/repo_slug).
    """
    owner = "test-owner"
    repo = "test-repo"
    commit_sha = "a" * 40

    if skill_md_content is None:
        skill_md_content = f"""---
name: {name}
description: Test skill
---

# {name}

This is a test skill.
"""

    files: Dict[str, bytes] = {}
    directory = f"skills/{name}"
    files[f"{directory}/SKILL.md"] = skill_md_content.encode("utf-8")

    if extra_files:
        for path, content in extra_files.items():
            if isinstance(content, bytes):
                files[f"{directory}/{path}"] = content
            else:
                files[f"{directory}/{path}"] = str(content).encode("utf-8")

    transport = FakeGitHubTransport()
    transport.add_repo(owner, repo, commit_sha, files)
    transport.add_ref(owner, repo, "main", commit_sha)

    # Apply mode/type overrides for the full repo paths
    if entry_modes:
        for path, mode in entry_modes.items():
            transport.entry_modes[f"{directory}/{path}"] = mode
    if entry_types:
        for path, etype in entry_types.items():
            transport.entry_types[f"{directory}/{path}"] = etype

    return transport, commit_sha, f"{owner}/{repo}"


def make_grill_me_fixture() -> Tuple[FakeGitHubTransport, str, str, str]:
    """Create the grill-me example fixture.

    Returns (transport, commit_sha, slug, directory).
    """
    owner = "mattpocock"
    repo = "skills"
    commit_sha = "b" * 40
    directory = "skills/productivity/grill-me"

    skill_md = """---
name: grill-me
description: Get grilled on any topic with intense questioning
---

# Grill Me

Use /grilling to provide the intense questioning.

## Dependencies

This skill requires the grilling skill.
"""

    agents_yaml = """name: grill-me-agent
tools:
  - Bash
  - Read
model: claude-sonnet-4-5
"""

    files: Dict[str, bytes] = {
        f"{directory}/SKILL.md": skill_md.encode("utf-8"),
        f"{directory}/agents/openai.yaml": agents_yaml.encode("utf-8"),
    }

    transport = FakeGitHubTransport()
    transport.add_repo(owner, repo, commit_sha, files)
    transport.add_ref(owner, repo, "main", commit_sha)

    return transport, commit_sha, f"{owner}/{repo}", directory
