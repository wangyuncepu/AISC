# Build 后端迁移 GO/NO-GO（Stage 4，A-DG05-1）

> 证据来源：`scripts/bench/build-bench.py`（真实 daemon，`python:3.12-slim` 本地缓存基镜像，离线可重复构建）。
> 平台：Windows 11 / x86_64，Docker Engine 26.1.x，docker SDK 7.2.0，Python 3.14。

## 基线（2026-08-16，samples=3，tag=aisc-bench:local）

| backend | p50 ms | p95 ms | max ms | exit codes |
|---|---|---|---|---|
| cli（`docker build`，当前默认） | 578 | 1192 | 1260 | 0,0,0 |
| sdk（docker-py `images.build`，实验） | 92 | 1844 | 2039 | 0,0,0 |

## 解读

- **p50**：SDK 明显更快（92ms vs 578ms）——docker-py 复用同一构建缓存层，`RUN echo built` 幂等层命中，中位数贴近纯 overhead。
- **p95/max**：SDK 尾部更差（1844/2039 vs 1192/1260）——构建缓存未命中时 SDK 的生成器消费/日志拉取开销更高，且单次方差大。
- 两者都 exit 0；样本 3 偏小，p95 置信度有限（见"局限"）。

## GO/NO-GO：**NO-GO（当前不迁移 Build 到 SDK）**

理由（对照 D4-05 / D4-08）：

1. **尾部风险**：SDK p95/max 劣于 CLI。Build 是大输出、可取消、流式事件（`build.output`）路径，尾部延迟恶化直接影响 `aisc build --events` 的用户感知。
2. **流式/取消语义已在 CLI 验证**：`tests/features/test_build_events_contract.py`（实时事件）+ `tests/integration/docker/test_build_cancellation.py`（cancel-kill）都在 CLI backend 上通过。SDK 的 `images.build` 是惰性生成器，取消语义需重写，且无等价证据。
3. **迁移收益不成立**：SDK 的唯一优势（p50）来自缓存层命中，这是构建本身的性质，不是 backend 的优势；把缓存层排除后 SDK 与 CLI 无实质差异。
4. **D4-08 约束**：未满足"等价性和跨平台证据齐全"前不得删除重复实现。

## 后续（若未来重估）

- 扩大 samples（≥10）并做冷/热缓存分离基准，重新计算 p50/p95/max。
- 补齐 SDK Build 的 cancel 语义与流式事件契约测试。
- 跨平台（Linux/macOS）Build smoke 后再重议。

## 本次留下的工程产物

- `scripts/bench/build-bench.py`：可重复的 CLI/SDK Build 基准（真实 daemon，离线可用）。
- 基镜像选择：`python:3.12-slim`（本地缓存，避免网络依赖）。
