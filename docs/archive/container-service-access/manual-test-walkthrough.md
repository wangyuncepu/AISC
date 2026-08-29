# 容器 Web 服务访问 — 手把手手测清单

> 对应验收项 M1-M13（acceptance.md §4）。每个步骤都写明**在哪操作、输入什么、应看到什么**。
> 全程只需要：鼠标、应用内终端、一个 PowerShell 窗口、浏览器。
> 遇到"应看到"之外的现象：截图 + 记下编号（如 M3），发给我即可。

## 0. 开始前的准备（只做一次）

**P1. 确认 Docker 在运行**

- 看任务栏右下角有没有 Docker 的鲸鱼图标，鲸鱼不动（稳定）即已在运行。
- 保险起见，开一个 **PowerShell**（开始菜单搜 powershell →"Windows PowerShell"），输入：

  ```powershell
  docker info --format "{{.ServerVersion}}"
  ```

  应输出 `29.7.2` 之类的版本号。如果报错，先打开 Docker Desktop 等它变成绿色 "Engine running"。

**P2. 建一个专门的测试文件夹**（手测会往里写容器文件，别用正式项目）

```powershell
mkdir C:\Users\VE111\Documents\aisc-manual-test
```

**P3. 启动 Workbench（开发模式）**

```powershell
cd C:\Users\VE111\Documents\AISC\workbench
npm run tauri dev
```

- 等待编译，直到弹出 AISC 应用窗口（首次约 1-3 分钟，看到 "Finished" 后再等窗口）。
- ⚠️ 今天 18:22 我已把新 CLI 同步进 dev 目录，**这个 dev 必须是现在启动的**，不要用昨天留下的旧窗口。

**两个"终端"的区别**（后面反复用到，先记住）：

| 名字 | 长相 | 怎么打开 | 用途 |
|---|---|---|---|
| **宿主 PowerShell** | Windows 蓝色/黑色窗口 | 开始菜单 | 启动 dev、跑 `aisc run` |
| **容器终端** | 应用窗口中间的黑色终端（标签页） | 应用里"新建标签" | 所有 `aisc-web-*` 命令在这里输 |

---

## A 组：基础链路（测试文件夹，bash 即可，不需要 AI 配置）

### M1 — 网关就绪显示

1. 应用窗口：**选择工作区** → 选 `C:\Users\VE111\Documents\aisc-manual-test`。
2. 走你熟悉的启动流程（直接模式/项目作用域，一路默认）→ 点「新建 Runtime」。
3. 等 runtime 变为运行中（侧栏状态变绿「运行中」）。
4. 点窗口**最右边缘中间的 ⓘ 圆钮** → 右侧滑出「状态信息」抽屉。
5. 在抽屉里找到新分区 **「Web 服务」**。

✅ 应看到：`网关就绪 :47xxx`（xxx 是 47000-47999 之间某个数，记住它，后面叫**网关端口**）。
❌ 若看到「当前 CLI 不支持服务访问」→ dev 用了旧 CLI，把 P3 重做；若看到其它灰色原因文案 → 截图给我。

### M2 — 容器内起服务并注册（本功能的"Agent 视角"）

1. 应用顶部标签栏点 **＋（新建标签）** → 选 **bash**。
2. 在这个黑色终端里逐行输入（每行回车）：

   ```bash
   python3 -m http.server 3000 --bind 127.0.0.1 > /tmp/http.log 2>&1 &
   ```

   （结尾的 `&` 表示"放后台跑"；会显示一行 `[1] 123` 之类的作业号，正常）

3. 自检服务确实活着：

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
   ```

   ✅ 应输出 `200`。

4. 注册到网关（核心命令）：

   ```bash
   aisc-web-expose 3000 --name "docs preview"
   ```

   ✅ 应**一字不差**输出：`aisc web service registered: port=3000 name="docs preview"`

5. 确认注册列表：

   ```bash
   aisc-web-list
   ```

   ✅ 应看到一行：`3000  http  registered  docs preview`

### M3 — 浏览器打开（最关键一步）

1. 回到状态抽屉「Web 服务」区，点 **刷新**（Runtime 区里的刷新按钮）。
2. ✅ 应看到新服务行：`docs preview  3000` + 两个小按钮「复制」「打开」。
3. 点 **打开**。

✅ 默认浏览器自动打开一个**目录列表页面**（Index of /），地址形如
`http://p3000.localhost:47xxx/`。
❌ 若浏览器提示找不到网站/DNS 错误 → 换 Edge 或 Chrome 再点一次（`*.localhost`
由浏览器解析，个别老浏览器不支持）；仍不行截图地址栏给我。

### M4 — 复制链接

1. 点服务行的 **复制** → 行内闪一下「已复制」。
2. 随便找个输入框（比如浏览器地址栏）Ctrl+V。
✅ 粘贴出 `http://p3000.localhost:47xxx/`，与 M3 打开的完全一致。

### M5 — 服务停了会怎样（502 页面）

1. 回容器终端，停掉刚才的服务：

   ```bash
   kill %1
   ```

   （如果提示没有该作业，用 `pkill -f http.server`）

2. 回状态抽屉点 **刷新** → 服务行**仍在**（注册不等于在线，这是设计如此）。
3. 再点 **打开**（或刷新浏览器里那个页面）。

✅ 浏览器显示纯文本错误页：`AISC_WEB_TARGET_UNAVAILABLE: service is not listening inside the container`

### M6 — 未注册端口拒绝（404）

1. 在浏览器地址栏，把 URL 里的 `p3000` 改成 `p4321`，其余不动，回车：

   `http://p4321.localhost:47xxx/`

✅ 显示 `AISC_WEB_PORT_NOT_EXPOSED: port is not registered ...`（404）。

### M7 — 注销

1. 容器终端：

   ```bash
   aisc-web-unexpose 3000
   ```

✅ 输出 `aisc web service unregistered: port=3000`
2. 抽屉点 **刷新** → 服务行消失，显示「暂无已注册服务…」提示。
3. 浏览器再开 `http://p3000.localhost:47xxx/` → 变成 404 页面。

### M8 — 停止 Runtime

1. 抽屉 Runtime 区点 **停止 Runtime**，等状态变「已停止」。
2. 看「Web 服务」区。

✅ 显示「运行时未运行」，服务行/打开按钮全部消失（没有死链）。

### M9 — 重启后端口不漂移

1. 关闭工作区再重新选 `aisc-manual-test`（或按你平时恢复工作区的方式）。
2. 启动摘要会显示「重启已停止 Runtime」→ 点它，等运行中。
3. 打开 ⓘ 抽屉看「Web 服务」区。

✅ `网关就绪 :47xxx` 的数字与 M1 **完全相同**（映射复用，URL 不漂移）。

---

## B 组：Agent 行为（用你平时的工作区）

### M10 — Claude/Codex 按新规办事

1. 关闭测试工作区，选择你**平时真实使用、已配好 Provider** 的工作区，复用/启动 runtime。
2. 新建一个 **claude** 标签，对它说：

   > 帮我起一个静态文件预览服务，用 3000 端口，然后告诉我怎么访问

3. 观察它的做法。

✅ 判定标准（CLAUDE.md/AGENTS.md 新合同）：
- 它会用 `aisc-web-expose 3000` 注册（而不是只说"打开 localhost:3000"）；
- 它告诉你"去 Workbench 侧栏打开"，**不会**把 `http://localhost:3000` 当成给你的 URL；
- 侧栏刷新后出现该服务行，点开就是页面。

（codex 标签同理可复测一次，二选一也行。）

### M11 — Vite HMR（可选，卡住可跳过）

在容器终端（bash 标签）：

```bash
mkdir -p vite-demo && cd vite-demo
cat > package.json <<'EOF'
{ "name": "demo", "private": true,
  "dependencies": {}, "devDependencies": { "vite": "^5" } }
EOF
cat > index.html <<'EOF'
<!doctype html><html><body><h1 id="t">v1</h1>
<script type="module" src="/main.js"></script></body></html>
EOF
cat > main.js <<'EOF'
document.title = "demo";
EOF
npm install --registry=https://registry.npmmirror.com
node_modules/.bin/vite --port 5173 --host 127.0.0.1 > /tmp/vite.log 2>&1 &
sleep 3 && curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5173/
aisc-web-expose 5173 --name "vite hmr"
```

`curl` 出 `200` 后：侧栏刷新 → 打开 5173 服务 → 浏览器显示大字 **v1**。
然后容器终端里：

```bash
sed -i 's/>v1</>v2</' index.html
```

✅ 浏览器**不刷新页面**的情况下，文字自动变成 **v2**（HMR 走通了网关的 WebSocket 透传）。

---

## C 组：命令行一次性容器（宿主 PowerShell）

### M12 — `aisc run` 同等能力

1. 开一个**新的**宿主 PowerShell：

   ```powershell
   cd C:\Users\VE111\Documents\aisc-manual-test
   C:\Users\VE111\Documents\AISC\dist\aisc-x86_64-pc-windows-msvc.exe run --name webtest
   ```

2. 启动菜单出现前，会先打印一行：

   ✅ `🌐 Web 服务网关: http://p<端口>.localhost:47xxx/ （容器内注册服务: aisc-web-expose <端口>）`
   —— 记下这个 47xxx（它是这次 run 专用的新端口）。
3. 菜单里选 **1** 进 bash，然后（和 M2 一样）：

   ```bash
   python3 -m http.server 3000 --bind 127.0.0.1 > /tmp/http.log 2>&1 &
   aisc-web-expose 3000 --name "run path"
   ```

4. 在宿主浏览器手动输入：`http://p3000.localhost:47xxx/`（47xxx 用第 2 步记下的）。

✅ 打开目录列表（说明一次性容器同样具备网关能力）。
5. 收尾：容器终端输 `exit` 退出 bash → 容器自动删除（`--rm`）。回到 PowerShell 验证没有残留：

   ```powershell
   docker ps -a --filter name=webtest
   ```

   ✅ 输出为空。

### M12b — JSON 元数据（30 秒）

```powershell
C:\Users\VE111\Documents\AISC\dist\aisc-x86_64-pc-windows-msvc.exe run --dry-run --format json
```

✅ 输出的 JSON 里能找到 `"web_gateway": { "container_port": 45871, "host_port": 47... }`，
且 `docker_argv` 数组里有 `"--publish"` 和 `"127.0.0.1:...:45871/tcp"`。

### M13 — 旧容器降级（本轮跳过）

本机 Docker 是新装的，没有"功能之前"的旧 runtime 可测，此项由集成测试覆盖，手测记 N/A。

---

## 收尾：怎么反馈

把下表填好发我（PASS / FAIL+截图 / SKIP）：

| 项 | 结果 | 备注 |
|---|---|---|
| M1 网关就绪 | | |
| M2 注册三连 | | |
| M3 浏览器打开 | | |
| M4 复制 | | |
| M5 502 页面 | | |
| M6 404 页面 | | |
| M7 注销 | | |
| M8 停止清空 | | |
| M9 端口不漂移 | | |
| M10 Agent 行为 | | |
| M11 Vite HMR（可选） | | |
| M12/M12b run 路径 | | |

全部 PASS → 我 push 分支、盯 CI、合并 develop。
