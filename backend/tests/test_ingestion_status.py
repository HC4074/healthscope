"""Tests for durable hospital ingestion run status and freshness reads."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from healthscope.config import Settings
from healthscope.database import Base, get_session
from healthscope.main import create_app
from healthscope.repositories.hospitals import (
    mark_hospital_snapshot_complete,
    upsert_hospital_snapshots,
)
from healthscope.repositories.ingestion_runs import (
    finish_hospital_ingestion_run,
    get_latest_hospital_ingestion_status,
    start_hospital_ingestion_run,
    update_hospital_ingestion_run,
)
from healthscope.schemas.hospitals import Hospital, HospitalIngestionRunState

DATASET_ID = "xubh-q36u"
SUCCESS_RETRIEVED_AT = datetime(2026, 7, 23, 12, tzinfo=UTC)
FAILED_RETRIEVED_AT = datetime(2026, 7, 24, 14, tzinfo=UTC)
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


def test_latest_ingestion_reports_failure_and_last_success_freshness() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session, session.begin():
        successful_run = start_hospital_ingestion_run(
            session,
            source_dataset_id=DATASET_ID,
            retrieved_at=SUCCESS_RETRIEVED_AT,
            started_at=SUCCESS_RETRIEVED_AT,
        )
        upsert_hospital_snapshots(
            session,
            [OFFICIAL_CMS_HOSPITAL],
            source_dataset_id=DATASET_ID,
            retrieved_at=SUCCESS_RETRIEVED_AT,
        )
        mark_hospital_snapshot_complete(
            session,
            source_dataset_id=DATASET_ID,
            retrieved_at=SUCCESS_RETRIEVED_AT,
            record_count=1,
        )
        finish_hospital_ingestion_run(
            session,
            run_id=successful_run.run_id,
            status=HospitalIngestionRunState.SUCCEEDED,
            expected_count=5432,
            fetched_count=5432,
            upserted_count=5432,
            pages=55,
            request_attempts=55,
            finished_at=SUCCESS_RETRIEVED_AT + timedelta(minutes=2),
        )
        failed_run = start_hospital_ingestion_run(
            session,
            source_dataset_id=DATASET_ID,
            retrieved_at=FAILED_RETRIEVED_AT,
            started_at=FAILED_RETRIEVED_AT,
        )
        finish_hospital_ingestion_run(
            session,
            run_id=failed_run.run_id,
            status=HospitalIngestionRunState.FAILED,
            expected_count=5432,
            fetched_count=200,
            upserted_count=200,
            pages=2,
            request_attempts=4,
            error=RuntimeError("CMS request failed"),
            finished_at=FAILED_RETRIEVED_AT + timedelta(minutes=1),
        )
        failed_run_id = failed_run.run_id

    with Session(engine) as session:
        status = get_latest_hospital_ingestion_status(
            session,
            source_dataset_id=DATASET_ID,
            stale_after=timedelta(hours=26),
            now=datetime(2026, 7, 24, 16, tzinfo=UTC),
        )

    assert status is not None
    assert status.run_id == failed_run_id
    assert status.status is HospitalIngestionRunState.FAILED
    assert status.expected_count == 5432
    assert status.fetched_count == 200
    assert status.upserted_count == 200
    assert status.pages == 2
    assert status.request_attempts == 4
    assert status.error_type == "RuntimeError"
    assert status.error_message == "CMS request failed"
    assert status.latest_successful_retrieved_at == SUCCESS_RETRIEVED_AT
    assert status.freshness_seconds == 28 * 60 * 60
    assert status.stale_after_seconds == 26 * 60 * 60
    assert status.is_stale is True
    engine.dispose()


def test_ingestion_status_without_success_is_stale() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        run = start_hospital_ingestion_run(
            session,
            source_dataset_id=DATASET_ID,
            retrieved_at=FAILED_RETRIEVED_AT,
            started_at=FAILED_RETRIEVED_AT,
        )
        run_id = run.run_id

    with Session(engine) as session:
        status = get_latest_hospital_ingestion_status(
            session,
            source_dataset_id=DATASET_ID,
            stale_after=timedelta(hours=26),
            now=FAILED_RETRIEVED_AT + timedelta(minutes=1),
        )

    assert status is not None
    assert status.run_id == run_id
    assert status.status is HospitalIngestionRunState.STARTED
    assert status.finished_at is None
    assert status.latest_successful_retrieved_at is None
    assert status.freshness_seconds is None
    assert status.is_stale is True
    engine.dispose()


def test_ingestion_run_lifecycle_rejects_invalid_transitions_and_counts() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        run = start_hospital_ingestion_run(
            session,
            source_dataset_id=DATASET_ID,
            retrieved_at=FAILED_RETRIEVED_AT,
        )
        with pytest.raises(ValueError, match="cannot be negative"):
            update_hospital_ingestion_run(
                session,
                run_id=run.run_id,
                expected_count=None,
                fetched_count=-1,
                upserted_count=0,
                pages=0,
                request_attempts=0,
            )
        with pytest.raises(ValueError, match="cannot remain started"):
            finish_hospital_ingestion_run(
                session,
                run_id=run.run_id,
                status=HospitalIngestionRunState.STARTED,
                expected_count=None,
                fetched_count=0,
                upserted_count=0,
                pages=0,
                request_attempts=0,
            )
        with pytest.raises(ValueError, match="cannot include an error"):
            finish_hospital_ingestion_run(
                session,
                run_id=run.run_id,
                status=HospitalIngestionRunState.SUCCEEDED,
                expected_count=0,
                fetched_count=0,
                upserted_count=0,
                pages=1,
                request_attempts=1,
                error=RuntimeError("unexpected"),
            )
        with pytest.raises(ValueError, match="must include an error"):
            finish_hospital_ingestion_run(
                session,
                run_id=run.run_id,
                status=HospitalIngestionRunState.FAILED,
                expected_count=None,
                fetched_count=0,
                upserted_count=0,
                pages=0,
                request_attempts=0,
            )
        finish_hospital_ingestion_run(
            session,
            run_id=run.run_id,
            status=HospitalIngestionRunState.FAILED,
            expected_count=None,
            fetched_count=0,
            upserted_count=0,
            pages=0,
            request_attempts=1,
            error=RuntimeError("x" * 1100),
        )
        assert run.error_message is not None
        assert len(run.error_message) == 1000
        with pytest.raises(ValueError, match="already failed"):
            update_hospital_ingestion_run(
                session,
                run_id=run.run_id,
                expected_count=None,
                fetched_count=0,
                upserted_count=0,
                pages=0,
                request_attempts=1,
            )
        with pytest.raises(ValueError, match="does not exist"):
            update_hospital_ingestion_run(
                session,
                run_id="missing",
                expected_count=None,
                fetched_count=0,
                upserted_count=0,
                pages=0,
                request_attempts=0,
            )

    with Session(engine) as session, pytest.raises(ValueError, match="must be positive"):
        get_latest_hospital_ingestion_status(
            session,
            source_dataset_id=DATASET_ID,
            stale_after=timedelta(0),
        )
    engine.dispose()


@pytest.mark.parametrize(
    ("source_dataset_id", "retrieved_at", "started_at", "message"),
    [
        ("", FAILED_RETRIEVED_AT, FAILED_RETRIEVED_AT, "1 to 32 characters"),
        (DATASET_ID, datetime(2026, 7, 24), FAILED_RETRIEVED_AT, "include a timezone"),
        (DATASET_ID, FAILED_RETRIEVED_AT, datetime(2026, 7, 24), "include a timezone"),
    ],
)
def test_ingestion_run_rejects_invalid_identity(
    source_dataset_id: str,
    retrieved_at: datetime,
    started_at: datetime,
    message: str,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, pytest.raises(ValueError, match=message):
        start_hospital_ingestion_run(
            session,
            source_dataset_id=source_dataset_id,
            retrieved_at=retrieved_at,
            started_at=started_at,
        )
    engine.dispose()


def test_latest_ingestion_endpoint_returns_started_run(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'ingestion-status.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        run = start_hospital_ingestion_run(
            session,
            source_dataset_id=DATASET_ID,
            retrieved_at=FAILED_RETRIEVED_AT,
            started_at=FAILED_RETRIEVED_AT,
        )
        run_id = run.run_id

    def provide_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app(Settings(environment="test", database_url=database_url))
    app.dependency_overrides[get_session] = provide_session
    with TestClient(app) as client:
        response = client.get("/api/v1/hospitals/ingestion/latest")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": run_id,
        "source_dataset_id": DATASET_ID,
        "status": "started",
        "retrieved_at": "2026-07-24T14:00:00Z",
        "started_at": "2026-07-24T14:00:00Z",
        "finished_at": None,
        "expected_count": None,
        "fetched_count": 0,
        "upserted_count": 0,
        "pages": 0,
        "request_attempts": 0,
        "error_type": None,
        "error_message": None,
        "latest_successful_retrieved_at": None,
        "freshness_seconds": None,
        "stale_after_seconds": 93600,
        "is_stale": True,
    }
    engine.dispose()


def test_latest_ingestion_endpoint_returns_not_found_without_runs(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty-ingestion-status.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)

    def provide_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app(Settings(environment="test", database_url=database_url))
    app.dependency_overrides[get_session] = provide_session
    with TestClient(app) as client:
        response = client.get("/api/v1/hospitals/ingestion/latest")

    assert response.status_code == 404
    assert response.json()["detail"] == "No CMS hospital ingestion run is available."
    engine.dispose()


def test_ingestion_health_endpoint_reports_no_runs(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty-ingestion-health.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)

    def provide_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app(Settings(environment="test", database_url=database_url))
    app.dependency_overrides[get_session] = provide_session
    with TestClient(app) as client:
        response = client.get("/api/v1/hospitals/ingestion/health")

    assert response.status_code == 503
    assert response.json() == {
        "healthy": False,
        "reason": "no_runs",
        "latest_run": None,
    }
    engine.dispose()


def test_ingestion_health_endpoint_tracks_success_progress_and_failure(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'ingestion-health.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    observed_at = datetime.now(UTC)

    with Session(engine) as session, session.begin():
        retrieved_at = observed_at - timedelta(minutes=10)
        successful_run = start_hospital_ingestion_run(
            session,
            source_dataset_id=DATASET_ID,
            retrieved_at=retrieved_at,
            started_at=retrieved_at,
        )
        upsert_hospital_snapshots(
            session,
            [OFFICIAL_CMS_HOSPITAL],
            source_dataset_id=DATASET_ID,
            retrieved_at=retrieved_at,
        )
        mark_hospital_snapshot_complete(
            session,
            source_dataset_id=DATASET_ID,
            retrieved_at=retrieved_at,
            record_count=1,
        )
        finish_hospital_ingestion_run(
            session,
            run_id=successful_run.run_id,
            status=HospitalIngestionRunState.SUCCEEDED,
            expected_count=1,
            fetched_count=1,
            upserted_count=1,
            pages=1,
            request_attempts=1,
            finished_at=retrieved_at + timedelta(minutes=1),
        )
        successful_run_id = successful_run.run_id

    def provide_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app(Settings(environment="test", database_url=database_url))
    app.dependency_overrides[get_session] = provide_session
    with TestClient(app) as client:
        healthy_response = client.get("/api/v1/hospitals/ingestion/health")
        assert healthy_response.status_code == 200
        assert healthy_response.json()["healthy"] is True
        assert healthy_response.json()["reason"] == "healthy"
        assert healthy_response.json()["latest_run"]["run_id"] == successful_run_id

        with Session(engine) as session, session.begin():
            running = start_hospital_ingestion_run(
                session,
                source_dataset_id=DATASET_ID,
                retrieved_at=observed_at - timedelta(minutes=2),
                started_at=observed_at - timedelta(minutes=2),
            )
            running_id = running.run_id

        running_response = client.get("/api/v1/hospitals/ingestion/health")
        assert running_response.status_code == 200
        assert running_response.json()["healthy"] is True
        assert running_response.json()["reason"] == "ingestion_in_progress"
        assert running_response.json()["latest_run"]["run_id"] == running_id

        with Session(engine) as session, session.begin():
            finish_hospital_ingestion_run(
                session,
                run_id=running_id,
                status=HospitalIngestionRunState.FAILED,
                expected_count=5432,
                fetched_count=100,
                upserted_count=100,
                pages=1,
                request_attempts=3,
                error=RuntimeError("CMS request failed"),
                finished_at=observed_at - timedelta(minutes=1),
            )

        failed_response = client.get("/api/v1/hospitals/ingestion/health")

    assert failed_response.status_code == 503
    assert failed_response.json()["healthy"] is False
    assert failed_response.json()["reason"] == "latest_run_failed"
    assert failed_response.json()["latest_run"]["run_id"] == running_id
    engine.dispose()


def test_ingestion_health_endpoint_reports_stale_success(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'stale-ingestion-health.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    retrieved_at = datetime.now(UTC) - timedelta(hours=2)

    with Session(engine) as session, session.begin():
        run = start_hospital_ingestion_run(
            session,
            source_dataset_id=DATASET_ID,
            retrieved_at=retrieved_at,
            started_at=retrieved_at,
        )
        upsert_hospital_snapshots(
            session,
            [OFFICIAL_CMS_HOSPITAL],
            source_dataset_id=DATASET_ID,
            retrieved_at=retrieved_at,
        )
        mark_hospital_snapshot_complete(
            session,
            source_dataset_id=DATASET_ID,
            retrieved_at=retrieved_at,
            record_count=1,
        )
        finish_hospital_ingestion_run(
            session,
            run_id=run.run_id,
            status=HospitalIngestionRunState.SUCCEEDED,
            expected_count=1,
            fetched_count=1,
            upserted_count=1,
            pages=1,
            request_attempts=1,
            finished_at=retrieved_at + timedelta(minutes=1),
        )

    def provide_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app(
        Settings(
            environment="test",
            database_url=database_url,
            cms_ingestion_stale_after_hours=1,
        )
    )
    app.dependency_overrides[get_session] = provide_session
    with TestClient(app) as client:
        response = client.get("/api/v1/hospitals/ingestion/health")

    assert response.status_code == 503
    assert response.json()["healthy"] is False
    assert response.json()["reason"] == "stale"
    assert response.json()["latest_run"]["is_stale"] is True
    engine.dispose()
