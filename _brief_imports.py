"""Hidden-import anchor for PyInstaller frozen builds.

PyInstaller's static analysis traces imports from the entrypoint
(entrypoint.py → aisc.cli.main).  In frozen mode, ``_cmd_brief()``
dynamically loads ``apps/ai-brief/brief.py`` via
``importlib.util.spec_from_file_location``, so PyInstaller cannot see
brief.py's imports.

This module explicitly imports every stdlib module that brief.py needs,
making them visible to PyInstaller's dependency collector.  It is
imported by ``entrypoint.py`` at build time and has **zero runtime
side-effects** — no network, no brief logic, no prints.

Keep this list synchronised with ``apps/ai-brief/brief.py`` top-level
imports.  When brief.py gains or removes an import, update this module.

Design rationale:
  - A single dedicated anchor module is minimal, auditable, and
    cross-platform (unlike long --hidden-import flags in workflow YAML).
  - Explicit imports are unambiguous (unlike --collect-all which would
    bloat the onefile with unnecessary transitive deps).
  - Placed at the project root for clean import without clashing with
    PyInstaller's own ``packaging`` dependency.
"""

# ------------------------------------------------------------------
# stdlib modules imported by apps/ai-brief/brief.py (top-level)
# ------------------------------------------------------------------
import argparse         # noqa: F401  — CLI argument parsing
import concurrent.futures  # noqa: F401  — ThreadPoolExecutor
import gzip             # noqa: F401  — Content-Encoding: gzip
import html             # noqa: F401  — html.unescape (aliased as ihtml)
import json             # noqa: F401  — JSON encode / decode
import os               # noqa: F401  — filesystem, env
import re               # noqa: F401  — regex matching
import socket           # noqa: F401  — timeout exception type
import sys              # noqa: F401  — stdout, exit
import time             # noqa: F401  — sleep, monotonic, localtime
import urllib.error     # noqa: F401  — HTTPError, URLError
import urllib.request   # noqa: F401  — urlopen, Request
import xml.etree.ElementTree  # noqa: F401  — RSS / sitemap parsing
import zlib             # noqa: F401  — Content-Encoding: deflate
import urllib.parse     # noqa: F401  — urlsplit (from import)
