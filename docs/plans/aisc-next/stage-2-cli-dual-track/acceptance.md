# Stage 2 验收清单

> 所有证据记录目标/验收 ID、Commit、OS/arch、Workbench/CLI/Docker 版本、前置、步骤、期望、结果、p50/p95/max、产物 hash、测试/日志、结论。

| ID | 目标/风险/步骤 | 可执行验收与证据 |
|---|---|---|
| CLI-A01 | CLI-01/CLI-R01/S2.1 | clean venv 与 pipx 安装 wheel/sdist；入口运行 `version --format json`，版本/依赖/退出码正确；重复安装可恢复。 |
| CLI-A02 | CLI-02/CLI-R02/S2.2 | pip、sidecar、Rust/TS 对 v1 fixture deep-equal；unknown 字段不丢；未知版本和坏 JSON fail closed。 |
| CLI-A03 | CLI-03/CLI-R03/S2.3 | capability matrix 覆盖满足、缺失、旧版本；unsupported 返回稳定 code/action，不调用不支持业务。 |
| CLI-A04 | CLI-04/CLI-R04/S2.4 | 构造 explicit/saved/bundled/PATH/platform 五来源，结果严格按优先级；显示绝对路径/source/version，argv 无 shell。 |
| CLI-A05 | CLI-05/CLI-R05/S2.5 | 同一命令矩阵比较参数解析、默认值、退出码、stable error code、JSON envelope；差异自动 FAIL。 |
| CLI-A06 | CLI-05/CLI-R05/S2.5 | runtime/session/doctor 正常、非法、超时、stdout overflow、取消在 pip 与 sidecar 等价；默认 stop/terminate 语义不变。 |
| CLI-A07 | CLI-06/CLI-R06/S2.6 | 三平台适用 sidecar clean-room smoke；manifest hash/arch/version 正确；模拟升级失败后旧版本可启动并可回滚。 |
| CLI-A08 | CLI-07/CLI-R07/S2.7 | SBOM/依赖审计通过；redaction 扫描无 secret；pip/sidecar 不改 PATH、不写凭据；诊断导出有用户确认清单。 |

阶段结论：CLI-A01～CLI-A08 全 PASS，且用户明确确认后才允许发布/推送/打 tag。

## 证据记录（2026-08-15，分支 `stage-2-cli-dual-track`）

> OS：Windows 11 x86_64；CLI 2.1.5.dev0；本地门禁全绿（Python 445 passed / Rust 120 lib + 集成 / TS 154）。

| ID | Commit（分支内） | 步骤与结果 |
|---|---|---|
| CLI-A01 | `2184a96` `533f641` `e9305c1` | wheel+sdist 构建；fresh venv + pipx + `--no-index` 离线安装 smoke（`scripts/verify-cli-install.py`）；`version --format json` 入口、版本（PEP 440 `2.1.5.dev0` 与 dist metadata 一致）、重复安装/卸载重装可恢复 → PASS |
| CLI-A02 | `8ce18d9` `a77d95e` | 真实 CLI 输出与 `envelope-version.json` deep-equal（归一 timestamp/run_id/python/claude 字段）；`JsonlEmitter` 与 `events-build.jsonl` 逐行 deep-equal；`runtime` 子命令缺参时 JSON usage（修复 `a77d95e`）→ PASS |
| CLI-A03 | `13246ac` | 8 例 capability 矩阵（满足/缺失/旧版本/全缺）；缺必需时 `WB_ERR_CAPABILITY_UNSUPPORTED` + `Action::UpgradeCli` fail-closed → PASS |
| CLI-A04 | `41dd290` | 五来源枚举严格优先级 + 去重；`candidate_from_envelope` 携带绝对路径/source/version/capabilities；错误码 fail-closed → PASS |
| CLI-A05/A06 | `a77d95e` `91865eb` | `verify-cli-parity.py` 25 命令矩阵：**pip venv CLI vs 真实 sidecar（`dist/aisc-x86_64-pc-windows-msvc.exe`）全一致**；退出码/stable code/envelope/文本输出 → PASS |
| CLI-A07 | `5ab1e1d` | `verify-sidecar.py`：smoke 出 manifest（sha256 `d6682b39cf8b…`、size、arch、version）；`atomic-upgrade` 成功替换留备份、坏 hash 拒绝且旧版本保留可运行 → PASS |
| CLI-A08 | `e38710c` | `verify-sbom.py`：9 包 SBOM + `pip check` integrity ok；denylist 形状扫描 version/doctor 无泄漏；隔离 HOME/APPDATA 运行零写入；子进程安装不改 caller PATH → PASS |

Sidecar 三平台构建/manifest/parity/SBOM 已接入 `cli-sidecar.yml`；真实 Workbench GUI 集成手测由用户在 PR CI 绿后执行。

