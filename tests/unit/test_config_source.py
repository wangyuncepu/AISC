"""Unit tests — adapter discovery (Oracle ora-6 final)."""

import json, os, stat, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from aisc.adapters.config_source import (
    discover_sources, _build_source_inventory, _resolve_source_path, _safe_read,
    load_provider_catalog,
)
from aisc.domain.config import (
    CredentialStatus, PathPolicy, PlatformPathConfig, ProviderCatalog, ProviderSpec,
)


# ==============================
# Source inventory
# ==============================
class TestInventory(unittest.TestCase):
    def test_fixed_ids(self):
        ids = {s.source_id for s in _build_source_inventory()}
        self.assertEqual(ids, {"w-aisc-secrets-api-keys","w-cc-config-api-keys",
            "w-claude-api-keys","w-claude-settings","r-aisc-state-env","r-deploy-state-env"})

    def test_root_kind(self):
        for s in _build_source_inventory():
            self.assertIn(s.root_kind, ("workspace","aisc_root"))


# ==============================
# Safe reader + symlink rejection
# ==============================
class TestSafeRead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_regular_ok(self):
        f = self.d/"x"; f.write_bytes(b"hi")
        self.assertEqual(_safe_read(f), b"hi")

    def test_symlink_rejected(self):
        t = self.d/"real"; t.write_bytes(b"x")
        l = self.d/"link"; os.symlink(str(t), str(l))
        with self.assertRaises(OSError):
            _safe_read(l)

    def test_dir_rejected(self):
        d = self.d/"sub"; d.mkdir()
        with self.assertRaises(OSError):
            _safe_read(d)


# ==============================
# Path resolution + root symlink
# ==============================
class TestResolveSourcePath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_absolute(self):
        from aisc.domain.config import SourceDescriptor
        pp = PathPolicy(PlatformPathConfig("/c","/s","/sec"), workspace=str(self.d))
        desc = SourceDescriptor("t","workspace",(".aisc","secrets","api-keys"),"api_keys")
        p = _resolve_source_path(desc, pp)
        self.assertIsNotNone(p)

    def test_root_none(self):
        from aisc.domain.config import SourceDescriptor
        pp = PathPolicy(PlatformPathConfig("/c","/s","/sec"))
        desc = SourceDescriptor("t","aisc_root",(".aisc",),"state")
        self.assertIsNone(_resolve_source_path(desc, pp))

    def test_root_symlink_rejected(self):
        real = self.d/"real_root"; real.mkdir()
        link = self.d/"sym_root"; os.symlink(str(real), str(link))
        pp = PathPolicy(PlatformPathConfig("/c","/s","/sec"), workspace=str(link))
        from aisc.domain.config import SourceDescriptor
        desc = SourceDescriptor("t","workspace",(".aisc",),"api_keys")
        # Root symlink should be rejected
        self.assertIsNone(_resolve_source_path(desc, pp))


# ==============================
# Discover sources — production API
# ==============================
class TestDiscoverSources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.b = Path(self.tmp.name)
        self.ws = self.b/"ws"; self.ws.mkdir()
        self.root = self.b/"root"; self.root.mkdir()
        self.cat = ProviderCatalog.build({
            "deepseek":ProviderSpec(id="deepseek",name="DS",auth_type="token",auth_key_name="DEEPSEEK_KEY",base_url=""),
        })

    def tearDown(self):
        self.tmp.cleanup()

    def _make(self, under, rel, content):
        p = under/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(content)

    def _policy(self, ws=True, root_ok=True):
        return PathPolicy(PlatformPathConfig("/c","/s","/sec"),
            workspace=str(self.ws) if ws else None,
            aisc_root=str(self.root) if root_ok else None)

    def test_api_keys_ok(self):
        self._make(self.ws, ".aisc/secrets/api-keys", b"DEEPSEEK_KEY=val\n")
        secrets, _, statuses = discover_sources(policy=self._policy(), catalog=self.cat)
        self.assertEqual(statuses.get("w-aisc-secrets-api-keys"), "ok")
        self.assertTrue(any(r.status==CredentialStatus.OK for r in secrets))

    def test_missing_no_fake_credential(self):
        secrets, _, statuses = discover_sources(policy=self._policy(), catalog=self.cat)
        self.assertEqual(statuses.get("w-aisc-secrets-api-keys"), "missing")
        self.assertFalse(any(r.status==CredentialStatus.OK for r in secrets))

    def test_r_none_skipped(self):
        _, _, statuses = discover_sources(policy=self._policy(root_ok=False), catalog=self.cat)
        self.assertEqual(statuses.get("r-aisc-state-env"), "skipped:not_located")

    def test_state_parsed(self):
        self._make(self.root, ".aisc/state.env", b"IMAGE=img\nPROXY_ENABLED=1\n")
        _, report, _ = discover_sources(policy=self._policy(), catalog=self.cat)
        self.assertEqual(len(report.effective), 2)

    def test_source_symlink_rejected(self):
        # Create a regular file at inventory path, then symlink at that exact path
        real_content = self.b/"hidden_real"
        real_content.write_bytes(b"DEEPSEEK_KEY=evil\n")
        sec_dir = self.ws/".aisc"/"secrets"
        sec_dir.mkdir(parents=True)
        sym_path = sec_dir/"api-keys"
        os.symlink(str(real_content), str(sym_path))
        # _safe_read with lstat should reject the symlink
        secrets, _, statuses = discover_sources(policy=self._policy(), catalog=self.cat)
        self.assertEqual(statuses.get("w-aisc-secrets-api-keys"), "error")

    def test_sentinel_not_leaked(self):
        sentinel = b"DISCOVER_LEAK_Z"
        self._make(self.ws, ".aisc/secrets/api-keys", b"DEEPSEEK_KEY=" + sentinel + b"\n")
        secrets, _, _ = discover_sources(policy=self._policy(), catalog=self.cat)
        self.assertNotIn(sentinel.decode(), repr(secrets))

    # B12: poison env
    def test_no_env_read(self):
        with patch.dict(os.environ, {"HOME":"/POISON"}, clear=True):
            secrets, _, _ = discover_sources(policy=self._policy(), catalog=self.cat)
            # just verifies no crash/leak from env
            self.assertFalse(any(r.status==CredentialStatus.OK for r in secrets))


# ==============================
# B11: load_provider_catalog strict required fields
# ==============================
_GOOD_ENTRY = {"id":"ds","name":"DS","auth_type":"token","auth_key_name":"DS_KEY","base_url":""}

def _make_catalog(overrides=None):
    entry = dict(_GOOD_ENTRY)
    if overrides:
        entry.update(overrides)
    return json.dumps({"schema_version":1,"providers":{"ds":entry}}).encode()

class TestLoadProviderCatalog(unittest.TestCase):
    def test_valid(self):
        cat = load_provider_catalog(_make_catalog())
        self.assertIn("ds", cat.providers)

    def test_real_file(self):
        p = str(Path(__file__).resolve().parent.parent.parent/"container"/"providers.json")
        if Path(p).exists():
            cat = load_provider_catalog(Path(p).read_bytes())
            self.assertIn("cc", cat.providers)

    # --- strict required fields ---
    def test_missing_id(self):
        with self.assertRaises(ValueError) as ctx:
            load_provider_catalog(_make_catalog({"id":None}))
        # Actually: None key won't be "id" missing, it'll be "id must be string"
        # Test with id completely absent:
        raw = json.dumps({"schema_version":1,"providers":{"ds":{"name":"DS","auth_type":"token","auth_key_name":"DS_KEY","base_url":""}}}).encode()
        with self.assertRaises(ValueError):
            load_provider_catalog(raw)

    def test_missing_name(self):
        raw = json.dumps({"schema_version":1,"providers":{"ds":{"id":"ds","auth_type":"token","auth_key_name":"DS_KEY","base_url":""}}}).encode()
        with self.assertRaises(ValueError):
            load_provider_catalog(raw)

    def test_missing_auth_type(self):
        raw = json.dumps({"schema_version":1,"providers":{"ds":{"id":"ds","name":"DS","auth_key_name":"DS_KEY","base_url":""}}}).encode()
        with self.assertRaises(ValueError):
            load_provider_catalog(raw)

    def test_missing_auth_key_name(self):
        raw = json.dumps({"schema_version":1,"providers":{"ds":{"id":"ds","name":"DS","auth_type":"token","base_url":""}}}).encode()
        with self.assertRaises(ValueError):
            load_provider_catalog(raw)

    def test_missing_base_url(self):
        raw = json.dumps({"schema_version":1,"providers":{"ds":{"id":"ds","name":"DS","auth_type":"token","auth_key_name":"DS_KEY"}}}).encode()
        with self.assertRaises(ValueError):
            load_provider_catalog(raw)

    # --- type errors ---
    def test_name_not_string(self):
        with self.assertRaises(ValueError):
            load_provider_catalog(_make_catalog({"name":123}))

    def test_auth_type_not_string(self):
        with self.assertRaises(ValueError):
            load_provider_catalog(_make_catalog({"auth_type":123}))

    def test_auth_key_name_not_string(self):
        with self.assertRaises(ValueError):
            load_provider_catalog(_make_catalog({"auth_key_name":123}))

    def test_base_url_not_string(self):
        with self.assertRaises(ValueError):
            load_provider_catalog(_make_catalog({"base_url":123}))

    # --- id/key mismatch ---
    def test_id_key_mismatch(self):
        raw = json.dumps({"schema_version":1,"providers":{"ds":{"id":"other","name":"DS","auth_type":"token","auth_key_name":"DS_KEY","base_url":""}}}).encode()
        with self.assertRaises(ValueError):
            load_provider_catalog(raw)

    # --- empty name rejected ---
    def test_empty_name(self):
        with self.assertRaises(ValueError):
            load_provider_catalog(_make_catalog({"name":"   "}))

    # --- sentinel scan: error messages never echo input values ---
    def test_sentinel_not_in_error(self):
        sentinel = "SENTINEL_CATALOG_ZZZ"
        raw = json.dumps({"schema_version":1,"providers":{sentinel:{"id":"ds","name":"DS","auth_type":"token","auth_key_name":"DS_KEY","base_url":""}}}).encode()
        try:
            load_provider_catalog(raw)
        except ValueError as e:
            self.assertNotIn(sentinel, str(e))

    def test_invalid_utf8(self):
        with self.assertRaises(ValueError):
            load_provider_catalog(b"\xff\xfe")

    def test_not_object(self):
        with self.assertRaises(ValueError):
            load_provider_catalog(b"[1]")


if __name__ == "__main__":
    unittest.main()
