# PLAN: Workbench S4.2 发布门（CI + 文档补全）

> 依据：`docs/gui-planning/06-implementation-plan.md` §七 S4.2。Phase 4 的 S4.1（安装体验）已闭环，本计划执行 S4.2 剩余可做部分。
> 状态：2026-08-09 用户确认范围「先做 CI+文档」。

## 范围

1. **三平台契约 smoke**：`tests.yml` 增加 macOS runner（当前 ubuntu+windows）。
2. **Linux/macOS bundle CI**：新增 workflow 在 ubuntu-latest（deb/AppImage）与 macos-latest（DMG）执行 `tauri build`，验证三平台安装包可产出。
3. **覆盖升级/卸载安全冒烟（Windows）**：静默装 v1 → 放置 workspace/配置标记 → 覆盖安装同版本 → 验证标记与 CLI 配置完好 → 静默卸载 → 验证 workspace/runtime 数据保留、卸载干净。
4. **回滚文档**：新增 `docs/releases/rollback.md`（版本协商/pin 重置、降级路径、数据保留说明）。

## 范围外（blocked，资源未到位）

- Windows 代码签名（无证书）。
- macOS 公证（无 Apple Developer 账号/实机）。
- 在签名/公证完成前发布正式 Preview。

## 验收标准

| # | 可观察结果 |
|---|---|
| A1 | tests.yml 三平台契约 smoke 全绿（含 macOS runner） |
| A2 | Linux bundle 产物 + macOS DMG 产物在 CI 产出 |
| A3 | Windows 升级/卸载冒烟通过：配置与 workspace 数据不受覆盖安装影响，卸载后数据保留 |
| A4 | 回滚文档存在且步骤可执行（版本协商、pin 重置、降级、数据保留边界） |

## 步骤

1. tests.yml：matrix 加 `macos-latest`；确认 3.11/3.12/3.13 × 3 OS 全绿。
2. 新建 `.github/workflows/bundle-linux-macos.yml`：三平台 sidecar 已由 cli-sidecar.yml 产出（需先在 jobs 内自行构建 sidecar 或复用 artifact）；ubuntu 装 webkit2gtk 系依赖；macos 直接 build。产物上传 artifact。
3. 扩展 `nsis-installer.yml` 冒烟：升级（同版本覆盖）+ 卸载两步，含数据保留断言。
4. 写 `docs/releases/rollback.md`。
5. 文档记录：devlog S4.2 条目 + 发布门状态。

## 风险

- macOS bundle：tauri 首次在 CI 构建 DMG 可能遇到 codesign 默认签名问题（macos-latest 无开发者证书时 tauri 2 默认 ad-hoc 签名，可产出）。
- Linux AppImage 依赖多（libfuse2 等），若失败可降级为仅 deb。
- 覆盖升级冒烟受 NSIS 同版本语义约束（PageReinstall 同版本 = add/reinstall，已验证该流程）。

## 待决

- 无（范围已确认）。
