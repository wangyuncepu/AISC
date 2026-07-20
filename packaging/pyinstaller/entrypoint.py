"""PyInstaller entry-point script.

Called by PyInstaller to bootstrap the frozen application.
Allows ``aisc.cli.main:main`` to work correctly in a onefile build.
"""

# ------------------------------------------------------------------
# Hidden-import anchors: PyInstaller statically traces imports from
# this entrypoint.  Modules imported here but not directly reachable
# from ``aisc.cli.main`` (e.g. dynamically loaded scripts like
# ai-brief/brief.py) must be listed explicitly so their dependencies
# are collected into the onefile bundle.
# ------------------------------------------------------------------
from aisc.cli.main import main       # primary entry
import _brief_imports  # noqa: F401 — brief stdlib deps (at project root)

if __name__ == "__main__":
    main()
