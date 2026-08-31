"""Reject mutable external action references in GitHub Actions workflows."""

import re
import sys
from pathlib import Path

WORKFLOW_DIRECTORY = Path(__file__).resolve().parents[1] / ".github" / "workflows"
USES_PATTERN = re.compile(r"^\s*-\s+uses:\s*([^\s#]+)")
IMMUTABLE_ACTION_PATTERN = re.compile(r"^[^/@\s]+/[^@\s]+@[0-9a-f]{40}$")


def mutable_action_references(
    workflow_directory: Path = WORKFLOW_DIRECTORY,
) -> list[str]:
    """Return workflow locations whose external actions are not SHA-pinned."""

    failures: list[str] = []
    for workflow in sorted(workflow_directory.glob("*.y*ml")):
        for line_number, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = USES_PATTERN.match(line)
            if match is None:
                continue
            reference = match.group(1)
            if reference.startswith(("./", "docker://")):
                continue
            if IMMUTABLE_ACTION_PATTERN.fullmatch(reference) is None:
                failures.append(
                    f"{workflow.relative_to(workflow_directory.parent.parent)}:"
                    f"{line_number}: {reference}"
                )
    return failures


def main() -> int:
    """Report mutable action references and return a CI-friendly status."""

    failures = mutable_action_references()
    if not failures:
        print("All external GitHub Actions references are pinned to full commit SHAs.")
        return 0

    print("Mutable external GitHub Actions references found:", file=sys.stderr)
    for failure in failures:
        print(f"- {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
