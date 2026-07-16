#!/usr/bin/env bash
# stage-mihomo.sh —— 构建前预下载 Mihomo 二进制 + geodata 到 image/downloads/
# 网络差/离线构建时用：Dockerfile 优先使用 image/downloads/ 本地副本，跳过联网下载。
# 一次性脚本，普通用户无需运行（默认 docker build 联网下载即可）。
#
# 产物（纳入 git，使构建自包含、国内网络不访问 GitHub）：
#   image/downloads/mihomo-linux-<arch>-<ver>.gz   mihomo 二进制（gz）
#   image/downloads/geoip.metadb  geosite.dat  country.mmdb   geodata
set -euo pipefail

DST="$(cd "$(dirname "$0")/.." && pwd)/image/downloads"
mkdir -p "$DST"

VER="${MIHOMO_VERSION:-v1.19.27}"
# 镜像前缀（按实测稳定性排序）；可在 MIHOMO_GH_PROXY 环境变量指定单一前缀
if [ -n "${MIHOMO_GH_PROXY:-}" ]; then
  MIRRORS=("${MIHOMO_GH_PROXY}")
else
  MIRRORS=("https://ghfast.top/" "https://gh-proxy.com/" "https://github.moeyy.xyz/" "https://ghproxy.net/" "https://mirror.ghproxy.com/")
fi

# arch 映射（宿主 uname -m → mihomo asset 命名）
case "$(uname -m)" in
  x86_64|amd64)  ARCH=amd64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *) ARCH=amd64 ;;
esac

# dl URL —— 多镜像轮询 + --http1.1（绕开 curl/GitHub HTTP/2 流异常）+ 直连兜底
# 用法: dl_url "<完整 github url>" "<输出文件>"
dl_url() {
  local url="$1" out="$2"
  local ok=0
  for m in "${MIRRORS[@]}" ""; do
    local u="${m}${url}"
    echo "  try: $u"
    if curl -fSL --http1.1 --retry 2 --retry-delay 1 --retry-all-errors \
            --connect-timeout 8 --max-time 180 "$u" -o "$out" 2>/dev/null; then
      ok=1; break
    fi
  done
  [ "$ok" = "1" ] || { echo "  ❌ 失败: $url"; return 1; }
}

echo "⬇️  预下载 Mihomo ${VER} (${ARCH}) 到 downloads/"
mihomo_url="https://github.com/MetaCubeX/mihomo/releases/download/${VER}/mihomo-linux-${ARCH}-${VER}.gz"
dl_url "$mihomo_url" "$DST/mihomo-linux-${ARCH}-${VER}.gz"

echo "⬇️  预下载 geodata 到 downloads/"
for f in geoip.metadb geosite.dat country.mmdb; do
  dl_url "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/$f" "$DST/$f" || \
    echo "  ⚠️  $f 下载失败（mihomo 仍可启动，GEO 规则可能受限）"
done

echo "✅ 完成。image/downloads/ 内容："
ls -la "$DST"
echo ""
echo "现在可离线/弱网构建：docker build -f image/Dockerfile -t super-claude:latest .（或直接跑启动器）"
