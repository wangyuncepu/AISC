"""Docker resource ownership contract (A0 / docker-ownership-foundation).

Single source of truth for the ownership labels shared by the
docker-resource-lifecycle and runtime-lifecycle-ux plans:

- docs/plans/docker-resource-lifecycle/02-domain-contract.md §1
- docs/plans/docker-resource-lifecycle/05-cross-plan-coordination.md §1

Containers and volumes carry ``io.aisc.*`` labels; workstation images carry
``org.aisc.*`` provenance labels (alongside the existing
``org.aisc.cc-switch.*`` build labels). Labels are the primary ownership
proof — name prefixes are legacy-compatibility evidence only and never the
sole mechanism for new resources.

Mirrored in Rust ``workbench/src-tauri/src/docker_ownership.rs`` and frozen
in ``tests/fixtures/docker-ownership/labels.json`` (the three-language
consistency gate for this stage; see the hash-vectors precedent in
``tests/fixtures/data-root/``).

Nothing here performs I/O and nothing here is secret-bearing: label keys,
kind/owner values and schema versions only. Docker argv assembly for
container/volume creation and the three-tier classification service
(owned / legacy_owned / unverified) live in application/adapters layers
(docker-resource-lifecycle stages A1-A2).
"""

from __future__ import annotations

from typing import Dict, List, Mapping

# ---------------------------------------------------------------------------
# Frozen constants (mirrored in Rust docker_ownership.rs / the labels fixture)
# ---------------------------------------------------------------------------

#: Marker label proving AISC ownership. Value is always ``true``.
LABEL_MANAGED = "io.aisc.managed"

#: Resource kind. One of :data:`KIND_*`.
LABEL_KIND = "io.aisc.kind"

#: Creating component. One of :data:`OWNER_*`.
LABEL_OWNER = "io.aisc.owner"

#: Ownership label schema version (label value; Docker labels are strings).
LABEL_SCHEMA_VERSION = "io.aisc.schema-version"

#: Workspace hash scoping a resource to one workspace (containers, volumes).
LABEL_WORKSPACE_KEY = "io.aisc.workspace-key"

#: Runtime UUID — runtime containers only.
LABEL_RUNTIME_ID = "io.aisc.runtime-id"

#: Image provenance labels (``org.aisc.*`` namespace).
IMAGE_LABEL_MANAGED = "org.aisc.managed"
IMAGE_LABEL_KIND = "org.aisc.kind"
IMAGE_LABEL_SCHEMA_VERSION = "org.aisc.schema-version"
IMAGE_LABEL_SOURCE_VERSION = "org.aisc.source-version"

# --- label values -----------------------------------------------------------

KIND_RUNTIME = "runtime"
KIND_ONE_SHOT = "one-shot"
KIND_TOOLCHAIN = "toolchain"

OWNER_WORKBENCH = "workbench"
OWNER_CLI = "cli"

#: The only image kind v1 defines (workstation images from ``aisc build``).
IMAGE_KIND_WORKSTATION = "workstation-image"

#: Value of ``io.aisc.schema-version`` / ``org.aisc.schema-version``.
OWNERSHIP_LABEL_SCHEMA_V1 = "1"

#: ``schema_version`` integer for the maintenance scan/cleanup JSON
#: envelopes (docker-resource-lifecycle stage B consumes this).
OWNERSHIP_SCHEMA_V1 = 1


# ---------------------------------------------------------------------------
# Pure label-set builders (consumed by the creation entry points, stage A2)
# ---------------------------------------------------------------------------

def base_labels(kind: str, owner: str) -> Dict[str, str]:
    """Managed + kind + owner + schema-version — the minimum ownership set."""
    return {
        LABEL_MANAGED: "true",
        LABEL_KIND: kind,
        LABEL_OWNER: owner,
        LABEL_SCHEMA_VERSION: OWNERSHIP_LABEL_SCHEMA_V1,
    }


def runtime_labels(runtime_id: str, owner: str, workspace_key: str) -> Dict[str, str]:
    """Label set for a Workbench runtime container (``kind=runtime``)."""
    labels = base_labels(KIND_RUNTIME, owner)
    labels[LABEL_RUNTIME_ID] = runtime_id
    labels[LABEL_WORKSPACE_KEY] = workspace_key
    return labels


def one_shot_labels(owner: str = OWNER_CLI) -> Dict[str, str]:
    """Label set for a CLI one-shot container (``aisc run``)."""
    return base_labels(KIND_ONE_SHOT, owner)


def toolchain_volume_labels(workspace_key: str) -> Dict[str, str]:
    """Label set for a persistent project toolchain volume.

    ``kind=toolchain`` volumes are deleted only by the explicit workspace
    runtime-data cleanup — never by generic Docker cleanup
    (02-domain-contract.md §3.1).
    """
    labels = base_labels(KIND_TOOLCHAIN, OWNER_WORKBENCH)
    labels[LABEL_WORKSPACE_KEY] = workspace_key
    return labels


def image_labels(source_version: str) -> Dict[str, str]:
    """Provenance label set for workstation images built by ``aisc build``."""
    return {
        IMAGE_LABEL_MANAGED: "true",
        IMAGE_LABEL_KIND: IMAGE_KIND_WORKSTATION,
        IMAGE_LABEL_SCHEMA_VERSION: OWNERSHIP_LABEL_SCHEMA_V1,
        IMAGE_LABEL_SOURCE_VERSION: source_version,
    }


def label_args(labels: Mapping[str, str]) -> List[str]:
    """Flatten a label mapping to deterministic ``--label k=v`` argv tokens.

    Sorted by key so generated argv (and its test snapshots) are stable
    regardless of dict construction order.
    """
    args: List[str] = []
    for key in sorted(labels):
        args.extend(("--label", f"{key}={labels[key]}"))
    return args


def managed_filter(kind: str = None) -> str:
    """``docker --filter`` value selecting AISC-managed resources.

    Optionally narrowed to one kind — e.g. ``label=io.aisc.managed=true``
    or ``label=io.aisc.kind=toolchain``.
    """
    if kind is not None:
        return f"label={LABEL_KIND}={kind}"
    return f"label={LABEL_MANAGED}=true"
