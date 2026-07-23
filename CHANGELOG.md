# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0-dev] - 2026-07-23

### Added

- **OpenAI Codex CLI 集成**：在容器中添加 `@openai/codex` npm 包
- **codex-wrapper**：创建 Codex 包装器脚本，支持环境变量注入
- **双 CLI 支持**：同时支持 Claude Code 和 OpenAI Codex
- **启动菜单增强**：添加第三个选项用于直接启动 Codex
- **Codex 配置目录**：支持临时模式（`/root/.codex`）和项目模式（`/root/app/.codex`）
- **环境变量**：新增 `CODEX_CONFIG_DIR` 和 `CLI_SCOPE`

### Changed

- **作用域选择**：从 "Claude 作用域" 改为 "AI CLI 作用域"，适用于两个 CLI
- **初始化消息**：从 "Super Claude 工作站" 改为 "AISC AI 工作站"
- **启动流程**：支持 `docker run ... codex` 直接启动 Codex
- **容器运行身份**：改为 root，移除宿主 UID 映射和启动/退出时的递归 chown，解决 WSL2 bind mount 中 root:root 文件的权限错误
- **沙箱标识**：容器内默认设置 `IS_SANDBOX=1`
- **README 文档**：全面更新，添加 Codex CLI 使用说明

### Technical Details

- Dockerfile 中同时安装 `@anthropic-ai/claude-code` 和 `@openai/codex`
- 无需 tmux 依赖（容器中不安装 tmux）
- 两个 CLI 共享 AISC 配置目录（`/root/app/.aisc`）
- Codex 使用独立配置目录，与 Claude 配置隔离

## [2.0.5] - 2026-07-23

### Fixed

- 修正 settings.json 检测逻辑，避免错误覆盖插件配置
- 修正插件注册表中的路径映射
- 改进 .claude 目录检测和复制的错误处理

## [2.0.4-dev] - Previous Release

Initial pre-release version with Claude Code CLI support.
