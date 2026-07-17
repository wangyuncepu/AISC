"""Unit tests — domain models (Oracle ora-6 final)."""

import dataclasses, json, pickle, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from aisc.domain.config import (
    CredentialCandidate, CredentialResult, CredentialStatus, CredentialValue,
    PathPolicy, PlatformPathConfig, ProviderCatalog, ProviderSpec, ReasonCode,
    StateEntry, StateIssue,
    _FIXED_UNKNOWN_KEY_MARKER,
    canonical_url, classify_credentials, is_valid_provider_id, parse_secret_ref,
)


def _make_cand(sid, key, val, from_cat=False, fname="", src_path="/p", line=0):
    c = CredentialCandidate(source_id=sid, value=CredentialValue(val), line_no=line)
    object.__setattr__(c, "_src_path", src_path)
    object.__setattr__(c, "_key", key)
    object.__setattr__(c, "_fname", fname)
    object.__setattr__(c, "_from_cat", from_cat)
    return c


# === A7: CredentialValue — opaque, no pickle ===
class TestCredentialValue(unittest.TestCase):
    def setUp(self):
        self._sentinel = b"SENTINEL_A7_X"
        self._v = CredentialValue(self._sentinel)

    def test_repr_redacted(self):
        self.assertNotIn(b"SENTINEL", repr(self._v).encode())
    def test_str_redacted(self):
        self.assertEqual(str(self._v), "****")
    def test_no_hash(self):
        with self.assertRaises(TypeError): hash(self._v)
    def test_reveal_for_io(self):
        self.assertEqual(self._v._reveal_for_io(), self._sentinel)
    def test_same_value(self):
        self.assertTrue(self._v.same_value(CredentialValue(self._sentinel)))
        self.assertFalse(self._v.same_value(CredentialValue(b"other")))
    def test_equals_ct(self):
        self.assertEqual(self._v, CredentialValue(self._sentinel))
        self.assertNotEqual(self._v, CredentialValue(b"other"))
    def test_to_safe_dict(self):
        d = self._v.to_safe_dict()
        self.assertNotIn(self._sentinel.decode(), str(d))
    def test_reject_pickle(self):
        with self.assertRaises(TypeError): pickle.dumps(self._v)


# === A6: CredentialCandidate — controlled repr, no arbitrary key/path ===
class TestCredentialCandidate(unittest.TestCase):
    def test_repr_no_raw_key_path(self):
        c = _make_cand("s","SENSITIVE_KEY",b"LEAK_A6")
        r = repr(c)
        self.assertNotIn("SENSITIVE_KEY", r)
        self.assertNotIn("LEAK_A6", r)

    def test_from_catalog_key_shown(self):
        c = _make_cand("s","DEEPSEEK_KEY",b"v",from_cat=True)
        self.assertEqual(c.display_key, "DEEPSEEK_KEY")

    def test_unknown_key_marker(self):
        c = _make_cand("s","ARBITRARY_UNKNOWN",b"v")
        self.assertEqual(c.display_key, _FIXED_UNKNOWN_KEY_MARKER)

    def test_field_name_shown(self):
        c = _make_cand("s","ANTHROPIC_API_KEY",b"v",fname="ANTHROPIC_API_KEY")
        self.assertEqual(c.display_key, "ANTHROPIC_API_KEY")

    def test_asdict_no_leak(self):
        sentinel = b"ASDICT_LEAK_A6"
        c = _make_cand("s","BAD_KEY",sentinel)
        r = CredentialResult(status=CredentialStatus.OK, candidate=c, provider_id="ds", reason_code=ReasonCode.OK)
        d = dataclasses.asdict(r)
        j = json.dumps(d, default=repr)
        self.assertNotIn("BAD_KEY", str(d))
        self.assertNotIn(sentinel.decode(), str(d))
        self.assertNotIn(sentinel.decode(), j)

    def test_repr_no_source_path(self):
        c = _make_cand("s","k",b"x",src_path="/evil/leak/path")
        self.assertNotIn("/evil/leak/path", repr(c))

    def test_to_summary_no_leak(self):
        sentinel = b"SUMMARY_A6"
        c = _make_cand("s","SK",sentinel)
        r = CredentialResult(status=CredentialStatus.OK, candidate=c, provider_id="ds", reason_code=ReasonCode.OK)
        self.assertNotIn(sentinel.decode(), str(r.to_summary()))


# === A4: canonical_url ===
class TestCanonicalUrl(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(canonical_url("HTTPS://API.Deepseek.COM/Anthropic"), "https://api.deepseek.com/Anthropic/")
    def test_default_port(self):
        self.assertEqual(canonical_url("https://e.com:443/p"), "https://e.com/p/")
    def test_non_default_port(self):
        self.assertEqual(canonical_url("https://e.com:8443/p"), "https://e.com:8443/p/")
    def test_trailing_path(self):
        self.assertEqual(canonical_url("https://e.com"), "https://e.com/")
    def test_path_case(self):
        self.assertEqual(canonical_url("https://e.com/MyPath"), "https://e.com/MyPath/")
    def test_query(self):
        self.assertEqual(canonical_url("https://e.com/p?K=V"), "https://e.com/p/?K=V")
    def test_fragment(self):
        self.assertEqual(canonical_url("https://e.com/p#f"), "https://e.com/p/#f")
    def test_query_fragment(self):
        self.assertEqual(canonical_url("https://e.com/p?q=1#f"), "https://e.com/p/?q=1#f")
    def test_percent2F(self):
        self.assertEqual(canonical_url("https://e.com/%2Ffoo"), "https://e.com/%2Ffoo/")
    def test_ipv6_strip_default(self):
        u = canonical_url("https://[::1]:443/a"); self.assertIn("[::1]/a/", u)
    def test_ipv6_non_default(self):
        u = canonical_url("https://[::1]:8080/a"); self.assertIn("[::1]:8080/a/", u)
    def test_reject_userinfo(self):
        with self.assertRaises(ValueError): canonical_url("https://u@e.com")
    def test_reject_non_http(self):
        with self.assertRaises(ValueError): canonical_url("ftp://e.com")
    def test_reject_no_hostname(self):
        with self.assertRaises(ValueError): canonical_url("https:///path")


# === ProviderCatalog ===
class TestProviderCatalog(unittest.TestCase):
    def _s(self, **kw):
        d={"id":"ds","name":"DS","auth_type":"token","auth_key_name":"DS_KEY","base_url":""}; d.update(kw); return ProviderSpec(**d)
    def test_valid(self):
        self.assertIn("ds", ProviderCatalog.build({"ds":self._s()}).providers)
    def test_bool_schema(self):
        with self.assertRaises(ValueError): ProviderCatalog.build({"ds":self._s()}, schema_version=True)
    def test_empty(self):
        with self.assertRaises(ValueError): ProviderCatalog.build({})
    def test_dup_auth(self):
        with self.assertRaises(ValueError): ProviderCatalog.build({"a":self._s(id="a",auth_key_name="X"),"b":self._s(id="b",auth_key_name="X")})
    def test_dup_url(self):
        with self.assertRaises(ValueError): ProviderCatalog.build({"a":self._s(id="a",base_url="https://x.com"),"b":self._s(id="b",base_url="https://x.com")})
    def test_mapping_proxy(self):
        from types import MappingProxyType
        self.assertIsInstance(ProviderCatalog.build({"ds":self._s()}).providers, MappingProxyType)
    def test_real_json(self):
        real=str(Path(__file__).resolve().parent.parent.parent/"container"/"providers.json")
        if Path(real).exists():
            from aisc.adapters.config_source import load_provider_catalog
            cat=load_provider_catalog(Path(real).read_bytes())
            self.assertIn("cc",cat.providers); self.assertEqual(cat.providers["deepseek"].auth_type,"token")


# === classify_credentials ===
class TestClassify(unittest.TestCase):
    def test_dedup(self):
        r=[CredentialResult(CredentialStatus.OK,_make_cand("a","K",b"v"),"ds"),
           CredentialResult(CredentialStatus.OK,_make_cand("b","K",b"v"),"ds")]
        c=classify_credentials(r)
        self.assertEqual(sum(1 for x in c if x.status==CredentialStatus.OK),1)
        self.assertEqual(sum(1 for x in c if x.status==CredentialStatus.AUDIT),1)
    def test_diff_0ok(self):
        r=[CredentialResult(CredentialStatus.OK,_make_cand("a","K",b"v1"),"ds"),
           CredentialResult(CredentialStatus.OK,_make_cand("b","K",b"v2"),"ds")]
        c=classify_credentials(r)
        self.assertEqual(sum(1 for x in c if x.status==CredentialStatus.OK),0)
        self.assertEqual(sum(1 for x in c if x.status==CredentialStatus.CONFLICT),2)
    def test_already_conflict(self):
        r=[CredentialResult(CredentialStatus.CONFLICT,_make_cand("a","K",b"v"),"ds"),
           CredentialResult(CredentialStatus.OK,_make_cand("b","K",b"v"),"ds")]
        c=classify_credentials(r)
        self.assertEqual(sum(1 for x in c if x.status==CredentialStatus.OK),0)
        self.assertEqual(sum(1 for x in c if x.status==CredentialStatus.CONFLICT),2)
    def test_unmapped_passthrough(self):
        r=[CredentialResult(CredentialStatus.UNMAPPED,reason_code=ReasonCode.UNMAPPED)]
        self.assertEqual(classify_credentials(r)[0].status,CredentialStatus.UNMAPPED)


# === PathPolicy ===
class TestPathPolicy(unittest.TestCase):
    def test_valid(self):
        pp=PathPolicy(PlatformPathConfig("/c","/s","/sec"),workspace="/tmp/ws"); self.assertEqual(pp.workspace,"/tmp/ws")
    def test_reject_empty(self):
        with self.assertRaises(ValueError): PathPolicy(PlatformPathConfig("/c","/s","/sec"),workspace="")
    def test_reject_relative(self):
        with self.assertRaises(ValueError): PathPolicy(PlatformPathConfig("/c","/s","/sec"),workspace="rel")
    def test_reject_whitespace(self):
        with self.assertRaises(ValueError): PathPolicy(PlatformPathConfig("/c","/s","/sec"),workspace=" /t ")
    def test_none_ok(self):
        self.assertIsNone(PathPolicy(PlatformPathConfig("/c","/s","/sec")).workspace)


# === State models ===
class TestStateModels(unittest.TestCase):
    def test_entry_repr_no_value(self):
        e=StateEntry(key="IMAGE",value="secret",source=".aisc",line_no=1)
        self.assertNotIn("secret",repr(e))
    def test_entry_to_summary_no_value(self):
        e=StateEntry(key="IMAGE",value="secret_val",source=".aisc",line_no=1)
        self.assertNotIn("secret_val",str(e.to_summary()))
    def test_issue_no_raw(self):
        si=StateIssue(source=".aisc",line_no=5,reason_code="unknown_key",message="Unknown")
        self.assertNotIn("unknown_key_value",repr(si).lower())


if __name__=="__main__":
    unittest.main()
