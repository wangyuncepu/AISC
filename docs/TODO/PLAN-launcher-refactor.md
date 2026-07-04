# 启动器模块化重构计划 (v1.3.0)

> 目标：把臃肿的单体启动器(`launcher.ps1` 131 行 / `启动_AI工作站.sh` 134 行,逻辑高度重叠)拆成 4 个低耦合生命周期模块 + 薄流水线入口,跨平台 .sh + .ps1 平行,模块间用 `.deploy/state.env` 状态文件解耦。

## 设计决策

- **D1 · 按平台 .sh + .ps1**(已与用户确认):bash/PowerShell 各平台自带,零宿主依赖,匹配现有模式。代价:两套平行逻辑同步维护(可接受)。
- **D2 · 状态文件解耦**:`.deploy/state.env`(KEY=value,gitignored)。只存**简单值**(`IMAGE`/`PROXY_ENABLED`/`CONTAINER_NAME`),**不存路径**——路径由各模块从自身位置推导 `PROJECT_ROOT=scripts/..`,避免空格/特殊字符破坏 `source`/解析。bash `source` 读、PS 正则读;写用 `KEY="$val"` 追加/更新。
- **D3 · 入口极薄**:根 `启动_AI工作站.sh` 与 `一键启动_AI工作站.bat` 只负责按序调用 4 模块(pipeline),不含业务逻辑。
- **D4 · 行为保持**:根文件名 + 双击入口不变;代理 TUI / 构建菜单 / docker run 参数全部等价迁移。**API Key 仍在容器内 `cs` 收集**(不在宿主 02 处理密钥);**作用域选择仍在容器内 entrypoint**(不在宿主 02)。如需移到宿主,另行迭代。
- **D5 · 容器侧不动**:`Dockerfile`/`entrypoint.sh`/`mihomo-build-config.js`/`stage-mihomo.sh` 全部不变。

## 目标目录结构

```
scripts/
  _state.sh              # bash 状态助手:state_init / state_set / state_get
  _state.ps1             # PS 状态助手:同
  01_check_env.sh        # 环境检测(docker 装了且在跑)
  01_check_env.ps1
  02_config_wizard.sh    # 代理 TUI → .claude/mihomo/config.yaml + state(PROXY_ENABLED)
  02_config_wizard.ps1
  03_build_image.sh      # 镜像菜单 + 构建 → state(IMAGE)
  03_build_image.ps1
  04_launcher.sh         # 读 state → docker run(按需加 NET_ADMIN/tun/挂载)
  04_launcher.ps1
  run.sh                 # bash 流水线(调 01-04.sh,失败即中止)
  run.ps1                # PS 流水线(调 01-04.ps1)
.deploy/
  state.env              # 运行时状态(gitignored;KEY=value 简单值)
```

根入口(改薄):
- `启动_AI工作站.sh` → `exec bash "$DIR/scripts/run.sh"`(几行)
- `一键启动_AI工作站.bat` → `chcp 65001` + `powershell -File "%~dp0scripts\run.ps1"`(ASCII,不变薄度,只改目标)
- `启动_AI工作站.command` → 不变(透传 .sh)
- **删除** `launcher.ps1`(逻辑拆入 02/03/04.ps1)

## 状态文件契约 (.deploy/state.env)

```
IMAGE=super-claude:latest          # 03 写入(可能被 newname 改)
PROXY_ENABLED=1                    # 02 写入(0/1)
CONTAINER_NAME=super-claude-station-12345  # run 编排器写入(唯一后缀)
```
- 只存简单值(无空格/特殊字符)→ bash `source` 与 PS `^(\w+)=(.*)$` 解析都安全。
- 路径(`MIHOMO_CFG`、`PROJECT_ROOT`)**不存**——各模块从 `$0`/`$PSScriptRoot` 推导 `PROJECT_ROOT`,配置路径 = `$PROJECT_ROOT/.claude/mihomo/config.yaml`。
- `_state.sh`:`state_init`(建 .deploy + 清空 state.env)、`state_set KEY VAL`(追加/更新)、`state_get KEY`(echo)。
- `_state.ps1`:`Init-State`、`Set-State`、`Get-State`。

## 各模块职责

### 01_check_env (.sh/.ps1)
- 检 `docker` 命令存在(`command -v docker` / `Get-Command docker`)。
- 检 daemon 运行(`docker info` 成功)。
- 失败 → 友好提示 + `exit 1`。
- 不写 state。(网络连通性不单独测——02 的下载即实测。)

### 02_config_wizard (.sh/.ps1)
- 代理 TUI(迁移当前 `configure_proxy` 逻辑):`y/N` → `1本地/2URL` → 下载/拷贝 → 非空校验。
- 写 `.claude/mihomo/config.yaml`(宿主原始配置,格式由容器内识别/转换)。
- 写 state:`PROXY_ENABLED`(0/1)。
- **不**碰 API Key / 作用域(D4)。

### 03_build_image (.sh/.ps1)
- 镜像存在检查 → 菜单 `[1]运行/[2]重建/[3]新名`(不存在则直接构建)。
- 构建:`cache?` + `国内镜像?` 提示 → `docker build`。
- 构建后 `立即运行? [Y/n]`(`n` → `exit 0` 中止流水线)。
- 写 state:`IMAGE`(最终镜像名,可能被 newname 改)。

### 04_launcher (.sh/.ps1)
- 读 state:`IMAGE`/`PROXY_ENABLED`/`CONTAINER_NAME`。
- 推导 `PROJECT_ROOT` + `MIHOMO_CFG`。
- 清理已退出的旧容器。
- 拼 `docker run -it --rm -e TERM=... --name $CONTAINER_NAME -v $PWD:/home/AISC/app $IMAGE`;`PROXY_ENABLED=1` 则追加 `--cap-add=NET_ADMIN --device=/dev/net/tun -v $MIHOMO_CFG:/etc/mihomo/config.yaml:ro`。
- 执行 `docker run`(前台,接管 TTY)。

### run.sh / run.ps1(编排器)
- `state_init`(新建 .deploy/state.env)。
- 写 `CONTAINER_NAME`(bash `$$`/PS `Get-Random`)、`IMAGE=super-claude:latest` 默认。
- 打印头部 banner。
- 按序 `01 → 02 → 03 → 04`,任一非零退出即中止(`set -e` / `if ($LASTEXITCODE)` )。
- run.sh 用 `bash scripts/0X.sh`;run.ps1 用 `& powershell -File scripts/0X.ps1` 或 `. scripts/0X.ps1`(同进程 source,共享状态函数)。

## 跨模块数据流

```
run.*        → state: CONTAINER_NAME, IMAGE(默认)
01_check_env → (无写)
02_config_wizard → state: PROXY_ENABLED;  文件: .claude/mihomo/config.yaml
03_build_image   → state: IMAGE
04_launcher      ← 读 state: IMAGE, PROXY_ENABLED, CONTAINER_NAME → docker run
```

## 路径解析(两平台一致)
- bash:`PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"`
- PS:`$ProjectRoot = Split-Path $PSScriptRoot -Parent`
- state 文件:`$PROJECT_ROOT/.deploy/state.env`
- 配置:`$PROJECT_ROOT/.claude/mihomo/config.yaml`

## 配置文件改动
- `.gitignore`:加 `.deploy/`(运行时状态)。
- `.gitattributes`:加 `scripts/*.sh text eol=lf`、`scripts/*.ps1 text eol=lf`(PS1 需 BOM —— .ps1 加 BOM,见下)。
- **PS1 BOM**:所有 `scripts/*.ps1` + `run.ps1` 需 UTF-8 BOM(PS5.1 按 BOM 识别 UTF-8 中文)。创建后用 `printf '\xEF\xBB\xBF'` 前置。
- **.sh 行尾**:LF(`.gitattributes` eol=lf 保证)。

## 分批实施(等你"确认"后)

1. **脚手架**:`scripts/` 目录、`_state.sh`+`_state.ps1`、`.deploy/` gitignore、.gitattributes。
2. **01_check_env** `.sh`+`.ps1`。
3. **02_config_wizard** `.sh`+`.ps1`。
4. **03_build_image** `.sh`+`.ps1`。
5. **04_launcher** `.sh`+`.ps1`。
6. **run.sh**+`run.ps1` 编排器。
7. **根入口改薄**:`启动_AI工作站.sh`、`一键启动_AI工作站.bat`;**删** `launcher.ps1`。
8. **测试 + 文档**:`bash -n`/PS 语法;e2e(管道输入跑通两条路径);更新 README/devlog(.gitignore/.gitattributes)。

## 测试
- `bash -n scripts/*.sh` 全过。
- PS 语法:`[System.Management.Automation.Language.Parser]::ParseFile`。
- e2e(Linux/Git Bash):`printf '1\nn\n' | bash 启动_AI工作站.sh` → 验证 state.env 写入 + docker run 拼对。
- e2e(Windows):`printf '1\nn\n' | cmd /c 一键启动_AI工作站.bat`(拷 ASCII 名避中文文件名编码)→ 验证 PS1 流水线 + 中文 UI + docker run 拼对。
- 代理路径:`1\ny\n2\n<url>\n` → 验证 `PROXY_ENABLED=1` + `--cap-add`/`--device`/挂载。

## 风险/取舍
- 两套平行逻辑(.sh/.ps1)同步维护——用户已选,接受。提示文案改动需同步两份。
- 状态文件明文(仅 flag/镜像名/容器名,无密钥)——订阅凭据仍在 `.claude/mihomo/config.yaml`(gitignored),不入 state。
- PS1 BOM 必须保留(git `text eol=lf` 不动 BOM)——创建后前置,提交时 .gitattributes 保证 LF+BOM。
- 删 `launcher.ps1` 后,旧 `.bat` 调用目标改 `run.ps1`——无向后兼容包袱(用户用根入口,不直接调 launcher.ps1)。
