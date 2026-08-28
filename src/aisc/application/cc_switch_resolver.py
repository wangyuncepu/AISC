"""cc-switch release resolver — application layer (Stage 8b, CS-01).

Bridges the pure selection in ``aisc.domain.cc_switch_release`` to the real
world: GitHub Releases API (paginated, rate-limit aware, injectable transport
for tests), a TTL metadata cache under the shared data root (Stage 7 layout
``<data-root>/cache/cc-switch/``), and offline builds from a previously
written manifest file.

Policies (03-build-version-resolution.md):
- ``latest`` resolves live; a fresh-enough cache may serve a network failure,
  but the manifest always records ``source`` (api|cache|manifest) — a cached
  resolution is surfaced, never silent;
- rate limiting never degrades into stale assets: with no usable cache the
  resolve fails closed and points at the explicit-manifest path;
- an explicit ``vX.Y.Z`` may be served from a cache of any age (the pinned
  release's digest is stable content), again with ``source=cache``;
- as the LAST offline resort (2.1.7 #37), the per-build receipt written after
  every successful resolve (``cache/cc-switch/last-resolved.json``, any age —
  a pinned digest is stable content) may serve a network/rate-limit failure,
  same semantics as ``docker_lifecycle._cc_switch_for_rebuild``; a receipt
  that does not match the request (channel/version/arch/libc) is never used.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from aisc.domain.cc_switch_release import (
    ResolveError,
    ResolvedRelease,
    SOURCE_API,
    SOURCE_CACHE,
    SOURCE_MANIFEST,
    UPSTREAM_REPO,
    CC_SWITCH_ERROR_BAD_MANIFEST,
    CC_SWITCH_ERROR_NETWORK,
    CC_SWITCH_ERROR_RATE_LIMITED,
)


DEFAULT_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_TTL_S = 600.0
DEFAULT_PER_PAGE = 50
DEFAULT_MAX_PAGES = 4
CACHE_SCHEMA = "aisc.cc-switch-releases-cache/v1"

#: Injectable transport: (url, headers, timeout) -> (status, headers, body).
#: ``body`` is the parsed JSON (dict) on success. Raising propagates as a
#: network error except URLError/HTTPError which are mapped here.
Transport = Callable[[str, Dict[str, str], float], Tuple[int, Dict[str, str], Any]]


def default_transport(url: str, headers: Dict[str, str], timeout: float) -> Tuple[int, Dict[str, str], Any]:
    """stdlib urllib transport (no extra dependency; PyInstaller-friendly)."""
    req = urllib.request.Request(url, headers={"User-Agent": "aisc-resolver", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return int(resp.status), {k.lower(): v for k, v in resp.headers.items()}, body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            body: Any = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"message": raw}
        return int(exc.code), {k.lower(): v for k, v in exc.headers.items()}, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ResolveError(
            CC_SWITCH_ERROR_NETWORK,
            f"github api unreachable: {exc}",
        ) from exc


def _cache_dir() -> Path:
    # Local import keeps the module importable without a resolved data root
    # (domain selection and manifest loading never touch the cache).
    from aisc.application.data_root import shared_root

    return shared_root() / "cache" / "cc-switch"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CcSwitchResolver:
    """Resolves the cc-switch release for a build.

    Args mirror the CLI knobs; every I/O seam (transport, cache dir, clock)
    is injectable so the fake-API test matrix in
    ``tests/test_cc_switch_resolver.py`` covers pagination, rate limits,
    cache fallback and offline manifests without network access.
    """

    def __init__(
        self,
        *,
        transport: Transport = default_transport,
        cache_dir: Optional[Path] = None,
        api_base: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        ttl_s: float = DEFAULT_TTL_S,
        clock: Callable[[], float] = time.time,
    ):
        self._transport = transport
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._api_base = (api_base or os.environ.get("AISC_GH_API_BASE") or DEFAULT_API_BASE).rstrip("/")
        self._token = token or os.environ.get("AISC_GH_API_TOKEN") or ""
        self._timeout = timeout
        self._ttl_s = ttl_s
        self._clock = clock

    # --- public API ---------------------------------------------------------

    def resolve(
        self,
        *,
        channel: str = "stable",
        version: str = "latest",
        arch: str = "x64",
        libc: str = "musl",
        manifest_path: Optional[Path] = None,
    ) -> ResolvedRelease:
        """Resolve to a :class:`ResolvedRelease` (fail closed).

        ``manifest_path`` short-circuits all network/cache I/O: the file is
        strictly validated and cross-checked against the request.
        """
        if manifest_path is not None:
            return self._from_manifest(manifest_path, channel, version)

        try:
            releases = self._fetch_releases()
        except ResolveError as network_error:
            if network_error.code not in (CC_SWITCH_ERROR_NETWORK, CC_SWITCH_ERROR_RATE_LIMITED):
                raise
            cached = self._cached_resolve(channel, version, arch, libc)
            if cached is not None:
                return cached
            # 2.1.7 #37: last resort — the receipt from ANY previous
            # successful resolve (any age, digest-stable pin).
            receipt = self._last_resolved_fallback(channel, version, arch, libc)
            if receipt is not None:
                return receipt
            raise ResolveError(
                network_error.code,
                f"{network_error.message} "
                f"(no usable cache — check network/proxy access to "
                f"api.github.com and retry; for fully offline builds pass a "
                f"manifest file written by a previous resolve via "
                f"--cc-switch-manifest)",
            ) from network_error

        selection = self._select(releases, channel, version, arch, libc, source=SOURCE_API)
        self._write_cache(releases)
        return selection

    # --- manifest (offline) --------------------------------------------------

    def _from_manifest(self, path: Path, channel: str, version: str) -> ResolvedRelease:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResolveError(
                CC_SWITCH_ERROR_BAD_MANIFEST,
                f"cannot read cc-switch manifest {path}: {exc}",
            ) from exc
        resolved = ResolvedRelease.from_manifest(data)
        resolved.check_matches_request(channel, version)
        # A manifest build never claims to be live.
        return replace(resolved, source=SOURCE_MANIFEST)

    # --- GitHub API ----------------------------------------------------------

    def _fetch_page(self, page: int) -> Tuple[List[Dict[str, Any]], bool]:
        url = (
            f"{self._api_base}/repos/{UPSTREAM_REPO}/releases"
            f"?per_page={DEFAULT_PER_PAGE}&page={page}"
        )
        headers: Dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        status, resp_headers, body = self._transport(url, headers, self._timeout)

        if status in (403, 429):
            remaining = str(resp_headers.get("x-ratelimit-remaining", ""))
            if status == 429 or remaining == "0":
                raise ResolveError(
                    CC_SWITCH_ERROR_RATE_LIMITED,
                    "github api rate limited (pass --cc-switch-manifest for an offline build)",
                )
            raise ResolveError(
                CC_SWITCH_ERROR_NETWORK,
                f"github api refused (HTTP {status}): {body.get('message', '')!s:.120}",
            )
        if status != 200:
            raise ResolveError(
                CC_SWITCH_ERROR_NETWORK,
                f"github api error (HTTP {status})",
            )
        if not isinstance(body, list):
            raise ResolveError(
                CC_SWITCH_ERROR_NETWORK,
                "github api returned a non-list releases payload",
            )
        return body, len(body) < DEFAULT_PER_PAGE

    def _fetch_releases(self) -> List[Dict[str, Any]]:
        all_releases: List[Dict[str, Any]] = []
        for page in range(1, DEFAULT_MAX_PAGES + 1):
            page_releases, last = self._fetch_page(page)
            all_releases.extend(page_releases)
            if last or not page_releases:
                break
        else:
            # Exhausted pagination without finding a terminal page; keep what
            # we have — selection fails closed if the target isn't in range.
            pass
        return all_releases

    # --- cache ---------------------------------------------------------------

    @property
    def _cache_file(self) -> Optional[Path]:
        return (self._cache_dir or _cache_dir()) / "releases.json"

    def _write_cache(self, releases: List[Dict[str, Any]]) -> None:
        path = self._cache_file
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema": CACHE_SCHEMA,
                "fetched_at": self._clock(),
                "repo": UPSTREAM_REPO,
                "releases": releases,
            }
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            # Cache is an optimization, never a gate.
            pass

    def _read_cache(self) -> Optional[Tuple[float, List[Dict[str, Any]]]]:
        path = self._cache_file
        if path is None or not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema") != CACHE_SCHEMA:
                return None
            fetched_at = float(payload["fetched_at"])
            releases = payload["releases"]
            if not isinstance(releases, list):
                return None
            return fetched_at, releases
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _cached_resolve(
        self, channel: str, version: str, arch: str, libc: str
    ) -> Optional[ResolvedRelease]:
        cached = self._read_cache()
        if cached is None:
            return None
        fetched_at, releases = cached
        age = self._clock() - fetched_at
        # latest only trusts a fresh cache; an explicit version is pinned, so
        # any age is acceptable (source=cache still surfaces the fact).
        if version == "latest" and age > self._ttl_s:
            return None
        try:
            return self._select(releases, channel, version, arch, libc, source=SOURCE_CACHE)
        except ResolveError:
            return None

    @property
    def _last_resolved_file(self) -> Path:
        # The per-build receipt ``aisc build`` writes after every successful
        # resolve (cli.main._write_cc_switch_manifest — same shared-root
        # cache dir as ``releases.json``).
        return (self._cache_dir or _cache_dir()) / "last-resolved.json"

    def _last_resolved_fallback(
        self, channel: str, version: str, arch: str, libc: str
    ) -> Optional[ResolvedRelease]:
        """Offline last resort (2.1.7 #37): serve the request from the
        last-resolved receipt, ANY age (a pinned digest is stable content —
        same semantics as ``_cc_switch_for_rebuild``).

        Strictly fail-closed on mismatch: a receipt that does not match the
        requested channel/version/arch/libc must never silently build the
        wrong pin, so it reads as "no fallback" and the network error
        propagates. The served resolution keeps ``source=cache`` — surfaced,
        never silent."""
        try:
            data = json.loads(self._last_resolved_file.read_text(encoding="utf-8"))
            resolved = ResolvedRelease.from_manifest(data)
            resolved.check_matches_request(channel, version)
            if resolved.arch != arch or resolved.libc != libc:
                return None
        except (OSError, ValueError, ResolveError):
            return None
        # A receipt never masquerades as a live resolution.
        return replace(resolved, source=SOURCE_CACHE)

    # --- selection wrapper -----------------------------------------------------

    def _select(
        self,
        releases: List[Dict[str, Any]],
        channel: str,
        version: str,
        arch: str,
        libc: str,
        *,
        source: str,
    ) -> ResolvedRelease:
        # Local import: domain module has no application deps.
        from aisc.domain.cc_switch_release import resolved_from_release, select_release

        release, asset = select_release(
            releases, channel=channel, version=version, arch=arch, libc=libc
        )
        return resolved_from_release(
            release, asset, channel=channel, arch=arch, libc=libc, source=source
        )


def resolved_at_now() -> str:
    """Timestamp stamped into manifests written by the build command."""
    return _utc_now_iso()
