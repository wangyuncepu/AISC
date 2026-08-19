# IDEA-5 + KI-7 实施计划：Provider 管理打磨

> 状态：已规划（2026-08-19 用户批准）。分支 `idea-5-ki7-provider-polish`。
> 阶段 5a..5e；每阶段最小 commit + 先报后做 + 手测门禁；收口 `--no-ff` 合并 + 四 CI。

## 1. 背景与决策

IDEA-5（provider 打磨：①模型映射 ②切换视觉反馈）合并 KI-7（IDEA-2 手测发现：
①自定义添加报 `unknown preset provider` ②外部 cc-switch 改动不同步）。

用户拍板（2026-08-19）：**映射入口=编辑表单内嵌五槽**（claude 侧；codex 单模型位
不适用）；**切换反馈=行高亮脉冲 + chip 平滑过渡 + 顶部浮动 toast**（保留 aria
播报；遵循 reduced-motion）。

## 2. 已核实事实

1. **KI-7① 根因**：`main.py:304` `--mode default="simple"` + Rust 从不传 `--mode`
   → `cc_switch.py:61` 的 stdin 文档 `"mode":"custom"` 被 argparse 默认值覆盖 →
   adapter 按 simple 走 `_preset_provider("")` 报错。全链路其余环节正确；该行
   零测试覆盖。
2. **KI-7② 根因**：CcSwitchUiTab 仅 onMounted 一次性拉 list；useProviderPolling
   只覆盖 provider current；面板 v-show 常驻不重挂载 → 外部改动不可见。
3. **五角色位 ↔ env 键**：MODEL/OPUS/SONNET/HAIKU/SUBAGENT ↔
   `ANTHROPIC_MODEL` / `ANTHROPIC_DEFAULT_OPUS_MODEL` /
   `ANTHROPIC_DEFAULT_SONNET_MODEL` / `ANTHROPIC_DEFAULT_HAIKU_MODEL` /
   `CLAUDE_CODE_SUBAGENT_MODEL`。上游只给 MODEL 会外溢同值 → **保存必须五键
   全显式写**（空值→null 删键走服务端别名兜底）。`[1m]` 后缀仅 MODEL/OPUS/SONNET。
4. **编辑链路 wire 已支持 env 端到端**（adapter `_merge_patch` 的 `patch.env`
   + TS 类型已有）；缺快照脱敏 env 视图（全量 env 含 AUTH_TOKEN）与 UI。
5. **fetch-models 上游存在**（`cc-switch -a <app> provider fetch-models [ID]`，
   无 --json）；实机 DeepSeek 探测 `{base}/v1/models` 得 **401** → 数据源三级
   降级（拉取 ∪ known_models ∪ 手动输入）；成功态格式未知（GitHub 代码搜索要
   登录）→ 防御式解析 + 5c 手测实测后冻结。
6. **Ownership**：deepseek 预置 `claude_env`+`_env_history` 机制用户覆盖存活；
   **legacy 预置（zhipu/kimi/volcengine）的 ANTHROPIC_MODEL 刷新时被无条件
   覆盖** → 需扩展 history 机制，否则映射覆盖会被清。
7. 预置默认集：deepseek 全五键；zhipu/kimi 仅 MODEL（glm-5.2/kimi-k3）；
   volcengine 无模型键。

## 3. 阶段设计

### 5a KI-7① 自定义添加修复（快赢）
- `main.py` `--mode` 改 `default=None`（stdin 文档的 mode 生效，缺省 simple）。
- 测试：CLI 层（FakeExec 模式构造 args+stdin 断言 custom 存活）+ UI 层自定义
  添加用例（现只有 simple）。

### 5b KI-7② 外部同步
- CcSwitchUiTab watch 面板可见性 false→true 即 `ui.list()`（busy 守卫复用）；
  不加定时轮询。测试：可见性翻转断言重拉。

### 5c 数据面
- adapter `provider_view`（claude）加脱敏 `role_env`（五键+EFFORT_LEVEL+
  BASE_URL 白名单，永不吐 AUTH_TOKEN）与 `known_models`（预置行 `_env_history`
  并集；自定义行空）。
- adapter 新 op `fetch-models --agent claude --id <pid>`：`_cli` 跑上游（stdout
  一律 redact），防御式解析模型 id；失败（401 等）→ ok=true + available=false
  + message 透传提示。
- 宿主：`aisc cc-switch` 组加 `fetch-models` 子命令（`_OPS` 扩 + 走
  `_exec_adapter`）；Rust `cc_switch_fetch_models`（复用 cc_switch_argv 模式）
  + lib.rs + ipc 绑定。
- legacy ownership 修复：zhipu/kimi/volcengine 的 `ANTHROPIC_MODEL` 建
  `_env_history`，刷新改走 `_merged_claude_env`（覆盖存活/默认升级保留）。
- 测试：adapter seeded-db（白名单/known_models/解析降级/redaction）+ 宿主
  FakeExec + ownership legacy 用例。

### 5d UI
- 编辑表单（claude）内嵌五槽：预填 `role_env`；保存五键全显式（空→null 删键）；
  `[1m]` 脚注。
- `<datalist>` 三级降级下拉（拉取按钮结果 ∪ known_models ∪ 现值）；拉取失败
  提示条 + 手动输入兜底。
- store `fetchModels(pid)` action（F-A01：组件零直接 ipc）。
- 切换反馈三件套：新当前行脉冲 keyframe（~1.2s）+ `.cur.on` transition +
  横幅升级顶部浮动 toast（Teleport + zoom 补偿照 TabBar 模式，保留
  role=status）；`prefers-reduced-motion` 全退化即时。
- i18n 双语 ~25 键；测试：patch.env 构造（全显式/删键）、datalist 合并、
  flash 类、reduced-motion、parity。

### 5e 收口
手测矩阵 + todo.md 闭环 + `--no-ff` 合并 + 四 CI。

## 4. 手测矩阵（5e）

自定义添加（真实供应商）成功；bash TUI 改动回面板即见；五槽保存→容器内
settings.json 五键正确、切 HAIKU 位聊天验证生效；拉取模型（DeepSeek 预期 401
降级 + 手动输入）；zhipu 覆盖 MODEL 后容器重启覆盖存活；切换动效三件套 +
reduced-motion 退化；codex 侧无映射 UI 回归。

## 5. 风险与缓解

1. fetch-models 成功格式未知 → 防御解析 + 降级 + 手动兜底；实测后冻结。
2. 五键显式写 × 上游外溢 → 手测切 HAIKU 位验证。
3. ownership 扩展改刷新行为 → 既有套件全保 + legacy 新用例。
4. toast × CSS zoom → 照 TabBar zoom 补偿模式。

## 6. 验证纪律

每阶段 python 全测 / vitest / vue-tsc /（涉 Rust 时）cargo --lib；改
`container/` 后 `tools/vendor-refresh.sh`（python3 shim 前置）；改 Python 源后
`scripts/build-cli.ps1` 重建 sidecar 同步 `binaries/`+`target/debug/`；收口四 CI。
