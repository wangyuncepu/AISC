"""B-05 regression: the sidecar resize-file poll step.

The previous INLINE watch-loop assigned the closed-over ``last_size``
without ``nonlocal`` — Python scoped it to the thread function, so EVERY
iteration raised UnboundLocalError (swallowed by the broad except) and no
resize after the sidecar's initial read ever reached the container.
Terminals were stuck at their session-startup size forever.

``_poll_resize_step`` is the hoisted, unit-testable core; both interactive
paths (``docker_.RealDockerExecutor.open_interactive`` and
``docker_gateway.SdkGateway.open_interactive``) run it from a LOCAL copy of
the last size.
"""

import os

from aisc.adapters.docker_ import _poll_resize_step
from aisc.adapters.docker_gateway import _poll_resize_step as _gw_step


def test_changed_size_applies_and_updates(tmp_path):
    f = tmp_path / "size.txt"
    f.write_text("120 30\n")
    applied = []
    last = _poll_resize_step(str(f), (80, 24), applied.append)
    assert last == (120, 30)
    assert applied == [(120, 30)]


def test_unchanged_size_is_a_no_op(tmp_path):
    f = tmp_path / "size.txt"
    f.write_text("120 30\n")
    applied = []
    last = _poll_resize_step(str(f), (120, 30), applied.append)
    assert last == (120, 30)
    assert applied == []


def test_consecutive_changes_all_apply(tmp_path):
    """The essence of the B-05 regression: the second change must apply too
    (the closure bug dropped everything after the first)."""
    f = tmp_path / "size.txt"
    applied = []
    last = (80, 24)
    for size in ((120, 30), (200, 50), (92, 15)):
        f.write_text(f"{size[0]} {size[1]}\n")
        last = _poll_resize_step(str(f), last, applied.append)
    assert applied == [(120, 30), (200, 50), (92, 15)]
    assert last == (92, 15)


def test_missing_or_garbage_file_is_tolerated(tmp_path):
    applied = []
    # Missing file.
    last = _poll_resize_step(str(tmp_path / "gone.txt"), (80, 24), applied.append)
    assert last == (80, 24)
    assert applied == []
    # Garbage content (torn write between Rust truncate and write).
    f = tmp_path / "size.txt"
    f.write_text("")
    assert _poll_resize_step(str(f), (80, 24), applied.append) == (80, 24)
    f.write_text("not a number pair\n")
    assert _poll_resize_step(str(f), (80, 24), applied.append) == (80, 24)
    assert applied == []


def test_gateway_imports_the_same_step():
    assert _gw_step is _poll_resize_step
