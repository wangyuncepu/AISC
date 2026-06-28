# 20260625

1. [X] 仅保留docker_version使用即可

* [X] 没有挂VPN的时候node:20-slim无法安装
* [X] 挂VPN之后可以安装，配置提示`.claude/`缺少报错，不再继续进行

2. [ ] ssh配置，需要windows开放端口直接外网访问，Termius配置文档+setup-ssh-portproxy.ps1（转发ssh端口，作为参考）

* [X] skill增加一个[github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md)（尽可能模拟/使用**Claude Code Plugin**安装）
* [X] 全局配置claude-switch命令，用来切换模型配置

# 20260625

* [x] karpathy-skills安装后并没有被claude调用，需要主要启用；全局CLAUDE.md使用这个技能的CLAUDE.md文件（不是项目文件夹那个）
* [x] README.md使用引导统一，分为Windows，Linux，MacOS使用，各自有一键运行脚本
* [x] EADME.md中 直接运行super-claude:v1.1.2h 空白 和 bash的区别，两者使用上似乎没有区别，前者配置好之后再次登录不会调用claude
* [X] Windows一键运行脚本.bat，没有版本更新更改名称，改为“docker run -it --rm -v "%cd%:/app" super-claude:v1.1.2”
* [x] 保留之前的单次运行的使用方法，交互式+运行单个命令
* [ ] 产生的Container如果用户直接关闭Terminal，不会关闭Container，需要docker手动删除???
* [ ] gstack没有成功安装??
* [x] Caveman安装了，但是需要默认激活（默认是不激活的）
* [x] CMD运行有中文乱码问题，跨平台使用的终端方案（目前我用的是Wrap和Termius）
