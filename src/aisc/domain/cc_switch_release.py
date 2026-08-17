"""cc-switch release selection — pure domain logic (Stage 8, CS-01/CS-02).

Operates on GitHub Releases API dicts (already fetched; this module never
performs I/O). Encodes the asset contract proven by the 8a black-box probe
(``docs/plans/aisc-next-followup/stage-8-cc-switch-provider-ui/8a-discovery-report.md``):

- asset names: ``cc-switch-cli-{tag}-linux-{x64|arm64}-{musl|glibc}.tar.gz``
  (versioned, preferred) and the unversioned twin inside the SAME release;
  the arch token is ``x64`` — NOT ``amd64``;
- every release asset carries an authoritative ``digest`` (``sha256:<hex>``)
  from the Releases API — a missing digest fails closed;
- only releases with ``prerelease=false, draft=false`` and a semver ``vX.Y.Z``
  tag are eligible for the ``stable`` channel.

Fail-closed everywhere: an ambiguous or unverifiable release is rejected,
never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

RESOLVED_SCHEMA = "aisc.cc-switch-resolved/v1"
UPSTREAM_REPO = "saladday/cc-switch-cli"

# Stable error codes (never change the string; diagnostics rely on them).
CC_SWITCH_ERROR_INVALID_CHANNEL = "AISC_ERR_CC_SWITCH_INVALID_CHANNEL"
CC_SWITCH_ERROR_INVALID_TAG = "AISC_ERR_CC_SWITCH_INVALID_TAG"
CC_SWITCH_ERROR_NO_STABLE_RELEASE = "AISC_ERR_CC_SWITCH_NO_STABLE_RELEASE"
CC_SWITCH_ERROR_VERSION_NOT_FOUND = "AISC_ERR_CC_SWITCH_VERSION_NOT_FOUND"
CC_SWITCH_ERROR_NO_MATCHING_ASSET = "AISC_ERR_CC_SWITCH_NO_MATCHING_ASSET"
CC_SWITCH_ERROR_MISSING_DIGEST = "AISC_ERR_CC_SWITCH_MISSING_DIGEST"
CC_SWITCH_ERROR_BAD_MANIFEST = "AISC_ERR_CC_SWITCH_BAD_MANIFEST"
CC_SWITCH_ERROR_MANIFEST_MISMATCH = "AISC_ERR_CC_SWITCH_MANIFEST_MISMATCH"
CC_SWITCH_ERROR_NETWORK = "AISC_ERR_CC_SWITCH_NETWORK"
CC_SWITCH_ERROR_RATE_LIMITED = "AISC_ERR_CC_SWITCH_RATE_LIMITED"

SEMVER_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Arch tokens upstream uses in asset names (map your platform's uname arch
# through this before calling select_release).
ASSET_ARCHS = ("x64", "arm64")
ASSET_LIBCS = ("musl", "glibc")

# Where a resolution came from — surfaced in the manifest so a cached or
# file-supplied resolution is never mistaken for a live one (fail-visible).
SOURCE_API = "api"
SOURCE_CACHE = "cache"
SOURCE_MANIFEST = "manifest"


class ResolveError(Exception):
    """Release selection failure with a stable code (fail closed)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_arch(platform_arch: str) -> str:
    """Map a platform arch (``amd64``/``x86_64``/``arm64``/``aarch64``) to the
    upstream asset token (``x64``/``arm64``). Unknown arches fail closed."""
    a = platform_arch.strip().lower()
    if a in ("amd64", "x86_64", "x64"):
        return "x64"
    if a in ("arm64", "aarch64"):
        return "arm64"
    raise ResolveError(
        CC_SWITCH_ERROR_NO_MATCHING_ASSET,
        f"unsupported platform arch for cc-switch assets: {platform_arch!r}",
    )


def _asset_names(tag: str, arch: str, libc: str) -> Tuple[str, str]:
    """(versioned, unversioned) asset names for a release tag."""
    return (
        f"cc-switch-cli-{tag}-linux-{arch}-{libc}.tar.gz",
        f"cc-switch-cli-linux-{arch}-{libc}.tar.gz",
    )


def _usable_asset(release: Dict[str, Any], tag: str, arch: str, libc: str) -> Optional[Dict[str, Any]]:
    """Pick the asset for this release matching the arch/libc contract, with a
    trustworthy sha256 digest. Versioned name wins; the unversioned twin in
    the same release is the same file. Missing/invalid digest -> not usable."""
    versioned, unversioned = _asset_names(tag, arch, libc)
    assets = {a.get("name", ""): a for a in release.get("assets", [])}
    chosen = assets.get(versioned) or assets.get(unversioned)
    if chosen is None:
        return None
    digest = str(chosen.get("digest") or "")
    sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
    if not _SHA256_RE.match(sha):
        return None
    return chosen


def _eligible(release: Dict[str, Any]) -> bool:
    if release.get("draft") or release.get("prerelease"):
        return False
    return bool(SEMVER_TAG_RE.match(str(release.get("tag_name") or "")))


def select_release(
    releases: List[Dict[str, Any]],
    *,
    channel: str = "stable",
    version: str = "latest",
    arch: str = "x64",
    libc: str = "musl",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Pure selection: (release, asset) for the channel/version/arch/libc.

    ``version="latest"`` takes the newest eligible release that HAS a usable
    asset (skipping empty releases); an explicit ``vX.Y.Z`` must exist and
    have the asset (fail closed otherwise).
    """
    if channel != "stable":
        raise ResolveError(
            CC_SWITCH_ERROR_INVALID_CHANNEL,
            f"unsupported cc-switch channel {channel!r} (only 'stable')",
        )
    if arch not in ASSET_ARCHS or libc not in ASSET_LIBCS:
        raise ResolveError(
            CC_SWITCH_ERROR_NO_MATCHING_ASSET,
            f"unsupported asset target linux-{arch}-{libc}",
        )

    want_explicit = version != "latest"
    if want_explicit and not SEMVER_TAG_RE.match(version):
        raise ResolveError(
            CC_SWITCH_ERROR_INVALID_TAG,
            f"cc-switch version must be 'latest' or vX.Y.Z, got {version!r}",
        )

    ordered = sorted(
        (r for r in releases if _eligible(r)),
        key=lambda r: str(r.get("published_at") or r.get("created_at") or ""),
        reverse=True,
    )

    if want_explicit:
        candidates = [r for r in ordered if r.get("tag_name") == version]
        if not candidates:
            raise ResolveError(
                CC_SWITCH_ERROR_VERSION_NOT_FOUND,
                f"cc-switch {version} not found in the stable channel",
            )
    else:
        candidates = ordered

    for release in candidates:
        asset = _usable_asset(release, str(release["tag_name"]), arch, libc)
        if asset is not None:
            return release, asset

    if want_explicit:
        raise ResolveError(
            CC_SWITCH_ERROR_NO_MATCHING_ASSET,
            f"cc-switch {version} has no linux-{arch}-{libc}.tar.gz asset with a sha256 digest",
        )
    raise ResolveError(
        CC_SWITCH_ERROR_NO_STABLE_RELEASE,
        f"no stable cc-switch release with a usable linux-{arch}-{libc} asset",
    )


@dataclass(frozen=True)
class ResolvedRelease:
    """The frozen resolution result consumed by the build and baked into the
    image labels / manifest (02-domain-contract.md §Build input)."""

    channel: str
    tag: str
    release_id: int
    commit: str
    published_at: str
    asset_name: str
    asset_url: str
    asset_sha256: str
    asset_size: int
    arch: str
    libc: str
    source: str  # api | cache | manifest

    def to_manifest(self, *, resolved_at: str = "") -> Dict[str, Any]:
        return {
            "schema": RESOLVED_SCHEMA,
            "channel": self.channel,
            "version": self.tag,
            "release_id": self.release_id,
            "commit": self.commit,
            "published_at": self.published_at,
            "asset_name": self.asset_name,
            "asset_url": self.asset_url,
            "asset_sha256": self.asset_sha256,
            "asset_size": self.asset_size,
            "arch": self.arch,
            "libc": self.libc,
            "source": self.source,
            "resolved_at": resolved_at,
        }

    @classmethod
    def from_manifest(cls, data: Dict[str, Any]) -> "ResolvedRelease":
        """Strict load for ``--cc-switch-manifest`` (offline/reproducible
        builds). Unknown extra keys are ignored; missing/invalid fields fail
        closed — a partial manifest must never enter a build."""
        try:
            schema = data["schema"]
            obj = cls(
                channel=str(data["channel"]),
                tag=str(data["version"]),
                release_id=int(data["release_id"]),
                commit=str(data["commit"]),
                published_at=str(data["published_at"]),
                asset_name=str(data["asset_name"]),
                asset_url=str(data["asset_url"]),
                asset_sha256=str(data["asset_sha256"]),
                asset_size=int(data["asset_size"]),
                arch=str(data["arch"]),
                libc=str(data["libc"]),
                source=str(data.get("source") or SOURCE_MANIFEST),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ResolveError(
                CC_SWITCH_ERROR_BAD_MANIFEST,
                f"cc-switch manifest is missing/invalid fields: {exc}",
            ) from exc
        if schema != RESOLVED_SCHEMA:
            raise ResolveError(
                CC_SWITCH_ERROR_BAD_MANIFEST,
                f"cc-switch manifest schema {schema!r} != {RESOLVED_SCHEMA!r}",
            )
        if not SEMVER_TAG_RE.match(obj.tag):
            raise ResolveError(
                CC_SWITCH_ERROR_BAD_MANIFEST,
                f"cc-switch manifest version {obj.tag!r} is not vX.Y.Z",
            )
        if not _SHA256_RE.match(obj.asset_sha256):
            raise ResolveError(
                CC_SWITCH_ERROR_BAD_MANIFEST,
                "cc-switch manifest asset_sha256 is not a bare sha256 hex digest",
            )
        if obj.asset_name != _asset_names(obj.tag, obj.arch, obj.libc)[0] and \
                obj.asset_name != _asset_names(obj.tag, obj.arch, obj.libc)[1]:
            raise ResolveError(
                CC_SWITCH_ERROR_BAD_MANIFEST,
                f"cc-switch manifest asset_name {obj.asset_name!r} does not match "
                f"linux-{obj.arch}-{obj.libc} for {obj.tag}",
            )
        if obj.source not in (SOURCE_API, SOURCE_CACHE, SOURCE_MANIFEST):
            raise ResolveError(
                CC_SWITCH_ERROR_BAD_MANIFEST,
                f"cc-switch manifest source {obj.source!r} is unknown",
            )
        return obj

    def check_matches_request(self, channel: str, version: str) -> None:
        """Cross-check a loaded manifest against the requested channel/version
        (both explicit) — a mismatch fails closed instead of building the
        wrong thing."""
        if channel != self.channel:
            raise ResolveError(
                CC_SWITCH_ERROR_MANIFEST_MISMATCH,
                f"manifest channel {self.channel!r} != requested {channel!r}",
            )
        if version != "latest" and version != self.tag:
            raise ResolveError(
                CC_SWITCH_ERROR_MANIFEST_MISMATCH,
                f"manifest version {self.tag!r} != requested {version!r}",
            )


def resolved_from_release(
    release: Dict[str, Any],
    asset: Dict[str, Any],
    *,
    channel: str,
    arch: str,
    libc: str,
    source: str,
) -> ResolvedRelease:
    """Build a ResolvedRelease from an API release+asset pair."""
    tag = str(release["tag_name"])
    return ResolvedRelease(
        channel=channel,
        tag=tag,
        release_id=int(release.get("id") or 0),
        commit=str(release.get("target_commitish") or ""),
        published_at=str(release.get("published_at") or ""),
        asset_name=str(asset["name"]),
        asset_url=str(asset.get("browser_download_url") or ""),
        asset_sha256=str(asset.get("digest") or "").split(":", 1)[-1],
        asset_size=int(asset.get("size") or 0),
        arch=arch,
        libc=libc,
        source=source,
    )
