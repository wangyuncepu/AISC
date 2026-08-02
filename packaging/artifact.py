#!/usr/bin/env python3
"""Cross-platform artifact builder: stage, archive, and verify bundles.

Usage:
    python3 packaging/artifact.py stage          [--root DIR] [--output DIR]
    python3 packaging/artifact.py archive        --staging DIR --executable PATH [--output DIR] [--platform PLATFORM] [--arch ARCH]
    python3 packaging/artifact.py verify         [--bundle PATH] [--archive PATH]
    python3 packaging/artifact.py build-onefile  [--root DIR] [--output DIR]
    python3 packaging/artifact.py aggregate      --directory DIR --expected PLAT1-ARCH1,PLAT2-ARCH2,...
"""

from __future__ import annotations

import argparse, fnmatch, glob as _glob_module, gzip, hashlib, io, json, os, platform as _platform
import re, shutil, stat, struct, subprocess, sys, tarfile, tempfile, time, zipfile
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set, Tuple


# ===========================================================================
# Platform detection
# ===========================================================================

_PLAT_TAG = {"linux": "linux", "darwin": "macos", "win32": "windows"}.get(sys.platform, sys.platform)

def _detect_arch() -> str:
    raw = _platform.machine().lower()
    m = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}
    if raw in m: return m[raw]
    if raw == "amd64": return "x86_64"
    sys.exit(f"ERROR: Unknown architecture: {raw}")

ARCH_TAG = _detect_arch()


# ===========================================================================
# Version helpers
# ===========================================================================

def get_version(root: Path) -> str:
    vf = root / "VERSION"
    if not vf.is_file(): sys.exit(f"ERROR: VERSION not found at {vf}")
    return vf.read_text(encoding="utf-8").strip().split("\n")[0].strip()

def _assert_version_guard(root: Path) -> str:
    """Return the sole project version source after validating it exists."""
    return get_version(root)


# ===========================================================================
# Bundle staging
# ===========================================================================

BUNDLE_REQUIRED = ["VERSION", "README.md", "LICENSE", ".dockerignore", "config/versions.env"]
BUNDLE_EXCLUDE_PATTERNS = [
    "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".coverage", "coverage", "htmlcov", ".tox", ".git", ".github", ".gitignore",
    ".gitattributes", ".DS_Store", "Thumbs.db", "*.egg-info", ".aisc",
    ".deploy", "node_modules", ".env", ".env.*", "api-keys", ".git-credentials",
    ".claude", ".claude_keys", "secrets", "cache",
]
BUNDLE_ALLOWLIST_PREFIXES = [
    "container/_bundle/plugins/cache/",
    "container/_bundle/plugins/marketplaces/",
]
BUNDLE_FORBIDDEN_TOP = [
    "src","tests","docs","packaging","tools","scripts","cli",
    ".git",".github",".gitleaks.toml","tasks","pyproject.toml","skills-lock.json",".project",
    ".env","api-keys",".git-credentials",".claude",".claude_keys",".aisc",".deploy",
]
_EXEC_SOURCE_NAMES = {"claude-wrapper", "entrypoint.sh"}

def _should_exclude(rel_path: str) -> bool:
    clean = rel_path.replace("\\", "/")
    for prefix in BUNDLE_ALLOWLIST_PREFIXES:
        if clean.startswith(prefix): return False
    for part in clean.split("/"):
        for pat in BUNDLE_EXCLUDE_PATTERNS:
            if fnmatch.fnmatch(part, pat): return True
    return False

def _stage_file(src: Path, bundle_root: Path, rel_path: str) -> None:
    dest = bundle_root / rel_path; dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest); os.utime(dest, (0, 0))

def _git_canonical_container_paths(root: Path) -> Set[str]:
    """Return tracked container files whose canonical bytes are in the index."""
    try:
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "container"],
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        modified = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "-z", "--", "container"],
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
    except (FileNotFoundError, subprocess.CalledProcessError):
        return set()
    tracked_paths = {p.decode("utf-8", "surrogateescape") for p in tracked if p}
    modified_paths = {p.decode("utf-8", "surrogateescape") for p in modified if p}
    return tracked_paths - modified_paths

def _stage_container_file(
    root: Path,
    bundle_root: Path,
    rel_path: str,
    canonical_index_paths: Set[str],
) -> None:
    if rel_path not in canonical_index_paths:
        _stage_file(root / rel_path, bundle_root, rel_path)
        return
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f":{rel_path}"],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        _stage_file(root / rel_path, bundle_root, rel_path)
        return
    src = root / rel_path
    dest = bundle_root / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(proc.stdout)
    shutil.copymode(src, dest)
    os.utime(dest, (0, 0))

def _find_files(root: Path, subdir: str) -> List[str]:
    base = root / subdir
    if not base.exists(): return []
    r = []
    for dp, _, fns in os.walk(str(base)):
        for fn in fns:
            rel = str((Path(dp) / fn).relative_to(root)).replace("\\", "/")
            if not _should_exclude(rel): r.append(rel)
    return r

def stage_bundle(root: Path, output_dir: Path, *, verify_version: bool = True) -> Path:
    if verify_version: _assert_version_guard(root)
    pv = get_version(root)
    br = output_dir / "aisc-bundle"
    if br.exists(): shutil.rmtree(br)
    br.mkdir(parents=True)
    for fn in BUNDLE_REQUIRED:
        if not (root / fn).is_file(): sys.exit(f"ERROR: required file missing: {fn}")
        _stage_file(root / fn, br, fn)
    _stage_file(root / "config" / "versions.env", br, "config/versions.env")
    # config.json and profiles.json are optional (tests may not have them)
    if (root / "config" / "config.json").is_file():
        _stage_file(root / "config" / "config.json", br, "config/config.json")
    if (root / "config" / "profiles.json").is_file():
        _stage_file(root / "config" / "profiles.json", br, "config/profiles.json")
    canonical_container_paths = _git_canonical_container_paths(root)
    for rel in _find_files(root, "container"):
        _stage_container_file(root, br, rel, canonical_container_paths)
    base = root / "apps" / "ai-brief"
    if base.exists():
        for dp, _, fns in os.walk(str(base)):
            for fn in fns:
                full = Path(dp) / fn
                rel = str(full.relative_to(root)).replace("\\", "/")
                if "__pycache__" in rel or fn.endswith(".pyc"): continue
                if not _should_exclude(rel): _stage_file(full, br, rel)
    vf = _find_files(root, "vendor")
    for x in ["vendor/manifest.json","vendor/checksums.txt"]:
        if not any(f==x for f in vf): sys.exit(f"ERROR: required vendor file missing: {x}")
    for rel in vf: _stage_file(root / rel, br, rel)
    _write_manifest(br/"manifest.json", {"schema_version":1,"compatible_cli_versions":[pv]})
    (br/"VERSION").write_text(pv+"\n", encoding="utf-8")
    return br

def _write_manifest(path: Path, data: dict) -> None:
    sv, vs = data.get("schema_version", 1), sorted(data.get("compatible_cli_versions", []))
    path.write_text('{\n  "schema_version": '+json.dumps(sv)+',\n  "compatible_cli_versions": '+json.dumps(vs)+'\n}\n', encoding="utf-8", newline="")


# ===========================================================================
# Staging verification
# ===========================================================================

def verify_staged_bundle(bundle_root: Path) -> List[str]:
    errors: List[str] = []
    mp = bundle_root / "manifest.json"
    if not mp.is_file(): return ["manifest.json missing from staged bundle"]
    try:
        mt = mp.read_text(encoding="utf-8")
        if "\r" in mt: errors.append("manifest.json contains CR (must be LF)")
        if not mt.endswith("\n"): errors.append("manifest.json does not end with newline")
        m = json.loads(mt)
    except json.JSONDecodeError as e: return [f"manifest.json is not valid JSON: {e}"]
    if m.get("schema_version") != 1: errors.append(f"manifest.json schema_version={m.get('schema_version')}, expected 1")
    compat = m.get("compatible_cli_versions")
    if not isinstance(compat, list): errors.append("manifest.json compatible_cli_versions is not a list")
    elif len(compat)==0: errors.append("manifest.json compatible_cli_versions is empty")
    else:
        pv = get_version(bundle_root); seen: Set[str] = set()
        for v in compat:
            if not isinstance(v,str): errors.append(f"manifest.json version not string: {v}")
            elif v in seen: errors.append(f"manifest.json duplicate version: {v}")
            seen.add(v)
        if pv not in compat: errors.append(f"manifest.json allowlist missing current version {pv}")
    for k in ("timestamp","platform","arch","checksums"):
        if k in m: errors.append(f"manifest.json contains forbidden field: {k}")
    for k in m:
        if k not in ("schema_version","compatible_cli_versions"): errors.append(f"manifest.json contains unknown field: {k}")
    for fn in BUNDLE_REQUIRED:
        if not (bundle_root/fn).is_file(): errors.append(f"Required file missing: {fn}")
    if not (bundle_root/"config"/"versions.env").is_file(): errors.append("config/versions.env missing")
    df = bundle_root / "container" / "Dockerfile"
    if df.is_file(): errors.extend(_verify_dockerfile_sources(df, bundle_root))
    else: errors.append("container/Dockerfile missing")
    errors.extend(_verify_vendor_checksums(bundle_root))
    errors.extend(_audit_forbidden(bundle_root))
    if not (bundle_root/"container"/"_bundle"/"plugins").exists(): errors.append("container/_bundle/plugins missing")
    if not (bundle_root/"container"/"downloads").exists(): errors.append("container/downloads missing")
    return errors

def _audit_forbidden(bundle_root: Path) -> List[str]:
    es = []
    for dp, dns, fns in os.walk(str(bundle_root)):
        rp = Path(dp).relative_to(bundle_root); rs = str(rp).replace("\\","/")
        for dn in dns:
            if dn=="__pycache__" or dn.startswith(".pytest_cache"): es.append(f"Forbidden dir: {rs}/{dn}")
        for fn in fns:
            fr = (rs+"/"+fn) if rs!="." else fn
            if fn.endswith(".pyc"): es.append(f"Forbidden .pyc: {fr}")
            if fn in (".env","api-keys",".git-credentials") and len(fr.split("/"))>1: es.append(f"Forbidden file: {fr}")
    for fb in BUNDLE_FORBIDDEN_TOP:
        if (bundle_root/fb).exists(): es.append(f"Forbidden top-level: {fb}")
    return es

def _verify_dockerfile_sources(df: Path, br: Path) -> List[str]:
    es = []
    for no, line in enumerate(df.read_text(encoding="utf-8").splitlines(),1):
        s=line.strip()
        if not s or s.startswith("#"): continue
        if not s.upper().startswith("COPY"): continue
        if s.startswith("COPY [") or s.startswith("COPY["): es.append(f"Dockerfile line {no}: JSON-form COPY not supported"); continue
        if "--FROM" in s.upper(): es.append(f"Dockerfile line {no}: COPY --from not supported"); continue
        parts=s.split()
        if len(parts)<3: continue
        cargs=[p for p in parts[1:] if not p.startswith("--")]
        if len(cargs)<2: continue
        for src in cargs[:-1]:
            sp=src.lstrip("/")
            if "*" in sp or "?" in sp:
                if not _glob_module.glob(str(br/sp)): es.append(f"Dockerfile line {no}: COPY source glob not found: {sp}")
            elif not (br/sp.rstrip("/")).exists(): es.append(f"Dockerfile line {no}: COPY source not found: {sp}")
    return es

def _verify_vendor_checksums(bundle_root: Path) -> List[str]:
    es = []
    cf = bundle_root/"vendor"/"checksums.txt"
    if not cf.is_file(): return ["vendor/checksums.txt missing from bundle"]
    for no, line in enumerate(cf.read_text(encoding="utf-8").splitlines(),1):
        s=line.strip()
        if not s or s.startswith("#"): continue
        m = re.match(r'^([0-9a-fA-F]{64})\s+(.+)$', s)
        if not m: es.append(f"vendor/checksums.txt line {no}: malformed: {s[:80]}"); continue
        eh, rp = m.group(1).lower(), m.group(2).strip()
        if rp.startswith("/") or ".." in rp.replace("\\","/").split("/"): es.append(f"vendor/checksums.txt line {no}: unsafe path: {rp}"); continue
        target = (bundle_root/rp).resolve()
        try: target.relative_to(bundle_root.resolve())
        except ValueError: es.append(f"vendor/checksums.txt line {no}: path escapes bundle: {rp}"); continue
        if not target.is_file(): es.append(f"vendor/checksums line {no}: file not found: {rp}"); continue
        ah = hashlib.sha256(target.read_bytes()).hexdigest()
        if ah!=eh: es.append(f"vendor/checksums line {no}: hash mismatch for {rp}: expected {eh[:16]}..., got {ah[:16]}...")
    return es


# ===========================================================================
# Archive creation
# ===========================================================================

def _file_mode_for_path(rel_path: str, is_top_exe: bool = False) -> int:
    if is_top_exe: return 0o755
    name = rel_path.replace("\\","/").split("/")[-1]
    if name in _EXEC_SOURCE_NAMES or name.endswith(".sh"): return 0o755
    return 0o644

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(65536),b""): h.update(chunk)
    return h.hexdigest()

def _write_sidecar(output_dir: Path, archive_basename: str, sha256: str) -> None:
    sc = output_dir / f"{archive_basename}.sha256"
    sc.write_text(f"{sha256}  {archive_basename}\n", encoding="utf-8")

class PosixPath:
    def __init__(self, path: str): self._p = Path(path)
    def __str__(self) -> str: return self._p.as_posix()
    def __repr__(self) -> str: return str(self)
    def __fspath__(self) -> str: return self._p.as_posix()

def create_tar_archive(staging_dir: Path, version: str, platform: str, arch: str,
                       output_dir: Path) -> Tuple[Path, str]:
    archive_name = f"AISC-{version}-{platform}-{arch}"
    archive_file = output_dir / f"{archive_name}.tar.gz"
    exe_name = "aisc.exe" if platform == "windows" else "aisc"
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w", format=tarfile.PAX_FORMAT) as tar:
        entries: List[Tuple[str, Path]] = []
        for item in sorted(staging_dir.iterdir(), key=lambda p: p.name):
            an = f"{archive_name}/{item.name}"
            if item.is_dir():
                for dp, dns, fns in os.walk(str(item)):
                    dns.sort(); fns.sort()
                    for fn in fns:
                        full = Path(dp) / fn
                        entries.append((f"{archive_name}/{str(full.relative_to(staging_dir)).replace(chr(92),'/')}", full))
            else:
                entries.append((an, item))
        for arcname, full in entries:
            ti = tarfile.TarInfo(name=arcname); ti.size = full.stat().st_size
            ti.mtime = ti.uid = ti.gid = 0; ti.uname = ti.gname = "root"
            rel = str(full.relative_to(staging_dir)).replace("\\","/")
            ti.mode = _file_mode_for_path(rel, full.parent==staging_dir and full.name==exe_name)
            ti.type = tarfile.REGTYPE
            with open(full,"rb") as f: tar.addfile(ti, f)
    uncompressed = tar_bytes.getvalue()
    with open(archive_file,"wb") as f:
        with gzip.GzipFile(filename="", mode="wb", mtime=0, fileobj=f) as gz: gz.write(uncompressed)
    sha256 = _sha256_file(archive_file)
    _write_sidecar(output_dir, f"{archive_name}.tar.gz", sha256)
    return archive_file, sha256

def create_zip_archive(staging_dir: Path, version: str, platform: str, arch: str,
                       output_dir: Path) -> Tuple[Path, str]:
    archive_name = f"AISC-{version}-{platform}-{arch}"
    archive_file = output_dir / f"{archive_name}.zip"
    exe_name = "aisc.exe"
    fd = (2026, 1, 1, 0, 0, 0)

    with zipfile.ZipFile(archive_file, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # Collect all directory paths needed
        dirs: Set[str] = set()
        entries: List[Tuple[str, Path, bool]] = []  # (arcname, src_path, is_dir)

        for item in sorted(staging_dir.iterdir(), key=lambda p: p.name):
            ap = f"{archive_name}/{item.name}"
            if item.is_dir():
                dirs.add(ap + "/")
                for dp, dns, fns in os.walk(str(item)):
                    dns.sort(); fns.sort()
                    for fn in fns:
                        full = Path(dp) / fn
                        rel = str(full.relative_to(staging_dir))
                        arc = f"{archive_name}/{rel}"
                        entries.append((arc, full, False))
                        # Add parent directories
                        parent = str(PurePosixPath(arc).parent)
                        if parent != archive_name:
                            dirs.add(parent + "/")
            else:
                entries.append((ap, item, False))

        # Write directory entries first (sorted, deterministic)
        for d in sorted(dirs):
            zi = zipfile.ZipInfo(d, fd)
            zi.create_system = 3
            zi.external_attr = (stat.S_IFDIR | 0o755) << 16
            zi.extra = b""
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, b"")

        # Write file entries (sorted for determinism)
        for arcname, full, _ in sorted(entries, key=lambda x: str(PosixPath(x[0]))):
            zi = zipfile.ZipInfo(str(PosixPath(arcname)), fd)
            zi.create_system = 3
            is_exe = (full.parent == staging_dir and full.name == exe_name)
            rp = str(full.relative_to(staging_dir)).replace("\\","/")
            mode = _file_mode_for_path(rp, is_exe)
            zi.external_attr = (stat.S_IFREG | mode) << 16
            zi.extra = b""
            zi.compress_type = zipfile.ZIP_DEFLATED
            with zf.open(zi, "w") as d: d.write(full.read_bytes())

    sha256 = _sha256_file(archive_file)
    _write_sidecar(output_dir, archive_name + ".zip", sha256)
    return archive_file, sha256


# ===========================================================================
# PyInstaller build
# ===========================================================================

def build_onefile(root: Path, output_dir: Path) -> Tuple[Path, str]:
    ep = root / "packaging" / "pyinstaller" / "entrypoint.py"
    if not ep.is_file(): sys.exit("ERROR: packaging/pyinstaller/entrypoint.py not found")
    wd = Path(tempfile.mkdtemp(prefix="aisc-pyinstaller-"))
    try:
        dd = wd / "dist"
        try: subprocess.run([sys.executable,"-m","PyInstaller","--version"], check=True, capture_output=True, cwd=str(root))
        except (subprocess.CalledProcessError, FileNotFoundError): sys.exit("ERROR: PyInstaller not found. Install: pip install PyInstaller==6.21.0")
        subprocess.run(
            [
                sys.executable, "-m", "PyInstaller", "--onefile",
                "--name", "aisc",
                "--paths", str(root / "src"),
                "--add-data", f"{root / 'VERSION'}:.",
                "--distpath", str(dd),
                "--workpath", str(wd / "build"),
                "--specpath", str(wd),
                str(ep),
            ],
            check=True,
            cwd=str(root),
        )
        en = "aisc.exe" if sys.platform=="win32" else "aisc"
        epath = dd / en
        if not epath.is_file():
            cand = list(dd.glob("*"))
            if cand: epath = cand[0]
            else: sys.exit("ERROR: PyInstaller did not produce an executable")
        output_dir.mkdir(parents=True, exist_ok=True)
        dp = output_dir / en; shutil.copy2(epath, dp); os.chmod(dp, 0o755)
        return dp, _sha256_file(dp)
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ===========================================================================
# Safe archive extraction (PUBLIC)
# ===========================================================================

def _norm_path(p: str) -> str:
    return re.sub(r'/+', '/', p.replace("\\","/")).strip("/")

def _validate_archive_path(name: str) -> Optional[str]:
    """Validate archive member path. Returns error or None."""
    raw = name
    if "\x00" in raw: return "NUL byte in path"
    # Check raw (before any normalisation) for POSIX absolute, UNC, Windows drive
    r = raw.lstrip()
    if r.startswith("//") or r.startswith("\\\\"): return f"UNC path: {raw!r}"
    if r.startswith("/"): return f"POSIX absolute path: {raw!r}"
    if re.match(r'^[a-zA-Z]:[/\\\\]', r): return f"Windows drive path: {raw!r}"
    n = _norm_path(raw)
    if not n or n == ".": return f"empty or '.' path: {raw!r}"
    parts = n.split("/")
    if ".." in parts: return f"path escape (..): {raw!r}"
    if "." in parts: return f"path with '.' segment: {raw!r}"
    return None

def _normalised_key(name: str) -> str:
    """Casefolded normalised path for duplicate detection."""
    return _norm_path(name).casefold()

def validate_tar_members(tar: tarfile.TarFile) -> List[str]:
    """Validate all tar members. Only REGTYPE/DIRTYPE allowed.
    Rejects symlink, hardlink, FIFO, char/block device.
    Checks for normalized+casefold duplicate targets.
    """
    errors = []; seen: Set[str] = set()
    for m in tar.getmembers():
        e = _validate_archive_path(m.name)
        if e: errors.append(e); continue
        if m.type not in (tarfile.REGTYPE, tarfile.DIRTYPE):
            tname = {tarfile.SYMTYPE:"symlink", tarfile.LNKTYPE:"hardlink",
                     tarfile.FIFOTYPE:"fifo", tarfile.CHRTYPE:"chardev",
                     tarfile.BLKTYPE:"blockdev"}.get(m.type, f"type({m.type})")
            errors.append(f"forbidden tar member type {tname}: {m.name}")
            if m.linkname:
                le = _validate_archive_path(m.linkname)
                if le: errors.append(f"unsafe tar link target: {m.linkname} ({le})")
            continue
        nk = _normalised_key(m.name)
        if nk in seen: errors.append(f"duplicate path in tar: {m.name}")
        seen.add(nk)
    return errors

def validate_zip_members(zf: zipfile.ZipFile) -> List[str]:
    """Validate zip members. Rejects unsafe paths, special file types,
    Unix symlinks, casefold duplicates."""
    errors = []; seen: Set[str] = set()
    for zi in zf.infolist():
        e = _validate_archive_path(zi.filename)
        if e: errors.append(e); continue

        # Full high 16 bits for S_IFMT
        full_mode = (zi.external_attr >> 16) & 0xFFFF
        if zi.create_system == 3 and full_mode != 0:
            if stat.S_ISLNK(full_mode):
                errors.append(f"zip contains Unix symlink: {zi.filename}")
            elif not (stat.S_ISREG(full_mode) or stat.S_ISDIR(full_mode)):
                ftype = "unknown"
                if stat.S_ISFIFO(full_mode): ftype = "fifo"
                elif stat.S_ISCHR(full_mode): ftype = "chardev"
                elif stat.S_ISBLK(full_mode): ftype = "blockdev"
                elif stat.S_ISSOCK(full_mode): ftype = "socket"
                errors.append(f"zip contains forbidden file type {ftype}: {zi.filename}")
            # is_dir flag and S_IFDIR must agree
            if zi.is_dir() and not stat.S_ISDIR(full_mode):
                errors.append(f"zip directory flag vs mode mismatch: {zi.filename}")
            if stat.S_ISDIR(full_mode) and not zi.is_dir():
                errors.append(f"zip mode says dir but not flagged as dir: {zi.filename}")
        elif zi.create_system != 3 and full_mode != 0:
            # Non-Unix: if it has mode bits, basic validation; otherwise allow (old zip compat)
            if stat.S_ISLNK(full_mode): errors.append(f"zip contains symlink (non-Unix): {zi.filename}")

        nk = _normalised_key(zi.filename)
        if nk in seen: errors.append(f"duplicate path in zip: {zi.filename}")
        seen.add(nk)
    return errors

def _check_containment(dest_dir: Path, target: Path) -> Optional[str]:
    """Check target resolves inside dest_dir. Returns error or None."""
    try:
        target.resolve().relative_to(dest_dir.resolve())
    except ValueError:
        return f"extraction escapes dest: {target}"
    return None

def safe_extract_tar(tar: tarfile.TarFile, dest_dir: Path) -> List[str]:
    errors = validate_tar_members(tar)
    if errors: return errors
    for m in tar.getmembers():
        if m.type == tarfile.DIRTYPE: continue  # dirs created implicitly
        target = dest_dir / m.name
        ce = _check_containment(dest_dir, target)
        if ce: errors.append(ce); continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with tar.extractfile(m) as src:
            if src is None: errors.append(f"cannot read tar member: {m.name}"); continue
            target.write_bytes(src.read())
        target.chmod(m.mode & 0o777)
    return errors

def safe_extract_zip(zf: zipfile.ZipFile, dest_dir: Path) -> List[str]:
    errors = validate_zip_members(zf)
    if errors: return errors
    for zi in zf.infolist():
        if zi.is_dir(): continue  # dirs created implicitly
        target = dest_dir / zi.filename
        ce = _check_containment(dest_dir, target)
        if ce: errors.append(ce); continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(zi.filename))
        mode = (zi.external_attr >> 16) & 0o777
        target.chmod(mode if mode else 0o644)
    return errors

def safe_extract_archive(archive_path: Path, dest_dir: Path) -> List[str]:
    """Public: safely extract archive to dest_dir.

    If dest_dir does not exist, it is created.
    If dest_dir exists, it MUST be a directory and MUST be empty
    (no pre-existing symlinks, files, or subdirectories).
    Validates all members before writing anything.
    """
    if dest_dir.exists():
        if not dest_dir.is_dir():
            return [f"dest exists but is not a directory: {dest_dir}"]
        if any(dest_dir.iterdir()):
            return [f"dest directory is not empty: {dest_dir}"]
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)

    is_zip = archive_path.suffix == ".zip"
    if is_zip:
        with zipfile.ZipFile(str(archive_path), "r") as zf:
            return safe_extract_zip(zf, dest_dir)
    else:
        with tarfile.open(str(archive_path), "r:*") as tar:
            return safe_extract_tar(tar, dest_dir)


# ===========================================================================
# Archive verification
# ===========================================================================

def _parse_sidecar_strict(sc_path: Path) -> Optional[Tuple[str, str]]:
    """Parse sidecar: exactly one non-empty line '<64hex>  <basename>\\n'."""
    text = sc_path.read_text(encoding="utf-8")
    if not text.endswith("\n"): return None
    lines = text.splitlines()
    nonempty = [l for l in lines if l.strip()]
    if len(nonempty) != 1: return None
    # Must not have trailing blank lines after the content
    stripped = text.strip()
    if stripped + "\n" != text: return None
    line = nonempty[0]
    # Must be exactly two tokens separated by two spaces, no extra whitespace in filename
    if line != line.strip(): return None  # no leading/trailing whitespace on the line itself
    # Find the two-space separator
    idx = line.find("  ")
    if idx < 0: return None
    h = line[:idx].strip()
    fn = line[idx+2:].strip()
    # Reject if there are stray spaces before/after the two-space separator
    if line[:idx] != h: return None
    if line[idx+2:] != fn: return None
    if not re.match(r'^[0-9a-fA-F]{64}$', h): return None
    if " " in fn: return None  # filename must not contain spaces
    if not fn: return None
    return (h.lower(), fn)

def verify_archive(archive_path: Path) -> List[str]:
    errors: List[str] = []
    if not archive_path.is_file(): return [f"Archive not found: {archive_path}"]
    sc = Path(str(archive_path)+".sha256")
    if sc.is_file():
        parsed = _parse_sidecar_strict(sc)
        if parsed is None:
            errors.append(f"sidecar invalid format: {sc.name}")
        else:
            eh, fn = parsed
            if fn != archive_path.name:
                errors.append(f"sidecar declares wrong filename: {fn} (expected {archive_path.name})")
            else:
                ah = _sha256_file(archive_path)
                if ah != eh: errors.append(f"SHA256 mismatch: expected {eh[:16]}..., got {ah[:16]}...")
    is_zip = archive_path.suffix == ".zip"
    ed = Path(tempfile.mkdtemp(prefix="aisc-verify-arch-"))
    try:
        xerr = safe_extract_archive(archive_path, ed)
        errors.extend(xerr)
        if xerr: return errors
        entries = list(ed.iterdir())
        if len(entries) != 1 or not entries[0].is_dir():
            errors.append(f"Archive must have exactly one top-level dir, got {len(entries)}"); return errors
        td = entries[0]
        en = "aisc.exe" if is_zip else "aisc"
        ep = td / en; bp = td / "aisc-bundle"
        tns = {e.name for e in td.iterdir()}
        if en not in tns: errors.append(f"Executable not found: {en}")
        elif not is_zip:
            # Validate executable permission from archive member mode (cross-platform);
            # on-disk stat is unreliable on Windows for Unix permission bits after tar extraction.
            with tarfile.open(str(archive_path), "r:*") as t:
                exe_member = next((m for m in t.getmembers() if m.name.endswith("/" + en)), None)
                if exe_member is not None and not (exe_member.mode & 0o111):
                    errors.append(f"Executable {en} missing execute permission")
        if "aisc-bundle" not in tns: errors.append("aisc-bundle/ not found in archive")
        elif not bp.is_dir(): errors.append("aisc-bundle exists but is not a directory")
        extra = tns - {en, "aisc-bundle"}
        if extra: errors.append(f"Extra top-level entries in archive: {extra}")
        if bp.is_dir(): errors.extend(verify_staged_bundle(bp))
        for d in td.rglob("*"):
            if d.name in (".env","api-keys",".git-credentials",".claude",".aisc"):
                errors.append(f"Forbidden inside archive: {d.relative_to(td)}")
    finally:
        shutil.rmtree(ed, ignore_errors=True)
    return errors


# ===========================================================================
# Aggregate
# ===========================================================================

def _parse_archive_name(name: str) -> Optional[Tuple[str, str, str]]:
    """Parse AISC-<version>-<plat>-<arch>.{tar.gz|zip}. Reverse recognition."""
    known = [("linux-x86_64", ".tar.gz"), ("macos-arm64", ".tar.gz"), ("windows-x86_64", ".zip")]
    for pa, ext in known:
        if name.startswith("AISC-") and name.endswith(f"-{pa}{ext}"):
            ver_part = name[len("AISC-"):-len(f"-{pa}{ext}")]
            if not ver_part: return None
            return (ver_part, pa.split("-")[0], pa.split("-")[1])
    return None

def aggregate_archives(directory: Path, expected_platforms: List[str]) -> int:
    archives: List[Tuple[Path, str, str, str]] = []
    sidecars: List[Path] = []
    for p in sorted(directory.iterdir()):
        if not p.is_file(): continue
        if p.name.endswith(".sha256"): sidecars.append(p); continue
        if p.name.startswith("AISC-"):
            parsed = _parse_archive_name(p.name)
            if parsed: archives.append((p, *parsed))
            else: print(f"AGGREGATE ERROR: unrecognised archive name: {p.name}"); return 1
    ec = len(expected_platforms)
    es = []
    if len(archives) != ec: es.append(f"Expected {ec} archives, found {len(archives)}")
    if len(sidecars) != ec: es.append(f"Expected {ec} sidecars, found {len(sidecars)}")
    versions = {v for _, v, _, _ in archives}
    if len(versions) != 1: es.append(f"All archives must have same version, got: {sorted(versions)}")
    fs = {f"{p}-{a}" for _, _, p, a in archives}
    if fs != set(expected_platforms): es.append(f"Platform mismatch: expected {sorted(expected_platforms)}, found {sorted(fs)}")
    for sc in sidecars:
        parsed = _parse_sidecar_strict(sc)
        if parsed is None: es.append(f"Invalid sidecar format: {sc.name}"); continue
        eh, fn = parsed
        # sidecar filename must be exactly <archive_basename>.sha256
        expected_sc_name = fn + ".sha256"
        if sc.name != expected_sc_name:
            es.append(f"Sidecar filename mismatch: {sc.name} (expected {expected_sc_name})"); continue
        matching = [a for a, _, _, _ in archives if a.name == fn]
        if not matching: es.append(f"Sidecar {sc.name} has no matching archive (expected {fn})"); continue
        ah = _sha256_file(matching[0])
        if ah != eh: es.append(f"Hash mismatch for {fn}: sidecar={eh[:16]}..., actual={ah[:16]}...")
    if es:
        for e in es: print(f"AGGREGATE ERROR: {e}")
        return 1
    lines = []
    for a, _, _, _ in sorted(archives, key=lambda x: x[0].name):
        lines.append(f"{_sha256_file(a)}  {a.name}")
    (directory/"SHA256SUMS").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(f"=== Aggregate OK: {len(lines)} archives, {len(sidecars)} sidecars ===")
    for l in lines: print(f"  {l}")
    return 0


# ===========================================================================
# CLI
# ===========================================================================

def main() -> None:
    p = argparse.ArgumentParser(description="AISC artifact builder")
    sub = p.add_subparsers(dest="command", required=True)
    sp=sub.add_parser("stage"); sp.add_argument("--root"); sp.add_argument("--output"); sp.add_argument("--no-version-guard", action="store_true")
    ap=sub.add_parser("archive"); ap.add_argument("--staging", required=True); ap.add_argument("--executable", required=True); ap.add_argument("--output"); ap.add_argument("--platform"); ap.add_argument("--arch")
    vp=sub.add_parser("verify"); vp.add_argument("--bundle"); vp.add_argument("--archive")
    bp=sub.add_parser("build-onefile"); bp.add_argument("--root"); bp.add_argument("--output")
    ag=sub.add_parser("aggregate"); ag.add_argument("--directory", required=True); ag.add_argument("--expected", required=True)
    args = p.parse_args()
    root: Optional[Path] = None
    if args.command in ("stage","build-onefile"): root = _find_repo_root(args.root if hasattr(args,"root") and args.root else None)
    if args.command == "stage":
        assert root is not None
        out = Path(args.output) if args.output else Path(tempfile.mkdtemp(prefix="aisc-stage-"))
        out.mkdir(parents=True, exist_ok=True)
        bundle = stage_bundle(root, out, verify_version=not getattr(args,"no_version_guard",False))
        errors = verify_staged_bundle(bundle)
        if errors: print(f"VERIFICATION FAILED ({len(errors)} errors):"); [print(f"  - {e}") for e in errors]; sys.exit(1)
        print(f"Staged: {bundle}"); print("VERIFICATION: PASSED")
    elif args.command == "archive":
        staging, exe_src = Path(args.staging), Path(args.executable)
        if not staging.is_dir(): sys.exit(f"ERROR: staging dir not found: {staging}")
        if not exe_src.is_file(): sys.exit(f"ERROR: executable not found: {exe_src}")
        bvp = staging/"aisc-bundle"/"VERSION"
        if not bvp.is_file(): sys.exit("ERROR: aisc-bundle/VERSION not found in staging")
        pv = bvp.read_text(encoding="utf-8").strip()
        plat = args.platform if args.platform else _PLAT_TAG
        arch = args.arch if args.arch else ARCH_TAG
        out_dir = Path(args.output) if args.output else Path.cwd()/"dist"
        out_dir.mkdir(parents=True, exist_ok=True)
        en = "aisc.exe" if plat=="windows" else "aisc"
        de = staging/en; shutil.copy2(exe_src, de)
        if plat!="windows": os.chmod(de, 0o755)
        if plat=="windows": af, sha = create_zip_archive(staging, pv, plat, arch, out_dir)
        else: af, sha = create_tar_archive(staging, pv, plat, arch, out_dir)
        print(f"Archive: {af}\nSHA256:  {sha}")
        errors = verify_archive(af)
        if errors: print(f"ARCHIVE VERIFICATION FAILED ({len(errors)} errors):"); [print(f"  - {e}") for e in errors]; sys.exit(1)
        print("ARCHIVE VERIFICATION: PASSED")
        if de.exists(): de.unlink()
    elif args.command == "verify":
        if args.archive: errors = verify_archive(Path(args.archive))
        elif args.bundle: errors = verify_staged_bundle(Path(args.bundle))
        else: sys.exit("ERROR: specify --bundle or --archive")
        if errors: print(f"VERIFICATION FAILED ({len(errors)} errors):"); [print(f"  - {e}") for e in errors]; sys.exit(1)
        print("VERIFICATION: PASSED")
    elif args.command == "build-onefile":
        assert root is not None
        out_dir = Path(args.output) if args.output else Path.cwd()/"dist"
        out_dir.mkdir(parents=True, exist_ok=True)
        ep, sha = build_onefile(root, out_dir)
        print(f"Executable: {ep}\nSHA256:     {sha}")
    elif args.command == "aggregate":
        directory = Path(args.directory)
        expected = [x.strip() for x in args.expected.split(",") if x.strip()]
        if not expected: sys.exit("ERROR: --expected requires at least one platform-arch")
        sys.exit(aggregate_archives(directory, expected))

def _find_repo_root(explicit: Optional[str] = None) -> Path:
    if explicit:
        p = Path(explicit).resolve()
        if (p/"VERSION").is_file() and (p/"container"/"Dockerfile").is_file(): return p
        sys.exit(f"Not a valid AISC repo root: {explicit}")
    for start in [Path(__file__).resolve().parent.parent, Path.cwd()]:
        c = start
        while True:
            if (c/"VERSION").is_file() and (c/"container"/"Dockerfile").is_file(): return c
            parent = c.parent
            if parent == c: break
            c = parent
    sys.exit("ERROR: Cannot find AISC repository root. Use --root.")

if __name__ == "__main__":
    main()
