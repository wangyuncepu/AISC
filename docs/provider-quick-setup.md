# Provider 一键配置指南

本文档提供常见 AI 供应商的 cc-switch provider 快速配置方法。**AISC v2.1.4+ 已在镜像构建时预配置这些 provider（除 API Key 外的所有参数）**，用户只需设置 API Key 即可使用。

## 快速开始

### 1. 查看预配置的 provider

容器启动后，这些 provider 已自动添加到 cc-switch：

```bash
cc-switch -a claude provider list
```

你将看到以下预配置的 provider（标记为 `[no key]` 表示需要设置 API Key）：

- `deepseek` - DeepSeek 高性价比 AI 模型
- `codex-claude` - 通过 Codex 订阅访问 Claude
- `volcengine-ark` - 火山引擎 Ark 模型服务
- `zhipu` - 智谱 GLM 系列模型
- `kimi` - 月之暗面 Kimi 长文本模型

### 2. 设置 API Key

选择一个 provider，设置 API Key 后即可使用：

```bash
# 交互式输入 API Key（推荐，不会显示在终端历史）
cc-switch -a claude provider set-key deepseek

# 或直接在命令中指定
cc-switch -a claude provider set-key deepseek <your-api-key>
```

### 3. 切换并使用

```bash
# 在容器内切换
cc-switch -a claude provider switch deepseek

# 或在宿主机快速切换
aisc switch --quick deepseek

# 测试连接
claude "你好"
```

---

## 使用方式

**注意：AISC v2.1.4+ 已自动预配置这些 provider，通常无需手动添加。** 以下操作仅在特殊情况下需要（如修改配置或在旧版本中使用）。

### 容器内配置

手动添加或修改 provider：

```bash
# 添加 provider（v2.1.4+ 已自动完成）
cc-switch -a claude provider add <provider-id> \
  --base-url <api-endpoint> \
  --model <default-model>

# 配置 API Key（必需）
cc-switch -a claude provider set-key <provider-id>
# 或直接在命令中指定
cc-switch -a claude provider set-key <provider-id> <your-api-key>

# 切换到该 provider
cc-switch -a claude provider switch <provider-id>
```

### 宿主机快速切换

配置完成后，可在宿主机使用 `aisc switch --quick` 快速切换（无需再次输入 API Key）：

```bash
aisc switch --quick <provider-id>
```

---

## 预配置的供应商

AISC v2.1.4+ 已在镜像中预配置以下供应商，**只需设置 API Key 即可使用**。

### 1. DeepSeek

DeepSeek 提供高性价比的 AI 模型服务，支持 Claude-compatible API。

**✅ 已预配置 - 只需设置 API Key：**

```bash
# 设置 API Key
cc-switch -a claude provider set-key deepseek

# 切换使用
cc-switch -a claude provider switch deepseek
# 或在宿主机
aisc switch --quick deepseek
```

**配置详情：**
- Provider ID: `deepseek`
- API Endpoint: `https://api.deepseek.com/v1`
- 默认模型: `deepseek-chat`

**可选模型：**
- `deepseek-chat`：通用对话模型（预配置默认）
- `deepseek-coder`：代码专用模型

**获取 API Key：**
访问 [DeepSeek Platform](https://platform.deepseek.com/) 注册并创建 API Key。

**手动配置（可选，已自动完成）：**

```bash
cc-switch -a claude provider add deepseek \
  --base-url https://api.deepseek.com/v1 \
  --model deepseek-chat

cc-switch -a claude provider set-key deepseek
```

**快速切换：**
```bash
aisc switch --quick deepseek
```

---

### 2. Claude via Codex 订阅

使用 Codex 订阅服务访问 Claude 官方模型，无需单独配置 Anthropic API Key。

**✅ 已预配置 - 只需设置 Codex API Key：**

```bash
# 设置 Codex API Key
cc-switch -a claude provider set-key codex-claude

# 切换使用
cc-switch -a claude provider switch codex-claude
# 或在宿主机
aisc switch --quick codex-claude
```

**配置详情：**
- Provider ID: `codex-claude`
- API Endpoint: `https://api.codex.so/v1`
- 默认模型: `claude-opus-5`

**可选模型：**
- `claude-opus-5`：最强推理能力（预配置默认）
- `claude-sonnet-5`：平衡性能与速度
- `claude-haiku-4-5-20251001`：快速响应

**获取 API Key：**
访问 [Codesome](https://meta.codesome.cn/?aff=FAP2ASVX) 订阅 Codex 服务并获取 API Key。

**手动配置（可选，已自动完成）：**

```bash
cc-switch -a claude provider add codex-claude \
  --base-url https://api.codex.so/v1 \
  --model claude-opus-5

cc-switch -a claude provider set-key codex-claude
```

**快速切换：**
```bash
aisc switch --quick codex-claude
```

---

### 3. 火山引擎 Ark

火山引擎 Ark 提供兼容 OpenAI/Anthropic 格式的模型服务。

**✅ 已预配置框架 - 需设置 API Key 和 Endpoint ID：**

```bash
# 1. 更新为你的推理接入点 ID
cc-switch -a claude provider update volcengine-ark --model <your-endpoint-id>

# 2. 设置 API Key
cc-switch -a claude provider set-key volcengine-ark

# 3. 切换使用
cc-switch -a claude provider switch volcengine-ark
# 或在宿主机
aisc switch --quick volcengine-ark
```

**配置详情：**
- Provider ID: `volcengine-ark`
- API Endpoint: `https://ark.cn-beijing.volces.com/api/v3`
- 模型字段：需替换为你的推理接入点 ID

**注意事项：**
- `<your-endpoint-id>` 需替换为在火山引擎控制台创建的推理接入点 ID
- API Key 格式通常为 `<access-key>.<secret-key>`

**获取配置：**
访问 [火山引擎 Ark 控制台](https://console.volcengine.com/ark) 创建推理接入点和 API Key。

**手动配置（可选，已自动完成）：**

```bash
cc-switch -a claude provider add volcengine-ark \
  --base-url https://ark.cn-beijing.volces.com/api/v3 \
  --model <your-endpoint-id>

cc-switch -a claude provider set-key volcengine-ark
```

**快速切换：**
```bash
aisc switch --quick volcengine-ark
```

---

### 4. 智谱 Z.ai (GLM)

智谱 AI 提供 GLM 系列大语言模型。

**✅ 已预配置 - 只需设置 API Key：**

```bash
# 设置 API Key
cc-switch -a claude provider set-key zhipu

# 切换使用
cc-switch -a claude provider switch zhipu
# 或在宿主机
aisc switch --quick zhipu
```

**配置详情：**
- Provider ID: `zhipu`
- API Endpoint: `https://open.bigmodel.cn/api/paas/v4`
- 默认模型: `glm-4-plus`

**可选模型：**
- `glm-4-plus`：增强版 GLM-4（预配置默认）
- `glm-4-air`：轻量高速版
- `glm-4-flash`：极速响应版

**获取 API Key：**
访问 [智谱开放平台](https://open.bigmodel.cn/) 注册并创建 API Key。

**手动配置（可选，已自动完成）：**

```bash
cc-switch -a claude provider add zhipu \
  --base-url https://open.bigmodel.cn/api/paas/v4 \
  --model glm-4-plus

cc-switch -a claude provider set-key zhipu
```

**快速切换：**
```bash
aisc switch --quick zhipu
```

---

### 5. Kimi (月之暗面)

Kimi 提供长文本处理能力的 AI 模型服务。

**✅ 已预配置 - 只需设置 API Key：**

```bash
# 设置 API Key
cc-switch -a claude provider set-key kimi

# 切换使用
cc-switch -a claude provider switch kimi
# 或在宿主机
aisc switch --quick kimi
```

**配置详情：**
- Provider ID: `kimi`
- API Endpoint: `https://api.moonshot.cn/v1`
- 默认模型: `moonshot-v1-128k`

**可选模型：**
- `moonshot-v1-128k`：128K 上下文（预配置默认）
- `moonshot-v1-32k`：32K 上下文
- `moonshot-v1-8k`：8K 上下文，速度更快

**获取 API Key：**
访问 [Kimi 开放平台](https://platform.moonshot.cn/) 注册并创建 API Key。

**手动配置（可选，已自动完成）：**

```bash
cc-switch -a claude provider add kimi \
  --base-url https://api.moonshot.cn/v1 \
  --model moonshot-v1-128k

cc-switch -a claude provider set-key kimi
```

**快速切换：**
```bash
aisc switch --quick kimi
```

---

## 常见操作

### 查看所有 provider

```bash
cc-switch -a claude provider list
```

### 查看当前 provider

```bash
cc-switch -a claude provider current
```

### 删除 provider

```bash
cc-switch -a claude provider remove <provider-id>
```

### 更新 API Key

```bash
cc-switch -a claude provider set-key <provider-id> <new-api-key>
```

### 测试 provider 连接

```bash
# 切换到目标 provider 后直接使用
claude "测试消息"
```

---

## 注意事项

1. **自动预配置：** AISC v2.1.4+ 在容器首次启动时会自动添加上述 provider（除 API Key 外），无需手动执行 `provider add` 命令
2. **API Key 安全：** API Key 只存储在容器内 `.cc-switch/` 目录，不会写入代码仓库或 AISC 配置
3. **作用域选择：** 
   - `project` 作用域：配置保存在工作区 `.cc-switch/` 目录，跨容器保留
   - `temporary` 作用域：配置位于 `/tmp/aisc-home`，容器退出后清空
4. **快速切换限制：** `aisc switch --quick` 只支持 Claude provider，Codex provider 需在容器内使用 `cc-switch -a codex provider switch`
5. **模型兼容性：** 不同供应商的模型能力和 API 格式可能有差异，部分高级特性可能不可用
6. **计费方式：** 各供应商计费规则不同，使用前请了解对应平台的价格策略
7. **禁用预配置：** 如不需要自动预配置，可设置环境变量 `AISC_PRESET_PROVIDERS=off`（需在镜像构建时或运行时通过 Docker 传入）

---

## 故障排查

### Provider 切换失败

```bash
# 检查 cc-switch daemon 状态
cc-switch daemon status
cc-switch daemon logs

# 检查当前 provider 配置
cc-switch -a claude provider current
```

### API Key 无效

```bash
# 重新设置 API Key
cc-switch -a claude provider set-key <provider-id>

# 测试连接
claude "hello"
```

### 宿主机快速切换不可用

```bash
# 确认容器正在运行
aisc status

# 确认 provider 已在容器内配置
aisc shell
cc-switch -a claude provider list
```

---

## 相关文档

- [AISC 用户手册](../README.md)
- [AISC 开发者手册](../DEVELOP_WIKI.md)
- [cc-switch-cli 官方仓库](https://github.com/saladday/cc-switch-cli)
- [Codesome 文档](https://doc.codesome.ai/)
