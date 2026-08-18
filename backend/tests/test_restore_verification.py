"""Tests for read-only database restore integrity verification."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from alembic import command
from healthscope.config import Settings
from healthscope.database import create_database_engine
from healthscope.models.hospitals import HospitalSnapshot
from healthscope.repositories.hospitals import (
    mark_hospital_snapshot_complete,
    upsert_hospital_snapshots,
)
from healthscope.repositories.ingestion_runs import (
    finish_hospital_ingestion_run,
    start_hospital_ingestion_run,
)
from healthscope.restore_verification import (
    EXPECTED_DATABASE_REVISION,
    RestoreVerificationError,
    RestoreVerificationResult,
    _run_configured_verification,
    main,
    verify_restored_database,
)
from healthscope.schemas.hospitals import Hospital, HospitalIngestionRunState

DATASET_ID = "xubh-q36u"
RETRIEVED_AT = datetime(2026, 8, 17, 12, tzinfo=UTC)
FINISHED_AT = RETRIEVED_AT + timedelta(minutes=2)
OFFICIAL_CMS_HOSPITAL = Hospital(
    facility_id="010001",
    facility_name="SOUTHEAST HEALTH MEDICAL CENTER",
    address="1108 ROSS CLARK CIRCLE",
    city="DOTHAN",
    state="AL",
    zip_code="36301",
    county="HOUSTON",
    telephone="(334) 793-8701",
    hospital_type="Acute Care Hospitals",
    ownership="Government - Hospital District or Authority",
    emergency_services=True,
    birthing_friendly=True,
    overall_rating=4,
)


@pytest.fixture
def migrated_engine(tmp_path: Path) -> Iterator[Engine]:
    """Create a migrated database without bypassing the Alembic contract."""

    backend_root = Path(__file__).parents[1]
    database_url = f"sqlite:///{tmp_path / 'restored.db'}"
    config = Config(backend_root / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == EXPECTED_DATABASE_REVISION

    engine = create_database_engine(database_url)
    yield engine
    engine.dispose()


def persist_valid_restore(session: Session, *, run_count: int = 1) -> str:
    """Persist one captured official CMS row and its operational metadata."""

    run = start_hospital_ingestion_run(
        session,
        source_dataset_id=DATASET_ID,
        retrieved_at=RETRIEVED_AT,
        started_at=RETRIEVED_AT,
    )
    upsert_hospital_snapshots(
        session,
        [OFFICIAL_CMS_HOSPITAL],
        source_dataset_id=DATASET_ID,
        retrieved_at=RETRIEVED_AT,
    )
    mark_hospital_snapshot_complete(
        session,
        source_dataset_id=DATASET_ID,
        retrieved_at=RETRIEVED_AT,
        record_count=1,
    )
    finish_hospital_ingestion_run(
        session,
        run_id=run.run_id,
        status=HospitalIngestionRunState.SUCCEEDED,
        expected_count=run_count,
        fetched_count=run_count,
        upserted_count=run_count,
        pages=1,
        request_attempts=1,
        finished_at=FINISHED_AT,
    )
    return run.run_id


def test_restore_verification_returns_aggregate_evidence(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session, session.begin():
        run_id = persist_valid_restore(session)

    with Session(migrated_engine) as session:
        result = verify_restored_database(session, source_dataset_id=DATASET_ID)

    assert result == RestoreVerificationResult(
        database_revision=EXPECTED_DATABASE_REVISION,
        source_dataset_id=DATASET_ID,
        snapshot_retrieved_at=RETRIEVED_AT,
        snapshot_completed_at=result.snapshot_completed_at,
        record_count=1,
        state_count=1,
        ingestion_run_id=run_id,
        ingestion_finished_at=FINISHED_AT,
    )


def test_configured_restore_verification_uses_database_setting(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session, session.begin():
        persist_valid_restore(session)

    result = _run_configured_verification(
        Settings(environment="test", database_url=str(migrated_engine.url))
    )

    assert result.record_count == 1
    assert result.source_dataset_id == DATASET_ID


def test_restore_verification_rejects_wrong_schema_revision(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        connection.exec_driver_sql("UPDATE alembic_version SET version_num = 'older_revision'")

    with (
        Session(migrated_engine) as session,
        pytest.raises(RestoreVerificationError, match="expected 20260724_03"),
    ):
        verify_restored_database(session, source_dataset_id=DATASET_ID)


def test_restore_verification_requires_completed_snapshot(migrated_engine: Engine) -> None:
    with (
        Session(migrated_engine) as session,
        pytest.raises(RestoreVerificationError, match="No completed hospital snapshot"),
    ):
        verify_restored_database(session, source_dataset_id=DATASET_ID)


def test_restore_verification_rejects_missing_snapshot_rows(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session, session.begin():
        persist_valid_restore(session)
        session.execute(delete(HospitalSnapshot))

    with (
        Session(migrated_engine) as session,
        pytest.raises(RestoreVerificationError, match="completion=1, rows=0"),
    ):
        verify_restored_database(session, source_dataset_id=DATASET_ID)


def test_restore_verification_requires_matching_successful_run(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session, session.begin():
        upsert_hospital_snapshots(
            session,
            [OFFICIAL_CMS_HOSPITAL],
            source_dataset_id=DATASET_ID,
            retrieved_at=RETRIEVED_AT,
        )
        mark_hospital_snapshot_complete(
            session,
            source_dataset_id=DATASET_ID,
            retrieved_at=RETRIEVED_AT,
            record_count=1,
        )

    with (
        Session(migrated_engine) as session,
        pytest.raises(RestoreVerificationError, match="no matching successful ingestion run"),
    ):
        verify_restored_database(session, source_dataset_id=DATASET_ID)


def test_restore_verification_rejects_inconsistent_run_counts(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session, session.begin():
        persist_valid_restore(session, run_count=2)

    with (
        Session(migrated_engine) as session,
        pytest.raises(RestoreVerificationError, match="expected=2, fetched=2"),
    ):
        verify_restored_database(session, source_dataset_id=DATASET_ID)


def test_restore_verification_cli_reports_json_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = RestoreVerificationResult(
        database_revision=EXPECTED_DATABASE_REVISION,
        source_dataset_id=DATASET_ID,
        snapshot_retrieved_at=RETRIEVED_AT,
        snapshot_completed_at=FINISHED_AT,
        record_count=5419,
        state_count=56,
        ingestion_run_id="11111111-1111-1111-1111-111111111111",
        ingestion_finished_at=FINISHED_AT,
    )

    with patch(
        "healthscope.restore_verification._run_configured_verification", return_value=result
    ):
        main()

    assert json.loads(capsys.readouterr().out) == {
        "status": "ok",
        "database_revision": EXPECTED_DATABASE_REVISION,
        "source_dataset_id": DATASET_ID,
        "snapshot_retrieved_at": "2026-08-17T12:00:00+00:00",
        "snapshot_completed_at": "2026-08-17T12:02:00+00:00",
        "record_count": 5419,
        "state_count": 56,
        "ingestion_run_id": "11111111-1111-1111-1111-111111111111",
        "ingestion_finished_at": "2026-08-17T12:02:00+00:00",
    }


def test_restore_verification_cli_reports_json_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(
            "healthscope.restore_verification._run_configured_verification",
            side_effect=RestoreVerificationError("snapshot rows do not match"),
        ),
        pytest.raises(SystemExit) as exit_info,
    ):
        main()

    assert exit_info.value.code == 1
    assert json.loads(capsys.readouterr().err) == {
        "status": "error",
        "error_type": "RestoreVerificationError",
        "message": "snapshot rows do not match",
    }


def test_restore_verification_cli_hides_database_error_detail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_error = OperationalError(
        "SELECT version_num FROM alembic_version",
        {},
        RuntimeError("private restored database connection detail"),
    )
    with (
        patch(
            "healthscope.restore_verification._run_configured_verification",
            side_effect=database_error,
        ),
        pytest.raises(SystemExit) as exit_info,
    ):
        main()

    assert exit_info.value.code == 1
    assert json.loads(capsys.readouterr().err) == {
        "status": "error",
        "error_type": "OperationalError",
        "message": "Could not query the configured restored database",
    }
