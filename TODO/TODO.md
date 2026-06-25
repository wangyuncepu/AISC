# 20260625

1. 仅保留docker_version使用即可
2. dockers_version安装有两个问题
   1. 没有挂VPN的时候node:20-slim无法安装
   2. 挂VPN之后可以安装，配置提示`.claude/`缺少报错，不再继续进行
3. ssh配置，需要windows开放端口直接外网访问，Termius配置文档+setup-ssh-portproxy.ps1（转发ssh端口，作为参考）
4. skill增加一个[github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md)（尽可能模拟/使用**Claude Code Plugin**安装）
5. 全局配置claude-switch命令，用来切换模型配置
