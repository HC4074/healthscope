"""Database-backed exclusion for scheduled CMS hospital ingestion."""

from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256

from sqlalchemy import text
from sqlalchemy.engine import Engine


class HospitalIngestionAlreadyRunningError(RuntimeError):
    """Another process already owns the hospital ingestion lock."""


def _hospital_ingestion_lock_key(source_dataset_id: str) -> int:
    """Derive a stable signed PostgreSQL advisory-lock key for one dataset."""

    digest = sha256(f"healthscope:hospital-ingestion:{source_dataset_id}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


@contextmanager
def acquire_hospital_ingestion_lock(
    engine: Engine,
    *,
    source_dataset_id: str,
) -> Iterator[None]:
    """Prevent overlapping PostgreSQL ingestion jobs for one source dataset.

    Production settings already require PostgreSQL. Non-PostgreSQL engines are
    retained only for isolated development and tests, where PostgreSQL advisory
    locks are unavailable.
    """

    if engine.dialect.name != "postgresql":
        yield
        return

    lock_key = _hospital_ingestion_lock_key(source_dataset_id)
    with engine.connect() as connection:
        acquired = connection.scalar(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        if acquired is not True:
            raise HospitalIngestionAlreadyRunningError(
                f"CMS hospital ingestion is already running for dataset {source_dataset_id}"
            )

        try:
            yield
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": lock_key},
            )
