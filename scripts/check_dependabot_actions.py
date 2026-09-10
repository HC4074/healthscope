"""Enforce the reviewed Dependabot policy for Actions and container bases."""

import sys
from pathlib import Path

DEPENDABOT_CONFIG = Path(__file__).resolve().parents[1] / ".github" / "dependabot.yml"
EXPECTED_CONFIGURATION = """version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "09:00"
      timezone: "America/New_York"
    open-pull-requests-limit: 5
    commit-message:
      prefix: "ci(deps)"
  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "09:00"
      timezone: "America/New_York"
    open-pull-requests-limit: 1
    commit-message:
      prefix: "ci(deps)"
  - package-ecosystem: "docker"
    directory: "/backend"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "09:00"
      timezone: "America/New_York"
    open-pull-requests-limit: 1
    commit-message:
      prefix: "ci(deps)"
  - package-ecosystem: "docker"
    directory: "/frontend"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "09:00"
      timezone: "America/New_York"
    open-pull-requests-limit: 2
    commit-message:
      prefix: "ci(deps)"
"""


def dependabot_configuration_failures(
    config_path: Path = DEPENDABOT_CONFIG,
) -> list[str]:
    """Return failures when Actions update automation differs from policy."""

    if not config_path.is_file():
        return [f"Dependabot configuration is missing: {config_path}"]

    if config_path.read_text(encoding="utf-8") != EXPECTED_CONFIGURATION:
        return [
            "Dependabot must update only the approved GitHub Actions and Docker "
            "locations on the reviewed weekly schedule."
        ]
    return []


def main() -> int:
    """Report policy drift and return a CI-friendly status."""

    failures = dependabot_configuration_failures()
    if not failures:
        print(
            "Dependabot is configured for reviewed weekly Actions and Docker updates."
        )
        return 0

    print("Dependabot update policy failures found:", file=sys.stderr)
    for failure in failures:
        print(f"- {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
