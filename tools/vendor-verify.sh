#!/usr/bin/env bash
# vendor-verify.sh — verify vendor integrity via checksums
#
# Runs sha256sum -c against vendor/checksums.txt from repo root.
# Reports per-file PASS/FAIL/MISS and a summary with exit code.
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

# Force C locale so sha256sum outputs "OK" / "FAILED" in English
export LC_ALL=C

tmpout=$(mktemp)
tmperr=$(mktemp)
trap 'rm -f "$tmpout" "$tmperr"' EXIT

set +e
sha256sum -c "$CHECKSUM_FILE" >"$tmpout" 2>"$tmperr"
sha_exit=$?
set -e

# ── Parse stdout: OK / FAILED / FAILED open or read ────────────────
verified=0
mismatch=0
missing=0

while IFS= read -r line; do
  case "$line" in
    *": OK")
      verified=$((verified + 1))
      echo "  PASS  ${line%: OK}"
      ;;
    *": FAILED open or read")
      missing=$((missing + 1))
      echo "  MISS  ${line%: FAILED open or read}"
      ;;
    *": FAILED")
      mismatch=$((mismatch + 1))
      echo "  FAIL  ${line%: FAILED}  [checksum mismatch]"
      ;;
    *"WARNING:"*)
      # Skip summary lines from sha256sum
      ;;
    *)
      # Unexpected output — echo as info
      if [ -n "$line" ]; then
        echo "  INFO  ${line}"
      fi
      ;;
  esac
done < "$tmpout"

# ── Summary ────────────────────────────────────────────────────────
total=$((verified + mismatch + missing))
echo ""
echo "=== Summary ==="
echo "${verified} verified, ${missing} missing, ${mismatch} checksum mismatch"

if [ "$sha_exit" -eq 0 ] && [ "$missing" -eq 0 ] && [ "$mismatch" -eq 0 ]; then
  echo "All ${total} checksums passed."
  exit 0
else
  echo "Integrity check failed."
  exit 1
fi
