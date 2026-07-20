#!/usr/bin/env python3
"""Offline smoke test for frozen brief — validates that brief.py's stdlib
imports are available in a PyInstaller build by running brief in-process
(via importlib, same path as frozen ``_cmd_brief``) with mocked HTTP
responses.  No real network, no credentials, no LLM calls.

Exits 0 on success.
"""

import io
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import importlib.util

_PROJ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJ))


# ====================================================================
# Mock HTTP responses — minimal but valid TLDR RSS + issue page
# ====================================================================

MOCK_TLDR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>TLDR AI</title>
<link>https://tldr.tech/ai</link>
<description>TLDR AI daily newsletter</description>
<item>
<title>MOCK TLDR AI 2026-07-20 — Offline Test Article</title>
<link>https://tldr.tech/ai/2026-07-20</link>
<guid>https://tldr.tech/ai/2026-07-20</guid>
</item>
</channel>
</rss>
"""

MOCK_ISSUE_HTML = """<html><body>
<article class="mt-3">
<a class="font-bold" href="https://example.com/offline-test-article">Offline Test: PyInstaller Frozen Brief Verification</a>
<h3>Frozen Brief Works</h3>
<div class="newsletter-html"><p>This article proves that the frozen brief import path correctly loads all stdlib dependencies.</p></div>
</article>
</body></html>
"""


def run_offline_brief() -> tuple[int, str, str]:
    """Load brief.py via importlib and run with mocked HTTP."""
    brief_path = str(_PROJ / "apps" / "ai-brief" / "brief.py")
    spec = importlib.util.spec_from_file_location("ai_brief_test", brief_path)
    assert spec is not None and spec.loader is not None, f"Failed to load: {brief_path}"
    module = importlib.util.module_from_spec(spec)

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()

    # Mock http_get_cached: serve our canned content based on URL
    def _mock_http_get_cached(url, cache_key, timeout=6, deadline=None):
        if "tldr.tech/api/rss" in url or "/rss" in url:
            return MOCK_TLDR_RSS
        if "/ai/2026-07-20" in url:
            return MOCK_ISSUE_HTML
        raise RuntimeError(f"Unexpected URL in mock: {url}")

    sys.stdout = captured_stdout
    sys.stderr = captured_stderr
    try:
        spec.loader.exec_module(module)
        # Patch http_get_cached on the loaded module
        with patch.object(module, "http_get_cached", side_effect=_mock_http_get_cached):
            exit_code = module.main(
                argv=["--source", "tldr", "--no-cache", "--strict"]
            )
    finally:
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

    return exit_code, captured_stdout.getvalue(), captured_stderr.getvalue()


def main() -> int:
    print("=== Frozen Brief Offline Smoke Test ===")
    print(f"Project root: {_PROJ}")
    print()

    # Step 1: verify anchor is importable
    try:
        import _brief_imports  # noqa: F401
        print("PASS: _brief_imports anchor importable")
    except Exception as exc:
        print(f"FAIL: _brief_imports anchor not importable: {exc}")
        return 1

    # Step 2: run offline brief
    print("Running brief.py via importlib with mocked HTTP (no real network)...")
    exit_code, stdout, stderr = run_offline_brief()

    print(f"  exit code: {exit_code}")
    if stdout.strip():
        print(f"  stdout ({len(stdout)} bytes):")
        for line in stdout.strip().splitlines()[:15]:
            print(f"    {line}")
    else:
        print("  stdout: (empty)")

    if stderr.strip():
        print(f"  stderr: {stderr[:300]}")

    # Validate
    errors = []
    if exit_code != 0:
        errors.append(f"Expected exit 0, got {exit_code}")

    if "Frozen Brief Works" not in stdout and "Offline Test" not in stdout:
        errors.append("Output missing expected mock article content")
    if "ModuleNotFoundError" in stderr or "ModuleNotFoundError" in stdout:
        errors.append("ModuleNotFoundError present — hidden imports still missing!")
    if "Traceback" in stderr:
        errors.append(f"Traceback in stderr — import or execution failed")

    if errors:
        print()
        for e in errors:
            print(f"FAIL: {e}")
        return 1

    print()
    print("PASS: frozen brief smoke — brief ran successfully via importlib,")
    print("      generated output from mock data, no ModuleNotFoundError.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
