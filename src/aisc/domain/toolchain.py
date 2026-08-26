"""Persistent project toolchain contract (runtime-lifecycle-ux 02 §8).

Scope-derived policy (D-RUNTIME-09):
- scope=project    -> dependency_policy=persistent_toolchain
                     -> a host-side toolchain dir mounts at
                        ``/opt/aisc/toolchain`` (host_bind backend — the
                        2026-08-26 Windows spike passed the frozen decision
                        gate, see spike-toolchain-windows.md);
- scope=temporary  -> dependency_policy=ephemeral_toolchain
                     -> no mount; the entrypoint creates the same layout at
                        ``/tmp/aisc-toolchain`` (container-only).

Both modes inject identical user-level package-manager paths so commands
behave the same regardless of scope:
- npm:   ``NPM_CONFIG_PREFIX=<tc>/npm-global``  (``npm i -g`` persists)
- pip:   ``PYTHONUSERBASE=<tc>/python``         (``--user`` installs persist;
         PIP_USER is deliberately NOT forced — it breaks venv installs, and
         the plan's §7.2 already scopes system pip to container-only)
- cargo: ``CARGO_HOME=<tc>/cargo``              (``cargo install`` persists)

v1 carries a lightweight ``environment.json`` baseline marker (OS/arch/
glibc/Node/Python/image id) — NOT an install manifest; a mismatch is a
warning, never a block or auto-delete (02 §8.3, D-RUNTIME-11).

Pure constants/helpers only; filesystem work lives in
application/toolchain.py.
"""

from __future__ import annotations

from typing import List

#: In-container mount target for the persistent toolchain (both backends).
TOOLCHAIN_MOUNT_TARGET = "/opt/aisc/toolchain"

#: Temporary-mode equivalent layout (container-only, dies with the runtime).
TOOLCHAIN_TMP_ROOT = "/tmp/aisc-toolchain"

#: Subdirs under the toolchain root (contract layout, 02 §8.2).
TOOLCHAIN_SUBDIRS = ("bin", "npm-global", "python", "cargo", "cache")

#: Lightweight environment baseline marker (never an install manifest).
ENVIRONMENT_MARKER = "environment.json"
ENVIRONMENT_MARKER_SCHEMA = "aisc.toolchain-environment/v1"
ENVIRONMENT_MARKER_VERSION = 1

#: Mismatch warning file (entrypoint writes when the baseline differs from
#: the running container; host-side inspect surfaces it as a warning).
TOOLCHAIN_WARNING_FILE = "toolchain-incompatible.txt"

#: Registry metadata: which storage backend this runtime's toolchain uses.
TOOLCHAIN_STORAGE_HOST_BIND = "host_bind"
TOOLCHAIN_STORAGE_DOCKER_VOLUME = "docker_volume"  # parameterized, not default


def toolchain_bind_argv(host_dir: str) -> List[str]:
    """docker -v argv mounting a host toolchain dir at the contract target."""
    return ["-v", f"{host_dir}:{TOOLCHAIN_MOUNT_TARGET}"]


def base_environment_marker(
    *, source_version: str, image_id: str, written_at: str
) -> dict:
    """Host-side marker seed (container facts merge in from the entrypoint)."""
    return {
        "schema": ENVIRONMENT_MARKER_SCHEMA,
        "schema_version": ENVIRONMENT_MARKER_VERSION,
        "os": "linux",
        "source_version": source_version,
        "image_id": image_id,
        "written_at": written_at,
    }
