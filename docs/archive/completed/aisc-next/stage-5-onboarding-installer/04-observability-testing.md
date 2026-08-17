# Stage 5 可观测性与测试

## 指标

step enter/exit/duration/outcome、resume/skip/retry、Docker installed→ready duration、network probe outcome、runtime first-ready；不记录路径正文、key、prompt。

## 自动化

- onboarding reducer/checkpoint/migration/unsupported/corrupt；
- NSIS handoff schema 和 locale；
- environment/agent/network/runtime 状态映射；
- Docker deadline/retry/cancel/stale；
- step back/skip/reopen，不重复 destructive action；
- i18n、focus、aria、compact、reduced motion；
- installer workflow/path filters/smoke。

## 真机矩阵

Windows：fresh/upgrade/reinstall/uninstall；Docker 未装、winget 失败、许可未接受、WSL 初始化、需重启、starting、ready；WebView2；PATH 冲突。

Linux/macOS：bundle 首次向导、Docker unavailable/ready、workspace、Agent、network skip、Runtime。

网络：无代理、宿主代理、错误代理、TUN 成功/失败/撤销、离线；不得因探针失败阻止用户稍后继续。

## 视觉/可访问性

320/600/800/1280、100/150%、中英、暗/亮、键盘、读屏；截图基线只验证结构和可见操作，不锁死动态状态文本。