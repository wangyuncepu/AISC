#!/usr/bin/env python
"""Personal-tool Windows smoke test for S5.3 secure store (currently-wired public API).

Usage::

    python tests/manual/smoke_s5_3_windows.py --output-dir PATH
    PYTHONPATH=src python tests/manual/smoke_s5_3_windows.py --output-dir PATH

Non-Windows: writes evidence JSON, prints BLOCKED, exits 2.
Windows: runs Q1–Q5 against ``ensure_secure_directory``, ``create_private_file``,
``SecureStorePermissionError``.  No retained-handle path, no production claim.
"""

from __future__ import annotations

import argparse, datetime, json, os, platform as _platform, subprocess, sys, tempfile, traceback
from pathlib import Path
from typing import Any, List

# Bootstrap: insert repo src/ so import works without PYTHONPATH
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = str(_REPO_ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from aisc.adapters.secret_store import (  # noqa: E402
    SecureStorePermissionError, create_private_file, ensure_secure_directory,
)

SCHEMA_VERSION = "s5.3-personal-smoke-1"

# ---------------------------------------------------------------------------
# Row + evidence helpers (compact)
# ---------------------------------------------------------------------------

class Row:
    __slots__ = ("id", "status", "operation", "exception", "observed")
    def __init__(self, qid: str):
        self.id = qid; self.status = "BLOCKED"; self.operation = ""
        self.exception: str | None = None; self.observed: List[str] = []
    def ok(self, msg=""):      self.status = "PASS";     msg and self.observed.append(msg)
    def fail(self, exc, obs=""): self.status = "FAIL"; self.exception = exc; obs and self.observed.append(obs)
    def blocked(self, reason): self.status = "BLOCKED"; self.observed.append(reason)
    def to_dict(self) -> dict:
        return {"id": self.id, "status": self.status, "operation": self.operation,
                "exception": self.exception, "observed": self.observed}

def _overall(rows):  # noqa: ANN001
    ss = {r.status for r in rows}
    return "FAIL" if "FAIL" in ss else ("BLOCKED" if "BLOCKED" in ss else "PASS")

_EXIT_MAP = {"FAIL": 1, "BLOCKED": 2}

def _make_evidence(rows, overall, cleanup_errs, now):  # noqa: ANN001
    return {
        "schema_version": SCHEMA_VERSION, "platform": _platform.platform(),
        "python": _platform.python_version(), "timestamp": now,
        "backend": {"scope": "currently_wired_public_api", "retained_handle": "intentionally_unwired"},
        "rows": rows, "cleanup_errors": cleanup_errs or None, "overall": overall,
        "limitations": ["No TOCTOU/race closure testing", "No retained-handle proof", "No production-safety claim"],
    }

def _write_json(path, obj):  # noqa: ANN001
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
    with open(path, "ab") as fh:
        fh.write(b"\n")

def _hex(path):  # noqa: ANN001
    with open(path, "rb") as fh: return fh.read().hex()

# ---------------------------------------------------------------------------
# Filesystem safety helpers
# ---------------------------------------------------------------------------

def _rmdir_nofollow(p: str) -> str | None:
    """Remove *p* non-followingly. Returns error string or None."""
    if not p or not os.path.lexists(p): return None
    try:
        if os.name == "nt":
            cp = subprocess.run(
                ["cmd", "/c", "rmdir", p], capture_output=True, text=True, timeout=15,
            )
            if cp.returncode != 0:
                return f"cmd rmdir failed rc={cp.returncode} stderr={cp.stderr!r}"
        else:
            (os.unlink if os.path.islink(p) else os.rmdir)(p)
    except Exception as exc:
        return f"_rmdir_nofollow({p!r}): {exc}"
    return None


def _is_reparse(path: str) -> bool:
    """Symlink (all platforms) or Windows reparse point (FILE_ATTRIBUTE_REPARSE_POINT=0x400)."""
    if os.path.islink(path): return True
    if os.name == "nt":
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & 0x400)
    return False


def _safe_rmtree(root: str, errors_out: List[str]) -> None:
    """Recurse safely: remove reparse/symlink non-followingly, never traverse them."""
    try:
        with os.scandir(root) as it:
            for entry in it:
                p = entry.path
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if _is_reparse(p):
                            e = _rmdir_nofollow(p)
                            if e: errors_out.append(e)
                        else:
                            _safe_rmtree(p, errors_out)
                    else:
                        os.unlink(p)
                except OSError as exc:
                    errors_out.append(f"unlink/rmdir {p}: {exc}")
        os.rmdir(root)
    except OSError as exc:
        errors_out.append(f"rmdir {root}: {exc}")


# ---------------------------------------------------------------------------
# Q1 – Normal use (fd-safe: close exactly once)
# ---------------------------------------------------------------------------

def _q1(work: str) -> Row:
    r = Row("Q1-normal-use")
    r.operation = "ensure_secure_directory + create_private_file + write/read/close"
    fd = -1
    try:
        sec = os.path.join(work, "sec dir \u2603")
        ensure_secure_directory(sec)
        leaf = "s\u00e9cret \u2620.txt"
        fd = create_private_file(sec, leaf)
        payload = b"Q1-hello-world-\xf0\x9f\x94\x92"
        os.write(fd, payload)
        os.close(fd)
        fd = -1
        fp = os.path.join(sec, leaf)
        if not os.path.isfile(fp): r.fail("FileNotFound", str(fp)); return r
        got = _hex(fp)
        if got != payload.hex(): r.fail("PayloadMismatch", f"want={payload.hex()} got={got}"); return r
        r.observed.append("secure dir + leaf OK, content matches")
        r.ok()
    except Exception as exc:
        r.fail(f"{type(exc).__name__}: {exc}", traceback.format_exc())
    finally:
        if fd >= 0:
            try: os.close(fd)
            except OSError as exc:
                (r.fail if r.status != "FAIL" else r.observed.append)(f"close fd failed: {exc}")
    return r


# ---------------------------------------------------------------------------
# Q2 – Permission/DACL sanity
# ---------------------------------------------------------------------------

def _q2(work: str) -> Row:
    r = Row("Q2-permission-sanity")
    r.operation = "ensure_secure_directory again (existing dir re-validation)"
    try:
        sec = os.path.join(work, "sec dir \u2603")
        if not os.path.isdir(sec): r.blocked("No Q1 dir"); return r
        ensure_secure_directory(sec)
        r.observed.append("re-validate OK")
        if os.name == "nt":
            try:
                cp = subprocess.run(["icacls", sec], capture_output=True, text=True, timeout=10)
                r.observed.append(f"icacls: {cp.stdout[:200]}")
            except Exception as ce:
                r.observed.append(f"icacls unavailable: {ce}")
        r.ok()
    except Exception as exc:
        r.fail(f"{type(exc).__name__}: {exc}", traceback.format_exc())
    return r


# ---------------------------------------------------------------------------
# Q3 – Junction rejection (fail-closed cleanup via finally)
# ---------------------------------------------------------------------------

def _q3(work: str) -> Row:
    r = Row("Q3-junction-rejection")
    r.operation = "mklink /J inside secure dir; ensure_secure_directory on junction"
    if os.name != "nt": r.blocked("Windows only"); return r

    sec = os.path.join(work, "sec dir \u2603")
    outside = os.path.join(work, "_outside_q3")
    junc = os.path.join(sec, "_junc_q3")
    otgt = os.path.join(outside, "should-not-touch.txt")
    known = b"OUTSIDE-DATA-Q3-unchanged"
    junc_created = False
    pre: set | None = None

    # Phase 0: outside dir (no junction, no cleanup needed)
    try:
        os.makedirs(outside, exist_ok=True)
        with open(otgt, "wb") as fh: fh.write(known)
        pre = set(os.listdir(outside))
    except Exception as exc:
        r.blocked(f"Outside dir setup failed: {exc}"); return r

    # Phase 1: junction + API test — wrapped in try/finally for cleanup
    try:
        try:
            cp = subprocess.run(
                ["cmd", "/c", "mklink", "/J", junc, outside],
                capture_output=True, text=True, timeout=15,
            )
        except Exception as exc:
            r.blocked(f"mklink unavailable: {exc}"); return r
        if cp.returncode != 0: r.blocked(f"mklink /J failed rc={cp.returncode}"); return r
        junc_created = True

        # After success, absence is FAIL (fail closed)
        if not os.path.lexists(junc):
            r.fail("JunctionNotPresent", "mklink succeeded but junction absent"); return r

        # ensure_secure_directory on junction → reparse check → SecureStorePermissionError
        try:
            ensure_secure_directory(junc)
            r.fail("ExpectedSecureStorePermissionError", "API accepted junction"); return r
        except SecureStorePermissionError:
            r.observed.append("SecureStorePermissionError — junction rejected")
        except Exception as exc:
            r.fail(f"Unexpected: {type(exc).__name__}: {exc}", traceback.format_exc()); return r

        # Verify outside untouched
        try:
            post = set(os.listdir(outside))
            if pre is not None and pre != post:
                r.fail("OutsideDirChanged", f"pre={pre} post={post}")
            else: r.observed.append("outside inventory unchanged")
            actual = None
            if os.path.isfile(otgt):
                with open(otgt, "rb") as fh: actual = fh.read()
            if actual != known:
                r.fail("OutsideContentChanged",
                       f"want={known.hex()} got={actual.hex() if actual else 'NONE'}")
            else: r.observed.append("outside content unchanged")
        except Exception as exc:
            r.fail(f"Integrity check: {exc}", "")

        if r.status != "FAIL": r.ok("Junction rejection PASS")
    finally:
        if junc_created:
            cerr = _rmdir_nofollow(junc)
            if cerr is not None:
                (r.fail if r.status != "FAIL" else r.observed.append)(
                    f"Q3 junction cleanup failed: {cerr}")
    return r


# ---------------------------------------------------------------------------
# Q4 – Collision safety (fd-safe on unexpected success)
# ---------------------------------------------------------------------------

def _q4(work: str) -> Row:
    r = Row("Q4-collision-safety")
    r.operation = "pre-existing leaf → FileExistsError, data/stats preserved"
    fd = -1
    try:
        sec = os.path.join(work, "sec dir \u2603")
        leaf = "_collision_test.dat"
        full = os.path.join(sec, leaf)
        known = b"COLLISION-PRE-EXISTING-DATA-42"
        with open(full, "wb") as fh: fh.write(known)
        pre_hex = _hex(full); pre_sz = os.stat(full).st_size
        before = set(os.listdir(sec))

        try:
            fd = create_private_file(sec, leaf)
            r.fail("ExpectedFileExistsError", f"fd={fd}"); return r
        except FileExistsError as fe:
            r.observed.append(f"FileExistsError: {fe}")
        except Exception as exc:
            r.fail(f"Wrong exception: {type(exc).__name__}: {exc}"); return r

        if _hex(full) != pre_hex: r.fail("ContentChanged"); return r
        if os.stat(full).st_size != pre_sz: r.fail("SizeChanged"); return r
        r.observed.append("content and size unchanged")
        after = set(os.listdir(sec))
        if after != before: r.fail("ExtraLeaf", f"before={before} after={after}"); return r
        r.observed.append("no unexpected additional leaf")
        r.ok("collision/data-preservation smoke PASS")
    except Exception as exc:
        r.fail(f"{type(exc).__name__}: {exc}", traceback.format_exc())
    finally:
        if fd >= 0:
            try: os.close(fd)
            except OSError as exc:
                (r.fail if r.status != "FAIL" else r.observed.append)(
                    f"close fd (unexpected success): {exc}")
    return r


# ---------------------------------------------------------------------------
# Q5 – FD hygiene (fd-safe: close exactly once)
# ---------------------------------------------------------------------------

def _q5(work: str) -> Row:
    r = Row("Q5-fd-hygiene")
    r.operation = "create_private_file → int fd → close 1x → os.fstat(fd) raises"
    fd = -1
    try:
        sec = os.path.join(work, "sec dir \u2603")
        fd = create_private_file(sec, "_fd_hygiene_test.bin")
        if not isinstance(fd, int) or isinstance(fd, bool) or fd < 0:
            r.fail("InvalidFD", f"{type(fd).__name__} {fd!r}"); return r
        os.fstat(fd); r.observed.append(f"fstat({fd}) before close OK")
        os.close(fd); fd_was = fd; fd = -1
        r.observed.append(f"close({fd_was}) done")
        try:
            os.fstat(fd_was)
            r.fail("FStatAfterCloseShouldFail", "succeeded after close")
        except OSError:
            r.observed.append("fstat after close raises OSError (expected)")
            r.ok()
    except Exception as exc:
        r.fail(f"{type(exc).__name__}: {exc}", traceback.format_exc())
    finally:
        if fd >= 0:
            try: os.close(fd)
            except OSError as exc:
                (r.fail if r.status != "FAIL" else r.observed.append)(f"close fd failed: {exc}")
    return r


# ---------------------------------------------------------------------------
# Cleanup (dependency-safe: remove junction first, then safe recursive)
# ---------------------------------------------------------------------------

def _cleanup(work: str, junc_path: str | None = None) -> str | None:
    if not os.path.isdir(work): return None
    errs: List[str] = []

    # Phase 1: remove known junction non-followingly; STOP on failure
    if junc_path is not None and os.path.lexists(junc_path):
        e = _rmdir_nofollow(junc_path)
        if e: errs.append(f"junction cleanup failed: {e}")
        if os.path.lexists(junc_path):
            errs.append(f"junction still exists after cleanup: {junc_path!r}")
            return "; ".join(errs)

    # Phase 2: safe recursive (never traverses reparse/symlinks)
    _safe_rmtree(work, errs)
    return "; ".join(errs) if errs else None


# ---------------------------------------------------------------------------
# Linux BLOCKED
# ---------------------------------------------------------------------------

def _blocked(evidence_path: str, now: str) -> int:
    rows = [
        {"id": qid, "status": "BLOCKED", "operation": qid, "exception": None,
         "observed": ["Platform is not Windows — test blocked"]}
        for qid in ("Q1-normal-use", "Q2-permission-sanity", "Q3-junction-rejection",
                    "Q4-collision-safety", "Q5-fd-hygiene")
    ]
    ev = _make_evidence(rows, "BLOCKED", None, now)
    _write_json(evidence_path, ev)
    print("BLOCKED: Windows-only smoke test")
    for r in rows: print(f"[{r['id']}] BLOCKED")
    print("OVERALL: BLOCKED")
    print(f"Evidence: {evidence_path}")
    return 2


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="S5.3 Windows personal smoke")
    ap.add_argument("--output-dir", default=None, help="Evidence output directory")
    args = ap.parse_args()

    out = os.path.abspath(args.output_dir or os.path.join(tempfile.gettempdir(), "aisc-personal-smoke"))
    os.makedirs(out, exist_ok=True)
    evpath = os.path.join(out, "smoke_evidence.json")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if os.name != "nt":
        return _blocked(evpath, now)

    work = os.path.join(out, "work_tree")
    os.makedirs(work, exist_ok=True)

    rows: List[Row] = []
    for fn in (_q1, _q2, _q3, _q4, _q5):
        rows.append(fn(work))

    junc_path = os.path.join(work, "sec dir \u2603", "_junc_q3")
    cerr = _cleanup(work, junc_path=junc_path)
    overall = _overall(rows)
    if cerr:
        overall = "FAIL"
        for r in rows:
            if r.status != "FAIL": r.status = "FAIL"; r.observed.append(f"cleanup error: {cerr}")

    ev = _make_evidence([r.to_dict() for r in rows], overall, [cerr] if cerr else None, now)
    _write_json(evpath, ev)

    for r in rows: print(f"[{r.id}] {r.status}")
    print(f"OVERALL: {overall}")
    print(f"Evidence: {evpath}")
    return _EXIT_MAP.get(overall, 0)


if __name__ == "__main__":
    sys.exit(main())
