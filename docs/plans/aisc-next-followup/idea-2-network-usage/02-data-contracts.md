# IDEA-2 数据契约（初版）

> 状态：**初版（2026-08-19）**。订阅侧（§1-§4）随 2b 实现微调；
> **usage 侧（§5）全部字段为假设，2a 探针轮冻结**——探针前不得照此写死
> adapter/聚合代码。

## 0. 存储布局（数据根）

```
<data-root>/config/mihomo/subscription.yaml        # 原始订阅文件（下载原样，挂载源）
<data-root>/config/network-subscription.json       # 订阅快照（含完整 URL，refresh 用）
<data-root>/cache/usage/<ws-hash>.json             # 各工作区用量缓存快照
```

- `subscription.yaml` 即挂载到 `/etc/mihomo/config.yaml` 的文件（`start_runtime`
  自动解析的目标；容器内 `mihomo-build-config.js` 负责转换，宿主不改内容）。
- 完整 URL 只落 `network-subscription.json`（数据根在 `%LOCALAPPDATA%`，不入
  repo、不入诊断包）；一切信封/UI 输出一律脱敏。

## 1. 订阅快照文件 `network-subscription.json`

```json
{
  "schema": "aisc.network-subscription/v1",
  "url": "https://provider.example/api/v1/client/subscribe?token=SECRET",
  "fetched_at": "2026-08-19T12:34:56+08:00",
  "config_sha256": "sha256:3f2a…",
  "userinfo": {
    "upload": 1638257504,
    "download": 13418441583,
    "total": 1073741824000,
    "expire": 1750000000
  }
}
```

- `url`：完整原始 URL（refresh 数据源）。
- `userinfo`：可整体缺失（响应无 `subscription-userinfo` 头）；字段可部分
  缺失（`expire` 常缺；`total=0` = 不限量，原样存 0，展示层解释）。
  数值一律非负整数原样透传（字节 / Unix 秒），换算归展示层。
- `config_sha256`：`subscription.yaml` 内容哈希（调试/显示用；fingerprint
  以 start 时对实际解析文件现算为准，不信任快照缓存值）。

## 2. userinfo 头解析规则

- 头名大小写不敏感（HTTP 侧由 transport 归一为
  `Subscription-Userinfo`）；取首个出现，多头不合并。
- 值为 `;` 分隔的 `k=v` 对；逐对 strip 空白；仅认
  `upload|download|total|expire` 四键，值为非负十进制整数，其余键/畸形对
  忽略；空结果 → `userinfo: null`。

## 3. 下载 transport 契约

- urllib 可注入 transport（照 `cc_switch_resolver.default_transport` 模式，
  测试注入伪 transport）。
- `User-Agent`：`clash-verge/v2.2.0 (aisc)`（常量；订阅服务按 UA 门控返回
  Clash 格式，不用 curl/python 默认 UA）。
- 超时 30s/次；`URLError`/超时重试 1 次；HTTP 4xx 不重试（错误带状态码）；
  5xx 重试 1 次。
- 响应体非空（≥1 字节）才算成功；落盘用临时文件 + `os.replace`（同卷原子）。
- 稳定错误码：`AISC_ERR_NETWORK_SUBSCRIPTION_FETCH`（网络/5xx 重试后仍败）、
  `AISC_ERR_NETWORK_SUBSCRIPTION_HTTP`（4xx，message 带状态码，不含响应体）、
  `AISC_ERR_NETWORK_SUBSCRIPTION_INVALID_URL`、
  `AISC_ERR_NETWORK_SUBSCRIPTION_NOT_CONFIGURED`（refresh/clear 时无快照）、
  `AISC_ERR_NETWORK_SUBSCRIPTION_EMPTY`（200 空体）。

## 4. `aisc network subscription` 信封 data 形状

`import`（URL 走 **stdin**，不进 argv）/ `refresh` / `show` 成功后统一返回：

```json
{
  "configured": true,
  "source": "download",
  "url_masked": "https://provider.example/api/…?****",
  "fetched_at": "2026-08-19T12:34:56+08:00",
  "config_sha256": "sha256:3f2a…",
  "has_config_file": true,
  "userinfo": { … },        // 或 null
  "config_path": "C:\\…\\subscription.yaml"
}
```

- `source`: `download`（URL 拉取）| `manual`（内容导入/legacy 采用，无 URL）。
- `config_path`：落盘绝对路径（非机密）；其余调用无此键。
- `clear --confirm` 成功 → `{"configured": false}`。
- 脱敏规则（Python 侧确定性实现）：保留 `scheme://host`；路径截前 8 字符接
  `…`；有 query 则替换为 `****`；fragment 丢弃。
- `url_masked` 是信封与 UI 的**唯一** URL 形态。

### fingerprint 扩维（D1，随 2b）

```
compute_config_fingerprint(image, network, scope, workspace, proxy_config_sha256=None)
canonical = {"image":…, "network":…, "scope":…, "workspace":…}
if network == "proxy":
    canonical["proxy_config_sha256"] = proxy_config_sha256 or ""   # "" = 无配置
```

- direct 模式 canonical 与现状**字节级一致**（无新键）→ 存量 direct 容器
  零冲突（测试钉死）。
- proxy 模式：无配置 ↔ 有配置 ↔ 内容变化，三者指纹互异 → 订阅刷新后下次
  start 判 runtime_conflict，走既有重建引导。

### legacy 采用（一次性，只读源不动）

- 触发：数据根 `config/mihomo/subscription.yaml` 不存在 且
  `<aisc_root>/.claude/mihomo/config.yaml` 存在 → 拷贝（不移动、不改源）。
- 采用发生在 start_runtime 自动解析与 `subscription show` 时（幂等：目标
  存在即跳过）；`aisc build` 向导步骤 2b 起改写新路径。

## 5. 用量数据面契约（✅ 2a 探针冻结：2026-08-19，宿主侧 db 副本实探）

### 5.0 实测 schema（cc-switch v5.10.1，schema v16）

数据源裁定：**adapter 只聚合 `proxy_request_logs`**（逐请求事实表，全部
`data_source` 来源一并统计）；`usage_daily_rollups` 为上游自身缓存（新鲜度
语义未知，不读）；`session_log_sync`/`session-scan-cache.db` 为扫描断点状态
（不读）。

```sql
-- 逐请求事实表（数据落点；data_source 区分 'proxy' 直录 vs 会话扫描导入）
CREATE TABLE proxy_request_logs (
  request_id TEXT PRIMARY KEY, provider_id TEXT NOT NULL,
  app_type TEXT NOT NULL,             -- 'claude'|'codex'|'gemini'|'grokbuild'
  model TEXT NOT NULL, request_model TEXT, pricing_model TEXT,
  input_tokens INT, output_tokens INT,
  cache_read_tokens INT, cache_creation_tokens INT,
  input_token_semantics INT DEFAULT 0,
  input_cost_usd TEXT, output_cost_usd TEXT,
  cache_read_cost_usd TEXT, cache_creation_cost_usd TEXT, total_cost_usd TEXT,
  latency_ms INT, first_token_ms INT, duration_ms INT,
  status_code INT, error_message TEXT, session_id TEXT,
  provider_type TEXT, is_streaming INT DEFAULT 0,
  cost_multiplier TEXT DEFAULT '1.0', created_at INT NOT NULL,
  data_source TEXT NOT NULL DEFAULT 'proxy'
);
-- 名称映射
CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT, settings_config TEXT, …,
  is_current BOOLEAN, PRIMARY KEY (id, app_type));  -- settings_config 含密钥：永不 SELECT
-- 定价（费用已在日志行内预计算，无需 join 此表）
CREATE TABLE model_pricing (model_id TEXT PRIMARY KEY, display_name TEXT,
  input_cost_per_million TEXT, output_cost_per_million TEXT,
  cache_read_cost_per_million TEXT, cache_creation_cost_per_million TEXT);
```

实测补充事实：
- live 库中 `proxy_request_logs`/`usage_daily_rollups` **0 行**（容器 08-18
  重建后无走代理流量；schema 完好）。2c 手测时打一发真实请求验证落库与
  `created_at` 单位后，adapter 的时间过滤按实测单位固化。
- `providers` 表 `settings_config` 含 API 密钥——adapter 侧只 SELECT
  `id, app_type, name`，其余列不触碰（redaction 纪律）。
- 成功判定（我们自己的口径）：`status_code BETWEEN 200 AND 299`。
- `tokens_total`（真实消耗）= `input+output+cache_read+cache_creation`（与
  cc-switch 用量页归一化口径一致）。
- 费用 = SUM(`total_cost_usd`)（TEXT 十进制，容器侧转 float 求和，展示层
  保留 4 位）；币种恒 USD。

### 5.1 容器 adapter `usage` 操作（`aisc.cc-switch-provider/v1` 信封扩展）

- argv：`aisc-cc-provider usage --range today|7d|30d`（容器内只读 SQLite，
  照 `op_list` 快照模式；输出经既有 redaction）。
- data（冻结）：

```json
{
  "range": "7d",
  "generated_at": "2026-08-19T12:00:00Z",
  "available": true,
  "providers": [
    { "app": "claude", "provider_id": "deepseek", "provider_name": "DeepSeek",
      "requests": 123, "success": 120, "failed": 3,
      "tokens_total": 1234567,
      "cost_estimate": 1.2345, "currency": "USD" }
  ],
  "models": [
    { "app": "claude", "model": "deepseek-v4-flash", "requests": 120,
      "tokens_in": 100000, "tokens_out": 5000,
      "cost_estimate": 0.5678 }
  ]
}
```

- `available=false`：表缺失/版本不符 → `ok=true` + 空数组（面板「暂无数据」，
  不报错）；表存在但 0 行 → `available=true` + 空数组（正常态）。
- provider 归属口径：cc-switch 自身（代理日志精确 + 会话扫描导入）；官方直连
  流量归属有限，面板附口径说明。
- 聚合 SQL 一次往返（GROUP BY provider_id, app_type / GROUP BY model, app_type），
  `created_at` 时间下界按 range 换算（单位以 2c 实测为准）。

### 5.2 宿主 `aisc usage overview --format json`

- argv：`aisc usage overview [--range today|7d|30d] [--workspace <path>]`
  （默认 7d；`--workspace` 限定单工作区，默认聚合全部）。
- data（冻结）：

```json
{
  "subscription": { …§4 同构… },
  "workspaces": [
    { "workspace_hash": "sha256-v1-…", "workspace_path": "C:\\Users\\…\\proj",
      "running": true, "source": "live",
      "fetched_at": "2026-08-19T12:00:00+08:00",
      "providers": [ …5.1 行同构… ], "models": [ … ] }
  ],
  "totals": {
    "providers": [ …跨工作区按 (app, provider_id) 聚合行… ],
    "tokens_total": 0, "requests": 0, "cost_estimate": 0.0
  }
}
```

- `source`: `live`（容器运行中，adapter 实时取，顺手写缓存快照）|
  `cache`（容器停止，读 `<data-root>/cache/usage/<ws-hash>.json`）|
  `none`（无缓存）。
- 时间范围语义：`today`=本地自然日 00:00 起；`7d`/`30d`=`now - N*24h` 起。

### 5.3 Rust 侧

- Tauri 命令：`network_subscription_import`（stdin 通道传 URL 或内容，走
  `run_control_input`）/ `network_subscription_refresh` / `network_subscription_clear`
  / `usage_overview(range, workspace?)`（`run_control`，**超时 120s**——多容器
  逐个 exec）。
- argv builder 纯函数 + 内联测试（照 `cc_switch_argv` 模式）。

## 6. 订阅源传输契约修订（⚠️ 2a 探针实测：2026-08-19，用户真实机场链接）

### 6.1 实测行为矩阵（103.14.76.98，IP 直连 HTTPS 订阅）

> ⚠️ **2026-08-19 晚复核勘误（挂账① 落地时）**：原矩阵「真 Chrome headless 通过」
> 系**误读**——dump-dom 捕获的 190KB "JS 壳 HTML" 实为 Chrome 自带的
> `ERR_CONNECTION_CLOSED` 报错页（Lit 模板，两种 UA 下均同尺寸仅 nonce 异），
> Chrome 当时即已被掐。且该源防护在 8/17→8/19 间进一步收紧：clash-verge
> 自身的三级更新（直连→Clash 代理→系统代理，reqwest+rustls）8/17 12:50 经
> 第二级成功拿到 userinfo 头（profiles.yaml `extra` 为证），8/19 12:15 与
> 16:18 两轮**全灭**（verge 日志原文「所有重试均已失败」）。v1.2.3 时代
> （2026-07）宿主 curl.exe 直拉订阅可用——该墙为后加且动态变化。

| 客户端栈 | 路径 | 结果（8/19 晚实探） |
|---|---|---|
| 直连 443 | 任意 | **TCP 拒绝**（os error 10061） |
| HTTP 80 | clash UA | 308 → 同址 https（无 http 回退） |
| curl(schannel)（经 7890 代理 CONNECT） | clash UA，tls1.1/1.2/1.3 各档 | **全灭**（无响应） |
| reqwest+rustls(ring)（经 7890） | clash UA | **TLS handshake EOF**（错误链实证） |
| 真 Chrome headless（经 7890） | 浏览器/clash UA | **ERR_CONNECTION_CLOSED**（见上勘误） |
| clash-verge 自身更新器 | 三级全试 | 8/19 **全灭**；8/17 第二级（自身 mihomo）可过 |
| 同机场域名端点（http://，经 7890） | curl + clash UA | **通过**：200 + 真实 `Subscription-Userinfo` 头 + 114KB yaml |

结论（修订）：该机场 IP 源的墙是**动态收紧的黑名单/风控**（8/19 状态：一切
客户端栈含 clash-verge 与浏览器皆灭），非可通过栈形状工程绕过的静态 JA3 白
名单；其**域名 http 端点**对一切栈开放。工程含义：下载器按「clash 家族栈形
状」（reqwest+rustls + clash UA + WinINET 系统代理）实现——墙回落到
clash-verge 可过的档位时本传输自动受益；全杀档位下逐级降级（Python 传输 →
粘贴导入），不误伤可用性。

### 6.2 契约修订：URL 与内容双导入（D4，2026-08-19）

- `aisc network subscription import`：stdin=URL（原设计不变，适用于无指纹
  防护的源：自建 subconverter、多数面板）。
- **新增 `aisc network subscription import-file`**：stdin=完整订阅内容
  （任意格式，`mihomo-build-config.js` 全都能转）→ 落盘 `subscription.yaml`，
  快照 `source: "manual"`、`url: null`、`userinfo: null`。文件/粘贴路径，
  指纹防护源的保底通路。
- 快照 schema v1 增字段：`"source": "download" | "manual"`。
- 新增稳定错误码 `AISC_ERR_NETWORK_SUBSCRIPTION_TLS_REJECTED`：transport 捕获
  握手期 EOF/连接重置类 SSL 错误时映射（区别于网络不可达）→ UI 引导「该订阅
  源拒绝自动化下载，请改用粘贴配置内容导入」。
- SubscriptionForm（UI）双模式：订阅链接输入 + 粘贴配置内容文本域。
- **挂账（指纹防护源的自动下载）——2026-08-19 已落地（挂账①）**：Rust 侧
  下载器上线：`workbench/src-tauri/src/subscription.rs`（reqwest+rustls、
  clash 家族 UA、WinINET/环境双探测系统代理、30s+1 重试、10MB 上限、宽容自
  签证书；捕获 `subscription-userinfo` 头）→ 经 stdin JSON（b64 内容）交给
  新 CLI op `network subscription store-downloaded`，持久化/脱敏/假节点兜底
  全留 Python。import/refresh 命令改为「Rust 下载优先，失败回落 Python 传输」。
  墙态勘误与实探矩阵见 §6.1 修订。

### 6.3 2a 探针清单执行状态

- [x] cc-switch.db usage 表结构/行数/落点（宿主副本实探，§5.0）；
- [x] 真实订阅源连通性/UA/TLS 行为（§6.1 矩阵；userinfo 头未实测）；
- [ ] `created_at` 单位 + 首行真实数据落库验证（2c，镜像重建后打真实请求）；
- [ ] fixtures：usage schema/样例（2c 随 adapter 测试落 `tests/fixtures/`）。
