# PyInstaller spec for the AISC CLI sidecar binary.
#
# Build: python -m PyInstaller --noconfirm --clean packaging/aisc.spec
#
# One-file mode (single executable, no COLLECT). console=True on purpose:
# the CLI is a console tool - `aisc session open` runs interactively through
# the Workbench PTY (ConPTY on Windows), which needs a console subsystem
# child. Piped (non-interactive) spawns from the Workbench use
# CREATE_NO_WINDOW so no console flashes.

import sys
from pathlib import Path

# SPECPATH is the directory containing the spec (provided by PyInstaller).
# The spec lives in <repo>/packaging/, so the repo root is its parent.
REPO_ROOT = Path(SPECPATH).resolve().parent if "SPECPATH" in globals() else Path.cwd()

a = Analysis(
    [str(REPO_ROOT / "src" / "aisc" / "cli" / "main.py")],
    pathex=[str(REPO_ROOT / "src")],
    binaries=[],
    datas=[(str(REPO_ROOT / "VERSION"), ".")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter", "unittest"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="aisc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # console subsystem: required for PTY/ConPTY interactive sessions
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
