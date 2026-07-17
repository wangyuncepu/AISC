"""Unit tests — config schema & legacy parsers (Oracle ora-6 final)."""

import json, re, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from aisc.domain.config import (
    CredentialCandidate, CredentialResult, CredentialStatus, CredentialValue,
    IssueSeverity, ProviderCatalog, ProviderSpec, ReasonCode,
    StateEntry, StateIssue, LegacyStateReport,
)
from aisc.schemas.config_schema import (
    validate_config, parse_api_keys, parse_settings,
    parse_raw_state_bytes, merge_state,
)

# ==============================
# Config schema validation
# ==============================
class TestValidateConfig(unittest.TestCase):
    def test_valid_user(self):
        self.assertEqual(validate_config({"schema_version":1,"provider":{"id":"deepseek","auth":{"secret_ref":"provider:deepseek"}}}), [])

    def test_valid_no_provider(self):
        self.assertEqual(validate_config({"schema_version":1}), [])

    def test_user_missing_auth(self):
        issues = validate_config({"schema_version":1,"provider":{"id":"deepseek"}}, is_workspace=False)
        self.assertTrue(any(i.reason_code=="provider_auth_missing" for i in issues))

    def test_workspace_auth_forbidden(self):
        issues = validate_config({"schema_version":1,"provider":{"id":"ds","auth":{"secret_ref":"provider:ds"}}}, is_workspace=True)
        self.assertTrue(any(i.reason_code=="workspace_auth_forbidden" for i in issues))

    def test_schema_version_bool(self):
        issues = validate_config({"schema_version":True})
        self.assertTrue(any(i.reason_code=="schema_version_type" for i in issues))

    def test_provider_id_invalid(self):
        issues = validate_config({"schema_version":1,"provider":{"id":"BAD!"}})
        self.assertTrue(any(i.reason_code=="provider_id_invalid" for i in issues))

    def test_secret_ref_mismatch(self):
        issues = validate_config({"schema_version":1,"provider":{"id":"ds","auth":{"secret_ref":"provider:other"}}})
        self.assertTrue(any(i.reason_code=="secret_ref_mismatch" for i in issues))

    def test_unknown_keys_dont_echo(self):
        issues = validate_config({"schema_version":1,"HACK":"evil"})
        for i in issues:
            self.assertNotIn("HACK", i.message)
            self.assertNotIn("evil", i.message)

    def test_invalid_profile_not_echoed(self):
        issues = validate_config({"schema_version":1,"defaults":{"profile":"MY_CUSTOM"}})
        for i in issues:
            self.assertNotIn("MY_CUSTOM", i.message)

    def test_invalid_network_not_echoed(self):
        issues = validate_config({"schema_version":1,"defaults":{"network":"TUNNEL"}})
        for i in issues:
            self.assertNotIn("TUNNEL", i.message)


# ==============================
# A1: parse_api_keys — value NOT stripped, exact bytes
# ==============================
class TestParseApiKeys(unittest.TestCase):
    def setUp(self):
        self.cat = ProviderCatalog.build({"deepseek":ProviderSpec(id="deepseek",name="DS",auth_type="token",auth_key_name="DEEPSEEK_KEY",base_url="")})

    def _p(self, raw): return parse_api_keys(raw, "t", "/p", catalog=self.cat)

    def test_value_exact_bytes(self):
        """A1: value preserved exactly, including leading/trailing spaces."""
        r = self._p(b"DEEPSEEK_KEY=  value  \n")
        ok = [x for x in r if x.status==CredentialStatus.OK]
        self.assertTrue(len(ok)>0)
        self.assertEqual(ok[0].candidate.value._raw, b"  value  ")

    def test_whitespace_only_value(self):
        """A1: whitespace-only value is preserved (not stripped)."""
        r = self._p(b"DEEPSEEK_KEY=   \n")
        ok = [x for x in r if x.status==CredentialStatus.OK]
        self.assertTrue(len(ok)>0)
        self.assertEqual(ok[0].candidate.value._raw, b"   ")

    def test_crlf(self):
        r = self._p(b"DEEPSEEK_KEY=val\r\n")
        self.assertTrue(any(x.status==CredentialStatus.OK for x in r))

    def test_bom_rejected(self):
        r = self._p(b"\xef\xbb\xbfDEEPSEEK_KEY=val\n")
        self.assertTrue(any(x.reason_code==ReasonCode.MALFORMED_VALUE_BOM for x in r))

    def test_nul_rejected(self):
        r = self._p(b"DEEPSEEK_KEY=val\x00ue\n")
        self.assertTrue(any(x.reason_code==ReasonCode.MALFORMED_VALUE_NUL for x in r))

    def test_cr_in_value_rejected(self):
        r = self._p(b"DEEPSEEK_KEY=val\rue\n")
        self.assertTrue(any(x.reason_code==ReasonCode.MALFORMED_VALUE_CRLF for x in r))

    # A3: dup-diff zero OK, same provider_id
    def test_dup_diff_zero_ok(self):
        r = self._p(b"DEEPSEEK_KEY=v1\nDEEPSEEK_KEY=v2\n")
        self.assertEqual(sum(1 for x in r if x.status==CredentialStatus.OK), 0)
        conflicts = [x for x in r if x.status==CredentialStatus.CONFLICT]
        self.assertEqual(len(conflicts), 2)
        # A3: all share provider_id
        for c in conflicts:
            self.assertEqual(c.provider_id, "deepseek")

    def test_dup_same_audit(self):
        r = self._p(b"DEEPSEEK_KEY=same\nDEEPSEEK_KEY=same\n")
        self.assertEqual(sum(1 for x in r if x.status==CredentialStatus.OK), 1)
        self.assertEqual(sum(1 for x in r if x.status==CredentialStatus.AUDIT), 1)

    # A6: repr no raw key_name
    def test_repr_no_raw_key(self):
        r = self._p(b"ARBITRARY_UNKNOWN_KEY=secret\n")
        rep = repr(r)
        self.assertNotIn("ARBITRARY_UNKNOWN_KEY", rep)
        self.assertNotIn("secret", rep)

    def test_sentinel_not_in_repr(self):
        s = b"SENTINEL_APIKEY_A1"
        r = self._p(b"DEEPSEEK_KEY=" + s + b"\n")
        self.assertNotIn(s.decode(), repr(r))

    def test_multiple_equals(self):
        r = self._p(b"DEEPSEEK_KEY=val=with=equals\n")
        ok = [x for x in r if x.status==CredentialStatus.OK]
        self.assertTrue(len(ok)>0)
        self.assertTrue(ok[0].candidate.value._raw.startswith(b"val=with=equals"))


# ==============================
# A2: parse_settings — auth_type matching
# ==============================
class TestParseSettings(unittest.TestCase):
    def setUp(self):
        self.cat = ProviderCatalog.build({
            "deepseek":ProviderSpec(id="deepseek",name="DS",auth_type="token",auth_key_name="DS",base_url="https://api.deepseek.com/anthropic"),
            "cc":ProviderSpec(id="cc",name="CC",auth_type="api_key",auth_key_name="CC",base_url="https://api.anthropic.com"),
        })

    def _p(self, d): return parse_settings(json.dumps(d).encode(),"t","/p",catalog=self.cat)

    # A2: AUTH_TOKEN matches only token providers
    def test_token_matches_token_provider(self):
        r = self._p({"env":{"ANTHROPIC_BASE_URL":"https://api.deepseek.com/anthropic","ANTHROPIC_AUTH_TOKEN":"sk"}})
        ok = [x for x in r if x.status==CredentialStatus.OK]
        self.assertEqual(len(ok), 1)
        self.assertEqual(ok[0].provider_id, "deepseek")

    def test_token_mismatch_api_key_provider(self):
        """A2: AUTH_TOKEN where only api_key provider matches URL → unmapped."""
        r = self._p({"env":{"ANTHROPIC_BASE_URL":"https://api.anthropic.com","ANTHROPIC_AUTH_TOKEN":"sk"}})
        ok = [x for x in r if x.status==CredentialStatus.OK]
        self.assertEqual(len(ok), 0)

    def test_api_key_matches_api_key_provider(self):
        r = self._p({"env":{"ANTHROPIC_BASE_URL":"https://api.anthropic.com","ANTHROPIC_API_KEY":"sk"}})
        ok = [x for x in r if x.status==CredentialStatus.OK]
        self.assertEqual(len(ok), 1)
        self.assertEqual(ok[0].provider_id, "cc")

    def test_api_key_mismatch_token_provider(self):
        r = self._p({"env":{"ANTHROPIC_BASE_URL":"https://api.deepseek.com/anthropic","ANTHROPIC_API_KEY":"sk"}})
        ok = [x for x in r if x.status==CredentialStatus.OK]
        self.assertEqual(len(ok), 0)

    # A2: candidate key_name/field_name equals real field
    def test_candidate_field_name_is_real(self):
        r = self._p({"env":{"ANTHROPIC_BASE_URL":"https://api.anthropic.com","ANTHROPIC_API_KEY":"sk"}})
        self.assertTrue(r[0].candidate._fname == "ANTHROPIC_API_KEY")

    # B5: two tokens same value
    def test_two_same_value_canonical(self):
        r = self._p({"env":{"ANTHROPIC_BASE_URL":"https://api.deepseek.com/anthropic",
            "ANTHROPIC_AUTH_TOKEN":"same","ANTHROPIC_API_KEY":"same"}})
        self.assertEqual(sum(1 for x in r if x.status==CredentialStatus.OK), 1)
        self.assertEqual(sum(1 for x in r if x.status==CredentialStatus.DUPLICATE_SAME), 1)

    # B5: two tokens different → both CONFLICT
    def test_two_different_both_conflict(self):
        r = self._p({"env":{"ANTHROPIC_BASE_URL":"https://api.deepseek.com/anthropic",
            "ANTHROPIC_AUTH_TOKEN":"tok","ANTHROPIC_API_KEY":"key"}})
        self.assertEqual(sum(1 for x in r if x.status==CredentialStatus.OK), 0)
        self.assertEqual(sum(1 for x in r if x.status==CredentialStatus.CONFLICT), 2)

    def test_sentinel_not_in_repr(self):
        s = "SETTINGS_SENT_B5"
        r = self._p({"env":{"ANTHROPIC_BASE_URL":"https://api.deepseek.com/anthropic","ANTHROPIC_AUTH_TOKEN":s}})
        self.assertNotIn(s, repr(r))


# ==============================
# A5: State — strict models, no raw in issues
# ==============================
class TestStateParser(unittest.TestCase):
    def test_entries_issues_separate(self):
        entries, issues = parse_raw_state_bytes(b"IMAGE=img\nUNKNOWN=x\n", ".aisc")
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].reason_code, "unknown_key")

    def test_issue_no_raw_value(self):
        _, issues = parse_raw_state_bytes(b"HACK=evil\n", ".aisc")
        r = repr(issues[0])
        self.assertNotIn("evil", r)
        self.assertNotIn("HACK", r)

    # --- merge_state: blocker 1 ---
    def test_merge_last_one_wins(self):
        aisc = [("IMAGE","v2",".aisc",1),("IMAGE","v2b",".aisc",2)]
        deploy = [("IMAGE","v1",".deploy",1)]
        report = merge_state(aisc, deploy, [], [])
        eff = {e.key:e.value for e in report.effective}
        self.assertEqual(eff["IMAGE"], "v2b")
        imgs = [e for e in report.all_entries if e.key=="IMAGE"]
        self.assertTrue(any(e.shadowed for e in imgs))

    def test_merge_deploy_only_duplicates_last_wins(self):
        """Deploy-only IMAGE=v1/v2 => effective v2, v1 shadowed."""
        deploy = [("IMAGE","v1",".deploy",1),("IMAGE","v2",".deploy",2)]
        report = merge_state([], deploy, [], [])
        self.assertEqual(report.effective[0].value, "v2")
        self.assertEqual(len(report.all_entries), 2)
        self.assertTrue(any(e.shadowed for e in report.all_entries))

    def test_merge_aisc_only_duplicates_last_wins(self):
        """AISC-only IMAGE=v1/v2 => effective v2."""
        aisc = [("IMAGE","v1",".aisc",1),("IMAGE","v2",".aisc",2)]
        report = merge_state(aisc, [], [], [])
        self.assertEqual(report.effective[0].value, "v2")

    def test_merge_both_duplicates_aisc_wins(self):
        """Both sources have duplicates: aisc last wins, all deploy shadowed."""
        aisc = [("IMAGE","a1",".aisc",1),("IMAGE","a2",".aisc",2)]
        deploy = [("IMAGE","d1",".deploy",1),("IMAGE","d2",".deploy",2)]
        report = merge_state(aisc, deploy, [], [])
        self.assertEqual(report.effective[0].value, "a2")
        # All 4 entries in all_entries
        self.assertEqual(len(report.all_entries), 4)
        # Deploy entries all shadowed
        for e in report.all_entries:
            if e.source == ".deploy":
                self.assertTrue(e.shadowed, f"deploy entry should be shadowed: {e}")
        # AISC early duplicate shadowed
        aisc_early = [e for e in report.all_entries if e.source==".aisc" and e.value=="a1"]
        self.assertEqual(len(aisc_early), 1)
        self.assertTrue(aisc_early[0].shadowed)

    def test_merge_preserves_all(self):
        aisc = [("IMAGE","v2",".aisc",1)]
        deploy = [("IMAGE","v1",".deploy",1)]
        report = merge_state(aisc, deploy, [], [])
        self.assertEqual(len(report.all_entries), 2)

    def test_merge_no_mutate_input(self):
        aisc = [("IMAGE","v2",".aisc",1)]
        deploy = [("IMAGE","v1",".deploy",1)]
        orig_aisc = list(aisc)
        orig_deploy = list(deploy)
        merge_state(aisc, deploy, [], [])
        self.assertEqual(aisc, orig_aisc)
        self.assertEqual(deploy, orig_deploy)

    def test_state_entry_repr_no_value(self):
        e = StateEntry(key="IMAGE", value="secret", source=".aisc", line_no=1)
        self.assertNotIn("secret", repr(e))


if __name__ == "__main__":
    unittest.main()
