# HANDOFF — 暂停交接文档

> **日期**：2026-07-17（周五）
> **当前 commit**：`1014acb` — `feat(v3): 增加只读配置验证命令`
> **示意图：**
> `c706a68 → c95bd45 → a8cee46 → 4508248 → 238eed8 → 5105495 → 4894ef0 → 1014acb`
> **停止位置**：S5.2 已完成并提交。**S5.3 尚未开始**。
> **目标读者**：接手开发者（Claude Code / 人工）。

---

## 1 关键历史 commit（按时间正序）

| Commit | 说明 |
|--------|------|
| `c706a68` | `docs(v3)`: 制定统一 CLI 分阶段实施计划（`PLAN-p3-unified-cli.md`） |
| `c95bd45` | `test(v3)`: 冻结 CLI 协议与 Legacy 行为基线（feature tests、harness、RFC） |
| `a8cee46` | `feat(v3)`: 实现只读 Python CLI 基础（`version`/`doctor`、`pyproject.toml`） |
| `4508248` | `feat(v3)`: 实现 Docker planner 与 executor（`build`/`run`、`docker_.py`） |
| `238eed8` | `feat(v3)`: 构建可验证的 CLI workflow 制品（`packaging/artifact.py`、CI artifact） |
| `5105495` | `docs(v3)`: 收紧 S5 copy-only 迁移契约（更新 `PLAN-p3-unified-cli.md`） |
| `4894ef0` | `feat(v3)`: 建立安全的配置发现模型（config domain/schema/source） |
| `1014acb` | `feat(v3)`: 增加只读配置验证命令（`config validate`/`effective`）← **HEAD** |

---

## 2 当前新 CLI 预览命令

以下命令**全部可用**，运行方式均为（项目根目录下）：

```bash
PYTHONPATH=src python3 -m aisc <command>
```

| 命令 | 说明 |
|------|------|
| `aisc version` | 版本信息（`--format text\|json`） |
| `aisc doctor` | 环境诊断（text/json） |
| `aisc build [--dry-run]` | Docker 镜像构建（`--tag`、`--no-cache`、`--pull`） |
| `aisc build --dry-run` | 构建计划预览（不执行） |
| `aisc run [--dry-run]` | 容器运行（`--image`、`--workspace`、`--name`、`--network direct\|proxy`） |
| `aisc run --dry-run` | 运行计划预览（不执行） |
| `aisc config validate` | 配置校验（`--config`、`--workspace`） |
| `aisc config effective` | 有效配置输出（脱敏，text/json） |

**重要**：这些命令**不替代** `start.sh` / `start.bat` / `start.command`。旧入口依然是用户的默认路径。CLI 目前仅用于开发和 CI。

---

## 3 S5.2 交付物与只读边界

### 3.1 S5.2 文件清单

S5.2 新增/修改文件（commit `4894ef0` + `1014acb`）：

| 文件 | 作用 |
|------|------|
| `src/aisc/domain/config.py` (540 行) | 配置领域模型：`PlatformPathConfig`、`PathPolicy`、`CredentialValue`、provider ID grammar、secret_ref 解析、冲突规则 |
| `src/aisc/schemas/config_schema.py` (499 行) | config.json 最小 schema 校验（用户级 + workspace 级） |
| `src/aisc/adapters/config_source.py` (235 行) | source inventory 只读发现（精确路径枚举，不递归搜索） |
| `src/aisc/adapters/config_reader.py` (215 行) | 安全文件读取（POSIX `O_NOFOLLOW`，16KB 限制，平台分派） |
| `src/aisc/adapters/windows_config_reader.py` (249 行) | Windows ctypes kernel32 原生读取（可注入 backend） |
| `src/aisc/application/config_service.py` (445 行) | `config validate` / `config effective` 服务层 |
| `src/aisc/cli/commands/config.py` (104 行) | CLI 命令实现薄层 |
| `src/aisc/cli/main.py` (551 行) | CLI 入口（新增 `config` 子命令分派） |
| `tests/unit/test_config_domain.py` (204 行) | domain 模型单元测试 |
| `tests/unit/test_config_schema.py` (277 行) | schema 校验单元测试 |
| `tests/unit/test_config_source.py` (262 行) | source inventory 单元测试 |
| `tests/unit/test_config_service.py` (337 行) | config service 单元测试 |
| `tests/unit/test_config_s5_final.py` (564 行) | S5.2 终审集成测试（42 tests） |
| `tests/unit/test_windows_reader.py` (533 行) | Windows reader 单元测试（含 ABI tests + fake backend + 7 real tests） |

### 3.2 只读边界（强制）

**S5.2 不得读/写的目录与文件**：

| 禁止访问 | 原因 |
|----------|------|
| `secrets/` 目录及其内容 | S5.3 才开始 |
| `.aisc/secrets/api-keys` | 保密数据，S5.4 migrate 才读 |
| `.cc-config/api-keys` | 保密数据 |
| `.claude/api-keys` | 历史候选路径 |
| `.claude/settings.json` | S5.4 才读 |
| `.aisc/state.env` / `.deploy/state.env` | legacy state，只允许 S5.4 以后报告 |
| Provider catalog / `providers.json` | S5.3 以后 |
| 任何 migration / journal / HMAC / cleanup 逻辑 | S5.3/S5.4/S5.5 专属 |

**config validate/effective 仅读** `config.json`（用户级 + workspace 级）。不访问任何密钥文件。

### 3.3 user + workspace 路径与 overlay

- **user 层（用户级）**：由平台决定，默认路径见 PLAN §8.1 表。
  - Linux: `$XDG_CONFIG_HOME/aisc/config.json`（默认 `~/.config/aisc/config.json`）
  - macOS: `~/Library/Application Support/aisc/config.json`
  - Windows: `%APPDATA%/aisc/config.json`
- **workspace 层（项目级）**：`<workspace>/.aisc/config.json`
- 可通过 `--config` 显式指定 user config 路径；`--workspace` 指定 workspace 根。

**overlay 字段**（config service `_overlay` 函数，`config_service.py:153-169`）：

| 字段 | 说明 |
|------|------|
| `provider.id` + `auth.secret_ref` | 从 user/workspace config 提取，secret_ref 生成为 `provider:<id>` |
| `defaults.profile` | `"safe"` 或 `"unsafe"` |
| `defaults.network` | `"direct"` 或 `"proxy"` |

**precedence（优先级）**：workspace 层覆盖 user 层。provenance 记录每个字段的来源（`"user"` / `"workspace"` / `"derived"` / `"default"`）。

### 3.4 退出码（所有 S5.2 已实现路径）

| exit_code | 含义 | 触发条件 |
|-----------|------|----------|
| `0` | 成功 / 配置有效 | 无错误 |
| `1` | 通用/结构性错误 | 路径是 symlink/reparse point/非目录、OS 错误 |
| `2` | 用法错误 | 未指定命令、未知子命令、`--format json --events` 互斥 |
| `6` | 配置无效 | `AISC_ERR_CONFIG_INVALID`：schema 校验失败 |
| `7` | 配置缺失 | `AISC_ERR_CONFIG_MISSING`：显式 `--config` 路径不存在 |
| `9` | 权限不足 | `AISC_ERR_PERMISSION_DENIED`：无法读取配置路径 |

### 3.5 JSON 约束（S5.2 reader 级别）

| 限制 | 值 |
|------|----|
| 最大原始文件字节数 | **16 KB**（`MAX_FILE_BYTES`） |
| 最大嵌套深度 | **20**（`MAX_JSON_DEPTH`） |
| 最大 JSON 节点数 | **2000**（`MAX_JSON_NODES`） |
| 最大字符串字节数 | **8192**（`MAX_JSON_STRING_BYTES`） |
| 禁止重复 key | `object_pairs_hook` 去重检测 |
| 编码 | **UTF-8 only**（非 UTF-8 → `ContentErrorKind.INVALID_UTF8`） |
| 文件类型 | 必须为常规文件（POSIX `S_ISREG`，Windows `FILE_TYPE_DISK`） |
| 禁止 symlink/reparse point | POSIX `O_NOFOLLOW` + `S_ISLNK` 拒绝；Windows `FILE_FLAG_OPEN_REPARSE_POINT` + reparse 拒绝 |

---

## 4 安全措施细节

### 4.1 reader 安全措施（`config_reader.py`）

- **POSIX**：`os.lstat` → 拒绝 symlink（`S_ISLNK`）/ 目录（`S_ISDIR`）/ 非普通文件（`!S_ISREG`）。`os.open(fp, os.O_RDONLY | os.O_NOFOLLOW)` → `os.fstat` 再次确认 `S_ISREG`。分块读取（4096 bytes/chunk），总大小 ≤ 16KB。
- **Windows**：`CreateFileW` → `GetFileAttributes`（拒绝 `FILE_ATTRIBUTE_REPARSE_POINT` / `FILE_ATTRIBUTE_DIRECTORY`）→ `GetFileType` **必须等于 `FILE_TYPE_DISK`（`0x0001`）**。逐父目录 component open（拒绝 reparse point / 非目录）。
- 平台分派：`safe_read_config_bytes` 在 `os.name == "nt"` 时分派到 Windows reader，否则 POSIX。
- `check_root_exists` / `check_dir_component`：额外 root 和 `.aisc` 目录验证，使用平台原生 API（`lstat` / `CreateFileW` + `BACKUP_SEMANTICS`）。

### 4.2 Windows `FILE_TYPE_DISK == 0x0001`

`windows_config_reader.py:24` 明确定义：
```python
FILE_TYPE_DISK = 0x0001
```
`GetFileType` 返回非 `FILE_TYPE_DISK` 的任何值（包括 `FILE_TYPE_UNKNOWN`（0x0000）、`FILE_TYPE_CHAR`（0x0002）、`FILE_TYPE_PIPE`（0x0003））均被拒绝。`FILE_TYPE_UNKNOWN` 时额外检查 `GetLastError() != 0`。

### 4.3 explicit config lexical `abspath`

`config_service.py:184`：
```python
explicit_config = os.path.abspath(explicit_config)
```
在**任何** workspace early return 之前执行 `abspath`，确保两条 source（user + workspace）身份在返回数据中始终保持固定——即使后续发生 `FileNotFoundError`/`PermissionError` 等 early return，source info 中的 `path` 字段也已经是绝对路径。

---

## 5 Windows 验证状态（**诚实注明**）

- **真实 Windows runner 未执行**。所有测试均在 Linux 上运行。
- `tests/unit/test_windows_reader.py` 第 278 行：`@unittest.skipUnless(os.name == "nt", "Windows only")` — **7 个 real Windows tests** 在 Linux 上全部 **skipped**。
- Windows ABI tests（sizeof 52、field order、exact offsets、FILETIME 8 bytes、AST proof）在 Linux 上通过，但不构成真实 Windows 验证。
- **不可宣称完整 Windows 验证**。在真实 Windows runner 上执行完整测试套件后方可宣称。
- **不可未经批准 push 以触发 CI**。CI 的 Windows runner 也需 gate 确认后再触发。

---

## 6 下一步：**仅 S5.3**（不得越界）

### 6.1 S5.3 目标

**secure store adapter**（`src/aisc/adapters/secret_store.py`）：

1. **平台原生路径解析**：
   - Linux: `$XDG_CONFIG_HOME/aisc/`, `$XDG_STATE_HOME/aisc/`, `$XDG_DATA_HOME/aisc/secrets/`
   - macOS: `~/Library/Application Support/aisc/`
   - Windows: `%APPDATA%/aisc/config`, `%LOCALAPPDATA%/aisc/state` + `secrets/`
2. **POSIX owner/mode**：目录 0700、文件 0600、owner 校验。**必须提供实际 `os.stat` 证据**，不能仅 mock。
3. **Windows DACL**：current user SID + SYSTEM full control，禁继承、拒绝 Everyone/Users/Authenticated Users。**必须写后回读验证**，失败 exit 9。**DACL 的真实设置与回读验证是本切片的完成条件**，不允许以未接线 stub 延后。
4. S5.3 只提供后续安全写入所需的 secure-store 原语与权限验证；migration HMAC key、journal、迁移锁和 copy-only 流程均属于 **S5.4**，不得提前接入业务迁移。

### 6.2 不可越界事项

| 禁止 | 原因 |
|------|------|
| ❌ 迁移/复制任何 legacy secret | S5.4 专属 |
| ❌ cleanup 任何文件 | S5.5 专属（且 S5.5 也仅是拒绝 stub） |
| ❌ 读取或修改 `.cc-config/api-keys`、`.aisc/secrets/`、`.claude/settings.json` | S5.4 才读 |
| ❌ 读取/修改 `providers.json` | S7 专属 |
| ❌ 修改 `claude-switch` 或 `cs` 行为 | S7 专属 |
| ❌ 实现 profile 解析 | S6 专属 |
| ❌ 删除 legacy Bash/PS 脚本 | S11 专属（需用户单独批准） |
| ❌ 切换 `start.*` 默认入口 | S10 专属（需分发授权门 + 用户批准） |

---

## 7 后续切片顺序（严格单向依赖）

```
S5.1 → S5.2 → S5.3 → S5.4 → S5.5 → S6 → S7 → S8 → S9 → S10 → S11
```

- **S5.3**（当前下一步）：secure store adapter
- **S5.4**：config migrate + journal（copy-only）
- **S5.5**：cleanup 拒绝 stub（exit 11，零读写）
- **S6**：最小 safe/unsafe resolver + network 正交
- **S7**：Provider 唯一权威路径 + 端到端 non-interactive
- **S8**：容器契约 / 安全默认 / 移除 wrapper 默认 unsafe
- **S9**：CLI 机器协议稳定化
- **S10**：默认入口切换（需分发授权门 + 用户批准）
- **S11**：观察期后删除 legacy（需用户批准）

---

## 8 需要重新用户批准的危险动作

以下操作**不能**在无用户明确批准的情况下执行：

| 编号 | 动作 | 触发条件 | 当前状态 |
|------|------|----------|----------|
| D1 | **cleanup 旧密钥** | `aisc config cleanup` 真实执行（非 stub） | S5.5 仅 stub；真实 cleanup 不早于 v3.1.0/2026-09-01 |
| D2 | **push / PR / release / OSS 发布** | 任何时候 | 当前一切本地 |
| D3 | **删除 legacy Bash/PS 脚本** | S11 | 需用户批准 + ≥2 周观察期 |
| D4 | **切换 start 默认入口到新 CLI** | S10 | 需分发授权门 + 用户批准 + S8+S9 完成 |
| D5 | **触发 CI（含 Windows runner）** | push | 当前未 push |

### 8.1 legacy credential 潜在路径（供参考，**不在 S5.3 范围内**）

| 路径 | 格式 | 内容 |
|------|------|------|
| `<workspace>/.cc-config/api-keys` | `KEY=VALUE` | provider API keys（每 provider 一个） |
| `<workspace>/.aisc/secrets/api-keys` | `KEY=VALUE` | 同上（v2.0.0-p1.4 迁移副本） |
| `<workspace>/.claude/api-keys` | `KEY=VALUE` | 历史候选，非 active 源 |
| `<workspace>/.claude/settings.json` | JSON `env` 块 | `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` 明文（Claude Code 运行依赖写入） |
| `<aisc_root>/.aisc/state.env` | `KEY=VALUE` | runtime 状态 |
| `<aisc_root>/.deploy/state.env` | `KEY=VALUE` | runtime 状态（旧目录） |

**当前（S5.2）状态**：以上路径均**未被 CLI 读取**。仅 `config_source.py` 枚举其 descriptor 作为 source inventory，不实际 read。实际读取在 S5.4 migrate 阶段进行。

---

## 9 验证命令与最终 S5.2 证据

### 9.1 验证命令

```bash
# 全量测试（results: 718 passed, 7 skipped）
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'

# 聚焦 config-specific 测试（139 passed, 7 skipped）
PYTHONPATH=src python3 -W error::ResourceWarning -m unittest \
  tests.unit.test_config_service \
  tests.unit.test_config_s5_final \
  tests.unit.test_windows_reader -v

# Wheel/入口打包 smoke（6 项）
bash tests/smoke/packaging_smoke.sh

# 语法检查（69 files）
bash tests/smoke/check-syntax.sh

# 文档一致性检查（54 checks）
bash tools/check-docs.sh
```

### 9.2 最终 S5.2 测试证据（devlog 记录）

| 指标 | 数值 |
|------|------|
| config-specific tests | **256**（S5.1: 117 + S5.2: 139） |
| total tests (full suite) | **718 passed** / **7 skipped** |
| packaging tests | **6 passed** |
| syntax check files | **69** |
| docs consistency checks | **54** |
| ResourceWarning | `-W error::ResourceWarning` **clean** |
| 连续通过 | **连续两次**全量通过 |
| 跳过的测试 | 7 个 `skipUnless(nt)` real Windows tests |

### 9.3 已知缺口（如实记录，不作为已完成）

- **Windows real runner 未执行**：7 个 `skipUnless(nt)` tests local skipped。
- **Parent race**：POSIX reader 不在 component-by-component 遍历父目录后再验证最终文件。
- **Full handle-relative traversal**：Windows reader 当前逐父 component open + 最终文件 open，但非 handle-relative traversal。
- **DACL**：已延期到 S5.3。

---

## 10 文档/提交维护规则

1. **提交粒度**：每个 S5.x 切片至少一个独立 commit；复杂切片允许多个 commit，但每个 commit 必须可独立理解。
2. **commit message 格式**：`<type>(v3): <中文简述>`，type 为 `feat`/`test`/`docs`/`fix`/`refactor`。
3. **devlog 更新**：每个 S5.x 切片完成后在 `docs/devlog.md` 追加条目，记录修改文件、验证数字、已知缺口。
4. **plan 同步**：若实施过程中发现 plan 与实际不符，需更新 `docs/plans/PLAN-p3-unified-cli.md` 对应段落，并在 devlog 注明差异。
5. **禁止修改其他文件**：每个切片只修改其声明范围内的文件。特别禁止在 S5.3 修改 `start.*`、`scripts/*`、`container/*`。
6. **HANDOFF 更新**：若本交接文档中记录的信息在执行过程中发生变化（如验证数字更新、新发现的风险），需更新本文档对应条目。

### 10.1 接手时优先校正的记录项

以下内容在本次暂停前已发现口径需要进一步核对，按用户要求保留在交接记录中，暂不修改主体章节：

1. 文档中的测试统计同时出现“718 passed / 7 skipped”和“256 config-specific”等表述；实际 `unittest` 汇总是 718 个测试案例，其中 7 个 Windows-only 测试 skipped。接手后应统一统计口径，并以实际命令输出为准。
2. 验证命令必须使用项目当前采用的 stdlib `unittest` 与 `tests/smoke/packaging_smoke.sh`，不要改写为未声明依赖的 pytest 命令。
3. `config_source.py` 提供了独立 source inventory/discovery 能力；S5.2 的 `config validate/effective` 执行路径不应调用 legacy credential/state reader。接手时需区分“模块提供能力”和“当前命令实际调用路径”。
4. S5.3 只负责 secure-store 原语与平台权限验证；migration HMAC key、journal、迁移锁和 copy-only 流程属于 S5.4，不能提前接入 S5.3。
5. 真实 Windows runner 尚未执行，Linux 上的 mock/ABI 测试不能替代 Windows 实机证据。

---

**全文结束。**
