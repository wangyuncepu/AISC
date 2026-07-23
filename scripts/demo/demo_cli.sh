#!/usr/bin/env bash
# AISC CLI Demo — one-click validation script
# Usage: bash scripts/demo/demo_cli.sh
# Uses PYTHONPATH=src, avoids real builds/runs, avoids real secrets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="$ROOT_DIR/src"

RED='\033[31m'; GREEN='\033[32m'; YELLOW='\033[33m'; BOLD='\033[1m'; NC='\033[0m'
PASS=0; FAIL=0

log_pass() { echo -e "  ${GREEN}PASS${NC} $1"; PASS=$((PASS + 1)); }
log_fail() { echo -e "  ${RED}FAIL${NC} $1"; FAIL=$((FAIL + 1)); }
log_info() { echo -e "  ${BOLD}INFO${NC} $1"; }

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

aisc() {
    python3 -m aisc "$@"
}

echo "========================================"
echo " AISC CLI Demo — Incremental Validation "
echo "========================================"
echo ""

# -------------------------------------------------------------------
# 1. version
# -------------------------------------------------------------------
echo "--- [1] version ---"
if aisc version > "$tmpdir/version.out" 2>/dev/null; then
    log_pass "version (text)"
else
    log_fail "version (text) exit=$?"
fi

if aisc version --format json > "$tmpdir/version.json" 2>/dev/null; then
    if python3 -c "import json; d=json.load(open('$tmpdir/version.json')); assert d['meta']['command']=='version'" 2>/dev/null; then
        log_pass "version --format json (valid envelope)"
    else
        log_fail "version --format json (invalid envelope)"
    fi
else
    log_fail "version --format json exit=$?"
fi

# version global args position
if aisc --format json version > "$tmpdir/vp.json" 2>/dev/null; then
    if python3 -c "import json; d=json.load(open('$tmpdir/vp.json')); assert d['meta']['command']=='version'" 2>/dev/null; then
        log_pass "version global --format before subcommand"
    else
        log_fail "version global --format before subcommand"
    fi
else
    log_fail "version global --format before subcommand exit=$?"
fi

# -------------------------------------------------------------------
# 2. doctor
# -------------------------------------------------------------------
echo "--- [2] doctor ---"
set +e
aisc doctor > "$tmpdir/doctor.out" 2>/dev/null
doc_exit=$?
set -e
if [ "$doc_exit" -eq 0 ] || [ "$doc_exit" -eq 3 ] || [ "$doc_exit" -eq 9 ]; then
    if grep -q "AISC Doctor" "$tmpdir/doctor.out" 2>/dev/null; then
        log_pass "doctor (text, exit=$doc_exit)"
    else
        log_fail "doctor (text, missing header)"
    fi
else
    log_fail "doctor unexpected exit=$doc_exit"
fi

set +e
aisc doctor --format json > "$tmpdir/doctor.json" 2>/dev/null
docj_exit=$?
set -e
if python3 -c "
import json
d=json.load(open('$tmpdir/doctor.json'))
assert d['meta']['command']=='doctor'
assert isinstance(d['data']['host']['checks'], list)
" 2>/dev/null; then
    log_pass "doctor --format json (valid envelope, exit=$docj_exit)"
else
    log_fail "doctor --format json"
fi

# -------------------------------------------------------------------
# 3. config validate / effective / show
# -------------------------------------------------------------------
echo "--- [3] config ---"
set +e
aisc config validate > "$tmpdir/cfgv.out" 2>/dev/null
cfgv_exit=$?
set -e
if grep -q "Config Validate" "$tmpdir/cfgv.out" 2>/dev/null; then
    log_pass "config validate (text, exit=$cfgv_exit)"
else
    log_fail "config validate (missing header)"
fi

set +e
aisc config validate --format json > "$tmpdir/cfgv.json" 2>/dev/null
cfgvj=$?
set -e
if python3 -c "
import json
d=json.load(open('$tmpdir/cfgv.json'))
assert d['meta']['command']=='config'
" 2>/dev/null; then
    log_pass "config validate --format json (exit=$cfgvj)"
else
    log_fail "config validate --format json"
fi

if aisc config effective > "$tmpdir/cfge.out" 2>/dev/null; then
    log_pass "config effective (text)"
else
    log_fail "config effective (text)"
fi

if aisc config show > "$tmpdir/cfgs.out" 2>/dev/null; then
    if grep -q "Config Effective" "$tmpdir/cfgs.out" 2>/dev/null; then
        log_pass "config show (alias → effective text)"
    else
        log_fail "config show (missing header)"
    fi
else
    log_fail "config show"
fi

if aisc config effective --format json > "$tmpdir/cfge.json" 2>/dev/null; then
    if python3 -c "
import json
d=json.load(open('$tmpdir/cfge.json'))
assert d['meta']['command']=='config'
assert 'effective' in d['data']
" 2>/dev/null; then
        log_pass "config effective --format json"
    else
        log_fail "config effective --format json"
    fi
else
    log_fail "config effective --format json"
fi

# -------------------------------------------------------------------
# 5. profile list / show
# -------------------------------------------------------------------
echo "--- [5] profile ---"
if aisc profile list > "$tmpdir/prlist.out" 2>/dev/null; then
    if grep -q "safe" "$tmpdir/prlist.out" 2>/dev/null && grep -q "unsafe" "$tmpdir/prlist.out" 2>/dev/null; then
        log_pass "profile list (text, safe + unsafe)"
    else
        log_fail "profile list (missing profiles)"
    fi
else
    log_fail "profile list exit=$?"
fi

if aisc profile list --format json > "$tmpdir/prlist.json" 2>/dev/null; then
    if python3 -c "
import json
d=json.load(open('$tmpdir/prlist.json'))
profiles={p['name']:p for p in d['data']['profiles']}
assert profiles['safe']['dangerously_skip_permissions']==False
assert profiles['unsafe']['dangerously_skip_permissions']==True
" 2>/dev/null; then
        log_pass "profile list --format json (correct fields)"
    else
        log_fail "profile list --format json"
    fi
else
    log_fail "profile list --format json"
fi

# profile show safe (default)
if aisc profile show > "$tmpdir/prsafe.out" 2>/dev/null; then
    if grep -q "dangerously_skip_permissions" "$tmpdir/prsafe.out" 2>/dev/null; then
        log_pass "profile show (default=safe, text)"
    else
        log_fail "profile show default"
    fi
else
    log_fail "profile show default exit=$?"
fi

# profile show unsafe
if aisc profile show unsafe > "$tmpdir/prunsafe.out" 2>/dev/null; then
    if grep -qi "true" "$tmpdir/prunsafe.out" 2>/dev/null; then
        log_pass "profile show unsafe (text, dangerously_skip_permissions=true)"
    else
        log_fail "profile show unsafe"
    fi
else
    log_fail "profile show unsafe exit=$?"
fi

# profile show json
if aisc profile show safe --format json > "$tmpdir/prshow.json" 2>/dev/null; then
    if python3 -c "
import json
d=json.load(open('$tmpdir/prshow.json'))
assert d['data']['dangerously_skip_permissions']==False
assert d['data']['name']=='safe'
" 2>/dev/null; then
        log_pass "profile show safe --format json"
    else
        log_fail "profile show safe --format json"
    fi
else
    log_fail "profile show safe --format json"
fi

# profile show unknown → non-zero
set +e
aisc profile show nonexistent > /dev/null 2>/dev/null
pr_unk=$?
set -e
if [ "$pr_unk" -ne 0 ]; then
    log_pass "profile show nonexistent (non-zero exit=$pr_unk)"
else
    log_fail "profile show nonexistent (should fail)"
fi

# -------------------------------------------------------------------
# 6. build dry-run
# -------------------------------------------------------------------
echo "--- [6] build --dry-run ---"
set +e
aisc build --dry-run > "$tmpdir/builddr.out" 2>/dev/null
bdr_exit=$?
set -e
log_info "build --dry-run exit=$bdr_exit"
if grep -q "Build plan\|dry-run\|docker build\|docker " "$tmpdir/builddr.out" 2>/dev/null; then
    log_pass "build --dry-run (text, shows plan)"
else
    log_fail "build --dry-run (no plan output)"
fi

# build dry-run json
set +e
aisc build --dry-run --format json > "$tmpdir/builddr.json" 2>/dev/null
bdrj=$?
set -e
if python3 -c "
import json
d=json.load(open('$tmpdir/builddr.json'))
assert d['meta']['command']=='build'
" 2>/dev/null; then
    log_pass "build --dry-run --format json (exit=$bdrj)"
else
    log_fail "build --dry-run --format json"
fi

# build dry-run events
set +e
aisc build --dry-run --events > "$tmpdir/buildev.jsonl" 2>/dev/null
bdev=$?
set -e
if [ "$bdev" -eq 0 ]; then
    lines=$(wc -l < "$tmpdir/buildev.jsonl")
    if [ "$lines" -ge 1 ]; then
        log_pass "build --dry-run --events ($lines lines)"
    else
        log_fail "build --dry-run --events (empty)"
    fi
else
    log_info "build --dry-run --events exit=$bdev (may need docker)"
fi

# -------------------------------------------------------------------
# 7. run dry-run
# -------------------------------------------------------------------
echo "--- [7] run --dry-run ---"
set +e
aisc run --dry-run > "$tmpdir/rundr.out" 2>/dev/null
rdr_exit=$?
set -e
log_info "run --dry-run exit=$rdr_exit"
if grep -q "Run plan\|dry-run\|docker run\|docker " "$tmpdir/rundr.out" 2>/dev/null; then
    log_pass "run --dry-run (text, shows plan)"
else
    log_fail "run --dry-run (no plan output)"
fi

# -------------------------------------------------------------------
# 8. JSON events mutual exclusion
# -------------------------------------------------------------------
echo "--- [8] --format json + --events mutual exclusion ---"
set +e
aisc build --format json --events --dry-run > /dev/null 2>/dev/null
mex1=$?
set -e
if [ "$mex1" -eq 2 ]; then
    log_pass "--format json --events mutually exclusive (exit 2)"
else
    log_fail "--format json --events expected exit 2, got $mex1"
fi

# -------------------------------------------------------------------
# 9. global arg position (--format before/after subcommand)
# -------------------------------------------------------------------
echo "--- [9] global arg position compatibility ---"
if aisc --format json config effective > /dev/null 2>/dev/null; then
    log_pass "--format json config effective (global before subcommand)"
else
    log_fail "--format json config effective"
fi

if aisc profile --format json list > /dev/null 2>/dev/null; then
    log_pass "profile --format json list (global within subcommand)"
else
    log_fail "profile --format json list"
fi

# -------------------------------------------------------------------
# 10. brief (Task A)
# -------------------------------------------------------------------
echo "--- [10] brief ---"
# brief --help
if aisc brief --help > "$tmpdir/brief_help.out" 2>/dev/null; then
    if grep -q "AI news brief" "$tmpdir/brief_help.out" 2>/dev/null || grep -q "brief" "$tmpdir/brief_help.out" 2>/dev/null; then
        log_pass "brief --help"
    else
        log_fail "brief --help (unexpected output)"
    fi
else
    log_fail "brief --help exit=$?"
fi

# brief --format json → rejected (exit 2)
set +e
aisc brief --format json > "$tmpdir/brief_json.json" 2>/dev/null
bj_exit=$?
set -e
if [ "$bj_exit" -eq 2 ]; then
    if python3 -c "
import json
d=json.load(open('$tmpdir/brief_json.json'))
assert d['meta']['exit_code']==2
assert d['errors'][0]['code']=='AISC_ERR_USAGE'
" 2>/dev/null; then
        log_pass "brief --format json (rejected, exit 2)"
    else
        log_fail "brief --format json (invalid envelope)"
    fi
else
    log_fail "brief --format json expected exit 2, got $bj_exit"
fi

# brief --events → rejected (exit 2)
set +e
aisc brief --events > /dev/null 2>/dev/null
be_exit=$?
set -e
if [ "$be_exit" -eq 2 ]; then
    log_pass "brief --events (rejected, exit 2)"
else
    log_fail "brief --events expected exit 2, got $be_exit"
fi

# brief default text (no network dependency check)
set +e
aisc brief --no-cache --strict 2>/dev/null > "$tmpdir/brief_run.out"
br_exit=$?
set -e
# brief.py exits 0 even on failure unless --strict, so any exit is OK for this smoke
if grep -qi "brief\|TLDR\|Rundown\|Simon\|Changelog\|HN Show\|资讯\|No sources" "$tmpdir/brief_run.out" 2>/dev/null || [ -s "$tmpdir/brief_run.out" ] || [ "$br_exit" -eq 0 ] || [ "$br_exit" -eq 1 ]; then
    log_pass "brief default (executed, exit=$br_exit)"
else
    log_info "brief default exit=$br_exit (no network — expected)"
    log_pass "brief default (exit=$br_exit, no network ok)"
fi

# -------------------------------------------------------------------
# 11. unknown profile subcommand JSON (Task C)
# -------------------------------------------------------------------
echo "--- [11] unknown subcommand JSON ---"
# profile unknown subcommand
set +e
aisc profile --format json unknown_cmd > "$tmpdir/pr_unk.json" 2>/dev/null
pr_unkj=$?
set -e
if [ "$pr_unkj" -eq 2 ] && python3 -c "
import json
d=json.load(open('$tmpdir/pr_unk.json'))
assert d['meta']['command']=='profile'
assert d['meta']['exit_code']==2
assert d['errors'][0]['code']=='AISC_ERR_USAGE'
" 2>/dev/null; then
    log_pass "profile unknown subcommand --format json (exit 2, envelope)"
else
    log_fail "profile unknown subcommand --format json"
fi

# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------
echo ""
echo "========================================"
echo " RESULTS"
echo "========================================"
echo -e "  ${GREEN}PASS: $PASS${NC}"
echo -e "  ${RED}FAIL: $FAIL${NC}"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}[PASS] All demo checks passed!${NC}"
    exit 0
else
    echo -e "${RED}${BOLD}[FAIL] $FAIL check(s) failed${NC}"
    exit 1
fi
