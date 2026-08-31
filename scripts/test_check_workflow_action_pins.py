"""Tests for immutable GitHub Actions reference enforcement."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.check_workflow_action_pins import mutable_action_references


class WorkflowActionPinTests(unittest.TestCase):
    """Validate mutable and immutable workflow reference detection."""

    def test_rejects_mutable_external_action_reference(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            workflows = Path(temporary_directory) / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "ci.yml").write_text(
                "steps:\n  - uses: actions/checkout@v7\n", encoding="utf-8"
            )

            self.assertEqual(
                mutable_action_references(workflows),
                [f"{Path('.github') / 'workflows' / 'ci.yml'}:2: actions/checkout@v7"],
            )

    def test_accepts_sha_pinned_local_and_container_actions(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            workflows = Path(temporary_directory) / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "ci.yaml").write_text(
                "steps:\n"
                "  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
                "  - uses: ./local-action\n"
                "  - uses: docker://alpine:3.23\n",
                encoding="utf-8",
            )

            self.assertEqual(mutable_action_references(workflows), [])


if __name__ == "__main__":
    unittest.main()
