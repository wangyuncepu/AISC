# Stage 10 Token 映射表（10b）

> 用途：新旧 token 对照 + 兼容别名处置计划。
> 生命周期（已闭环）：10b 定义别名 → 10c/10d 迁移组件 → **10f（`62f5361`）别名全部删除**，最后使用者 OnboardingWizard --muted 迁正 --text-muted。

## 1. 旧名 → 规范名（别名已生效）

| 旧名（组件在用） | 规范 token | 使用处（迁移对象） |
|---|---|---|
| `--muted` | `--text-muted` | OnboardingWizard、WorkspaceExplorer |
| `--text-dim` | `--text-muted` | NetworkUsageTab、SubscriptionForm |
| `--text-1` | `--text` | WorkspaceBar（原为裸引用，无 fallback） |
| `--danger` | `--error` | NetworkUsageTab、SubscriptionForm |
| `--accent-text` | `--accent-fg` | SubscriptionForm |
| `--accent-dim` | `--accent-soft` | WorkspaceExplorer |
| `--warn-dim` | `--warn-soft` | WorkspaceExplorer |
| `--mono` | `--font-mono` | SubscriptionForm |

## 2. 新增语义 token（10b 首次定义）

| token | 用途 | dark / light |
|---|---|---|
| `--accent-soft` | 强调色淡底（badge、segmented 选中、行选中） | `rgba(74,158,255,.25)` / `rgba(14,99,156,.12)` |
| `--success-soft` / `--warn-soft` / `--error-soft` / `--info-soft` | 状态淡底族（chip/badge/selected） | 见 styles.css |
| `--scrim` | dialog/drawer 遮罩 | `rgba(0,0,0,.55)` / `rgba(0,0,0,.32)` |

## 3. 新增非语义族（10b 首次定义）

| 族 | token |
|---|---|
| line-height | `--leading-tight/normal/relaxed` |
| mono 字体 | `--font-mono`（仅 UI chrome；终端字体走 `terminal.font_family` 设置，不读此 token） |
| control 高度 | `--control-h-sm(26)/md(32)/lg(38)`——D10-14 大命中区 |
| border 宽度 | `--border-w(1)/--border-w-strong(2)` |
| focus ring | `--focus-ring-width(2)/--focus-ring-offset(2)` |
| duration | 补 `--duration-slow(300ms)`（drawer/dialog 进出场） |
| spacing | 补 `--space-5(20)/--space-10(40)` |

## 4. 既有 token 改值（D10-14 iOS 取向，全局生效）

| token | 旧值 | 新值 |
|---|---|---|
| `--radius-sm` | 2px | 6px |
| `--radius-md` | 4px | 10px |
| `--radius-lg` | 6px | 14px |
| `--radius-xl` | （新增） | 20px |

radius 改值是 10b 唯一全局视觉跳变；暗/亮两套同改。试点页验收时确认无小尺寸控件变形（badge/小 chip 若过圆，在组件侧换 `--radius-sm`）。

## 5. 定义了但当前无引用（保留，族完整性）

`--space-1/4/6/8`、`--shadow-2`、`--duration-normal`——族完整性保留，Primitive 起用。
