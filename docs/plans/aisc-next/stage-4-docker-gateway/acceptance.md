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
- `A-DG05-1` Build CLI baseline 有 p50/p95/max；SDK 迁移有明确 GO/NO-GO。
- `A-DG06-1` application 不感知 backend；auto/sdk/cli flag 可回滚。
- `A-DG07-1` Fake/recording/fault injection 覆盖 daemon/permission/timeout/partial cleanup。
  - Commit：`7aa27d3`
  - 证据：`SdkLifecycleTests` 注入 start/stop/remove/wait 的 daemon_down/permission/wait_timeout；`wait_container` 修复 `requests.ReadTimeout` 逃逸（非 DockerException）→ 稳定 `DOCKER_ERR_TIMEOUT` + `timed_out=True`；remove 已不存在容器幂等 OK。
  - 步骤：Fake 生命周期故障 → 断言 error code / exit / timed_out / observed_state。
  - 结果：23 passed（query+lifecycle）；全库 pytest 497 passed。
  - 结论：PASS
- `A-DG08-1` Windows/Linux/macOS smoke、旧 CLI 回归、删除重复代码前用户确认。

每项记录 commit、平台/版本、步骤、结果、耗时和日志；无真实 Docker 环境不得宣称跨平台 PASS。