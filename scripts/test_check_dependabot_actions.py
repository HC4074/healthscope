"""Tests for the reviewed Dependabot GitHub Actions policy."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.check_dependabot_actions import (
    EXPECTED_CONFIGURATION,
    dependabot_configuration_failures,
)


class DependabotActionsPolicyTests(unittest.TestCase):
    """Validate accepted, missing, and broadened updater configurations."""

    def test_accepts_reviewed_github_actions_configuration(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "dependabot.yml"
            config_path.write_text(EXPECTED_CONFIGURATION, encoding="utf-8")

            self.assertEqual(dependabot_configuration_failures(config_path), [])

    def test_rejects_missing_configuration(self) -> None:
        config_path = Path("missing-dependabot.yml")

        self.assertEqual(
            dependabot_configuration_failures(config_path),
            [f"Dependabot configuration is missing: {config_path}"],
        )

    def test_rejects_broadened_package_ecosystems(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "dependabot.yml"
            config_path.write_text(
                EXPECTED_CONFIGURATION
                + '\n  - package-ecosystem: "pip"\n'
                + '    directory: "/backend"\n'
                + "    schedule:\n"
                + '      interval: "weekly"\n',
                encoding="utf-8",
            )

            self.assertEqual(
                dependabot_configuration_failures(config_path),
                [
                    "Dependabot must update only GitHub Actions from the repository root "
                    "on the reviewed weekly schedule."
                ],
            )


if __name__ == "__main__":
    unittest.main()
