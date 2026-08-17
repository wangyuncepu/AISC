# Stage 6 可观测性与测试

## 自动化

- token/static color/raw string 扫描；
- Vue component + axe/a11y；
- tabs/dialog/sidebar/menu keyboard；
- responsive screenshot matrix；
- reduced motion；
- operation/error redaction fixture；
- diagnostic allowlist/secret scan；
- migration/upgrade/rollback；
- full pytest/vitest/cargo/build/contract/soak smoke。

## 性能与发布

记录 Stage 0 冻结的冷启动、preflight、首字节、Tab/Pane、退出、artifact、Docker operation p50/p95/max；三平台 bundle/sidecar 版本、权限、资源、非 checkout cwd；Windows NSIS fresh/upgrade/uninstall/PATH/Docker；Linux/macOS 适用 smoke。

## 人工验收

暗/亮、中英、320/600/800/1280、100/150%、键盘/读屏、Docker unavailable/ready、Agent guide、Explorer/artifact、网络 skip/TUN、升级恢复。