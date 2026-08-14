# Stage 6 Domain Contract

## UI tokens/layout

统一 spacing/type/control/radius/shadow/z/duration；布局等级：Compact `<640px`、Standard `640–1100px`、Wide `>1100px`。Sidebar/Explorer/Tab/terminal 的最小宽高必须显式定义。

## Accessibility

- Tabs 使用 roving tabindex、真实 tabpanel 关联；
- Dialog 保存 opener、focus trap、inert、Escape、restore；
- copy/list/context actions 是 button/menuitem；
- reduced motion 下 duration/smooth scroll 为 0；
- 用户层文案全部 message key，raw enum 只在 developer details。

## Operation/diagnostic

```json
{"operation_id":"...","source":"rust|cli|docker|ui","phase":"...","duration_ms":123,"outcome":"ok|error|cancel","error_code":null,"retryable":true,"action":"retry","detail":null}
```

诊断包只允许 version/platform/capabilities/redacted settings/stable errors/timings；导出前展示清单。

## Release compatibility

settings/history/artifact/onboarding/CLI protocol migration 必须支持 current/previous fixture；unsupported schema fail closed；升级、回滚、卸载保留用户数据和 PATH。