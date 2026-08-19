"""Build configuration wizard for aisc build command.

Interactive wizard that prompts for:
- Image name/tag
- Proxy configuration
- Build cache options
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Tuple


def _prompt(message: str, default: str = "") -> str:
    """Prompt user for input with optional default."""
    if default:
        prompt_text = f"{message} [{default}]: "
    else:
        prompt_text = f"{message}: "

    try:
        response = input(prompt_text).strip()
        return response if response else default
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)


def _prompt_yes_no(message: str, default: bool = False) -> bool:
    """Prompt user for yes/no confirmation."""
    default_str = "Y/n" if default else "y/N"
    prompt_text = f"{message} [{default_str}]: "

    try:
        response = input(prompt_text).strip().lower()
        if not response:
            return default
        return response in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)


def run_build_wizard(
    default_tag: str = "super-claude:latest",
    aisc_root: Optional[Path] = None,
) -> Tuple[str, bool, bool, Optional[str]]:
    """Run interactive build configuration wizard.

    Args:
        default_tag: Default image tag to suggest
        aisc_root: AISC repository root for proxy config path

    Returns:
        Tuple of (tag, no_cache, pull, proxy_config_path)
        - tag: Docker image tag
        - no_cache: Whether to disable build cache
        - pull: Whether to pull base image
        - proxy_config_path: Path to proxy config file, or None
    """
    print("\n🚀 AISC Build Configuration Wizard")
    print("=" * 50)

    # 1. Image name/tag
    print("\n📦 Docker Image Configuration")
    tag = _prompt("Image tag", default=default_tag)
    if ":" not in tag:
        tag = f"{tag}:latest"

    # 2. Build cache
    print("\n🔧 Build Options")
    no_cache = _prompt_yes_no("Disable Docker build cache?", default=False)
    pull = _prompt_yes_no("Always pull base image?", default=False)

    # 3. Proxy configuration
    print("\n🌐 Proxy Configuration (for container network access)")
    use_proxy = _prompt_yes_no("Configure proxy network?", default=False)

    proxy_config_path: Optional[str] = None
    if use_proxy:
        print("\nProxy configuration options:")
        print("  1) Local file - Enter absolute path to config file")
        print("  2) URL - Enter subscription/config URL")

        mode = _prompt("Select [1/2]", default="2")

        if mode == "1":
            # Local file → store as manually imported subscription content
            path_input = _prompt("Local config file absolute path")
            if path_input and Path(path_input).is_file():
                from aisc.application.network_subscription import (
                    import_subscription_content,
                )
                try:
                    snap = import_subscription_content(Path(path_input).read_bytes())
                    proxy_config_path = snap["config_path"]
                    print(f"✅ Config imported: {snap['config_path']}")
                except Exception as e:  # noqa: BLE001 - wizard stays chatty
                    print(f"❌ Import failed: {e}")
            else:
                print(f"⚠️  File not found: {path_input}, skipping proxy.")
        else:
            # URL download (IDEA-2: data-root subscription store; the clash
            # UA, retries and userinfo capture live in the application layer)
            url = _prompt("Config URL")
            if url:
                from aisc.application.network_subscription import import_subscription
                from aisc.domain.models import CliError

                print("⬇️  Downloading subscription...")
                try:
                    snap = import_subscription(url)
                    proxy_config_path = snap["config_path"]
                    print(f"✅ Subscription imported: {snap['config_path']}")
                    if snap.get("userinfo"):
                        print(f"📊 Usage header captured: {snap['userinfo']}")
                except CliError as e:
                    print(f"❌ Import failed: {e.message}")

    print("\n" + "=" * 50)
    print("Configuration Summary:")
    print(f"  Image tag:    {tag}")
    print(f"  No cache:     {no_cache}")
    print(f"  Pull base:    {pull}")
    print(f"  Proxy config: {proxy_config_path or 'None (direct connection)'}")
    print("=" * 50 + "\n")

    return tag, no_cache, pull, proxy_config_path
