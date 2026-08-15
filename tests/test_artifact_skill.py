"""Stage 3 (3e, A-ART03-1): the built-in Artifact Skill carries the required
semantic constraints and is staged into the container bundle."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "container" / "_bundle" / "skills" / "artifact" / "SKILL.md"


class ArtifactSkillTests(unittest.TestCase):
    def test_skill_exists_in_container_bundle(self):
        self.assertTrue(SKILL.is_file(), f"Artifact Skill missing: {SKILL}")

    def test_skill_defines_classification_semantics(self):
        text = SKILL.read_text(encoding="utf-8")
        for kind in ("deliverable", "source_change", "generated_output"):
            self.assertIn(kind, text, f"missing kind {kind}")

    def test_skill_requires_relative_paths_only(self):
        text = SKILL.read_text(encoding="utf-8").lower()
        self.assertIn("relative", text)
        self.assertIn("never absolute", text)

    def test_skill_instructs_aisc_artifact_record(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("aisc artifact record", text)

    def test_skill_is_not_a_fact_database(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("not", text.lower())
        # The skill must point at the CLI as the authoritative fact, never
        # claim to BE the registry.
        self.assertIn("authoritative fact", text)

    def test_skill_is_checksummed_in_vendor(self):
        import hashlib

        checksums = REPO_ROOT / "vendor" / "checksums.txt"
        entry = [l for l in checksums.read_text(encoding="utf-8").splitlines()
                 if "container/_bundle/skills/artifact/SKILL.md" in l]
        self.assertEqual(len(entry), 1, "Skill must be in vendor/checksums.txt")
        recorded = entry[0].split()[0]
        actual = hashlib.sha256(SKILL.read_bytes()).hexdigest()
        self.assertEqual(recorded, actual)


if __name__ == "__main__":
    unittest.main()
