"""PyInstaller entry-point script.

Called by PyInstaller to bootstrap the frozen application.
Allows ``aisc.cli.main:main`` to work correctly in a onefile build.
"""

import sys

# ------------------------------------------------------------------
# Hidden-import anchors: PyInstaller statically traces imports from
# this entrypoint.  Modules imported here but not directly reachable
# from ``aisc.cli.main`` (e.g. dynamically loaded scripts like
# ai-brief/brief.py) must be listed explicitly so their dependencies
# are collected into the onefile bundle.
# ------------------------------------------------------------------
from aisc.cli.main import main       # primary entry
import _brief_imports  # noqa: F401 — brief stdlib deps (at project root)


def _configure_frozen_io() -> None:
    """Ensure Windows frozen processes use UTF-8 for stdout/stderr.

    PyInstaller-bundled Windows CLI can produce non-UTF-8 output when
    captured by PowerShell, causing encoding errors downstream (e.g.
    JSON parsing failures for provider data containing CJK characters).

    This is a narrow, defensive fix: it only activates on Windows when
    ``sys.frozen`` is truthy, and handles every known edge case
    gracefully (streams are None, Python < 3.7 without reconfigure,
    or reconfigure raising an exception).
    """
    try:
        # Only applicable to frozen Windows processes.
        if sys.platform != "win32":
            return
        if not getattr(sys, "frozen", False):
            return

        for stream_name, stream in (
            ("stdout", sys.stdout),
            ("stderr", sys.stderr),
        ):
            if stream is None:
                continue
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is None:          # Python < 3.7 or not a TextIOWrapper
                continue
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                # Never let a failed reconfigure crash the CLI.
                pass
    except Exception:
        pass                                 # safety net for any unexpected failure


_configure_frozen_io()

if __name__ == "__main__":
    main()
