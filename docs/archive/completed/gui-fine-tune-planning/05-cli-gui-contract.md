# Fine-Tune CLI–GUI 契约边界

> 基线快照：commit `1f15f8bbb6beeee0e9a6af8a4daa3310ee02747a` 的 `docs/archive/gui-planning/05-cli-gui-contract.md`。  
> 继承清单：§三结构化协议、§四 build events、§五 runtime 5.1–5.5（但 stop grace 由本文件覆盖）、§六 session 6.1–6.4（但 workspace/terminate grace 由本文件覆盖）、§七 provider current、§八错误 envelope/退出码、§九 runner/PTY 数据面、§十安全约束。  
> 不继承清单：归档 §十一验收测试；本阶段验收只使用当前 `A-*` 台账。  
> 覆盖清单：控制面措辞、runtime/session grace、Session workspace、doctor 和 Workbench NSIS PATH 以本文件为准。  
> 本文件是 fine-tune 阶段 CLI 命令、默认值和 PATH 行为的技术 SSOT。

## 一、控制面与数据面边界

### 1.1 必须走 AISC CLI

- Runtime preflight/start/list/inspect/stop/restart/remove。
- Provider 查询使用实际命令 `aisc provider current --runtime-id <uuid> --agent <claude|codex> --workspace <path> --format json`。
- 容器内 Session 创建和终止：`aisc session open/terminate`。
- doctor、build 等已有结构化命令。

Workbench 不直接调用 Docker API/CLI，不读写 registry 文件，不修改 Provider 配置。

### 1.2 Workbench Rust 可直接管理

- 宿主 PTY 创建、字节读写、resize、child wait/reap/force-kill。
- Tauri 窗口、托盘、通知、settings/history。
- 作为宿主集成动作启动 Docker Desktop；这不是 Docker/registry 控制操作。

因此“CLI 是唯一控制面”不等于每个 PTY byte/resize 都启动一次 CLI。

## 二、命名约定

| 层级 | 规范名称 | 说明 |
|---|---|---|
| CLI | `aisc runtime stop --grace <seconds>` | 容器 stop grace |
| CLI | `aisc session terminate --grace <seconds>` | 容器内 Session TERM/KILL grace |
| CLI | `aisc doctor --format json` | 结构化诊断 |
| Tauri command | `stop_runtime` | 构造完整 CLI argv |
| Tauri command | `open_session / close_session / resize_session` | Session/PTY API |
| Tauri command | `shutdown_workbench` | 统一退出协调 |
| Frontend action | `stopRuntime()` | Store action |
| Domain result | `SessionExit` | 单一终止结果 |
| PTY signal | `exit/output/error` | backend channel 事件 |

文档不得使用不完整的“stop 命令”“后台收尾”等称呼代替完整层级和语义。

## 三、G-07 Runtime stop 参数化

### 3.1 CLI 契约

新增：

```text
aisc runtime stop \
  --runtime-id <uuid> \
  --workspace <canonical-path> \
  [--grace <integer-seconds>] \
  --format json
```

规则：

- `--grace` 默认 `10`；CLI 直用默认行为不变。
- 允许范围 `1..600`，`argparse` 先保证整数类型；`0`、负数或大于 600 的值由命令层返回 usage error，且不调用 Docker。
- `src/aisc/adapters/docker_.py::stop_container(timeout=10)` 已支持 timeout；新增工作是 parser → command → application → executor 的完整透传。
- JSON envelope、`RuntimeSnapshot`、退出码和错误码不变。

### 3.2 Workbench 路径

Workbench Rust 构造：

```text
aisc runtime stop ... --grace 3 --format json
```

- Frontend 只传 domain 参数，不自行拼 CLI argv。
- Tauri `stop_runtime` 不接收 grace；Rust backend 固定构造 `--grace 3`。Frontend 仅传 runtime/workspace 等 domain 参数。
- stop 返回后必须 inspect；UI 不仅信任操作返回。

## 四、G-07 Session close 与 workspace

当前 Session argv 缺少 workspace，必须在 G-07/G-08 前修复。

### 4.1 Open

```text
aisc session open \
  --runtime-id <uuid> \
  --session-id <uuid> \
  --agent <claude|codex|bash|cc-switch> \
  --workspace <canonical-path>
```

`open_session` Tauri command 新增 `workspace`。Canonical workspace 的唯一生产者是 Rust backend：

1. 收到前端 workspace 后用平台文件系统 canonicalize；不存在/无权限时返回稳定 workspace error，不启动 child。
2. canonical 结果写入 `SessionEntry`，并用于 open/terminate argv；frontend 原始字符串不再作为 Session identity。
3. preflight/start 成功返回的 canonical `config.workspace` 同步回 store/history；history key 使用该值。
4. Windows 比较使用 canonical 路径及大小写不敏感 key；UNC/symlink 以 OS canonical 结果为准。

### 4.2 Terminate

CLI 直用契约保持：

```text
aisc session terminate ... --grace 5 --format json
```

Workbench 快路径显式使用：

```text
aisc session terminate \
  --runtime-id <uuid> \
  --session-id <uuid> \
  --workspace <canonical-path> \
  --grace 3 \
  --format json
```

- CLI 默认 5 不变；输入必须是有限数值，合法范围 `0..600`，负数、NaN、Infinity 和越界值返回 usage error、零 Docker 调用。
- Python terminate 的 Docker command timeout 固定为 `grace + 1s`，替代当前 `grace + 10s`；这不改变 TERM→KILL grace，只收紧外层 transport 余量，确保 Workbench `--grace 3` 能在 Rust 5 秒 command budget 内完成或失败。
- Workbench Rust command budget 5 秒；其后按生命周期契约等待/force-reap 本地 PTY。
- terminate 失败不等于本地 child 可以遗留；本地回收始终由 Rust 完成。

## 五、G-18 Workbench sidecar 加入用户 PATH

### 5.1 安装对象

- Windows Workbench 为 current-user NSIS 安装，默认目录 `%LOCALAPPDATA%\AISC Workbench`。
- Tauri externalBin 在正式安装布局中使用 base name：`$INSTDIR\aisc.exe`；target-triple 文件名只作为兼容 fallback。
- PATH 加入目录 `$INSTDIR`，不是 exe 路径。
- Workbench 内部 CLI discovery 仍优先使用已 pin/sidecar 绝对路径；PATH 仅为用户终端入口。

### 5.2 安全算法

安装时：

1. 读取 `HKCU\Environment\Path`，保留原注册表字符串类型和未相关内容。
2. 对每个目录项做比较规范化：trim、去成对引号、统一尾斜杠、Windows 大小写不敏感；写回时不无故展开 `%VAR%`。
3. 如果 `$INSTDIR` 已存在：不重复追加；只有已有 installer ownership marker 时继续视为 owned。
4. 冲突探测按原 PATH 顺序做无副作用静态检查：split raw entries；去引号并仅为 probe 展开 `%VAR%`；跳过空项和 UNC/网络目录；检查 `<expanded-entry>\aisc.exe`，记录首个实际命中路径，但写回保留 raw 文本。
5. 如果首个命中不是 `$INSTDIR\aisc.exe`：不覆盖、不重排、不追加 `$INSTDIR`，记录 conflict path。若 `$INSTDIR` 已在后方但被前项遮蔽，同样视为 conflict。交互安装完成页显示提示，静默安装只写 DetailPrint/日志。
6. 否则追加 `$INSTDIR`，写入：

```text
HKCU\Software\aisc\AISC Workbench\PathEntryOwned = 1
HKCU\Software\aisc\AISC Workbench\PathEntry = "$INSTDIR"
```

7. 广播 `WM_SETTINGCHANGE("Environment")`；提示用户已打开终端需重开。

升级时：

- `/UPDATE` 不得最终删除 owned entry；旧卸载若移除，新安装必须重建一次。
- 重复安装后 `$INSTDIR` 恰好出现一次。
- 安装目录变化时，仅在旧 marker 表明 owned 时移除旧精确项，再写新项。

正常卸载时：

- 仅当 `PathEntryOwned=1` 且 marker 路径与本次 `$INSTDIR` 规范化后相等，才删除精确匹配目录项。
- 不删除 PATH 中的其他目录或其他 `aisc`。
- `/UPDATE` 卸载不执行最终 ownership 清理。
- 删除 marker 并广播环境变更。

### 5.3 Manufacturer 与安装器语言

- 打包身份固定为 `manufacturer=aisc`、`productName=AISC Workbench`，完整 product key 为 `HKCU\Software\aisc\AISC Workbench`。
- NSIS 使用该 key 写 `Installer Language` 与 PATH ownership marker；Rust 使用单一常量读取。CI 解析生成后的 `!define MANUFACTURER/PRODUCTNAME` 并与 Rust 常量断言一致。

## 六、G-13 Doctor 契约

CLI 已存在：

```text
aisc doctor --format json
```

Workbench 新增：

- Rust `doctor_argv()`；
- `DoctorReport/DoctorCheck` serde 类型；
- Tauri `run_doctor`；
- frontend IPC/TS 类型和 error view。

校验：

- `meta.protocol == aisc.cli/v1`；
- `meta.command == doctor`；
- process exit code 与 `meta.exit_code` 一致；
- `data.host.checks` 和 `data.host.summary` 类型合法；`data.container` 当前可为 `null` 或未来结构，未知字段忽略；
- 每个 check 可含 `name/status/message/detail?/hint?`，`hint` 不是 report-level 字段；
- timeout、stdout cap、stderr redaction 使用现有 runner。

失败时展示 Workbench domain error；不回退到解析 CLI 人类文本。

## 七、G-02 Resize 决策门

根因确认前，不预先承诺修改 CLI。

观测链：

```text
ResizeObserver
→ FitAddon rows/cols
→ resize_session IPC
→ portable-pty MasterPty::resize
→ Windows ConPTY / Unix PTY
→ aisc session open child
→ docker exec TTY
→ container foreground process
```

第一处 rows/cols 偏差决定修改层：

- 前端/IPC/PTY 偏差：在 Workbench 修复，不改 CLI 契约。
- `aisc session open`/docker exec 传播偏差：在 CLI 修复，并增加 CLI 直用 resize 回归。
- cc-switch 自身 redraw 问题：修复或上报 cc-switch，不用错误地重写 PTY 层。

## 八、CLI 回归矩阵

每次涉及 Python CLI/Rust argv 的提交至少验证：

| 场景 | 断言 |
|---|---|
| `version --format json` | envelope/capability 不变 |
| `runtime stop` 无 `--grace` | Fake executor timeout=10 |
| `runtime stop --grace 3` | Docker argv 为 `stop -t 3` |
| 非法 runtime grace（非整数、0、负数、>600） | exit 2/稳定 usage code/零 Docker 调用 |
| `session terminate` 无 grace | 默认 5；`0` 合法，负数/non-finite/>600 为 usage error且零 Docker 调用 |
| Workbench session argv | 同时含 `--workspace` 与 `--grace 3` |
| CLI 直用 session resize | 与 GUI 最终 rows/cols 一致（若 G-02 修改 CLI） |
| doctor | 正常、受控错误、无效 JSON/timeout 映射 |
| standalone AISC 与 Workbench 共存 | installer 不覆盖已有 `aisc`，Workbench sidecar discovery 仍可用 |

## 九、禁止事项

- GUI 不新增 Docker/registry 直接读写通道。
- 前端不构造 shell 字符串或接受任意 executable/arguments。
- 不为 Workbench 快路径改变 CLI 默认 stop/terminate grace。
- 不从 CLI 人类文本、终端内容或 `docker logs` 推断结构化状态。
- PATH 安装/卸载不得覆盖整个值或无所有权删除目录项。
- doctor、通知、标题、日志和错误详情不得包含密钥或终端内容。

## 十、契约验收

### A-G18-1 安装

- PATH 原无 `$INSTDIR`/其他 aisc：安装后新 PowerShell 的 `Get-Command aisc` 指向 `$INSTDIR\aisc.exe`，`aisc version --format json` 成功。

### A-G18-2 冲突

- PATH 已有 standalone AISC：Workbench 不覆盖或重排；交互/静默路径分别给出提示/日志；sidecar 绝对路径仍通过 capability。

### A-G18-3 升级与卸载

- 连续安装后 entry 恰好一次；最终卸载只删除 owned entry，sentinel 和 standalone PATH 均保留；`/UPDATE` 不留下缺失项。

### A-G18-4 注册表安全

- 空 PATH、`REG_EXPAND_SZ`、含 `%USERPROFILE%`、引号、尾斜杠、大小写和重复项均通过静态/实机测试。

### A-G02-1 链路观测

- 诊断模式对 ResizeObserver、FitAddon、IPC、portable-pty、CLI/docker exec 和容器探针记录同一 operation 的 cols/rows/timestamp；不记录终端内容。

### A-G02-2 根因门

- 固定 80×24、120×40、60×20 序列各重复 20 次，报告第一处偏差及证据；未完成报告前不允许修改其他层掩盖问题。

### A-G02-3 修复分支

- Workbench/Rust/CLI 分支各有对应自动化；若根因在 cc-switch，上游 issue/版本和复现证据记录为 `BLOCKED-UPSTREAM`，Bash 链路仍须通过。

### A-G02-4 端到端

- Windows ConPTY + Docker Desktop 下，布局稳定后 500ms 内容器 rows/cols 与 xterm 一致；cc-switch 连续 20 次 resize 无旧区域且光标可见。若改 CLI，standalone 同样通过。

### A-G07-4 参数与 workspace

- Python 全链路透传 runtime grace；Rust open/terminate argv 均含 selected canonical workspace；不同进程 cwd 不影响 Session 定位。

### A-G13-2 Doctor

- 成功、CLI error、timeout、stdout overflow、无效 envelope 均有稳定映射，且没有人类文本解析。
