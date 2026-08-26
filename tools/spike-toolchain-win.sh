#!/usr/bin/env bash
# runtime-lifecycle-ux Stage 3a — Windows toolchain-storage spike (03 §3a.1/2).
# Compares NTFS bind mount vs Docker named volume for the persistent
# project toolchain: npm -g install of a frozen local tarball (typescript
# 7.0.2, 416 files, bin entry) — symlink creation, exec, cross-container
# reuse, cold (fresh store) x3 and hot (populated store) x5 timings.
# Usage: bash tools/spike-toolchain-win.sh   (Docker must be running)
set -u

SPIKE_W="$(cygpath -m "$LOCALAPPDATA")/AISC/spike"
PKG_DIR="$SPIKE_W/pkg"
BIND_DIR="$SPIKE_W/bind"
VOL=aisc-spike-toolchain
IMG=node:20-slim

INNER='set -e; export NPM_CONFIG_PREFIX=/opt/aisc/toolchain/npm-global; export PATH=$NPM_CONFIG_PREFIX/bin:$PATH; cd /pkg; s=$(date +%s%3N); npm install -g --no-update-notifier --no-fund --no-audit ./typescript.tgz >/dev/null 2>&1; e=$(date +%s%3N); echo -n "install_ms=$((e-s)) "; ls -l $NPM_CONFIG_PREFIX/bin | grep -q tsc && echo -n "symlink=ok " || { echo "symlink=FAIL"; exit 1; }; tsc --version >/dev/null 2>&1 && echo "exec=ok" || { echo "exec=FAIL"; exit 1; }'

run_bind() { docker run --rm -v "$PKG_DIR:/pkg:ro" -v "$BIND_DIR:/opt/aisc/toolchain" "$IMG" bash -lc "$INNER"; }
run_vol()  { docker run --rm -v "$PKG_DIR:/pkg:ro" -v "$VOL:/opt/aisc/toolchain"   "$IMG" bash -lc "$INNER"; }

fresh_bind() { rm -rf "$BIND_DIR"/* "$BIND_DIR"/.[!.]* 2>/dev/null; }
fresh_vol()  { docker volume rm -q "$VOL" >/dev/null 2>&1; docker volume create "$VOL" >/dev/null; }

echo "== backend A: host_bind ($BIND_DIR) =="
for i in 1 2 3; do fresh_bind; echo -n "cold$i  "; run_bind; done
for i in 1 2 3 4 5; do echo -n "hot$i   "; run_bind; done

echo "== backend B: docker_volume ($VOL) =="
for i in 1 2 3; do fresh_vol; echo -n "cold$i  "; run_vol; done
for i in 1 2 3 4 5; do echo -n "hot$i   "; run_vol; done

echo "== cross-container reuse (store survives the container) =="
fresh_vol >/dev/null; run_vol >/dev/null
docker run --rm -v "$VOL:/opt/aisc/toolchain" "$IMG" bash -lc 'export NPM_CONFIG_PREFIX=/opt/aisc/toolchain/npm-global; $NPM_CONFIG_PREFIX/bin/tsc --version' && echo "volume_reuse=ok"
docker run --rm -v "$BIND_DIR:/opt/aisc/toolchain" "$IMG" bash -lc 'export NPM_CONFIG_PREFIX=/opt/aisc/toolchain/npm-global; $NPM_CONFIG_PREFIX/bin/tsc --version' && echo "bind_reuse=ok"

echo "== file counts =="
docker run --rm -v "$VOL:/t" "$IMG" bash -lc 'echo "volume_files=$(find /t -type f | wc -l)"'
echo "bind_files=$(find "$BIND_DIR" -type f 2>/dev/null | wc -l)"
