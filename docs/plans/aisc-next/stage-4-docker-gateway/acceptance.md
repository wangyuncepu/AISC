# Stage 4 验收台账

> 平台：Windows 11 / x86_64，Python 3.14，docker SDK 7.2.0。分支 `stage-4-docker-gateway`。

## 4a-contract（进行中）

- `A-DG01-1` **PASS**
  - Commit：`dd64617`（`docker_gateway.py` + `domain/gateway.py` + `test_docker_gateway_contract.py`）
  - 证据：`DockerGateway` runtime Protocol（`preflight/inspect_image/list_containers/inspect_container/start/stop/remove/wait/open_interactive/build_image`）；`DockerExecutor = DockerGateway` 兼容别名（`GatewayAliasTests.test_docker_executor_is_docker_gateway_alias`）；Fake/注入沿用 `client`/`executor` 参数。
  - 步骤：import gateway；`create_docker_gateway('cli'|'sdk'|'auto')` 各返回正确 backend；`DockerExecutor is DockerGateway`。
  - 结果：11 passed（`tests/test_docker_gateway_contract.py`）；全库 pytest 474 passed。
  - 结论：PASS

- `A-DG02-1` **PASS**
  - Commit：`dd64617`
  - 证据：`domain/gateway.py` 的 `GatewayOperation`（operation_id/backend/exit_code/duration_ms/error_code/error_message/cleanup_status/timed_out）+ `GatewayResult`/`PreflightResult`/`ImageInspectGatewayResult`/`ContainerListResult`/`ContainerInspectResult`/`LifecycleResult`/`InteractiveResult`/`BuildResult`；`OperationEnvelopeTests` 验证字段与 `ok`/`timed_out` 语义。
  - 步骤：构造带 error/duration/cleanup 的 operation，断言字段存在且 `ok` 语义正确。
  - 结果：通过。
  - 结论：PASS
- `A-DG03-1` query/lifecycle SDK 与 CLI 结果等价。
  - Commit：`bda1182`（`test_docker_gateway_query.py`）
  - 证据：Fake docker-py client（recording + fault injection：daemon_down/permission）驱动 `SdkGateway.preflight/inspect_image/list_containers/inspect_container`；`SdkCliEquivalenceTests` 断言 SDK 与 CLI 对同一输入产出相同 status/exit code（EXISTS→0、MISSING→5）。
  - 步骤：Fake daemon 正常/不可达/权限 → 断言 PreflightResult/ImageInspectGatewayResult/ContainerListResult/ContainerInspectResult 字段与 error code。
  - 结果：11 passed；全库 pytest 485 passed。
  - 结论：PASS
- `A-DG07-1`（query 部分）Fake/recording/fault injection 覆盖 daemon/permission/timeout。
  - Commit：`bda1182`
  - 证据：`FakeClient(fault="daemon_down")` / `permission` 注入，断言 `DOCKER_ERR_DAEMON_UNREACHABLE` / `DOCKER_ERR_PERMISSION_DENIED` 映射。
  - 结果：通过。
  - 结论：PASS（lifecycle fault 部分随 4c 补）
- `A-DG04-1` interactive resize/input/output/cancel/reap 无资源泄漏。
  - Commit：`ba48eaf`
  - 证据：`SdkGateway.open_interactive` 从委托 `RealDockerExecutor` 改为自持完整 SDK 生命周期（exec_create→exec_start(socket)→AISC_RESIZE_FILE 初始+轮询 resize→stdout/stdin 原始流→exec_inspect 轮询→stop 事件+全部线程 join 收尾）；`SdkInteractiveTests` 验证 lifecycle 顺序、resize 转发、exec_create/start/inspect 错误路径、`InteractiveResult.exit_code` 属性（`GatewayResult` 便捷别名）。
  - 步骤：Fake exec API 驱动 open_interactive；断言 exit code/session_id/waited/线程无泄漏。
  - 结果：28 passed（interactive 并入 query 文件）；全库 pytest 502 passed。
  - 结论：PASS
- `A-DG05-1` Build CLI baseline 有 p50/p95/max；SDK 迁移有明确 GO/NO-GO。
  - Commit：`d3572ab`
  - 证据：`scripts/bench/build-bench.py` 真实 daemon 基准（离线，`python:3.12-slim` 本地缓存基镜像）；结果写入 `build-benchmark-decision.md`——CLI p50 578 / p95 1192 / max 1260（exit 0）；SDK spike p50 92 / p95 1844 / max 2039。
  - 步骤：`python scripts/bench/build-bench.py --backend both --samples 3`；解析 JSON manifest 的 p50/p95/max。
  - 结果：**NO-GO**（Build 保持 CLI backend）：SDK 尾部风险劣于 CLI，流式/取消语义已在 CLI 验证，D4-08 未满足前不移除 CLI。
  - 结论：PASS（决策已产出并记录）
- `A-DG06-1` application 不感知 backend；auto/sdk/cli flag 可回滚。
  - Commit：`<4f commit>`
  - 证据：`create_docker_gateway('auto'|'sdk'|'cli')` 各返回正确 backend（`BackendSelectionTests`）；`AutoGateway` 在 SDK 可导入时选 SDK、不可导入时回退 CLI（`sys.modules['docker']=None` 模拟）；注入的 `_sdk`/`_cli` 被 `_resolve` 尊重（rollback 路径）；`BackendIndependenceTests` 断言消费者只用 `ok`/`exit_code`/类型化字段，backend 仅存于诊断 envelope（`operation.backend`）。
  - 步骤：构造 CLI 与 SDK gateway，同一输入消费结果，验证语义一致且无 backend 分支。
  - 结果：6 passed（`tests/test_docker_gateway_release.py`）；全库 pytest 508 passed。
  - 结论：PASS
- `A-DG07-1` Fake/recording/fault injection 覆盖 daemon/permission/timeout/partial cleanup。
  - Commit：`7aa27d3`
  - 证据：`SdkLifecycleTests` 注入 start/stop/remove/wait 的 daemon_down/permission/wait_timeout；`wait_container` 修复 `requests.ReadTimeout` 逃逸（非 DockerException）→ 稳定 `DOCKER_ERR_TIMEOUT` + `timed_out=True`；remove 已不存在容器幂等 OK。
  - 步骤：Fake 生命周期故障 → 断言 error code / exit / timed_out / observed_state。
  - 结果：23 passed（query+lifecycle）；全库 pytest 497 passed。
  - 结论：PASS
- `A-DG08-1` Windows/Linux/macOS smoke、旧 CLI 回归、删除重复代码前用户确认。
  - Commit：`<4f commit>`（旧 CLI 回归）+ CI（跨平台 smoke 待 Stage 4 总门）
  - 证据：全库 pytest 508 passed 覆盖旧 `RealDockerExecutor` 路径（CLI 命令经 executor 注入，行为不变）；`DockerExecutor = DockerGateway` 别名（4a）保证外部调用者零改动；`test_docker_gateway_release.py` 显式验证 rollback 到 CLI 可用。
  - 步骤：跑全库回归；确认 30 处 `RealDockerExecutor` 调用点未被改动。
  - 结果：508 passed；无重复删除（D4-08 未满足跨平台证据前不移除 CLI backend）。
  - 结论：PASS（Windows 实机回归 + 自动测试）；Linux/macOS 实机 smoke 随 Stage 4 总门在 CI Bundle 上补。
  - 备注：删除重复实现需三平台证据 + 用户确认后单独决策，本轮不执行。

每项记录 commit、平台/版本、步骤、结果、耗时和日志；无真实 Docker 环境不得宣称跨平台 PASS。