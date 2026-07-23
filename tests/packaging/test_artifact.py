"""Tests for packaging artifact module — staging, verification, archive, safety, aggregate."""

import gzip, hashlib, io, json, os, shutil, stat, struct, subprocess, sys, tarfile, tempfile, unittest, zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(_PROJECT_ROOT))

import importlib.util as _iu
def _lm(n,p):
    s=_iu.spec_from_file_location(n,p); m=_iu.module_from_spec(s); s.loader.exec_module(m); return m
_art = _lm("artifact", _PROJECT_ROOT/"packaging"/"artifact.py")


class TestContainerCheckoutContract(unittest.TestCase):
    def test_checksumming_inputs_force_lf_even_below_nested_attributes(self):
        paths = [
            "container/_bundle/plugins/cache/caveman/caveman/63a91ecadbf4/.codex/config.toml",
            "container/_bundle/plugins/marketplaces/caveman/tests/test_validate_inline.py",
            "container/cc-switch-wrapper",
        ]
        proc = subprocess.run(
            ["git", "check-attr", "eol", "--", *paths],
            cwd=_PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        attrs = {}
        for line in proc.stdout.splitlines():
            path, attribute, value = line.rsplit(": ", 2)
            self.assertEqual(attribute, "eol")
            attrs[path] = value
        self.assertEqual(attrs, {path: "lf" for path in paths})

        for path in paths:
            self.assertNotIn(
                b"\r\n",
                (_PROJECT_ROOT / path).read_bytes(),
                f"{path} was checked out with CRLF",
            )

# ========================================================================
# Helpers
# ========================================================================

def _make_fake_tar(path: Path, members: list):
    """members: list of (name, type, data_or_none, linkname_or_none, mode_or_none)"""
    with tarfile.open(str(path), "w") as t:
        for name, mtype, data, linkname, mode in members:
            ti = tarfile.TarInfo(name=name)
            ti.type = mtype
            ti.size = len(data) if data else 0
            ti.mode = mode or 0o644
            if linkname: ti.linkname = linkname
            buf = io.BytesIO(data) if data else io.BytesIO(b"")
            t.addfile(ti, buf)

def _make_fake_zip(path: Path, entries: list):
    """entries: list of (filename, external_attr, data, create_system)"""
    with zipfile.ZipFile(str(path), "w") as zf:
        for fn, attr, data, cs in entries:
            zi = zipfile.ZipInfo(fn, (2026,1,1,0,0,0))
            zi.create_system = cs
            zi.external_attr = attr
            zf.writestr(zi, data)


# ========================================================================
# Tar safety tests (new)
# ========================================================================

class TestTarSafety(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="tarsafe-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)

    def _validate(self, members):
        p = self.td / "test.tar"
        _make_fake_tar(p, members)
        with tarfile.open(str(p)) as t: return _art.validate_tar_members(t)

    def test_symlink_rejected(self):
        e = self._validate([("dir/a", tarfile.SYMTYPE, b"", "target", 0o777)])
        self.assertTrue(any("symlink" in x for x in e), str(e))

    def test_hardlink_rejected(self):
        e = self._validate([("dir/a", tarfile.REGTYPE, b"x", None, 0o644),
                           ("dir/b", tarfile.LNKTYPE, b"", "dir/a", 0o644)])
        self.assertTrue(any("hardlink" in x for x in e), str(e))

    def test_fifo_rejected(self):
        e = self._validate([("fifo", tarfile.FIFOTYPE, b"", None, 0o644)])
        self.assertTrue(any("fifo" in x for x in e), str(e))

    def test_chardev_rejected(self):
        e = self._validate([("dev", tarfile.CHRTYPE, b"", None, 0o644)])
        self.assertTrue(any("chardev" in x for x in e), str(e))

    def test_blockdev_rejected(self):
        e = self._validate([("dev", tarfile.BLKTYPE, b"", None, 0o644)])
        self.assertTrue(any("blockdev" in x for x in e), str(e))

    def test_windows_drive_C_colon_slash(self):
        e = self._validate([("C:/windows/system", tarfile.REGTYPE, b"x", None, 0o644)])
        self.assertTrue(any("Windows drive" in x for x in e), str(e))

    def test_windows_drive_C_colon_backslash(self):
        e = self._validate([("C:\\windows\\system", tarfile.REGTYPE, b"x", None, 0o644)])
        self.assertTrue(any("Windows drive" in x for x in e), str(e))

    def test_unc_path(self):
        e = self._validate([("//server/share/x", tarfile.REGTYPE, b"x", None, 0o644)])
        self.assertTrue(any("UNC" in x for x in e), str(e))

    def test_dotdot_backslash(self):
        e = self._validate([("a\\..\\..\\etc", tarfile.REGTYPE, b"x", None, 0o644)])
        self.assertTrue(any("path escape" in x for x in e), str(e))

    def test_duplicate_normalized(self):
        e = self._validate([("a/b", tarfile.REGTYPE, b"x", None, 0o644),
                           ("a//b", tarfile.REGTYPE, b"y", None, 0o644)])
        self.assertTrue(any("duplicate" in x for x in e), str(e))

    def test_duplicate_casefold(self):
        e = self._validate([("A/B", tarfile.REGTYPE, b"x", None, 0o644),
                           ("a/b", tarfile.REGTYPE, b"y", None, 0o644)])
        self.assertTrue(any("duplicate" in x for x in e), str(e))


# ========================================================================
# Zip safety tests (new)
# ========================================================================

class TestZipSafety(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="zipsafe-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)

    def _validate(self, entries):
        p = self.td / "test.zip"
        _make_fake_zip(p, entries)
        with zipfile.ZipFile(str(p)) as z: return _art.validate_zip_members(z)

    def test_unix_symlink_rejected(self):
        mode = stat.S_IFLNK | 0o777
        e = self._validate([("link", (mode << 16), b"", 3)])
        self.assertTrue(any("symlink" in x for x in e), str(e))

    def test_unix_fifo_rejected(self):
        mode = stat.S_IFIFO | 0o644
        e = self._validate([("fifo", (mode << 16), b"", 3)])
        self.assertTrue(any("fifo" in x for x in e), str(e))

    def test_unix_chardev_rejected(self):
        mode = stat.S_IFCHR | 0o644
        e = self._validate([("dev", (mode << 16), b"", 3)])
        self.assertTrue(any("chardev" in x for x in e), str(e))

    def test_unix_blockdev_rejected(self):
        mode = stat.S_IFBLK | 0o644
        e = self._validate([("dev", (mode << 16), b"", 3)])
        self.assertTrue(any("blockdev" in x for x in e), str(e))

    def test_unix_socket_rejected(self):
        mode = stat.S_IFSOCK | 0o644
        e = self._validate([("sock", (mode << 16), b"", 3)])
        self.assertTrue(any("socket" in x for x in e), str(e))

    def test_windows_drive_rejected(self):
        e = self._validate([("C:/windows/file", 0o644 << 16, b"x", 0)])
        self.assertTrue(any("Windows drive" in x for x in e), str(e))

    def test_unc_rejected(self):
        e = self._validate([("//server/share/x", 0o644 << 16, b"x", 0)])
        self.assertTrue(any("UNC" in x for x in e), str(e))

    def test_backslash_traversal_rejected(self):
        e = self._validate([("a\\..\\..\\etc", 0o644 << 16, b"x", 0)])
        self.assertTrue(any("path escape" in x for x in e), str(e))

    def test_casefold_duplicate_rejected(self):
        e = self._validate([("A/B", 0o644 << 16, b"x", 0),
                           ("a/b", 0o644 << 16, b"y", 0)])
        self.assertTrue(any("duplicate" in x for x in e), str(e))

    def test_regular_file_accepted(self):
        e = self._validate([("a/b.txt", (stat.S_IFREG|0o644)<<16, b"x", 3)])
        self.assertEqual(e, [])

    def test_dir_flag_vs_mode_mismatch(self):
        """is_dir() flag contradicts S_IFREG mode."""
        mode = (stat.S_IFREG | 0o755) << 16
        zi = zipfile.ZipInfo("mydir/", (2026,1,1,0,0,0))
        zi.create_system = 3; zi.external_attr = mode
        p = self.td / "test2.zip"
        with zipfile.ZipFile(str(p), "w") as z: z.writestr(zi, b"")
        with zipfile.ZipFile(str(p)) as z: e = _art.validate_zip_members(z)
        self.assertTrue(any("directory flag vs mode" in x for x in e), str(e))

    def test_old_zip_mode_zero_accepted(self):
        """mode=0 with create_system!=3 is old zip compat, should pass."""
        e = self._validate([("file.txt", 0, b"x", 0)])
        self.assertEqual(e, [])


# ========================================================================
# ZIP archive metadata tests (new)
# ========================================================================

class TestZipArchiveMeta(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="zipmeta-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)

    def _make_staging(self, d: Path):
        d.mkdir(parents=True, exist_ok=True)
        b = d/"aisc-bundle"; b.mkdir()
        (b/"VERSION").write_text("2.0.0-dev\n"); (b/"README.md").write_text("# T\n"); (b/"LICENSE").write_text("MIT\n")
        (b/".dockerignore").write_text("t\n"); cfg=b/"config"; cfg.mkdir(); (cfg/"versions.env").write_text("V=1\n")
        c=b/"container"; c.mkdir(); (c/"Dockerfile").write_text("FROM node\n"); (c/"entrypoint.sh").write_text("#!/bin/bash\necho ok\n")
        (c/"regular.txt").write_text("p\n"); (c/"downloads").mkdir(); (c/"downloads"/"x.dat").write_text("d\n")
        (c/"_bundle"/"plugins"/"d").mkdir(parents=True); (c/"_bundle"/"plugins"/"d"/"x.txt").write_text("x\n")
        ab=b/"apps"/"ai-brief"; ab.mkdir(parents=True); (ab/"brief.py").write_text("ok\n")
        v=b/"vendor"; v.mkdir(); (v/"manifest.json").write_text("{}"); (v/"checksums.txt").write_text("# e\n")
        vl=v/"licenses"; vl.mkdir(); (vl/"README.md").write_text("# lic\n")
        _art._write_manifest(b/"manifest.json",{"schema_version":1,"compatible_cli_versions":["2.0.0-dev"]})
        (b/"VERSION").write_text("2.0.0-dev\n")
        exe=d/"aisc.exe"; exe.write_bytes(b"fake"); exe.chmod(0o755)

    def test_sidecar_filename_is_zip_basename(self):
        self._make_staging(self.td)
        out = self.td / "out"; out.mkdir()
        arch, sha = _art.create_zip_archive(self.td, "2.0.0-dev", "windows", "x86_64", out)
        sc = Path(str(arch)+".sha256")
        self.assertTrue(sc.is_file(), f"sidecar not found: {sc}")
        content = sc.read_text(encoding="utf-8")
        self.assertIn("AISC-2.0.0-dev-windows-x86_64.zip", content)
        self.assertIn(sha, content)

    def test_zip_contains_directory_entries(self):
        self._make_staging(self.td)
        out = self.td / "out"; out.mkdir()
        arch, _ = _art.create_zip_archive(self.td, "2.0.0-dev", "windows", "x86_64", out)
        with zipfile.ZipFile(str(arch), "r") as zf:
            names = zf.namelist()
            # Check top-level dir entry exists
            self.assertTrue(any(n.endswith("/") and "aisc-bundle/" in n for n in names),
                            f"Missing directory entries: {[n for n in names if n.endswith('/')]}")
            # Check directory metadata
            for zi in zf.infolist():
                if zi.is_dir():
                    mode = (zi.external_attr >> 16) & 0xFFFF
                    self.assertTrue(stat.S_ISDIR(mode), f"Dir {zi.filename} not S_IFDIR: mode={oct(mode)}")
                    perm = mode & 0o777
                    self.assertEqual(perm, 0o755, f"Dir {zi.filename} mode={oct(perm)} expected 0755")
                else:
                    if zi.filename.endswith("/aisc.exe"):
                        mode = (zi.external_attr >> 16) & 0xFFFF
                        self.assertTrue(stat.S_ISREG(mode), f"Exe not S_ISREG: {oct(mode)}")
                        self.assertEqual(mode & 0o777, 0o755, f"Exe mode={oct(mode&0o777)}")
                    elif "regular.txt" in zi.filename:
                        mode = (zi.external_attr >> 16) & 0xFFFF
                        self.assertTrue(stat.S_ISREG(mode))
                        self.assertEqual(mode & 0o777, 0o644, f"Regular mode={oct(mode&0o777)}")


# ========================================================================
# Sidecar strict tests
# ========================================================================

class TestSidecarStrict(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="sidecar-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)

    def _write_sc(self, content):
        p = self.td / "test.sha256"; p.write_text(content, encoding="utf-8"); return p

    def test_valid(self):
        r = _art._parse_sidecar_strict(self._write_sc("a"*64+"  test.txt\n"))
        self.assertEqual(r, ("a"*64, "test.txt"))

    def test_no_newline(self):
        r = _art._parse_sidecar_strict(self._write_sc("a"*64+"  test.txt"))
        self.assertIsNone(r)

    def test_extra_lines(self):
        r = _art._parse_sidecar_strict(self._write_sc("a"*64+"  test.txt\n\n"))
        self.assertIsNone(r)

    def test_wrong_separator(self):
        r = _art._parse_sidecar_strict(self._write_sc("a"*64+" test.txt\n"))
        self.assertIsNone(r)

    def test_short_hash(self):
        r = _art._parse_sidecar_strict(self._write_sc("b"*63+"  test.txt\n"))
        self.assertIsNone(r)

    def test_extra_tokens(self):
        r = _art._parse_sidecar_strict(self._write_sc("a"*64+"  test.txt extra\n"))
        self.assertIsNone(r)

    def test_empty_file(self):
        r = _art._parse_sidecar_strict(self._write_sc(""))
        self.assertIsNone(r)

    def test_uppercase_hash_accepted(self):
        r = _art._parse_sidecar_strict(self._write_sc("A"*64+"  test.txt\n"))
        self.assertEqual(r, ("a"*64, "test.txt"))


# ========================================================================
# Aggregate strict tests (new)
# ========================================================================

class TestAggregateStrict(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="aggstr-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)

    def _make(self, name, content, version="2.0.0-dev", plat="linux", arch="x86_64"):
        p = self.td / name; p.write_bytes(content)
        h = hashlib.sha256(content).hexdigest()
        (self.td / (name+".sha256")).write_text(f"{h}  {name}\n", encoding="utf-8")

    def _make_valid_set(self, ver="2.0.0-dev"):
        self._make(f"AISC-{ver}-linux-x86_64.tar.gz", b"linux", ver, "linux", "x86_64")
        self._make(f"AISC-{ver}-macos-arm64.tar.gz", b"macos", ver, "macos", "arm64")
        self._make(f"AISC-{ver}-windows-x86_64.zip", b"win", ver, "windows", "x86_64")

    def test_mixed_versions_rejected(self):
        self._make("AISC-2.0.0-dev-linux-x86_64.tar.gz", b"a", "2.0.0-dev")
        self._make("AISC-2.0.0-dev-macos-arm64.tar.gz", b"b", "2.0.0-dev")
        self._make("AISC-3.0.0-windows-x86_64.zip", b"c", "3.0.0")
        rc = _art.aggregate_archives(self.td, ["linux-x86_64","macos-arm64","windows-x86_64"])
        self.assertNotEqual(rc, 0)

    def test_windows_tar_gz_rejected(self):
        self._make("AISC-2.0.0-dev-windows-x86_64.tar.gz", b"x")
        rc = _art.aggregate_archives(self.td, ["windows-x86_64"])
        self.assertNotEqual(rc, 0)

    def test_linux_zip_rejected(self):
        self._make("AISC-2.0.0-dev-linux-x86_64.zip", b"x")
        rc = _art.aggregate_archives(self.td, ["linux-x86_64"])
        self.assertNotEqual(rc, 0)

    def test_wrong_sidecar_filename(self):
        name = "AISC-2.0.0-dev-linux-x86_64.tar.gz"
        (self.td/name).write_bytes(b"a")
        h = hashlib.sha256(b"a").hexdigest()
        (self.td/(name+".sha256")).write_text(f"{h}  wrong-name.tar.gz\n", encoding="utf-8")
        rc = _art.aggregate_archives(self.td, ["linux-x86_64"])
        self.assertNotEqual(rc, 0)

    def test_sidecar_missing_newline_rejected(self):
        name = "AISC-2.0.0-dev-linux-x86_64.tar.gz"
        (self.td/name).write_bytes(b"a")
        h = hashlib.sha256(b"a").hexdigest()
        (self.td/(name+".sha256")).write_text(f"{h}  {name}", encoding="utf-8")  # no newline
        rc = _art.aggregate_archives(self.td, ["linux-x86_64"])
        self.assertNotEqual(rc, 0)

    def test_arbitrary_gz_rejected(self):
        (self.td/"AISC-2.0.0-dev-linux-x86_64.gz").write_bytes(b"x")
        rc = _art.aggregate_archives(self.td, ["linux-x86_64"])
        self.assertNotEqual(rc, 0)

    def test_sidecar_extra_line_rejected(self):
        name = "AISC-2.0.0-dev-linux-x86_64.tar.gz"
        (self.td/name).write_bytes(b"a"); h = hashlib.sha256(b"a").hexdigest()
        (self.td/(name+".sha256")).write_text(f"{h}  {name}\n\n", encoding="utf-8")
        rc = _art.aggregate_archives(self.td, ["linux-x86_64"])
        self.assertNotEqual(rc, 0)

    def test_find_single_archive_rejects_unknown(self):
        """_find_single_archive ignores files that _parse_archive_name rejects."""
        # Create an AISC-looking file that doesn't match known suffixes
        (self.td / "AISC-2.0.0-dev-bogus.dat").write_bytes(b"x")
        # Import ci_smoke to test
        cs = _lm("ci_smoke", _PROJECT_ROOT/"packaging"/"ci_smoke.py")
        with self.assertRaises(SystemExit):
            cs._find_single_archive(self.td)

    def test_find_single_archive_zero_candidates(self):
        cs = _lm("ci_smoke", _PROJECT_ROOT/"packaging"/"ci_smoke.py")
        with self.assertRaises(SystemExit):
            cs._find_single_archive(self.td)

    def test_find_single_archive_two_valid(self):
        self._make("AISC-2.0.0-dev-linux-x86_64.tar.gz", b"a", "2.0.0-dev")
        self._make("AISC-2.0.0-dev-macos-arm64.tar.gz", b"b", "2.0.0-dev")
        cs = _lm("ci_smoke", _PROJECT_ROOT/"packaging"/"ci_smoke.py")
        with self.assertRaises(SystemExit):
            cs._find_single_archive(self.td)

    def test_renamed_sidecar_rejected(self):
        """Sidecar with correct content but wrong filename is rejected."""
        name = "AISC-2.0.0-dev-linux-x86_64.tar.gz"
        (self.td/name).write_bytes(b"a"); h = hashlib.sha256(b"a").hexdigest()
        # Content declares the correct archive name, but sidecar file is renamed
        (self.td/"renamed.sha256").write_text(f"{h}  {name}\n", encoding="utf-8")
        rc = _art.aggregate_archives(self.td, ["linux-x86_64"])
        self.assertNotEqual(rc, 0)

    def test_correct_sidecar_filename_passes(self):
        """Correct sidecar filename + correct content passes."""
        name = "AISC-2.0.0-dev-linux-x86_64.tar.gz"
        (self.td/name).write_bytes(b"a"); h = hashlib.sha256(b"a").hexdigest()
        (self.td/(name+".sha256")).write_text(f"{h}  {name}\n", encoding="utf-8")
        rc = _art.aggregate_archives(self.td, ["linux-x86_64"])
        self.assertEqual(rc, 0)


# ========================================================================
# Keep existing tests (unchanged from before, ensure compatibility)
# ========================================================================

class TestVersionGuard(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="vg-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)
    def _mk(self, version):
        r=self.td; (r/"VERSION").write_text(version+"\n"); (r/"container").mkdir(); (r/"container"/"Dockerfile").write_text("FROM node\n")
    def test_reads_canonical_version(self): self._mk("2.0.0-dev"); self.assertEqual(_art._assert_version_guard(self.td),"2.0.0-dev")
    def test_missing_version(self): self.assertRaises(SystemExit, _art._assert_version_guard, self.td)
    def test_no_hardcoded_package_version_required(self): self._mk("1.2.3-test"); self.assertEqual(_art._assert_version_guard(self.td),"1.2.3-test")
    def test_staged(self):
        self._mk("2.0.0-dev");
        for x in ["README.md","LICENSE",".dockerignore"]: (self.td/x).write_text("#T\n")
        cfg=self.td/"config"; cfg.mkdir(); (cfg/"versions.env").write_text("NODE_IMAGE=node:20-slim\n")
        c=self.td/"container"; (c/"_bundle"/"plugins"/"d").mkdir(parents=True); (c/"_bundle"/"plugins"/"d"/"x.txt").write_text("x\n"); (c/"downloads").mkdir(); (c/"downloads"/"x.dat").write_text("x\n")
        ab=self.td/"apps"/"ai-brief"; ab.mkdir(parents=True); (ab/"brief.py").write_text("ok\n")
        v=self.td/"vendor"; v.mkdir(); (v/"manifest.json").write_text("{}"); (v/"checksums.txt").write_text("#e\n"); vl=v/"licenses"; vl.mkdir(); (vl/"README.md").write_text("#lic\n")
        b=_art.stage_bundle(self.td, self.td/"out"); sv=(b/"VERSION").read_text(encoding="utf-8").strip(); self.assertEqual(sv,"2.0.0-dev")
        m=json.loads((b/"manifest.json").read_text()); self.assertIn("2.0.0-dev", m["compatible_cli_versions"])

class TestStaging(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="stg-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)
    def _cr(self,r):
        (r/"VERSION").write_text("2.0.0-dev\n")
        for x in ["README.md","LICENSE",".dockerignore"]: (r/x).write_text("#T\n")
        cfg=r/"config"; cfg.mkdir(); (cfg/"versions.env").write_text("NODE_IMAGE=node:20-slim\n")
        c=r/"container"; c.mkdir(); (c/"Dockerfile").write_text("FROM node\nCOPY container/entrypoint.sh /\nCOPY container/_bundle/ /home/\nCOPY apps/ai-brief/ /home/\n"); (c/"entrypoint.sh").write_text("#!/bin/bash\necho ok\n")
        (c/"_bundle"/"plugins"/"marketplaces"/"tp").mkdir(parents=True); (c/"_bundle"/"plugins"/"marketplaces"/"tp"/"README.md").write_text("#t\n")
        (c/"_bundle"/"plugins"/"marketplaces"/"tp"/".github").mkdir(); (c/"_bundle"/"plugins"/"marketplaces"/"tp"/".github"/"ci.yml").write_text("name: test\n")
        (c/"_bundle"/"plugins"/"cache").mkdir(parents=True); (c/"_bundle"/"plugins"/"cache"/"data.json").write_text('{"k":"v"}\n')
        (c/"downloads").mkdir(); (c/"downloads"/"test.dat").write_text("data\n"); (c/"lib").mkdir(); (c/"lib"/"test.sh").write_text("#!/bin/bash\n")
        ab=r/"apps"/"ai-brief"; ab.mkdir(parents=True); (ab/"brief.py").write_text("ok\n"); (ab/"README.md").write_text("#ab\n")
        v=r/"vendor"; v.mkdir(); (v/"manifest.json").write_text('{"t":true}\n'); vl=v/"licenses"; vl.mkdir(); (vl/"README.md").write_text("#lic\n")
        cs=[]; import hashlib as hh
        for f in ["container/downloads/test.dat","container/_bundle/plugins/marketplaces/tp/README.md","container/_bundle/plugins/marketplaces/tp/.github/ci.yml"]:
            fp=r/f; cs.append(f"{hh.sha256(fp.read_bytes()).hexdigest()}  {f}")
        (v/"checksums.txt").write_text("\n".join(cs)+"\n")
    def test_basic(self): self._cr(self.td); b=_art.stage_bundle(self.td,self.td/"out"); self.assertTrue(b.is_dir()); self.assertTrue((b/"manifest.json").is_file()); self.assertTrue((b/"VERSION").is_file())
    def test_cache_preserved(self): self._cr(self.td); b=_art.stage_bundle(self.td,self.td/"out"); self.assertTrue((b/"container"/"_bundle"/"plugins"/"cache").is_dir())
    def test_marketplace_metadata_preserved(self): self._cr(self.td); b=_art.stage_bundle(self.td,self.td/"out"); self.assertTrue((b/"container"/"_bundle"/"plugins"/"marketplaces"/"tp"/".github"/"ci.yml").is_file())
    def test_pycache_excluded(self):
        self._cr(self.td); (self.td/"apps"/"ai-brief"/"__pycache__").mkdir(parents=True); (self.td/"apps"/"ai-brief"/"__pycache__"/"x.pyc").write_bytes(b"x"); b=_art.stage_bundle(self.td,self.td/"out")
        for _,dns,fns in os.walk(str(b)): self.assertNotIn("__pycache__",dns)
    def test_cache_dirs_excluded(self): self._cr(self.td); (self.td/"apps"/"ai-brief"/"cache").mkdir(parents=True); (self.td/"apps"/"ai-brief"/"cache"/"x.json").write_text("{}"); b=_art.stage_bundle(self.td,self.td/"out"); self.assertFalse((b/"apps"/"ai-brief"/"cache").exists())
    def test_pytest_cache_excluded(self): self._cr(self.td); (self.td/"container"/".pytest_cache").mkdir(parents=True); (self.td/"container"/".pytest_cache"/"v"/"cache").mkdir(parents=True); (self.td/"container"/".pytest_cache"/"v"/"cache"/"dummy").write_text(""); b=_art.stage_bundle(self.td,self.td/"out"); self.assertFalse((b/"container"/".pytest_cache").exists())
    def test_nested_env_excluded(self): self._cr(self.td); (self.td/"apps"/"ai-brief"/".env").write_text("SECRET=123"); b=_art.stage_bundle(self.td,self.td/"out"); self.assertFalse((b/"apps"/"ai-brief"/".env").exists())
    def test_nested_api_keys_excluded(self): self._cr(self.td); (self.td/"container"/"downloads"/"api-keys").write_text("k"); b=_art.stage_bundle(self.td,self.td/"out"); self.assertFalse((b/"container"/"downloads"/"api-keys").exists())
    def test_forbidden_top(self):
        self._cr(self.td); b=_art.stage_bundle(self.td,self.td/"out")
        for fb in (".git",".github","src","tests","docs","packaging","tools","scripts","cli"):
            self.assertFalse((b/fb).exists(), f"Forbidden: {fb}")

class TestManifestValidation(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="mv-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)
    def _mb(self):
        b=self.td/"aisc-bundle"; b.mkdir()
        for x in ["VERSION","README.md","LICENSE",".dockerignore"]: (b/x).write_text("2.0.0-dev\n" if x=="VERSION" else "#T\n")
        cfg=b/"config"; cfg.mkdir(); (cfg/"versions.env").write_text("NODE_IMAGE=node:20-slim\n")
        c=b/"container"; c.mkdir(); (c/"Dockerfile").write_text("FROM node\n"); (c/"_bundle"/"plugins"/"d").mkdir(parents=True); (c/"_bundle"/"plugins"/"d"/"x.txt").write_text("x\n"); (c/"downloads").mkdir(); (c/"downloads"/"x.dat").write_text("x\n")
        ab=b/"apps"/"ai-brief"; ab.mkdir(parents=True); (ab/"brief.py").write_text("ok\n")
        v=b/"vendor"; v.mkdir(); (v/"manifest.json").write_text("{}"); (v/"checksums.txt").write_text("#e\n"); vl=v/"licenses"; vl.mkdir(); (vl/"README.md").write_text("#lic\n")
        _art._write_manifest(b/"manifest.json",{"schema_version":1,"compatible_cli_versions":["2.0.0-dev"]})
        return b
    def test_valid(self): b=self._mb(); self.assertEqual(_art.verify_staged_bundle(b),[])
    def test_missing(self): b=self._mb(); (b/"manifest.json").unlink(); self.assertTrue(any("missing" in e for e in _art.verify_staged_bundle(b)))
    def test_malformed(self): b=self._mb(); (b/"manifest.json").write_text("not json{"); self.assertTrue(any("not valid JSON" in e for e in _art.verify_staged_bundle(b)))
    def test_wrong_schema(self): b=self._mb(); (b/"manifest.json").write_text('{\n  "schema_version":99,\n  "compatible_cli_versions":["2.0.0-dev"]\n}\n'); self.assertTrue(any("schema_version" in e for e in _art.verify_staged_bundle(b)))
    def test_not_in_allowlist(self): b=self._mb(); (b/"manifest.json").write_text('{\n  "schema_version":1,\n  "compatible_cli_versions":["1.0.0"]\n}\n'); self.assertTrue(any("allowlist" in e for e in _art.verify_staged_bundle(b)))
    def test_forbidden_timestamp(self): b=self._mb(); (b/"manifest.json").write_text('{\n  "schema_version":1,\n  "compatible_cli_versions":["2.0.0-dev"],\n  "timestamp":"x"\n}\n'); self.assertTrue(any("forbidden field" in e.lower() and "timestamp" in e.lower() for e in _art.verify_staged_bundle(b)))
    def test_unknown_field(self): b=self._mb(); (b/"manifest.json").write_text('{\n  "schema_version":1,\n  "compatible_cli_versions":["2.0.0-dev"],\n  "extra":"x"\n}\n'); self.assertTrue(any("unknown field" in e for e in _art.verify_staged_bundle(b)))

class TestTarArchive(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="tar-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)
    def _ms(self,d):
        d.mkdir(parents=True,exist_ok=True); b=d/"aisc-bundle"; b.mkdir()
        for x in ["VERSION","README.md","LICENSE",".dockerignore"]: (b/x).write_text("2.0.0-dev\n" if x=="VERSION" else "#T\n")
        cfg=b/"config"; cfg.mkdir(); (cfg/"versions.env").write_text("V=1\n")
        c=b/"container"; c.mkdir(); (c/"Dockerfile").write_text("FROM node\n"); (c/"entrypoint.sh").write_text("#!/bin/bash\necho ok\n"); (c/"claude-wrapper").write_text("#!/bin/bash\nexec claude-real\n"); (c/"regular.txt").write_text("plain\n"); (c/"lib").mkdir(); (c/"lib"/"writable.sh").write_text("#!/bin/bash\nensure_writable() { :; }\n")
        (c/"downloads").mkdir(); (c/"downloads"/"x.dat").write_text("d\n"); (c/"_bundle"/"plugins"/"d").mkdir(parents=True); (c/"_bundle"/"plugins"/"d"/"x.txt").write_text("x\n")
        ab=b/"apps"/"ai-brief"; ab.mkdir(parents=True); (ab/"brief.py").write_text("ok\n")
        v=b/"vendor"; v.mkdir(); (v/"manifest.json").write_text("{}"); (v/"checksums.txt").write_text("#e\n"); vl=v/"licenses"; vl.mkdir(); (vl/"README.md").write_text("#lic\n")
        _art._write_manifest(b/"manifest.json",{"schema_version":1,"compatible_cli_versions":["2.0.0-dev"]}); (b/"VERSION").write_text("2.0.0-dev\n")
        exe=d/"aisc"; exe.write_bytes(b"fake"); exe.chmod(0o755)
    def test_determinism(self):
        s1=Path(tempfile.mkdtemp(prefix="s1-")); s2=Path(tempfile.mkdtemp(prefix="s2-")); o1=Path(tempfile.mkdtemp(prefix="o1-")); o2=Path(tempfile.mkdtemp(prefix="o2-"))
        try:
            self._ms(s1); self._ms(s2)
            for p in s2.rglob("*"):
                if p.is_file(): os.utime(p,(0,0))
            a1,_=_art.create_tar_archive(s1,"2.0.0-dev","linux","x86_64",o1)
            a2,_=_art.create_tar_archive(s2,"2.0.0-dev","linux","x86_64",o2)
            self.assertEqual(_art._sha256_file(a1),_art._sha256_file(a2))
        finally:
            for x in [s1,s2,o1,o2]: shutil.rmtree(x,ignore_errors=True)
    def test_gzip_mtime_zero(self):
        self._ms(self.td); o=self.td/"out"; o.mkdir(); a,_=_art.create_tar_archive(self.td,"2.0.0-dev","linux","x86_64",o)
        with open(a,"rb") as f:
            h=f.read(10); self.assertEqual(h[0:2],b'\x1f\x8b')
            self.assertEqual(struct.unpack("<I",h[4:8])[0],0)
    def test_exe_mode(self):
        self._ms(self.td); o=self.td/"out"; o.mkdir(); a,_=_art.create_tar_archive(self.td,"2.0.0-dev","linux","x86_64",o)
        with tarfile.open(a,"r:gz") as t: exe=[m for m in t.getmembers() if m.name.endswith("/aisc")]; self.assertEqual(len(exe),1); self.assertEqual(exe[0].mode,0o755)
    def test_script_mode(self):
        self._ms(self.td); o=self.td/"out"; o.mkdir(); a,_=_art.create_tar_archive(self.td,"2.0.0-dev","linux","x86_64",o)
        with tarfile.open(a,"r:gz") as t:
            for m in t.getmembers():
                if m.name.endswith("/entrypoint.sh") or m.name.endswith("/claude-wrapper"): self.assertEqual(m.mode,0o755,f"{m.name}: {oct(m.mode)}")
                elif m.name.endswith("/regular.txt"): self.assertEqual(m.mode,0o644,f"{m.name}: {oct(m.mode)}")
    def test_layout(self):
        self._ms(self.td); o=self.td/"out"; o.mkdir(); a,_=_art.create_tar_archive(self.td,"2.0.0-dev","linux","x86_64",o)
        with tarfile.open(a,"r:gz") as t: names=t.getnames(); self.assertIn("AISC-2.0.0-dev-linux-x86_64/aisc",names)
    def test_sidecar_filename(self):
        self._ms(self.td); o=self.td/"out"; o.mkdir(); a,_=_art.create_tar_archive(self.td,"2.0.0-dev","linux","x86_64",o)
        sc=Path(str(a)+".sha256"); self.assertTrue(sc.is_file()); content=sc.read_text(encoding="utf-8"); self.assertIn("AISC-2.0.0-dev-linux-x86_64.tar.gz",content)

class TestZipArchive(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="zip-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)
    def _ms(self,d):
        d.mkdir(parents=True,exist_ok=True); b=d/"aisc-bundle"; b.mkdir()
        for x in ["VERSION","README.md","LICENSE",".dockerignore"]: (b/x).write_text("2.0.0-dev\n" if x=="VERSION" else "#T\n")
        cfg=b/"config"; cfg.mkdir(); (cfg/"versions.env").write_text("V=1\n")
        c=b/"container"; c.mkdir(); (c/"Dockerfile").write_text("FROM node\n"); (c/"entrypoint.sh").write_text("#!/bin/bash\necho\n"); (c/"regular.txt").write_text("p\n")
        (c/"downloads").mkdir(); (c/"downloads"/"x.dat").write_text("d\n"); (c/"_bundle"/"plugins"/"d").mkdir(parents=True); (c/"_bundle"/"plugins"/"d"/"x.txt").write_text("x\n")
        ab=b/"apps"/"ai-brief"; ab.mkdir(parents=True); (ab/"brief.py").write_text("ok\n")
        v=b/"vendor"; v.mkdir(); (v/"manifest.json").write_text("{}"); (v/"checksums.txt").write_text("#e\n"); vl=v/"licenses"; vl.mkdir(); (vl/"README.md").write_text("#lic\n")
        _art._write_manifest(b/"manifest.json",{"schema_version":1,"compatible_cli_versions":["2.0.0-dev"]}); (b/"VERSION").write_text("2.0.0-dev\n")
        exe=d/"aisc.exe"; exe.write_bytes(b"fake"); exe.chmod(0o755)
    def test_no_backslashes(self):
        self._ms(self.td); o=self.td/"out"; o.mkdir(); a,_=_art.create_zip_archive(self.td,"2.0.0-dev","windows","x86_64",o)
        with zipfile.ZipFile(str(a)) as z:
            for n in z.namelist(): self.assertNotIn("\\",n,f"Backslash: {n}")
    def test_create_system(self):
        self._ms(self.td); o=self.td/"out"; o.mkdir(); a,_=_art.create_zip_archive(self.td,"2.0.0-dev","windows","x86_64",o)
        with zipfile.ZipFile(str(a)) as z:
            for zi in z.infolist(): self.assertEqual(zi.create_system,3,f"create_system={zi.create_system} for {zi.filename}")
    def test_compression_larger_file(self):
        self._ms(self.td); (self.td/"aisc-bundle"/"container"/"larger.bin").write_bytes(b"x"*1024)
        o=self.td/"out"; o.mkdir(); a,_=_art.create_zip_archive(self.td,"2.0.0-dev","windows","x86_64",o)
        with zipfile.ZipFile(str(a)) as z:
            for zi in z.infolist():
                if zi.filename.endswith("/larger.bin") and not zi.is_dir(): self.assertEqual(zi.compress_type,zipfile.ZIP_DEFLATED)

class TestChecksumParsing(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="cs-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)
    def _mk(self,cs,fs):
        b=self.td
        for x in ["VERSION","README.md","LICENSE",".dockerignore"]: (b/x).write_text("2.0.0-dev\n" if x=="VERSION" else "#T\n")
        cfg=b/"config"; cfg.mkdir(); (cfg/"versions.env").write_text("V=1\n")
        c=b/"container"; c.mkdir(); (c/"Dockerfile").write_text("FROM node\n"); (c/"_bundle"/"plugins"/"d").mkdir(parents=True); (c/"_bundle"/"plugins"/"d"/"x.txt").write_text("x\n")
        (c/"downloads").mkdir(); (c/"downloads"/"x.dat").write_text("x\n")
        ab=b/"apps"/"ai-brief"; ab.mkdir(parents=True); (ab/"brief.py").write_text("ok\n")
        v=b/"vendor"; v.mkdir(); (v/"manifest.json").write_text("{}"); vl=v/"licenses"; vl.mkdir(); (vl/"README.md").write_text("#lic\n")
        _art._write_manifest(b/"manifest.json",{"schema_version":1,"compatible_cli_versions":["2.0.0-dev"]})
        (v/"checksums.txt").write_text(cs,encoding="utf-8")
        for rel,data in fs.items(): fp=b/rel; fp.parent.mkdir(parents=True,exist_ok=True); fp.write_bytes(data)
    def test_valid(self): d=b"hello"; h=hashlib.sha256(d).hexdigest(); self._mk(f"#c\n{h}  container/downloads/test.bin\n",{"container/downloads/test.bin":d}); self.assertEqual(_art._verify_vendor_checksums(self.td),[])
    def test_malformed(self): self._mk("not-valid\n",{}); self.assertTrue(any("malformed" in e for e in _art._verify_vendor_checksums(self.td)))
    def test_absolute(self): self._mk("a"*64+"  /etc/passwd\n",{}); self.assertTrue(any("unsafe" in e for e in _art._verify_vendor_checksums(self.td)))
    def test_dotdot(self): self._mk("a"*64+"  ../outside\n",{}); self.assertTrue(any("unsafe" in e for e in _art._verify_vendor_checksums(self.td)))
    def test_escape(self): self._mk("a"*64+"  container/../../etc/secrets\n",{}); self.assertTrue(any("escapes" in e or "unsafe" in e for e in _art._verify_vendor_checksums(self.td)))
    def test_mismatch(self): d=b"actual"; self._mk("b"*64+"  container/downloads/test.bin\n",{"container/downloads/test.bin":d}); self.assertTrue(any("hash mismatch" in e for e in _art._verify_vendor_checksums(self.td)))
    def test_missing(self): h=hashlib.sha256(b"x").hexdigest(); self._mk(f"{h}  nonexistent/file.txt\n",{}); self.assertTrue(any("file not found" in e for e in _art._verify_vendor_checksums(self.td)))

class TestDockerCopyParser(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="df-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)
    def _mk(self,df,fs):
        (self.td/"Dockerfile").write_text(df)
        for rel,data in fs.items(): fp=self.td/rel; fp.parent.mkdir(parents=True,exist_ok=True); fp.write_bytes(data)
    def test_missing(self): self._mk("FROM node\nCOPY nonexistent/path /dst\n",{}); self.assertTrue(any("not found" in e for e in _art._verify_dockerfile_sources(self.td/"Dockerfile",self.td)))
    def test_found(self): self._mk("FROM node\nCOPY existing.txt /dst\n",{"existing.txt":b"x"}); self.assertEqual(_art._verify_dockerfile_sources(self.td/"Dockerfile",self.td),[])
    def test_json_rejected(self): self._mk('FROM node\nCOPY ["src","/dst"]\n',{}); self.assertTrue(any("JSON-form" in e for e in _art._verify_dockerfile_sources(self.td/"Dockerfile",self.td)))
    def test_from_rejected(self): self._mk("FROM node AS base\nFROM node\nCOPY --from=base /src /dst\n",{}); self.assertTrue(any("--from" in e for e in _art._verify_dockerfile_sources(self.td/"Dockerfile",self.td)))
    def test_chown(self): self._mk("FROM node\nCOPY --chown=AISC:AISC existing.txt /dst\n",{"existing.txt":b"x"}); self.assertEqual(_art._verify_dockerfile_sources(self.td/"Dockerfile",self.td),[])
    def test_multi(self): self._mk("FROM node\nCOPY a.txt b.txt /dst/\n",{"a.txt":b"a","b.txt":b"b"}); self.assertEqual(_art._verify_dockerfile_sources(self.td/"Dockerfile",self.td),[])
    def test_real_dockerfile(self):
        r=_PROJECT_ROOT; df=r/"container"/"Dockerfile"
        if not df.is_file(): self.skipTest("no dockerfile")
        self.assertEqual(_art._verify_dockerfile_sources(df,r),[])

class TestArchiveVerification(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="av-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)
    def _ms(self,d):
        d.mkdir(parents=True,exist_ok=True); b=d/"aisc-bundle"; b.mkdir()
        for x in ["VERSION","README.md","LICENSE",".dockerignore"]: (b/x).write_text("2.0.0-dev\n" if x=="VERSION" else "#T\n")
        cfg=b/"config"; cfg.mkdir(); (cfg/"versions.env").write_text("V=1\n")
        c=b/"container"; c.mkdir(); (c/"Dockerfile").write_text("FROM node\n"); (c/"_bundle"/"plugins"/"d").mkdir(parents=True); (c/"_bundle"/"plugins"/"d"/"x.txt").write_text("x\n")
        (c/"downloads").mkdir(); (c/"downloads"/"x.dat").write_text("x\n")
        ab=b/"apps"/"ai-brief"; ab.mkdir(parents=True); (ab/"brief.py").write_text("ok\n")
        v=b/"vendor"; v.mkdir(); (v/"manifest.json").write_text("{}"); (v/"checksums.txt").write_text("#e\n"); vl=v/"licenses"; vl.mkdir(); (vl/"README.md").write_text("#lic\n")
        _art._write_manifest(b/"manifest.json",{"schema_version":1,"compatible_cli_versions":["2.0.0-dev"]}); (b/"VERSION").write_text("2.0.0-dev\n")
        exe=d/"aisc"; exe.write_bytes(b"fake"); exe.chmod(0o755)
    def test_passes(self): self._ms(self.td); o=self.td/"out"; o.mkdir(); a,_=_art.create_tar_archive(self.td,"2.0.0-dev","linux","x86_64",o); self.assertEqual(_art.verify_archive(a),[])
    def test_extra_top(self): self._ms(self.td); (self.td/"extra-file.txt").write_text("bad"); o=self.td/"out"; o.mkdir(); a,_=_art.create_tar_archive(self.td,"2.0.0-dev","linux","x86_64",o); self.assertTrue(any("Extra top-level" in e for e in _art.verify_archive(a)))
    def test_exe_mode(self):
        self._ms(self.td); o=self.td/"out"; o.mkdir(); a,_=_art.create_tar_archive(self.td,"2.0.0-dev","linux","x86_64",o); self.assertEqual([m.mode for m in tarfile.open(a,"r:gz").getmembers() if m.name.endswith("/aisc")][0],0o755)
    def test_bundle_direct(self): self._ms(self.td); self.assertEqual(_art.verify_staged_bundle(self.td/"aisc-bundle"),[])

class TestArchiveSafety(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="as-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)
    def test_reject_absolute(self):
        a=self.td/"bad.tar.gz"
        with tarfile.open(a,"w:gz") as t: ti=tarfile.TarInfo(name="/etc/evil"); ti.size=4; ti.type=tarfile.REGTYPE; t.addfile(ti,io.BytesIO(b"bad\n"))
        self.assertTrue(len(_art.verify_archive(a))>0)
    def test_reject_dotdot(self):
        a=self.td/"bad2.tar.gz"
        with tarfile.open(a,"w:gz") as t: ti=tarfile.TarInfo(name="AISC-2.0.0-dev-linux-x86_64/../../evil"); ti.size=4; ti.type=tarfile.REGTYPE; t.addfile(ti,io.BytesIO(b"bad\n"))
        self.assertTrue(len(_art.verify_archive(a))>0)

class TestSafeExtractNonEmpty(unittest.TestCase):
    """safe_extract_archive must reject non-empty dest_dir."""
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="sene-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)

    def _make_tar(self):
        p = self.td / "test.tar.gz"
        data1 = b"fake"
        data2 = b"2.0.0-dev\n"
        with tarfile.open(str(p), "w:gz") as t:
            ti = tarfile.TarInfo(name="AISC-2.0.0-dev-linux-x86_64/aisc"); ti.size=len(data1); ti.type=tarfile.REGTYPE; t.addfile(ti, io.BytesIO(data1))
            ti2 = tarfile.TarInfo(name="AISC-2.0.0-dev-linux-x86_64/aisc-bundle/VERSION"); ti2.size=len(data2); ti2.type=tarfile.REGTYPE; t.addfile(ti2, io.BytesIO(data2))
        return p

    def test_non_empty_file_rejected(self):
        a = self._make_tar()
        d = self.td / "dest"
        d.mkdir()
        (d / "existing.txt").write_text("pre-existing")
        errors = _art.safe_extract_archive(a, d)
        self.assertTrue(len(errors) > 0, f"Should reject non-empty dest, got: {errors}")
        # Verify the pre-existing file was NOT modified
        self.assertEqual((d / "existing.txt").read_text(), "pre-existing")

    def test_non_empty_symlink_rejected(self):
        a = self._make_tar()
        d = self.td / "dest"
        d.mkdir()
        try:
            (d / "link").symlink_to("/etc/passwd")
        except OSError:
            self.skipTest("symlink not supported on this platform")
        errors = _art.safe_extract_archive(a, d)
        self.assertTrue(len(errors) > 0, f"Should reject dest with symlink, got: {errors}")

    def test_empty_dir_accepted(self):
        a = self._make_tar()
        d = self.td / "dest"
        d.mkdir()
        errors = _art.safe_extract_archive(a, d)
        self.assertEqual(errors, [], f"Empty dir should pass: {errors}")

    def test_nonexistent_dir_created(self):
        a = self._make_tar()
        d = self.td / "nonexistent"
        errors = _art.safe_extract_archive(a, d)
        self.assertEqual(errors, [], f"Should create dir: {errors}")
        self.assertTrue(d.is_dir())

    def test_dest_is_file_rejected(self):
        a = self._make_tar()
        d = self.td / "dest"
        d.write_text("not a dir")
        errors = _art.safe_extract_archive(a, d)
        self.assertTrue(len(errors) > 0, f"Should reject file dest: {errors}")

class TestArchDetection(unittest.TestCase):
    def test_known(self): self.assertIn(_art.ARCH_TAG,("x86_64","arm64"))
    def test_mapping(self): self.assertTrue(_art.ARCH_TAG in ("x86_64","arm64"))
    def test_is_string(self): self.assertIsInstance(_art.ARCH_TAG,str); self.assertGreater(len(_art.ARCH_TAG),0)

class TestAggregate(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="agg-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)
    def _ma(self,name,content): p=self.td/name; p.write_bytes(content); h=hashlib.sha256(content).hexdigest(); (self.td/(name+".sha256")).write_text(f"{h}  {name}\n"); return p
    def test_success_3(self):
        for n in ["AISC-2.0.0-dev-linux-x86_64.tar.gz","AISC-2.0.0-dev-windows-x86_64.zip","AISC-2.0.0-dev-macos-arm64.tar.gz"]: self._ma(n,b"a-"+n.encode())
        rc=_art.aggregate_archives(self.td,["linux-x86_64","windows-x86_64","macos-arm64"]); self.assertEqual(rc,0); self.assertEqual(len((self.td/"SHA256SUMS").read_text().strip().splitlines()),3)
    def test_missing_sidecar(self): (self.td/"AISC-2.0.0-dev-linux-x86_64.tar.gz").write_bytes(b"c"); self.assertNotEqual(_art.aggregate_archives(self.td,["linux-x86_64"]),0)
    def test_wrong_count(self): self._ma("AISC-2.0.0-dev-linux-x86_64.tar.gz",b"a"); self._ma("AISC-2.0.0-dev-windows-x86_64.zip",b"b"); self.assertNotEqual(_art.aggregate_archives(self.td,["linux-x86_64","windows-x86_64","macos-arm64"]),0)
    def test_hash_mismatch(self): n="AISC-2.0.0-dev-linux-x86_64.tar.gz"; (self.td/n).write_bytes(b"real"); (self.td/(n+".sha256")).write_text(f"{'f'*64}  {n}\n"); self.assertNotEqual(_art.aggregate_archives(self.td,["linux-x86_64"]),0)
    def test_wrong_platform_name(self): self._ma("AISC-2.0.0-dev-linux-x86_64.tar.gz",b"a"); self.assertNotEqual(_art.aggregate_archives(self.td,["macos-arm64"]),0)
    def test_extra_archive(self): self._ma("AISC-2.0.0-dev-linux-x86_64.tar.gz",b"a"); self._ma("AISC-2.0.0-dev-extra-x86_64.tar.gz",b"b"); self.assertNotEqual(_art.aggregate_archives(self.td,["linux-x86_64"]),0)

class TestCiSmokeLoading(unittest.TestCase):
    def setUp(self): self.td = Path(tempfile.mkdtemp(prefix="cism-"))
    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)
    def test_importlib_loading(self):
        s=_iu.spec_from_file_location("aat",_PROJECT_ROOT/"packaging"/"artifact.py"); self.assertIsNotNone(s); self.assertIsNotNone(s.loader)
        m=_iu.module_from_spec(s); s.loader.exec_module(m); self.assertTrue(hasattr(m,"stage_bundle")); self.assertTrue(hasattr(m,"aggregate_archives"))
    def test_archive_dir_0(self):
        cs=_lm("cs",_PROJECT_ROOT/"packaging"/"ci_smoke.py"); (self.td/"empty").mkdir()
        with self.assertRaises(SystemExit): cs._find_single_archive(self.td/"empty")
    def test_archive_dir_2(self):
        cs=_lm("cs2",_PROJECT_ROOT/"packaging"/"ci_smoke.py"); ad=self.td/"multi"; ad.mkdir()
        h=hashlib.sha256(b"x").hexdigest(); (ad/"AISC-2.0.0-dev-linux-x86_64.tar.gz").write_bytes(b"x"); (ad/"AISC-2.0.0-dev-linux-x86_64.tar.gz.sha256").write_text(f"{h}  AISC-2.0.0-dev-linux-x86_64.tar.gz\n")
        (ad/"AISC-2.0.0-dev-macos-arm64.tar.gz").write_bytes(b"y"); (ad/"AISC-2.0.0-dev-macos-arm64.tar.gz.sha256").write_text(f"{hashlib.sha256(b'y').hexdigest()}  AISC-2.0.0-dev-macos-arm64.tar.gz\n")
        with self.assertRaises(SystemExit): cs._find_single_archive(ad)
    def test_version_mismatch(self):
        cs=_lm("cs3",_PROJECT_ROOT/"packaging"/"ci_smoke.py")
        script=self.td/"fake_version.py"; script.write_text("import sys,json\nif '--format' in sys.argv and 'json' in sys.argv:\n    print(json.dumps({'data':{'cli_version':'9.9.9'}}))\nelse:\n    print('version text')\nsys.exit(0)\n",encoding="utf-8")
        if sys.platform == "win32":
            fe=self.td/"aisc.cmd"; fe.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',encoding="utf-8")
        else:
            fe=self.td/"aisc"; fe.write_text(f"#!{sys.executable}\n"+script.read_text(encoding="utf-8"),encoding="utf-8"); fe.chmod(0o755)
        vf=self.td/"VERSION"; vf.write_text("2.0.0-dev\n")
        with self.assertRaises(SystemExit): cs._smoke_onedir(fe,vf)

if __name__=="__main__": unittest.main()
