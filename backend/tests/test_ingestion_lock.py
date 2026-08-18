"""Tests for database-backed hospital ingestion exclusion."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from healthscope.services.ingestion_lock import (
    HospitalIngestionAlreadyRunningError,
    _hospital_ingestion_lock_key,
    acquire_hospital_ingestion_lock,
)


def _postgresql_engine(*, acquired: bool) -> tuple[Engine, MagicMock]:
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = engine.connect.return_value.__enter__.return_value
    connection.scalar.return_value = acquired
    return engine, connection


def test_ingestion_lock_uses_stable_dataset_scoped_signed_key() -> None:
    first = _hospital_ingestion_lock_key("xubh-q36u")

    assert first == _hospital_ingestion_lock_key("xubh-q36u")
    assert first != _hospital_ingestion_lock_key("another-dataset")
    assert -(2**63) <= first < 2**63


def test_ingestion_lock_acquires_and_releases_postgresql_lock() -> None:
    engine, connection = _postgresql_engine(acquired=True)

    with acquire_hospital_ingestion_lock(engine, source_dataset_id="xubh-q36u"):
        connection.execute.assert_not_called()

    acquisition = connection.scalar.call_args
    release = connection.execute.call_args
    assert str(acquisition.args[0]) == "SELECT pg_try_advisory_lock(:lock_key)"
    assert str(release.args[0]) == "SELECT pg_advisory_unlock(:lock_key)"
    assert acquisition.args[1] == release.args[1]


def test_ingestion_lock_releases_when_the_protected_job_fails() -> None:
    engine, connection = _postgresql_engine(acquired=True)

    with (
        pytest.raises(RuntimeError, match="source failed"),
        acquire_hospital_ingestion_lock(engine, source_dataset_id="xubh-q36u"),
    ):
        raise RuntimeError("source failed")

    connection.execute.assert_called_once()


def test_ingestion_lock_rejects_an_overlapping_postgresql_job() -> None:
    engine, connection = _postgresql_engine(acquired=False)

    with (
        pytest.raises(
            HospitalIngestionAlreadyRunningError,
            match="already running for dataset xubh-q36u",
        ),
        acquire_hospital_ingestion_lock(engine, source_dataset_id="xubh-q36u"),
    ):
        pytest.fail("overlapping job entered the protected section")

    connection.execute.assert_not_called()


def test_ingestion_lock_leaves_isolated_sqlite_workflows_available() -> None:
    engine = create_engine("sqlite://")

    with acquire_hospital_ingestion_lock(engine, source_dataset_id="xubh-q36u"):
        assert engine.dialect.name == "sqlite"

    engine.dispose()
