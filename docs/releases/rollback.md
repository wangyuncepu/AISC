# AISC Workbench 回滚与版本恢复指南

> S4.2 发布门文档。覆盖安装包回退、CLI 版本协商与数据保留边界。
> 状态：2026-08-09 随 S4.2 发布门编写；签名/公证完成前 Preview 不发布。

## 1. 数据保留边界（先读这个）

卸载与重装**不触碰**以下数据：

| 位置 | 内容 | 生命周期 |
|---|---|---|
| `%APPDATA%\cn.aisc.workbench\`（app_config_dir） | `history.json`（workspace 历史/布局）、`settings.json`（pinned CLI 路径） | 跨卸载/重装保留 |
| 用户工作区（含 `.aisc/`） | runtime 元数据、用户文件 | 安装器从不读写 |
| Docker Desktop 及容器/镜像 | 用户数据 | 与 Workbench 安装无关 |

NSIS 卸载器只删除 `$INSTDIR`（`%LOCALAPPDATA%\AISC Workbench`）、开始菜单快捷方式与卸载注册表键。

## 2. 安装包版本回退

**降级被禁用**（`allow_downgrades=false` 默认）：安装器检测到已装版本更新时，维护页只允许「卸载」，不允许「不卸载」继续。

回退流程：

1. 运行新版安装器 → 维护页选「**卸载应用**」→ 卸载完成（卸载后安装器会继续进入安装向导，可在此直接取消）。
   - 或直接运行 `%LOCALAPPDATA%\AISC Workbench\uninstall.exe`。
2. 运行旧版安装包 → 全新安装。
3. 数据保留：第 1 步不删除 `%APPDATA%\cn.aisc.workbench\` 与工作区（见 §1）。

**同版本覆盖**：重跑同版本安装器 = 修复/重装（add/reinstall 流程），同样不动数据。

## 3. CLI（sidecar）版本协商与回退

协商顺序（`cli.rs` negotiate）：**`--aisc-cli` 进程参数 > settings.json 中 pinned 路径 > 安装目录旁 sidecar 发现**。

- **正常**：安装器随附 sidecar（`aisc.exe`，tauri 2.9.x 以基名安装）；首启协商自动选中并持久化为 pin（`settings.json`）。
- **覆盖升级后**：新版本安装会重新协商，pinned 路径若指向旧安装则被新 sidecar 超越（pin 持久化 + 升级重协商）。
- **手动回退 CLI**：
  - 启动参数指定：`workbench --aisc-cli <旧 CLI 绝对路径>`（开发/诊断用）。
  - 清 pin 恢复自动发现：删除 `%APPDATA%\cn.aisc.workbench\settings.json` 中的 pinned 路径（或整体删文件，恢复默认）。
- **独立运行**：sidecar 即完整 AISC CLI（`dist/aisc-*.exe` / `aisc.exe`），可直接执行 `aisc version` 验证。

## 4. 回滚验证清单

1. 卸载后：`%LOCALAPPDATA%\AISC Workbench` 不存在；`%APPDATA%\cn.aisc.workbench\` 存在；工作区 `.aisc/` 存在。
2. 降级：新版→卸载→旧版安装成功，历史布局与 workspace 记录仍在（`history.json` 未动）。
3. CLI：旧 CLI 可经 `--aisc-cli` 显式启用；pin 删除后协商回落到随包 sidecar。

## 5. 未覆盖（blocked）

- Windows 代码签名（无证书）→ SmartScreen 警告期行为未验证。
- macOS 公证（无 Apple Developer 账号/实机）→ Gatekeeper 路径未验证。
