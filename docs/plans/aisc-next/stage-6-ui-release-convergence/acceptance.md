# Stage 6 验收台账

> 分支 `stage-6-ui-release-convergence`。实施中：6a–6g 已提交（见下），6h（总门禁/发布文档/合入）进行中。

## 子步证据（commit）

| 子步 | 验收 | Commit | 证据 |
|---|---|---|---|
| 6a-ki1 | KI-1 查因 | `b91732e` | 复现 Rust 探测正常；`engine_reachable_detail` 经 Docker Desktop bin 路径解析 + 返回 redacted 原因；向导显示"引擎探测详情"。待用户实机复测确认。 |
| 6b-tokens | A-UX01-1 | `12df0c0` | `styles.css` 定义 `--space-*/--font-*/--radius-*/--shadow-*/--z-*/--duration-*` + 状态色；全组件精确迁移（零视觉变化）；`tokens.test.ts` 门禁（token 族存在 + 组件无裸 hex）。 |
| 6c-responsive | A-UX02-1 | `5a8f469` | `layoutTierFor` 纯函数（Compact<640/Standard/Wide>1100，按有效 box 宽度=viewport/zoom）；`data-tier` 驱动 compact 规则；TabBar 横向滚动；显式 min-width。4 个边界测试。 |
| 6d-a11y | A-UX03-1 | `5962ff4` | `useDialogA11y`（focus trap + Escape + opener restore）接入 Settings/Doctor；全局 reduced-motion CSS + xterm smooth-scroll 归零；Terminal 右键菜单 Menu/Shift+F10 键盘开启。2 个辅助函数测试。 |
| 6e-i18n-zoom | A-UX04/05-1 | `ecbdfc3` | 顶栏 status + sidebar sessionState 映射 i18n（不再裸 enum）；zoom rem 迁移 **NO-GO**（D6-09，保留 zoom，证据见 decisions.md）。字典 parity 保持。 |
| 6f-observability | A-REL01-1 | `d73b777` | `trace.rs` 有界 op 耗时环（run_control/env_readiness/start_docker 喂入）+ `op_traces` 命令；`diagnostic_bundle` allowlist 脱敏包（version/platform/redacted settings/env/doctor/traces）导出前展示清单；DoctorDialog 最近操作 + 导出按钮（走 store，F-A01）。2 个 trace 测试。 |
| 6g-migration | A-REL03-1 | `d42d896` | settings/onboarding/artifact previous-version fixture 测试（缺失新字段 → 默认值 + 未知字段保留）；history v1→v2 已有覆盖；unsupported schema fail-closed 已测。3 个新测试。 |

## 全量本地门禁（6h 基线，2026-08-16）

- Python `pytest tests`：**508 passed**（68 skipped）。
- Rust `cargo test`（`SH=...Git/bin/sh.exe`）：**194 passed**（173 lib + 21 集成）。
- TS `vitest run`：**213 passed**；`vue-tsc --noEmit` + `vite build` 干净。

## 待办（6h 收口）

- 推送分支 → `--no-ff` 合并 develop → 监视 CI（Workbench CI / Bundle Linux·macOS / NSIS）。
- devlog / release notes / 归档规则补齐；用户确认后合入发布。

## 手测（2026-08-16）

- **用户确认：当前部分（6a–6g 的 UI/功能）PASS，无问题。**
- **遗留 KI-2**：初始化引导界面有问题，需重新实机手测确认具体症状——**暂不处理**，
  已记录 `../todo.md` KI-2，待 Stage 6 收口后单独安排一轮复检（可能归属 Stage 5
  onboarding 回归或与 6b/6c 交互）。
- 6h 收口继续：合并 → CI → 最终发布文档。

## 验收清单（A-*）

- `A-UX01-1` tokens 覆盖颜色/间距/字体/控件/z/duration，组件无新增主题硬编码。
- `A-UX02-1` 320/600/800/1280、中文/英文、100/150% 无关键控件溢出。
- `A-UX03-1` tabs/dialog/sidebar/context menu/reduced-motion 键盘与读屏通过。
- `A-UX04-1` 用户层无裸字符串/raw enum，字典/长文案通过。
- `A-UX05-1` zoom 迁移有性能/视觉对照；不通过则记录 NO-GO 并保留旧路径。
- `A-UX06-1` Sidebar 常驻摘要、developer details、危险操作层级和 stale 语义通过。
- `A-REL01-1` operation timing/error action/diagnostic redaction allowlist 通过。
- `A-REL02-1` pytest/vitest/cargo/build/contract/soak/axe/visual 和三平台适用门禁通过。
- `A-REL03-1` settings/history/artifact/onboarding/CLI current/previous migration、upgrade/rollback/uninstall 通过。
- `A-REL04-1` devlog/release notes/手测证据/规划归档完整；用户确认后合并发布。
