# Super Claude · 容器内建 Mihomo TUN 透明代理 — 实施方案 (v1.2.3)

> 目标：宿主机零代理，容器内 Mihomo TUN 接管全部出站，Claude Code 直连 Anthropic API。用户无需懂技术，TUI 引导完成。

## 设计决策（已与用户确认）

- **D1 · TUN 补丁在容器内权威注入**：宿主脚本只负责下载/拷贝**原始**用户配置到 `.claude/mihomo/config.yaml`（不打补丁）；`entrypoint.sh` 用 Node 在**可写副本**上做 strip+append，再以该副本启动 mihomo。落盘文件保留用户原始配置，运行时强制含 TUN。理由：容器内 Node+工具必有、每次启动重打、手动丢配置也能兜底；宿主环境不可控（Windows BAT 无 Node/awk）。
- **D2 · docker run 特权按需追加**：仅当 TUI 选“需要代理”时追加 `--cap-add=NET_ADMIN --device /dev/net/tun` 与配置只读挂载；不配代理则零特权、零 tun 设备依赖，避免宿主缺 `/dev/net/tun` 时启动失败。
- **D3 · Mihomo 版本 pin + geodata 预置**：`MIHOMO_VERSION=v1.19.27`（build-arg 可覆盖，asset `mihomo-linux-<arch>-v1.19.27.gz`，已核验）；geodata（geoip.metadb/geosite.dat/country.mmdb）构建期预置进镜像，避免受限网络下 mihomo 运行时下载 geodata 失败导致起不来。
- **D4 · 跨平台对等**：`启动_AI工作站.sh`（Linux/macOS）与 `一键启动_AI工作站.bat`（Windows）同步实现 TUI；`启动_AI工作站.command` 透传 `.sh` 不改。

---

## 模块 1 · TUI 引导（启动器）

### 1a. `启动_AI工作站.sh`（bash）
在镜像构建/检测之后、`docker run` 拼接之前，新增 `configure_proxy()`：

```bash
configure_proxy() {
  PROXY_ENABLED=0
  MIHOMO_DIR="$SCRIPT_DIR/.claude/mihomo"
  local cfg="$MIHOMO_DIR/config.yaml"

  echo "🌐 代理网络配置（用于容器内访问 Anthropic API 等国际网络）"
  read -r -p "是否需要配置代理网络? [y/N]: " pc
  case "$pc" in y|Y) ;; *) echo "⏭️  跳过代理，容器直连网络。"; return 0 ;; esac

  echo "  1) 本地文件 — 输入本地 config.yaml 绝对路径"
  echo "  2) 网络链接 — 输入订阅链接 / 配置直链 URL"
  read -r -p "选择 [1/2，默认 2]: " mode
  mode="${mode:-2}"

  mkdir -p "$MIHOMO_DIR"
  if [ "$mode" = "1" ]; then
    read -r -p "本地 config.yaml 绝对路径: " src
    [ -f "$src" ] || { echo "❌ 文件不存在: $src"; return 1; }
    cp -f "$src" "$cfg"
  else
    read -r -p "配置 URL: " url
    [ -n "$url" ] || { echo "❌ URL 为空"; return 1; }
    echo "⬇️  下载配置..."
    curl -fsSL "$url" -o "$cfg" || { echo "❌ 下载失败"; return 1; }
  fi

  # 基本校验：非空且含 yaml 片段（订阅可能返回 base64 → 提示用户用转换后的 yaml）
  if [ ! -s "$cfg" ] || ! grep -q ':' "$cfg"; then
    echo "⚠️  配置内容异常（可能为 base64 订阅）。仅支持 yaml 直链，请用订阅转换后的 yaml。"
    rm -f "$cfg"; return 1
  fi
  echo "✅ 代理配置已就绪: $cfg"
  PROXY_ENABLED=1
}
```

`docker run` 拼接处改为条件追加：
```bash
RUN_ARGS=(-it --rm -e TERM=xterm-256color --name "$NAME" -v "$(pwd):/home/AISC/app")
if [ "$PROXY_ENABLED" = "1" ]; then
  RUN_ARGS+=(--cap-add=NET_ADMIN --device /dev/net/tun \
    -v "$SCRIPT_DIR/.claude/mihomo/config.yaml:/etc/mihomo/config.yaml:ro")
  echo "🛡️  已启用容器内 TUN 透明代理（NET_ADMIN + /dev/net/tun）"
fi
docker run "${RUN_ARGS[@]}" "$IMAGE"
```

### 1b. `一键启动_AI工作站.bat`（Windows）
- `:runcontainer` 前调用 `call :configure_proxy`。
- 本地：`copy /Y "%SRC%" "%CFG%"`（双引号绝对路径）。
- 网络：优先 `curl.exe -fsSL`（Win10+ 自带）；`errorlevel` 非零则回退 `powershell -Command "iwr -Uri ... -OutFile ..."`。
- 配置目录用脚本所在目录：`set MIHOMO_DIR=%~dp0.claude\mihomo`，挂载路径转 docker 正斜杠风格。
- `PROXY_ENABLED=1` 时在 `:runcontainer` 拼接：
  ```bat
  set RUN_ARGS=-it --rm -e TERM=xterm-256color --name %NAME% -v "%cd%:/home/AISC/app"
  if "%PROXY_ENABLED%"=="1" set RUN_ARGS=%RUN_ARGS% --cap-add=NET_ADMIN --device /dev/net/tun -v "%~dp0.claude\mihomo\config.yaml:/etc/mihomo/config.yaml:ro"
  docker run %RUN_ARGS% %IMAGE%
  ```

---

## 模块 2 · TUN 配置强制修补（容器内 Node，权威逻辑）

落点：`entrypoint.sh` 内 `ensure_tun_config()`。源文件 `/etc/mihomo/config.yaml`（ro 挂载，用户原始配置）→ 读文本 → strip 已有顶层 `tun:` 块 → 追加规范 `tun:` 块（+ 必要时补 `dns:`）→ 写可写副本 `/home/AISC/.mihomo/config.yaml`。

**算法（最稳妥，幂等，处理 CRLF/注释/已有块）：**
- 顶层 key = 行首非空白字符；遇 `^tun:` 进入 strip 模式；strip 模式下的缩进行（行首空白）跳过；遇下一个顶层 key 退出 strip。
- 注释行 `^\s*#`：原样保留，**不**改变 strip 状态（YAML 中注释不断块）。
- 读取时 `sub(/\r$/,"")` 去 CRLF，写入统一 `\n`。
- 同法处理 `dns:`：仅在用户配置**没有**顶层 `dns:` 块时，追加一个最小可用 `dns:` 块（TUN 的 `dns-hijack` 需要解析器，否则域名不解析 → claude 连不上 API）。**用户已有 `dns:` 则完全不碰。**
- 幂等：重复运行结果一致（先剥离再追加）。

**Node 实现（`node -e`，容器内 Node 必有，无外部依赖）：**

```js
const fs = require('fs');
const src = '/etc/mihomo/config.yaml';
const dstDir = '/home/AISC/.mihomo';
const dst = dstDir + '/config.yaml';
fs.mkdirSync(dstDir, { recursive: true });

let text = fs.readFileSync(src, 'utf8').replace(/\r\n?/g, '\n');
const lines = text.split('\n');

// 1) 通用顶层块剥离：返回不含指定顶层 key 块的文本
function stripTopBlock(lines, key) {
  const out = [];
  let inBlock = false;
  for (const raw of lines) {
    if (/^\s*#/.test(raw)) { if (!inBlock) out.push(raw); continue; } // 注释:块外才保留
    if (/^[^\s]/.test(raw)) {                  // 新顶层 key
      inBlock = new RegExp('^' + key + ':').test(raw);
      if (!inBlock) out.push(raw);
      continue;
    }
    if (!inBlock) out.push(raw);               // 缩进行:仅块外保留
  }
  return out.join('\n');
}

const TUN = [
  '# === AISC forced TUN (auto-patched) ===',
  'tun:',
  '  enable: true',
  '  stack: system',
  '  dns-hijack:',
  '    - any:53',
  '  auto-route: true',
  '  auto-detect-interface: true',
].join('\n');

const DNS = [
  '# === AISC fallback DNS (auto-patched, only if absent) ===',
  'dns:',
  '  enable: true',
  '  listen: 0.0.0.0:1053',
  '  enhanced-mode: fake-ip',
  '  nameserver:',
  '    - 223.5.5.5',
  '    - 119.29.29.29',
  '  fallback:',
  '    - 8.8.8.8',
  '    - 1.1.1.1',
].join('\n');

let patched = stripTopBlock(lines, 'tun');
patched = patched.replace(/\s+$/, '\n') + '\n' + TUN + '\n';
// 仅当无 dns: 顶层块时补
if (!/^dns:/m.test(patched)) patched += '\n' + DNS + '\n';

fs.writeFileSync(dst, patched, 'utf8');
console.log('✅ TUN 配置已注入: ' + dst);
```

> 注：`dns:` 块为**保证可用性**的推荐增强（用户 spec 仅列 `tun:`）。若你希望严格只注入 `tun:`、不碰 `dns:`，可在审阅时去掉 DNS 段——但实测无 `dns:` 时 TUN 劫持 53 端口易形成解析死循环。

---

## 模块 3 · Dockerfile + docker run

### Dockerfile 改动
1. **apt 工具**：首条 `apt-get install` 增加 `iptables iproute2 ca-certificates`（TUN `auto-route` 操纵 iptables；`ip` 来自 iproute2；https 需要 ca-certificates）。
2. **Mihomo 下载层**（root 阶段，`USER AISC` 之前）：
   ```dockerfile
   ARG MIHOMO_VERSION=v1.19.27
   # GitHub 代理前缀（USE_CN_MIRROR=1 时启用，可 --build-arg 覆盖）
   ARG GH_PROXY=https://mirror.ghproxy.com/
   RUN set -eux; \
       arch="$(dpkg --print-architecture)"; \
       case "$arch" in amd64) mih_arch=amd64;; arm64|aarch64) mih_arch=arm64;; *) mih_arch=amd64;; esac; \
       base="https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/mihomo-linux-${mih_arch}-${MIHOMO_VERSION}.gz"; \
       ok=0; \
       for u in "${GH_PROXY}${base}" "$base"; do \
         echo "⬇️  try: $u"; \
         if curl -fSL --retry 2 "$u" -o /tmp/mihomo.gz; then ok=1; break; fi; \
       done; [ "$ok" = "1" ] || { echo "❌ mihomo 下载失败"; exit 1; }; \
       gunzip -f /tmp/mihomo.gz; \
       mv /tmp/mihomo /usr/local/bin/mihomo; \
       chmod +x /usr/local/bin/mihomo; \
       /usr/local/bin/mihomo -v
   ```
   （代理前缀空串时 `${GH_PROXY}${base}` == `$base`，自然走直连。）
3. **geodata 预置**（同 root 阶段，下载到 AISC 运行时数据目录，最终 `chown` 交还）：
   ```dockerfile
   RUN set -eux; mkdir -p /home/AISC/.mihomo; \
       for f in geoip.metadb geosite.dat country.mmdb; do \
         url="https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/$f"; \
         ok=0; \
         for u in "${GH_PROXY}${url}" "$url"; do \
           if curl -fSL --retry 2 "$u" -o "/home/AISC/.mihomo/$f"; then ok=1; break; fi; \
         done; [ "$ok" = "1" ] || { echo "⚠️ geodata $f 下载失败（mihomo 仍可启动，GEO 规则可能受限）"; }; \
       done
   ```
   > geodata 失败不 `exit 1`（降级：GEO 规则不可用时多数订阅仍可用 IP-CIDR/域名规则）。
4. **CRLF 防御**：现有 `sed -i 's/\r$//'` 块**不**加 mihomo（ELF 二进制，同 `claude-real` 教训，sed 会破坏）。
5. 现有 `chown -R AISC:AISC /home/AISC` 自动覆盖 `/home/AISC/.mihomo` → AISC 可写、geodata 可读。

### docker run（启动器拼接，见模块 1）
条件追加 `--cap-add=NET_ADMIN --device /dev/net/tun -v <cfg>:/etc/mihomo/config.yaml:ro`。

---

## 模块 4 · entrypoint.sh 流量接管

在“作用域/env 注入”之后、“启动菜单 / `exec "$@"`”之前插入 mihomo 启动块：

```bash
# ==========================================
# 6.5 容器内 Mihomo TUN 透明代理（若挂载了配置）
# ==========================================
if [ -f /etc/mihomo/config.yaml ]; then
    echo "🚀 正在内建 TUN 透明代理网络..."

    # 权威注入 TUN 块到可写副本（ro 挂载不可写 → 副本）
    MIHOMO_DATA_DIR="/home/AISC/.mihomo"
    MIHOMO_CFG="$MIHOMO_DATA_DIR/config.yaml"
    SETTINGS_FILE="$SETTINGS_FILE" node - <<'NODE'
    const fs = require('fs');
    const src = '/etc/mihomo/config.yaml';
    const dstDir = '/home/AISC/.mihomo';
    const dst = dstDir + '/config.yaml';
    fs.mkdirSync(dstDir, { recursive: true });
    let text = fs.readFileSync(src, 'utf8').replace(/\r\n?/g, '\n');
    const lines = text.split('\n');
    function stripTopBlock(lines, key) {
      const out = []; let inBlock = false;
      for (const raw of lines) {
        if (/^\s*#/.test(raw)) { if (!inBlock) out.push(raw); continue; }
        if (/^[^\s]/.test(raw)) { inBlock = new RegExp('^' + key + ':').test(raw); if (!inBlock) out.push(raw); continue; }
        if (!inBlock) out.push(raw);
      }
      return out.join('\n');
    }
    const TUN = ['# === AISC forced TUN (auto-patched) ===','tun:','  enable: true','  stack: system','  dns-hijack:','    - any:53','  auto-route: true','  auto-detect-interface: true'].join('\n');
    const DNS = ['# === AISC fallback DNS (auto-patched, only if absent) ===','dns:','  enable: true','  listen: 0.0.0.0:1053','  enhanced-mode: fake-ip','  nameserver:','    - 223.5.5.5','    - 119.29.29.29','  fallback:','    - 8.8.8.8','    - 1.1.1.1'].join('\n');
    let p = stripTopBlock(lines, 'tun');
    p = p.replace(/\s+$/, '\n') + '\n' + TUN + '\n';
    if (!/^dns:/m.test(p)) p += '\n' + DNS + '\n';
    fs.writeFileSync(dst, p, 'utf8');
NODE

    # mihomo 建 TUN + iptables 需要 CAP_NET_ADMIN → 以 root(sudo) 后台启动
    # NOPASSWD sudoers 已就绪。日志写 AISC 可写目录。
    sudo -b bash -c "mihomo -d '$MIHOMO_DATA_DIR' -f '$MIHOMO_CFG' > '$MIHOMO_DATA_DIR/mihomo.log' 2>&1"

    # 等待 2-3s 让 TUN 接管路由
    sleep 2
    if sudo pgrep -x mihomo >/dev/null 2>&1; then
        echo "✅ Mihomo TUN 已就绪（PID $(sudo pgrep -x mihomo | tr '\n' ' ')）"
        # 健康探测：经代理拉一次小请求（失败仅 warn，不阻断）
        if curl -fsS --max-time 6 -o /dev/null https://api.anthropic.com 2>/dev/null; then
            echo "🌐 代理连通: api.anthropic.com 可达"
        else
            echo "⚠️  代理健康探测未通过（可继续；若 claude 连不上请检查 $MIHOMO_DATA_DIR/mihomo.log）"
        fi
    else
        echo "❌ Mihomo 启动失败，请查日志: $MIHOMO_DATA_DIR/mihomo.log"
    fi
    echo "----------------------------------------"
fi
```

随后原有 `exec "$@"` 启动 claude。TUN 已接管容器出站，claude 的 API 请求经 mihomo 代理。

---

## 文件改动清单

| 文件 | 改动 |
|------|------|
| `Dockerfile` | apt 加 `iptables iproute2 ca-certificates`；新增 mihomo 下载层（pin v1.19.27 + ghproxy 回退）；新增 geodata 预置层 |
| `entrypoint.sh` | 新增 `ensure_tun_config`（Node strip+append）+ mihomo 后台启动 + 健康探测 + 极客日志 |
| `启动_AI工作站.sh` | 新增 `configure_proxy` TUI（本地/URL）+ `docker run` 条件追加特权与挂载 |
| `一键启动_AI工作站.bat` | 新增 `:configure_proxy`（curl/PS 回退）+ `:runcontainer` 条件追加 |
| `.gitignore` | 忽略 `.claude/mihomo/`（订阅配置含节点凭据，不应入库） |
| `README.md` | 补“代理网络配置”章节 + docker run 示例 + 已知限制 |
| `devlog.md` | 新增 v1.2.3 条目 |

---

## 风险与取舍

1. **mihomo 需 root cap 建 TUN**：容器 `--cap-add=NET_ADMIN` 已授；`USER AISC` 无该 cap → mihomo 以 `sudo` 后台启动（NOPASSWD sudoers 已就绪）。
2. **DNS 死循环风险**：TUN `dns-hijack: any:53` 需 mihomo DNS 解析器；用户 config 无 `dns:` 块时自动补最小 `dns:` 块（仅当缺失，不覆盖用户配置）。
3. **geodata ~10MB 进镜像**：换“受限网络开箱即用”；下载失败降级（不阻断构建）。
4. **ghproxy 镜像 flaky**：`GH_PROXY` build-arg 可覆盖；下载逻辑代理→直连回退。
5. **订阅 base64**：仅支持 yaml 直链/转换后 yaml；TUI 检测异常内容并提示。
6. **`/dev/net/tun` 可用性**：Docker Desktop（Win/macOS）LinuxKit VM 内含该设备；原生 Linux 需 tun 内核模块（通常内置）。仅启用代理时才 `--device`，不配代理不受影响。
7. **PID1 与后台 mihomo**：`exec claude` 后 mihomo（sudo root）重父到 PID1；容器退出随 PID1 终止，`--rm` 自动清理。

## 实施顺序

1. Dockerfile（工具 + mihomo + geodata）→ 构建验证 `mihomo -v`
2. entrypoint.sh（ensure_tun_config + 启动块）
3. 启动器 .sh → .bat（TUI + 条件追加）
4. .gitignore + README + devlog
5. 端到端：TUI 选 URL → 起 container → `curl api.anthropic.com` 通 → `claude` 连通
