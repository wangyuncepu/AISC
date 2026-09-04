#!/usr/bin/env bash
# T-F1a (D-10): stage the mutagen HOST-side binaries into downloads/host-bin/.
#
# Vendor policy (docs/plans/2.1.9-dev-plans/f1-f2-design.md §F1-1):
#   - v0.16.x ONLY — the last fully-MIT series. v0.17+ official binaries
#     bundle SSPL-licensed code; redistributing them in our installers is a
#     compliance gray zone we simply avoid.
#   - Host asset (never enters the container image) → gitignored cache +
#     CI downloads with the sha256 pins below (fail closed), unlike mihomo
#     which ships inside the image from the git-tracked downloads/.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="v0.16.4"
BASE="https://github.com/mutagen-io/mutagen/releases/download/${VERSION}"
DEST="downloads/host-bin"

# sha256 pins (fail closed — a mismatch aborts the stage)
declare -A SHA=(
  [windows_amd64]="0dd0782f7eae0b3b6b2d4ce0ebdf742ca2b2e46a77eb15c0ed0f6531074fa1b9"
  [linux_amd64]="7bb029ff21e5fab0bc2e094af5a93903a14ec0105d6247de441c521e431801e0"
  [darwin_arm64]="9d11b6e3ab096a7ddf37dfbf79a2e0c17644117938e4d9fcf84dce12b7322d4f"
  [darwin_amd64]="7bf6b4e41aa6238a560a67634e52085dda9ac3af610526baccf567ccdcd82d9b"
)

mkdir -p "${DEST}"
extract() { # always (re)extract: a cached archive must still land its binary
  local plat="$1" out="$2"
  local dir="${DEST}/${plat}"
  mkdir -p "${dir}"
  tar -xzf "${out}" -C "${dir}"
  echo "✅ ${plat}: $(ls "${dir}" | tr '\n' ' ')"
}
rc=0
for plat in windows_amd64 linux_amd64 darwin_arm64 darwin_amd64; do
  asset="mutagen_${plat}_${VERSION}.tar.gz"
  out="${DEST}/${asset}"
  if [ -f "${out}" ] && echo "${SHA[${plat}]}  ${out}" | sha256sum -c - >/dev/null 2>&1; then
    echo "📦 已缓存: ${out}"
    extract "${plat}" "${out}"
    continue
  fi
  ok=0
  for m in ${GH_PROXY:-} https://ghfast.top/ https://gh-proxy.com/ ""; do
    if curl -fSL --http1.1 --retry 2 --retry-delay 1 --retry-all-errors \
         --connect-timeout 10 --max-time 180 "${m}${BASE}/${asset}" -o "${out}"; then
      ok=1; break
    fi
  done
  [ "$ok" = "1" ] || { echo "❌ 下载失败: ${asset}"; rc=1; continue; }
  if ! echo "${SHA[${plat}]}  ${out}" | sha256sum -c -; then
    echo "❌ sha256 不匹配: ${asset}"; rm -f "${out}"; rc=1; continue
  fi
  extract "${plat}" "${out}"
done
exit $rc
