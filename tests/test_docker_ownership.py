"""docker-ownership-foundation A0: the frozen ownership-label contract.

src/aisc/domain/docker_ownership.py is authoritative; the Rust mirror
(workbench/src-tauri/src/docker_ownership.rs) and this file both decode
tests/fixtures/docker-ownership/labels.json — the three-language gate
(same pattern as tests/fixtures/data-root/hash-vectors.json).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from aisc.domain import docker_ownership as own

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "docker-ownership" / "labels.json"

RID = "11111111-1111-4111-8111-111111111111"
WSKEY = "abcd1234"


class DockerOwnershipConstantTests(unittest.TestCase):
    def test_fixture_constants_match_module(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            data["container_labels"],
            {
                "managed": own.LABEL_MANAGED,
                "kind": own.LABEL_KIND,
                "owner": own.LABEL_OWNER,
                "schema_version": own.LABEL_SCHEMA_VERSION,
                "workspace_key": own.LABEL_WORKSPACE_KEY,
                "runtime_id": own.LABEL_RUNTIME_ID,
            },
        )
        self.assertEqual(
            data["image_labels"],
            {
                "managed": own.IMAGE_LABEL_MANAGED,
                "kind": own.IMAGE_LABEL_KIND,
                "schema_version": own.IMAGE_LABEL_SCHEMA_VERSION,
                "source_version": own.IMAGE_LABEL_SOURCE_VERSION,
            },
        )
        self.assertEqual(
            data["kind_values"],
            {"runtime": own.KIND_RUNTIME, "one_shot": own.KIND_ONE_SHOT, "toolchain": own.KIND_TOOLCHAIN},
        )
        self.assertEqual(
            data["owner_values"],
            {"workbench": own.OWNER_WORKBENCH, "cli": own.OWNER_CLI},
        )
        self.assertEqual(data["image_kind_workstation"], own.IMAGE_KIND_WORKSTATION)
        self.assertEqual(data["label_schema_v1"], own.OWNERSHIP_LABEL_SCHEMA_V1)
        self.assertEqual(data["envelope_schema_v1"], own.OWNERSHIP_SCHEMA_V1)


class DockerOwnershipBuilderTests(unittest.TestCase):
    def test_example_label_sets_match_fixture(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(own.runtime_labels(RID, own.OWNER_WORKBENCH, WSKEY), data["example_runtime_labels"])
        self.assertEqual(own.one_shot_labels(), data["example_one_shot_labels"])
        self.assertEqual(own.toolchain_volume_labels(WSKEY), data["example_toolchain_volume_labels"])
        self.assertEqual(own.image_labels("2.1.6"), data["example_image_labels"])

    def test_every_built_set_carries_managed_and_schema_version(self):
        for labels in (
            own.runtime_labels(RID, own.OWNER_WORKBENCH, WSKEY),
            own.one_shot_labels(),
            own.toolchain_volume_labels(WSKEY),
            own.image_labels("2.1.6"),
        ):
            self.assertEqual(labels[own.LABEL_MANAGED if own.LABEL_MANAGED in labels else own.IMAGE_LABEL_MANAGED], "true")
        for labels in (
            own.runtime_labels(RID, own.OWNER_WORKBENCH, WSKEY),
            own.one_shot_labels(),
            own.toolchain_volume_labels(WSKEY),
        ):
            self.assertEqual(labels[own.LABEL_SCHEMA_VERSION], own.OWNERSHIP_LABEL_SCHEMA_V1)
        self.assertEqual(own.image_labels("0")[own.IMAGE_LABEL_SCHEMA_VERSION], own.OWNERSHIP_LABEL_SCHEMA_V1)

    def test_label_args_sorted_and_matches_fixture(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(own.label_args(own.one_shot_labels()), data["example_label_args"])
        # Deterministic regardless of input dict order.
        shuffled = dict(reversed(list(own.one_shot_labels().items())))
        self.assertEqual(own.label_args(shuffled), own.label_args(own.one_shot_labels()))

    def test_filters_match_fixture(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(own.managed_filter(), data["example_managed_filter"])
        self.assertEqual(own.managed_filter(own.KIND_TOOLCHAIN), data["example_kind_filter"])

    def test_runtime_labels_keep_legacy_keys(self):
        # The pre-A0 runtime container already carried runtime-id/owner/
        # workspace-key/managed/kind; A0 only adds schema-version. Existing
        # label-based queries must keep matching.
        labels = own.runtime_labels(RID, own.OWNER_WORKBENCH, WSKEY)
        self.assertEqual(labels["io.aisc.runtime-id"], RID)
        self.assertEqual(labels["io.aisc.owner"], own.OWNER_WORKBENCH)
        self.assertEqual(labels["io.aisc.workspace-key"], WSKEY)
        self.assertEqual(labels["io.aisc.kind"], own.KIND_RUNTIME)


if __name__ == "__main__":
    unittest.main()
