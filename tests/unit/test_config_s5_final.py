"""S5.2 final tests — permission, structural, unknown subcommand, CLI spy (0 skipped)."""

import json as _json, os, stat, sys, tempfile, unittest, subprocess, io
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src")
_HAS_MKFIFO = hasattr(os, "mkfifo")
_SENTINEL = object()


# ========== 1. Permission ==========
class TestPermission(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        self.u = self.d / "u.json"; self.u.write_bytes(b'{}')

    def _call(self, **kw):
        from aisc.application.config_service import run_config_validate
        return run_config_validate(explicit_config=str(self.u), home=str(self.d),
                                   env={}, platform_name="linux", **kw)

    def _patch_lstat(self, cond):
        orig = os.lstat
        def _ls(p):
            if cond(p): raise PermissionError("denied")
            return orig(p)
        return patch("os.lstat", side_effect=_ls)

    def test_lstat_permission(self):
        with self._patch_lstat(lambda p: "u.json" in str(p)):
            r = self._call()
            self.assertEqual(r.exit_code, 9)

    def test_open_permission(self):
        with patch("aisc.adapters.config_reader.os.open", side_effect=PermissionError("denied")):
            self.assertEqual(self._call().exit_code, 9)

    def test_fstat_permission(self):
        with patch("aisc.adapters.config_reader.os.fstat", side_effect=PermissionError("denied")):
            r = self._call()
            self.assertEqual(r.exit_code, 9)
            self.assertEqual(r.data["sources"][0]["status"], "permission_denied")

    def test_workspace_root_permission(self):
        ws = self.d / "ws"; ws.mkdir()
        with self._patch_lstat(lambda p: str(p).endswith("ws")):
            self.assertEqual(self._call(workspace=str(ws)).exit_code, 9)

    def test_platform_root_permission(self):
        c = self.d / ".config" / "aisc"; c.mkdir(parents=True)
        self.u.write_bytes(b'{"schema_version":1}')
        # Without explicit config, platform root is checked
        from aisc.application.config_service import run_config_validate
        orig = os.lstat
        def _ls(p):
            if str(p).endswith(".config/aisc") or str(p).endswith(".config\\aisc"):
                raise PermissionError("denied")
            return orig(p)
        with patch("os.lstat", side_effect=_ls):
            r = run_config_validate(home=str(self.d), env={}, platform_name="linux")
            self.assertEqual(r.exit_code, 9)

    def test_aisc_component_permission(self):
        self.u.write_bytes(b'{"schema_version":1}')
        ws = self.d / "ws"; ws.mkdir(); (ws / ".aisc").mkdir()
        (ws / ".aisc" / "config.json").write_bytes(b'{"schema_version":1}')
        with self._patch_lstat(lambda p: ".aisc" in str(p) and "config.json" not in str(p)):
            self.assertEqual(self._call(workspace=str(ws)).exit_code, 9)


# ========== 2. Structural ==========
class TestStructural(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)

    def test_explicit_dir_exit1(self):
        a = self.d / "a"; a.mkdir()
        (self.d / ".config" / "aisc").mkdir(parents=True)
        from aisc.application.config_service import run_config_validate
        r = run_config_validate(explicit_config=str(a), home=str(self.d), env={}, platform_name="linux")
        self.assertEqual(r.exit_code, 1)

    def test_explicit_missing_exit7(self):
        from aisc.application.config_service import run_config_validate
        (self.d / ".config" / "aisc").mkdir(parents=True)
        r = run_config_validate(explicit_config="/nonexistent/xyz.json", home=str(self.d), env={}, platform_name="linux")
        self.assertEqual(r.exit_code, 7)

    def test_relative_xdg_exit1(self):
        """Relative XDG_CONFIG_HOME → structural exit 1."""
        from aisc.application.config_service import run_config_validate
        (self.d / ".config" / "aisc").mkdir(parents=True)
        r = run_config_validate(home=str(self.d), env={"XDG_CONFIG_HOME": "relative/path"}, platform_name="linux")
        self.assertEqual(r.exit_code, 1)
        self.assertEqual(len(r.data["sources"]), 2)
        self.assertEqual(r.data["valid"], False)

    def test_relative_xdg_effective(self):
        from aisc.application.config_service import run_config_effective
        (self.d / ".config" / "aisc").mkdir(parents=True)
        r = run_config_effective(home=str(self.d), env={"XDG_CONFIG_HOME": "relative/path"}, platform_name="linux")
        self.assertEqual(r.exit_code, 1)
        self.assertEqual(r.data["valid"], False)
        self.assertEqual(r.data["sources"][0]["status"], "missing")
        self.assertEqual(r.data["sources"][1]["status"], "missing")
        self.assertIsNone(r.data["effective"])
        self.assertEqual(r.data["provenance"], {})

    @unittest.skipUnless(_HAS_MKFIFO, "os.mkfifo not available")
    def test_fifo_reader(self):
        import shutil
        d = Path(tempfile.mkdtemp())
        try:
            f = d / "f.fifo"; os.mkfifo(str(f))
            from aisc.adapters.config_reader import safe_read_config_bytes, ReadError
            with self.assertRaises(ReadError):
                safe_read_config_bytes(f)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    @unittest.skipUnless(_HAS_MKFIFO, "os.mkfifo not available")
    def test_fifo_subprocess(self):
        import shutil
        d = Path(tempfile.mkdtemp())
        try:
            (d / ".config" / "aisc").mkdir(parents=True, exist_ok=True)
            f = d / "f.fifo"; os.mkfifo(str(f))
            env = {"HOME": str(d), "XDG_CONFIG_HOME": str(d/".config"),
                   "PYTHONPATH": _SRC, "PATH": os.environ.get("PATH","")}
            r = subprocess.run([sys.executable, "-m", "aisc", "config", "validate",
                                "--format", "json", "--config", str(f)],
                               capture_output=True, text=True, timeout=5, env=env)
            self.assertNotEqual(r.returncode, 0)
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ========== 3. Unknown subcommand JSON ==========
class TestUnknownSubcommand(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        (self.d / ".config" / "aisc").mkdir(parents=True)
        self.env = {"HOME": str(self.d), "XDG_CONFIG_HOME": str(self.d/".config"),
                     "PYTHONPATH": _SRC, "PATH": os.environ.get("PATH","")}

    def _check(self, args):
        r = subprocess.run([sys.executable, "-m", "aisc"] + list(args),
                           capture_output=True, text=True, timeout=5, env=self.env, cwd=str(self.d))
        self.assertEqual(r.returncode, 2, f"args={args} stderr={r.stderr}")
        self.assertEqual(r.stderr.strip(), "", f"stderr: {r.stderr!r}")
        d = _json.loads(r.stdout)
        self.assertEqual(d["meta"]["command"], "config")
        self.assertEqual(d["meta"]["exit_code"], 2)
        self.assertEqual(d["errors"][0]["code"], "AISC_ERR_USAGE")

    def test_fmt1(self): self._check(["--format","json","config","unknown"])
    def test_fmt2(self): self._check(["config","--format","json","unknown"])
    def test_fmt3(self): self._check(["config","unknown","--format","json"])
    def test_fmt4(self): self._check(["config","--format=json","unknown"])


# ========== 4. In-process CLI spy ==========
class TestCLISpy(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        (self.d / ".config" / "aisc").mkdir(parents=True)
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1,"defaults":{"profile":"unsafe"}}')
        ws_root = self.d / "ws"; ws_root.mkdir()
        (ws_root / ".aisc").mkdir()
        (ws_root / ".aisc" / "config.json").write_bytes(b'{"schema_version":1,"defaults":{"network":"proxy"}}')
        self._u_path = str(u.resolve())
        self._ws_root = str(ws_root.resolve())
        self._ws_path = str((ws_root / ".aisc" / "config.json").resolve())

    def _run_and_spy(self, args):
        from aisc.cli.main import main
        from aisc.application import config_service as cs
        from aisc.adapters import config_reader as cr
        reader_calls = []
        orig = cr.safe_read_config_bytes
        def _s(p): reader_calls.append(os.path.realpath(str(p))); return orig(p)
        cr.safe_read_config_bytes = _s; cs.safe_read_config_bytes = _s

        cat_calls, disc_calls, write_calls = [], [], []
        def _fc(*a,**kw): cat_calls.append(1); raise AssertionError("catalog")
        def _fd(*a,**kw): disc_calls.append(1); raise AssertionError("discover")
        def _fw(name):
            def _f(*a,**kw): write_calls.append(name); raise AssertionError(f"write:{name}")
            return _f

        # Save env with sentinel
        sh, sx = os.environ.get("HOME", _SENTINEL), os.environ.get("XDG_CONFIG_HOME", _SENTINEL)
        sc = os.getcwd()
        os.environ["HOME"] = str(self.d)
        os.environ["XDG_CONFIG_HOME"] = str(self.d / ".config")
        os.chdir(self.d)

        out, err = io.StringIO(), io.StringIO()
        from contextlib import redirect_stdout, redirect_stderr
        try:
            with redirect_stdout(out), redirect_stderr(err), \
                 patch("aisc.adapters.config_source.load_provider_catalog", side_effect=_fc), \
                 patch("aisc.adapters.config_source.discover_sources", side_effect=_fd), \
                 patch("os.mkdir", side_effect=_fw("os.mkdir")), \
                 patch("os.makedirs", side_effect=_fw("os.makedirs")), \
                 patch("os.rename", side_effect=_fw("os.rename")), \
                 patch("os.replace", side_effect=_fw("os.replace")), \
                 patch("pathlib.Path.mkdir", side_effect=_fw("Path.mkdir")), \
                 patch("pathlib.Path.write_text", side_effect=_fw("Path.write_text")), \
                 patch("pathlib.Path.write_bytes", side_effect=_fw("Path.write_bytes")), \
                 patch("pathlib.Path.touch", side_effect=_fw("Path.touch")):
                try: main(argv=args); ec = 0
                except SystemExit as e: ec = e.code if isinstance(e.code, int) else 1
        finally:
            for k, v in [("HOME", sh), ("XDG_CONFIG_HOME", sx)]:
                if v is _SENTINEL: os.environ.pop(k, None)
                else: os.environ[k] = v
            os.chdir(sc)
            cr.safe_read_config_bytes = orig
            cs.safe_read_config_bytes = orig
        return out.getvalue(), err.getvalue(), ec, reader_calls, cat_calls, disc_calls, write_calls

    def _verify(self, out, err, ec, rc, cc, dc, wc, text_mode=False):
        self.assertEqual(ec, 0, f"exit={ec} err={err}")
        self.assertEqual(len(rc), 2, f"reader calls={len(rc)}: {rc}")
        self.assertCountEqual(rc, [self._u_path, self._ws_path],
                              f"Expected [{self._u_path}, {self._ws_path}], got {rc}")
        self.assertEqual(cc, [], f"catalog={cc}")
        self.assertEqual(dc, [], f"discover={dc}")
        self.assertEqual(wc, [], f"write={wc}")
        if not text_mode:
            self.assertEqual(err.strip(), "")
            self.assertTrue(_json.loads(out)["data"]["valid"])
        else:
            self.assertIn("Config", out, "text output missing header")
            self.assertEqual(err.strip(), "", f"stderr: {err!r}")

    def test_validate_json_spy(self):
        o,e,ec,rc,cc,dc,wc = self._run_and_spy(
            ["config","validate","--format","json","--config",self._u_path,"--workspace",self._ws_root])
        self._verify(o,e,ec,rc,cc,dc,wc)

    def test_validate_text_spy(self):
        o,e,ec,rc,cc,dc,wc = self._run_and_spy(
            ["config","validate","--config",self._u_path,"--workspace",self._ws_root])
        self._verify(o,e,ec,rc,cc,dc,wc, text_mode=True)

    def test_effective_json_spy(self):
        o,e,ec,rc,cc,dc,wc = self._run_and_spy(
            ["config","effective","--format","json","--config",self._u_path,"--workspace",self._ws_root])
        self._verify(o,e,ec,rc,cc,dc,wc)

    def test_effective_text_spy(self):
        o,e,ec,rc,cc,dc,wc = self._run_and_spy(
            ["config","effective","--config",self._u_path,"--workspace",self._ws_root])
        self._verify(o,e,ec,rc,cc,dc,wc, text_mode=True)


# ========== 5. POSIX OSError classification ==========
@unittest.skipIf(os.name == "nt", "POSIX-specific error tests")
class TestPOSIXErrors(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        (self.d / ".config" / "aisc").mkdir(parents=True, exist_ok=True)
        self.u = self.d / "u.json"; self.u.write_bytes(b'{"schema_version":1}')

    def test_workspace_lstat_eio_exit1(self):
        from aisc.application.config_service import run_config_validate
        ws = self.d / "ws"; ws.mkdir()
        orig = os.lstat
        def _ls(p):
            if "ws" in str(p) and ".aisc" not in str(p): raise OSError(5, "EIO")
            return orig(p)
        with patch("os.lstat", side_effect=_ls):
            r = run_config_validate(explicit_config=str(self.u), workspace=str(ws),
                                    home=str(self.d), env={}, platform_name="linux")
            self.assertEqual(r.exit_code, 1)
            self.assertIn(r.data["sources"][0]["status"], ["loaded","missing"])
            self.assertEqual(r.data["sources"][1]["status"], "error")

    def test_final_lstat_eio_exit1(self):
        from aisc.application.config_service import run_config_validate
        orig = os.lstat
        def _ls(p):
            if "u.json" in str(p): raise OSError(5, "EIO")
            return orig(p)
        with patch("os.lstat", side_effect=_ls):
            r = run_config_validate(explicit_config=str(self.u), home=str(self.d),
                                    env={}, platform_name="linux")
            self.assertEqual(r.exit_code, 1)
            self.assertEqual(r.data["sources"][0]["status"], "error")

    def test_open_eio_exit1(self):
        from aisc.application.config_service import run_config_validate
        with patch("os.open", side_effect=OSError(5, "EIO")):
            r = run_config_validate(explicit_config=str(self.u), home=str(self.d),
                                    env={}, platform_name="linux")
            self.assertEqual(r.exit_code, 1)

    def test_fstat_eio_exit1(self):
        from aisc.application.config_service import run_config_validate
        with patch("os.fstat", side_effect=OSError(5, "EIO")):
            r = run_config_validate(explicit_config=str(self.u), home=str(self.d),
                                    env={}, platform_name="linux")
            self.assertEqual(r.exit_code, 1)

    def test_read_eio_exit1(self):
        from aisc.application.config_service import run_config_validate
        with patch("os.read", side_effect=OSError(5, "EIO")):
            r = run_config_validate(explicit_config=str(self.u), home=str(self.d),
                                    env={}, platform_name="linux")
            self.assertEqual(r.exit_code, 1)

    def test_enametoolong_subprocess(self):
        import errno
        long_name = "x" * 5000
        cfg_path = os.path.join("/tmp", long_name)
        # Verify this platform triggers ENAMETOOLONG; skip if not
        try:
            os.lstat(cfg_path)
        except FileNotFoundError:
            self.skipTest("ENAMETOOLONG not triggered on this platform")
        except OSError as e:
            if e.errno != errno.ENAMETOOLONG:
                self.skipTest(f"ENAMETOOLONG not triggered: {e}")
        env = {"HOME": str(self.d), "XDG_CONFIG_HOME": str(self.d/".config"),
               "PYTHONPATH": os.path.join(os.path.dirname(__file__),"..","..","src"),
               "PATH": os.environ.get("PATH","")}
        r = subprocess.run([sys.executable, "-m", "aisc", "config", "validate",
                            "--format", "json", "--config", cfg_path],
                           capture_output=True, text=True, timeout=5, env=env)
        self.assertEqual(r.returncode, 1, f"rc={r.returncode}")
        self.assertEqual(r.stderr.strip(), "", f"stderr: {r.stderr!r}")
        d = _json.loads(r.stdout)
        self.assertEqual(d["meta"]["exit_code"], 1)
        self.assertEqual(d["errors"][0]["code"], "AISC_ERR_GENERAL")
        self.assertFalse(d["data"]["valid"])
        self.assertEqual(len(d["data"]["sources"]), 2)
        self.assertNotIn("Traceback", r.stdout)

    def test_eio_cli_main(self):
        """EIO on open → exit 1 clean JSON via main()."""
        from aisc.cli.main import main
        import io
        with patch("aisc.adapters.config_reader.os.open",
                   side_effect=OSError(5, "EIO_sentinel")):
            out = io.StringIO(); err = io.StringIO()
            from contextlib import redirect_stdout, redirect_stderr
            with redirect_stdout(out), redirect_stderr(err):
                try: main(argv=["config","validate","--format","json","--config",str(self.u)])
                except SystemExit: pass
            self.assertEqual(err.getvalue().strip(), "")
            d = _json.loads(out.getvalue())
            self.assertEqual(d["meta"]["exit_code"], 1)
            self.assertEqual(d["errors"][0]["code"], "AISC_ERR_GENERAL")
            self.assertNotIn("EIO_sentinel", out.getvalue())

    def test_eio_cli_json(self):
        """EIO on lstat → exit 1 with clean JSON."""
        from aisc.application.config_service import run_config_validate
        with patch("aisc.adapters.config_reader.os.lstat",
                   side_effect=OSError(5, "EIO_sentinel")):
            r = run_config_validate(explicit_config=str(self.u), home=str(self.d),
                                    env={}, platform_name="linux")
            self.assertEqual(r.exit_code, 1)
            self.assertNotIn("EIO_sentinel", r.error_message)
            self.assertNotIn("sentinel", str(r.data).lower())

    def test_close_failure_no_primary(self):
        from aisc.adapters.config_reader import _close_fd, _posix_safe_read
        import tempfile
        d = Path(tempfile.mkdtemp())
        f = d / "c.json"; f.write_bytes(b'{"a":1}')
        with patch("os.close", side_effect=OSError(5, "close fail")):
            with self.assertRaises(OSError) as ctx:
                _close_fd(3, None)
            self.assertIn("Failed to close", str(ctx.exception))

    def test_close_failure_with_primary(self):
        from aisc.adapters.config_reader import _close_fd
        primary = ValueError("primary")
        with patch("os.close", side_effect=OSError(5, "close fail")):
            # should NOT raise — primary exception suppresses close failure
            _close_fd(3, primary)
            # no exception → pass

    def test_message_no_sentinel(self):
        from aisc.application.config_service import run_config_validate
        sentinel = "SENTINEL_OSERROR_XYZ"
        with patch("os.lstat", side_effect=OSError(5, sentinel)):
            r = run_config_validate(explicit_config=str(self.u), home=str(self.d),
                                    env={}, platform_name="linux")
            self.assertNotIn(sentinel, r.error_message)
            # No path in generic OSError messages
            for s in r.data["sources"]:
                self.assertNotIn(sentinel, str(s))


# ========== 6. Explicit config isolation ==========
class TestExplicitConfigIsolation(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)

    def test_explicit_skips_platform_root(self):
        """With --config, platform root is not accessed."""
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1}')
        ws = self.d / "ws"; ws.mkdir(); (ws / ".aisc").mkdir()
        (ws / ".aisc" / "config.json").write_bytes(b'{"schema_version":1}')
        # Platform root is a symlink — should NOT matter when explicit is given
        cfg = self.d / ".config" / "aisc"; cfg.mkdir(parents=True)
        link = self.d / ".config" / "aisc_link"
        os.symlink(str(cfg), str(link))  # make platform root a symlink
        from aisc.application.config_service import run_config_validate
        # Use explicit config, so platform root check is skipped
        r = run_config_validate(explicit_config=str(u), workspace=str(ws),
                                home=str(self.d),
                                env={"XDG_CONFIG_HOME": str(link)},
                                platform_name="linux")
        self.assertTrue(r.valid, f"exit={r.exit_code} msg={r.error_message}")

    def test_relative_explicit_config(self):
        """Relative explicit config is resolved against cwd."""
        u = self.d / "subdir" / "u.json"
        u.parent.mkdir(parents=True)
        u.write_bytes(b'{"schema_version":1}')
        ws = self.d / "ws"; ws.mkdir(); (ws / ".aisc").mkdir()
        (ws / ".aisc" / "config.json").write_bytes(b'{"schema_version":1}')
        (self.d / ".config" / "aisc").mkdir(parents=True)
        saved = os.getcwd()
        try:
            os.chdir(str(self.d))
            from aisc.application.config_service import run_config_validate
            r = run_config_validate(explicit_config="subdir/u.json", workspace=str(ws),
                                    home=str(self.d), env={}, platform_name="linux")
            self.assertTrue(r.valid)
        finally:
            os.chdir(saved)


# ========== 7. .aisc missing semantics ==========
class TestAiscMissing(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        (self.d / ".config" / "aisc").mkdir(parents=True, exist_ok=True)

    def test_workspace_exists_no_aisc_dir_valid(self):
        """Workspace root exists, .aisc does not → valid, ws source missing."""
        from aisc.application.config_service import run_config_validate
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1}')
        ws = self.d / "ws"; ws.mkdir()
        r = run_config_validate(explicit_config=str(u), workspace=str(ws),
                                home=str(self.d), env={}, platform_name="linux")
        self.assertTrue(r.valid)
        self.assertEqual(r.exit_code, 0)
        self.assertEqual(r.data["sources"][1]["status"], "missing")

    def test_aisc_exists_no_config_valid(self):
        """.aisc exists but no config.json → valid, ws source missing."""
        from aisc.application.config_service import run_config_validate
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1}')
        ws = self.d / "ws"; ws.mkdir(); (ws / ".aisc").mkdir()
        r = run_config_validate(explicit_config=str(u), workspace=str(ws),
                                home=str(self.d), env={}, platform_name="linux")
        self.assertTrue(r.valid)
        self.assertEqual(r.data["sources"][1]["status"], "missing")

    def test_aisc_reparse_exit1(self):
        """.aisc is a symlink → exit 1."""
        from aisc.application.config_service import run_config_validate
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1}')
        ws = self.d / "ws"; ws.mkdir()
        real_aisc = self.d / "real_aisc"; real_aisc.mkdir()
        os.symlink(str(real_aisc), str(ws / ".aisc"))
        r = run_config_validate(explicit_config=str(u), workspace=str(ws),
                                home=str(self.d), env={}, platform_name="linux")
        self.assertEqual(r.exit_code, 1)
        self.assertEqual(r.data["sources"][1]["status"], "invalid_source")

    def test_aisc_permission_exit9(self):
        """.aisc lstat PermissionError → exit 9 via service mock."""
        from aisc.application.config_service import run_config_validate
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1}')
        ws = self.d / "ws"; ws.mkdir(); (ws / ".aisc").mkdir()
        with patch("os.lstat", side_effect=PermissionError("denied")):
            r = run_config_validate(explicit_config=str(u), workspace=str(ws),
                                    home=str(self.d), env={}, platform_name="linux")
            self.assertEqual(r.exit_code, 9)

    def test_no_fallback_isdir(self):
        """After check_root_exists, os.path.isdir is never called."""
        from aisc.application.config_service import run_config_validate
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1}')
        ws = self.d / "ws"; ws.mkdir()
        with patch("os.path.isdir", side_effect=AssertionError("isdir must not be called")), \
             patch("os.path.lexists", side_effect=AssertionError("lexists must not be called")):
            r = run_config_validate(explicit_config=str(u), workspace=str(ws),
                                    home=str(self.d), env={}, platform_name="linux")
            self.assertTrue(r.valid)


class TestExplicitSourcePath(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        (self.d / ".config" / "aisc").mkdir(parents=True, exist_ok=True)

    def test_explicit_relative_becomes_absolute(self):
        u = self.d / "sub"; u.mkdir()
        uf = u / "u.json"; uf.write_bytes(b'{"schema_version":1}')
        from aisc.application.config_service import run_config_validate
        saved = os.getcwd()
        try:
            os.chdir(str(self.d))
            r = run_config_validate(explicit_config="sub/u.json",
                                    home=str(self.d), env={}, platform_name="linux")
            self.assertTrue(r.valid)
            p = r.data["sources"][0]["path"]
            self.assertTrue(os.path.isabs(p), f"Not absolute: {p}")
        finally:
            os.chdir(saved)

    def test_explicit_abs_workspace_missing(self):
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1}')
        from aisc.application.config_service import run_config_validate
        r = run_config_validate(explicit_config=str(u), workspace="/nonexistent_ws_xyz",
                                home=str(self.d), env={}, platform_name="linux")
        self.assertEqual(r.exit_code, 7)
        self.assertEqual(r.data["sources"][0]["path"], str(u.resolve()))
        self.assertEqual(r.data["sources"][0]["status"], "missing")
        self.assertEqual(len(r.data["sources"]), 2)

    def test_explicit_abs_workspace_symlink(self):
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1}')
        ws = self.d / "ws_real"; ws.mkdir()
        link = self.d / "ws_link"; os.symlink(str(ws), str(link))
        from aisc.application.config_service import run_config_validate
        r = run_config_validate(explicit_config=str(u), workspace=str(link),
                                home=str(self.d), env={}, platform_name="linux")
        self.assertEqual(r.exit_code, 1)
        self.assertEqual(r.data["sources"][0]["path"], str(u.resolve()))
        self.assertEqual(len(r.data["sources"]), 2)

    def test_effective_explicit_abs_workspace_missing(self):
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1}')
        from aisc.application.config_service import run_config_effective
        r = run_config_effective(explicit_config=str(u), workspace="/nonexistent_ws_xyz",
                                 home=str(self.d), env={}, platform_name="linux")
        self.assertEqual(r.exit_code, 7)
        self.assertEqual(r.data["sources"][0]["path"], str(u.resolve()))
        self.assertIsNone(r.data["effective"])
        self.assertEqual(r.data["provenance"], {})


if __name__ == "__main__":
    unittest.main()
