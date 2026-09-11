"""Global test isolation (2.1.11 P1 manual-test finding).

2026-09-10 audit: the real data root carried **3637 empty workspace
skeletons** (`workspaces/<hash>/{claude,codex,cc-switch,runtime,toolchain}`
with zero files). Root cause: isolation relied on per-file
`os.environ.setdefault("AISC_DATA_ROOT", …)` (the #53-era discipline), and
any test module without it — or running after a test that popped the
variable in tearDown — resolved temp workspaces against the REAL root,
where the container-prep mkdirs left skeletons behind.

This conftest makes isolation structural: one session-scoped autouse
fixture pins AISC_DATA_ROOT to a tempdir for every test in the tree,
re-asserting it before each test (individual tests may still override it
inside themselves — that is their business — but they can no longer
inherit "unset").

ruff: noqa: E402
"""

from __future__ import annotations

import os
import tempfile

import pytest

_ISOLATED_ROOT = os.environ.get("AISC_TEST_DATA_ROOT") or tempfile.mkdtemp(
    prefix="aisc-conftest-data-")
os.environ["AISC_DATA_ROOT"] = _ISOLATED_ROOT
# The config/ subdir satisfies the resolver's layout expectations.
os.makedirs(os.path.join(_ISOLATED_ROOT, "config"), exist_ok=True)


@pytest.fixture(autouse=True)
def _pin_isolated_data_root():
    """Re-assert the isolated root before EVERY test.

    A previous test's tearDown may have restored the env to "unset" (the
    #53 pattern), which would silently fall later modules back onto the
    real root — the exact leak this conftest exists to close.
    """
    previous = os.environ.get("AISC_DATA_ROOT")
    os.environ["AISC_DATA_ROOT"] = _ISOLATED_ROOT
    yield
    if previous is None:
        # Leave the pin in place: the next test gets re-pinned anyway, and
        # "unset" is never a state we want to hand back mid-session.
        os.environ["AISC_DATA_ROOT"] = _ISOLATED_ROOT
    else:
        os.environ["AISC_DATA_ROOT"] = previous
