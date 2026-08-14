# Test fixtures

Content-addressed baseline fixtures (Stage 0, B-01). Every file here is hashed
by `scripts/baseline/run_baseline.py` and committed to the repo so two clean
checkouts produce an identical `fixture_hashes` map.

## `cli/` — `aisc.cli/v1` contract fixtures (S0.2, B-A03)

Consumed by all three layers against the same files:

- Python: `tests/test_cli_fixtures.py`
- Rust: `workbench/src-tauri/tests/cli_fixtures.rs`
- TypeScript: `workbench/src/lib/__tests__/cliFixtures.test.ts`

| File | Purpose |
|---|---|
| `envelope-version.json` | Golden `version` envelope with capabilities |
| `envelope-error-invalid-runtime-id.json` | Exit 15, `AISC_ERR_INVALID_RUNTIME_ID` |
| `envelope-error-usage.json` | Exit 2, `AISC_ERR_USAGE` |
| `envelope-unknown-field.json` | Unknown fields must survive round-trip |
| `envelope-unsupported-protocol.json` | `aisc.cli/v2` — negative, consumers reject |
| `events-build.jsonl` | `build --events` JSONL, seq 1..5, terminal `build.complete` |
| `error-codes.json` | Stable error-code manifest (code → exit/retryable/action) |

## `redaction/` — denylist shapes (S0.5, B-A08)

`denylist.txt` holds realistic-but-not-real secret shapes (Anthropic/OpenAI
keys, OAuth JWTs, env-pair values). Rust `redact()` must never emit a raw
line; the matrix test is `error::tests::redact_denylist_fixture_never_leaks`.

Do not store real secrets, terminal scrollback, or machine-specific absolute
paths here; fixtures must be deterministic across environments. When changing
a fixture, update the baseline `fixture_hashes` and all consumers together.
