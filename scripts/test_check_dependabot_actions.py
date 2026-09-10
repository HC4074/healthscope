"""Tests for the reviewed Dependabot update policy."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.check_dependabot_actions import (
    EXPECTED_CONFIGURATION,
    dependabot_configuration_failures,
)


class DependabotActionsPolicyTests(unittest.TestCase):
    """Validate accepted, missing, and broadened updater configurations."""

    def test_accepts_reviewed_update_configuration(self) -> None:
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

    def test_rejects_unreviewed_package_ecosystems(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "dependabot.yml"
            config_path.write_text(
                EXPECTED_CONFIGURATION
                + '  - package-ecosystem: "pip"\n'
                + '    directory: "/backend"\n'
                + "    schedule:\n"
                + '      interval: "weekly"\n',
                encoding="utf-8",
            )

            self.assertEqual(
                dependabot_configuration_failures(config_path),
                [
                    "Dependabot must update only the approved GitHub Actions and Docker "
                    "locations on the reviewed weekly schedule."
                ],
            )


if __name__ == "__main__":
    unittest.main()
