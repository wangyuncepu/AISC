"""LiteLLM proxy 本地启动包装器。

为何需要包装：
- venv 位于 /mnt/windows（WSL DrvFs），bin/litellm 脚本无 exec 位，不能直接执行，
  故改用 python 调 console_script 入口 litellm=litellm:run_server。
- 当前系统 Python 为 3.14，uvloop 0.21.x 运行时不兼容
  （asyncio.events.BaseDefaultEventLoopPolicy 在 3.14 已移除），
  而 litellm 在 linux 上硬编码 loop=uvloop（见 proxy_cli.py:_get_loop_type）。
  这里 monkeypatch 该方法返回 None，让 uvicorn 回退默认 asyncio 循环。
"""
import sys

import litellm.proxy.proxy_cli as _pc

_pc.ProxyInitializationHelpers._get_loop_type = staticmethod(lambda: None)

from litellm import run_server

sys.exit(run_server())
