# Test fixtures

Content-addressed baseline fixtures (Stage 0, B-01). Every file here is hashed
by `scripts/baseline/run_baseline.py` and committed to the repo so two clean
checkouts produce an identical `fixture_hashes` map.

- `cli/` — `aisc.cli/v1` envelope/JSONL contract fixtures (Stage 0, S0.2).
- Do not store secrets, terminal scrollback, or machine-specific absolute paths
  here; fixtures must be deterministic across environments.
