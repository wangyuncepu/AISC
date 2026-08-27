# Gate-S4 · 构建进度与 Docker 安装事件契约（已冻结）

> 2026-08-27 冻结。实现与 fixture 以本文为准；变更需回此文档先行修订。

## 1. `build.progress` 事件（随 `aisc.build-events/v2` 通道）

能力键 `buildEvents` 的值由 `aisc.build-events/v1` 升为 **`v2`**。v1 事件（start/plan/output/complete/failed/cancelled）原样保留；v2 新增一个事件类型，未知类型的消费端必须忽略（TS/Rust 均如此实现）。

```json
{"type":"build.progress","seq":7,"ts":"2026-08-27T12:00:00Z","data":{
  "phase": "prepare | pull | steps | export | done",
  "step_current": 3,
  "step_total": 12,
  "percent": 25.0,
  "progress_kind": "determinate | indeterminate",
  "summary": "RUN apt-get update",
  "log_path": "C:\\...\\logs\\build-1724760000.log"
}}
```

- `step_current/step_total/percent` 可为 `null`（不可靠即缺席）。
- **诚实规则**（Python 端保证，消费端只信字段）：
  - `percent` 仅在 `step_total>0` 且映射稳定时产生；单调不回退；`build.complete` 之前恒 `< 100`。
  - 拉取层为独立 `phase=pull`，`progress_kind=indeterminate`（字节级不做伪百分比）。
  - 解析不出的输出只进 `build.output`，不产生 progress 事件。
  - **修订（2026-08-27 手测第 2 轮）**：`phase=prepare` 的 `transferring context` 允许用**上一次构建日志的最终上下文字节数**做分母产生估算 `percent`——`step_total` 携带该估算字节数、`summary` 以 `≈` 前缀标注估算、prepare 阶段封顶 95、无估算数据时回退 indeterminate。估算分母永不写入 `step_current/step_total` 的步骤语义（`progress_kind` 仍为 determinate，字段语义按字节计）。
- `log_path`（仅 `build.start` 携带）：本次构建完整原始输出的落盘文件；UI 只渲染有界尾部窗口，完整日志经此路径打开。
- 解析源：BuildKit `--progress=plain`（`#12 [3/7] RUN …`、`#12 CACHED`、`#12 DONE`、`exporting to image`）与 legacy 构建器（`Step 3/12 : …`）。**不改 docker_argv**（不强制 `--progress`，避免 legacy builder 拒绝未知 flag）。
- 兼容：v1 消费端（旧 Workbench）忽略新事件，行为不变。

## 2. `docker-install-progress` 事件（Tauri 事件，非 CLI 通道）

```json
{"operationId":"uuid","backend":"winget | bundled",
 "phase":"install | engine_start",
 "state":"running | done | failed | timeout",
 "elapsedMs":125000,"deadlineMs":600000}
```

- 每 ≤5s 一拍心跳；同一 `operationId` 的晚到事件不得覆盖新 operation（前端按 id 过滤）。
- 超时：**kill + wait/reap 子进程**后才发 `state=timeout`；安装成功进入 `phase=engine_start`（独立 deadline，与安装 10min 分离）。
- 终态事件 `terminal:true` 语义由 `state∈{done,failed,timeout}` 承担。
- 不解析 winget/bundled 的人类输出；心跳只报已耗时与期限（D8）。

## 3. 测试锚点

- Python：`tests/cli/test_build_progress_parser.py`（双格式/乱序/CACHED/无 total/垃圾行/单调性/完成前<100）。
- Fixture：`tests/fixtures/cli/events-build-v2.jsonl`（含 progress 序列样本，三端对拍）。
- TS：store 处理 `build.progress` → 进度状态；未知 type 忽略不炸。
- 手测（A-2174x）：冷构建 %、全缓存构建（CACHED 步瞬时，仍单调）、断网降级 indeterminate。
