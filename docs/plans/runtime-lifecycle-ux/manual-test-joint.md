# 联合手测清单（runtime-lifecycle-ux Stage 6 + docker-resource 真机行）

> 日期：2026-08-26 · 分支 `docker-ownership-foundation`（19 提交）
> 覆盖：一次性 Runtime 生命周期、阻断页、懒布局、toolchain 持久化、maintenance CLI
> 用法：从 P0 开始按组推进，每组做完在文末台账表记 PASS/FAIL。
> 所有 `docker`/`aisc` 命令在 **PowerShell** 里跑；GUI 操作在 Workbench 里做。

---

## P0 准备（一次性，约 10-15 分钟）

**P0-1 重建镜像**（entrypoint.sh 加了 toolchain 注入，必须烤进去；不用 --no-cache，
只重建变化层，几分钟）：

```powershell
cd C:\Users\VE111\Documents\AISC
python -m aisc build -t super-claude:latest
```

预期：构建成功。验证新镜像带溯源标签（A2 新增）：

```powershell
docker inspect super-claude:latest --format "{{json .Config.Labels}}"
```

预期输出包含 `"org.aisc.managed":"true"` 和 `"org.aisc.source-version"`。

**P0-2 确认 sidecar 是新的**（已替你重建过，双确认）：

```powershell
workbench\src-tauri\target\debug\aisc.exe runtime --help
```

预期子命令列表含 `reconcile` 和 `lease`。

```powershell
workbench\src-tauri\target\debug\aisc.exe maintenance --help
```

预期含 `docker-scan / docker-cleanup / docker-rebuild`。

**P0-3 干净起点**：

```powershell
docker ps -a --filter "label=io.aisc.managed=true"
```

预期：空（上一轮手测已清干净）。若有残留，重启 Workbench 后打开任意工作区会自动回收，或直接 `aisc maintenance docker-cleanup --context uninstall --format json`（注意：这会连 `super-claude:latest` 一起删，做完 P0-1 再跑，之后 E3 重建）。

**P0-4 重启 Workbench dev**：完全关掉当前 dev 会话（若在跑），然后：

```powershell
cd C:\Users\VE111\Documents\AISC\workbench
npm run tauri dev
```

预期：正常进入选择器。

---

## A 组：生命周期核心 + 懒布局（Stage 3/5）

**A1 首次打开（干净工作区）**
1. 新建/选一个从未用过的文件夹作为工作区，打开。
2. 预期：正常启动；只有一个 Bash 标签；无冲突页。
3. 验证：`docker ps --filter "label=io.aisc.managed=true"` 恰好 1 个容器，状态 Up。

**A2 懒布局恢复（本轮核心）**
1. 在工作区里再开 2 个标签（+ 菜单，比如再加一个 Bash 和一个 Claude）。
2. 确认此刻 3 个标签都在跑（可输入）。
3. **关闭工作区**（chip 上的 ×，确认弹窗应说"删除临时运行环境"）。
4. **重新打开同一工作区**。
5. 预期：
   - 标签**结构**恢复：还是 3 个标签；
   - 只有**上次激活的那个**标签在跑；另外两个显示灰色斜体的「**待启动**」；
   - 没有"恢复布局"按钮，也没有双选。
6. 点一个「待启动」标签 → 预期：立即开始启动（转 running），**再点一次不会重复开**（终端不闪、无第二个会话）。
7. 把另一个「待启动」标签 × 掉 → 预期：**立即消失，无确认弹窗、无终止动作**。
8. 验证容器数仍为 1。

**A3 停止 runtime（回归）**
1. 侧栏「停止 Runtime」→ 确认 → 回到选择器。
2. 验证：`docker ps -a --filter "label=io.aisc.managed=true"` 为空。

**A4 同路径聚焦（回归）**：开工作区 X 后，再从选择器选同一路径 X → 预期：直接聚焦已开的 X，不新建容器（docker ps 数量不变）。

**A5 多工作区隔离**：开 A、B 两个工作区（各 1 容器）→ 关闭 A → 预期：B 的容器还在跑，A 的消失。

**A6 托盘语义**
1. 最小化到托盘（关窗到托盘），等 1 分钟以上。
2. 从托盘恢复 → 预期：工作区原样在，容器没被删（这是"隐藏≠退出"）。
3. 托盘菜单「退出」→ 预期：进程退出，`docker ps -a` 里 AISC 容器**全部清空**。

---

## C 组：崩溃/残留自动回收（reconcile 真机行）

**C1 崩溃模拟 + 租约新鲜期阻断**
1. 打开工作区 X（容器在跑）。
2. 直接杀掉 Workbench 进程（任务管理器结束 workbench.exe，或关掉 dev 终端按 Ctrl+C 多次）——**不要**走正常退出。
3. 立刻（45 秒内）重新 `npm run tauri dev` 并打开 X。
4. 预期：出现阻断页「**此工作区正在另一个 Workbench 实例中使用**」，只有三个按钮（重新检测/返回/打开诊断），**没有停止/删除列表**。点「返回」回选择器。
   - 若没等到 45s 就重开却直接进了启动流程，也记录下来（说明租约心跳停得比预期早——需要告诉我）。
5. 等 1 分钟（租约过期），再打开 X → 预期：短暂清理后**自动进入启动**，摘要页显示「**已自动回收上次未正常关闭的运行环境**」，新容器起来。
6. 验证：`docker ps` 1 个新容器；旧容器没了。

**C2 外部 docker rm（注册表残留）**
1. 打开 X，然后强杀 Workbench（同 C1-2）。
2. 手动 `docker rm -f <容器名>`（名字用 `docker ps -a --filter label=io.aisc.managed=true` 查）。
3. 重开 Workbench 打开 X → 预期：不弹冲突页，自动清理注册表残留后正常启动（摘要页可能有「已自动回收」提示）。

**C3 旧版本遗留记录（可选）**
1. 手工往注册表塞一条假记录：
   ```powershell
   # 找到 X 的数据目录（哈希名）
   ls $env:LOCALAPPDATA\AISC\data\workspaces
   ```
   在对应 `...\runtime\containers.json` 的 containers 里加一条 `{"image":"super-claude:latest","workspace":"<X的路径>","runtime_id":"00000000-0000-4000-8000-000000000000","owner":"workbench","scope":"project","lifecycle":"","config_fingerprint":""}`（改完保存）。
2. 打开 X → 预期：当作 legacy 自动回收，正常启动。

---

## B 组：阻断页（Stage 4）

**B1 另一实例占用**（若 C1-4 已出现过该页面，此步只补验按钮行为）
1. 打开 X（GUI 在跑）。
2. PowerShell 手动 claim 租约（模拟另一实例）：
   ```powershell
   workbench\src-tauri\target\debug\aisc.exe runtime lease claim --workspace "X的路径" --instance-id 12345678-1234-4123-8123-123456789123 --format json
   ```
   注意：GUI 自己的心跳会抢回租约（同 instance 才算自己的）——所以更稳的顺序是：**先杀 GUI，再 claim，再开 GUI 打开 X**。
3. 预期：阻断页「另一个 Workbench 实例中使用」；点「打开诊断」能弹出诊断对话框；点「重新检测」仍阻断（租约还新鲜）；等过期后再「重新检测」即可通过。

**B2 归属不明（unknown_owner）**
1. 手工把注册表里 X 记录的 `owner` 改成 `"cli"`（或删掉 owner 字段），并造一个对应容器（简单法：`docker run -d --name aisc-fake-x --label io.aisc.workspace-key=<X的wskey> super-claude:latest sleep 600`，wskey 从注册表记录里抄）。
2. 打开 X → 预期：阻断页「**无法确认运行环境的归属**」，显示「检测到 1 个无法确认归属的资源（仅报告，未删除）」，无任何删除按钮。
3. 验证：`docker ps` 里 aisc-fake-x **还在**（没被动）。测完 `docker rm -f aisc-fake-x` 清场。

---

## D 组：toolchain 持久化（3a）

**D1 npm 全局安装跨容器保留（核心）**
1. 打开 X，在 Bash 终端里：
   ```bash
   npm install -g typescript
   tsc --version
   ```
   预期：安装成功（约 10-20 秒），版本号打印出来。
2. **关闭工作区**，再**重新打开**。
3. 在新容器的终端里直接：
   ```bash
   tsc --version
   ```
   预期：**直接可用**（持久工具链生效——这就是"运行环境已回收但工具还在"）。
4. 验证宿主可见：
   ```powershell
   ls $env:LOCALAPPDATA\AISC\data\workspaces
   ```
   对应工作区目录下有 `toolchain\npm-global\bin\tsc*`。

**D2 pip --user 持久（可选）**
```bash
pip install --user requests
python -c "import requests; print(requests.__version__)"
```
关闭重开后 `python -c "import requests; print(requests.__version__)"` 仍成功。

**D3 侧栏依赖策略显示**
打开 X 后看右侧状态抽屉 → 预期：新增「**依赖策略**」块，显示「持久工具链（跨运行时保留）」+「工具链兼容」。

**D4 一次性 run（temporary 语义，可选）**
```powershell
python -m aisc run --rm --workspace "X的路径" -- bash -lc "echo \$PATH | tr ':' '\n' | head -5; ls /tmp/aisc-toolchain 2>/dev/null || echo tmp-toolchain-created"
```
预期：PATH 前几项是 /opt 或 /tmp 工具链路径；`/tmp/aisc-toolchain` 目录存在。

---

## E 组：maintenance CLI（破坏性，放最后；做完 E3 恢复镜像）

**E1 扫描分类**
```powershell
workbench\src-tauri\target\debug\aisc.exe maintenance docker-scan --context uninstall --format json
```
预期：若 AISC 容器在跑 → containers.owned 有条目（reason=label）；镜像 `super-claude:latest` 在 images.owned（P0-1 重建后带 org.aisc 标签，reason=label）；非 AISC 镜像（nginx 等）完全不出现。`first_install` 语境下无标签默认 tag 会落 unverified。

**E2 清理（会删 super-claude:latest，做完 E3 重建）**
```powershell
# 先放个非 AISC 镜像/容器做对照（没有就跳过）
docker run -d --name keepme nginx sleep 600 2>$null
workbench\src-tauri\target\debug\aisc.exe maintenance docker-cleanup --context uninstall --format json
```
预期：AISC 容器+镜像全进 removed；`keepme` 和 nginx 镜像原样；退出码 0。`docker images` 里 super-claude 没了。测完 `docker rm -f keepme`。

**E3 重建（= 升级路径预演）**
```powershell
python -m aisc build -t super-claude:latest
```
然后再次 docker-scan → super-claude:latest 回到 owned。

---

## F 组（可选）：睡眠恢复

打开 X → Windows 睡眠 ≥1 分钟 → 唤醒 → 预期：Workbench 还在、容器还在；侧栏刷新正常；
再开第二个 Workbench 打开 X（若做了）不得仅凭时间戳删除——唤醒后原实例心跳恢复。

---

## 台账

| 组 | 项 | 结果 | 备注 |
|---|---|---|---|
| P0 | 镜像重建+标签 | ✅ | 2026-08-26；代理死配置排障后直连构建成功，org.aisc.* 标签齐全，scan 判 owned(label) |
| A | A1 首开 | ✅ | 用户确认（2026-08-26 整轮汇报：A→E 基本无明显异常） |
| A | A2 懒布局 | ✅ | 用户点名确认：「懒布局正确，无异常」 |
| A | A3 停止 | ✅ | 同轮回归 |
| A | A4 聚焦 | ✅ | 同轮回归 |
| A | A5 多区隔离 | ✅ | 同轮 |
| A | A6 托盘 | ✅ | 同轮 |
| C | C1 崩溃+租约 | ✅ | 同轮 |
| C | C2 外部 rm | ✅ | 同轮 |
| B | B1 他实例 | ✅ | 同轮 |
| B | B2 归属不明 | ✅ | 同轮 |
| D | D1 npm 持久 | ✅ | 同轮 |
| D | D3 侧栏显示 | ✅ | 同轮 |
| E | E1 扫描 | ✅ | 另有独立验证：uninstall 语境重建前 legacy_owned(default-tag)/重建后 owned(label) |
| E | E2 清理 | ✅ | 同轮（AISC 资源清、非 AISC 保留） |
| E | E3 重建 | ✅ | 即 P0-1 + 3a 轮构建 |
| F | 睡眠恢复（可选） | — | 本轮未单独执行；机制由 lease TTL+对账设计覆盖，Rust 心跳恢复路径有单测 |

> 2026-08-26 用户结论：「懒布局正确，无异常。A→E 流程基本无明显异常。」——整轮 PASS。

FAIL 的项直接把现象（截图/命令输出）发我，不要自行改代码。
