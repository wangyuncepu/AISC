# -*- coding: utf-8 -*-
"""2.1.9: the interactive shell is zsh (2.1.8 T2/D-4), which has NO env-var
function import — the bash path's BASH_FUNC_help%% injection stopped
working and ``help`` went missing in zsh. The managed container/aisc-zshrc
now defines it; these tests pin that contract:

- the zshrc defines a help() function;
- its heredoc tutorial text matches tutorial.py's _TUTORIAL BYTE-FOR-BYTE
  (the zshrc is the image-side copy; tutorial.py stays the SSOT — this is
  the drift guard so the two can never silently diverge);
- the bash env fallback still exports the same SSOT text.
"""

import re
from pathlib import Path

from aisc.cli.tutorial import _TUTORIAL, help_function_env

REPO_ROOT = Path(__file__).resolve().parents[1]
ZSHRC = REPO_ROOT / "container" / "aisc-zshrc"

_HEREDOC_RE = re.compile(
    r"<<'__AISC_TUTORIAL_EOF__'\n(.*?)\n__AISC_TUTORIAL_EOF__", re.DOTALL
)


def _zshrc_text() -> str:
    return ZSHRC.read_text(encoding="utf-8")


def test_zshrc_defines_help_function():
    text = _zshrc_text()
    assert re.search(r"^help\(\)\s*\{", text, re.MULTILINE), (
        "managed zshrc must define help() — zsh cannot import BASH_FUNC_* env"
    )


def test_zshrc_tutorial_text_matches_ssot_byte_for_byte():
    """The heredoc inside the zshrc must equal tutorial._TUTORIAL exactly —
    edit BOTH files together or neither."""
    match = _HEREDOC_RE.search(_zshrc_text())
    assert match, "zshrc help() must embed the tutorial via the EOF heredoc"
    assert match.group(1) == _TUTORIAL.rstrip("\n"), (
        "zshrc tutorial text drifted from src/aisc/cli/tutorial.py::_TUTORIAL"
    )


def test_bash_env_fallback_still_carries_ssot_text():
    """Older images fall back to bash; the session env function must keep
    delivering the same SSOT text (A-21765/A-21766 contract unchanged)."""
    env = help_function_env()
    assert "BASH_FUNC_help%%" in env
    assert _TUTORIAL.rstrip("\n") in env["BASH_FUNC_help%%"]
