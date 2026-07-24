import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ReleaseNotesContractTests(unittest.TestCase):
    def test_release_workflow_reads_tag_scoped_markdown(self) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "artifact.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("- uses: actions/checkout@v4", workflow)
        self.assertIn(
            "body_path: docs/releases/${{ github.ref_name }}.md",
            workflow,
        )

    def test_current_version_has_release_notes(self) -> None:
        version = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        release_notes = PROJECT_ROOT / "docs" / "releases" / f"v{version}.md"

        self.assertTrue(
            release_notes.is_file(),
            f"missing GitHub Release Notes: {release_notes.relative_to(PROJECT_ROOT)}",
        )
        self.assertIn(
            f"# AISC v{version}",
            release_notes.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
