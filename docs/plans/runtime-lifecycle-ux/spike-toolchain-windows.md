# Windows toolchain 存储后端 spike 留证（Stage 3a 任务 1-2）

> 日期：2026-08-26 · 执行人：Claude（用户监督）· 脚本：`tools/spike-toolchain-win.sh`（可复现）

## 环境

| 项 | 值 |
|---|---|
| Windows | 10.0.26200.9168（Windows 11 Pro） |
| Docker Desktop | engine 29.7.2，WSL2（kernel 6.18.33.2-microsoft-standard-WSL2），overlayfs |
| 测试包 | 本地冻结 tarball `typescript-7.0.2.tgz`（366KB / 解包 416 文件 / 含 bin entry，安装后 530 文件）——零网络 |
| 容器 | `node:20-slim`（本机已拉取） |
| npm 配置 | `NPM_CONFIG_PREFIX=/opt/aisc/toolchain/npm-global`，PATH 前置其 bin |

## 度量（毫秒，每行一次完整 `npm install -g` + symlink 校验 + `tsc --version` 执行校验）

### 后端 A：host_bind（`%LOCALAPPDATA%\AISC\spike\bind` → `/opt/aisc/toolchain`）

| 轮次 | install_ms | symlink | exec |
|---|---|---|---|
| cold1（首拉镜像后） | 13016 | ok | ok |
| cold2 | 8575 | ok | ok |
| cold3 | 6915 | ok | ok |
| hot1 | 21171 | ok | ok |
| hot2 | 13606 | ok | ok |
| hot3 | 5919 | ok | ok |
| hot4 | 15275 | ok | ok |
| hot5 | 7760 | ok | ok |

冷装中位 **8575ms**；热装中位 **13606ms**。

### 后端 B：docker named volume（`aisc-spike-toolchain`）

| 轮次 | install_ms | symlink | exec |
|---|---|---|---|
| cold1 | 13959 | ok | ok |
| cold2 | 7530 | ok | ok |
| cold3 | 6121 | ok | ok |
| hot1 | 16813 | ok | ok |
| hot2 | 20702 | ok | ok |
| hot3 | 10666 | ok | ok |
| hot4 | 5996 | ok | ok |
| hot5 | 7784 | ok | ok |

冷装中位 **7530ms**；热装中位 **10666ms**。

### 跨容器复用 / 文件计数

- 新容器挂同一 store（两后端各一次）：`tsc --version` → `Version 7.0.2` ✅（bind_reuse=ok / volume_reuse=ok）
- 两后端安装后文件数一致：530

## 对照决策门（03 §3a 任务 2，冻结阈值）

| 门 | 实测 | 触发？ |
|---|---|---|
| npm bin symlink 创建或解析失败 | 全部 ok | 否 |
| 挂载目录中的二进制不能执行 | ok | 否 |
| 删除旧容器后新容器不能复用 | ok | 否 |
| bind 中位数 > volume 2 倍 | 冷 1.14× / 热 1.28× | 否 |
| bind 绝对额外耗时 > 30s | 冷 +1.0s / 热 +2.9s | 否 |
| 依赖管理员权限 / Developer Mode / 非默认设置 | 均不需要 | 否 |

## 决策（D-RUNTIME-10 落地）

**Windows project toolchain 默认后端 = `host_bind`**（data-root 下
`workspaces/<hash>/toolchain/`，用户可直接查看与备份）。决策门全部未触发；
bind 的中位开销（≤1.3×、≤3s）远低于阈值。named volume 路径保留为可切换
实现（`toolchain_storage=docker_volume` 元数据字段与挂载 argv 已参数化），
但 02 §8.5 的卷管理 CLI（inspect/export/import/remove）按"如果平台选择
docker_volume"的条件暂不实现；若未来某些机器触发决策门，补齐该子阶段。

注：热装慢于冷装（两后端一致）是 npm 重装既有包的元数据开销，非存储后端
差异；绝对耗时主体是 npm 本身（530 个小文件），两后端同量级。
