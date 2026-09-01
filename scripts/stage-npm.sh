#!/usr/bin/env bash
# stage-npm.sh — 预下载 npm 包（claude-code / codex + linux 平台伴生包）到 container/downloads/
#
# 2.1.9 T8c/T8e（D-9）：大陆网络下 npmmirror/GitHub 抖动会让 `aisc build`
# 的 npm 安装段或 yazi 下载段失败。本脚本在有好网络时把安装包预先落到
# container/downloads/，Dockerfile 检测到预置包后走离线安装路径，构建零外网。
#
# 关键点：claude-code / codex 的原生二进制在平台伴生包里（主包是纯 JS，
# ~27KB）——离线安装必须同时预置 linux-x64/arm64 伴生包，版本钉在主包
# optionalDependencies 声明上（本脚本从下载的主包 tgz 里解析，不猜）。
#
# 用法（在仓库根目录，需 python3）：
#   bash scripts/stage-npm.sh                # claude-code + codex（npmmirror）
#   bash scripts/stage-npm.sh --yazi         # 顺带 yazi（GitHub，走 ghproxy 链）
#   bash scripts/stage-npm.sh --registry https://registry.npmjs.org/
#
# 产物命名（Dockerfile 按前缀 glob 识别，主包 glob 用 [0-9]* 防误配伴生包）：
#   container/downloads/claude-code-<version>.tgz            主包（纯 JS）
#   container/downloads/claude-code-linux-<a>-<version>.tgz  伴生包（原生二进制）
#   container/downloads/codex-<version>.tgz / codex-linux-<a>-<version>.tgz
#   container/downloads/yazi-<arch>-<version>.zip           （--yazi）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DL="$ROOT/container/downloads"
REGISTRY="https://registry.npmmirror.com"
WANT_YAZI=0
YAZI_VERSION="25.2.26"
ALL_ARCHES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --yazi) WANT_YAZI=1 ;;
    --all-arches) ALL_ARCHES=1 ;;
    --registry) REGISTRY="${2:?--registry 需要值}"; shift ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
  shift
done
mkdir -p "$DL"

if [ "$ALL_ARCHES" = "1" ]; then ARCHES="x64 arm64"; else
  case "$(uname -m 2>/dev/null || echo x86_64)" in
    x86_64|amd64) ARCHES="x64" ;;
    aarch64|arm64) ARCHES="arm64" ;;
    *) ARCHES="x64" ;;
  esac
fi

# Windows 上 python3 可能是 Microsoft Store 桩（吞 stdin、零输出——本次实测
# "curl: Failed writing body"）。探测能真正执行的解释器。
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && [ "$("$cand" -c 'print(1)' 2>/dev/null)" = "1" ]; then
    PY="$cand"; break
  fi
done
[ -n "$PY" ] || { echo "❌ 需要 python3（解析 npm 包元数据用）"; exit 1; }

# <scoped-name> -> tarball basename（作用域包的 tarball 文件名不带 scope）
pkg_basename() { basename "$1"; }

# 从已下载的主包 tgz 解析指定架构伴生包的 {真实包名, 版本}。
# codex 用 npm alias（"npm:@openai/codex@0.152.0-linux-x64"——平台包名不存在
# 于 registry，真身是同包的平台后缀版本）；claude-code 直接钉普通版本。
parse_pkg_meta() {
  local tgz="$1" comp_name="$2"
  tar -xzOf "$tgz" package/package.json | PYTHONIOENCODING=utf-8 "$PY" -c "
import json, sys
d = json.load(sys.stdin)
pv = (d.get('optionalDependencies') or {}).get('$comp_name', '')
if not pv:
    print('\t')
else:
    spec = pv[4:] if pv.startswith('npm:') else f'$comp_name@{pv}'
    real, _, ver = spec.rpartition('@')
    print(f'{real}\t{ver}')
"
}

fetch_one() {
  # fetch_one <pkg> <out-file> <version>
  local pkg="$1" out="$2" ver="$3" base
  base="$(pkg_basename "$pkg")"
  echo "⬇️  ${pkg}@${ver} -> $(basename "$out")"
  curl -fSL --retry 3 --retry-delay 2 "$REGISTRY/$pkg/-/$base-$ver.tgz" -o "$out"
}

stage_family() {
  # stage_family <pkg> <main-prefix> <companion-dep-prefix>
  #   例：stage_family @anthropic-ai/claude-code claude-code @anthropic-ai/claude-code-linux
  local pkg="$1" main_prefix="$2" comp_prefix="$3"
  local ver comp_pkg comp_ver meta tmp a f keep
  ver="$(curl -fsSL --retry 5 --retry-delay 3 --retry-all-errors "$REGISTRY/$pkg/latest" | PYTHONIOENCODING=utf-8 "$PY" -c 'import json,sys; print(json.load(sys.stdin)["version"])')"
  [ -n "$ver" ] || { echo "❌ 无法解析 $pkg 最新版本（$REGISTRY）"; exit 1; }
  # 已是最新且伴生包齐 → 跳过（重跑不重拉 ~100MB 级文件）
  if [ -f "$DL/$main_prefix-$ver.tgz" ]; then
    local skip=1 comp
    for comp in $ARCHES; do
      comp="$(/usr/bin/ls "$DL"/$main_prefix-linux-${comp}-*.tgz 2>/dev/null | head -1 || true)"
      [ -n "$comp" ] || skip=0
    done
    if [ "$skip" = "1" ]; then echo "✓ $main_prefix@$ver 预置已是最新，跳过"; return 0; fi
  fi
  tmp="$DL/.stage-$main_prefix.tgz"
  fetch_one "$pkg" "$tmp" "$ver"
  keep="$DL/$main_prefix-$ver.tgz"
  for a in $ARCHES; do
    meta="$(parse_pkg_meta "$tmp" "${comp_prefix}-${a}")"
    comp_pkg="${meta%%$'\t'*}"; comp_ver="${meta##*$'\t'}"
    if [ -z "$comp_pkg" ] || [ -z "$comp_ver" ]; then
      echo "❌ $pkg 未声明 ${comp_prefix}-${a} 伴生包——离线路径无法满足，中止（请反馈）"; exit 1
    fi
    fetch_one "$comp_pkg" "$DL/$main_prefix-linux-${a}-${comp_ver}.tgz" "$comp_ver"
    keep="$keep $DL/$main_prefix-linux-${a}-${comp_ver}.tgz"
  done
  mv "$tmp" "$DL/$main_prefix-$ver.tgz"
  # 清掉本家族旧版本/未请求架构的预置（Dockerfile 只取 glob 第一个）
  for f in "$DL"/$main_prefix-*.tgz; do
    case " $keep " in *" $f "*) ;; *) rm -f "$f" ;; esac
  done
}

stage_family "@anthropic-ai/claude-code" "claude-code" "@anthropic-ai/claude-code-linux"
stage_family "@openai/codex" "codex" "@openai/codex-linux"

if [ "$WANT_YAZI" = "1" ]; then
  arch="$(uname -m 2>/dev/null || echo x86_64)"
  case "$arch" in
    x86_64|amd64) yazi_arch="x86_64-unknown-linux-musl" ;;
    aarch64|arm64) yazi_arch="aarch64-unknown-linux-musl" ;;
    *) echo "⚠️  未知架构 $arch，跳过 yazi"; exit 0 ;;
  esac
  zip="$DL/yazi-${yazi_arch}-v${YAZI_VERSION}.zip"
  base="https://github.com/sxyazi/yazi/releases/download/v${YAZI_VERSION}/yazi-${yazi_arch}.zip"
  ok=0
  for m in "https://ghfast.top/" "https://gh-proxy.com/" "https://github.moeyy.xyz/" ""; do
    echo "⬇️  yazi try: ${m}${base}"
    if curl -fSL --http1.1 --retry 2 --retry-all-errors --connect-timeout 8 \
        --max-time 120 "${m}${base}" -o "$zip"; then ok=1; break; fi
  done
  [ "$ok" = "1" ] || { echo "❌ yazi 下载失败"; exit 1; }
fi

echo "✅ 预置完成："
ls -la "$DL" | grep -E "claude-code|codex|yazi" || true
