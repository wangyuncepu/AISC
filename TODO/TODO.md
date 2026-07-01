# 20260625

1. [X] 仅保留docker_version使用即可

* [X] 没有挂VPN的时候node:20-slim无法安装
* [X] 挂VPN之后可以安装，配置提示`.claude/`缺少报错，不再继续进行

2. [ ] ssh配置，windows端配置，检查是否打开ssh，如果没打开运行配置脚本

* [X] skill增加一个[github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md)（尽可能模拟/使用**Claude Code Plugin**安装）
* [X] 全局配置claude-switch命令，用来切换模型配置

# 20260627

* [X] karpathy-skills安装后并没有被claude调用，需要主要启用；全局CLAUDE.md使用这个技能的CLAUDE.md文件（不是项目文件夹那个）
* [X] README.md使用引导统一，分为Windows，Linux，MacOS使用，各自有一键运行脚本
* [X] EADME.md中 直接运行super-claude:v1.1.2h 空白 和 bash的区别，两者使用上似乎没有区别，前者配置好之后再次登录不会调用claude
* [X] Windows一键运行脚本.bat，没有版本更新更改名称，改为“docker run -it --rm -v "%cd%:/app" super-claude:v1.1.2”
* [X] 保留之前的单次运行的使用方法，交互式+运行单个命令
* [X] 产生的Container如果用户直接关闭Terminal，不会关闭Container，需要docker手动删除（进入虚拟机之后，exit推出回windows，如果这个时候不输入exit，关闭windows的命令行，docker不关闭）
* [X] gstack没有成功安装: gstack的安装略微不同于其它的（/slash运行模式下没有/gstack./office-hour）
* [X] Caveman安装了，但是需要默认激活（默认是不激活的）
* [X] CMD运行有中文乱码问题，跨平台使用的终端方案（目前我用的是Wrap和Termius）

# 20260701

* [ ] 每日skill/claude学习模块
* [ ] clash翻墙配置（docker内部翻墙）
* [ ] 一键启动脚本规范化配置
* [ ] claude code CLI外配置 cc-switch-cli：[github.com/saladday/cc-switch-cli](https://github.com/saladday/cc-switch-cli) （暂时保留cs-switch）
