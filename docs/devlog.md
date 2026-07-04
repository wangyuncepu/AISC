# Super Claude — 开发日志

## v1.3.2 (2026-07-04) — 容器内 Python 运行时

### 动机
TODO「配置 docker 容器系统的 python」——容器内无 Python，Claude Code 无法跑 Python 脚本 / pip 装包。

### 变更
- **Dockerfile**：新增 Python apt 层（放 sed CRLF 之后，避免使 npm/claude 重型层缓存失效）——`python3 python3-pip python3-venv python-is-python3`（Debian 12 → Python 3.11）。
- **默认 venv**：`python3 -m venv /home/AISC/.venv`（USER AISC 后创建，AISC 可写）+ `ENV PATH="/home/AISC/.venv/bin:$PATH"`（venv 挂 PATH 头）。
- 绕过 Debian 12 PEP 668：系统 `pip install` 受限（externally-managed-environment），venv 内 `pip install` 直达，无需 `--break-system-packages`。

### 取舍
- **venv 在镜像内（`--rm` 每次重置）**：pip 装的包每次容器重启回到出厂（仅 pip 升级）。如需持久化包，加 requirements.txt + 启动安装脚本（未做，按需）。
- **Python 版本**：用系统 3.11（Debian 12 自带），不引入 pyenv/deadsnakes（够用）。
- **层位置**：python apt 放 sed CRLF 之后，npm/claude 重型层缓存命中，重建仅 ~30s。

### 测试
- 构建：python apt + venv 层新建，重型层 CACHED。
- 容器内：`which python` → `/home/AISC/.venv/bin/python`；`python --version` → 3.11.2；`pip install requests` → 成功（PEP 668 绕过）。

### 其他
- PLAN 文件从 `docs/TODO/` 移到 `docs/plans/`（与 TODO 分开）。
- TODO #3（启动器规范化）、#5（python）标完成。

---

## v1.3.1 (2026-07-04) — 项目目录重构（按职责分组）

### 动机

根目录 ~18 项混杂（Dockerfile/entrypoint/claude-switch/wrapper/_bundle/downloads/commands/启动器/文档/生成器…），违反高聚合。按职责分组到 `image/` / `scripts/` / `tools/` / `docs/`，根目录收敛到 7 项（入口 + README + 配置 + 锁文件）。

### 变更

- **`image/`**（新建，= 镜像构建上下文）：Dockerfile + entrypoint.sh + claude-switch + claude-wrapper + claude-settings.json + global-claude.md + mihomo-build-config.js + commands/ + _bundle/ + downloads/ 全部搬入。构建上下文从根改为 `image/`，**Dockerfile COPY 路径零改动**（全相对上下文）。
- **`tools/`**（新建）：stage-skills.sh + stage-mihomo.sh 搬入；`DST` 改为 `image/_bundle`、`image/downloads`（`$(dirname "$0")/..` 推导项目根）。
- **`docs/`**（新建）：devlog.md + TODO/ 搬入。
- **`scripts/03_build_image.{sh,ps1}`**：构建命令加 `-f $PROJECT_ROOT/image/Dockerfile` + 上下文改 `$PROJECT_ROOT/image`。
- **根目录**：仅留 README.md + .gitignore + .gitattributes + 3 个入口(.bat/.sh/.command) + skills-lock.json。
- **README**：项目结构章节重写；构建命令全部更新（`docker build -f image/Dockerfile ... image/`）；引用更新（stage-*.sh → tools/，downloads/ → image/downloads/，devlog.md → docs/devlog.md）。

### 取舍

- **构建上下文 = `image/`**：Dockerfile COPY 全相对上下文，搬入后零改动；额外收益——上下文从根（含 `.git/`/62MB 二进制/scripts/docs）缩到 `image/`，**传输更小、构建更快**。
- **`.gitattributes`/`.gitignore` 不动**：模式全局（`*.sh`/`*.ps1`/`claude-switch` 按文件名匹配子目录；`.claude/`/`.deploy/` 全局忽略），移动后仍生效。
- **宿主 `.claude/mihomo/` 留根**：02 写、04 挂载的代理配置是宿主运行时产物，非镜像输入。
- **`skills-lock.json` 留根**：未被构建/启动器引用，锁文件约定根。
- **版本号**：v1.3.0（模块化）已推送，本次续 v1.3.1（目录重构），不 force-push 重写历史。

### 测试

- `bash -n` 全 .sh；PS 语法全 .ps1。
- `docker build -f image/Dockerfile image/` 构建成功（验证上下文 + COPY）。
- e2e：启动器流水线（镜像存在→run）两平台通过。

---

## v1.3.0 (2026-07-04) — 启动器模块化重构（流水线 + 状态解耦）

### 动机

`launcher.ps1`（131 行）/ `启动_AI工作站.sh`（134 行）随 Mihomo TUN、API 配置等功能膨胀，构建/代理/运行逻辑耦合在单体脚本里，违反低耦合高聚合。拆为 4 个生命周期模块 + 薄流水线入口，模块间用状态文件解耦。

### 设计决策

- **D1 · 按平台 .sh + .ps1 平行**（已与用户确认）：bash/PowerShell 各平台自带，零宿主依赖（不选 Node.js 调度——宿主 Node 不可控，违反"开箱即用"）。代价：两套平行逻辑同步维护。
- **D2 · 状态文件解耦**：`.deploy/state.env`（KEY=value，gitignored）。只存简单值 `IMAGE`/`PROXY_ENABLED`/`CONTAINER_NAME`/`DO_RUN`；**路径不入状态**——各模块从 `$0`/`$PSScriptRoot` 推导 `PROJECT_ROOT`，避免空格/特殊字符破坏 `source`/解析。bash `source`/grep 读、PS 正则读；写用追加+去重。
- **D3 · 入口极薄**：根 `.sh`/`.bat` 只按序调 4 模块（pipeline）。
- **D4 · 行为保持**：根文件名 + 双击入口不变；代理 TUI/构建菜单/docker run 参数等价迁移。**API Key 仍在容器内 `cs`**、**作用域仍在 entrypoint**（不挪到宿主 02）。
- **D5 · 容器侧不动**：Dockerfile/entrypoint/mihomo-build-config.js/stage-mihomo.sh 全不变。

### 变更

- **scripts/ 流水线**（新增 12 文件，6 .sh + 6 .ps1）：
  - `run.*` 编排器：`state_init` + 写 `CONTAINER_NAME`/`IMAGE`/`DO_RUN`/`PROXY_ENABLED` 默认值 → 按序调 01-04，任一非零退出即中止。
  - `01_check_env.*`：`docker` 命令存在 + `docker info` daemon 运行；失败友好退出。
  - `02_config_wizard.*`：代理 TUI（y/N → 本地/URL → 下载/拷贝 → 非空校验）→ 写 `.claude/mihomo/config.yaml` + `state(PROXY_ENABLED)`。代理非阻断：失败/跳过 → `PROXY_ENABLED=0` 回退直连（匹配旧行为）。
  - `03_build_image.*`：镜像存在菜单（[1]运行/[2]重建/[3]新名）+ 构建（cache/镜像源提示）+ "立即运行?" → `state(IMAGE, DO_RUN)`。`DO_RUN=0`（选不运行）→ 04 跳过 docker run。
  - `04_launcher.*`：读 state → 清退出的旧容器 → 拼 `docker run`（`PROXY_ENABLED=1` 追加 `--cap-add=NET_ADMIN --device=/dev/net/tun` + 配置只读挂载）。
  - `_state.*`：`state_init`/`state_set`/`state_get`（bash）/ `Init-State`/`Set-State`/`Get-State`（PS）。PS 用 .NET `WriteAllText`（UTF-8 无 BOM + LF）避免 bash `source` 被 BOM/CR 破坏；bash `state_get` 末尾 `tr -d '\r'` 防御。
- **根入口改薄**：`启动_AI工作站.sh` → `exec bash scripts/run.sh`；`一键启动_AI工作站.bat`（ASCII）→ `powershell -File scripts/run.ps1`；`.command` 不变。
- **PS1 BOM**：所有 `scripts/*.ps1` UTF-8 BOM（PS5.1 按 BOM 识别中文）；`.gitattributes` `*.ps1 text eol=lf` 保证提交后 LF+BOM。
- **`.gitignore`**：加 `.deploy/`（运行时状态）。

### 取舍

- **PS 编排用子进程**：`run.ps1` 用 `& powershell -NoProfile -File` 调各模块（独立进程 + `$LASTEXITCODE`），而非 dot-source——dot-source 下模块 `exit 0` 会退出整个 run.ps1，破坏流水线。子进程有 ~1-2s 启动开销，可接受。bash 同理用 `bash scripts/0X.sh` 子进程。
- **DO_RUN 状态位**：03"构建后不运行"需干净中止 04。用 `DO_RUN` 状态位（0/1）而非特殊退出码，符合状态解耦原则。
- **两套平行逻辑**：改提示文案需同步 .sh + .ps1 两份（用户已接受）。

### 测试

- `bash -n` 全 .sh 通过；PS `[Parser]::ParseFile` 全 .ps1 通过。
- e2e 两平台 × 两路径（配/不配代理）全通过：4 模块按序、state.env 正确流转（`PROXY_ENABLED`/`DO_RUN`/`IMAGE`/`CONTAINER_NAME`）、docker run 拿到正确参数（代理路径含 `--cap-add=NET_ADMIN --device=/dev/net/tun` + 配置挂载）。

---

## v1.2.3 (2026-07-04) — 容器内建 Mihomo TUN 透明代理

### 动机

宿主机零代理场景下，让容器内 Claude Code 直连 Anthropic API。在容器内以 Mihomo (Clash Meta) TUN 模式接管全部出站，宿主无需开任何代理；TUI 引导用户完成配置，开箱即用。对应 TODO「clash翻墙配置（docker内部翻墙）」。

### 设计决策（与用户确认）

- **D1 · TUN 补丁容器内权威注入**：宿主启动器只下载/拷贝用户**原始**配置到 `.claude/mihomo/config.yaml`（不打补丁）；`entrypoint.sh` 用 Node 在可写副本上 strip+append。落盘文件保留原始配置，运行时强制含 TUN。理由：容器内 Node+工具必有、每次启动重打、手动丢配置也兜底；宿主环境不可控（Windows BAT 无 Node/awk）。
- **D2 · docker run 特权按需追加**：仅 TUI 选“需要代理”时追加 `--cap-add=NET_ADMIN --device /dev/net/tun` 与配置只读挂载；不配代理则零特权、零 tun 设备依赖，避免宿主缺 `/dev/net/tun` 时启动失败。

### 变更

- **Dockerfile**：apt 增加 `iptables iproute2 ca-certificates`（TUN auto-route 操纵 iptables/路由表、https 下载）；新增 mihomo 下载层（pin `MIHOMO_VERSION=v1.19.27`，arch 自适应）+ geodata 预置层（geoip.metadb/geosite.dat/country.mmdb → `/home/AISC/.mihomo`，单文件失败仅 warn 不阻断）。**下载加固**：优先用 `downloads/` 本地预置（离线/弱网）；否则多镜像轮询（ghfast.top 实测稳，依次 gh-proxy/github.moeyy/ghproxy.net/mirror.ghproxy）+ 强制 `--http1.1`（绕开 curl/GitHub CDN HTTP/2 流异常）+ 短 connect-timeout 快失败 + 直连兜底。
- **stage-mihomo.sh**（新增）：预下载 mihomo.gz + geodata 到 `downloads/`。镜像 `stage-skills.sh`+`_bundle` 自包含哲学；`downloads/` **已纳入 git** → `docker build` 完全不访问 GitHub（详见增量）。
- **entrypoint.sh**：新增 §3.5 — 若 `/etc/mihomo/config.yaml` 存在：Node 读 ro 源 → 通用顶层块剥离（`tun:`/`dns:`）→ 追加规范 `tun:` 块（+ 缺失时补最小 `dns:` 防 53 端口解析死循环）→ 写可写副本 → `sudo -b mihomo -d ~/.mihomo -f 副本` → sleep 2 → pgrep 健康检查 + `curl api.anthropic.com` 探测 → 极客日志。失败仅告警不阻断（便于进 bash 排障）。
- **启动_AI工作站.sh**：新增 `configure_proxy()`（本地文件/URL 二选一，curl 下载，base64 异常检测）+ `docker run` 数组化条件追加 `--cap-add=NET_ADMIN --device /dev/net/tun -v .../config.yaml:/etc/mihomo/config.yaml:ro`。
- **一键启动_AI工作站.bat**：降级为纯 ASCII 三行包装（`chcp 65001` + `powershell -File launcher.ps1`）；中文 UI 与全部逻辑移至 `launcher.ps1`（PowerShell 原生 Unicode）。cmd .bat 对中文有 DBCS 解析缺陷，无法在 .bat 内承载中文（详见增量「Windows 启动器中文化」）。
- **.gitignore**：显式忽略 `.claude/mihomo/`（订阅凭据敏感；`.claude/` 已覆盖，此处防御性显式）。
- **README / devlog**：新增“代理网络（容器内建 Mihomo TUN）”章节（原理图/使用/手动构建/已知限制）+ 数据模型补 `.claude/mihomo/`。

### 取舍

- **DNS 块**：用户 spec 仅列 `tun:`；实测 TUN `dns-hijack: any:53` 无解析器易形成解析死循环 → 仅在用户配置**无** `dns:` 顶层块时补一个最小 `dns:`（fake-ip + 国内外 nameserver/fallback），不覆盖用户已有 `dns:`。
- **mihomo 版本 pin**：v1.19.27（build-arg 可覆盖），换可复现构建；asset `mihomo-linux-<arch>-<ver>.gz` 已核验。
- **mihomo 以 root 启动**：`USER AISC` 无 `CAP_NET_ADMIN`，建 TUN + iptables 必须 root → `sudo`（NOPASSWD sudoers 已就绪）。后台 `sudo -b`，容器退出随 PID1 终止，`--rm` 自动清理。
- **geodata 失败降级**：不阻断构建（GEO 规则不可用，多数订阅仍可用 IP-CIDR/域名规则）。
- **ghproxy flaky**：`GH_PROXY` build-arg 可覆盖；下载逻辑代理→直连回退。

### v1.2.3 增量（多格式订阅自动转换 + 启动器中文化 + 构建下载加固）

- **下载加固（Dockerfile）**：mihomo/geodata 下载层重写——优先用 `downloads/` 本地预置（离线/弱网）；否则多镜像轮询（`ghfast.top` 实测稳，依次 gh-proxy / github.moeyy / ghproxy.net / mirror.ghproxy）+ 强制 `--http1.1`（绕开 curl/GitHub CDN HTTP/2 流异常）+ 短 connect-timeout 快失败 + 直连兜底。修复用户构建时 `mirror.ghproxy.com` SSL 失败 + GitHub HTTP/2 流异常导致下载失败。
- **stage-mihomo.sh（新增）**：预下载 mihomo.gz + geodata 到 `downloads/`。**已纳入 git**（同 `_bundle` 哲学）→ `docker build` 完全不访问 GitHub，国内网络无忧（消除用户提出的「构建期 GitHub 下载慢/失败」风险）。升级 mihomo：改 Dockerfile `MIHOMO_VERSION` 后重跑本脚本更新 `downloads/` 再提交。`downloads/` 为空时构建自动回退多镜像下载。
- **mihomo-build-config.js（新增）**：把原 entrypoint 内联 heredoc 抽成独立脚本（可测、清晰）。职责 = 原始订阅 → mihomo 配置：①格式识别（clash-yaml / base64订阅 / URI直链 / JSON(SIP008)），非 yaml 自动转最小 Clash 配置（proxies + url-test自动选最快 + select + MATCH,PROXY），节点协议支持 ss/vmess/trojan/vless/hysteria2(hy2)；②剥离已有 tun:/dns: 顶层块 → 追加规范 tun:（+ 缺失时补 dns:）。退出码：0 产出配置 / 1 硬失败（空 / 识别为订阅但 0 节点 / 读取失败）。
- **entrypoint.sh**：§3.5 改调 `node /usr/local/bin/mihomo-build-config.js`，去掉大段内联 heredoc。健康检查改用 **curl 探测作主信号**——初版用 `pgrep -x mihomo` 在 3s 时点曾误报「启动失败」（进程名/时序问题），但 mihomo 实际存活并处理了请求；改为 `curl -sS https://api.anthropic.com`（去 `-f`：无 auth 返 401/404，`-f` 会误判失败，任何 HTTP 响应都算可达）。sleep→4 给 url-test 初选时间。curl 失败时用 `pgrep -f 'mihomo -d'` 区分「进程退出 vs 仍在初选」。实测：用户 base64 订阅 → 31 节点 → TUN 接口 `Meta` UP → api.anthropic.com 经 hysteria2 节点可达（HTTP 404）。
- **启动器校验放宽**：`.sh`/`.bat` 去掉「必须含冒号」的 yaml 限制，改为非空即可——格式由容器内识别/转换。
- **Windows 启动器中文化（.bat → .ps1 拆分）**：cmd.exe 的 .bat 对中文有 DBCS 解析缺陷，三方案全败——① UTF-8 文件按 OEM(936/GBK)解析致 3 字节错切，中文片段被当命令执行（`'时多开...' is not recognized`）；② GBK 编码又撞 cmd 第二个 bug（GBK 尾字节落 ASCII 特殊字符区如 `|`/`{`，`if/goto` 上下文不当双字节处理 → `syntax incorrect`）；③ UTF-8 BOM 不被 cmd 识别（破坏 `@echo off`）。`chcp`/BOM 均改不了 .bat 解析码页（固定 OEM）。故 `.bat` 降级为纯 ASCII 三行包装（`chcp 65001` + `powershell -File launcher.ps1`），所有中文 UI 移到 `launcher.ps1`（PowerShell 原生 Unicode，UTF-8 BOM 解析无缺陷）。`launcher.ps1` 设 `[Console]::OutputEncoding=UTF8` + `.bat` 已 `chcp 65001` → 中文在任何 Windows 正常显示。docker 调用用数组 splatting（`& docker @args`）规避 PS 原生参数引号问题；`--device=/dev/net/tun` 用 `=` 形式避免 PS 对 `/` 前缀的处理。实测中文 UI 完美显示、无解析错误、两条路径（配/不配代理）均正确拼出 docker run。
- **多格式验证**：用户订阅 `https://103.14.76.98/sub/fsc/...`（base64，31 节点：trojan/vless/hysteria2）→ 转换后 `mihomo -t` 校验通过。

### 已知限制

- 自动转换生成最小配置（自动选最快节点 + 全流量走代理），不含原订阅分流规则/分组；需精细分流仍可提供 Clash YAML 直链（原样使用，仅注入 TUN）。节点协议暂支持 ss/vmess/trojan/vless/hysteria2，其余协议解析到 0 节点会明确报错。
- `/dev/net/tun` 依赖：Docker Desktop LinuxKit VM 内置；原生 Linux 需 tun 模块。仅启用代理时挂载。
- mihomo 日志在容器内 `/home/AISC/.mihomo/mihomo.log`。

---

## v1.2.2 (2026-07-01) — 非 root 运行（AISC 用户）

### 动机

Claude Code 在 root 下拒绝 `--dangerously-skip-permissions` 模式。容器全程改用非 root 用户 `AISC`（uid 1000），
让该模式可用；挂载点从 `/app` 移到 AISC 家目录 `/home/AISC/app`，所有运行态目录均在 AISC 可写范围内。

### 变更

- **Dockerfile**：`useradd -m -u 1000 AISC`；出厂 `.claude` 由 `/root/.claude` 改建 `/home/AISC/.claude`；
  `WORKDIR /home/AISC/app`；构建末尾 `chown -R AISC:AISC /home/AISC` 后 `USER AISC`。
- **entrypoint.sh**：`GLOBAL=/home/AISC/.claude`、`PROJECT=/home/AISC/app/.claude`、`CC_CONFIG=/home/AISC/app/.cc-config`；
  删除 root 专属的 `chown` 权限交还逻辑（AISC 直接读写挂载卷）；作用域导出改写 `~/.bashrc`，不再写 `/etc/profile.d`。
- **claude-wrapper / claude-switch**：fallback 与 `do_upgrade` 出厂源路径改 `/home/AISC/.claude`；
  `cs` KEY_DIR 解析路径改 `/home/AISC/app/.cc-config`；`do_upgrade` 删除 `chown` 交还块。
- **stage-skills.sh**：`IMG_HOME=/home/AISC/.claude`。
- **启动器（.sh / .bat）**：挂载目标 `:/app` → `:/home/AISC/app`（.bat 的 named volume 同步改 `/home/AISC/app/.claude`）。
- **README / devlog**：路径表与示例命令同步更新。

### 取舍

- 不做 UID 匹配（无 build-arg UID/GID）。Docker Desktop 下容器 uid 对宿主透明，AISC(1000) 写入即归宿主用户。
  原生 Linux Docker 若宿主 uid ≠ 1000，挂载卷可能写不动 —— 留待实际遇到再加 build-arg。
- 不保留旧 root 所有权文件的迁移修复：全新非 root 环境，旧 `/app/.claude` 若 root 所有权残留需手动删除重建。

### v1.2.2 增量（容器配置加固）

在非 root 运行基础上，补齐权限/安全/构建稳健性与 git 工作流。

- **AISC 用户密码 + sudoers**：`echo 'AISC:AISC' | chpasswd`；`/etc/sudoers.d/aisc` 写 `AISC ALL=(ALL) NOPASSWD:ALL`（440）。容器内 AISC 免密 sudo，便于权限修复与系统操作。
- **entrypoint.sh 自愈 `.cc-config` 所有权**：旧镜像曾以 root 运行，绑定挂载把 root 所有权持久化到宿主，导致 AISC 读不了 `root:600` 的 `api-keys` → `cs` 切换静默失败。改为 `sudo chown -R AISC:AISC "$CC_CONFIG_DIR"` 自愈（依赖前述 sudoers）。
- **claude-wrapper 默认 `--dangerously-skip-permissions`**：注入默认 flag 跳过权限确认（容器内自动流），用户手动传入则不重复追加，避免重复 flag 报错。前提是 `USER AISC`（root 下 Claude 拒绝此 flag）。
- **git 全局 `core.autocrlf=input`**：Dockerfile 内 `USER AISC` 后 `git config --global core.autocrlf input`。commit 时 CRLF→LF（仓库永远干净 LF），checkout 不转；跨平台(Win 宿主 + Linux 容器)避免 CRLF 噪音进历史，`.gitattributes` 优先于此。
- **`.gitattributes` 行尾规范化**：`git add --renormalize .` 一次性把 665 个 `_bundle` CRLF 噪音归零（纯行尾，无内容差异），分两个 commit（行尾规范化 + 源文件改动）入库。
- **启动器 `.bat` 加固**：
  - `:build` 开头检查 `%~dp0Dockerfile` 是否存在，缺失则报错退出（提示「请在有 Dockerfile 及其它资源的文件夹下进行 build 操作」）。
  - build 失败检测修正：`if` 块内 echo 去括号（修 "was unexpected at this time" 解析错误）；每个 `call :build` 后加 `if errorlevel 1 exit /b 1`（修 `exit /b` 从 call 返回不退出脚本、假报成功的问题）。
- **本项目 git 配置**：`user.name=Thomas Wang`、`user.email`、`credential.helper=store`（token 存 `.git-credentials`，600 权限，`.gitignore` 忽略），remote 走 HTTPS + PAT。

### 取舍（增量）

- `--dangerously-skip-permissions` 默认开：容器 `--rm` 隔离 + 绑定挂载仅 `app/`，风险可控；纯本地自动流场景值得。
- token 存仓库内 `.git-credentials`：随项目走但明文（600），比放 `~/.git-credentials` 风险略高，用户取舍。
- sudoers `NOPASSWD`：容器内便利 > 安全约束；容器即用即弃，影响域有限。

### v1.2.2 增量二（后端模型配置对齐 + xf 后端 + cs show 增强）

实测各代理可用模型后，对齐 `claude-switch` 配置。

- **新增 xf 后端**（讯飞 maas-coding）：`XF_BASE=https://maas-coding-api.cn-huabei-1.xf-yun.com/anthropic`，独立 `XF_KEY`。三档：OPUS=`xopglm52`（glm5.2，512k 无 1M）、SONNET=`xopdeepseekv4pro[1m]`、HAIKU/SUBAGENT=`xopdeepseekv4flash[1m]`；EFFORT=max、COMPACT=512000。
- **ark 低端两档换 deepseek**：SONNET 由 `glm-5.2[1m]` → `deepseek-v4-pro[1m]`，HAIKU/SUBAGENT 由 `glm-4.7` → `deepseek-v4-flash[1m]`；OPUS 保持 `glm-5.2[1m]`；EFFORT 开 max。
- **1y 配置实测对齐**：1y 仅 `glm-5.2` 可用（Claude 模型名全 503），全档改 `glm-5.2[1m]`。
- **duo-cc 配置实测对齐**：duo-cc Claude 模型名 `claude-sonnet-5`/`claude-opus-4.8`/`claude-haiku-4.5` 实测可用，MODEL 全设 `claude-sonnet-5[1m]`。
- **COMPACT 统一**：除 cc（清空设计）与 xf（512000）外，deepseek/ark/1y/duo-cc 全设 `1000000`，充分利用 1M 窗口、减少压缩损失。
- **`cs show` 增强**：不再只显示后端名，打印全部 11 个 settings.json env 变量（BASE/TOKEN/API_KEY/MODEL/OPUS/SONNET/HAIKU/SUBAGENT/EFFORT/COMPACT），敏感 token 截断显示（前 12 + 后 4）。

### 取舍（增量二）

- duo-cc/1y 设 COMPACT=1M 但模型未必真支持 1M：若实际窗口 <1M，到模型上限才报错而非提前压缩。duo-cc 充值后实测确认。
- xf OPUS `xopglm52` 不加 `[1m]`：glm5.2 在讯飞只有 512k，加后缀会错。

## v1.2.1 (2026-06-30) — README 手动构建/运行 文档完善

- **README 手动构建/运行部分重写**：拆分为构建/运行/常用变体三个小节，覆盖三平台命令。
  - 构建：明确 `USE_CN_MIRROR` 默认=1，新增 `--no-cache` 示例。
  - 运行：新增 Windows PowerShell/CMD 的 `-v` 语法，强调 `TERM=xterm-256color` 必要性。
  - 常用变体：`CLAUDE_SCOPE` 跳过菜单、`bash` 直接进 shell、`cs <后端>` 一键切换、`--name` 容器命名。

## v1.2.0 (2026-06-30) — 插件化重构 + 双作用域 + 跨平台修复

### 架构重构

- **临时 / 项目双作用域**：用 Claude CLI 原生 `CLAUDE_CONFIG_DIR` 驱动。
  临时 = 镜像内置 `/root/.claude`（即用即弃）；项目 = `/app/.claude`（从镜像完整复制，持久到宿主机卷）。
  entrypoint 交互菜单 / `CLAUDE_SCOPE` 环境变量选择，导出并写入 `.bashrc`/`profile.d`。
- **`.claude` 与 `.cc-config` 分离**：`.claude` 为 CLI 原生完整目录（skills/plugins/projects…）；
  `.cc-config` 仅存 cs 的 `api-keys`（密钥隔离，gitignore）。
- **插件机制集成 6 套技能**（离线可用，预置 cache + marketplaces + 注册表 + `enabledPlugins`）：
  caveman（SessionStart hook 默认激活）/ claude-hud（statusLine HUD）/ document-skills /
  superpowers / skill-creator + gstack（扁平文档，6 子技能 + 斜杠命令）。
  `skill-creator` 构建期从本地 marketplace 离线 install。
- **自包含构建**：插件包 `_bundle` 纳入 git（约 24M），`docker build` 不再依赖宿主机 `~/.claude`。
  `stage-skills.sh` 作为一次性生成器（裁剪 marketplace、cache 版本剪枝、gstack 仅 6 子技能）。
- **cs 实时切换**：env 块改写入 `.claude/settings.json`（Claude Code 原生读取），`!cs ds` 当场生效；
  `write_settings` 合并保留 `enabledPlugins/statusLine`。`cs cc` 允许留空清空所有配置。
- **cs upgrade + 出厂版本检测**：`.factory-version`（出厂内容哈希）；项目版本旧则提示升级；
  `cs upgrade` 叠加更新出厂部分、合并 settings（留 env）、保留运行态、孤项编号表格多选删除。

### 启动器增强（.sh / .bat / .command）

- 镜像不存在自动构建；已存在三选一（直接运行 / 删旧重建防悬空 / 新镜像名）。
- 构建前两问：是否用缓存（`--no-cache`）、是否用国内镜像源（`USE_CN_MIRROR` + daocloud 基础镜像）。
- 容器名唯一后缀（`$$` / `%RANDOM%`），仅清理已退出容器 → 项目+临时多开互不挤掉。

### 跨平台修复（Windows 重点）

- **`.bat` 改纯英文 ASCII**：UTF-8 中文被 cmd 按代码页解析断行报错（wt 同样），英文根治；`chcp 65001` 仅保障 claude 输出。
- **基础镜像 docker.io 超时**：国内镜像选项同时把 `NODE_IMAGE` 指向 daocloud，绕开 `auth.docker.io`。
- **HUD 不显示（多根因）**：① 强制 `TERM=xterm-256color`（Windows 容器 TERM 缺失致 statusLine 隐藏）；
  ② 符号链接（superpowers AGENTS.md）`cp -r` 在 grpcfuse 创建失败 + `set -e` 中断致 `.claude` 复制残缺 →
  镜像内解引用所有 symlink + entrypoint 完整性校验补拷 + `cp -rL`；
  ③ **插件自带 `.gitignore`（含 `dist/`）导致 claude-hud `dist/index.js` 漏提交** → 用户 clone 缺文件、
  statusLine `MODULE_NOT_FOUND`；stage-skills 删除嵌套 `.gitignore` + 补提交；
  ④ `installed_plugins.json` 路径写死 `/root` → CLI 误判项目副本 orphan 可能删 dist → 复制后重写路径为项目目录。
- **`.claude.json` 缺失**：新版 CLI 核心状态在 `.claude.json`，构建期写入 onboarding + 跑一次 CLI 补全运行字段。

### 网络 / 工具（前置工作）

- WSL → Windows Clash 代理（7890）走 SSH-over-443（`ssh.github.com`），9 仓库切 SSH remote。
- 主机 `claude-switch` 增加 `duo-cc` 后端。

## 修复：.bat WT 启动逻辑重做 (2026-06-29, bug4 后续)

### 🐛 no.4 修复后暴露的两个新问题

- **4a 重复开窗** — 已在 Windows Terminal 内运行 `.bat` 仍无条件再开一个 wt。
  根因：脚本只 `where wt` 判断系统是否装 wt，未判断**当前是否已在 wt 内**。
  修复：读环境变量 `WT_SESSION`，已在 wt 则 `goto run` 直接当前标签运行。
- **4b docker 丢参** — 新 wt 内报 `'docker run' requires at least 1 argument`（`%IMAGE%` 丢失）。
  根因：`wt ... cmd /k "...""%cd%:/app""...%IMAGE%"` 的嵌套双引号经 **wt tokenizer**（非 cmd）解析时被拆断，
  命令在 `-v` 后截断，`%IMAGE%` 落入 wt 的其它参数而丢失。
  修复：改为**自重启模式** — wt 仅以本脚本 `cmd /k ""%~f0""` 开新标签，
  `docker run` 在重启实例内**直接执行**，不再把命令串塞进 wt 解析器；`wt -d "%cd%"` 保留工作目录。
  结构用 `if defined WT_SESSION goto run` + `where wt` / `if errorlevel 1 goto run` + `:run` 标签，
  规避 `&&( ... )` 括号块的批处理解析坑。

### ⚠️ 验证

本机 Linux 无法执行 `.bat`，仅做静态校验（含 `WT_SESSION`/`wt -d`、docker run 参数完整、无嵌套 docker 串）。
**需 Windows + Windows Terminal 实测三场景**：① 已在 wt 标签内双击/运行 ② CMD/PowerShell 双击 ③ 未装 wt。

## 修复：容器运行时与 Windows 启动问题 (2026-06-29, no.3-5)

### 🐛 三项缺陷修复

- **no.5 中文乱码** — 容器内未配置 UTF-8 locale，`ls` 等输出八进制转义乱码。
  Dockerfile 注入 `ENV LANG=C.UTF-8 LC_ALL=C.UTF-8`（debian-slim/glibc 内置，无需 locale-gen），
  `entrypoint.sh` 追加 `export LANG/LC_ALL` 作运行期兜底。已在容器内验证 `locale`=`C.UTF-8`、中文文件名与渲染正常。
- **no.4 .bat 报错** — `一键启动_AI工作站.bat` 经 Windows Terminal 启动报 `参数格式不正确 - >nul`，
  根因为 `wt ... cmd /k "chcp 65001 ^>nul && ..."` 中 caret 转义的 `>nul` 被 wt 参数切分误判。
  去除该重定向（保留一行 `Active code page` 输出，无害）。
- **no.3 残留容器** — `docker run --rm` 无 `--name`，窗口被强制关闭时容器残留需手动删。
  启动脚本（`.bat` + `启动_AI工作站.sh`）改用固定 `--name super-claude-station`，
  并在每次启动前 `docker rm -f` 清理同名 stale 容器，保证不堆积。正常退出仍建议 `exit`。

### ✅ 验证

`docker build` 通过；容器内 `locale` 确认 `C.UTF-8`，`ls` 中文无乱码。
Windows `.bat` 的 no.4 需在 Windows + Windows Terminal 环境实测确认。

## v1.1.3 (2026-06-28)

### 🚀 启动体验与全局行为优化

**重大变更**：后端配置与 Key 统一持久化到项目挂载目录 `/app/.claude/`，并在 `entrypoint.sh` 与 `claude-wrapper` 中自动注入环境变量，解决配置后仍进入登录引导、首次进入 bash 后手动 `claude` 不生效等问题。

### ✨ 变更

| 项 | 说明 |
|----|------|
| 配置持久化 | `cs` 在 Docker 内优先写入 `/app/.claude/settings.json`，随项目挂载卷保留 |
| Key 持久化 | `cs` 在 Docker 内优先写入 `/app/.claude/api-keys`，容器重建不丢失 |
| `claude-wrapper` | 新增包装器：每次运行 `claude` 前读取 settings env，注入 `ANTHROPIC_*` / `CLAUDE_CODE_*` 后再执行 `claude-real` |
| 全局 `CLAUDE.md` | 新增 `global-claude.md`，构建时复制到 `/root/.claude/CLAUDE.md` |
| karpathy-flow 默认启用 | 将 Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution 写入全局 `CLAUDE.md` |
| Caveman 默认启用 | 全局默认 Caveman `full` 沟通风格，用户可用 `normal mode` / `stop caveman` 关闭 |
| 跨平台启动脚本 | 新增 Linux `启动_AI工作站.sh` 与 macOS `启动_AI工作站.command`，Windows `.bat` 更新为 v1.1.2 横幅并优先使用 Windows Terminal |
| README 启动说明 | 按 Windows / Linux / macOS 拆分，补充启动模式、单次运行、容器残留清理、终端乱码说明 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| 登录引导误触发 | `entrypoint.sh` 读取 settings 后真正 `export` env，避免只有配置文件但 Claude 进程无 token |
| 首次 bash 后手动 `claude` 不生效 | `claude-wrapper` 每次启动都重新注入 env，解决 `cs` 写入配置后当前 bash 环境未更新的问题 |
| 项目级 settings 覆盖全局 settings | `cs` 优先写 `/app/.claude/settings.json`，避免 `.claude/settings.json` 与 `~/.claude/settings.json` 不一致 |
| `/model` pin 冲突 | `cs` 写 settings 时删除 `model` 字段，让 `env.ANTHROPIC_MODEL` 接管当前后端 |
| 空 API Key 覆盖 Auth Token | env 注入时对空值执行 `unset`，避免 `ANTHROPIC_API_KEY=""` 干扰 `ANTHROPIC_AUTH_TOKEN` |
| 单次运行模式 | 验证 `docker run ... claude -p "..."` 可用，并写入 README |
| CMD 中文乱码 | `.bat` 优先使用 Windows Terminal；README 明确传统 CMD 可能乱码 |

### 📝 已知问题

- [ ] Termius SSH 配置文档未编写
- [ ] gstack 仅有技能描述，完整运行时安装方案待确认

---

## v1.1.2 (2026-06-27)

### 🔐 安全重构：API Key 与脚本分离

**重大变更**：`cs` 脚本不再硬编码 Key，改为从 `~/.claude/api-keys` 读取，无 Key 时交互式提示输入。

### ✨ 变更

| 项 | 说明 |
|----|------|
| Key Store | `~/.claude/api-keys`（chmod 600），`KEY_NAME=value` 格式，5 组 Key 独立存储 |
| `get_key()` | 新函数：先查 Key Store → 没有则提示用户输入 → 输入后自动保存 |
| `cs show` 增强 | 显示当前后端 + 各后端 Key 保存状态（✓/✗） |
| URL 保留 | 端点 URL 仍留在脚本中（非机密），仅 Key 走外部存储 |
| Dockerfile | 构建时不执行 `cs`，改为创建空 `api-keys` + 空 `settings.json` |
| entrypoint 引导 | 未配置时自动显示 `cs deepseek` / `cs ark` 等可用命令 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| 硬编码 Key | `claude-switch` 第 21-27 行移除全部默认 Key |
| 构建时依赖 Key | Dockerfile 不再 `RUN cs deepseek`，避免 build 阶段要求交互输入 |
| Key 注入 JS 字符串 | 改为 env var 传递（`export CS_AUTH_TOKEN`），消除 `'` `\` 等特殊字符引发的 SyntaxError |
| `get_key()` stdout 污染 | `echo` 提示文案全部改 `>&2`，`$()` 只捕获纯 Key 值 |
| CRLF 混入 Key | `grep` → `tr -d '\r'` 清洗 Windows 行尾 |
| 密钥路径 | Docker 容器内自动使用 `/app/.claude/api-keys`（随 `-v` 挂载） |
| entrypoint 重复提示 | Section 3 改为单行状态；Section 5 仅在拦截时显示一次性引导 |
| entrypoint 未配置拦截 | `claude` 命令在无后端时 `exec bash` 而非直接进 Claude Code |
| `.gitignore` | 新增 `api-keys` + `super-claude-v1.1.2.tar` 排除规则 |

### 📝 已知问题

- [ ] Termius SSH 配置文档未编写
- [x] ~~`cs` 脚本内 API Key 硬编码~~ → v1.1.2 修复

---

## v1.1.1 (2026-06-27)

### 🔄 切换脚本重构：`cs` 统一入口

**重大变更**：废弃交互式菜单方案，改用 `cs` 一键切换 + `~/.claude/settings.json` 持久化。

### ✨ 变更

| 项 | 说明 |
|----|------|
| `cs` 统一入口 | `cs` / `claude-switch` 指向同一脚本，写入 `~/.claude/settings.json` |
| 放弃菜单交互 | 旧版 `claude-switch` 菜单 + `.claude_keys` 方案全部移除 |
| 5 后端内嵌 Key | cc / deepseek / ark / 1y / duo-cc 的 API Key 内置脚本，切换即用 |
| `cs show` | 快速查看当前后端 |
| `SC_RESTART=1` | 切换后自动重启 Claude Code（Docker 直连模式） |
| 默认后端初始化 | Dockerfile 构建时 `RUN cs deepseek`，不再用 `ENV` 硬编码 |
| `ARG NODE_IMAGE` | 基础镜像可通过 `--build-arg` 替换，解决国内拉取问题 |
| `.gitignore` | 排除 `super-claude-v1.tar`、`.claude_keys` |
| 构建导出流程 | `docker build` + `docker save` → `super-claude-v1.tar` |

### 🔧 修复

| 项 | 说明 |
|----|------|
| CRLF 行尾 | `claude-switch` 从 CRLF 转为 LF，修复容器内 `bash\r` 错误 |
| DeepSeek 无 Key | 移除 Dockerfile 中 `ENV ANTHROPIC_BASE_URL`（有 URL 无 Token 导致 `ERR_BAD_REQUEST`） |
| entrypoint 横幅 | 改为从 `~/.claude/settings.json` 读取后端信息，不再依赖 Docker ENV |
| `claude` 包装器 | 简化为直接移交 `claude-real`，不再做 Key 检测（切换交给 `cs`） |
| cygpath 兼容 | `cs` 脚本自动识别 Windows/Linux 环境，Linux 容器内直接使用 POSIX 路径 |

### 📝 文档

- README.md 重写：`cs` 用法、平台详情表、构建导出流程
- 新增 `cs` 直连模式说明：`docker run ... cs ark`

### 🗑️ 移除

- 旧版交互式 `claude-switch` 菜单（Anthropic/DeepSeek/硅基流动/OpenRouter/智谱 5 选 1）
- `.claude_keys` Key 持久化文件（改为 `~/.claude/settings.json` 管理）
- `entrypoint.sh` 中无 Key 自动引导逻辑（不再需要）
- Dockerfile 中 7 行 `ENV` 硬编码 DeepSeek 变量

### 📂 当前项目结构

```
.
├── Dockerfile
├── entrypoint.sh
├── claude-switch                       # 同时是 cs 和 claude-switch 的源
├── 一键启动_AI工作站.bat
├── devlog.md
├── README.md
├── skills/
│   ├── claude.json
│   ├── karpathy-flow/
│   └── ... (20+ 技能)
├── .claude/
│   └── settings.local.json
├── .claude_keys                        (已废弃，不再使用)
└── todo/
    ├── todo.md
    └── 20260625/
        ├── claude-switch               (开发过程中的中间版本)
        └── setup-ssh-portproxy.ps1
```

### 已知问题

- [ ] Termius SSH 配置文档未编写
- [ ] `cs` 脚本内 API Key 硬编码，后续可改为环境变量覆盖 + 运行时输入

---

## v1.1.0 (2026-06-27)

### 🔄 架构重构：纯终端闭环

**重大决策**：彻底切断对第三方 GUI 黑盒工具的依赖，转向 100% 内部闭环的纯终端 CLI 工作流。

### ✨ 新增

| 项 | 说明 |
|----|------|
| `claude-switch` | 内置模型后端切换器 CLI，支持 5 大平台、15+ 模型 |
| 平台接入 | Anthropic 官方 / DeepSeek 官方 / 硅基流动 / OpenRouter / 智谱 Z.AI |
| 硅基流动子菜单 | 5 款国产模型可选（DeepSeek-V4-Pro、GLM-5.2、Nex-N2-Pro、MiniMax M3、Qwen3.6-35B） |
| OpenRouter 子菜单 | 6 款全球模型可选（Claude Opus 4.8、Sonnet 4.6、DeepSeek V3.2、GLM-5.2、Qwen3 Coder、Kimi K2.7） |
| 智谱 Z.AI 子菜单 | 3 款 GLM 模型可选（GLM-4.6、GLM-4.5、GLM-4.5-Air） |
| `一键启动_AI工作站.bat` | Windows 一键启动脚本，`chcp 65001` 防乱码，零参数开箱即用 |
| API Key 持久化 | `/app/.claude_keys`（chmod 600），5 组 Key 独立存储，容器重启不丢失 |
| `karpathy-flow` 技能 | Andrej Karpathy 编码规范 skill，自动化入容器 |
| `devlog.md` | 开发日志，提升至项目根目录 |
| entrypoint 自动引导 | 无 Key 时启动 `claude` 自动重定向到 `claude-switch` |
| `claude` 包装器 | 重命名原版为 `claude-real`，包装脚本统一拦截：有 Key → 原版，无 Key → `claude-switch` |
| `AUTH_METHOD` 双通道 | Anthropic 官方用 `ANTHROPIC_API_KEY`，第三方平台用 `ANTHROPIC_AUTH_TOKEN` + 清空 `API_KEY` |
| Claude Code 启动绕过 | 预置 `config.json`（`hasCompletedOnboarding: true`）跳过首次联网验证 |

### 🔧 修复

| 项 | 说明 |
|----|------|
| Dockerfile — VPN 依赖 | 注入清华 apt 镜像源 + 淘宝 NPM 镜像源，国内网络无需 VPN 即可构建 |
| Dockerfile — `.claude/` 报错 | 不再 `COPY .claude/`（宿主机缺失时构建失败），改为镜像内生成默认 `settings.local.json` |
| entrypoint.sh — 覆盖风险 | 原逻辑缺文件就强覆盖，现改为仅首次运行注入，保护用户自定义配置 |
| entrypoint.sh — root 锁死 | 新增 `chown` 权限修复，自动检测宿主机 UID/GID 归还文件所有权 |
| entrypoint.sh — Shell | `#!/bin/sh` → `#!/bin/bash`，支持 `echo -e` 等特性 |
| Dockerfile — 工具链 | 补上 `sudo`、`tmux` |
| `claude-switch` — Anthropic 模型 | `claude-3-5-sonnet-20241022`（已退役）→ `claude-opus-4-8` |
| `claude-switch` — 硅基流动模型 | `Pro/deepseek-ai/DeepSeek-V3` → `Pro/deepseek-ai/DeepSeek-V4-Pro` |
| Claude Code — 国内无 VPN 无法启动 | 预置 `config.json` 跳过 onboarding + 第三方平台改用 `ANTHROPIC_AUTH_TOKEN` |
| `claude` 包装器 — 死循环 | 兼容 `ANTHROPIC_AUTH_TOKEN`，两个变量任非空即放行 |
| `claude-switch` — Anthropic 模型 | `claude-3-5-sonnet-20241022`（已退役）→ `claude-opus-4-8` |
| `claude-switch` — 硅基流动模型 | `Pro/deepseek-ai/DeepSeek-V3` → `Pro/deepseek-ai/DeepSeek-V4-Pro` |

### 📝 文档

- README.md 全面重写：5 大平台菜单、子菜单表格、claude-switch 详解

### 🗑️ 移除

- `docker_version/` 子目录清理，文件全部提升至项目根目录

### 📂 当前项目结构

```
.
├── Dockerfile
├── entrypoint.sh
├── claude-switch
├── 一键启动_AI工作站.bat
├── devlog.md
├── README.md
├── skills/
│   ├── claude.json
│   ├── karpathy-flow/SKILL.md     ← v1.1.0 新增
│   └── ... (20+ 技能)
├── .claude/
│   └── settings.local.json
├── .claude_keys                   (运行时生成)
└── todo/
    └── todo.md
```

---

## v1.0.0 (2026-06-25)

### 初始版本

- `node:20-slim` 基础镜像
- 全局安装 `@anthropic-ai/claude-code`
- 预配置 DeepSeek Anthropic 兼容 API（`ANTHROPIC_BASE_URL`、模型映射、effort）
- `claude.json` 全局配置（claude-hud + document-skills 插件）
- 20+ 预装技能库 → `/root/.claude/skills/`
- `entrypoint.sh` 入口脚本：自动注入项目级 `.claude/` 模板
- Windows SSH 端口代理配置（`setup-ssh-portproxy.ps1`）

### 已知问题

- [x] ~~无 VPN 时 `node:20-slim` apt/npm 安装失败~~ → v1.1.0 修复
- [x] ~~`.claude/` 缺失导致 Docker 构建报错~~ → v1.1.0 修复
- [x] ~~Skill 引入（andrej-karpathy-skills）~~ → v1.1.0 完成
- [x] ~~全局 claude-switch 命令~~ → v1.1.0 完成
- [ ] Termius SSH 配置文档未编写
