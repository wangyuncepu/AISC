"""Unit tests for Windows reader — mock + real integration."""

import json as _json
import os, sys, tempfile, unittest, subprocess
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from aisc.adapters.windows_config_reader import (
    set_backend, _win_safe_read, _split_parents, _win_open_component,
    GENERIC_READ, FILE_READ_ATTRIBUTES, SHARE_RWD,
    OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, FILE_FLAG_BACKUP_SEMANTICS,
    FILE_ATTRIBUTE_REPARSE_POINT, FILE_ATTRIBUTE_DIRECTORY,
    ERROR_FILE_NOT_FOUND, ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION,
)
from aisc.adapters.config_reader import ReadError, MAX_FILE_BYTES


class FakeKernel32:
    """Fake backend — does NOT auto-create unknown paths."""
    def __init__(self):
        self._files = {}    # key -> {data, attrs, ftype, h}
        self._errors = {}   # key -> win_error
        self._next = 1
        self._closed = set()
        self._close_counts = {}
        self._read_pos = {}
        self.calls_create = []
        self._last_err = 0
        self._read_fail = False
        self._attr_fail = False
        self._type_fail = False

    @property
    def INVALID_HANDLE_VALUE(self): return -1

    def _key(self, p): return p.lower().replace("/","\\").rstrip("\\")

    def add_file(self, path: str, data: bytes, attrs: int = 0,
                 ftype: int = 0x0001, is_dir: bool = False):
        k = self._key(path)
        h = self._next; self._next += 1
        a = attrs
        if is_dir: a |= 0x0010  # literal FILE_ATTRIBUTE_DIRECTORY
        self._files[k] = dict(data=data, attrs=a, ftype=ftype, h=h)

    def add_error(self, path: str, code: int):
        self._errors[self._key(path)] = code

    def CreateFileW(self, path: str, access: int, share: int,
                    security: int, creation: int, flags: int, template: int) -> int:
        self.calls_create.append((path, access, share, flags))
        k = self._key(path)
        if k in self._errors:
            self._last_err = self._errors[k]
            return self.INVALID_HANDLE_VALUE
        if k in self._files:
            return self._files[k]["h"]
        # NOT found → error (do NOT auto-create)
        self._last_err = ERROR_FILE_NOT_FOUND
        return self.INVALID_HANDLE_VALUE

    def CloseHandle(self, handle: int) -> bool:
        self._closed.add(handle)
        self._close_counts[handle] = self._close_counts.get(handle, 0) + 1
        return True

    def ReadFile(self, handle: int, size: int) -> bytes:
        if self._read_fail:
            raise OSError("ReadFile failed")
        for v in self._files.values():
            if v["h"] == handle:
                d = v["data"]
                pos = self._read_pos.get(handle, 0)
                if pos >= len(d):
                    return b""
                chunk = d[pos:pos + size]
                self._read_pos[handle] = pos + len(chunk)
                return chunk
        return b""

    def GetFileType(self, handle: int) -> int:
        if self._type_fail:
            self._last_err = 1
            return 0  # FILE_TYPE_UNKNOWN
        for v in self._files.values():
            if v["h"] == handle:
                return v["ftype"]
        return 0

    def GetFileAttributes(self, handle: int) -> int:
        if self._attr_fail:
            raise OSError("GetFileAttributes failed")
        for v in self._files.values():
            if v["h"] == handle:
                return v["attrs"]
        return 0

    def GetLastError(self) -> int:
        return self._last_err


# ============================================================
class TestWinMock(unittest.TestCase):
    def setUp(self):
        self.fake = FakeKernel32()
        set_backend(self.fake)
        # Auto-add root C:\ as a directory (required for parent validation)
        self.fake.add_file("C:\\", b'', is_dir=True)
    def tearDown(self):
        set_backend(None)

    def _add_tree(self, path, data=b'{}'):
        """Add file and all parent directories."""
        parts = path.replace("/","\\").rstrip("\\").split("\\")
        accum = ""
        for i, p in enumerate(parts):
            if i == 0:
                accum = p
                if len(parts) > 1:
                    accum += "\\"
                self.fake.add_file(accum, b'', is_dir=True)
            else:
                accum = (accum + "\\" + p) if not accum.endswith("\\") else (accum + p)
                is_last = (i == len(parts) - 1)
                if not is_last:
                    self.fake.add_file(accum, b'', is_dir=True)
                else:
                    self.fake.add_file(accum, data)

    def test_regular(self):
        self._add_tree("C:\\Users\\test\\config.json", b'{"a":1}')
        data = _win_safe_read(Path("C:\\Users\\test\\config.json"))
        self.assertEqual(data, b'{"a":1}')

    def test_missing(self):
        self.fake.add_error("C:\\missing.json", ERROR_FILE_NOT_FOUND)
        with self.assertRaises(FileNotFoundError):
            _win_safe_read(Path("C:\\missing.json"))

    def test_permission(self):
        self.fake.add_error("C:\\perm.json", ERROR_ACCESS_DENIED)
        with self.assertRaises(PermissionError):
            _win_safe_read(Path("C:\\perm.json"))

    def test_dir_final(self):
        self.fake.add_file("C:\\adir", b'', is_dir=True)
        with self.assertRaises(ReadError):
            _win_safe_read(Path("C:\\adir"))

    def test_reparse_final(self):
        self.fake.add_file("C:\\link.json", b'{}', attrs=FILE_ATTRIBUTE_REPARSE_POINT)
        with self.assertRaises(ReadError):
            _win_safe_read(Path("C:\\link.json"))

    def test_parent_reparse(self):
        self.fake.add_file("C:\\Users", b'', is_dir=True)
        self.fake.add_file("C:\\Users\\.aisc", b'', attrs=FILE_ATTRIBUTE_REPARSE_POINT)
        self.fake.add_file("C:\\Users\\.aisc\\c.json", b'{}')
        with self.assertRaises(ReadError):
            _win_safe_read(Path("C:\\Users\\.aisc\\c.json"))

    def test_parent_missing(self):
        self.fake.add_error("C:\\missing_dir", ERROR_FILE_NOT_FOUND)
        with self.assertRaises(FileNotFoundError):
            _win_safe_read(Path("C:\\missing_dir\\c.json"))

    def test_parent_permission(self):
        self.fake.add_file("C:\\perm_dir", b'', is_dir=True)
        self.fake.add_error("C:\\perm_dir\\c.json", ERROR_ACCESS_DENIED)
        with self.assertRaises(PermissionError):
            _win_safe_read(Path("C:\\perm_dir\\c.json"))

    def test_parent_non_dir(self):
        self.fake.add_file("C:\\file_as_dir", b'', is_dir=False)
        with self.assertRaises(ReadError):
            _win_safe_read(Path("C:\\file_as_dir\\c.json"))

    def test_oversize(self):
        self.fake.add_file("C:\\big.json", b'x' * (MAX_FILE_BYTES + 100))
        with self.assertRaises(ReadError):
            _win_safe_read(Path("C:\\big.json"))

    def test_close_counts(self):
        self.fake.add_file("C:\\c.json", b'{}')
        _win_safe_read(Path("C:\\c.json"))
        self.assertGreaterEqual(len(self.fake._closed), 1)

    def test_handle_int(self):
        self.fake.add_file("C:\\x.json", b'hi')
        h = self.fake._files["c:\\x.json"]["h"]
        self.assertIsInstance(h, int)

    def test_invalid_handle(self):
        self.assertEqual(self.fake.INVALID_HANDLE_VALUE, -1)

    def test_flags_access(self):
        self._add_tree("C:\\d\\c.json")
        _win_safe_read(Path("C:\\d\\c.json"))
        final = [c for c in self.fake.calls_create if "c.json" in c[0]]
        self.assertTrue(any(c[1] & GENERIC_READ for c in final))

    def test_split_parents_drive(self):
        parts = _split_parents("C:\\config.json")
        self.assertEqual(parts, ["C:\\"])

    def test_split_parents_nested(self):
        parts = _split_parents("C:\\Users\\test\\.aisc\\config.json")
        expected = ["C:\\", "C:\\Users", "C:\\Users\\test", "C:\\Users\\test\\.aisc"]
        self.assertEqual(parts, expected)

    def test_split_parents_unc(self):
        parts = _split_parents("\\\\server\\share\\dir\\config.json")
        self.assertEqual(parts, ["\\\\server\\share", "\\\\server\\share\\dir"])

    def test_invalid_unc(self):
        # \\server_only — no share → rejected
        with self.assertRaises(ReadError):
            _split_parents("\\\\server_only\\config.json")
        # \\\\ — too few components
        with self.assertRaises(ReadError):
            _split_parents("\\\\server_only\\")
        # Drive-relative
        with self.assertRaises(ReadError):
            _split_parents("C:config.json")
        # Path with .. component
        with self.assertRaises(ReadError):
            _split_parents("C:\\Users\\..\\config.json")
        # Path with . component
        with self.assertRaises(ReadError):
            _split_parents("C:\\.\\config.json")

    def test_readfile_error(self):
        self.fake.add_file("C:\\c.json", b'{}')
        self.fake._read_fail = True
        with self.assertRaises(OSError):
            _win_safe_read(Path("C:\\c.json"))

    def test_attr_error(self):
        self.fake.add_file("C:\\c.json", b'{}')
        self.fake._attr_fail = True
        with self.assertRaises(OSError):
            _win_safe_read(Path("C:\\c.json"))

    def test_type_error(self):
        self.fake.add_file("C:\\c.json", b'{}')
        self.fake._type_fail = True
        with self.assertRaises(OSError):
            _win_safe_read(Path("C:\\c.json"))

    def test_component_close_failure(self):
        self.fake.add_file("C:\\bad.json", b'{}')
        orig = self.fake.CloseHandle
        self.fake.CloseHandle = lambda h: False
        try:
            with self.assertRaises(OSError):
                _win_safe_read(Path("C:\\bad.json"))
        finally:
            self.fake.CloseHandle = orig

    def test_component_close_failure_with_primary(self):
        """Close failure during component check with primary exception does not override."""
        self.fake.add_file("C:\\d\\bad.json", b'{}')
        from aisc.adapters.windows_config_reader import _win_open_final, _get_backend
        # Make ReadFile fail to trigger a primary exception
        self.fake._read_fail = True
        orig = self.fake.CloseHandle
        self.fake.CloseHandle = lambda h: False
        try:
            with self.assertRaises(OSError):  # ReadFile error, not close error
                _win_safe_read(Path("C:\\d\\bad.json"))
        finally:
            self.fake.CloseHandle = orig


# ============================================================
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestWinReal(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name)
        set_backend(None)

    def tearDown(self):
        self._t.cleanup()
        set_backend(None)

    def test_read_real(self):
        f = self.d / "c.json"; f.write_bytes(b'{"a":1}')
        self.assertEqual(_win_safe_read(f), b'{"a":1}')

    def test_missing_real(self):
        with self.assertRaises(FileNotFoundError):
            _win_safe_read(self.d / "nope.json")

    def test_oversize_real(self):
        f = self.d / "big.json"
        f.write_bytes(b'x' * (MAX_FILE_BYTES + 100))
        with self.assertRaises(ReadError):
            _win_safe_read(f)

    def test_symlink_rejected(self):
        import subprocess as sp
        target = self.d / "real.json"; target.write_bytes(b'{"a":1}')
        link = self.d / "link.json"
        r = sp.run(["cmd","/c","mklink",str(link),str(target)],
                   capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest(f"mklink unavailable: {r.stderr.strip()}")
        with self.assertRaises((ReadError, OSError)):
            _win_safe_read(link)

    def test_junction_root_rejected(self):
        import subprocess as sp
        real_dir = self.d / "real_ws"; real_dir.mkdir()
        junction = self.d / "junc_ws"
        r = sp.run(["cmd","/c","mklink","/J",str(junction),str(real_dir)],
                   capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest(f"mklink /J unavailable: {r.stderr.strip()}")
        (junction / ".aisc").mkdir()
        (junction / ".aisc" / "config.json").write_bytes(b'{"schema_version":1}')
        with self.assertRaises((ReadError, OSError)):
            _win_safe_read(junction / ".aisc" / "config.json")

    def test_aisc_junction_rejected(self):
        import subprocess as sp
        ws = self.d / "ws"; ws.mkdir()
        real_aisc = self.d / "real_aisc"; real_aisc.mkdir()
        junction_aisc = ws / ".aisc"
        r = sp.run(["cmd","/c","mklink","/J",str(junction_aisc),str(real_aisc)],
                   capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest(f"mklink /J unavailable: {r.stderr.strip()}")
        real_aisc_file = real_aisc / "config.json"
        real_aisc_file.write_bytes(b'{"schema_version":1}')
        with self.assertRaises((ReadError, OSError)):
            _win_safe_read(junction_aisc / "config.json")

    def test_handle_no_leak(self):
        """Repeated reads should not monotonically increase handle count."""
        f = self.d / "c.json"; f.write_bytes(b'{"a":1}')
        try:
            import ctypes
            k32 = ctypes.WinDLL("kernel32")
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.GetCurrentProcess.argtypes = []
            k32.GetProcessHandleCount.restype = ctypes.c_int
            k32.GetProcessHandleCount.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            current = k32.GetCurrentProcess()
            count = ctypes.c_ulong()
            def get_count():
                ok = k32.GetProcessHandleCount(current, ctypes.byref(count))
                if not ok:
                    raise OSError("GetProcessHandleCount failed")
                return count.value
        except Exception as e:
            self.skipTest(f"GetProcessHandleCount unavailable: {e}")
        before = get_count()
        for _ in range(100):
            _win_safe_read(f)
        after = get_count()
        diff = after - before
        self.assertLess(diff, 20, f"Handle leak: {before} -> {after}")


# ============================================================
# B1: ABI structure test + B2: error mapping
# ============================================================
class TestWindowsABI(unittest.TestCase):
    def test_struct_size(self):
        from aisc.adapters.windows_config_reader import _BY_HANDLE_FILE_INFO
        import ctypes
        self.assertEqual(ctypes.sizeof(_BY_HANDLE_FILE_INFO), 52)

    def test_struct_fields_order(self):
        from aisc.adapters.windows_config_reader import _BY_HANDLE_FILE_INFO
        names = [f[0] for f in _BY_HANDLE_FILE_INFO._fields_]
        expected = ["dwFileAttributes", "ftCreationTime", "ftLastAccessTime",
                    "ftLastWriteTime", "dwVolumeSerialNumber", "nFileSizeHigh",
                    "nFileSizeLow", "nNumberOfLinks", "nFileIndexHigh", "nFileIndexLow"]
        self.assertEqual(names, expected)

    def test_offsets(self):
        from aisc.adapters.windows_config_reader import _BY_HANDLE_FILE_INFO
        offsets = {
            "dwFileAttributes": 0, "ftCreationTime": 4, "ftLastAccessTime": 12,
            "ftLastWriteTime": 20, "dwVolumeSerialNumber": 28, "nFileSizeHigh": 32,
            "nFileSizeLow": 36, "nNumberOfLinks": 40, "nFileIndexHigh": 44,
            "nFileIndexLow": 48,
        }
        for name, expected in offsets.items():
            got = getattr(_BY_HANDLE_FILE_INFO, name).offset
            self.assertEqual(got, expected, f"Field {name}: expected offset {expected}, got {got}")

    def test_filestime_size(self):
        from aisc.adapters.windows_config_reader import _FILETIME
        import ctypes
        self.assertEqual(ctypes.sizeof(_FILETIME), 8)

    def test_no_wintypes_by_handle_reference(self):
        import ast
        path = os.path.join(os.path.dirname(__file__), "..", "..", "src",
                            "aisc", "adapters", "windows_config_reader.py")
        with open(path) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "wintypes" and node.attr == "BY_HANDLE_FILE_INFORMATION":
                    self.fail("Found wintypes.BY_HANDLE_FILE_INFORMATION reference")

    def test_file_type_literals(self):
        from aisc.adapters.windows_config_reader import (
            FILE_TYPE_UNKNOWN, FILE_TYPE_DISK, FILE_TYPE_CHAR, FILE_TYPE_PIPE,
        )
        self.assertEqual(FILE_TYPE_UNKNOWN, 0x0000)
        self.assertEqual(FILE_TYPE_DISK, 0x0001)
        self.assertEqual(FILE_TYPE_CHAR, 0x0002)
        self.assertEqual(FILE_TYPE_PIPE, 0x0003)

    def test_fake_non_disk_rejected(self):
        fk = FakeKernel32()
        fk.add_file("C:\\c.json", b'{}', ftype=0x0002)  # FILE_TYPE_CHAR
        fk.add_file("C:\\", b'', is_dir=True)
        set_backend(fk)
        try:
            with self.assertRaises(ReadError):
                _win_safe_read(Path("C:\\c.json"))
        finally:
            set_backend(None)

    def test_raise_win_error_types(self):
        from aisc.adapters.windows_config_reader import (
            _raise_win_error, ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION,
            ERROR_FILE_NOT_FOUND,
        )
        for code, cls in [
            (ERROR_ACCESS_DENIED, PermissionError),
            (ERROR_SHARING_VIOLATION, PermissionError),
            (ERROR_FILE_NOT_FOUND, FileNotFoundError),
        ]:
            try:
                _raise_win_error(code, "test")
            except cls:
                pass  # correct type
            except Exception as e:
                self.fail(f"code {code}: expected {cls.__name__} got {type(e).__name__}")
        with self.assertRaises(OSError) as ctx:
            _raise_win_error(9999, "test")
        self.assertIs(type(ctx.exception), OSError)
        self.assertNotIsInstance(ctx.exception, PermissionError)


class TestWinServiceMapping(unittest.TestCase):
    """Service-level mapping: reader PermissionError → service exit 9."""
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        (self.d / ".config" / "aisc").mkdir(parents=True, exist_ok=True)

    def test_user_permission_exit9(self):
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1}')
        from aisc.application.config_service import run_config_validate
        with patch("aisc.application.config_service.safe_read_config_bytes",
                   side_effect=PermissionError("denied")):
            r = run_config_validate(explicit_config=str(u), home=str(self.d),
                                    env={}, platform_name="linux")
            self.assertEqual(r.exit_code, 9)
            self.assertEqual(r.error_code, "AISC_ERR_PERMISSION_DENIED")
            self.assertEqual(r.data["sources"][0]["status"], "permission_denied")
            self.assertEqual(len(r.data["sources"]), 2)

    def test_user_general_oserror_exit1(self):
        u = self.d / "u.json"; u.write_bytes(b'{"schema_version":1}')
        from aisc.application.config_service import run_config_validate
        with patch("aisc.application.config_service.safe_read_config_bytes",
                   side_effect=OSError("denied")):
            r = run_config_validate(explicit_config=str(u), home=str(self.d),
                                    env={}, platform_name="linux")
            self.assertEqual(r.exit_code, 1)
            self.assertEqual(r.error_code, "AISC_ERR_GENERAL")
            self.assertEqual(r.data["sources"][0]["status"], "error")
            self.assertEqual(len(r.data["sources"]), 2)


# ============================================================
# B3: Relative explicit config proof
# ============================================================
class TestRelativeExplicitConfig(unittest.TestCase):
    def test_service_abspaths_relative_explicit(self):
        """Relative explicit config is abspath'd before reader."""
        import tempfile
        d = Path(tempfile.mkdtemp())
        try:
            (d / ".config" / "aisc").mkdir(parents=True, exist_ok=True)
            ws = d / "ws"; ws.mkdir(); (ws / ".aisc").mkdir()
            u = d / "subdir"; u.mkdir()
            uf = u / "u.json"; uf.write_bytes(b'{"schema_version":1}')
            (ws / ".aisc" / "config.json").write_bytes(b'{"schema_version":1}')
            saved = os.getcwd()
            try:
                os.chdir(d)
                from aisc.application.config_service import run_config_validate
                r = run_config_validate(explicit_config="subdir/u.json",
                                        workspace="ws",
                                        home=str(d), env={}, platform_name="linux")
                self.assertTrue(r.valid)
                user_src = r.data["sources"][0]["path"]
                self.assertTrue(os.path.isabs(user_src), f"Not absolute: {user_src}")
            finally:
                os.chdir(saved)
            # Also test subprocess
            import subprocess, sys
            env = {"HOME": str(d), "XDG_CONFIG_HOME": str(d/".config"),
                   "PYTHONPATH": os.path.join(os.path.dirname(__file__),"..","..","src"),
                   "PATH": os.environ.get("PATH","")}
            r = subprocess.run([sys.executable, "-m", "aisc", "config", "validate",
                                "--format", "json", "--config", "subdir/u.json",
                                "--workspace", str(ws)],
                               capture_output=True, text=True, timeout=10, env=env, cwd=str(d))
            self.assertEqual(r.returncode, 0)
            d2 = _json.loads(r.stdout)
            user_p = d2["data"]["sources"][0]["path"]
            self.assertTrue(os.path.isabs(user_p), f"CLI not absolute: {user_p}")
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
