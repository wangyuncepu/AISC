"""Runtime management utilities.

Functions for runtime ID generation, config fingerprinting, and runtime operations.
"""

import hashlib
import os
import secrets
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


def generate_runtime_id() -> str:
    """Generate a unique runtime ID.

    Format: rt_<16-char-hex>
    Example: rt_a3f9c8e1d4b2f5a7
    """
    random_hex = secrets.token_hex(8)
    return f"rt_{random_hex}"


def compute_config_fingerprint(
    image: str,
    network: str,
    scope: str,
    workspace: str,
) -> str:
    """Compute deterministic fingerprint of runtime configuration.

    Used for detecting config drift and idempotent retry.

    Args:
        image: Docker image name (e.g., "super-claude:latest")
        network: Network mode ("direct" or "proxy")
        scope: Scope mode ("project" or "temporary")
        workspace: Canonical absolute workspace path

    Returns:
        SHA256 hex digest (first 16 chars)
    """
    # Normalize workspace to canonical path
    canonical_workspace = str(Path(workspace).resolve())

    # Create stable string representation
    config_str = f"{image}|{network}|{scope}|{canonical_workspace}"

    # Hash and truncate
    digest = hashlib.sha256(config_str.encode("utf-8")).hexdigest()
    return digest[:16]


def validate_runtime_id(runtime_id: str) -> bool:
    """Validate runtime ID format.

    Args:
        runtime_id: ID to validate

    Returns:
        True if valid, False otherwise
    """
    if not runtime_id.startswith("rt_"):
        return False

    hex_part = runtime_id[3:]
    if len(hex_part) != 16:
        return False

    try:
        int(hex_part, 16)
        return True
    except ValueError:
        return False


@contextmanager
def workspace_lock(workspace: Path, timeout: float = 10.0) -> Iterator[None]:
    """Acquire exclusive lock on workspace for runtime operations.

    Uses fcntl.flock (Linux/macOS) or msvcrt.locking (Windows).
    Fail-closed: raises on lock acquisition failure.

    Args:
        workspace: Canonical workspace path
        timeout: Lock timeout in seconds

    Raises:
        TimeoutError: If lock cannot be acquired within timeout
        OSError: On other lock-related errors

    Yields:
        None while lock is held
    """
    workspace = workspace.resolve()
    aisc_dir = workspace / ".aisc"
    aisc_dir.mkdir(parents=True, exist_ok=True)
    lock_path = aisc_dir / ".workspace.lock"

    lock_fd = None
    locked = False

    try:
        # Open lock file
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)

        # Platform-specific locking
        if sys.platform == "win32":
            # Windows: msvcrt.locking with blocking
            import msvcrt
            import time

            start_time = time.time()
            while True:
                try:
                    msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    if time.time() - start_time > timeout:
                        raise TimeoutError(
                            f"Failed to acquire workspace lock within {timeout}s"
                        )
                    time.sleep(0.1)
        else:
            # Linux/macOS: fcntl.flock with timeout
            import fcntl
            import signal

            def timeout_handler(signum, frame):
                raise TimeoutError(
                    f"Failed to acquire workspace lock within {timeout}s"
                )

            # Set alarm for timeout
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(timeout))

            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                locked = True
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

        yield

    finally:
        # Release lock
        if locked and lock_fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass

        # Close file descriptor
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
