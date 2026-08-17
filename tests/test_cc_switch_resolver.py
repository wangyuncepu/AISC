"""Stage 8b (CS-01/CS-02): cc-switch release resolver.

Domain selection matrix over fake GitHub release payloads + the application
resolver (pagination, rate-limit, TTL cache fallback, offline manifest) + the
BuildPlan/BuildResult wiring. All hermetic: injectable transport and cache
dir; no network. The asset contract (x64 arch token, versioned names,
``digest`` = authoritative sha256) mirrors the 8a black-box probe.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aisc.domain.cc_switch_release import (
    CC_SWITCH_ERROR_BAD_MANIFEST,
    CC_SWITCH_ERROR_INVALID_CHANNEL,
    CC_SWITCH_ERROR_INVALID_TAG,
    CC_SWITCH_ERROR_MANIFEST_MISMATCH,
    CC_SWITCH_ERROR_MISSING_DIGEST,
    CC_SWITCH_ERROR_NO_MATCHING_ASSET,
    CC_SWITCH_ERROR_NO_STABLE_RELEASE,
    CC_SWITCH_ERROR_RATE_LIMITED,
    CC_SWITCH_ERROR_VERSION_NOT_FOUND,
    CC_SWITCH_ERROR_NETWORK,
    ResolveError,
    ResolvedRelease,
    normalize_arch,
    select_release,
)
from aisc.application.cc_switch_resolver import CcSwitchResolver

SHA_A = "a" * 64
SHA_B = "b" * 64


def make_release(tag: str, *, prerelease: bool = False, draft: bool = False,
                 published: str = "2026-08-06T00:00:00Z", with_digest: bool = True,
                 unversioned_only: bool = False, rid: int = 1) -> dict:
    digest = f"sha256:{SHA_A}" if with_digest else ""
    names = (
        [f"cc-switch-cli-linux-x64-musl.tar.gz"]
        if unversioned_only
        else [f"cc-switch-cli-{tag}-linux-x64-musl.tar.gz"]
    )
    return {
        "id": rid,
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "published_at": published,
        "target_commitish": "deadbeef",
        "assets": [
            {
                "name": n,
                "browser_download_url": f"https://x/{n}",
                "digest": digest,
                "size": 8353737,
            }
            for n in names
        ],
    }


V510 = make_release("v5.10.1", published="2026-08-06T00:00:00Z", rid=110)
V5100 = make_release("v5.10.0", published="2026-08-02T00:00:00Z", rid=100)
V59 = make_release("v5.9.0", published="2026-07-08T00:00:00Z", rid=90)


class SelectReleaseTests(unittest.TestCase):
    def test_latest_picks_newest_stable_with_asset(self):
        release, asset = select_release([V59, V5100, V510], version="latest")
        self.assertEqual(release["tag_name"], "v5.10.1")
        self.assertEqual(asset["name"], "cc-switch-cli-v5.10.1-linux-x64-musl.tar.gz")

    def test_prerelease_draft_and_non_semver_excluded(self):
        newer_bad = [
            make_release("v5.11.0-rc1", prerelease=True, published="2026-08-10T00:00:00Z"),
            make_release("v5.11.0", draft=True, published="2026-08-09T00:00:00Z"),
            make_release("nightly", published="2026-08-08T00:00:00Z"),
            V510,
        ]
        release, _ = select_release(newer_bad, version="latest")
        self.assertEqual(release["tag_name"], "v5.10.1")

    def test_latest_skips_assetless_releases(self):
        empty = make_release("v5.11.0", published="2026-08-10T00:00:00Z")
        empty["assets"] = [{"name": "cc-switch-cli-v5.11.0-linux-x64-musl.tar.gz", "digest": "", "size": 1}]
        release, _ = select_release([empty, V510], version="latest")
        self.assertEqual(release["tag_name"], "v5.10.1")

    def test_missing_digest_rejected_fail_closed(self):
        no_digest = make_release("v5.10.1", with_digest=False)
        with self.assertRaises(ResolveError) as ctx:
            select_release([no_digest], version="latest")
        self.assertEqual(ctx.exception.code, CC_SWITCH_ERROR_NO_STABLE_RELEASE)
        with self.assertRaises(ResolveError) as ctx:
            select_release([no_digest], version="v5.10.1")
        self.assertEqual(ctx.exception.code, CC_SWITCH_ERROR_NO_MATCHING_ASSET)

    def test_unversioned_asset_in_same_release_accepted(self):
        only_unversioned = make_release("v5.10.1", unversioned_only=True)
        release, asset = select_release([only_unversioned], version="latest")
        self.assertEqual(asset["name"], "cc-switch-cli-linux-x64-musl.tar.gz")

    def test_explicit_version_found_and_missing(self):
        release, _ = select_release([V510, V59], version="v5.9.0")
        self.assertEqual(release["tag_name"], "v5.9.0")
        with self.assertRaises(ResolveError) as ctx:
            select_release([V510], version="v5.8.0")
        self.assertEqual(ctx.exception.code, CC_SWITCH_ERROR_VERSION_NOT_FOUND)

    def test_explicit_version_prefers_versioned_asset_name(self):
        both = make_release("v5.10.1")
        both["assets"].append(
            {"name": "cc-switch-cli-linux-x64-musl.tar.gz",
             "browser_download_url": "https://x/u", "digest": f"sha256:{SHA_A}", "size": 1}
        )
        _, asset = select_release([both], version="v5.10.1")
        self.assertEqual(asset["name"], "cc-switch-cli-v5.10.1-linux-x64-musl.tar.gz")

    def test_bad_channel_and_bad_tag_rejected(self):
        with self.assertRaises(ResolveError) as ctx:
            select_release([V510], channel="beta")
        self.assertEqual(ctx.exception.code, CC_SWITCH_ERROR_INVALID_CHANNEL)
        with self.assertRaises(ResolveError) as ctx:
            select_release([V510], version="5.10.1")
        self.assertEqual(ctx.exception.code, CC_SWITCH_ERROR_INVALID_TAG)

    def test_arm64_and_glibc_targets(self):
        r = make_release("v5.10.1")
        r["assets"].append(
            {"name": "cc-switch-cli-v5.10.1-linux-arm64-musl.tar.gz",
             "browser_download_url": "https://x/a", "digest": f"sha256:{SHA_B}", "size": 1}
        )
        _, asset = select_release([r], version="latest", arch="arm64")
        self.assertEqual(asset["name"], "cc-switch-cli-v5.10.1-linux-arm64-musl.tar.gz")
        with self.assertRaises(ResolveError):
            select_release([r], version="latest", libc="glibc")

    def test_normalize_arch(self):
        self.assertEqual(normalize_arch("AMD64"), "x64")
        self.assertEqual(normalize_arch("x86_64"), "x64")
        self.assertEqual(normalize_arch("aarch64"), "arm64")
        with self.assertRaises(ResolveError):
            normalize_arch("riscv64")


def fake_transport(pages: list[list[dict]], calls: list | None = None):
    def transport(url: str, headers: dict, timeout: float):
        if calls is not None:
            calls.append(url)
        page = int(url.split("&page=")[1])
        if page > len(pages):
            return 200, {}, []
        return 200, {}, pages[page - 1]

    return transport


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.tmp.name) / "cache" / "cc-switch"
        self.now = 1_000_000.0
        self.addCleanup(self.tmp.cleanup)

    def resolver(self, transport, **kw):
        return CcSwitchResolver(
            transport=transport,
            cache_dir=self.cache_dir,
            clock=lambda: self.now,
            **kw,
        )

    def test_resolve_latest_writes_cache_and_manifest_shape(self):
        r = self.resolver(fake_transport([[V510, V5100]]))
        resolved = r.resolve(version="latest")
        self.assertEqual(resolved.tag, "v5.10.1")
        self.assertEqual(resolved.source, "api")
        self.assertEqual(resolved.asset_sha256, SHA_A)
        self.assertEqual(resolved.commit, "deadbeef")
        manifest = resolved.to_manifest(resolved_at="t")
        self.assertEqual(manifest["schema"], "aisc.cc-switch-resolved/v1")
        # Cache written for future fallbacks.
        self.assertTrue((self.cache_dir / "releases.json").exists())

    def test_pagination_for_explicit_old_version(self):
        # GitHub semantics: a partial page is the LAST page, so page 1 must be
        # full (50 entries) for the resolver to fetch page 2.
        full_first = [V510] + [
            make_release(f"v5.9.{i}", published="2026-07-07T00:00:00Z", rid=50 + i)
            for i in range(1, 50)
        ]
        self.assertEqual(len(full_first), 50)
        r = self.resolver(fake_transport([full_first, [V59]]))
        resolved = r.resolve(version="v5.9.0")
        self.assertEqual(resolved.tag, "v5.9.0")

    def test_rate_limit_fails_closed_without_cache(self):
        def transport(url, headers, timeout):
            return 403, {"x-ratelimit-remaining": "0"}, {"message": "rate"}

        r = self.resolver(transport)
        with self.assertRaises(ResolveError) as ctx:
            r.resolve(version="latest")
        self.assertEqual(ctx.exception.code, CC_SWITCH_ERROR_RATE_LIMITED)

    def test_network_failure_falls_back_to_fresh_cache_for_latest(self):
        r = self.resolver(fake_transport([[V510]]))
        r.resolve(version="latest")
        self.now += 60  # within TTL

        dead = self.resolver(
            lambda url, headers, timeout: (_ for _ in ()).throw(
                ResolveError(CC_SWITCH_ERROR_NETWORK, "down")
            )
        )
        resolved = dead.resolve(version="latest")
        self.assertEqual(resolved.source, "cache")  # surfaced, never silent
        self.assertEqual(resolved.tag, "v5.10.1")

    def test_stale_cache_not_used_for_latest(self):
        r = self.resolver(fake_transport([[V510]]), ttl_s=100)
        r.resolve(version="latest")
        self.now += 600  # beyond TTL

        def down(url, headers, timeout):
            raise ResolveError(CC_SWITCH_ERROR_NETWORK, "down")

        with self.assertRaises(ResolveError) as ctx:
            self.resolver(down, ttl_s=100).resolve(version="latest")
        self.assertEqual(ctx.exception.code, CC_SWITCH_ERROR_NETWORK)

    def test_stale_cache_ok_for_explicit_version(self):
        r = self.resolver(fake_transport([[V510, V59]]), ttl_s=100)
        r.resolve(version="v5.9.0")
        self.now += 600

        def down(url, headers, timeout):
            raise ResolveError(CC_SWITCH_ERROR_NETWORK, "down")

        resolved = self.resolver(down, ttl_s=100).resolve(version="v5.9.0")
        self.assertEqual(resolved.source, "cache")
        self.assertEqual(resolved.tag, "v5.9.0")

    def test_offline_manifest_roundtrip_and_mismatch(self):
        r = self.resolver(fake_transport([[V510]]))
        resolved = r.resolve(version="latest")
        path = Path(self.tmp.name) / "m.json"
        path.write_text(json.dumps(resolved.to_manifest(resolved_at="t")), encoding="utf-8")

        offline = self.resolver(fake_transport([[V59]]))
        got = offline.resolve(version="v5.10.1", manifest_path=path)
        self.assertEqual(got.source, "manifest")  # never claims to be live
        self.assertEqual(got.tag, "v5.10.1")
        # No network attempted.
        with self.assertRaises(ResolveError) as ctx:
            offline.resolve(version="v5.9.0", manifest_path=path)
        self.assertEqual(ctx.exception.code, CC_SWITCH_ERROR_MANIFEST_MISMATCH)

    def test_bad_manifest_rejected(self):
        path = Path(self.tmp.name) / "bad.json"
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(ResolveError) as ctx:
            self.resolver(fake_transport([[V510]])).resolve(manifest_path=path)
        self.assertEqual(ctx.exception.code, CC_SWITCH_ERROR_BAD_MANIFEST)
        # Bad sha / wrong asset name / bad tag all fail closed.
        base = json.loads(json.dumps(resolved_manifest()))
        for mutate in (
            {"asset_sha256": "zz"},
            {"asset_name": "cc-switch-cli-linux-arm64-musl.tar.gz"},
            {"version": "5.10.1"},
        ):
            data = {**base, **mutate}
            p2 = Path(self.tmp.name) / "bad2.json"
            p2.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ResolveError):
                ResolvedRelease.from_manifest(data)


def resolved_manifest() -> dict:
    return {
        "schema": "aisc.cc-switch-resolved/v1",
        "channel": "stable",
        "version": "v5.10.1",
        "release_id": 110,
        "commit": "deadbeef",
        "published_at": "2026-08-06T00:00:00Z",
        "asset_name": "cc-switch-cli-v5.10.1-linux-x64-musl.tar.gz",
        "asset_url": "https://x/cc-switch-cli-v5.10.1-linux-x64-musl.tar.gz",
        "asset_sha256": SHA_A,
        "asset_size": 8353737,
        "arch": "x64",
        "libc": "musl",
        "source": "api",
        "resolved_at": "t",
    }


class BuildWiringTests(unittest.TestCase):
    """BuildPlan/plan_build/run_build carry the resolution end to end."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "container").mkdir()
        (root / "config").mkdir()
        (root / "container" / "Dockerfile").write_text("FROM x\n", encoding="utf-8")
        (root / "config" / "versions.env").write_text(
            "NODE_IMAGE=node:20-slim\nUSE_CN_MIRROR=1\n", encoding="utf-8"
        )
        self.root = root

    def _resolved(self) -> ResolvedRelease:
        return ResolvedRelease.from_manifest(resolved_manifest())

    def test_plan_build_injects_args_and_label_manifest(self):
        from aisc.cli.commands.build import plan_build

        plan = plan_build(self.root, tag="t:1", cc_switch=self._resolved())
        argv = plan.docker_argv
        for pair in (
            ("CC_SWITCH_RESOLVED_VERSION", "v5.10.1"),
            ("CC_SWITCH_ASSET_SHA256", SHA_A),
            ("CC_SWITCH_ASSET_NAME", "cc-switch-cli-v5.10.1-linux-x64-musl.tar.gz"),
        ):
            i = argv.index("--build-arg")
            argv_rest = argv
            key = f"{pair[0]}={pair[1]}"
            self.assertIn(key, argv_rest)
        # Label manifest JSON is compact and carries the provenance fields.
        label = json.loads(plan.cc_switch_manifest)
        self.assertEqual(label["version"], "v5.10.1")
        self.assertEqual(label["asset_sha256"], SHA_A)
        self.assertFalse(plan.cc_switch_manifest.endswith("\n"))

    def test_plan_build_without_resolution_keeps_legacy_argv(self):
        from aisc.cli.commands.build import plan_build

        plan = plan_build(self.root, tag="t:1")
        self.assertEqual(plan.cc_switch_version, "")
        self.assertNotIn("CC_SWITCH_ASSET_SHA256=abc", " ".join(plan.docker_argv))
        self.assertFalse(any("CC_SWITCH_" in a for a in plan.docker_argv))

    def test_run_build_result_carries_resolution(self):
        from aisc.cli.commands.build import plan_build, run_build

        plan = plan_build(self.root, tag="t:1", dry_run=True, cc_switch=self._resolved())

        class FakeExec:
            def preflight(self):
                class P:
                    available = True
                return P()

        result = run_build(
            plan,
            executor=FakeExec(),
            cc_switch_summary=self._resolved().to_manifest(),
            cc_switch_manifest_path="/x/m.json",
        )
        self.assertEqual(result.cc_switch["version"], "v5.10.1")
        self.assertEqual(result.cc_switch_manifest_path, "/x/m.json")
        self.assertIn("cc_switch", result.to_dict())


if __name__ == "__main__":
    unittest.main()
