# F1/F2 新特性设计文档（SSH 工作区 · 宿主工具 MCP）

> 状态：**方案定稿待细化，未排期实施**。2026-09-01 两轮只读探底 + 用户
> 裁决后成文。用户裁决：**后续先做优化批次讨论，优化优先级高于新功能
> 添加**；F2/F1 实施等优化批次定案后再排期。探底证据（文件:行号）见
> 文末触点附录。

## 已裁决汇总（用户拍板，2026-09-01）

| 决策点 | 裁决 |
|---|---|
| F1 底层形态 | **双向同步**（Mutagen 式，非挂载/非单向） |
| F1 场景权重 | 远程为主 + 内网环境（初始同步可激进；冲突处理中等权重） |
| F1 影子目录位置 | **数据根内**（`<数据根>/sync-workspaces/<名称>/`，用户无感） |
| F2 安全模型 | **白名单**：默认空，用户逐条登记放行；未登记一律拒绝并回报错 |
| F2 白名单粒度 | **程序级 + 只读筛**（登记程序路径 + 可选"仅限只读子命令"预设，如 git status/log/diff） |
| F2 调用形态 | 文本流（stdout/stderr 回传）+ 文件产物（落盘+路径回传）；**不做**长任务句柄、不做宿主任意文件读取（记 backlog） |
| 实施顺序 | **F2 先**（体量小、风险隔离，先拿闭环）→ F1（体量大） |

## F2 · 宿主工具 MCP（先行）

**目标**：容器内 claude/codex 经 MCP 调用宿主机白名单命令（如 git/msbuild），
stdout/stderr 与产物文件回传。典型协同：F1 落地后宿主命令跑在本地影子目录。

**架构**（五个新件 + 注入链）：

1. **宿主 MCP server**（Rust 新模块 `host_mcp.rs`）：streamable-http MCP，
   `127.0.0.1:<动态口>`——端口分配复用 `web_gateway.py` 的 bind-probe 范式
   （`src/aisc/application/web_gateway.py:69-99`）；生命周期搭 `lease.rs` 的
   tokio 常驻骨架 + CancellationToken。启动即生成随机 token（鉴权）。
   ⚠️ 探底实证：Rust 后端现无任何 TcpListener——这是第一个本地监听服务。
2. **工具面**：`host_exec(program, args, cwd_workspace_relative?)` →
   白名单查（程序级+只读筛）→ `CREATE_NO_WINDOW` spawn（cwd 钉死工作区
   本地路径）→ stdout/stderr/exit_code/duration 回传（输出上限+截断标记、
   超时上限、并发上限）。另加零参 `host_tools_list`（自描述健康检查）。
3. **容器→宿主通道**：docker create（`runtime.py:1139` argv）追加
   `--add-host=host.docker.internal:host-gateway`。⚠️ P0 待实测：
   WSL2 引擎下容器经 host.docker.internal 能否达宿主 127.0.0.1 动态口；
   proxy 模式 mihomo TUN 是否截获该流量（需放行网关 IP 规则）。
4. **MCP 注册注入**（探底定案，复用既有范式）：
   - claude：项目级 `.mcp.json`（`enableAllProjectMcpServers` 已开，
     Dockerfile:272）或 `.claude.json` user-scope mcpServers（symlink
     持久化机制 entrypoint.sh:252-266）
   - codex：`config.toml` `[mcp_servers.aisc-host]` 行级 splice +
     entrypoint 每次启动幂等回填（照 `model_catalog_json` 范式，
     aisc-cc-provider:1138-1153 + entrypoint:499）
   - **绝不写 settings.json**（provider switch 整文件替换，aisc-cc-provider:486-494）
   - 下发时机：entrypoint 运行时幂等回填（首选，旧镜像重启即得）
5. **白名单配置面**：`settings.rs` 新节 `host_tools: Vec<HostToolEntry
   {name, program, read_only_preset?}>` + SettingsForm UI（增删改/路径校验/
   只读筛开关）。默认空 = 功能默认关闭。

**安全论证**（主战场）：

- 威胁主体：容器内 agent（root + skip-permissions）+ prompt injection
- 防线：白名单外拒绝并回显式错误；cwd 限工作区；只读筛预设；输出/时长/
  并发上限；token 鉴权防本机冒用；日志全量 redaction（复用
  conversation.py:68-100 正则）
- 已知残留（记 backlog）：程序级放行下 git 仍可 `git push`/改 global
  config；参数模板收紧为后续增强

**T 序列**：T-F2a 通道 PoC（手工 docker run 验证 host.docker.internal→
宿主 loopback，含 proxy 模式）→ T-F2b host_mcp.rs 最小实现（token+白名单+
host_exec）→ T-F2c 注入链 + entrypoint 回填 → T-F2d 设置 UI → T-F2e 手测
（claude/codex 实调宿主 git --version / git status，白名单外命令被拒）。

## F1 · SSH 工作区（双向同步）

**核心设计**：本地影子目录 = 真工作区 → **身份链零改动**（canonicalize/
hash/watcher/挂载/explorer 全部照旧操作影子目录），SSH-ness 收敛为一个
同步层。这是选同步形态的决定性收益：探底列出的 11 个"本地目录假设"触点
全部不需要动（见附录 A-1）。

**新件**：

1. **mutagen vendor**：核心 MIT（可再分发），二进制钉版本入安装包
   （NSIS resources；同 mihomo 的下载/校验模式）。⚠️ 待验证 v0.17+
   商业化是否影响 CLI 核心用法。
2. **SSH profiles**（settings 新节）：host/port/user/认证方式（key 路径
   vs 密码）/known_hosts 策略。凭据存储安全：密码不落明文（DPAPI/
   凭据管理器，方案细化时定）；私钥引用路径不复制。
3. **同步会话管理**（Rust 新模块）：mutagen daemon 生命周期（app 启动/
   退出）、session create（alpha=影子目录, beta=ssh://…）、pause/resume/
   terminate、`mutagen sync list` JSON 轮询出状态投影。ignores 默认 =
   WATCH_IGNORE 镜像 + VCS ignore 模式。冲突策略：mutagen 默认冲突
   保留双副本 → UI 呈现待处理列表（远端为主场景冲突低频，可接受）。
4. **WorkspacePicker 新入口**："SSH 工作区"表单（远端信息+名称→自动建
   `<数据根>/sync-workspaces/<名称>/`）；历史记录显示为远端标识。
5. **同步状态 UI**：初始同步进度（文件数/字节）、健康度 badge、冲突
   待处理提示、断网降级提示（本地照常干活，恢复自动追平——同步形态的
   核心卖点）。
6. **远端前置**：探测 rsync（mutagen ssh transport 依赖）缺失时引导
   （内网 Linux 一般有）。

**T 序列**：T-F1a mutagen vendor + 许可确认 → T-F1b SSH profiles +
picker 表单（不动同步）→ T-F1c 会话生命周期 + 状态投影 → T-F1d 同步
状态/冲突 UI → T-F1e 手测矩阵（内网真实远端：初始同步/断网续作/冲突
双副本/关闭工作区语义）。

**与 F2 协同**：F1 落地后 host_exec 的 cwd=影子目录天然成立；远端执行
需求（在远端机器跑命令）不在本期范围（记 backlog）。

## 里程碑

**优化批次（优先，待开题）** → F2 闭环 → F1 闭环 → 2.1.9 收尾（VERSION/
发布走周期冻结流程）。优化讨论的议题池由用户开题，本文「待决问题」
清单可一并带入。

## 验证

- F2：PoC 报告（通道矩阵：direct/proxy × WSL2）；白名单拒绝/放行/只读筛
  单测；注入链幂等单测；claude+codex 容器内实调手测
- F1：远端真实环境手测矩阵；断网/恢复演练；冲突双副本演练；卸载清理
  （sync-workspaces 随数据根）

## 待决问题（后续讨论清单）

1. F2 token 的存储面：`.mcp.json`/config.toml 在容器与工作区可见——
   接受"容器内即最高权限主体"论证，还是要更细隔离？
2. F1 认证：密码存储用 Windows 凭据管理器（DPAPI）还是仅支持 key 认证先行？
3. F1 影子目录与 recents 的关系：SSH 工作区在历史里以名称还是远端路径显示？
4. mutagen v0.17+ 商业化细节核查（vendor 前必做）
5. F2 host_exec 参数模板收紧（backlog 排期）

## 附录 A：探底触点索引（2026-09-01 两轮只读探底结论）

**A-1 工作区身份链（F1 相关"本地目录假设"触点）**：前端入口
（WorkspacePicker.vue / workspaceRuntime.ts:284-287 pickWorkspace /
tabLayout.ts:33-52 sameWorkspace）→ history.rs:101-108 WorkspaceRecord.path
→ workspace.rs（resolve_contained:1615-1638 + 全部 explorer fs 命令）→
watcher.rs:250,284（notify 递归、无轮询回退）→ runtime.rs argv builder
（workspace 串原样透传）→ Python canonicalize 层（runtime.py:976-984 /
data_root.py:62-86 哈希输入）→ 挂载点 runtime.py:1158
（`-v <canonical_workspace>:/root/app`）。两套哈希形式（`sha256-v1:` 目录名
vs label 裸 hex）由 hash-vectors.json 契约冻结。设置/onboarding 无任何
远程连接配置节（settings.rs:57-73）。全仓无 ssh/sftp/remote 工作区先例。

**A-2 容器→宿主与 MCP 注入面（F2 相关）**：容器→宿主方向现无任何通道
（无 --add-host/host-gateway/自定义 bridge；proxy 模式 mihomo TUN 接管
容器全部出站）。claude MCP 落点：`.mcp.json`（enableAllProjectMcpServers
已开，Dockerfile:272）/`.claude.json`（symlink 持久化 entrypoint:252-266）；
codex 落点：config.toml 行级 splice + 启动幂等回填范式
（aisc-cc-provider:1138-1153）。settings.json 被 provider switch 整文件
替换——禁写。宿主侧无常驻 TCP 服务先例；可复用：端口 bind-probe 分配器
（web_gateway.py:69-99）、lease.rs tokio 常驻骨架、secret 走 stdin 的
docker exec 通道、redaction 正则（conversation.py:68-100）。

## Sources

- [Building a Robust Future for Mutagen](https://mutagen.io/blog/building-a-robust-future-for-mutagen/)
- [mutagen-io/mutagen (GitHub)](https://github.com/mutagen-io/mutagen)
- [Mutagen 安装文档](https://mutagen.io/documentation/introduction/installation/)
