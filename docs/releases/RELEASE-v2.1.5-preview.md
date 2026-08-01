# AISC v2.1.5 Preview - Provider 预配置增强

## 新增特性

### 🎯 Provider 自动预配置

**AISC v2.1.5 在镜像构建时自动预配置常见 AI 供应商**，用户只需设置 API Key 即可立即使用，大幅简化配置流程。

#### 预配置的供应商

容器首次启动时，以下 provider 会自动添加到 cc-switch（除 API Key 外的所有参数）：

1. **DeepSeek** (`deepseek`)
   - API Endpoint: `https://api.deepseek.com/v1`
   - 默认模型: `deepseek-chat`
   - 描述：高性价比 AI 模型服务

2. **Claude via Codex 订阅** (`codex-claude`)
   - API Endpoint: `https://api.codex.so/v1`
   - 默认模型: `claude-opus-5`
   - 描述：通过 Codex 订阅访问 Claude 官方模型

3. **火山引擎 Ark** (`volcengine-ark`)
   - API Endpoint: `https://ark.cn-beijing.volces.com/api/v3`
   - 模型：需用户指定推理接入点 ID
   - 描述：火山引擎模型推理服务

4. **智谱 GLM** (`zhipu`)
   - API Endpoint: `https://open.bigmodel.cn/api/paas/v4`
   - 默认模型: `glm-4-plus`
   - 描述：智谱 AI GLM 系列模型

5. **Kimi** (`kimi`)
   - API Endpoint: `https://api.moonshot.cn/v1`
   - 默认模型: `moonshot-v1-128k`
   - 描述：月之暗面长文本 AI 模型

#### 使用体验对比

**v2.1.4 及之前（需手动配置）：**
```bash
# 1. 添加 provider
cc-switch -a claude provider add deepseek \
  --base-url https://api.deepseek.com/v1 \
  --model deepseek-chat

# 2. 设置 API Key
cc-switch -a claude provider set-key deepseek

# 3. 切换使用
cc-switch -a claude provider switch deepseek
```

**v2.1.5+（已预配置）：**
```bash
# 1. 直接设置 API Key
cc-switch -a claude provider set-key deepseek

# 2. 切换使用
cc-switch -a claude provider switch deepseek
# 或在宿主机快速切换
aisc switch --quick deepseek
```

#### 技术实现

1. **预配置脚本** (`container/lib/cc_switch_preset_providers.py`)
   - 容器启动时自动运行
   - 检查数据库中已存在的 provider，避免重复添加
   - 使用版本标记文件，支持增量更新

2. **集成到 entrypoint.sh**
   - 在 cc-switch daemon 启动后自动执行
   - 支持环境变量控制：`AISC_PRESET_PROVIDERS=auto|always|off`
   - 失败不阻断容器启动，记录日志便于排查

3. **幂等性保证**
   - 已存在的 provider 不会被覆盖
   - 用户自定义配置优先级高于预设
   - 支持项目和临时两种作用域

#### 环境变量控制

```bash
# 默认行为：仅在首次启动或版本变更时添加
AISC_PRESET_PROVIDERS=auto

# 强制每次启动都检查并添加缺失的 provider
AISC_PRESET_PROVIDERS=always

# 完全禁用自动预配置
AISC_PRESET_PROVIDERS=off
```

## 文档更新

1. **新增文档**
   - `docs/provider-quick-setup.md` - Provider 一键配置指南（408 行）
     - 快速开始指南
     - 5 个供应商的详细配置说明
     - 常见操作和故障排查

2. **更新文档**
   - `README.md` - 添加 Provider 快速配置章节
   - `docs/TODO/TODO.md` - 标记任务完成

## 兼容性

- **向后兼容**：v2.1.5 的预配置机制不影响已有的 provider 配置
- **可选功能**：可通过 `AISC_PRESET_PROVIDERS=off` 禁用
- **升级路径**：
  - 从 v2.1.4 升级到 v2.1.5，首次启动容器时会自动添加预设 provider
  - 已手动配置的 provider 不会被覆盖
  - API Key 需要用户重新设置（安全考虑，不会自动迁移）

## 用户收益

1. **降低入门门槛**：新用户无需学习复杂的 provider 配置命令
2. **提升配置效率**：从 3 步缩减到 2 步（省略 `provider add`）
3. **减少配置错误**：预设参数经过验证，避免 API Endpoint 或模型名称错误
4. **开箱即用体验**：容器启动后即可查看可用的 provider 列表

## 使用示例

### 场景 1：首次使用 DeepSeek

```bash
# 启动容器后
$ cc-switch -a claude provider list
✓ deepseek [no key] - DeepSeek 高性价比 AI 模型服务
✓ codex-claude [no key] - 通过 Codex 订阅访问 Claude 官方模型
...

# 设置 API Key
$ cc-switch -a claude provider set-key deepseek
Enter API Key: ********

# 切换并使用
$ aisc switch --quick deepseek
Switched to provider 'deepseek'

$ claude "你好"
你好！有什么我可以帮助你的吗？
```

### 场景 2：在项目间切换供应商

```bash
# 项目 A 使用 DeepSeek
$ cd /path/to/project-a
$ aisc run
$ cc-switch -a claude provider switch deepseek

# 项目 B 使用 Codex Claude
$ cd /path/to/project-b
$ aisc run
$ cc-switch -a claude provider switch codex-claude
```

### 场景 3：快速测试不同供应商

```bash
# 测试 DeepSeek
$ aisc switch --quick deepseek
$ claude "写一个快速排序"

# 测试智谱 GLM
$ aisc switch --quick zhipu
$ claude "写一个快速排序"

# 比较输出质量和响应速度
```

## 注意事项

1. **API Key 安全**：预配置不包含 API Key，用户需自行设置
2. **网络要求**：各供应商 API 可能需要网络代理，请配置 Mihomo TUN
3. **费用管理**：不同供应商计费规则不同，请注意成本控制
4. **模型限制**：部分供应商的模型可能不支持所有 Claude Code 特性

## 相关链接

- [Provider 快速配置文档](../provider-quick-setup.md)
- [AISC 用户手册](../../README.md)
- [cc-switch-cli 官方仓库](https://github.com/saladday/cc-switch-cli)
- [Codesome 文档](https://doc.codesome.ai/)
