"""O6 (opt-batch, D-11): the WSL2 memory guidance doctor check."""
from pathlib import Path

from aisc.application.doctor import _check_wsl_memory
from aisc.domain.models import CheckStatus


def _run(tmp_path: Path, ram: float, wslconfig: str | None, platform="win32"):
    if wslconfig is not None:
        (tmp_path / ".wslconfig").write_text(wslconfig, encoding="utf-8")
    return _check_wsl_memory(
        home=tmp_path, total_ram_gb=lambda: ram, platform=platform
    )


def test_low_ram_without_cap_warns_with_snippet(tmp_path):
    r = _run(tmp_path, ram=8.0, wslconfig=None)
    assert r.status == CheckStatus.WARN
    assert "[wsl2]" in (r.hint or "")
    assert "memory=5GB" in (r.hint or "")
    assert "wsl --shutdown" in (r.hint or "")


def test_low_ram_with_cap_passes(tmp_path):
    r = _run(tmp_path, ram=8.0, wslconfig="[wsl2]\nmemory=5GB\nswap=2GB\n")
    assert r.status == CheckStatus.PASS


def test_cap_recognized_case_insensitive_and_offset(tmp_path):
    # The memory= line may carry leading whitespace; the section name any case.
    r = _run(tmp_path, ram=6.0, wslconfig="[WSL2]\n  memory = 4GB\n")
    assert r.status == CheckStatus.PASS


def test_memory_line_outside_wsl2_section_does_not_count(tmp_path):
    r = _run(tmp_path, ram=6.0, wslconfig="[user]\nmemory=irrelevant\n")
    assert r.status == CheckStatus.WARN


def test_plenty_of_ram_passes_without_cap(tmp_path):
    r = _run(tmp_path, ram=32.0, wslconfig=None)
    assert r.status == CheckStatus.PASS


def test_4gb_machine_gets_4gb_recommendation(tmp_path):
    r = _run(tmp_path, ram=4.0, wslconfig=None)
    assert "memory=4GB" in (r.hint or "")


def test_non_windows_skips(tmp_path):
    r = _run(tmp_path, ram=8.0, wslconfig=None, platform="linux")
    assert r.status == CheckStatus.SKIP


def test_unreadable_ram_skips(tmp_path):
    r = _check_wsl_memory(
        home=tmp_path, total_ram_gb=lambda: None, platform="win32"
    )
    assert r.status == CheckStatus.SKIP
