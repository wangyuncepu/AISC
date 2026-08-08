# Workbench S4.1.a - CLI sidecar 打包与分发基础

> 状态：提案
> 规范：06-implementation-plan.md §六 S4.1；02-startup-flow.md §四.3（CLI discovery 候选序）
> 编写日期：2026-08-08
> 分支：feature/workbench-phase4

## 1. 范围

S4.1.a 立打包与分发基础：PyInstaller CLI 独立二进制 + Tauri sidecar 集成 + discovery 候选序插 sidecar + 版本对齐。S4.1.b（Windows NSIS 定制安装器，winget 引导装依赖）和 S4.1.c（macOS/Linux）后续切片。

### 本切片做（IN）

- **PyInstaller CLI 构建**：`packaging/aisc.spec` + 构建脚本（`scripts/build-cli.sh` / `build-cli.ps1`），产物 `aisc-x86_64-unknown-linux-gnu.sidecar` / `aisc-x86_64-pc-windows-msvc.sidecar` / `aisc-aarch64-apple-darwin.sidecar`（Tauri sidecar 标准命名：`<name>-<target-triple>.sidecar`）。隐藏窗口（Windows GUI 模式，CLI 无控制台）。
- **CI 矩阵**：`.github/workflows/cli-sidecar.yml`--linux/win/macos × PyInstaller 构建 CLI sidecar -> 上传 artifact（release 时进 Tauri bundle）。
- **Tauri sidecar 集成**：`tauri.conf.json` `bundle.externalBin`（3 个三元组 target）；运行时**手动解析 sidecar 路径**（Linux `/usr/lib/<app>/bin/`、macOS `Contents/MacOS/`、Windows exe 同目录），不引入 shell plugin（S3.2 攻击面原则）。
- **cli.rs 候选序插 sidecar**：`enumerate_candidates` 在 saved pin 之后、PATH 之前插入 sidecar（内置 CLI 优先于 pip/PATH 装的，除非用户显式 pin）。新 `CandidateSource::Sidecar`。
- **版本对齐**：sidecar 版本（VERSION 2.1.5-dev）与 Workbench 版本（tauri.conf 0.1.0）--Workbench 版本升为 `2.1.5-dev` 对齐，sidecar 构建时从 VERSION 注入。capability 协商（已实现）兜底：版本失配不阻塞（negotiate 已处理）。
- **`--aisc-cli` 启动 arg 接线**（S2.1 deferred）：main.rs 读 args -> lib.rs 传给 negotiate/discover（explicit 候选）。测试 sidecar vs PATH 优先级用。

### 本切片不做（OUT）

- **NSIS 定制安装器**（winget 引导装 Python/Docker/WebView2）-> S4.1.b。
- **macOS pkg / Linux preinst** -> S4.1.c。
- **Docker 安装检测 UI** -> S4.1.b（安装器内）。
- **平台依赖文档完整版**（WebKitGTK/WebView2 权限）-> S4.1.b/c 附带。

## 2. 关键设计

### 2.1 PyInstaller spec（packaging/aisc.spec）

- `console=False`（Windows 无控制台窗口）、`onefile`（单文件 sidecar 易分发）、entry `aisc.cli.main:main`。
- 排除不需要的大依赖（不打包测试/文档）；数据文件 VERSION。
- 命名：构建脚本按 `sys.platform`/target triple 重命名产物为 `<name>-<triple>.sidecar`（Windows 产物 `.exe` -> 重命名为 `.sidecar`；Tauri sidecar 约定 Windows 也要 `.sidecar` 后缀？--实测确认，Tauri 对 Windows sidecar 命名有特殊处理：`.exe` 在 bundle 时处理。计划按 Tauri docs 标准：`<name>-<triple>.exe` 放 externalBin，Tauri 自动处理。实现时以 tauri externalBin 文档为准）。

### 2.2 sidecar 路径解析（runtime.rs / cli.rs）

`sidecar_path(app) -> Option<PathBuf>`：`app.path().resource_dir()` 或按平台：
- Linux：`/usr/lib/<identifier>/bin/<name>-<triple>`（Tauri externalBin 默认布局）
- macOS：`Contents/MacOS/<name>-<triple>`
- Windows：exe 同目录 `<name>-<triple>.exe`
优先 `externalBin` 布局（Tauri 2 `bundle.externalBin` 自动放对位置），`resource_dir()` 探测 + 平台 fallback。dev 模式无 sidecar -> 返回 None（走 PATH/现有发现）。

### 2.3 候选序（cli.rs）

`enumerate_candidates(explicit, saved, sidecar)`：
`explicit > saved pin > sidecar > PATH > platform`。Sidecar 高于 PATH：内置版本与 Workbench 同构建，capability 必匹配；用户显式 pin 仍可覆盖。`CandidateSource::Sidecar` 序列化 `"sidecar"`（TS CandidateSource 同步加）。

### 2.4 `--aisc-cli` 接线

main.rs：`let args: Vec<String> = std::env::args().collect();` 找 `--aisc-cli <path>` -> 传 `run()`（lib.rs）。lib.rs `run(cli_arg: Option<String>)` -> cli 模块存 initial explicit（AppHandle state 或参数透传）。negotiate/discover 用 explicit 优先（enumerate_candidates explicit 参数）。测试：`npm run tauri dev -- --aisc-cli /path/to/aisc` 验优先级。

## 3. 改动文件

- `packaging/aisc.spec`（新）+ `scripts/build-cli.sh`（新，linux/macos）+ `scripts/build-cli.ps1`（新，windows）。
- `.github/workflows/cli-sidecar.yml`（新）。
- `workbench/src-tauri/tauri.conf.json`：`bundle.externalBin` + version 对齐 2.1.5-dev。
- `workbench/src-tauri/src/cli.rs`：`CandidateSource::Sidecar` + `enumerate_candidates` 插 sidecar + `sidecar_path()`。
- `workbench/src-tauri/src/main.rs` + `lib.rs`：`--aisc-cli` 接线。
- `workbench/src/types/index.ts`：`CandidateSource` 加 `"sidecar"`。

## 4. 步骤与验证

1. PyInstaller spec + 构建脚本 -> verify: 本地跑构建（linux）产物存在 + `./产物 version --format json` 正常 + envelope 正确。
2. CI 矩阵 -> verify: push 后 Actions 三平台产物 artifact 生成（`gh run watch`）。
3. tauri.conf externalBin + sidecar_path + cli.rs 候选序 -> verify: `cargo build` + `cargo test`（新枚举单测：sidecar 优先级）+ 67 不回归。
4. `--aisc-cli` 接线 -> verify: `cargo build` + `npm run build`。
5. 实机手测 -> verify:
   - 本地构建 sidecar 放进 dev 资源目录 -> dev 启动 discovery 报告 sidecar 候选（`cli_discover` 输出含 sidecar source）。
   - `npm run tauri dev -- --aisc-cli <path>` -> explicit 优先。
   - 常规流程回归（pick/start/tab）。

## 5. 验收（S4.1.a 局部）

- [ ] PyInstaller 三平台 CLI sidecar 构建脚本 + CI 矩阵。
- [ ] Tauri externalBin sidecar 集成 + 手动路径解析（无 shell plugin）。
- [ ] discovery 候选序 explicit > saved > sidecar > PATH > platform。
- [ ] `--aisc-cli` 接线。
- [ ] 版本对齐 2.1.5-dev；capability 协商兜底。
- [ ] `cargo test` + `npm run build` 零错误；67 测试不回归。
