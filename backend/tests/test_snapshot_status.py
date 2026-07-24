"""Tests for completed hospital snapshot status reads."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from healthscope.config import Settings
from healthscope.database import Base, get_session
from healthscope.main import create_app
from healthscope.repositories.hospitals import (
    get_latest_complete_hospital_snapshot,
    mark_hospital_snapshot_complete,
    upsert_hospital_snapshots,
)
from healthscope.schemas.hospitals import Hospital

DATASET_ID = "xubh-q36u"
FIRST_RETRIEVED_AT = datetime(2026, 7, 19, 12, tzinfo=UTC)
SECOND_RETRIEVED_AT = datetime(2026, 7, 20, 12, tzinfo=UTC)


def official_cms_hospital(facility_id: str, facility_name: str) -> Hospital:
    """Build a test record from fields captured from the official CMS dataset."""

    return Hospital(
        facility_id=facility_id,
        facility_name=facility_name,
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


HOSPITALS = [
    official_cms_hospital("010001", "SOUTHEAST HEALTH MEDICAL CENTER"),
    official_cms_hospital("010007", "MIZELL MEMORIAL HOSPITAL"),
]


def persist_complete_snapshot(
    session: Session,
    *,
    retrieved_at: datetime,
) -> None:
    """Persist and complete one deterministic snapshot."""

    upsert_hospital_snapshots(
        session,
        HOSPITALS,
        source_dataset_id=DATASET_ID,
        retrieved_at=retrieved_at,
    )
    mark_hospital_snapshot_complete(
        session,
        source_dataset_id=DATASET_ID,
        retrieved_at=retrieved_at,
        record_count=len(HOSPITALS),
    )


def test_latest_status_groups_state_coverage() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        persist_complete_snapshot(session, retrieved_at=FIRST_RETRIEVED_AT)

    with Session(engine) as session:
        status = get_latest_complete_hospital_snapshot(
            session,
            source_dataset_id=DATASET_ID,
        )

    assert status is not None
    assert status.snapshot_date.isoformat() == "2026-07-19"
    assert status.record_count == 2
    assert status.state_count == 1
    assert status.state_coverage[0].model_dump() == {
        "state": "AL",
        "hospital_count": 2,
    }
    engine.dispose()


def test_latest_status_skips_completion_invalidated_by_partial_same_day_retry() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        persist_complete_snapshot(session, retrieved_at=FIRST_RETRIEVED_AT)
        persist_complete_snapshot(session, retrieved_at=SECOND_RETRIEVED_AT)
        upsert_hospital_snapshots(
            session,
            HOSPITALS[:1],
            source_dataset_id=DATASET_ID,
            retrieved_at=SECOND_RETRIEVED_AT.replace(hour=18),
        )

    with Session(engine) as session:
        status = get_latest_complete_hospital_snapshot(
            session,
            source_dataset_id=DATASET_ID,
        )

    assert status is not None
    assert status.snapshot_date.isoformat() == "2026-07-19"
    engine.dispose()


def test_latest_snapshot_endpoint_returns_status(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'snapshot-status.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        persist_complete_snapshot(session, retrieved_at=FIRST_RETRIEVED_AT)

    def provide_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app(Settings(environment="test", database_url=database_url))
    app.dependency_overrides[get_session] = provide_session
    with TestClient(app) as client:
        response = client.get("/api/v1/hospitals/snapshots/latest")

    assert response.status_code == 200
    assert response.json() == {
        "source_dataset_id": DATASET_ID,
        "snapshot_date": "2026-07-19",
        "retrieved_at": "2026-07-19T12:00:00Z",
        "completed_at": response.json()["completed_at"],
        "record_count": 2,
        "state_count": 1,
        "state_coverage": [{"state": "AL", "hospital_count": 2}],
    }
    engine.dispose()


def test_latest_snapshot_endpoint_returns_not_found_without_completion(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty-status.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)

    def provide_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app(Settings(environment="test", database_url=database_url))
    app.dependency_overrides[get_session] = provide_session
    with TestClient(app) as client:
        response = client.get("/api/v1/hospitals/snapshots/latest")

    assert response.status_code == 404
    assert response.json()["detail"] == "No complete CMS hospital snapshot is available."
    engine.dispose()
