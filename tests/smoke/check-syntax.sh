#!/usr/bin/env bash
# Minimal syntax smoke test — validates .sh, .py, .js, .json files
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

total=0
passed=0
failed=0

fail() { echo "  FAIL: $1"; failed=$((failed + 1)); }
ok()   { echo "  PASS: $1"; passed=$((passed + 1)); }

echo "=== Syntax Smoke Test ==="
echo ""

# ---- Shell files (.sh) ----
echo "[sh] Checking shell syntax..."
sh_files=()
# Directories to scan
for dir in cli image scripts tools; do
  if [ -d "$dir" ]; then
    while IFS= read -r -d '' f; do
      sh_files+=("$f")
    done < <(find "$dir" -name '*.sh' -print0 2>/dev/null || true)
  fi
done
# Root-level scripts
for root_file in start.sh start.command; do
  if [ -f "$root_file" ] && [[ "$root_file" == *.sh ]]; then
    sh_files+=("$root_file")
  elif [ -f "$root_file" ]; then
    # start.command is treated as bash
    sh_files+=("$root_file")
  fi
done

for file in "${sh_files[@]}"; do
  total=$((total + 1))
  if bash -n "$file" 2>/dev/null; then
    ok "$file"
  else
    fail "$file"
  fi
done

# ---- Python files (.py) under ai_brief/ ----
echo ""
echo "[py] Checking python syntax under ai_brief/..."
if [ -d ai_brief ]; then
  while IFS= read -r -d '' f; do
    total=$((total + 1))
    if python3 -m py_compile "$f" 2>/dev/null; then
      ok "$f"
    else
      fail "$f"
    fi
  done < <(find ai_brief -name '*.py' -print0 2>/dev/null || true)
fi

# ---- JavaScript files (.js) under image/ (excluding _bundle/, downloads/, node_modules/) ----
echo ""
echo "[js] Checking JS syntax under image/..."
if [ -d image ]; then
  while IFS= read -r -d '' f; do
    total=$((total + 1))
    if node --check "$f" 2>/dev/null; then
      ok "$f"
    else
      fail "$f"
    fi
  done < <(find image -name '*.js' \
    -not -path '*/_bundle/*' \
    -not -path '*/downloads/*' \
    -not -path '*/node_modules/*' \
    -print0 2>/dev/null || true)
fi

# ---- JSON files (.json) under image/ (excluding _bundle/, downloads/) ----
echo ""
echo "[json] Checking JSON validity under image/..."
if [ -d image ]; then
  while IFS= read -r -d '' f; do
    total=$((total + 1))
    if python3 -m json.tool "$f" > /dev/null 2>&1; then
      ok "$f"
    else
      fail "$f"
    fi
  done < <(find image -name '*.json' \
    -not -path '*/_bundle/*' \
    -not -path '*/downloads/*' \
    -print0 2>/dev/null || true)
fi

# ---- Summary ----
echo ""
echo "=== Summary ==="
echo "$total files checked, $passed passed, $failed failed"

if [ "$failed" -gt 0 ]; then
  exit 1
fi
exit 0
