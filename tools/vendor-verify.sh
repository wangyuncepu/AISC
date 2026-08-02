#!/usr/bin/env bash
# vendor-verify.sh — verify Git-tracked vendor inputs via canonical checksums
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CHECKSUM_FILE="vendor/checksums.txt"

if [ ! -f "$CHECKSUM_FILE" ]; then
  echo "ERROR: ${CHECKSUM_FILE} not found. Run tools/vendor-refresh.sh first." >&2
  exit 2
fi

echo "=== Vendor Integrity Check ==="
echo "Checking: ${CHECKSUM_FILE}"
echo ""

verified=0
mismatch=0
missing=0
malformed=0

while IFS= read -r line || [ -n "$line" ]; do
  [ -z "$line" ] && continue
  [[ "$line" == \#* ]] && continue

  expected=${line:0:64}
  separator=${line:64:2}
  tracked_path=${line:66}
  if [[ ! "$expected" =~ ^[0-9a-fA-F]{64}$ ]] \
      || [ "$separator" != "  " ] \
      || [ -z "$tracked_path" ]; then
    malformed=$((malformed + 1))
    echo "  FAIL  malformed checksum line"
    continue
  fi

  if [ ! -f "$tracked_path" ]; then
    missing=$((missing + 1))
    echo "  MISS  $tracked_path"
    continue
  fi

  # Match vendor-refresh: stat-only checkout differences use index bytes,
  # while real staged or unstaged edits use the working-tree file.
  if git ls-files --error-unmatch -- "$tracked_path" >/dev/null 2>&1 \
      && git diff --quiet -- "$tracked_path" 2>/dev/null; then
    actual=$(git show ":$tracked_path" | sha256sum | cut -d ' ' -f 1)
  else
    actual=$(sha256sum "$tracked_path" | cut -d ' ' -f 1)
  fi

  expected_lower=$(printf '%s' "$expected" | tr '[:upper:]' '[:lower:]')
  if [ "$actual" = "$expected_lower" ]; then
    verified=$((verified + 1))
    echo "  PASS  $tracked_path"
  else
    mismatch=$((mismatch + 1))
    echo "  FAIL  $tracked_path  [checksum mismatch]"
  fi
done < "$CHECKSUM_FILE"

listed=$((verified + mismatch + missing))
tracked=$(git ls-files -- container | wc -l)
if [ "$listed" -ne "$tracked" ]; then
  malformed=$((malformed + 1))
  echo "  FAIL  checksum coverage: ${listed} entries for ${tracked} tracked files"
fi

echo ""
echo "=== Summary ==="
echo "${verified} verified, ${missing} missing, ${mismatch} checksum mismatch, ${malformed} malformed"

if [ "$missing" -eq 0 ] && [ "$mismatch" -eq 0 ] && [ "$malformed" -eq 0 ]; then
  echo "All ${verified} checksums passed."
  exit 0
fi

echo "Integrity check failed."
exit 1
