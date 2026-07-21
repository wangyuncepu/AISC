# AISC

在 Docker 容器中使用 Claude Code，并按项目保存配置的个人开发工具。

> **状态：Alpha / 开发中。** AISC 面向个人和开发环境，不是生产级工作站产品。请先阅读文末的安全边界与已知限制。
>
> **当前版本：v2.0.2-dev**

## v2.0.2-dev 更新 (2025-01)

### 新增功能

- **`--keep-alive` 标志**：`aisc run` 支持 `--keep-alive` 参数，容器退出后保留（不使用 `--rm`），便于调试和重用
- **Windows 安装器支持自定义目录**：setup.exe 现在允许用户选择安装位置
- **完整的 Docker 操作 API**：在 `docker_.py` 模块中统一整合容器和镜像的 CRUD 操作
  - 容器：list、stop、remove、inspect
  - 镜像：list、remove、pull、tag

### 改进

- **镜像检测逻辑**：`aisc build` 在构建前检查镜像是否存在，存在时发出警告提示
- **简化 run 命令**：`aisc run` 不再自动构建镜像，镜像不存在时提示用户先执行 `aisc build`
- **修复 Windows 兼容性**：处理 `os.getuid()`/`os.getgid()` 在 Windows 上不存在的问题
- **修复挂载权限问题**：容器自动使用宿主机用户的 uid:gid 运行（`--user`，仅 Unix 系统），确保挂载文件可正常读写
- **CI/CD 优化**：所有分支推送都运行测试，只有 `v*` 标签触发二进制构建

详细的命令行使用文档请参考 [README_USER.md](README_USER.md)。

## 从这里开始

第一次使用，推荐走**启动器路径**：不需要安装 Python，也不需要理解 `aisc` CLI。

### 1. 准备 Docker 与 Git

- Windows / macOS：安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Linux：安装并启动 Docker Engine
- 安装 Git，用于取得和更新仓库

先确认 Docker 可用：

```bash
docker version
```

### 2. 下载 AISC

```bash
git clone https://github.com/wangyuncepu/AISC.git AISC
cd AISC
```

也可以下载 ZIP；解压后在终端进入解压出的 `AISC` 目录。

### 3. 用启动器启动容器

| 平台 | 推荐入口 | 说明 |
| --- | --- | --- |
| Linux | `./start.sh` | 首次如有需要：`chmod +x start.sh` |
| macOS | `./start.command` | 可在 Finder 双击，或在终端运行 |
| Windows | `start.bat` | 建议从 Windows Terminal 启动 |

Linux 示例：

```bash
chmod +x start.sh
./start.sh
```

启动器会检查 Docker、询问代理设置、提供镜像构建选项，然后启动容器。首次构建可能需要一些时间。

> `start.sh`、`start.command`、`start.bat` 是普通使用者的入口；它们**不是** Python `aisc` 命令的包装器，也不会转发 `aisc` 子命令。比如 `./start.sh doctor` 无效。

### 4. 选择配置作用域

容器首次启动会询问 `.claude` 的作用域：

| 选择 | 配置位置 | 适合场景 |
| --- | --- | --- |
| **临时**（temp） | 容器内置 `.claude` | 试用或一次性会话；容器删除后改动不保留 |
| **项目**（project） | 挂载工作区中的 `.claude` | 长期使用同一项目；配置、技能与状态随项目保留 |

不确定时选择**项目**。在自动化或非交互场景，可在启动前设置 `CLAUDE_SCOPE=temp` 或 `CLAUDE_SCOPE=project`；实现也接受 `global` 作为临时作用域的兼容值。

### 5. 在容器内配置服务并进入 Claude Code

进入容器 shell 后，以 DeepSeek 为例：

```bash
cs deepseek
claude
```

首次切换会要求输入自己的 API Key，输入不会显示。不要把真实 API Key 写入 README、聊天记录或 Git 提交。第三方服务会收到你的 API 请求和密钥；只使用你信任、并已了解其条款的服务。

## 先分清两个入口

| 入口 | 运行位置 | 面向谁 | 用途 |
| --- | --- | --- | --- |
| `start.sh` / `start.command` / `start.bat` | 宿主机 | 大多数使用者 | 检查环境、配置代理、构建并启动容器 |
| `cs` | **容器内** | 容器使用者 | 配置或切换模型服务、执行 `cs upgrade` |
| `aisc` | **宿主机** | 开发者/高级用户 | 构建镜像、运行/管理容器、导入构建期 Skill |

## 工作流程

### 使用启动器（推荐新用户）

1. 在 AISC 项目根目录运行 `./start.sh`（或对应平台的启动器）
2. 启动器自动检测镜像，不存在时提示构建
3. 容器启动后自动进入 shell
4. 使用 `cs` 切换模型，`claude` 启动 Claude Code

### 使用 aisc CLI（开发者/高级用户）

1. **构建镜像**：
   ```bash
   aisc build
   ```
   - 首次构建或需要更新镜像时运行
   - 如果镜像已存在，会显示警告（可能产生悬空镜像）
   - 可选参数：`--no-cache`（完全重新构建）、`--tag <name>`（自定义镜像名）

2. **运行容器**：
   ```bash
   aisc run
   ```
   - 镜像必须先存在，否则报错提示先 `aisc build`
   - 默认挂载当前目录为工作区
   - 可选参数：
     - `--workspace <path>`：指定挂载目录
     - `--image <name>`：使用指定镜像
     - `--keep-alive`：容器退出后保留（不自动删除）
     - `--network proxy`：启用容器内 TUN 代理

3. **管理容器**：
   ```bash
   aisc ps          # 列出所有容器
   aisc stop        # 停止运行中的容器
   aisc shell       # 进入容器 shell
   ```

## 镜像与容器的关系

```
aisc build → Docker 镜像（模板）
             ↓
aisc run   → Docker 容器（运行实例）
```

- **镜像**：只需构建一次，可重复使用
- **容器**：每次 `aisc run` 创建新容器
  - 默认退出后自动删除（`--rm`）
  - 使用 `--keep-alive` 保留容器用于调试

## 配置位置

AISC 支持两种配置作用域：

| 作用域 | 配置位置 | 保存内容 | 适用场景 |
| --- | --- | --- | --- |
| **临时（temp）** | 容器内 `/home/AISC/.claude` | 仅在容器内，退出即失 | 临时试用、一次性任务 |
| **项目（project）** | 工作区 `.claude/` 目录 | 持久化到宿主机 | 长期项目、配置共享 |

首次运行时会提示选择作用域。选择"项目"后，`.claude` 目录会创建在工作区中，配置、技能、会话历史都会保存到宿主机。

## 安全边界与已知限制

### 安全边界

- **Docker 隔离**：容器与宿主机通过 Docker 隔离，但挂载的工作区可被容器内进程读写
- **网络访问**：容器可访问宿主机网络（除非使用 `--network none`）
- **API Key 安全**：API Key 存储在 `.claude` 目录中，使用项目作用域时会保存到宿主机
- **代理模式**：`--network proxy` 需要 `NET_ADMIN` 能力和 `/dev/net/tun` 设备

### 已知限制

- **平台支持**：
  - Linux: x86_64
  - macOS: arm64 (Apple Silicon)
  - Windows: x86_64
- **Docker 依赖**：必须安装 Docker Desktop（Windows/macOS）或 Docker Engine（Linux）
- **权限要求**：
  - Linux: 用户需在 `docker` 组
  - Windows: 需要 WSL 2 后端
- **镜像大小**：首次构建下载约 1-2 GB 依赖
- **构建时间**：首次构建约 5-15 分钟（取决于网络）

## 开发与贡献

### 从源码安装

```bash
git clone https://github.com/wangyuncepu/AISC.git
cd AISC
pip install -e .
```

### 运行测试

```bash
pytest tests/
```

### 构建打包

```bash
# 构建 onefile 可执行文件
python3 packaging/artifact.py build-onefile

# 完整打包流程（需要平台特定工具）
python3 packaging/artifact.py stage
python3 packaging/artifact.py archive --staging <dir> --executable <exe>
```

## 许可

MIT License. 详见 [LICENSE](LICENSE)。

## 相关资源

- [Claude Code 官方文档](https://docs.anthropic.com/claude/docs/claude-code)
- [Docker 文档](https://docs.docker.com/)
- [问题反馈](https://github.com/wangyuncepu/AISC/issues)

## 推荐服务

以下是两个相互独立的第三方服务，链接中含推广或邀请参数。请按实际需求选择，并在使用前自行确认价格、服务条款、适用地区及合规要求。

### Codesome｜Codex 与 Claude Code 二合一服务

Codesome AIO 同时支持 Codex 和 Claude Code。一个 Key 可用于不同客户端和模型场景，例如：

- 在 Claude Code、Claude Desktop 等客户端中配置该 Key，使用 Claude 模型。
- 在 Codex、Codex Desktop 等客户端中配置该 Key，使用 Codex 模型。

#### 购买与开通

通过以下链接在浏览器中打开 Codesome 下单页面：

[前往 Codesome 选购](https://fk.codesome.cn?aff=wvoiJ4PY)

通过此链接下单可享 **5% 折扣**。支付后请妥善保存订单详情中的序列号或卡密。根据所购产品，开通方式有所不同：

- **额度包**：订单中的序列号是兑换码。登录 [Codesome 控制台](https://cc.codesome.ai)，在**兑换区**填写兑换码，兑换成功后美元额度会一次性到账；随后进入**API 密钥**菜单创建专属 API Key。
- **AIO 产品**：收到的卡密就是 Key，格式类似 `codesome_aio_XX: aaaaaaaa aaaaaa`。请完整、妥善地保存，不要公开分享或提交到 Git 仓库。

#### 配置地址

Claude Code 与 Codex 使用不同的 API URL，配置时请勿混用：

| 使用端 | API URL |
| --- | --- |
| Claude Code / Claude | `https://v5.codesome.cn/api` |
| Codex | `https://v5.codesome.cn/openai/` |

Key 可配置到对应的命令行工具或桌面客户端中。具体字段和配置步骤请以 Codesome 最新教程为准。

#### 教程、用量查询与技术支持

可在以下页面查看使用教程，并查询 Key 的用量和当前状态：

[查看教程及 Key 用量状态](https://aio.codesome.ai/admin-next/api-stats)

Codesome 的下单购买、价格、稳定性说明、使用指南、扫码进群和福利领取等信息统一收录在飞书入口：

[打开 Codesome 飞书总入口](https://my.feishu.cn/wiki/Vaifwy0aAisdP8kDLPoc0jV5nCb?from=from_copylink)

详细使用问题请进入 Codesome 飞书群联系工作人员或客服。技术问题统一在飞书群内解答；微信渠道主要用于交友和商务合作。

Codesome 创始人 Mens 专注于 Claude Code 相关产品，并感谢用户对产品的支持。

> API Key 属于敏感凭据。请勿将其粘贴到公开页面、聊天记录或代码仓库中。

### 赔钱机场｜网络连接服务

赔钱机场提供网络连接服务，可用于改善部分网络环境下的访问体验。可通过以下邀请链接注册并查看可用套餐：

[前往赔钱机场注册](https://pqjc.site/register?code=EVYrdlM4&cover=sfw)

请在购买前确认套餐价格、流量限制、节点覆盖、退款政策及当地合规要求。AISC 与该服务相互独立，不对其可用性、稳定性或数据处理方式作保证。
