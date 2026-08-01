# AISC 代理/翻墙设置分析与优化

本文档分析容器内代理设置，排查与 cc-switch 的冲突，并验证 Codex 官方访问。

---

## 当前架构

### 1. 代理层级

容器内存在两层代理机制：

#### A. Mihomo TUN 透明代理（网络层）

- **启动时机**：`aisc run --network proxy` 且存在 `/etc/mihomo/config.yaml`
- **作用范围**：容器全局流量（TUN 设备接管所有出站）
- **实现方式**：TUN + iptables auto-route
- **健康检查**：`curl https://api.anthropic.com`
- **日志位置**：`/tmp/aisc-mihomo/mihomo.log`

#### B. cc-switch proxy（应用层）

- **启动时机**：cc-switch daemon 启动后
- **Claude**：自动启用（`cc-switch proxy -a claude enable`）
- **Codex**：默认**不启用**（保持官方直连）
- **作用范围**：拦截 Claude/Codex CLI 的 API 请求
- **目标**：允许通过 cc-switch 管理的 provider 访问 AI 服务

### 2. 启动顺序（entrypoint.sh）

```
1. 初始化作用域（temporary/project）
2. 启动 cc-switch daemon
3. 初始化 Codex provider（导入 config.toml 或使用 codex-official）
4. 预配置 provider（Claude + Codex）
5. cc-switch proxy -a claude enable     ← 应用层代理（Claude only）
6. Mihomo TUN 启动（如果存在配置）    ← 网络层代理（全局）
7. exec 用户选择的进程（bash/claude/codex）
```

---

## 冲突分析

### 问题 1：双层代理冲突

**现象：**
- Mihomo TUN：全局透明代理，接管所有容器流量
- cc-switch proxy：应用层本地代理，拦截 Claude API 请求

**潜在问题：**
1. **死循环风险**：cc-switch proxy 监听本地端口 → Claude 请求被代理到 cc-switch → cc-switch 转发到上游 → 被 Mihomo TUN 拦截 → 可能回到 cc-switch
2. **双重延迟**：请求经过两层代理，增加延迟
3. **错误诊断困难**：失败时难以判断是哪一层代理的问题

**实际影响：**
- 如果 Mihomo 配置正确（不代理本地流量），可以正常工作
- 如果 Mihomo 配置不当，可能导致连接失败

### 问题 2：Codex 官方直连意图 vs 实际行为

**设计意图：**
```bash
# Codex 默认不启用 cc-switch 代理
echo "ℹ️  Codex 未自动启用 cc-switch 代理；需要时可手动运行 cc-switch proxy -a codex enable。"
```

**实际行为：**
- 当 Mihomo TUN 启动时，**所有容器流量**都被接管
- Codex 的 API 请求也会经过 Mihomo 代理
- 结果：**Codex 实际上是走代理的**，而不是"官方直连"

**影响：**
- 如果用户期望 Codex 走官方直连（不经代理），当前架构无法实现
- 文档说明与实际行为不符

### 问题 3：Codex 官方访问验证

**Codex 官方端点：**
- API: `https://api.openai.com` (OpenAI Codex 已停止公开访问)
- 新版 Codex: 通过 Claude Code 集成，可能使用不同端点

**访问需求：**
- 国内网络访问 OpenAI API 通常需要代理
- Codex 官方登录流程可能需要浏览器认证
- 容器内环境可能无法完成网页登录

**当前状态：**
- `codex-official` provider 预置在数据库中
- 但不包含用户凭据，需要用户自行登录或配置 API Key

---

## 建议方案

### 方案 A：优化双层代理兼容性（推荐）

**目标：** 保持两层代理并存，但优化配置避免冲突

**实现：**

1. **Mihomo 配置优化**
   - 添加规则排除本地回环地址
   - 确保 `127.0.0.1` 和 `localhost` 不经过代理
   - 示例规则：
     ```yaml
     rules:
       - IP-CIDR,127.0.0.0/8,DIRECT
       - DOMAIN-SUFFIX,localhost,DIRECT
       - DOMAIN-KEYWORD,cc-switch,DIRECT
     ```

2. **启动顺序调整**
   - 保持 cc-switch proxy 先启动
   - Mihomo 后启动，确保不覆盖 cc-switch 的本地监听

3. **健康检查增强**
   - 在 Mihomo 启动后，测试 cc-switch proxy 是否仍然可达
   - 测试实际 Claude/Codex 请求是否能正常工作

4. **文档澄清**
   - 明确说明：在 proxy 模式下，Codex 也会走 Mihomo 代理
   - 提供关闭特定服务代理的方法

### 方案 B：分离代理层级

**目标：** 明确各层代理的职责，避免冲突

**实现：**

1. **Mihomo TUN 作为唯一代理**
   - 禁用 cc-switch proxy（对于使用 Mihomo 的用户）
   - 所有流量统一通过 Mihomo 处理
   - 优点：架构简单，易于理解
   - 缺点：无法使用 cc-switch 管理的自定义 provider

2. **cc-switch proxy 作为唯一代理**
   - 不启动 Mihomo TUN
   - 通过 cc-switch provider 配置代理
   - 优点：灵活性高，provider 级别控制
   - 缺点：需要为每个 provider 配置代理

### 方案 C：按需选择模式（最灵活）

**目标：** 让用户根据需求选择代理模式

**实现：**

添加环境变量控制：

```bash
# 代理模式选择
AISC_PROXY_MODE=none|cc-switch|mihomo|hybrid

# none: 不启用任何代理
# cc-switch: 只启用 cc-switch proxy
# mihomo: 只启用 Mihomo TUN
# hybrid: 两者都启用（当前默认）
```

---

## Codex 官方访问验证

### 当前状态

**Codex CLI：**
- 版本：OpenAI Codex（已集成到 Claude Code）
- 官方端点：可能已变更或不再公开
- 登录方式：Web 认证或 API Key

**容器内访问：**
- 直连测试：需要在无代理环境下测试
- 代理测试：通过 Mihomo 测试是否可达
- 结论：需要实际测试才能确定

### 验证步骤

```bash
# 1. 进入容器
aisc run

# 2. 测试直连（关闭代理）
cc-switch proxy -a codex disable
codex --version
codex auth status

# 3. 测试通过 Mihomo 代理
# （如果启用了 --network proxy）
curl -v https://api.openai.com

# 4. 测试 cc-switch 托管的 provider
cc-switch proxy -a codex enable
cc-switch -a codex provider current
codex "test"
```

### 预期结果

| 场景 | 无代理 | Mihomo TUN | cc-switch proxy |
|------|--------|-----------|-----------------|
| Codex 官方 API | ❌ 国内不可达 | ✅ 可达 | ✅ 可达（需配置） |
| Web 认证登录 | ❌ 需要浏览器 | ❌ 容器内无浏览器 | ❌ 容器内无浏览器 |
| API Key 认证 | ✅ 可用 | ✅ 可用 | ✅ 可用 |

**结论：**
- 容器内**无法完成网页登录**（无浏览器）
- 国内直连 OpenAI API **需要代理**
- **推荐方式**：使用 API Key 认证 + Mihomo 代理

---

## 配置示例

### 1. 只使用 Mihomo TUN（推荐给国内用户）

```bash
# 启动容器时启用代理模式
aisc run --network proxy

# 容器内禁用 cc-switch proxy（让 Mihomo 统一处理）
cc-switch proxy -a claude disable
cc-switch proxy -a codex disable

# 使用预配置的 provider
cc-switch -a claude provider list
cc-switch -a claude provider set-key deepseek
cc-switch -a claude provider switch deepseek
```

### 2. 只使用 cc-switch proxy（推荐给国外用户或企业代理）

```bash
# 启动容器时不启用 proxy 模式
aisc run

# 容器内配置 provider 级别的代理
cc-switch -a claude provider add my-proxy \
  --base-url https://my-proxy.example.com/v1 \
  --model claude-opus-5

cc-switch -a claude provider set-key my-proxy
cc-switch proxy -a claude enable
```

### 3. 混合模式（当前默认）

```bash
# 启动时启用 Mihomo
aisc run --network proxy

# cc-switch proxy 自动启用（Claude）
# Codex 保持通过 Mihomo 直达官方

# 如果需要为 Codex 使用 cc-switch provider
cc-switch proxy -a codex enable
cc-switch -a codex provider switch my-codex-provider
```

---

## 故障排查

### 问题 1：Claude/Codex 连接失败

```bash
# 检查 cc-switch daemon
cc-switch daemon status
cc-switch daemon logs

# 检查 proxy 状态
cc-switch proxy show

# 检查 Mihomo
pgrep -f mihomo
cat /tmp/aisc-mihomo/mihomo.log
```

### 问题 2：代理死循环

**症状：**
- 请求超时或无限等待
- Mihomo 日志显示大量重复请求

**解决：**
```bash
# 临时禁用 cc-switch proxy
cc-switch proxy -a claude disable
cc-switch proxy -a codex disable

# 或重启容器并不启用 proxy 模式
aisc stop
aisc run  # 不使用 --network proxy
```

### 问题 3：Codex 无法登录

**症状：**
- `codex auth login` 失败
- 提示需要浏览器

**解决：**
```bash
# 方案 1：使用 API Key（推荐）
# 在 Codex 官网获取 API Key
codex config set api_key <your-key>

# 方案 2：在宿主机浏览器登录后复制凭据
# （需要手动处理认证流程）
```

---

## 推荐配置

### 国内用户

```bash
# 使用 Mihomo TUN + 预配置 provider
aisc run --network proxy
aisc provider set-key deepseek
aisc switch --quick deepseek
```

**优势：**
- 统一代理管理
- 无需配置每个 provider 的代理
- 预配置供应商开箱即用

### 国外用户

```bash
# 直连模式，无需代理
aisc run
cc-switch -a claude provider switch codex-claude
cc-switch -a claude provider set-key codex-claude
```

**优势：**
- 无代理开销
- 官方直连速度更快
- 配置简单

---

## 后续优化建议

1. **添加代理模式选择**
   - 环境变量 `AISC_PROXY_MODE=none|cc-switch|mihomo|hybrid`
   - 根据模式自动调整启动流程

2. **改进健康检查**
   - 测试实际 Claude/Codex 请求，而不仅仅是 curl
   - 检测双层代理冲突

3. **文档完善**
   - 明确说明各种代理模式的适用场景
   - 提供针对国内/国外用户的最佳实践

4. **Codex 访问优化**
   - 调研 Codex 当前的官方访问方式
   - 提供容器内友好的认证流程

---

## 相关文档

- [AISC 用户手册](../README.md)
- [AISC 开发者手册](../DEVELOP_WIKI.md)
- [Provider 快速配置](./provider-quick-setup.md)
