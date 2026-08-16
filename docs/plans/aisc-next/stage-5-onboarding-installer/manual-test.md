# Stage 5 实机手测方法与清单

> 平台：Windows 11 / x86_64（主测）；Linux/macOS 见矩阵表（随 5g 总门）。
> 版本：2.1.5-dev（或当前 develop）；分支 `stage-5-onboarding-installer`。
> 目标：验证 Installer（NSIS）与首次启动向导（Onboarding）在真实环境的行为，
> 覆盖 A-INS01/02、A-ONB01..08。每项记录：日期、构建 commit、步骤、实际结果、PASS/FAIL。

---

## 0. 准备

1. **构建 sidecar + 前端**（改过前端/CLI 后必须重建 sidecar，否则向导读到旧 CLI）：
   ```powershell
   powershell -File scripts/build-cli.ps1
   # 复制新 sidecar 到 staging 源：
   Copy-Item dist\aisc.exe workbench\src-tauri\binaries\aisc-x86_64-pc-windows-msvc.exe -Force
   ```
2. **构建 NSIS 安装器**：
   ```powershell
   cd workbench
   npm run tauri build   # 产出 target/release/bundle/nsis/*-setup.exe
   ```
3. **准备干净测试工作区**：一个空目录 + 一个已有 runtime 的项目目录（用于 reuse/restart/conflict 分支）。
4. **记录基线**：`%LOCALAPPDATA%\aisc\artifacts`、`%APPDATA%\cn.aisc.workbench` 是否存在；
   若之前装过，先卸载旧版（见 1.3）。

---

## 1. Installer（A-INS01/A-INS02/A-ONB08）

### 1.1 Fresh 安装（A-INS01-1 主路径）
| # | 步骤 | 预期 |
|---|---|---|
| 1.1.1 | 双击 setup.exe，选语言 → 安装位置 | 中文/英文 UI 正常，步骤 rail 显示 |
| 1.1.2 | 安装完成 → 勾选"启动 Workbench" | 启动；`HKCU\Software\aisc\AISC Workbench` 写入 `InstallerSource=nsis`、`InstalledVersion`、`FirstRun=1`、`DockerHint=installer_checked` |
| 1.1.3 | 命令行 `aisc version --format json` | sidecar 可用（PATH 已加） |
| 1.1.4 | 注册表检查（见上） | 四个 handoff 值齐全，无 secret |

### 1.2 升级安装（A-INS01-1）
| # | 步骤 | 预期 |
|---|---|---|
| 1.2.1 | 再跑 setup.exe（同版本或更新版本） | 升级不丢 `%APPDATA%` 数据、不丢 handoff 的升级兼容 |
| 1.2.2 | 检查 settings/history/onboarding 文件 | 保留 |

### 1.3 卸载（A-INS01-1）
| # | 步骤 | 预期 |
|---|---|---|
| 1.3.1 | 控制面板卸载 或 uninstall.exe | 卸载完成 |
| 1.3.2 | 注册表 `HKCU\Software\aisc\AISC Workbench` | 键被 `DeleteRegKey` 清理（含 handoff） |
| 1.3.3 | PATH 中的安装目录条目 | 移除 |

### 1.4 失败/重试（A-INS02-1）
| # | 步骤 | 预期 |
|---|---|---|
| 1.4.1 | 安装目录不可写 / 空间不足时安装 | 报错可读，可返回/退出，不进入坏状态 |

---

## 2. 首次启动向导（A-ONB01..08）

> 触发：首次安装后启动（onboarding.json 不存在 → not_started）；或删掉
> `%APPDATA%\cn.aisc.workbench\onboarding.json` 后启动。

### 2.1 欢迎（A-ONB01）
| # | 步骤 | 预期 |
|---|---|---|
| 2.1.1 | 启动 → 看到欢迎页 | "欢迎/欢迎使用 AISC Workbench"，Begin/Skip |
| 2.1.2 | 点 Begin | 进入 environment 步骤；onboarding.json 写 `status=in_progress, current_step=environment` |

### 2.2 环境就绪（A-ONB02）
| # | 步骤 | 预期 |
|---|---|---|
| 2.2.1 | 环境步骤显示 CLI/Docker Desktop/Engine/WebView2 状态点 | 状态点颜色正确（绿=ready，黄=starting，红=unavailable） |
| 2.2.2 | Docker Desktop 未装 | docker=not_installed、engine=unavailable，Continue 禁用 |
| 2.2.3 | Docker Desktop 装了但没启动 | docker=installed、engine=starting → "Start Docker" 按钮出现 |
| 2.2.4 | 点 Start Docker → 等待 | 30s 轮询，Engine 起来后 engine=ready，Continue 启用 |
| 2.2.5 | 轮询超时 | 保持 starting，保留 Retry/Continue 状态，不把 stale 当 ready |
| 2.2.6 | 点 Retry | 重新探测 |

### 2.3 工作区（A-ONB03）
| # | 步骤 | 预期 |
|---|---|---|
| 2.3.1 | 环境就绪后 Continue | 进入 workspace 步骤；最近工作区列表（若有） |
| 2.3.2 | 点最近项 | 选中并恢复该 workspace 配置 |
| 2.3.3 | 点"浏览…" | 目录选择器；选目录后 workspace 生效 |
| 2.3.4 | 选好 workspace 后 Continue | completeStep=workspace → agent 步骤 |

### 2.4 Agent 就绪（A-ONB04）
| # | 步骤 | 预期 |
|---|---|---|
| 2.4.1 | agent 步骤显示 Claude/Codex | 状态文案（ready/需要登录/需要配置/不支持），无 secret/密钥 |
| 2.4.2 | 未配置过 runtime | 默认 needs_configuration（不崩、不显示内部 enum） |

### 2.5 网络（A-ONB05）
| # | 步骤 | 预期 |
|---|---|---|
| 2.5.1 | 网络步骤显示 direct/宿主代理/容器 TUN | 三选项 + 影响提示（不改宿主代理） |
| 2.5.2 | 选"容器 TUN" → Continue | Continue 禁用（需确认） |
| 2.5.3 | 点"确认——应用于运行环境" | 确认生效；再 Continue → 保存 network=proxy |
| 2.5.4 | 点"检查连通性" | 显示可达/不可达（依 Engine 状态） |
| 2.5.5 | 选 direct / 跳过 | 直接进入 runtime 步骤；network=direct |
| 2.5.6 | 中途点 revoke/跳过 | 回到 direct，不影响宿主代理 |

### 2.6 Runtime（A-ONB06）
| # | 步骤 | 预期 |
|---|---|---|
| 2.6.1 | runtime 步骤自动 preflight | 显示动作（新建/复用/重启/冲突） |
| 2.6.2 | 新 workspace → preflight=start | Continue 启用 → complete |
| 2.6.3 | 已有 runtime → preflight=reuse/restart | 对应文案；Continue 启用 |
| 2.6.4 | 冲突 → preflight=resolve_conflict | Continue 禁用，显示冲突 runtime 列表；Retry 重跑 |
| 2.6.5 | preflight 失败（Docker 掉了） | 显示错误，Retry 可用 |

### 2.7 完成（A-ONB07）
| # | 步骤 | 预期 |
|---|---|---|
| 2.7.1 | 到 complete 步骤 | "一切就绪"，进入工作区 / 稍后再说 |
| 2.7.2 | 点"进入工作区" | 覆盖层关闭；runtime 启动；onboarding.json `status=completed` |
| 2.7.3 | 主界面进入 workspace，Explorer 树可用 | Stage 3 Explorer 接通（agent 产物/树正常） |
| 2.7.4 | 设置 → "重新打开设置向导" | 覆盖层重现（in_progress/environment） |
| 2.7.5 | 已完成时点 Skip/稍后 | 温和提示可重开 |

### 2.8 中断恢复 / 损坏 / 高版本（A-ONB01）
| # | 步骤 | 预期 |
|---|---|---|
| 2.8.1 | 向导进行中直接关窗口 → 重启 | 恢复为 in_progress，从 current_step 继续 |
| 2.8.2 | 手工写坏 onboarding.json | 启动隔离到 `.corrupt`，以 not_started 启动，不崩溃 |
| 2.8.3 | 手工把 schema_version 改成 99 | 只读/安全回退，不覆盖原文件 |

---

## 3. 交叉验证

- **二次验证（D5-07 / A-ONB08）**：即使 installer handoff 写了 `FirstRun=1`，
  启动时 Workbench 仍**重新**探测 CLI/Docker（env_readiness），不以 handoff 为准。
  验证：篡改 handoff 的版本值不影响实际探测结果。
- **不泄露 secret**：全程观察（状态点、文案、日志）不出现 token/key/密钥。

---

## 4. 矩阵表（A-ONB08-2，随总门）

| 维度 | Windows 11（本机） | Linux | macOS |
|---|---|---|---|
| 中英文 | 测 | — | — |
| 窄窗 / 150% | 测 | — | — |
| 键盘（Tab/方向/Enter） | 测 | — | — |
| 读屏（role/aria） | 测 | — | — |

> Linux/macOS 实机在 Stage 5 总门用 CI Bundle + 真机补；本清单主要覆盖 Windows。

---

## 5. 记录模板（每项）

```text
验收 ID：
日期：            构建 commit：
平台/版本：       
前置条件：
步骤：
期望：
实际结果：
截图/日志：       
结论：PASS | FAIL
```
