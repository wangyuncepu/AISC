# Fine-Tune 可观察性与未配置引导

> 基线快照：commit `1f15f8bbb6beeee0e9a6af8a4daa3310ee02747a` 的 `docs/archive/gui-planning/04-observability.md`。  
> 继承清单：§三状态来源/所有权、§四 Runtime/Provider snapshot、§五刷新调度、§六 freshness/reducer、§七诊断通道、§八降级、§九可访问性。  
> 覆盖清单：归档 §二展示层级及与秒级相对时间绑定的实现以本文件用户层/详情层/G-12/无 ticker 规则为准。  
> 原则：用户层只展示有明确来源和行动价值的事实；开发者详情保留原始诊断字段。

## 一、现状问题

1. `RuntimeSidebar.vue` 的 1 秒 ticker 持续更新 `observed Xs ago`，造成整栏周期重渲染和视觉闪动。
2. freshness、observed、runtime/container ID、route/auth 原始值默认常显，信息偏开发者。
3. 状态缺少行动入口；Provider 未配置时用户不知道如何进入 cc-switch。
4. 当前 Provider 契约不含 model 字段，不能把 `provider_name` 描述成“当前模型名”。

## 二、展示分层

### 2.1 用户层（默认常显）

| 区域 | 内容 | 来源/规则 | 行动 |
|---|---|---|---|
| Workspace | basename；重名时可加父目录 | canonical workspace | 打开详情/复制路径 |
| Runtime | `运行中 / 已停止 / 不存在 / 无法确认 / 正在…` | 有效 Runtime observation | 刷新；合法时启动/停止/重启 |
| Provider | `provider_name`；无名称时显示状态文案 | 活动 Claude/Codex 的 Provider snapshot | 打开详情 |
| Auth | `已配置 / 需要登录 / 未配置 / 无法确认` | `auth_status` | 未配置时引导 cc-switch |
| Sessions | `n 个会话 · <活动 Session type>` | 当前 tab/pane registry | 激活对应 tab/pane |

规则：

- Bash/cc-switch 的 Provider 显示“不适用”。
- Provider capability 缺失显示“无法确认 · 需升级 CLI”，不得显示“未配置”。
- Runtime `stale` 时必须同时表达“上次已知”，不能继续显示确定性绿色运行中。
- 不显示契约中不存在的模型名；若未来增加 model，必须先扩展并版本化 CLI schema。

### 2.2 开发者详情（默认收起）

详情完整保留：

- runtime UUID、container name/ID、owner、config fingerprint；
- freshness、stale reason、相对和本地化绝对 observed time；
- image、network、scope、canonical workspace；
- provider ID/name、原始 route/auth；
- 最近 operation error 的稳定 code、run ID、exit code、脱敏 detail；
- 点击复制精确 ID/路径。

“分层”不等于删除字段。新增/删除字段需同步更新详情字段清单测试。

## 三、G-12 引导位置与行为

唯一主 banner 位于 **Claude/Codex 的 tab/pane 顶部**，不放在 RuntimeSidebar 顶部，以免把 Session-specific auth 误表达为 Runtime 全局状态。

侧边栏可以在活动 Claude/Codex 时显示短行动链接，但它不是第二个 banner。

状态规则：

| auth/capability | tab/pane 行为 |
|---|---|
| `configured` | 正常创建/运行 Session |
| `login_required` | 引导态；说明需要登录，按钮打开 cc-switch |
| `not_configured` | 引导态；说明未配置，按钮打开 cc-switch |
| `unknown` 或 capability 缺失 | 不创建 agent session；显示“无法确认”，提供重试/升级 CLI，不误导为未配置 |

「打开 cc-switch 配置」：

1. 查找当前 Runtime 内已有且未删除的 cc-switch tab/pane；有则激活。
2. 无则创建新的 cc-switch tab 并激活。
3. 不读取 Provider 密钥，不直接修改 Provider 配置。

## 四、刷新、Reducer 与无闪烁策略

Provider reducer 固定为：

| 输入 | 事实与 freshness | 新 Session 行为 |
|---|---|---|
| 有效 snapshot | 替换同 `(runtime_id, session_type)` 事实，fresh | 按 auth 决定 dormant/guide |
| poll/query error，有旧 snapshot | 保留旧事实，标 stale，并记录独立 operation error | 已运行 Session 不受影响；新 Claude/Codex 必须先刷新成功，不以 stale configured 自动启动 |
| poll/query error，无旧 snapshot | unknown | checking→guide(无法确认)，提供重试 |
| capability unsupported | unsupported/unknown + upgrade action | 不查询、不启动 Claude/Codex |

沿用归档基线的默认频率：

- 前台稳定 Runtime：每 5 秒 inspect；
- 活动 Claude/Codex Provider：每 15 秒；
- 控制操作中：最多每 2 秒 inspect；
- 失焦：Runtime 15 秒、Provider 60 秒；
- 最小化/suspend：暂停；恢复时先 stale 再立即刷新。

### 4.1 删除 ticker

- 删除 RuntimeSidebar 的 1 秒 `setInterval`。
- 相对时间仅在新 snapshot 提交、详情展开或用户手动刷新时重新计算。
- 详情同时显示绝对观察时间，因此相对时间无需秒级走动。

### 4.2 最小更新

- User layer 使用稳定的 semantic view model，例如：

```text
runtimeKey = state + freshness + actionableErrorCode
providerKey = runtime_id + session_type + provider_name + route_mode + auth_status + freshness
sessionsKey = ordered(tab_id/pane_id/state) + active IDs
```

- key 未变化时不替换对应 DOM 子树。
- `request_seq/revision` 继续阻止旧 observation 回退；UI 优化不得绕过 reducer。
- `aria-live` 只播报语义变化：状态、auth、操作结果；普通 poll/observed time 不播报。

## 五、文案与 i18n

以下状态必须同时有中英文键，不通过字符串拼接构造：

- Runtime state/freshness；
- Provider/auth；
- Session count（含复数/数量参数）；
- 引导 banner、按钮和重试/升级动作；
- 详情标签、复制成功和绝对/相对时间。

保留原始 code、route、auth 值时放在详情，以代码样式显示，不翻译其机器值。

## 六、可验证验收

### A-G05-1 无 1 秒更新

- RuntimeSidebar/其 composable 中不存在 1 秒 interval。
- 在 12 秒、无状态变化的前台轮询窗口中，用户层 Runtime/Provider/Sessions DOM 各自的内容 mutation 次数为 0；仅网络请求发生。

### A-G05-2 状态变化

- 注入 running→stopped observation 后，一个有效 poll 周期内用户层恰好更新为“已停止”；迟到 running response 被丢弃。
- stale 时同时显示“上次已知”和时间，不使用确定性 running 视觉。

### A-G05-3 详情完整性

自动化字段清单断言至少覆盖：runtime/container ID、image/network/scope、freshness/observed、provider/route/auth、operation error code；所有 ID/路径可复制。

### A-G12-1 引导可达

- 四种 Session type 始终出现在 `+` 选择器。
- `not_configured/login_required` 创建引导态，不调用 `open_session`。
- banner 按钮有已有 cc-switch 时激活，无时创建；Provider 配置后可从原 tab 启动新 Session。

### A-G12-2 未知态

capability 缺失或查询失败时显示 Unknown/升级或重试，不显示“未配置”，不读取任何密钥。

### A-G05-4 可访问性

状态不只依赖颜色；键盘可展开详情、触发引导和复制；普通 poll 不触发 `aria-live`。
