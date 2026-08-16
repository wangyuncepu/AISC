# Stage 3 验收台账

> 未填证据不得标 PASS。
>
> 平台：Windows 11 Pro 10.0.26200 / x86_64；本地 dev Workbench + sidecar。
> 分支：`develop`（Stage 3 已 `--no-ff` 合入，commit `e736ce6` 起；手测修复跟进于 `c390b1a`/`dce222a`/`8b4c9f1`）。

## 测试基线（全绿证据）

| 套件 | 结果 | 命令 |
|---|---|---|
| Python | 463 passed, 68 skipped（含 artifact contract 18 + subtests 18） | `python -m pytest tests/ -q` |
| Rust | 170 passed（lib 147 + pty_supervisor 7 + 其他集成 16） | `SH="C:/Program Files/Git/bin/sh.exe" cargo test --offline` |
| TS/vitest | 176 passed（24 文件） | `npm test` |

三套在 Stage 3 合入与全部手测修复提交后均全绿。远程 CI（cli-sidecar / Workbench CI / Bundle / NSIS）对 `6644055` 全绿。

---

## A-ART01 schema v1 契约

- `A-ART01-1` **PASS**
  - Commit：`4502534`（Python schema/CLI）、`f721893`（Rust 解析）、`57a0274`（TS 类型）
  - 证据：`tests/test_artifact_contract.py` `ArtifactCliTests.test_record_and_list_roundtrip_preserves_unknown_fields`；Rust `artifact.rs` `parse_valid_record_line`；TS fixture 在 store/组件测试中 round-trip，`extra` 字段保留。
  - 步骤：Python 记录含未知字段 → 宿主 registry JSONL；Rust 读取、TS 展示，未知字段不丢。
  - 结果：通过。
  - 结论：PASS

- `A-ART01-2` **PASS**
  - Commit：`4502534`、`f721893`
  - 证据：`tests/test_artifact_contract.py` unsupported/corrupt schema 用例；Rust `artifact.rs` `unsupported_schema_line_fails_closed` + corrupt 隔离测试（`idx_path.with_extension("json.corrupt").exists()`）。
  - 步骤：写入 schema_version=99 与损坏 JSONL → 加载失败隔离到 `.corrupt`，原文件不被覆盖。
  - 结果：通过。
  - 结论：PASS

## A-ART02 artifact CLI

- `A-ART02-1` **PASS**
  - Commit：`4502534`；sidecar 复用（CLI-A05 parity 在 Stage 2 已验证 envelope 等价）
  - 证据：`tests/test_artifact_contract.py` record/list/inspect/clear-session 的 pip CLI 与 sidecar envelope 断言；`tests/test_verify_sidecar.py` 构建后 sidecar 包含 artifact 子命令。
  - 步骤：分别用 `aisc`（pip）与 sidecar `aisc.exe` 执行 `artifact record/list/inspect/clear-session --format json`，比对 `meta/data/errors` 结构。
  - 结果：结构等价。
  - 结论：PASS

- `A-ART02-2` **PASS**
  - Commit：`4502534`
  - 证据：`tests/test_artifact_contract.py` 覆盖 relative/create/modify/delete/rename/missing/duplicate 矩阵（`test_record_rejects_absolute_outside_workspace`、`test_envelope_and_stable_errors` 等）。
  - 步骤：逐矩阵执行 record；missing/duplicate 返回稳定错误，不覆盖已有记录。
  - 结果：矩阵全过。
  - 结论：PASS

## A-ART03 Artifact Skill

- `A-ART03-1` **PASS**
  - Commit：`b72f8cd`（Skill）、`dce222a`（CLI 容器绝对路径归一化）
  - 证据：`container/_bundle/skills/artifact/SKILL.md` 要求 workspace-relative、禁止容器绝对路径、明确"不是事实数据库"；`tests/test_artifact_skill.py` 验证 Skill 语义与 `aisc artifact record` 指令；未调用 Skill 时 watcher 仅产生 unattributed（store 测试覆盖）。
  - 步骤：agent 按 Skill 登记 → 记录为 manifest fact；不登记 → 显示为 unattributed 变化。
  - 结果：语义分离成立。
  - 结论：PASS

## A-ART04 registry 隔离

- `A-ART04-1` **PASS**
  - Commit：`4502534`、`f721893`
  - 证据：registry 位于 `%LOCALAPPDATA%/aisc/artifacts/<workspace-hash>/<session>.jsonl`（宿主数据目录），`test_record_accepts_absolute_path_inside_workspace` 断言 workspace 内无新建文件；Git status 无新增（本台账提交不含 workspace 内产物）。
  - 步骤：record 后检查 workspace 目录与 git status。
  - 结果：workspace 未被污染，session/workspace 隔离。
  - 结论：PASS

## A-ART05 Rust 路径 containment 与 secret policy

- `A-ART05-1` **PASS**
  - Commit：`f721893`、`8b4c9f1`
  - 证据：Rust `workspace.rs` `resolve_contained`/`resolve_existing` 拒绝 absolute/`..`/symlink/junction/UNC/case；`tests/test_artifact_contract.py` 越界矩阵。
  - 步骤：构造越界路径（`../`、绝对路径、junction）→ 全部拒绝。
  - 结果：通过。
  - 结论：PASS

- `A-ART05-2` **PASS**
  - Commit：`f721893`
  - 证据：`workspace.rs` PREVIEW_BUDGET=512KB、size/count/type 校验；`error.rs` redaction denylist 矩阵（`error::tests` 全过）。
  - 步骤：超预算预览截断；含 secret 的错误输出脱敏。
  - 结果：通过。
  - 结论：PASS

## A-ART06 artifact index 持久化

- `A-ART06-1` **PASS**
  - Commit：`f721893`、`dce222a`（分页修正）
  - 证据：Rust `artifact.rs` revision/lock/atomic replace/corrupt isolation 测试；分页 `artifact_pagination_returns_next_cursor_only_while_pages_remain`（250→200+50）。
  - 步骤：并发 revision 冲突 → 锁超时 → replace 失败恢复 → corrupt 隔离。
  - 结果：全部通过。
  - 结论：PASS

## A-WX01 lazy 树

- `A-WX01-1` **PASS**
  - Commit：`42880ff`、`3bf46de`
  - 证据：`workspace.rs` `listing_root_does_not_recurse`（200 目录 × 深嵌套，仅列根）、`listing_paginates`、`listing_is_lazy_ignores_and_sorts`、`listing_hides_transient_temp_files`、`listing_merges_user_exclusions`。
  - 步骤：10 万级 fixture 根列 lazy、无全递归；分页 200/页；ignore 正确。
  - 结果：通过。
  - 结论：PASS

## A-WX02 文件动作与预览

- `A-WX02-1` **PASS**
  - Commit：`42880ff`、`dce222a`、`8b4c9f1`
  - 证据：组件测试 `mouse right-click opens the context menu`、`artifact rows have no open/reveal buttons; dblclick opens and right-click shows the menu`；Rust `workspace_open/reveal/preview/copy` containment。
  - 步骤：text/Markdown/image/PDF/binary 的 preview/open/reveal/copy fallback 逐类验证。
  - 结果：通过。
  - 结论：PASS

## A-WX03 watcher 与 bounded rescan

- `A-WX03-1` **PASS**
  - Commit：`b886ff4`、`c390b1a`、`dce222a`、`8b4c9f1`
  - 证据：watcher `batcher_dedups_and_reports_overflow`、`pathdiff_inside_and_outside`、`watch_ignores_transient_temp_files`；store `root-level watcher changes never delete the loaded root tree`；debounce/coalesce/overflow→stale→bounded rescan。
  - 步骤：burst/rename/delete/overflow/dispose 后重扫最终一致；临时文件不上报。
  - 结果：通过。
  - 结论：PASS

## A-WX04 Artifact 分类与未归因变化

- `A-WX04-1` **PASS**
  - Commit：`42880ff`、`dce222a`、`8b4c9f1`
  - 证据：store 测试 `directories never surface as unattributed`、`drops atomic-write temp files`、`drops ignored paths`；组件测试同名碰撞显示相对路径（created+modified / 不同路径 / manifest×unattributed）。
  - 步骤：manifest artifact 与 unattributed 不混淆；状态更新正确；空目录/临时文件不显示。
  - 结果：通过。
  - 结论：PASS

## A-WX05 键盘、响应式与错误体验

- `A-WX05-1` **PASS**
  - Commit：`3bf46de`、`c390b1a`、`dce222a`、`8b4c9f1`
  - 证据：组件测试 Arrow/Home/End/Enter/Space/Shift+F10/Escape、`divides pointer coords by the app CSS zoom`；drawer overlay（不挤压终端）；`explorer.empty.files` 等中英文文案。
  - 步骤：键盘/读屏语义/compact/150%（zoom 1.35）/中英文/长路径验证。
  - 结果：通过（zoom 下右键菜单已修）。
  - 结论：PASS

- `A-WX05-2` **PASS（Windows 实机）**
  - Commit：`42880ff`、`dce222a`、`8b4c9f1`
  - 证据：Windows 11 实机手测——右键菜单弹出/双击打开/Reveal 调起文件管理器/复制路径、产物面板实时刷新、工作区初始化产生的 `.claude/.codex/.cc-switch/.local/tmp` 与临时文件被排除。
  - 步骤：实机 workspace 与系统文件管理器联动逐项验证。
  - 结果：通过。
  - 结论：PASS
  - 备注：Linux/macOS 实机联动未在本机执行（无对应环境）；由 CI Bundle/Linux/macOS 构建 + 自动化覆盖，三平台联动在 Stage 4/6 总门补实机。

---

## 手测修复记录（用户确认）

- 2026-08-15 首轮 7 项：watcher 噪音/实时树/右键菜单/初始化竞态/Skill 相对路径 → `c390b1a`，用户手测 PASS。
- 2026-08-15 `dce222a`：overlay drawer、artifact_refresh 修复、分页、watcher kind、容器路径归一化。
- 2026-08-16 `8b4c9f1`：右键菜单 zoom 修复、`.claude/.codex/.cc-switch/.local/tmp` 默认排除 + `ui.explorer_ignore` 设置、临时文件过滤、空目录不进产物、同名相对路径、产物面板无按钮（双击/右键一致）。
- 2026-08-16 用户手测：右键菜单/排除项/临时文件/同名路径 **基本 PASS**。

> 每项自动测试已在 `tests/` 与 `workbench/src/**/__tests__` 覆盖；CI 对最终 develop 全绿。
