"""Reject mutable literal container images in build and Compose definitions."""

import re
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FROM_PATTERN = re.compile(
    r"^\s*FROM\s+(?:--platform=\S+\s+)?(?P<image>\S+)", re.IGNORECASE
)
STAGE_PATTERN = re.compile(r"\s+AS\s+(?P<stage>\S+)\s*$", re.IGNORECASE)
COMPOSE_IMAGE_PATTERN = re.compile(r"^\s*image:\s*(?P<image>.+?)\s*$")
DIGEST_PIN_PATTERN = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
IGNORED_DIRECTORIES = {".git", ".venv", "dist", "node_modules"}


def _repository_files(repository_root: Path) -> list[Path]:
    dockerfiles = [
        path
        for path in repository_root.rglob("Dockerfile*")
        if not IGNORED_DIRECTORIES.intersection(path.relative_to(repository_root).parts)
    ]
    compose_files = list(repository_root.glob("compose*.yml"))
    compose_files.extend(repository_root.glob("compose*.yaml"))
    return sorted({*dockerfiles, *compose_files})


def mutable_container_image_references(
    repository_root: Path = REPOSITORY_ROOT,
) -> list[str]:
    """Return locations whose literal external image is not digest-pinned."""

    failures: list[str] = []
    for definition in _repository_files(repository_root):
        stage_names: set[str] = set()
        for line_number, line in enumerate(
            definition.read_text(encoding="utf-8").splitlines(), 1
        ):
            reference: str | None = None
            from_match = FROM_PATTERN.match(line)
            if from_match is not None:
                reference = from_match.group("image")
                if reference == "scratch" or reference in stage_names:
                    reference = None
                stage_match = STAGE_PATTERN.search(line)
                if stage_match is not None:
                    stage_names.add(stage_match.group("stage"))
            else:
                image_match = COMPOSE_IMAGE_PATTERN.match(line)
                if image_match is not None:
                    reference = (
                        image_match.group("image").split(" #", 1)[0].strip(" '\"")
                    )
                    if reference.startswith("${"):
                        reference = None

            if (
                reference is not None
                and DIGEST_PIN_PATTERN.fullmatch(reference) is None
            ):
                relative_path = definition.relative_to(repository_root)
                failures.append(f"{relative_path}:{line_number}: {reference}")
    return failures


def main() -> int:
    """Report mutable container references and return a CI-friendly status."""

    failures = mutable_container_image_references()
    if not failures:
        print("All literal container image references are pinned to SHA-256 digests.")
        return 0

    print("Mutable literal container image references found:", file=sys.stderr)
    for failure in failures:
        print(f"- {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
