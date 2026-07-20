"""GitHub HTTP client — injectable transport for skill fetching.

All network access goes through ``GitHubTransport``.  Production
implementation uses stdlib ``urllib`` with GitHub REST API.

Tests inject a ``FakeGitHubTransport`` for deterministic,
network-free execution.

Token handling:
- Optional token from environment ``GITHUB_TOKEN`` only (never argv/log/lock).
- Token is attached as ``Authorization: Bearer <token>`` header.
- Token value is never recorded in manifests, locks, logs, or structured results.
- User-Agent header is explicit and identifiable.
- Redirect host allowlist restricts redirects to ``github.com`` and
  ``raw.githubusercontent.com``.
- Rate-limit and error classification returns structured error info.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple
from urllib.parse import urljoin, urlparse

from aisc.domain.skill_models import ParsedGitHubURL


# ---------------------------------------------------------------------------
# Transport protocol — injectable
# ---------------------------------------------------------------------------


@dataclass
class GitHubResponse:
    """Structured response from GitHub transport."""

    status: int
    body: bytes
    headers: Dict[str, str] = field(default_factory=dict)
    url: str = ""


class GitHubTransport(Protocol):
    """Protocol for GitHub HTTP access.

    Inject a real or fake implementation.
    """

    def get(self, url: str, *, headers: Optional[Dict[str, str]] = None,
            timeout: float = 30.0) -> GitHubResponse:
        """Perform a GET request.  Returns ``GitHubResponse`` or raises ``GitHubError``."""
        ...

    def resolve_ref(self, owner: str, repo: str, ref: str) -> str:
        """Resolve a mutable ref (branch/tag) to a full 40-char commit SHA.

        Raises ``GitHubError`` if the ref cannot be resolved.
        """
        ...

    def get_tree(self, owner: str, repo: str, commit_sha: str,
                 directory: str) -> List[Dict[str, Any]]:
        """Fetch the complete tree listing for *directory* at *commit_sha*.

        Returns list of tree entries (dicts with path, mode, type, sha, size).
        Raises ``GitHubError`` on failure.
        """
        ...

    def get_blob(self, owner: str, repo: str, blob_sha: str) -> bytes:
        """Fetch a blob by its SHA.

        Raises ``GitHubError`` on failure.
        """
        ...
# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


@dataclass
class GitHubError(Exception):
    """Structured GitHub client error."""

    message: str
    status: int = 0
    error_code: str = "GITHUB_ERR_GENERAL"
    url: str = ""
    retry_after: Optional[float] = None  # seconds from rate-limit headers


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_REDIRECT_HOSTS = frozenset({
    "github.com",
    "raw.githubusercontent.com",
    "api.github.com",
    "objects.githubusercontent.com",
    "codeload.github.com",
})

_USER_AGENT = "AISC-skill-bundle-importer/2.0 (Python)"

_GITHUB_API_BASE = "https://api.github.com"

# ---------------------------------------------------------------------------
# Production transport — urllib-based
# ---------------------------------------------------------------------------


class RealGitHubTransport:
    """Production GitHub transport using stdlib ``urllib``.

    Token from environment ``GITHUB_TOKEN`` only.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        user_agent: str = _USER_AGENT,
        connect_timeout: float = 15.0,
        read_timeout: float = 30.0,
    ) -> None:
        # Token: from parameter, then GITHUB_TOKEN env, then None
        if token is None:
            import os
            token = os.environ.get("GITHUB_TOKEN", "")
        self._token: str = token or ""
        self._user_agent = user_agent
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout

    def _build_request(self, url: str, *, headers: Optional[Dict[str, str]] = None,
                       method: str = "GET", data: Optional[bytes] = None,
                       accept: str = "application/vnd.github+json") -> urllib.request.Request:
        """Build a urllib Request with standard headers."""
        req_headers: Dict[str, str] = {
            "User-Agent": self._user_agent,
            "Accept": accept,
        }
        if self._token:
            req_headers["Authorization"] = f"Bearer {self._token}"
        if headers:
            req_headers.update(headers)
        return urllib.request.Request(url, data=data, headers=req_headers, method=method)

    def _do_request(self, url: str, *, headers: Optional[Dict[str, str]] = None,
                    timeout: float = 30.0, follow_redirects: bool = True,
                    accept: str = "application/vnd.github+json") -> GitHubResponse:
        """Perform a request with redirect host allowlisting."""
        req = self._build_request(url, headers=headers, accept=accept)

        try:
            # Create a redirect-aware opener
            from urllib.request import HTTPRedirectHandler, build_opener

            class _AllowedRedirectHandler(HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    parsed = urlparse(newurl)
                    host = parsed.hostname or ""
                    if host.lower() not in _ALLOWED_REDIRECT_HOSTS:
                        raise GitHubError(
                            f"Redirect to unauthorized host: {host}",
                            error_code="GITHUB_ERR_REDIRECT_DENIED",
                            url=url,
                        )
                    # Strip Authorization for cross-origin redirects
                    new_req = urllib.request.Request(
                        newurl,
                        headers={k: v for k, v in req.headers.items()
                                 if k != "Authorization"},
                        method=req.method,
                    )
                    return new_req

            opener = build_opener(_AllowedRedirectHandler())

            with opener.open(req, timeout=timeout) as resp:
                body = resp.read()
                resp_headers = dict(resp.headers.items())
                return GitHubResponse(
                    status=resp.status,
                    body=body,
                    headers=resp_headers,
                    url=resp.url or url,
                )

        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:
                pass

            error_code = "GITHUB_ERR_HTTP"
            retry_after = None

            if exc.code == 403:
                remaining = exc.headers.get("X-RateLimit-Remaining", "1")
                if remaining == "0":
                    error_code = "GITHUB_ERR_RATE_LIMITED"
                    reset_ts = exc.headers.get("X-RateLimit-Reset", "0")
                    try:
                        retry_after = max(0.0, float(reset_ts) - time.time())
                    except (ValueError, TypeError):
                        retry_after = None
            elif exc.code == 404:
                error_code = "GITHUB_ERR_NOT_FOUND"
            elif exc.code == 401:
                error_code = "GITHUB_ERR_UNAUTHORIZED"

            raise GitHubError(
                f"HTTP {exc.code} for {url}: {_body_summary(body)}",
                status=exc.code,
                error_code=error_code,
                url=url,
                retry_after=retry_after,
            ) from exc

        except urllib.error.URLError as exc:
            raise GitHubError(
                f"Connection error for {url}: {exc.reason}",
                error_code="GITHUB_ERR_CONNECTION",
                url=url,
            ) from exc

        except OSError as exc:
            raise GitHubError(
                f"OS error for {url}: {exc}",
                error_code="GITHUB_ERR_CONNECTION",
                url=url,
            ) from exc

    def get(self, url: str, *, headers: Optional[Dict[str, str]] = None,
            timeout: float = 30.0) -> GitHubResponse:
        return self._do_request(url, headers=headers, timeout=timeout)

    # -- Ref resolution --

    def resolve_ref(self, owner: str, repo: str, ref: str) -> str:
        """Resolve a branch/tag/commit ref to a full 40-char commit SHA.

        - Full 40-char SHA: verified via GET git/commits/<sha>.
        - Mutable ref: queries heads/<ref> and tags/<ref> independently.
          Branch: verify object is commit via commit endpoint.
          Tag: lightweight tags point directly to commit; annotated tags
          are peeled recursively (max depth 8) until commit found.
          Ambiguity (both branch and tag exist) raises GITHUB_ERR_AMBIGUOUS_REF.
        """
        from urllib.parse import quote
        from aisc.domain.skill_models import _SHA40_RE

        _enc = lambda s: quote(s, safe="")

        # --- Full SHA ---
        if _SHA40_RE.match(ref):
            url = f"{_GITHUB_API_BASE}/repos/{_enc(owner)}/{_enc(repo)}/git/commits/{_enc(ref)}"
            resp = self.get(url, timeout=self._read_timeout)
            if resp.status != 200:
                raise GitHubError(
                    f"Commit {ref[:7]} not found in {owner}/{repo}",
                    error_code="GITHUB_ERR_NOT_FOUND", status=404, url=url,
                )
            data = json.loads(resp.body.decode("utf-8"))
            returned_sha = data.get("sha", "")
            if not _SHA40_RE.match(returned_sha):
                raise GitHubError(
                    f"Commit endpoint returned non-SHA for {ref[:7]}",
                    error_code="GITHUB_ERR_UNEXPECTED", url=url,
                )
            if returned_sha.lower() != ref.lower():
                raise GitHubError(
                    f"Returned SHA {returned_sha[:7]} does not match requested {ref[:7]}",
                    error_code="GITHUB_ERR_UNEXPECTED", url=url,
                )
            return returned_sha.lower()

        # --- Mutable ref: query heads and tags independently ---
        head_url = f"{_GITHUB_API_BASE}/repos/{_enc(owner)}/{_enc(repo)}/git/ref/heads/{_enc(ref)}"
        tag_url  = f"{_GITHUB_API_BASE}/repos/{_enc(owner)}/{_enc(repo)}/git/ref/tags/{_enc(ref)}"

        head_data: Optional[dict] = None
        tag_data: Optional[dict] = None

        try:
            resp = self.get(head_url, timeout=self._read_timeout)
            if resp.status == 200:
                head_data = json.loads(resp.body.decode("utf-8"))
        except GitHubError as exc:
            if exc.status != 404:
                raise

        try:
            resp = self.get(tag_url, timeout=self._read_timeout)
            if resp.status == 200:
                tag_data = json.loads(resp.body.decode("utf-8"))
        except GitHubError as exc:
            if exc.status != 404:
                raise

        if head_data is not None and tag_data is not None:
            raise GitHubError(
                f"Ambiguous ref {ref!r}: both branch and tag exist in {owner}/{repo}",
                error_code="GITHUB_ERR_AMBIGUOUS_REF", status=409,
            )

        if head_data is not None:
            return self._verify_branch_object(owner, repo, ref, head_data)
        if tag_data is not None:
            return self._peel_tag(owner, repo, ref, tag_data)

        raise GitHubError(
            f"Ref {ref!r} not found in {owner}/{repo}",
            error_code="GITHUB_ERR_NOT_FOUND", status=404,
        )

    # -- Internal helpers --

    def _verify_branch_object(self, owner: str, repo: str, ref: str, ref_data: dict) -> str:
        """Verify a branch ref object is a commit and return its SHA."""
        from urllib.parse import quote
        from aisc.domain.skill_models import _SHA40_RE
        _enc = lambda s: quote(s, safe="")
        obj = ref_data.get("object", {})
        sha = obj.get("sha", "")
        obj_type = obj.get("type", "commit")
        if not _SHA40_RE.match(sha):
            raise GitHubError(
                f"Branch {ref!r} object has invalid SHA {sha!r}",
                error_code="GITHUB_ERR_UNEXPECTED",
            )
        if obj_type != "commit":
            raise GitHubError(
                f"Branch {ref!r} object is type {obj_type!r}, expected commit",
                error_code="GITHUB_ERR_UNEXPECTED",
            )
        # Verify via commit endpoint
        url = f"{_GITHUB_API_BASE}/repos/{_enc(owner)}/{_enc(repo)}/git/commits/{_enc(sha)}"
        resp = self.get(url, timeout=self._read_timeout)
        if resp.status != 200:
            raise GitHubError(
                f"Commit {sha[:7]} verification failed for branch {ref!r}",
                error_code="GITHUB_ERR_NOT_FOUND", status=404, url=url,
            )
        commit_data = json.loads(resp.body.decode("utf-8"))
        returned_sha = commit_data.get("sha", "")
        if not _SHA40_RE.match(returned_sha):
            raise GitHubError(
                f"Branch {ref!r}: commit endpoint returned non-SHA",
                error_code="GITHUB_ERR_UNEXPECTED", url=url,
            )
        return returned_sha.lower()

    def _peel_tag(self, owner: str, repo: str, ref: str, ref_data: dict) -> str:
        """Peel a tag (possibly annotated) to a commit SHA, max depth 8."""
        from urllib.parse import quote
        from aisc.domain.skill_models import _SHA40_RE
        _enc = lambda s: quote(s, safe="")
        obj = ref_data.get("object", {})
        sha = obj.get("sha", "")
        obj_type = obj.get("type", "")
        if not _SHA40_RE.match(sha):
            raise GitHubError(
                f"Tag {ref!r} object has invalid SHA {sha!r}",
                error_code="GITHUB_ERR_UNEXPECTED",
            )
        # Lightweight tag: object points directly to commit
        if obj_type == "commit":
            # Verify
            url = f"{_GITHUB_API_BASE}/repos/{_enc(owner)}/{_enc(repo)}/git/commits/{_enc(sha)}"
            resp = self.get(url, timeout=self._read_timeout)
            if resp.status != 200:
                raise GitHubError(
                    f"Lightweight tag {ref!r}: commit {sha[:7]} not found",
                    error_code="GITHUB_ERR_NOT_FOUND", status=404, url=url,
                )
            cdata = json.loads(resp.body.decode("utf-8"))
            ret = cdata.get("sha", "")
            if not _SHA40_RE.match(ret):
                raise GitHubError(
                    f"Lightweight tag {ref!r}: commit endpoint returned non-SHA",
                    error_code="GITHUB_ERR_UNEXPECTED", url=url,
                )
            return ret.lower()

        # Annotated tag: peel
        if obj_type != "tag":
            raise GitHubError(
                f"Tag {ref!r}: object type {obj_type!r}, expected tag or commit",
                error_code="GITHUB_ERR_UNEXPECTED",
            )
        seen: set = {sha}
        current_sha = sha
        for depth in range(8):
            url = f"{_GITHUB_API_BASE}/repos/{_enc(owner)}/{_enc(repo)}/git/tags/{_enc(current_sha)}"
            resp = self.get(url, timeout=self._read_timeout)
            if resp.status != 200:
                raise GitHubError(
                    f"Annotated tag {ref!r} depth {depth}: tag {current_sha[:7]} not found",
                    error_code="GITHUB_ERR_NOT_FOUND", status=404, url=url,
                )
            tdata = json.loads(resp.body.decode("utf-8"))
            inner_obj = tdata.get("object", {})
            inner_sha = inner_obj.get("sha", "")
            inner_type = inner_obj.get("type", "")
            if not _SHA40_RE.match(inner_sha):
                raise GitHubError(
                    f"Tag {ref!r} depth {depth}: invalid inner SHA",
                    error_code="GITHUB_ERR_UNEXPECTED", url=url,
                )
            if inner_type == "commit":
                # Found commit — verify
                curl = f"{_GITHUB_API_BASE}/repos/{_enc(owner)}/{_enc(repo)}/git/commits/{_enc(inner_sha)}"
                cresp = self.get(curl, timeout=self._read_timeout)
                if cresp.status != 200:
                    raise GitHubError(
                        f"Tag {ref!r}: peeled commit {inner_sha[:7]} not found",
                        error_code="GITHUB_ERR_NOT_FOUND", status=404, url=curl,
                    )
                cdata = json.loads(cresp.body.decode("utf-8"))
                ret = cdata.get("sha", "")
                if not _SHA40_RE.match(ret):
                    raise GitHubError(
                        f"Tag {ref!r}: peeled commit endpoint returned non-SHA",
                        error_code="GITHUB_ERR_UNEXPECTED", url=curl,
                    )
                return ret.lower()
            if inner_type == "tag":
                if inner_sha in seen:
                    raise GitHubError(
                        f"Tag {ref!r}: cycle detected at depth {depth}",
                        error_code="GITHUB_ERR_UNEXPECTED",
                    )
                seen.add(inner_sha)
                current_sha = inner_sha
                continue
            raise GitHubError(
                f"Tag {ref!r} depth {depth}: object type {inner_type!r}, expected tag or commit",
                error_code="GITHUB_ERR_UNEXPECTED", url=url,
            )
        raise GitHubError(
            f"Tag {ref!r}: exceeded max peel depth 8",
            error_code="GITHUB_ERR_UNEXPECTED",
        )

    # -- Tree fetching --

    def get_tree(self, owner: str, repo: str, commit_sha: str,
                 directory: str) -> List[Dict[str, Any]]:
        """Fetch the complete tree listing for *directory* at *commit_sha*.

        Uses recursive tree API.  Returns list of tree entries.
        """
        # First, get the tree SHA for the directory path
        if directory:
            # Get the commit's root tree, then traverse to subdirectory
            commit_url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/git/commits/{commit_sha}"
            resp = self.get(commit_url, timeout=self._read_timeout)
            commit_data = json.loads(resp.body.decode("utf-8"))
            tree_sha = commit_data.get("tree", {}).get("sha", "")

            if not tree_sha:
                raise GitHubError(
                    f"No tree SHA found for commit {commit_sha[:7]}",
                    error_code="GITHUB_ERR_UNEXPECTED",
                )

            # Recursively fetch the full tree
            tree_url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1"
            resp = self.get(tree_url, timeout=self._read_timeout)
            tree_data = json.loads(resp.body.decode("utf-8"))

            if tree_data.get("truncated"):
                raise GitHubError(
                    f"Tree too large — truncated response for {owner}/{repo} at {commit_sha[:7]}",
                    error_code="GITHUB_ERR_TREE_TRUNCATED",
                )

            all_entries = tree_data.get("tree", [])

            # Filter to entries within the target directory
            dir_prefix = directory.rstrip("/") + "/" if directory else ""
            matching = []
            for entry in all_entries:
                path = entry.get("path", "")
                if path.startswith(dir_prefix):
                    matching.append(entry)

            if not matching:
                raise GitHubError(
                    f"Directory {directory!r} not found or empty in {owner}/{repo} at {commit_sha[:7]}",
                    error_code="GITHUB_ERR_NOT_FOUND",
                    status=404,
                )

            return matching
        else:
            # Root directory: get the tree directly
            commit_url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/git/commits/{commit_sha}"
            resp = self.get(commit_url, timeout=self._read_timeout)
            commit_data = json.loads(resp.body.decode("utf-8"))
            tree_sha = commit_data.get("tree", {}).get("sha", "")
            tree_url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{tree_sha}"
            resp = self.get(tree_url, timeout=self._read_timeout)
            tree_data = json.loads(resp.body.decode("utf-8"))
            return tree_data.get("tree", [])

    # -- Blob fetching --

    def get_blob(self, owner: str, repo: str, blob_sha: str) -> bytes:
        """Fetch a blob by its SHA.  Returns raw bytes."""
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/git/blobs/{blob_sha}"
        resp = self.get(url, timeout=self._read_timeout)
        data = json.loads(resp.body.decode("utf-8"))
        content = data.get("content", "")
        encoding = data.get("encoding", "utf-8")

        import base64
        if encoding == "base64":
            return base64.b64decode(content)
        else:
            return content.encode("utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body_summary(body: bytes, max_len: int = 200) -> str:
    """Return a brief summary of response body for error messages."""
    if not body:
        return "(empty)"
    text = body.decode("utf-8", errors="replace")
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text
