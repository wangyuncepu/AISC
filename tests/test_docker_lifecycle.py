"""docker-resource-lifecycle A1-A3: ownership classification + cleanup matrix.

One test per 04-acceptance §1 row: labeled resources recognized; legacy
evidence (registry / name patterns) recognized; unverified NEVER deleted;
containers before images; per-resource failure continues; docker
unavailable refuses; image IDs deduped across tags; no system prune; no
volume/network argv ever. All against a machine-format fake executor.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

from aisc.application.docker_lifecycle import (
    classify_containers,
    classify_images,
    docker_cleanup,
    docker_rebuild,
    docker_scan,
)
from aisc.domain.models import CliError, ProcessResult


def ps_row(name, image="super-claude:latest", status="Up 2 hours",
           managed="", kind="", owner=""):
    return {
        "id": f"cid-{name[:8]}", "name": name, "image": image,
        "status": status, "managed": managed, "kind": kind, "owner": owner,
    }


def image_row(repo, tag, img_id, labels=None):
    return {
        "repository": repo, "tag": tag, "id": img_id,
        "ref": f"{repo}:{tag}" if tag != "<none>" else "",
        "_labels": labels or {},  # fake-side only: drives the label filter
    }


class LifecycleFakeExecutor:
    """Machine-format fake: ps/images templates + stop/rm/rmi/build/inspect."""

    def __init__(self, *, available=True, containers=None, images=None):
        self.available = available
        self.containers: List[Dict[str, str]] = list(containers or [])
        self.images: List[Dict[str, Any]] = list(images or [])
        self.calls: List[List[str]] = []
        self.fail_rm: set = set()
        self.fail_rmi: set = set()

    # -- probes ---------------------------------------------------------------

    def preflight(self):
        class R:
            pass
        r = R()
        r.available = self.available
        return r

    def run_captured(self, argv, timeout=None):
        cmd = argv[0]
        self.calls.append(argv)
        if cmd == "ps":
            lines = []
            for c in self.containers:
                lines.append("\t".join([
                    c["id"], c["name"], c["image"], c["status"],
                    c.get("managed", ""), c.get("kind", ""), c.get("owner", ""),
                ]))
            return ProcessResult(exit_code=0, stdout="\n".join(lines))
        if cmd == "images":
            rows = self.images
            flt = argv[argv.index("--filter") + 1] if "--filter" in argv else ""
            if flt == "label=org.aisc.managed=true":
                rows = [i for i in rows if i.get("_labels", {}).get("org.aisc.managed") == "true"]
            elif flt == "dangling=true":
                rows = [i for i in rows if i["repository"] == "<none>"]
            fmt = argv[argv.index("--format") + 1] if "--format" in argv else ""
            if fmt == "{{.ID}}":
                return ProcessResult(exit_code=0, stdout="\n".join(i["id"] for i in rows))
            lines = ["\t".join([im["repository"], im["tag"], im["id"]]) for im in rows]
            return ProcessResult(exit_code=0, stdout="\n".join(lines))
        if cmd == "stop":
            for c in self.containers:
                if c["name"] == argv[-1]:
                    c["status"] = "Exited (0) 1s ago"
            return ProcessResult(exit_code=0)
        if cmd in ("rm", "rmi"):
            target = argv[-1] if argv[-2] != "-f" else argv[-1]
            fails = self.fail_rm if cmd == "rm" else self.fail_rmi
            if target in fails:
                return ProcessResult(exit_code=1, stderr="docker: driver refuses")
            if cmd == "rm":
                before = len(self.containers)
                self.containers = [c for c in self.containers if c["name"] != target]
                if len(self.containers) == before:
                    return ProcessResult(exit_code=1, stderr="Error: No such container")
                return ProcessResult(exit_code=0)
            before = len(self.images)
            self.images = [i for i in self.images
                           if i["id"] != target and i.get("ref") != target]
            if len(self.images) == before:
                return ProcessResult(exit_code=1, stderr="Error: No such image")
            return ProcessResult(exit_code=0)
        if cmd == "build":
            # Real-docker semantics: retagging leaves the displaced image
            # dangling (present by ID), not deleted.
            kept = []
            for i in self.images:
                if i.get("ref") == "super-claude:latest":
                    kept.append(image_row("<none>", "<none>", i["id"], i.get("_labels")))
                else:
                    kept.append(i)
            self.images = kept
            self.images.append(image_row("super-claude", "latest", "sha256:newimg"))
            return ProcessResult(exit_code=0, stdout="Step 1/3 : FROM node\nOK\n")
        if cmd == "image":
            for im in self.images:
                if im.get("ref") == argv[2] or im["id"] == argv[2]:
                    return ProcessResult(exit_code=0, stdout=im["id"])
            return ProcessResult(exit_code=1, stderr="Error: No such image")
        raise AssertionError(f"unexpected argv {argv}")


class ClassifyTests(unittest.TestCase):
    def test_labeled_registry_and_name_evidence(self):
        rows = [
            ps_row("aisc-wb-1", managed="true", kind="runtime", owner="workbench"),
            ps_row("aisc-wb-2"),                       # legacy name
            ps_row("super-claude-station-x3", image="super-claude:v1"),
            ps_row("reg-evidence"),                    # in registry (below)
            ps_row("super-claude-mine"),               # similar name → unverified
            ps_row("plain-nginx", image="nginx:1"),    # not ours → absent
        ]
        buckets = classify_containers(rows, {"reg-evidence": {"runtime_id": "r"}})
        self.assertEqual([b["name"] for b in buckets["owned"]], ["aisc-wb-1"])
        self.assertEqual(
            sorted(b["name"] for b in buckets["legacy_owned"]),
            ["aisc-wb-2", "reg-evidence", "super-claude-station-x3"],
        )
        self.assertEqual([b["name"] for b in buckets["unverified"]], ["super-claude-mine"])

    def test_image_tiers_depend_on_context(self):
        owned = image_row("super-claude", "latest", "sha256:aa", {"org.aisc.managed": "true"})
        legacy = image_row("super-claude", "latest", "sha256:bb")
        custom = image_row("super-claude", "v1.2", "sha256:cc")
        rows = [owned, legacy, custom]
        buckets, _ = classify_images(
            rows, context="upgrade",
            owned_ids=[i["id"] for i in rows if i["_labels"].get("org.aisc.managed")],
            dangling_ids=[],
        )
        self.assertEqual(buckets["owned"][0]["id"], "sha256:aa")
        self.assertEqual(buckets["legacy_owned"][0]["id"], "sha256:bb")
        self.assertEqual(buckets["unverified"][0]["image"], "super-claude:v1.2")
        # first install: the unlabeled default tag is UNVERIFIED, not legacy.
        buckets2, _ = classify_images([legacy], context="first_install")
        self.assertEqual(buckets2["unverified"][0]["image"], "super-claude:latest")

    def test_dangling_with_old_id_evidence(self):
        labeled = image_row("<none>", "<none>", "sha256:dd", {"org.aisc.managed": "true"})
        evidence = image_row("<none>", "<none>", "sha256:ee")
        rows = [labeled, evidence]
        _, dangling = classify_images(
            rows, context="upgrade",
            owned_ids=[i["id"] for i in rows if i["_labels"].get("org.aisc.managed")],
            dangling_ids=[i["id"] for i in rows if i["repository"] == "<none>"],
            old_image_ids=["sha256:ee"],
        )
        self.assertEqual({d["id"] for d in dangling}, {"sha256:dd", "sha256:ee"})


class CleanupTests(unittest.TestCase):
    def _owned_world(self):
        return LifecycleFakeExecutor(
            containers=[
                ps_row("aisc-wb-1", managed="true", owner="workbench"),
                ps_row("aisc-wb-2"),  # legacy, stopped
                ps_row("super-claude-mine"),  # unverified
                ps_row("untouched", image="nginx:1"),  # not ours
            ],
            images=[
                image_row("super-claude", "latest", "sha256:aa", {"org.aisc.managed": "true"}),
                image_row("nginx", "1", "sha256:ff"),
            ],
        )

    def test_cleanup_removes_owned_and_legacy_keeps_unverified(self):
        ex = self._owned_world()
        result = docker_cleanup(ex, context="uninstall", data_root=None)
        self.assertEqual(sorted(result["containers"]["removed"]), ["aisc-wb-1", "aisc-wb-2"])
        self.assertEqual(result["images"]["removed"], ["super-claude:latest"])
        # unverified reported, untouched; nginx never even listed
        self.assertEqual(result["skipped_unverified"], ["super-claude-mine"])
        self.assertEqual([c["name"] for c in ex.containers], ["super-claude-mine", "untouched"])
        self.assertEqual([i["id"] for i in ex.images], ["sha256:ff"])
        # safety: no prune / volume / network argv ever issued
        flat = [" ".join(a) for a in ex.calls]
        self.assertFalse(any("prune" in f or "volume" in f or "network" in f for f in flat))

    def test_container_failure_continues_to_next_resource(self):
        ex = self._owned_world()
        ex.fail_rm = {"aisc-wb-1"}
        result = docker_cleanup(ex, context="uninstall", data_root=None)
        self.assertEqual(result["containers"]["failed"], ["aisc-wb-1"])
        self.assertEqual(result["containers"]["removed"], ["aisc-wb-2"])
        self.assertEqual(result["images"]["removed"], ["super-claude:latest"])

    def test_docker_unavailable_refuses(self):
        ex = LifecycleFakeExecutor(available=False)
        with self.assertRaises(CliError):
            docker_cleanup(ex, context="uninstall", data_root=None)
        self.assertEqual(ex.calls, [])  # zero Docker mutations attempted

    def test_containers_before_images(self):
        ex = self._owned_world()
        docker_cleanup(ex, context="uninstall", data_root=None)
        kinds = [a[0] for a in ex.calls if a[0] in ("rm", "rmi")]
        self.assertEqual(kinds, ["rm", "rm", "rmi"])

    def test_image_id_dedup_across_tags(self):
        ex = LifecycleFakeExecutor(
            images=[
                image_row("super-claude", "latest", "sha256:aa", {"org.aisc.managed": "true"}),
                image_row("super-claude", "extra", "sha256:aa", {"org.aisc.managed": "true"}),
            ],
        )
        result = docker_cleanup(ex, context="uninstall", data_root=None)
        rmi_calls = [a for a in ex.calls if a[0] == "rmi"]
        self.assertEqual(len(rmi_calls), 1)  # one delete per ID
        self.assertTrue(result["images"]["removed"])


class ScanTests(unittest.TestCase):
    def test_unavailable_reports_without_concluding(self):
        ex = LifecycleFakeExecutor(available=False)
        payload = docker_scan(ex, context="uninstall")
        self.assertFalse(payload["docker"]["available"])
        self.assertEqual(payload["containers"]["owned"], [])

    def test_envelope_shape(self):
        ex = self._world()
        payload = docker_scan(ex, context="uninstall")
        self.assertEqual(payload["schema_version"], "aisc.docker-scan/v1")
        self.assertEqual(payload["containers"]["owned"][0]["reason"], "label")
        self.assertEqual(payload["images"]["legacy_owned"][0]["reason"], "default-tag")

    def _world(self):
        return LifecycleFakeExecutor(
            containers=[ps_row("aisc-wb-1", managed="true", owner="workbench")],
            images=[image_row("super-claude", "latest", "sha256:aa")],
        )


class RebuildTests(unittest.TestCase):
    """Rebuild takes a BUNDLE root (container/Dockerfile + config/
    versions.env) and pins cc-switch from the resolver cache; tests inject
    cc_switch=None for the offline ARG-fallback path (no network)."""

    def _bundle(self, root: str) -> None:
        from pathlib import Path
        Path(root, "container").mkdir(parents=True, exist_ok=True)
        Path(root, "config").mkdir(parents=True, exist_ok=True)
        Path(root, "container", "Dockerfile").write_text(
            "FROM node:20-slim\n", encoding="utf-8")
        Path(root, "config", "versions.env").write_text(
            "NODE_IMAGE=node:20-slim\n", encoding="utf-8")

    def test_rebuild_success_handoff(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)
            ex = LifecycleFakeExecutor(
                images=[image_row("super-claude", "latest", "sha256:old")],
            )
            result = docker_rebuild(ex, root=root, old_image_id="sha256:old",
                                    cc_switch=None)
        self.assertFalse(result["failed"])
        self.assertEqual(result["new_image_id"], "sha256:newimg")
        self.assertTrue(result["image_changed"])
        self.assertEqual(result["old_image_action"], "removed")
        self.assertEqual(result["reconcile_hint"], "image_changed")
        # ARG fallback path recorded its warning
        self.assertTrue(any("cc-switch" in w for w in result["warnings"]))

    def test_rebuild_failure_keeps_old_image(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            self._bundle(root)
            ex = LifecycleFakeExecutor(
                images=[image_row("super-claude", "latest", "sha256:old")],
            )
            original = ex.run_captured

            def failing_build(argv, timeout=None):
                if argv[0] == "build":
                    return ProcessResult(exit_code=1, stderr="boom")
                return original(argv, timeout=timeout)

            ex.run_captured = failing_build
            result = docker_rebuild(ex, root=root, old_image_id="sha256:old",
                                    cc_switch=None)
        self.assertTrue(result["failed"])
        self.assertEqual(result["old_image_action"], "kept_referenced")
        # old image never removed on failure
        self.assertEqual([i["id"] for i in ex.images], ["sha256:old"])

    def test_rebuild_missing_bundle_is_usage_error(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            ex = LifecycleFakeExecutor()
            with self.assertRaises(CliError):
                docker_rebuild(ex, root=str(Path(root)), old_image_id="",
                               cc_switch=None)
            self.assertEqual(ex.calls, [])

    def test_scan_text_renderer_shape(self):
        from aisc.application.docker_lifecycle import render_scan_text
        payload = {
            "docker": {"available": True, "reason": "ok"},
            "containers": {"owned": [{"id": "cid1", "name": "aisc-wb-1"}],
                            "legacy_owned": [], "unverified": []},
            "images": {"owned": [], "legacy_owned": [
                {"id": "sha256:aa", "name": "super-claude:latest"}],
                "unverified": []},
            "dangling_owned": [],
        }
        text = render_scan_text(payload)
        lines = text.splitlines()
        self.assertEqual(lines[0], "docker available")
        self.assertIn("container owned cid1 aisc-wb-1", lines)
        self.assertIn("image legacy_owned sha256:aa super-claude:latest", lines)


class CliContractTests(unittest.TestCase):
    """Parser shapes for the installer-facing maintenance commands (B)."""

    def test_scan_parses_context_and_repeatable_old_ids(self):
        from aisc.cli.main import _build_parser
        args = _build_parser().parse_args([
            "maintenance", "docker-scan", "--context", "first_install",
            "--old-image-id", "sha256:a", "--old-image-id", "sha256:b",
        ])
        self.assertEqual(args.command, "maintenance")
        self.assertEqual(args.maintenance_command, "docker-scan")
        self.assertEqual(args.context, "first_install")
        self.assertEqual(args.old_image_id, ["sha256:a", "sha256:b"])

    def test_cleanup_defaults_to_uninstall_and_rebuild_requires_root(self):
        from aisc.cli.main import _build_parser
        args = _build_parser().parse_args(["maintenance", "docker-cleanup"])
        self.assertEqual(args.context, "uninstall")
        args2 = _build_parser().parse_args([
            "maintenance", "docker-rebuild", "--root", "C:/bundle",
            "--old-image-id", "sha256:old",
        ])
        self.assertEqual(args2.maintenance_command, "docker-rebuild")
        self.assertEqual(args2.tag, "super-claude:latest")
        self.assertTrue(args2.no_cache)
        with self.assertRaises(SystemExit):
            _build_parser().parse_args(["maintenance", "docker-rebuild"])


if __name__ == "__main__":
    unittest.main()
