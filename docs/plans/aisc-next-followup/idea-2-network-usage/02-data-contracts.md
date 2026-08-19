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
  "url_masked": "https://provider.example/api/…?****",
  "fetched_at": "2026-08-19T12:34:56+08:00",
  "config_sha256": "sha256:3f2a…",
  "has_config_file": true,
  "userinfo": { … }        // 或 null
}
```

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

## 5. 用量数据面契约（⚠️ 2a 探针后冻结）

### 5.1 容器 adapter `usage` 操作（`aisc.cc-switch-provider/v1` 信封扩展）

- argv：`aisc-cc-provider usage --range today|7d|30d`（容器内只读 SQLite，
  照 `op_list` 快照模式；输出经既有 redaction）。
- data（**假设，2a 冻结**）：

```json
{
  "range": "7d",
  "generated_at": "2026-08-19T12:00:00Z",
  "available": true,
  "providers": [
    {
      "app": "claude",
      "provider_id": "deepseek",
      "provider_name": "DeepSeek",
      "requests": 123, "success": 120, "failed": 3,
      "tokens_total": 1234567,
      "cost_estimate": 1.23, "currency": "USD"
    }
  ],
  "models": [
    { "app": "claude", "model": "deepseek-v4-flash", "requests": 120,
      "tokens_in": 100000, "tokens_out": 5000 }
  ]
}
```

- `available=false`：usage 表缺失/空库/版本不符 → `ok=true` + 空数据
  （面板显示「暂无数据」，不报错）。
- provider 归属口径：cc-switch 自身逻辑（代理请求日志精确归属 + 会话扫描
  导入）；官方直连流量归属有限，面板附口径说明。

### 5.2 宿主 `aisc usage overview --format json`

- argv：`aisc usage overview [--range today|7d|30d] [--workspace <path>]`
  （默认 7d；`--workspace` 限定单工作区，默认聚合全部）。
- data：

```json
{
  "subscription": { …§4 同构… },
  "workspaces": [
    {
      "workspace_hash": "sha256-v1-…",
      "workspace_path": "C:\\Users\\…\\proj",
      "running": true,
      "source": "live",
      "fetched_at": "2026-08-19T12:00:00+08:00",
      "providers": [ …5.1 行同构… ],
      "models": [ … ]
    }
  ],
  "totals": {
    "providers": [ …跨工作区同名 provider 聚合行… ],
    "tokens_total": 0, "requests": 0, "cost_estimate": 0.0
  }
}
```

- `source`: `live`（容器运行中，adapter 实时取，顺手写缓存快照）|
  `cache`（容器停止，读 `<data-root>/cache/usage/<ws-hash>.json`）|
  `none`（无缓存）。
- 时间范围语义：`today`=本地自然日 00:00 起；`7d`/`30d`=`now - N*24h` 起
  （与 cc-switch 用量页对齐；2a 探针确认其对齐方式后冻结）。

### 5.3 Rust 侧

- Tauri 命令：`network_subscription_import`（stdin 通道传 URL，走
  `run_control_input`）/ `network_subscription_refresh` / `network_subscription_clear`
  / `usage_overview(range, workspace?)`（`run_control`，**超时 120s**——多容器
  逐个 exec）。
- argv builder 纯函数 + 内联测试（照 `cc_switch_argv` 模式）。

## 6. 2a 探针清单（冻结前必做）

1. **cc-switch.db usage 表**（live 容器 `docker exec … python3 sqlite3`）：
   - `SELECT name FROM sqlite_master WHERE type='table'` 全表清单；
   - usage/请求/会话相关表逐一 `schema` + 行数 + 5 行脱敏样例；
   - 时间戳存储形态（epoch 秒/毫秒/ISO）、provider 关联方式（id/name/外键）、
     token 字段拆分（in/out/cache_read/cache_create）、费用与币种字段；
   - `app`（claude/codex）区分字段；定价表（180 行）结构。
2. **真实订阅行为**（用户机场链接，手测一次）：UA 门控返回格式；
   `subscription-userinfo` 是否存在及字段齐度；重定向行为。
3. 产出：本文 §5 改写为冻结版 + `tests/fixtures/` 增加 usage schema/样例
   fixture + `container/lib/` 如需 cc-switch usage 事实 fixture 一并落。
