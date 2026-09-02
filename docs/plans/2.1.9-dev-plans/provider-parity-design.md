# Provider 页对标 cc-switch 桌面端——设计决策（provider-parity，2.1.9 周期）

> 状态：**用户裁决已齐，决策冻结待实施**。2026-09-02 五张桌面端截图实测 +
> 官方用户手册/changelog 调研 + 四点裁决。实施排期：opt-batch O6-O8 之后
> （用户当前批次优先），或用户点名提前。

## 背景与目标

手测反馈：provider 页与 cc-switch 的配置能力**不对等**（如 upstream format
无 UI）。目标：**UI 与功能完全对标 cc-switch 桌面端**（farion1231/cc-switch
v3.16.x 形态）——专属编辑页 + 简易/高级两档 + 卡片化列表。

## 用户裁决（2026-09-02，四点 + 一条边界）

| 决策点 | 裁决 |
|---|---|
| 长尾能力取舍 | **图标对等要做；端点测速不做**（备注/网站链接 db 列现成，一并纳入一期——见字段表） |
| 列表形态 | **完全卡片化**（对齐桌面端，弃表格） |
| codex 映射默认值 | **按 preset 预填**（model_catalog 全量预填，优于桌面端的手动添加） |
| 上游格式暴露 | **两侧都露**；claude 侧默认 `anthropic`，codex 侧默认 `openai_responses`（**而非** chat） |
| 边界 | **不做** cc-switch 的"自定义预设 JSON 编辑器"形态（保持表单化） |

## 桌面端参照（截图五张 + 手册要点）

- 主界面：左侧 agent 栏 + provider 卡片列表；当前项高亮"启用中"；未启用项
  悬浮浮现操作组（启用/编辑/删除）。
- 专属编辑页：← 返回 + 标题"编辑供应商 <名>" + 保存；页内**简易/高级两档**：
  - 简易 = 名称 + API 地址 + API Key（预设联动自动填）
  - 高级 = 上述 + **上游格式**下拉 + **模型映射**（claude 默认给三档角色映射；
    codex 可手动加）+ agent 专属项
- 上游格式语义（手册）：Anthropic Messages 原生直通 / OpenAI Chat /
  OpenAI Responses——非 Anthropic 需本地路由做协议转换。**映射与格式解耦**
  （v3.16.4 修正：原生 Responses 供应商要映射但不要转换）。
- 映射表：codex 三列（模型 ID / 显示名 / 上下文窗口）→ 生成 model catalog。

## 数据契约（与现状的对齐）

### 现有支撑（全部已在 db/adapter，仅缺 UI）

| 桌面端概念 | 我们的落点 | 现状 |
|---|---|---|
| 上游格式 | `row.meta.apiFormat`（preset `codex_api_format` 同源，`_db_merge_meta` 已读写） | ✅ 有数据，无 UI |
| claude 映射 | `settings.env` 五槽（`ROLE_SLOTS`：model/opus/sonnet/haiku/subagent） | ✅ UI 已有（弹层形态） |
| codex 映射 | `settings.modelCatalog.models[]`（`{model, contextWindow}`） | ✅ catalog-sync 在用，无编辑 UI |
| 备注 | `providers.notes` 列 | ✅ 列在 |
| 图标/颜色 | `providers.icon / icon_color` 列 | ✅ 列在 |
| 网站链接 | `providers.website_url` 列 | ✅ 列在 |

### apiFormat 枚举与默认值（本设计新钉）

```
"anthropic"        # 原生 Anthropic Messages（claude 侧默认）
"openai_chat"      # OpenAI Chat Completions（经本地路由转换）
"openai_responses" # OpenAI Responses（codex 侧默认；原生 Responses 供应商）
```

- 读侧优先级：`row.meta.apiFormat` → preset 声明 → 上述 agent 默认值。
- 写侧：edit patch 携带 `api_format` → `_db_merge_meta`（既有通道）。
- 联动提示（非阻断，对齐手册语义）：选非 anthropic 格式时提示
  "该格式经本地代理路由转换，保存后路由将启用"。

## 信息架构与组件

```
CcSwitchUiTab（改造）
├── 列表视图（默认）
│   ├── agent 切换条（现有）
│   ├── ProviderCard × N        ← 新组件（完全卡片化）
│   │   ├── 图标（icon/icon_color，缺省 = 首字符圆标）
│   │   ├── 名称 + 端点 + 当前徽章（启用中）
│   │   └── 悬浮操作组：启用（当前项=取消代理）/ 编辑 / 删除
│   └── 添加供应商（进入编辑页新增态）
└── 编辑视图（整页替换列表，非弹层）
    └── ProviderEditPage        ← 新组件
        ├── 头部：← 返回 | 添加/编辑供应商 <名> | 保存
        ├── 档位切换：简易 | 高级
        ├── 简易档：名称 + API 地址 + API Key（预设下拉联动自动填）
        └── 高级档：简易字段 +
            ├── 上游格式（三选一，双侧都露，默认值见上）
            ├── 模型映射编辑器 ModelMappingEditor ← 新组件
            │   ├── claude：三档角色行（Sonnet/Opus/Haiku → 上游模型）
            │   │   + 高级行（默认模型/子代理，折叠）——数据形状仍写五槽 env
            │   └── codex：三列表（模型 ID/显示名/上下文窗口）
            │       + preset 预填（裁决 #3）+ fetch 候选下拉（现有）
            ├── 备注 + 网站链接（文本字段）
            └── 图标选择（内置预设图形集 + 颜色，对齐桌面端图标库）
```

- 保存路径：全部走既有 `op_edit`/`op_add`（无新 CLI 面）；编辑器把
  映射/格式渲染回 patch 形状。
- **退出前未保存提示**（编辑页返回时 dirty 检查）——桌面端同款。

## adapter 变更（container/aisc-cc-provider）

1. `provider_view` 透出（secret-free）：
   `api_format`（读侧优先级见上）、`notes`、`website_url`、`icon`、
   `icon_color`、`model_catalog`（codex：`{models: [{model, contextWindow}]}`；
   claude 恒空）。
2. `_merge_patch` 白名单扩展：
   - `api_format` → `_db_merge_meta(agent, id, {"apiFormat": v})`
   - `notes` / `website_url` / `icon` / `icon_color` → providers 行更新
   - codex `model_catalog` → `settings.modelCatalog`（用户编辑优先；后台
     catalog-sync 的 deference 规则已兼容——用户 catalog 存在即接管）
3. `build_add_settings` 同步支持新字段（新增态一次成型）。
4. preset 联动数据（`_preset_provider`）：base_url/model_catalog/
   `codex_api_format` 全套已在——op_list 无需再补。

## 前端变更

- `types`：CcSwitchProvider 扩展六字段；CcSwitchRequest patch 同步。
- `stores/ccSwitchUi`：无新增 op（edit/add 复用）；编辑页视图态
  （`view: "list" | "edit"`、editingId、dirty）。
- 新组件：`ProviderCard`、`ProviderEditPage`、`ModelMappingEditor`
  （features/ccswitch/ 下，layer contract 照守——ipc 只经 store）。
- i18n zh/en 双语全量（上游格式/映射/档位/未保存提示等 ~20 键）。
- 移除：现 edit/add 弹层（被编辑页取代）；表格样式。

## 测试矩阵

- adapter pytest：apiFormat 读写优先级（meta > preset > 默认）、patch 白名单
  六字段、codex modelCatalog 写入 + catalog-sync deference 兼容、secret-free
  视图断言（新字段不泄 key）。
- vitest：卡片渲染（当前徽章/悬浮操作）、编辑页两档切换、claude 映射行 ↔
  五槽 env 往返、codex 映射三列 ↔ modelCatalog 往返、preset 预填、dirty 提示、
  保存路径 patch 形状。
- 手测：与 cc-switch 桌面端并排对照走查（新增/编辑/切换/映射生效于 /model）。

## 实施序列（建议）

P1 数据契约（adapter 字段+白名单+pytest）→ P2 编辑页（ProviderEditPage +
ModelMappingEditor + 两档 + preset 联动）→ P3 卡片列表（ProviderCard 替表格）
→ P4 打磨（dirty 提示/图标库/联动提示文案/手测矩阵）。

## 约束

- 继承 opt-batch §G 全局红线（层契约/SSOT/i18n/四矩阵/上游只绕不改）。
- 上游 db schema 不动（全部用既有列）；`meta.apiFormat` 沿 `_db_merge_meta`
  通道（delete/re-add 重置 meta 的坑已有 merge 补写先例——edit 后同补）。
- 图标资源：内置 SVG/emoji 集（不走网络图床）。
