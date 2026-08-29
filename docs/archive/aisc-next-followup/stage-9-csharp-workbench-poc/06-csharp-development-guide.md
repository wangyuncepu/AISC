# C# Workbench POC 开发文档

## 环境固定

- Windows 11 x64；Visual Studio 2022（含 .NET desktop、C++/Windows SDK 组件）；
- 固定 .NET、Windows App SDK、Windows SDK 最低版本并写入 `global.json`/CI image；
- 生产构建使用可审计的签名/打包流程；POC 可先使用 unpackaged 调试启动。

## 项目规则

- nullable reference types、分析器、TreatWarningsAsErrors 和格式化检查开启；
- async API 全部接收 `CancellationToken`；UI thread 不能执行阻塞进程、IO 或 JSON 解析；
- 所有跨层数据来自 versioned DTO；禁止用 `dynamic` 传递业务事实；
- `ProcessRunner` 使用 argv 列表和 stdin，不使用 shell；stdout/stderr 有大小预算和超时；
- secret 类型使用不可意外格式化/日志化的 wrapper，提交前运行 argv/log/diagnostic secret scan。

## Terminal control spike

先验证可用的 Microsoft/Windows Terminal 原生控件或官方支持组件：ANSI SGR、cursor、alternate screen、truecolor、CJK/IME、emoji/combining、方向键、bracketed paste、mouse、resize、selection 和 100MB 输出。记录 NuGet/native dependency、许可证、DPI、输入法和部署限制。没有满足项时停止 POC 的终端部分，不手写完整 VT parser。

## Process/session adapter

`Windows.ProcessRunner` 建立 child process 和 Windows Job Object；`Core.SessionStore` 管理 `starting|running|stopping|exited|failed`。输出通过 bounded channel 汇聚，UI 按帧/时间窗口批量消费；取消顺序为 cancel request -> stdin/PTY close -> bounded wait -> job terminate -> handle dispose。

## Protocol integration

先实现 `aisc.cli/v1` capability discovery、JSONL event decoder、stable error mapping 和 fixture tests，再接 UI。Provider tab 只调用 `aisc cc-switch ...`；不引用 cc-switch SQLite、Docker SDK 或 container filesystem path。

## Build and test commands

```text
dotnet restore workbench-csharp/Aisc.Workbench.sln
dotnet build workbench-csharp/Aisc.Workbench.sln -warnaserror
dotnet test workbench-csharp/Aisc.Workbench.sln --configuration Release
```

CI 必须覆盖 clean Windows VM、普通用户、DPI/locale 矩阵；手测报告引用 Stage 9 acceptance ID。
