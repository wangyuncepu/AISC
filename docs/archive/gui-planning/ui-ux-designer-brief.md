1. 终端是主工作区域；
2. 产品需要支持高信息密度，但不能混乱；
3. 状态可见性、错误解释和恢复路径比装饰性更重要；
4. 暗色优先，但亮色主题、中文/英文和不同窗口尺寸也必须可用。


## 2. 核心对象关系

```text
Workbench
 ├─ Workspace 工作区
 │   ├─ Runtime 容器运行时
 │   ├─ Session / Tab Agent 会话
 │   ├─ Terminal 终端
 │   ├─ Explorer 文件 / 产物
 │   └─ Status 状态与诊断
 ├─ Provider 管理
 ├─ Network / Usage 网络与用量
 └─ Settings 设置
```

本次设计的重点不是单个页面，而是重新审视 Workspace、Runtime、Session、Provider 之间的层级和关系。

## 3. 会议目标

希望设计师帮助完成以下工作：

1. 梳理开发者工作台的信息架构；
2. 明确 Workspace、Runtime、Session、Provider 的层级关系；
3. 优化首次启动、工作区选择和 Runtime 启动流程；
4. 优化主工作区、Tab、Explorer、Terminal 和状态抽屉；
5. 建立统一的状态、反馈和错误恢复体系；
6. 形成适配 Compact / Standard / Wide 的布局方案；
7. 建立 Dark / Light 主题及组件视觉规范；
8. 输出可供开发落地的设计稿、原型和标注。

## 4. 演示顺序

演示应按照真实用户任务进行，不要只逐个介绍页面和按钮。

### 4.1 首次启动与 Onboarding

流程：

```text
首次打开
→ 环境检测
→ Docker / CLI / WebView2 检查
→ 选择工作区
→ 选择 Agent
→ 选择网络模式
→ Runtime 预检
→ 进入主工作区
```

需要展示：

- 正常完成流程；
- Docker 或 CLI 不可用时的失败流程；
- 重试、跳过、稍后配置和打开诊断等恢复路径。

请设计师重点观察：

- 用户是否知道当前处于哪一步；
- 技术概念是否需要解释；
- 失败后是否清楚下一步做什么；
- 首次启动是否信息过多；
- 是否需要提供简易模式和高级模式。

### 4.2 工作区选择与启动流程

流程：

```text
选择目录
→ 最近工作区
→ Preflight 检查
→ 启动摘要
→ 构建镜像
→ 启动 Runtime
→ 进入终端
```

重点展示：

- 长路径和长工作区名称；
- Preflight 检查；
- Docker 未启动；
- 镜像不存在需要构建；
- Runtime 冲突；
- 启动中、取消、失败、重试等状态。

需要讨论：

- Preflight 是否默认只显示“可启动 / 不可启动”；
- 技术详情是否折叠；
- “构建镜像”如何用普通用户能理解的方式表达；
- Runtime 冲突如何解释；
- 启动过程中使用阶段进度、百分比、日志还是当前动作提示。

### 4.3 主工作区

当前主界面包含：

```text
顶部标题栏
→ WorkspaceBar 工作区切换
→ TabBar Agent 会话切换
→ Explorer / Artifacts
→ Terminal
→ Runtime 状态和诊断
```

建议完整演示：

1. 打开 Bash；
2. 新建 Claude / Codex 会话；
3. 切换多个 Tab；
4. 关闭和重新打开 Tab；
5. 查看文件和 Agent 产物；
6. 打开 Runtime 状态抽屉；
7. 切换 Provider；
8. 打开 Settings / Usage；
9. 返回终端继续工作。

需要设计师回答：

- 用户当前最关心的是 Workspace、Runtime 还是 Session；
- WorkspaceBar 和 TabBar 是否容易混淆；
- Runtime 状态应该放在哪里；
- Provider 是全局、工作区级别还是 Agent 级别；
- Explorer 是否应该默认展开；
- Status Drawer 应该常驻、隐藏还是只在异常时出现。

### 4.4 多工作区与多 Tab

建议模拟：

```text
Workspace A：项目 A
 ├─ Bash
 ├─ Claude
 └─ Codex

Workspace B：项目 B
 └─ Bash
```

演示：

- 新建工作区；
- 工作区之间切换；
- 同一工作区创建多个 Agent Tab；
- 关闭工作区；
- 工作区达到并发上限；
- 工作区处于启动中、停止中、异常或过期状态。

需要讨论：

- Workspace 和 Tab 是否需要不同的视觉语言；
- 是否显示项目类型、Git 分支或工作区图标；
- 如何快速识别当前上下文；
- 关闭工作区和关闭 Session 是否容易误操作；
- 是否需要工作区级菜单或右键菜单。

### 4.5 Provider、网络与用量

展示：

- Provider 列表；
- 新增、编辑、删除 Provider；
- 简单配置和自定义配置；
- Secret 掩码；
- 当前 Provider；
- 网络订阅；
- Provider 用量统计；
- Token、请求数、成功率和费用估算。

需要讨论：

- Provider 管理是否应该属于 Settings；
- Provider 是否应该在主工作区显示当前状态；
- 用量页面偏监控还是成本管理；
- 复杂字段是否需要分组或分步表单；
- 加载、错误、空数据和数据过期如何表达。

### 4.6 Settings、Doctor 和错误状态

建议展示：

- Settings；
- Doctor 诊断；
- Runtime 错误；
- Provider 错误；
- 文件状态过期；
- Session exited / failed / disconnected；
- Docker 未启动；
- 工作区冲突。

对于本项目，异常状态和恢复路径与正常态同等重要。

## 5. 当前问题与设计重点

### P0：必须优先解决

1. Workspace、Runtime、Session 的信息层级；
2. 启动失败和错误恢复流程；
3. 长路径、长名称、长 Provider 名的布局策略；
4. Tab 与 Workspace 的视觉区分；
5. Escape、关闭、返回、取消等退出路径；
6. 键盘焦点与 Tab 导航；
7. Compact 窗口下的基本可用性；
8. Loading、Ready、Warning、Error、Disabled、Stale、Exited 状态体系。

### P1：第二优先级

1. 主工作区视觉层级；
2. Explorer 与 Artifacts 的信息组织；
3. Runtime 状态抽屉；
4. Provider 表单和列表；
5. Settings 分组与帮助文案；
6. Onboarding 步骤简化；
7. Light / Dark 双主题一致性；
8. 中英文长文案适配。

### P2：后续优化

1. 动效细节；
2. 快捷键提示；
3. 个性化工作区；
4. 更丰富的 Agent 状态表达；
5. 空状态插图或品牌化视觉；
6. 更高级的成本分析和用量可视化。

## 6. 已发现的具体问题

| 编号 | 位置 | 当前问题 | 影响 |
|---|---|---|---|
| B-01 | 工作区选择 | 超长文件夹名可能超出界面边界 | 破坏布局 |
| B-02 | WorkspaceBar / TabBar | 超长工作区名称挤压其他 Tab | 当前上下文不易识别 |
| B-03 | Provider 页面 | 超长 Provider 名与其他内容重叠 | 信息不可读 |
| B-04 | 全局 Tab、按钮、滑块 | 控件偏小，点击和识别成本较高 | 使用体验不稳定 |
| B-05 | 终端输入 | 长输入存在不换行或覆盖问题 | 影响核心工作流，需与技术问题区分 |
| B-06 | 终端布局 | resize 时列数不实时跟随 | 影响终端可用性，需单独跟进 |
| B-07 | Dialog / Menu / Drawer | Escape 关闭路径不完整 | 用户缺少明确退出方式 |
| B-08 | 键盘导航 | 焦点无法完整穿越页面 | 影响无障碍和高级用户效率 |

注意：B-05、B-06 属于终端行为或技术问题，不能仅依靠视觉设计解决，应单独登记和排期。

## 7. UI/UX 需求表达方式

建议采用以下结构提出每一项需求：

```text
用户场景
→ 当前行为
→ 存在的问题
→ 对用户的影响
→ 设计目标
→ 技术约束
→ 验收标准
```

### 示例：长工作区名称

用户选择路径较深、名称较长的代码项目时，工作区名称会挤压 WorkspaceBar 和 TabBar，导致其他 Tab 不容易识别。

希望在不丢失完整路径信息的前提下，设计：

- 名称截断规则；
- Tooltip 或详情展示；
- 最小可用宽度；
- 过长名称下的操作按钮布局。

验收标准：

- 长名称不会挤出操作按钮；
- 当前工作区仍然容易识别；
- 完整路径可以通过 Tooltip 或详情查看。

### 示例：启动失败

Docker、CLI 或工作区权限检查失败时，当前界面会展示技术状态，但用户不一定知道下一步动作。

希望将错误页面设计成：

```text
发生了什么
→ 为什么发生
→ 用户可以做什么
→ 技术详情（可选）
```

至少提供：

- 重试；
- 打开诊断；
- 修改设置；
- 返回选择工作区；
- 展开技术详情。

### 示例：Tab 与 Workspace 层级

当前界面同时存在 WorkspaceBar 和 Session TabBar。希望重新定义两者的视觉层级和命名，使用户明确区分：

- 切换项目；
- 切换 Agent 会话。

建议通过位置、尺寸、图标、颜色和交互方式形成层级，而不是继续增加装饰。

### 示例：终端优先

终端是用户主要工作区域。Explorer、Runtime 状态和 Provider 信息不能抢占过多终端空间。

希望在 Compact、Standard、Wide 三种窗口宽度下：

- 终端始终拥有最大可用面积；
- 异常状态和关键操作仍然可见；
- 辅助信息可以折叠、抽屉化或延后展示；
- 不使用高频动画和大面积装饰背景。

## 8. 视觉和交互原则

### 8.1 总体原则

- 开发者工作台 / IDE command center 定位；
- 高信息密度，但保持平静、清晰；
- 暗色优先，亮色等价；
- 终端是主视觉；
- 使用表面、分隔和层级表达结构；
- 避免营销型 Dashboard、Hero、玻璃拟态、重 Blur、霓虹阴影和持续装饰动画。

### 8.2 状态表达

| 状态 | 设计要求 |
|---|---|
| Loading | 说明正在执行什么动作，不能只显示转圈 |
| Ready / Success | 展示结果或下一步动作 |
| Info | 用于解释，不伪装成警告 |
| Warning / Stale | 说明影响和恢复路径 |
| Error | 稳定错误标题、明确动作、可展开详情 |
| Selected / Active | 使用 selected surface 与 accent，同时同步语义状态 |
| Disabled | 说明不可用原因，不能只用低对比度隐藏原因 |
| Empty | 说明当前没有内容，并提供下一步动作 |

### 8.3 响应式布局

- Compact：隐藏非必要摘要，保留操作、Tooltip 和键盘可达性；
- Standard：终端保持最大面积，侧栏和抽屉边界清晰；
- Wide：增加有价值的信息摘要，而不是装饰性空白；
- 长文本必须支持截断、换行或详情查看；
- 中英文切换不能破坏布局；
- `ui.font_scale` 放大后不能造成主要操作溢出。

### 8.4 可访问性和键盘

需要覆盖：

- Tab / Shift+Tab；
- Enter / Space；
- 方向键；
- Home / End；
- Escape；
- Shift+F10 / Menu key；
- focus-visible；
- reduced-motion；
- aria-selected；
- aria-expanded；
- aria-label。

## 9. 设计交付物

不要只要求几张视觉效果图，建议明确要求以下交付物：

1. 产品信息架构图；
2. 核心用户流程图；
3. 主工作区线框图；
4. Onboarding / Startup 流程稿；
5. Workspace 与 Tab 的层级方案；
6. 状态矩阵；
7. Compact / Standard / Wide 三档布局；
8. Dark / Light 主题方案；
9. Button、Input、Tab、Badge、Drawer、Dialog、Menu、Toast 等组件规范；
10. 可点击原型；
11. 开发标注和交付规范；
12. 分阶段实施建议和优先级。

尤其需要交付：

> 状态设计，而不只是正常态页面。

本项目需要重点覆盖启动中、启动失败、Runtime 冲突、Provider 未配置、终端退出、文件状态过期、网络错误和诊断等状态。

## 10. 建议会议流程

如果会议约 60 分钟：

| 时间 | 内容 |
|---|---|
| 5 分钟 | 产品定位、目标用户、核心对象 |
| 10 分钟 | 首次启动和工作区选择 |
| 15 分钟 | 主工作区、Terminal、Tab、Explorer |
| 10 分钟 | 多工作区、Provider、Usage、Settings |
| 10 分钟 | 展示当前问题和截图证据 |
| 5 分钟 | 明确优先级 |
| 5 分钟 | 确认设计交付物和下一步 |

演示时建议使用真实任务：

> 打开一个项目，启动 Codex，让它修改代码，查看生成的文件，再切换到 Claude 继续工作；如果 Docker 未启动，观察用户是否知道如何恢复。

## 11. 会议结束前需要确认的问题

1. 设计师如何定义 Workspace、Runtime、Session、Provider 的层级？
2. WorkspaceBar 和 TabBar 是否需要重新设计？
3. 终端、Explorer、Status Drawer 的默认布局是什么？
4. 启动失败和 Runtime 冲突的主恢复路径是什么？
5. Compact / Standard / Wide 三种布局如何处理？
6. Dark / Light 主题是否共用同一套语义 Token？
7. 哪些问题属于 UI/UX，哪些需要单独作为技术问题处理？
8. 第一阶段最应该交付哪三个核心流程？
9. 设计稿是否包含状态、交互、键盘和无障碍标注？
10. 设计验收和开发验收的标准分别是什么？

