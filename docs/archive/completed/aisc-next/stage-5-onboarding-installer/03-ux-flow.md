# Stage 5 UX Flow

## NSIS

```text
欢迎/语言 → 安装位置 → 依赖检查 → 安装进度 → 完成/启动
```

单一主操作，技术日志折叠；失败显示原因、重试/返回/退出。Docker Desktop 可安装/启动，但不在安装器无限等待 Engine。

## Workbench 首次向导

```text
欢迎
 → 环境就绪（CLI/Docker/WebView2）
 → 工作区（新建/打开/最近/恢复）
 → Agent（Claude/Codex/Bash/cc-switch）
 → 网络（直连/宿主代理/容器 TUN/稍后）
 → Runtime（new/reuse/restart/restore 摘要）
 → 完成并进入 workspace
```

每页：标题、简短说明、主任务、一个主按钮、可选详情；步骤 rail 显示 complete/current/action required/skipped。

## 可恢复

关闭应用后从 checkpoint 恢复；Back 不撤销已安装依赖；Skip 记录理由并在相关功能入口提示。Settings/Help 可重新打开，不清除现有 workspace/runtime。

## Agent 页

不显示 raw `not_configured/login_required`，映射为 Ready/需要登录/需要配置；操作进入现有 guide/cc-switch，不收集 API Key。

## 网络页

默认直连；检测到连接问题才推荐宿主代理/TUN。TUN 显示用途、权限、影响、验证和撤销；可跳过。
