# Spike：codex 模型目录实时化（S9 候选）

> 2026-08-29 · 触发：用户问「每次都要随提供方更新手动追吗？不能实时吗？」（glm-5.2→5.3 追版本之痛）
> 结论：**可行且成本低**——拉取机制已在同一文件内，只差在 switch 钩子里接线。

## 现状代码事实（container/aisc-cc-provider）

| 组件 | 位置 | 现状 |
|---|---|---|
| 目录写盘钩子 | `_apply_codex_model_catalog(row)`（switch 后同步执行） | 目录来源优先级：行内 `settings.modelCatalog`（TUI 映射，**完全让位**）→ 预置 `model_catalog` → live `model` 行兜底；写 `~/.codex/aisc-model-catalog.json` + 注入 `model_catalog_json` |
| HTTP 抓取 | `_http_get_json(url, headers, timeout)`（**可注入 seam，测试既用**） | 仅被 `op_fetch_models` 使用 |
| URL 候选链 | `_models_url_candidates(base)`（上游 model_fetch.rs 移植：`/models`→`/v1/models`→anthropic 后缀剥根双探） | 同上 |
| 模型列表解析 | `_openai_compatible_models(base, key)` → `list[str] \| None` | 同上 |
| 现消费方 | `op_fetch_models` | 只喂 **claude 侧映射下拉**（base=ANTHROPIC_BASE_URL，key=AUTH_TOKEN） |
| codex 侧凭据 | 行 `settings.auth.OPENAI_API_KEY`（或 TOML api_key 镜像） | switch 时进程内可得 |
| codex base | 行 TOML `[model_providers.<id>].base_url`（tomllib 已可用） | 需解析一次 |

## 设计：switch 时实时合成目录

在 `_apply_codex_model_catalog` 组装完静态 `models` 后（且未触发 TUI 完全让位分支）：

1. **取数**：解析行 TOML 得 codex base_url + 行 auth 取 key → `_openai_compatible_models(base, key)`（超时 5s；无 key / 离线 / 401 → **fail-open 落回静态目录**，行为同今天）
2. **合并**：预置行原序原窗口在前；拉到的 id 去重后追加，`contextWindow` 沿用首行窗口（**各家 1M 级的族假设**，volcengine 兜底 128k）
3. **护栏**：追加条目上限 50；轻度垃圾过滤（embedding/whisper/tts/moderation/rerank/dall-e 子串剔除）；**只写生成的文件、永不回写 db 行**——预置所有权刷新与 TUI 映射优先级全部不变
4. **TUI 让位**：检测到 cc-switch 自家目录接管时直接 return（现状逻辑），不做实时合并

### 效果

- glm-5.4 / kimi-k4 / relay 新型号 → `/model` 自动出现，预置表只负责「出厂底线 + 准确首选」，不再追版本
- claude 侧映射下拉本就实时（IDEA-5），无改动

### 已知边界（如实告知用户）

- **contextWindow 拉不准**：`/models` 端点普遍只回 id；新 id 沿用族窗口，仅影响 codex 的 token 计量显示/压缩触发时机，不影响可用性
- 首次切换 +1 次 GET（5s 超时上限）
- 部分中转（如 cc.codesome.ai 未证实有 /models）→ fail-open 静态目录

### 测试面

`_http_get_json` seam 注入（既有模式）：合并去重 / TUI 让位跳过 / 无 key 跳过 / 垃圾过滤 / 上限 / 失败回退。

### 备选（否决）

- 构建期烘焙：仍是静态 ✗
- 常驻后台轮询：复杂度不值 ✗
- UI 手动「刷新模型列表」按钮：可作为后续补充，非本题 ✗

## 规模

集中在 `_apply_codex_model_catalog` + 一个合并纯函数 + 测试；约半天。
