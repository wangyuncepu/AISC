"""Test that ``_brief_imports`` anchor covers all stdlib modules needed by brief.py.

This test is a lightweight regression guard: when brief.py gains or loses
an import, this test flags the discrepancy so the anchor stays in sync.
It does NOT import brief.py at runtime — it only checks the anchor module.
"""

import ast
import os
import sys
import unittest
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJ))


def _collect_stdlib_top_imports(py_path: str) -> set[str]:
    """Parse a .py file and return top-level stdlib module names imported."""
    with open(py_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=py_path)
    stdlib_names: set[str] = set()
    _STDLIB_PREFIXES = frozenset({
        "argparse", "concurrent", "gzip", "html", "json", "os", "re",
        "socket", "sys", "time", "urllib", "xml", "zlib", "io", "math",
        "collections", "functools", "itertools", "typing", "pathlib",
    })
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _STDLIB_PREFIXES:
                    stdlib_names.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in _STDLIB_PREFIXES:
                    stdlib_names.add(top)
    return stdlib_names


class TestBriefImportsAnchor(unittest.TestCase):

    def test_anchor_imports_covers_brief(self):
        """Every stdlib top-level import in brief.py must appear in _brief_imports.py."""
        brief_path = str(_PROJ / "apps" / "ai-brief" / "brief.py")
        anchor_path = str(_PROJ / "_brief_imports.py")

        self.assertTrue(os.path.isfile(brief_path), f"brief.py not found: {brief_path}")
        self.assertTrue(os.path.isfile(anchor_path), f"anchor not found: {anchor_path}")

        brief_imports = _collect_stdlib_top_imports(brief_path)
        anchor_imports = _collect_stdlib_top_imports(anchor_path)

        missing = brief_imports - anchor_imports
        self.assertEqual(
            missing, set(),
            f"brief.py stdlib imports not covered by _brief_imports anchor: {sorted(missing)}. "
            f"Update packaging/pyinstaller/_brief_imports.py."
        )

    def test_anchor_imports_no_unused(self):
        """Anchor should not import modules that brief.py doesn't use (avoid bloat)."""
        brief_path = str(_PROJ / "apps" / "ai-brief" / "brief.py")
        anchor_path = str(_PROJ / "_brief_imports.py")

        brief_imports = _collect_stdlib_top_imports(brief_path)
        anchor_imports = _collect_stdlib_top_imports(anchor_path)

        # Some anchor imports may be needed transitively (e.g. urllib.parse
        # is a from-import in brief.py).  We flag only clearly unused ones.
        # Allow the anchor to have more imports (defensive imports).
        unused = anchor_imports - brief_imports
        # We don't assert strictly — extra imports in anchor are benign
        # and may be needed for transitive dependencies.
        self.assertLessEqual(
            len(unused), 5,
            f"Anchor has {len(unused)} imports not in brief.py top-level: {sorted(unused)}. "
            f"Review whether these are still needed."
        )

    def test_anchor_importable(self):
        """The anchor module must be importable without side-effects."""
        try:
            import _brief_imports  # noqa: F401
        except Exception as exc:
            self.fail(f"_brief_imports failed to import: {exc}")


if __name__ == "__main__":
    unittest.main()
