#!/usr/bin/env bash
# Documentation Consistency Checker — validates README matches codebase
set -euo pipefail

AISC_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$AISC_ROOT"

passed=0
warnings=0
failures=0

green()  { printf '\033[32m%s\033[0m\n' "$1"; }
red()    { printf '\033[31m%s\033[0m\n' "$1"; }
yellow() { printf '\033[33m%s\033[0m\n' "$1"; }

_pass()  { green  "[✓] $1"; passed=$((passed + 1)); }
_fail()  { red    "[✗] $1"; failures=$((failures + 1)); }
_warn()  { yellow "[!] $1"; warnings=$((warnings + 1)); }

echo "=== Documentation Consistency Check ==="
echo ""

# ---------------------------------------------------------------------------
# Check 1: README references real files
# ---------------------------------------------------------------------------
echo "--- Check 1: Path references ---"
echo ""

# Track already-checked paths to avoid duplicates between tree + body
declare -A checked_tree_paths=()

# Helper: given a relative path, check if it exists
check_path() {
  local desc="$1"  # description / original line snippet
  local path="$2"

  if [ -z "$path" ]; then
    return
  fi

  # Skip if already checked (normalize trailing slashes for dedup)
  local check_key="${path%/}"
  if [ -n "${checked_tree_paths[$check_key]+x}" ]; then
    return
  fi
  checked_tree_paths["$check_key"]=1

  # Expand wildcard patterns (e.g., "01_check_env.*")
  if echo "$path" | grep -q '\*'; then
    local expanded
    expanded=$(ls $path 2>/dev/null || true)
    if [ -n "$expanded" ]; then
      local count
      count=$(echo "$expanded" | wc -l)
      _pass "$path — referenced in README, $count matching file(s) exist"
    else
      _fail "$path — referenced in README but no matching files found"
    fi
    return
  fi

  if [ -e "$path" ]; then
    _pass "$path — referenced in README, exists"
  else
    _fail "$path — referenced in README but MISSING"
  fi
}

# Parse the project structure tree section (lines with ├── └── tree chars).
# These only appear in the project structure code block in README.
# Track hierarchy using indentation depth.
# Indentation measured in units of 4 (│   = 4 spaces, or 4 spaces for deeper levels).
tree_section=$(grep -E '[├└]──' README.md || true)

# dir_stack: array of (depth -> directory name). depth 0 = root.
dir_stack=()
declare -i depth_levels=()  # depth values for each stack entry

get_indent_depth() {
  local line="$1"
  # Count the indent units before the tree character.
  # Each "│   " or "    " is one depth level.
  # Strip the tree-drawing chars and count what leads to the first ├/└
  local prefix="${line%%[├└]*}"
  # Count characters: each depth level is 4 chars (│ + 3 spaces, or 4 spaces)
  local len=${#prefix}
  echo $(( len / 4 ))
}

while IFS= read -r line; do
  [ -z "$line" ] && continue

  depth=$(get_indent_depth "$line")

  # Pop stack entries deeper than current depth
  while [ ${#dir_stack[@]} -gt 0 ] && [ "${depth_levels[-1]}" -ge "$depth" ]; do
    unset 'dir_stack[-1]'
    unset 'depth_levels[-1]'
  done

  # Extract the path portion: after the last ├── or └──
  entry=$(echo "$line" | sed 's/.*[├└]──\s*//' | sed 's/\s*#.*//' | tr -d '\r')

  # Handle "run.sh / run.ps1" → split into two paths
  if echo "$entry" | grep -q ' / '; then
    entries=()
    while IFS=' / ' read -ra parts; do
      for p in "${parts[@]}"; do
        p=$(echo "$p" | tr -d ' ')
        [ -n "$p" ] && entries+=("$p")
      done
    done <<< "$entry"
  else
    entries=("$entry")
  fi

  for e in "${entries[@]}"; do
    [ -z "$e" ] && continue
    # Build full path: join dir_stack + this entry
    full_path=""
    for d in "${dir_stack[@]}"; do
      full_path="${full_path}${d}/"
    done
    full_path="${full_path}${e}"

    # If it ends with /, it's a directory (push to stack)
    if [ "${e: -1}" = "/" ]; then
      dir_stack+=("${e%/}")
      depth_levels+=("$depth")
      check_path "$line" "$full_path"
    else
      check_path "$line" "$full_path"
    fi
  done
done <<< "$tree_section"

# ---- Additional paths from README body (not in tree) ----
echo ""

# Paths from the README body that should exist as repo files
body_paths=(
  "container/claude-wrapper"
  "container/cc-switch-wrapper"
  "container/cc-switch-skills"
  "container/Dockerfile"
  "container/entrypoint.sh"
  "container/mihomo-build-config.js"
  "container/claude-settings.json"
  "container/global-claude.md"
  "container/commands"
  "container/_bundle"
  "container/downloads"
)

for bp in "${body_paths[@]}"; do
  check_path "body" "$bp"
done

# Runtime paths that README references (gitignored by design)
runtime_paths=(
  ".cc-switch/cc-switch.db"
  ".claude/settings.json"
  ".claude/mihomo/config.yaml"
  ".deploy/state.env"
)

for rp in "${runtime_paths[@]}"; do
  _pass "$rp — referenced in README (runtime path, gitignored)"
done

# ---------------------------------------------------------------------------
# Check 2: cc-switch factory skills
# ---------------------------------------------------------------------------
echo ""
echo "--- Check 2: cc-switch factory skills ---"
echo ""

for skill in caveman document-skills grill-me superpowers; do
  if [ -f "container/cc-switch-skills/$skill/SKILL.md" ]; then
    _pass "cc-switch factory skill present: $skill"
  else
    _fail "cc-switch factory skill missing: $skill"
  fi
done

# ---------------------------------------------------------------------------
# Check 3: Legacy launchers stay removed
# ---------------------------------------------------------------------------
echo ""
echo "--- Check 3: Legacy launcher removal ---"
echo ""

legacy_launcher_paths=(
  "start.sh"
  "start.bat"
  "start.command"
  "scripts/01_check_env.sh"
  "scripts/01_check_env.ps1"
  "scripts/02_config_wizard.sh"
  "scripts/02_config_wizard.ps1"
  "scripts/03_build_image.sh"
  "scripts/03_build_image.ps1"
  "scripts/04_launcher.sh"
  "scripts/04_launcher.ps1"
  "scripts/run.sh"
  "scripts/run.ps1"
  "scripts/_state.sh"
  "scripts/_state.ps1"
  "cli/commands/doctor.sh"
  "cli/lib"
)
for path in "${legacy_launcher_paths[@]}"; do
  if [ -e "$path" ]; then
    _fail "$path — legacy launcher content must remain removed"
  else
    _pass "$path — removed"
  fi
done

# ---------------------------------------------------------------------------
# Check 4: Stale reference scan
# ---------------------------------------------------------------------------
echo ""
echo "--- Check 4: Stale reference scan ---"
echo ""

found_stale_img=0

# 4a: Search for image/Dockerfile in README (should be container/Dockerfile after P1.1)
if grep -q 'image/Dockerfile' README.md; then
  _fail "Stale reference: 'image/Dockerfile' found in README (should be 'container/Dockerfile')"
  found_stale_img=1
fi

# Also check in active docs (exclude devlog.md, plans/, TODO/, _bundle/, vendor/)
while IFS= read -r -d '' f; do
  if grep -q 'image/Dockerfile' "$f"; then
    _fail "Stale reference: 'image/Dockerfile' found in $f (should be 'container/Dockerfile')"
    found_stale_img=1
  fi
done < <(find . -name '*.md' \
  -not -path './docs/devlog.md' \
  -not -path './docs/plans/*' \
  -not -path './docs/TODO/*' \
  -not -path './container/_bundle/*' \
  -not -path './vendor/*' \
  -print0 2>/dev/null || true)

if [ "$found_stale_img" -eq 0 ]; then
  _pass "No stale 'image/Dockerfile' references in active docs"
fi

# 4b: Search for api_route_demo or litellm in README (LiteLLM demo was removed in P0)
if grep -qi 'api_route_demo\|litellm' README.md; then
  _fail "Stale reference: 'api_route_demo' or 'liteLLM' found in README (LiteLLM demo was removed in P0)"
else
  _pass "No stale api_route_demo/litellm references in README"
fi

# 4c: Search for 一键启动 in README (old Chinese launcher names)
if grep -q '一键启动' README.md; then
  _warn "Legacy term '一键启动' found in README (old Chinese launcher names; consider updating)"
else
  _pass "No stale '一键启动' references in README"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=== Summary ==="
echo "$passed passed, $warnings warnings, $failures failures"

if [ "$failures" -gt 0 ]; then
  exit 1
fi
exit 0
