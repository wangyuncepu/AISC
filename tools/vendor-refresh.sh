#!/usr/bin/env bash
# vendor-refresh.sh — deterministically refresh vendored artifacts
#
# Steps:
#   1. Check that required source directories exist (warn if not)
#   2. Report on container/_bundle/ (manually managed; suggest tools/stage-skills.sh)
#   3. Verify container/downloads/ against vendor/manifest.json
#   4. Regenerate vendor/checksums.txt via find+sha256sum
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DRY_RUN=false

usage() {
  cat <<'EOF'
Usage: vendor-refresh.sh [OPTIONS]

Deterministically refresh vendored artifacts and regenerate checksums.

Options:
  --dry-run     Print what would be done without making changes
  -h, --help    Show this help message

Steps:
  1. Verify source directories referenced in vendor/manifest.json exist
  2. Report on container/_bundle/ contents (manually managed)
  3. Verify container/downloads/ files against vendor/manifest.json
  4. Regenerate vendor/checksums.txt from all files under container/
EOF
  exit 0
}

# ── Argument parsing ──────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    -h|--help) usage ;;
    *) echo "ERROR: Unknown option: $arg" >&2; usage ;;
  esac
done

# ── Source version info (optional) ─────────────────────────────────
if [ -f "config/versions.env" ]; then
  # shellcheck source=/dev/null
  source config/versions.env
  echo "📋 Loaded config/versions.env (AISC_VERSION=${AISC_VERSION:-unset})"
fi

echo ""
echo "=== Vendor Refresh ==="
$DRY_RUN && echo "[DRY RUN MODE — no changes will be made]"
echo ""

# ── Step 1: Check source directories ──────────────────────────────
echo "--- Step 1: Check source directories ---"

SRC_DIRS=(
  "container"
  "container/downloads"
  "container/_bundle"
  "container/_bundle/plugins/cache"
  "container/_bundle/plugins/marketplaces"
  "container/_bundle/skills"
)

for dir in "${SRC_DIRS[@]}"; do
  if [ -d "$dir" ]; then
    echo "  ✓ $dir"
  else
    echo "  ⚠ WARNING: $dir does not exist"
  fi
done

# Report manifest source references
MANIFEST="vendor/manifest.json"
if [ -f "$MANIFEST" ]; then
  echo ""
  echo "  Source references in vendor/manifest.json:"
  python3 -c "
import json
with open('$MANIFEST') as f:
    m = json.load(f)
for c in m.get('components', []):
    print(f\"    {c['name']:28s} → {c['source']}\")
" 2>/dev/null || echo "  (could not parse manifest.json)"
else
  echo "  ⚠ WARNING: vendor/manifest.json not found"
fi
echo ""

# ── Step 2: _bundle inspection ────────────────────────────────────
echo "--- Step 2: container/_bundle/ (manually managed plugins/skills) ---"

if [ -d "container/_bundle" ]; then
  echo "  Directory structure:"
  find container/_bundle -maxdepth 3 -type d 2>/dev/null | sort | while IFS= read -r d; do
    depth=$(echo "$d" | tr -cd '/' | wc -c)
    indent=$(printf '%*s' $((depth * 2)) '')
    echo "  ${indent}${d}"
  done

  FILE_COUNT=$(find container/_bundle -type f 2>/dev/null | wc -l)
  echo ""
  echo "  Total files: ${FILE_COUNT}"

  # Show which top-level components exist
  echo "  Top-level components:"
  for comp in container/_bundle/plugins/cache/*/; do
    [ -d "$comp" ] || continue
    name=$(basename "$comp")
    subcount=$(find "$comp" -type f 2>/dev/null | wc -l)
    echo "    plugins/cache/${name}  (${subcount} files)"
  done
  for comp in container/_bundle/plugins/marketplaces/*/; do
    [ -d "$comp" ] || continue
    name=$(basename "$comp")
    subcount=$(find "$comp" -type f 2>/dev/null | wc -l)
    echo "    plugins/marketplaces/${name}  (${subcount} files)"
  done
  if [ -d "container/_bundle/skills" ]; then
    for comp in container/_bundle/skills/*/; do
      [ -d "$comp" ] || continue
      name=$(basename "$comp")
      subcount=$(find "$comp" -type f 2>/dev/null | wc -l)
      echo "    skills/${name}  (${subcount} files)"
    done
  fi

  echo ""
  echo "  ⟳ These are manually managed. To rebuild from source:"
  echo "    tools/stage-skills.sh"
else
  echo "  ⚠ WARNING: container/_bundle/ does not exist."
  echo "  Run 'tools/stage-skills.sh' to stage skills/plugins."
fi
echo ""

# ── Step 3: Verify downloads against manifest ─────────────────────
echo "--- Step 3: Verify container/downloads/ against vendor/manifest.json ---"

missing_count=0
verified_count=0

if [ -f "$MANIFEST" ]; then
  # Extract download file paths from manifest
  dl_files=$(python3 -c "
import json
with open('$MANIFEST') as f:
    m = json.load(f)
for c in m.get('components', []):
    for fp in c.get('files', []):
        if fp.startswith('container/downloads/'):
            print(fp)
" 2>/dev/null)

  if [ -n "$dl_files" ]; then
    while IFS= read -r fpath; do
      [ -z "$fpath" ] && continue
      if [ -f "$fpath" ]; then
        size=$(stat -c%s "$fpath" 2>/dev/null || stat -f%z "$fpath" 2>/dev/null || echo "?")
        echo "  ✓ $fpath ($size bytes)"
        verified_count=$((verified_count + 1))
      else
        echo "  ✗ MISSING: $fpath"
        missing_count=$((missing_count + 1))
      fi
    done <<< "$dl_files"
  fi

  # Also check for unexpected files in downloads/
  if [ -d "container/downloads" ]; then
    while IFS= read -r f; do
      fname=$(basename "$f")
      case "$fname" in
        .gitkeep) continue ;;  # skip placeholder
      esac
      # Check if this file is in the manifest
      in_manifest=$(python3 -c "
import json
with open('$MANIFEST') as f:
    m = json.load(f)
known = set()
for c in m.get('components', []):
    for fp in c.get('files', []):
        known.add(fp)
print('yes' if '$f' in known else 'no')
" 2>/dev/null)
      if [ "$in_manifest" = "no" ]; then
        echo "  ⓘ Unlisted file in downloads/: $f"
      fi
    done < <(find container/downloads -type f 2>/dev/null)
  fi
fi

echo ""
echo "  Downloads: ${verified_count} verified, ${missing_count} missing"
echo ""

# ── Step 4: Regenerate checksums ──────────────────────────────────
echo "--- Step 4: Regenerate vendor/checksums.txt ---"

CHECKSUM_FILE="vendor/checksums.txt"

if $DRY_RUN; then
  file_count=$(find container -type f 2>/dev/null | wc -l)
  echo "  [DRY RUN] Would compute sha256 for ${file_count} files under container/"
  echo "  [DRY RUN] Would write to ${CHECKSUM_FILE}"
  echo "  Pattern: find container -type f -print0 | sort -z | xargs -0 sha256sum > ${CHECKSUM_FILE}"
else
  # Ensure vendor directory exists
  mkdir -p vendor

  echo "  Computing sha256 checksums for all files under container/..."
  find container -type f -print0 2>/dev/null | sort -z | xargs -0 sha256sum > "${CHECKSUM_FILE}.tmp"

  mv "${CHECKSUM_FILE}.tmp" "$CHECKSUM_FILE"
  line_count=$(wc -l < "$CHECKSUM_FILE")
  echo "  ✓ Done. ${line_count} files checksummed → ${CHECKSUM_FILE}"
fi
echo ""

echo "=== Refresh Complete ==="
