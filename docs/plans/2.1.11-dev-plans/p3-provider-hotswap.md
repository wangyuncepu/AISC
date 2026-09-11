# P3 调研——Provider 热切换可行性（D-3 裁决：出结论文档，实施下轮）

> 2026-09-12。代码证据：`container/aisc-cc-provider`（op_switch/
> _ensure_route_serving/_restart_daemon），容器实况（ps：cc-switch-real
> daemon + proxy serve ×2）。

## 结论（先答）

**provider↔provider 之间：真热切换架构上可行**——agent 的端点是容器内
**本地代理路由**（claude 127.0.0.1:15721 / codex 15722），不是 provider
直连。切换 provider 只是重指代理上游；运行中的会话 env 指向本地代理、
**不随切换失效**。已运行会话的下一个请求就走新 provider。

**两个不可热切/需接受的边界**：

1. **官方直连行（official-direct）参与时不可热切**：切到官方直连会把
   provider 直连 env 写回 live 文件并**拆掉代理路由**；反向则重写 live
   文件为本地路由 stub。官方↔第三方切换期间，运行中的会话仍持旧 env
   （直连或旧路由），**到会话结束才切**——这是 env 语义，无法绕过。
2. **切换瞬间的 daemon 重启窗口**：op_switch 为保证代理 worker 状态
   一致，现行实现是 stop→start（约 0.5-1s）。窗口内恰好**在途**的单个
   请求会失败一次（SDK 重试通常吸收）；已建立但空闲的会话无感。

## 证据链

- 代理拓扑：容器内常驻 `cc-switch-real daemon` + 每 agent 一个
  `proxy serve`（15721/15722）。usage 的 proxy_request_logs 证明请求
  流经本地代理。
- 切换语义（op_switch，2026-08-21 实测注释）：**先拆路由** → CLI switch
  重写 live 文件 → provider 行胜出则 daemon 重启 + 重新 enable。
  codex 的 worker 在 enable 时**捕获上游 token**（不透传客户端 bearer、
  不逐请求读库）——daemon 重启是 token 轮换的保障，不纯是保守。
- claude 路径：`proxy disable` 写回直连 env / `enable` 写回路由 stub——
  官方直连与路由模式的 live 文件互斥，见边界 1。

## 与现状的差距（用户问的「热切换」）

| 能力 | 现状 | 差距 |
| --- | --- | --- |
| 新会话即时生效 | ✅ 已有（live 文件切换即写） | 无 |
| 运行中会话：provider→provider | **事实上已热**（env 指本地代理，路由重指） | 仅 daemon 重启窗口的瞬断 |
| 运行中会话：official↔provider | ❌ 到会话结束 | env 语义边界 |
| 切换中模型映射 | 新会话读新 role_env；旧会话持旧模型名 | 新 provider 无该模型时报 4xx——热切换需配「模型映射兼容」提示 |

## 若下轮实施（建议范围）

1. **先实测「无重启切换」**：provider 行间切换不 stop/start daemon，只
   `provider switch` + enable——若 cc-switch 的 worker 依 enable 重读
   上游，则重启窗口可直接消掉（最可能一步到位）。
2. UI 语义：切换弹层区分「热切（provider 间）」与「会话延续切换（含
   官方直连）」两种文案；official 行标注「新会话生效」。
3. 模型兼容预检：切换前比对当前激活模型在新 provider 的 known_models，
   缺失时提示（数据已有，纯前端）。
4. 回归锚点：在途请求重试、token 捕获、usage 捕获连续性。

**Slurm/PBS 方案文档**：仍阻塞在用户提供实际工作流（提交节点形态/
认证/常用作业操作）——2.1.11 封版前若未提供则顺延 2.1.12。
