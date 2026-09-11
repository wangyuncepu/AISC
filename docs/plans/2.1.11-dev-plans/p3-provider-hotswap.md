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
## 追加调研——模型映射随切换实时变化（用户问 2026-09-12）

**能解。** 全部流量已经流经本地代理（man-in-the-middle），请求体改写
点天然存在；上游 cc-switch 代理**没有**请求时重写能力（容器实测
`proxy config` 仅 listen addr/port；其「模型映射」= 切换时写 env），
所以需要我们自加一层薄改写。

**方案（shim 层，保住全部现有能力）**：

```
agent ── env 指向 ──▶ 127.0.0.1:15720 映射 shim ──▶ 15721 cc-switch 代理 ──▶ provider
```

- shim 只做一件事：按**当前 provider 的映射表**重写请求体 `model` 字段
  （流式不影响——转发前改 body）；上游 token/路由/用量捕获全留在
  cc-switch 代理，一行不动。
- **按角色映射而非按名映射**（关键设计）：provider 行已携带
  role_env（ANTHROPIC_DEFAULT_OPUS/SONNET/HAIKU/MODEL 槽位）+ 
  model_catalog。会话发来的旧模型名 → 先在「历史 provider 的角色表」
  里解析出槽位 → 再取当前 provider 该槽位的模型名发出。例：
  deepseek-v4-flash（旧 opus 槽）→ zhipu 的 glm-4.6（新 opus 槽）。
  解析不出角色的自定义名 → 原样透传（保守）。
- 映射表缓存 + 失效：读 cc-switch db 现值；切换后由 adapter 通知失效
  （op_switch 尾部加一次 shim 的 invalidate，或 shim watch db mtime）。
- 代价：多一跳本地回环（<1ms）；agent env 的路由 stub 从 15721 改指
  15720（改 adapter 的 enable 写入值）。

**如实告知的边界**：

1. 会话侧的**自我认知**不变：claude CLI 界面仍显示它启动时的模型名
   （它是 env 读进内存的），但实际请求已按新 provider 走——显示名与
   实际模型可能不一致，属显示层错位，功能无损。
2. 上下文长度/计价假设随模型真实切换而变——重写后请求以新模型的
   上下文窗口与计价运行，会话不感知。
3. 官方直连行（proxy off）时 shim 不在路径上——该场景本就不热切，
   一致。

**实施量级**：容器内 Python asyncio 薄层（~200 行）+ adapter 路由 stub
改端口 + 映射失效钩子 + 映射表解析测试。下轮与「无重启切换」同批。
## 追加验证——CLI 原生热重载（用户问「改 settings.json 实时变化」）

**两个 CLI 的 env/模型配置均无原生热重载**（2026-09-12 查证）：

- **claude**：settings.json 的 hooks/permissions/keybindings/theme 热重载，
  但 `env`（ANTHROPIC_BASE_URL/MODEL/TOKEN 所在）**改后需重启会话**——
  官方 issue #42251（请求 env 热重载）与 #15858（配置热重载 RFC）仍
  open。用户印象中的「改 settings.json 即生效」是前者那批键。
- **codex**：config.toml 由 Rust 二进制启动时读入，无任何重载机制。

**结论不变且更明确**：会话内的「实时变化」**只能**在传输层实现——
本地代理换上游（已热）+ shim 重写 model 字段（下轮实施）。CLI 界面
显示的模型名到会话结束都停留在启动值（两 CLI 同），属显示层错位；
实际服务方与实际模型随切换即时变化。

**Slurm/PBS 方案文档**：仍阻塞在用户提供实际工作流。
