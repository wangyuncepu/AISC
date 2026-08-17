# Stage 3 用户流程

> 基线：`d2bdcd9`

## Explorer

```text
Ready workspace
  → 打开 Explorer rail
  → lazy 展开目录
  → 选择文件
  → [预览] [系统打开] [在文件管理器中显示] [复制相对/绝对路径]
```

目录未授权、路径消失或越界时显示短错误和“刷新/诊断”，不展示 raw OS error 作为主文案。

## Agent 产物

```text
Agent 创建文件
  → Artifact Skill 分类并调用 aisc artifact record
  → CLI 验证相对路径并写 session registry
  → Workbench 导入/验证
  → Artifact 面板显示 Deliverable
  → 用户打开/Reveal/复制路径
```

Agent 最终回答仍列出相对路径，但 GUI 不解析该自然语言作为事实。

## 未登记变化

```text
watcher 发现文件变化
  → “工作区变化（未归因）”
  → 用户可打开/Reveal
  → 不显示 Agent badge
```

watcher overflow：顶部显示“文件状态可能过期”，执行 bounded rescan；rescan 未完成前保留 last-known 并标 stale。

## 面板信息架构

```text
Explorer
Artifacts
  本次会话
    Deliverables
    Source changes
    Generated outputs
  其他会话
Workspace changes (unattributed)
```

默认突出 Deliverable；源码和生成输出折叠计数。窄窗使用抽屉；键盘支持树的上下/左右/Home/End，操作菜单支持 Enter/Shift+F10/Escape。

## 空态/错误态

- 无 workspace：引导选择工作区。
- 无 artifact：说明 Agent 生成可交付文件后会显示，不承诺自动捕获全部。
- 文件删除：保留记录并标 missing/deleted，可从历史移除。
- preview 不支持：提供系统打开/Reveal。
