"""Docker maintenance lock (A0 / docker-ownership-foundation).

Cross-process lock serializing host-level Docker resource mutations:
installer scan/cleanup/rebuild, ``aisc build`` writes to the default
workstation tag, runtime create/start resolving the default tag to an
image ID, and reconcile's removal critical sections
(docker-resource-lifecycle 02-domain-contract.md §4.1,
05-cross-plan-coordination.md §4).

FROZEN LOCK ORDER (violating it deadlocks — enforced by convention and
reviewed in tests/docs, not by the runtime):

    docker-maintenance.lock  ->  workspace lock  ->  registry transaction

The lock file lives at ``<data-root>/state/locks/docker-maintenance.lock``
via the frozen DataRootStore layout (domain/data_root.py LOCKS_SUBDIR —
the plans' ``<data-root>/locks/`` notation resolves to this contract
path; consumers never concatenate paths themselves).

The acquisition timeout must outlast the longest legitimate holder (a
no-cache workstation rebuild takes minutes); callers may lower it when
they know the contention window is short.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from aisc.adapters.data_root_store import SCOPE_SHARED, DataRootStore
from aisc.domain.data_root import ERR_LOCK_TIMEOUT

#: Lock name; ``DataRootStore.lock_path_for`` turns this into
#: ``state/locks/docker-maintenance.lock`` under the shared scope.
MAINTENANCE_LOCK_NAME = "docker-maintenance"

#: Stable error code surfaced when acquisition times out.
ERR_MAINTENANCE_LOCK_TIMEOUT = "AISC_ERR_MAINTENANCE_LOCK_TIMEOUT"

#: Default acquisition timeout (seconds) — sized to survive a no-cache
#: rebuild holding the lock, not just metadata mutations.
MAINTENANCE_LOCK_TIMEOUT = 300.0


@contextmanager
def docker_maintenance_lock(
    store: DataRootStore,
    timeout: float = MAINTENANCE_LOCK_TIMEOUT,
) -> Iterator[None]:
    """Hold the Docker maintenance lock.

    Raises ``CliError(ERR_MAINTENANCE_LOCK_TIMEOUT)`` on timeout — the
    caller must NOT proceed to mutate Docker resources without the lock
    (fail-closed). Acquire this BEFORE any workspace/registry lock.
    """
    with store.lock(
        MAINTENANCE_LOCK_NAME,
        timeout,
        scope=SCOPE_SHARED,
        error_code=ERR_MAINTENANCE_LOCK_TIMEOUT,
    ):
        yield


def maintenance_lock_path(store: DataRootStore):
    """Canonical lock file path (contract: ``state/locks/<name>.lock``)."""
    return store.lock_path_for(MAINTENANCE_LOCK_NAME, scope=SCOPE_SHARED)


@contextmanager
def docker_maintenance_lock_at_root(
    data_root,
    timeout: float = MAINTENANCE_LOCK_TIMEOUT,
) -> Iterator[None]:
    """Same lock, addressed by the data ROOT directly (installer-side
    callers have no workspace to resolve a store with). Identical file —
    both entries serialize against each other."""
    from aisc.adapters.data_root_store import file_lock
    from aisc.domain.data_root import LOCKS_SUBDIR

    lock_path = Path(str(data_root)).joinpath(*LOCKS_SUBDIR.split("/")) / (
        MAINTENANCE_LOCK_NAME + ".lock"
    )
    with file_lock(lock_path, timeout, error_code=ERR_MAINTENANCE_LOCK_TIMEOUT):
        yield


# Re-exported for callers that construct their own timeout errors.
__all__ = [
    "MAINTENANCE_LOCK_NAME",
    "MAINTENANCE_LOCK_TIMEOUT",
    "ERR_MAINTENANCE_LOCK_TIMEOUT",
    "ERR_LOCK_TIMEOUT",
    "docker_maintenance_lock",
    "maintenance_lock_path",
]
