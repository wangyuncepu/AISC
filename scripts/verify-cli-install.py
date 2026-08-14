#!/usr/bin/env python3
"""CLI-A01 clean-room install verification for the aisc CLI.

Builds the wheel and sdist, installs each into a FRESH venv, and asserts:

- the console-script entry point and ``python -m aisc`` both run
  ``version --format json`` with exit 0 and a well-formed ``aisc.cli/v1``
  envelope whose reported version matches the repo ``VERSION``;
- the installed dist metadata (``importlib.metadata.version``) matches the
  reported ``cli_version`` (CLI-R01: no version drift between wheel and CLI);
- a repeat ``--force-reinstall`` and an uninstall→reinstall round-trip both
  leave the entry point working (CLI-A01: repeated install is recoverable);
- when ``pipx`` is available, ``pipx install --force`` into an isolated
  ``PIPX_HOME``/``PIPX_BIN_DIR`` also yields a working entry point.

Artifacts are built into ``--build-dir`` (default: a temp dir, kept on
failure via ``--keep``). Use ``--offline-deps-dir`` to install with
``--no-index`` from a pre-populated wheel dir (offline smoke).

Exit 0 on full PASS; non-zero with a diagnostic line on any failure.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = "aisc.cli/v1"
REQUIRED_CAPS = {"runtime", "session", "providerStatus", "buildEvents"}


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _run(argv: list[str | Path], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    argv = [str(a) for a in argv]
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=cwd)
    if check and proc.returncode != 0:
        _fail(f"command failed ({proc.returncode}): {' '.join(argv)}\n"
              f"  stdout: {proc.stdout[-2000:]}\n  stderr: {proc.stderr[-2000:]}")
    return proc


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _venv_entry(venv: Path) -> Path:
    return venv / ("Scripts/aisc.exe" if sys.platform == "win32" else "bin/aisc")


def _assert_envelope(stdout: str, expected_version: str, *, context: str) -> None:
    env = json.loads(stdout)
    meta, data, errors = env["meta"], env["data"], env["errors"]
    if meta["protocol"] != PROTOCOL:
        _fail(f"[{context}] protocol mismatch: {meta['protocol']!r}")
    if meta["command"] != "version":
        _fail(f"[{context}] unexpected command: {meta['command']!r}")
    if meta["exit_code"] != 0:
        _fail(f"[{context}] exit_code {meta['exit_code']} != 0")
    if meta["version"] != expected_version:
        _fail(f"[{context}] meta.version {meta['version']!r} != expected {expected_version!r}")
    if data.get("cli_version") != expected_version:
        _fail(f"[{context}] cli_version {data.get('cli_version')!r} != expected {expected_version!r}")
    if data.get("bundle_version") != expected_version:
        _fail(f"[{context}] bundle_version {data.get('bundle_version')!r} != expected {expected_version!r}")
    caps = data.get("capabilities") or {}
    missing = REQUIRED_CAPS - set(caps)
    if missing:
        _fail(f"[{context}] missing capabilities: {sorted(missing)}")
    if errors:
        _fail(f"[{context}] unexpected errors: {errors}")


def _assert_dist_version(venv: Path, expected_version: str, *, context: str) -> None:
    proc = _run(
        [_venv_python(venv), "-c", "from importlib import metadata; print(metadata.version('aisc'))"],
    )
    if proc.stdout.strip() != expected_version:
        _fail(f"[{context}] dist metadata {proc.stdout.strip()!r} != expected {expected_version!r}")


def install_verify(
    artifact: Path,
    expected_version: str,
    *,
    keep_dir: Path | None,
    offline_deps: Path | None,
    label: str,
    is_sdist: bool = False,
) -> None:
    print(f"== [{label}] installing {artifact.name} into fresh venv ==")
    with tempfile.TemporaryDirectory(prefix=f"aisc-verify-{label}-") as tmp:
        venv = Path(tmp) / "venv"
        _run([sys.executable, "-m", "venv", str(venv)])
        py = _venv_python(venv)

        base_args = [py, "-m", "pip", "install", "--quiet"]
        if offline_deps is not None:
            base_args += ["--no-index", "--find-links", str(offline_deps)]
        install_args = list(base_args)
        if is_sdist and offline_deps is not None:
            # An sdist must be built; the fresh venv has no build backend, and
            # pip's isolated build env cannot reach the network. Install the
            # build-system requirements from the offline dir first, then build
            # the sdist without isolation.
            _run(base_args + ["setuptools", "wheel"])
            install_args += ["--no-build-isolation"]
        install_args += [str(artifact)]
        _run(install_args)

        # console-script entry point
        out = _run([_venv_entry(venv), "version", "--format", "json"]).stdout
        _assert_envelope(out, expected_version, context=f"{label}:console-script")
        # python -m aisc
        out = _run([py, "-m", "aisc", "version", "--format", "json"]).stdout
        _assert_envelope(out, expected_version, context=f"{label}:python -m")
        _assert_dist_version(venv, expected_version, context=label)

        # repeat install (force-reinstall) is recoverable
        print(f"== [{label}] repeat install (--force-reinstall) ==")
        _run(install_args + ["--force-reinstall"])
        out = _run([_venv_entry(venv), "version", "--format", "json"]).stdout
        _assert_envelope(out, expected_version, context=f"{label}:reinstall")

        # uninstall -> entry gone -> reinstall works again
        print(f"== [{label}] uninstall -> reinstall round-trip ==")
        _run([py, "-m", "pip", "uninstall", "--quiet", "-y", "aisc"])
        try:
            gone = subprocess.run([_venv_entry(venv), "version"], capture_output=True)
        except FileNotFoundError:
            gone = None  # entry point removed — expected
        if gone is not None and gone.returncode == 0:
            _fail(f"[{label}] entry point still runs after uninstall")
        _run(install_args)
        out = _run([_venv_entry(venv), "version", "--format", "json"]).stdout
        _assert_envelope(out, expected_version, context=f"{label}:round-trip")
    print(f"== [{label}] PASS ==")


def pipx_verify(artifact: Path, expected_version: str) -> None:
    pipx = shutil.which("pipx")
    if pipx is None:
        print("== pipx not found; skipping pipx smoke ==")
        return
    print(f"== [pipx] installing {artifact.name} into isolated PIPX_HOME ==")
    with tempfile.TemporaryDirectory(prefix="aisc-verify-pipx-") as tmp:
        home = Path(tmp) / "pipx"
        bindir = Path(tmp) / "bin"
        env = dict(
            os.environ.copy(),
            PIPX_HOME=str(home),
            PIPX_BIN_DIR=str(bindir),
        )

        def px(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run([pipx, *args], capture_output=True, text=True, env=env, check=False)

        r = px("install", "--force", str(artifact))
        if r.returncode != 0:
            _fail(f"[pipx] install failed: {r.stdout[-1000:]} {r.stderr[-1000:]}")
        entry = bindir / ("aisc.exe" if sys.platform == "win32" else "aisc")
        out = _run([str(entry), "version", "--format", "json"]).stdout
        _assert_envelope(out, expected_version, context="pipx")
        # reinstall (upgrade path) is recoverable
        r = px("install", "--force", str(artifact))
        if r.returncode != 0:
            _fail(f"[pipx] reinstall failed: {r.stdout[-1000:]} {r.stderr[-1000:]}")
        out = _run([str(entry), "version", "--format", "json"]).stdout
        _assert_envelope(out, expected_version, context="pipx:reinstall")
    print("== [pipx] PASS ==")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build-dir", type=Path, default=None, help="dir to build into (default: temp)")
    ap.add_argument("--keep", action="store_true", help="keep the build dir on failure")
    ap.add_argument("--offline-deps-dir", type=Path, default=None,
                    help="pre-populated wheel dir; install with --no-index")
    ap.add_argument("--skip-pipx", action="store_true", help="skip the pipx smoke")
    args = ap.parse_args()

    expected = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()

    built = args.build_dir or Path(tempfile.mkdtemp(prefix="aisc-build-"))
    if args.build_dir is None:
        print(f"== building wheel+sdist into {built} ==")
        _run([sys.executable, "-m", "build", "--outdir", str(built)], cwd=REPO_ROOT)
    else:
        built = built.resolve()

    wheels = sorted(built.glob("*.whl"))
    sdists = sorted(built.glob("*.tar.gz"))
    if not wheels:
        _fail(f"no wheel found in {built}")
    if not sdists:
        _fail(f"no sdist found in {built}")
    wheel = wheels[0]
    sdist = sdists[0]

    offline = args.offline_deps_dir
    try:
        install_verify(wheel, expected, keep_dir=built, offline_deps=offline, label="wheel")
        install_verify(sdist, expected, keep_dir=built, offline_deps=offline, label="sdist",
                       is_sdist=True)
        if not args.skip_pipx:
            pipx_verify(wheel, expected)
    except SystemExit:
        if args.keep:
            print(f"== artifacts kept in {built} ==", file=sys.stderr)
        raise

    if args.build_dir is None and not args.keep:
        shutil.rmtree(built, ignore_errors=True)
    print("CLI-A01 PASS: clean venv + pipx + repeat-install verified")


if __name__ == "__main__":
    main()
