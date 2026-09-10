"""Tests for immutable container image reference enforcement."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.check_container_image_pins import mutable_container_image_references


class ContainerImagePinTests(unittest.TestCase):
    """Validate mutable, digest-pinned, and runtime-supplied images."""

    def test_rejects_mutable_dockerfile_and_compose_images(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            backend = repository_root / "backend"
            backend.mkdir()
            (backend / "Dockerfile").write_text(
                "FROM python:3.12-slim AS runtime\n", encoding="utf-8"
            )
            (repository_root / "compose.yaml").write_text(
                "services:\n  database:\n    image: postgres:17-alpine\n",
                encoding="utf-8",
            )

            self.assertEqual(
                mutable_container_image_references(repository_root),
                [
                    f"{Path('backend') / 'Dockerfile'}:1: python:3.12-slim",
                    "compose.yaml:3: postgres:17-alpine",
                ],
            )

    def test_accepts_digest_pins_stages_scratch_and_runtime_variables(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            frontend = repository_root / "frontend"
            frontend.mkdir()
            digest = "a" * 64
            (frontend / "Dockerfile").write_text(
                f"FROM node:24-alpine@sha256:{digest} AS build\n"
                "FROM build AS packaged\n"
                "FROM scratch\n",
                encoding="utf-8",
            )
            (repository_root / "compose.production.yaml").write_text(
                'services:\n  api:\n    image: "${HEALTHSCOPE_API_IMAGE:?required}"\n',
                encoding="utf-8",
            )

            self.assertEqual(mutable_container_image_references(repository_root), [])


if __name__ == "__main__":
    unittest.main()
