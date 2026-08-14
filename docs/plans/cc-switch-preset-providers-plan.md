# 计划：更新 cc-switch 预配置 Provider + 修复历史遗留问题

## 背景

`container/lib/cc_switch_preset_providers.py` 的 `PRESET_PROVIDERS` 信息大面积过时。联网核实（2026-08）确认：

- **DeepSeek**：`deepseek-chat` → `deepseek-v4-flash`/`v4-pro`；新增 Anthropic 端点 `https://api.deepseek.com/anthropic`
- **智谱 Zhipu**：`glm-4-plus` → `glm-5.2`（旗舰）；Anthropic 端点 `https://open.bigmodel.cn/api/anthropic`
- **Kimi**：`moonshot-v1-128k` → `kimi-k3`；Anthropic 端点 `https://api.moonshot.cn/anthropic`
- **codex-claude (codex.so)**：失效——codex.so 是 "CodeX Team"（JetBrains 开发者社区），`api.codex.so` 不可解析，非 Claude 供应商
- **Volcengine Ark**：仍为 endpoint-ID 模式；Anthropic 端点未能从文档确认

并发现两处结构遗留问题：
1. 单一 `base_url` 同时用于 claude（需 Anthropic 端点）和 codex（需 OpenAI 端点）agent，但三家供应商两种端点 URL 不同 → claude agent 实际不可用
2. codex 预置 `wire_api = "responses"`，第三方供应商只支持 Chat Completions，应为 `"chat"`

## 分支

从 `develop` 切 `fix/cc-switch-preset-providers`（用户已授权切分支）。

## 改动清单

### 1. `container/lib/cc_switch_preset_providers.py`（核心）

**a. `PRESET_PROVIDERS` 数据更新：**
- DeepSeek：`model` → `deepseek-v4-flash`；新增 `anthropic_base_url = "https://api.deepseek.com/anthropic"`；description 更新
- 智谱：`model` → `glm-5.2`；新增 `anthropic_base_url = "https://open.bigmodel.cn/api/anthropic"`；description 更新（"Z.ai/Zhipu GLM"）
- Kimi：`model` → `kimi-k3`；新增 `anthropic_base_url = "https://api.moonshot.cn/anthropic"`；description 更新
- Volcengine Ark：保持 `model = ""`（endpoint ID）；不加 `anthropic_base_url`（未确认，回退到 `base_url`，与现状一致不退步）
- **删除 `codex-claude` 整条**（codex.so 失效）

**b. `_settings_config(agent, provider)` 逻辑修正：**
- claude 分支：`ANTHROPIC_BASE_URL` 取 `provider.get("anthropic_base_url") or provider["base_url"]`（有 Anthropic 端点用之，否则回退）
- codex 分支：`wire_api = "responses"` → `"wire_api = "chat"`；删除 `disable_response_storage = true`（Responses API 专属，chat 模式无意义）；保留 `model_reasoning_effort`、`requires_openai_auth`

**c. `PRESET_FORMAT_VERSION` 2 → 3**（schema 变更，触发 revision 变化 → 新装自动应用新预置）

### 2. `tests/test_cc_switch_runtime.py`

- `test_presets_use_v5_schema_and_independent_agent_markers`：断言 `wire_api = "responses"` → `"wire_api = "chat"`；该测试用 `len(PRESET_PROVIDERS)` 动态计数，删 codex-claude 后自动适配（5→4），无需改计数
- 新增断言：claude settings 中 DeepSeek/智谱/Kimi 的 `ANTHROPIC_BASE_URL` 等于各自 anthropic 端点（验证 per-agent URL 修正）

### 3. `README.md`（Provider 快速配置段，约 247-294 行）

- 删除 `codex-claude` 预置说明行（256）与 `aisc switch --quick codex-claude` 示例（290）
- 更新各供应商描述（DeepSeek/智谱 GLM-5.2/Kimi k3 等措辞）
- 链接 `docs/provider-quick-setup.md` 实际已归档至 `docs/archive/`——本计划范围内顺手修正链接或标注（视情况）

### 4. `src/aisc/cli/main.py`（约 240 行）

- help 文本示例 `Provider ID (e.g., deepseek, codex-claude)` → 去掉 `codex-claude`，换 `zhipu` 或 `kimi`

### 不改动的文件

- `tests/test_provider_inspect.py`：其 `_DEEPSEEK_TOML` 等是 inspector 解析逻辑的测试夹具（codex/OpenAI base_url），不依赖预置数据，无需改
- `docs/archive/**`：归档历史文档，保持原样（含旧的 codex-claude/glm-4-plus 记录）
- `token_stats.py`：未跟踪的本地脚本，不动

## 验收清单（A-*）

- A-1：`PRESET_PROVIDERS` 含 4 条（deepseek/zhipu/kimi/volcengine-ark），无 codex-claude
- A-2：DeepSeek/智谱/Kimi 的 claude settings `ANTHROPIC_BASE_URL` 指向各自 `/anthropic` 端点
- A-3：codex settings 含 `wire_api = "chat"`，不含 `disable_response_storage`
- A-4：`PRESET_FORMAT_VERSION == 3`
- A-5：`python -m pytest tests/test_cc_switch_runtime.py` 全绿
- A-6：`python -m pytest tests/test_provider_inspect.py` 全绿（未受影响，回归确认）
- A-7：README / main.py 无 `codex-claude` 残留
- A-8：手动测试——在干净 cc-switch.db 上跑预置脚本，确认 4 条 provider 正确写入（claude + codex 各 4 条），claude 端点正确

## 验收结果（2026-08-14）

- A-1～A-7：PASS。`python -m pytest tests/test_cc_switch_runtime.py tests/test_provider_inspect.py`：53 passed、1 skipped。
- A-8：PASS。`CcSwitchProviderPresetTests` 在隔离的临时 cc-switch v5 数据库上 9/9 通过，覆盖 Claude/Codex 各 4 条预置、Anthropic endpoint、Codex chat wire API、既有配置刷新、API Key/当前选择保留及退休 provider 清理。

## 已知限制

- ~~`add_preset_providers` 是 add-only，现有用户不会自动更新。~~ 已由 `d571103` 解决：现有预置会原地刷新，同时保留 API Key、`is_current`、`in_failover_queue` 及非预置顶层字段；被用户复用的退休 ID 不会误删。
- Volcengine Ark 的 Anthropic 端点未确认：当前回退到 OpenAI base_url（与现状一致，不退步）。若后续确认 Ark 有 Anthropic 端点，再补 `anthropic_base_url`。

## commit 粒度

1. `fix(cc-switch): refresh preset provider models to 2026 latest (deepseek-v4-flash, glm-5.2, kimi-k3)`
2. `fix(cc-switch): drop invalid codex-claude preset (codex.so is not a provider)`
3. `fix(cc-switch): use per-agent base URLs + codex wire_api=chat for third-party providers`
4. `docs: update README/CLI help after preset provider refresh`

（实际合并时若 1+3 耦合可并为一个 commit，遵循最小单元化原则。）
