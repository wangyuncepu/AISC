# 全流程全生命周期日志（新接口：aisc logs + 界面双入口）

分支：`lifecycle-logging`（自 develop）。目标：用户遇到问题时，一条 run_id
串起「界面操作 → CLI 调用 → 容器操作」完整时间线，CLI 与界面双入口可查、
诊断包自动携带。

## 用户决策（2026-08-20，AskUserQuestion）

1. **单一时间线单文件**：`<数据根>/logs/aisc.log`，Rust(app) 与 Python(cli)
   双端追加 JSONL；轮转 2MB×3（当前+2 历史，≤6MB 磁盘封顶）。
2. **双入口**：新增 `aisc logs` 命令组 + 诊断对话框内嵌「最近日志」折叠段 +
   诊断包自动附日志尾。
3. **带容器日志尾随**：诊断包收集所有 `io.aisc.managed` 容器
   `docker logs --tail 50`。

## 现状（摸底结论）

- Rust `trace.rs`：64 条内存 op 耗时环（process-local，**不落盘**），进
  Doctor 对话框与诊断包（允许清单制，D6-05/06）。
- Python CLI：envelope `meta.run_id`（每次调用 uuid4）只活在 stdout，无处
  持久化；无 logging 模块使用。出口收口点：`main.py` 的 `emit_json`（成功/
  错误两处）与 `emit_json_usage_error`。
- 容器侧：entrypoint/mihomo 日志只在 docker logs 里，我们从不采集。
- 诊断包（doctor.rs）：版本/平台/脱敏 settings/环境就绪/doctor 报告/op 环/
  data root——无日志、无容器尾随。

## 事件 schema（红线：字段允许清单制）

一行一事件 JSONL：

```json
{"ts":"2026-08-20T05:40:00Z","level":"info","source":"app|cli",
 "event":"app_start|app_quit|cli_exit|cli_usage_error|op_ok|op_error|container_created|container_ready|container_removed|...",
 "run_id":"uuid","command":"runtime start","duration_ms":123,
 "exit_code":0,"error_code":"AISC_ERR_...","detail":"..."}
```

- **永不入日志**：stdin 载荷、订阅 URL、API key、PTY 内容、完整环境变量、
  工作区绝对路径（容器事件用 runtime_id 短前缀/容器名即可）。schema 固定
  键 + detail 限枚举描述——脱敏靠构造而非过滤（照 D6-05/06 哲学）。
- 关联链：Rust 每次 CLI 调用生成 op id → 子进程 env `AISC_RUN_ID` 注入 →
  CLI envelope `meta.run_id` 复用该值 + 日志行同值 → app 侧 op 事件与 cli
  侧 cli_exit 行天然对齐。CLI 独立使用（无 env）时自生 uuid，现状不变。

## 阶段划分

### P1 数据面：双端 appender + 轮转 + 关联链

- **Rust**：新 `logging.rs`（append+rotate+初始化自 data_root；`logs` 目录
  常量入 `data_root.rs`）；`trace.rs` 的 record 处加文件 sink（OpTrace 原样
  落盘，内存环保留）；`lib.rs` 启动时写 `app_start`；`cli.rs` spawn 处注入
  `AISC_RUN_ID` env；`runtime.rs` 容器生命周期关键点（created/ready/removed/
  conflict）打点。
- **Python**：新 `src/aisc/applog.py`（append_event+rotate，阈值常量与 Rust
  一致）；`main.py` 出口收口两处（emit_json 前 + usage error 前）落
  `cli_exit`/`cli_usage_error` 行（command/exit_code/run_id/duration_ms/
  error codes）；run_id 读 env `AISC_RUN_ID` 传入 build_envelope。
- 测试：双端 rotate（小阈值）、run_id 注入复用、cli_exit 行字段、app 事件
  打点（runtime.rs 单测模式）。

### P2 CLI 接口：aisc logs 命令组

- `aisc logs show [--lines N=200] [--source app|cli|all] [--format json|text]`
  → data `{path, lines:[事件对象]}`；text 渲染 `ts LEVEL source event detail`。
- `aisc logs path` → data `{path}`（脚本/界面定位用）。
- 读尾实现：文件 ≤6MB 直接行数组取尾（不做 seek 优化，规模不需要）。
- 测试：注入 tmp 数据根，断言过滤/行数/格式。

### P3 界面入口：诊断对话框 + 诊断包

- Rust `logs_tail` 命令（直读文件取尾，不经 CLI——少一次子进程；组件仍不
  直连 ipc，走 doctor store，F-A01 不破）。
- DoctorDialog 新增「最近日志」原生折叠段（details/summary，默认收起）：
  最近 100 行 + 复制按钮（照 RuntimeSidebar 开发者详情模式）。
- `DiagnosticBundle` 增 `recent_log_lines`（最近 100 事件对象）。
- i18n 双语成对 + vitest。

### P4 容器日志尾随进诊断包

- `diagnostic_bundle` 生成时：`docker ps --filter label=io.aisc.managed=true`
  → 每容器 `docker logs --tail 50`（docker CLI 子进程，复用既有候选链）→
  `container_logs: [{name, id, tail}]`；docker 不可用整节跳过。
- 容器 stdout 本身无机密（mihomo/entrypoint 日志）；照旧不采集挂载内容。

### P5 收口

手测矩阵：正常启动工作区 → aisc.log 出现 app_start→op→cli_exit 同 run_id
链；关引擎制造失败 → error 行 + 诊断包带日志尾+容器尾随；DoctorDialog 最近
日志段显示与复制；`aisc logs show` 各参数；超阈值轮转（单测小阈值覆盖）。
`--no-ff` 合并 + 四 CI。

## 边界与不做

- 不做实时 follow/tail -f（下轮有需求再说）；不做日志上传遥测（永远本地）；
- 不改既有 trace 环语义（内存环照旧，文件 sink 是增量）；
- PTY/会话内容永不入日志（D6-06 红线延续）；
- Python 端不改用 logging 框架（保持无配置、单点 appender，测试环境零噪声）。

## 门禁与产物

- python 全测 / cargo --lib / vitest + vue-tsc（P3 起）/ sidecar 重建同步。
- container/ 不动 → 无 vendor 刷新。
- 新增文档：本计划 + todo.md 新块；02 契约文档（事件 schema 冻结）随 P1 落。
