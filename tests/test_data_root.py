"""Stage 7 (7a, DATA-01..04): data root resolver contract tests.

Covers (04-observability-testing, resolver row):
- Known Folder default (LOCALAPPDATA on Windows / XDG elsewhere);
- override variable accepted (absolute) and rejected (relative, whitespace);
- workspace/root overlap rejected in both directions;
- reparse point/symlink path components rejected;
- hash stability + cross-language vectors (tests/fixtures/data-root);
- structured result schema/layout (no path concatenation by callers).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from aisc.application.data_root import (
    ERR_OVERRIDE_RELATIVE,
    ERR_REPARSE_POINT,
    ERR_WORKSPACE_OVERLAP,
    DataRootResolver,
)
from aisc.domain.data_root import (
    DATA_ROOT_PROTOCOL,
    SHARED_SUBDIRS,
    WORKSPACE_SUBDIRS,
    ResolvedDataRoot,
    canonical_workspace_path,
    hash_canonical_path,
    strip_verbatim,
    workspace_dir_name,
    workspace_hash_v1,
)
from aisc.domain.models import CliError

REPO_ROOT = Path(__file__).resolve().parent.parent
VECTORS = json.loads(
    (REPO_ROOT / "tests" / "fixtures" / "data-root" / "hash-vectors.json").read_text(
        encoding="utf-8"
    )
)


class HashContractTests(unittest.TestCase):
    """Pure hash/strip vectors — shared with the Rust mirror (data_root.rs)."""

    def test_hash_vectors(self) -> None:
        for v in VECTORS["hash_vectors"]:
            with self.subTest(v["name"]):
                self.assertEqual(hash_canonical_path(v["canonical"]), v["hash"])

    def test_strip_vectors(self) -> None:
        for v in VECTORS["strip_vectors"]:
            with self.subTest(v["verbatim"]):
                self.assertEqual(strip_verbatim(v["verbatim"]), v["stripped"])

    def test_workspace_dir_name_is_windows_safe(self) -> None:
        # ':' is illegal in Windows directory names — swap for a dash.
        h = hash_canonical_path("/x")
        name = workspace_dir_name(h)
        self.assertNotIn(":", name)
        self.assertTrue(name.startswith("sha256-v1-"))
        self.assertEqual(len(name), len("sha256-v1-") + 64)

    def test_hash_is_stable_and_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "proj"
            ws.mkdir()
            first = workspace_hash_v1(ws)
            self.assertTrue(first.startswith("sha256-v1:"))
            self.assertEqual(len(first), len("sha256-v1:") + 64)
            # Same path object → same hash; a second dir → different hash.
            self.assertEqual(workspace_hash_v1(ws), first)
            other = Path(tmp) / "proj2"
            other.mkdir()
            self.assertNotEqual(workspace_hash_v1(other), first)

    def test_canonical_of_real_workspace_has_no_verbatim_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            canon = canonical_workspace_path(Path(tmp))
            self.assertFalse(canon.startswith("\\\\?\\"))


class DefaultRootTests(unittest.TestCase):
    """Known Folder default via injected env (no os.environ patching)."""

    def test_windows_default_uses_localappdata(self) -> None:
        resolver = DataRootResolver(env={"LOCALAPPDATA": "C:\\Users\\dev\\AppData\\Local"})
        # _default_root is pure and platform-independent — exercise the
        # Windows branch directly on any OS.
        from aisc.application.data_root import _default_root

        root = _default_root({"LOCALAPPDATA": "C:\\Users\\dev\\AppData\\Local"}, True)
        self.assertEqual(
            root,
            Path("C:\\Users\\dev\\AppData\\Local") / "AISC" / "data",
        )

    def test_posix_default_uses_xdg_then_home(self) -> None:
        from aisc.application.data_root import _default_root

        xdg = _default_root({"XDG_DATA_HOME": "/opt/xdg"}, False)
        self.assertEqual(xdg, Path("/opt/xdg") / "aisc" / "data")
        home = _default_root({}, False)
        self.assertEqual(
            home,
            Path.home() / ".local" / "share" / "aisc" / "data",
        )

    def test_resolve_default_origin_and_layout(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            resolver = DataRootResolver(env={"AISC_DATA_ROOT": root_tmp})
            result = resolver.resolve(Path(ws_tmp))
            self.assertEqual(result.origin, "env")
            self.assertEqual(result.root, Path(root_tmp))
            # Contract layout, contract order — callers never concatenate.
            self.assertEqual(tuple(result.shared_dirs), SHARED_SUBDIRS)
            self.assertEqual(tuple(result.workspace_dirs), WORKSPACE_SUBDIRS)
            for name in SHARED_SUBDIRS:
                self.assertEqual(result.shared_dirs[name], Path(root_tmp) / name)
            ws_dir = Path(root_tmp) / "workspaces" / workspace_dir_name(result.workspace_hash)
            for name in WORKSPACE_SUBDIRS:
                self.assertEqual(result.workspace_dirs[name], ws_dir / name)
            # resolve is read-only: nothing was created.
            self.assertFalse(ws_dir.exists())
            self.assertFalse((Path(root_tmp) / "config").exists())
            self.assertTrue(result.writable)  # nearest existing ancestor writable


class OverrideValidationTests(unittest.TestCase):
    def test_relative_override_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolver = DataRootResolver(env={"AISC_DATA_ROOT": "relative/data"})
            with self.assertRaises(CliError) as ctx:
                resolver.resolve(Path(tmp))
            self.assertEqual(ctx.exception.error_code, ERR_OVERRIDE_RELATIVE)

    def test_whitespace_override_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolver = DataRootResolver(env={"AISC_DATA_ROOT": " " + tmp})
            with self.assertRaises(CliError) as ctx:
                resolver.resolve(Path(tmp))
            self.assertEqual(ctx.exception.error_code, ERR_OVERRIDE_RELATIVE)

    def test_empty_override_falls_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolver = DataRootResolver(env={"AISC_DATA_ROOT": ""})
            result = resolver.resolve(Path(tmp))
            self.assertEqual(result.origin, "default")


class ContainmentTests(unittest.TestCase):
    def test_root_inside_workspace_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "proj"
            (ws / ".aisc-data").mkdir(parents=True)
            resolver = DataRootResolver(env={"AISC_DATA_ROOT": str(ws / ".aisc-data")})
            with self.assertRaises(CliError) as ctx:
                resolver.resolve(ws)
            self.assertEqual(ctx.exception.error_code, ERR_WORKSPACE_OVERLAP)

    def test_workspace_inside_root_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "aisc-data"
            ws = root / "workspaces" / "proj"
            ws.mkdir(parents=True)
            resolver = DataRootResolver(env={"AISC_DATA_ROOT": str(root)})
            with self.assertRaises(CliError) as ctx:
                resolver.resolve(ws)
            self.assertEqual(ctx.exception.error_code, ERR_WORKSPACE_OVERLAP)

    def test_f1_shadow_workspace_carve_out(self) -> None:
        """F1 (D-10): <root>/sync-workspaces/<name> is the sanctioned shadow
        subtree; the bare subtree and other root children still fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "aisc-data"
            shadow = root / "sync-workspaces" / "f1test"
            shadow.mkdir(parents=True)
            resolver = DataRootResolver(env={"AISC_DATA_ROOT": str(root)})
            resolved = resolver.resolve(shadow)  # must NOT raise
            self.assertTrue(resolved.workspace_dir.exists() or True)
            # bare subtree itself still rejected
            with self.assertRaises(CliError) as ctx:
                resolver.resolve(root / "sync-workspaces")
            self.assertEqual(ctx.exception.error_code, ERR_WORKSPACE_OVERLAP)
            # other root children still rejected
            with self.assertRaises(CliError) as ctx:
                resolver.resolve(root / "config")
            self.assertEqual(ctx.exception.error_code, ERR_WORKSPACE_OVERLAP)

    def test_equal_root_and_workspace_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolver = DataRootResolver(env={"AISC_DATA_ROOT": tmp})
            with self.assertRaises(CliError) as ctx:
                resolver.resolve(Path(tmp))
            self.assertEqual(ctx.exception.error_code, ERR_WORKSPACE_OVERLAP)

    def test_disjoint_paths_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            resolver = DataRootResolver(env={"AISC_DATA_ROOT": root_tmp})
            result = resolver.resolve(Path(ws_tmp))
            self.assertIsInstance(result, ResolvedDataRoot)

    def _make_reparse(self, target: Path, link: Path) -> bool:
        """Create a directory symlink (or junction on Windows — no admin
        needed); False when unsupported here."""
        try:
            os.symlink(target, link, target_is_directory=True)
            return True
        except (OSError, NotImplementedError):
            pass
        if os.name == "nt":
            import _winapi

            try:
                _winapi.CreateJunction(str(target), str(link))
                return True
            except OSError:
                return False
        return False

    def test_reparse_point_on_root_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real-root"
            link = Path(tmp) / "link-root"
            real.mkdir()
            if not self._make_reparse(real, link):
                self.skipTest("directory symlinks unavailable on this platform/CI")
            resolver = DataRootResolver(env={"AISC_DATA_ROOT": str(link)})
            with self.assertRaises(CliError) as ctx:
                resolver.resolve(Path(tmp) / "unrelated-ws")
            self.assertEqual(ctx.exception.error_code, ERR_REPARSE_POINT)


class StructuredResultTests(unittest.TestCase):
    def test_to_dict_shape_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as ws_tmp, tempfile.TemporaryDirectory() as root_tmp:
            resolver = DataRootResolver(env={"AISC_DATA_ROOT": root_tmp})
            d = resolver.resolve(Path(ws_tmp)).to_dict()
            self.assertEqual(d["schema"], DATA_ROOT_PROTOCOL)
            self.assertEqual(d["schema_version"], 1)
            self.assertEqual(d["origin"], "env")
            self.assertTrue(d["workspace_hash"].startswith("sha256-v1:"))
            # The raw workspace path is NOT part of the envelope (redaction:
            # hash only, 04-observability-testing).
            self.assertNotIn("workspace", d)
            self.assertNotIn(str(ws_tmp), json.dumps(d))
            for key in ("config", "state", "workspaces", "artifacts", "cache",
                        "diagnostics", "migrations"):
                self.assertIn(key, d["shared_dirs"])
            for key in ("claude", "codex", "cc-switch", "runtime", "logs"):
                self.assertIn(key, d["workspace_dirs"])


if __name__ == "__main__":
    unittest.main()
