"""Tests for database configuration and CMS hospital persistence."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from alembic import command
from healthscope.config import Settings
from healthscope.database import (
    Base,
    create_database_engine,
    get_engine,
    get_session,
    get_session_factory,
)
from healthscope.models import HospitalSnapshot
from healthscope.repositories.hospitals import (
    _upsert_statement,
    mark_hospital_snapshot_complete,
    upsert_hospital_snapshots,
)
from healthscope.schemas.hospitals import Hospital

RETRIEVED_AT = datetime(2026, 7, 19, 12, 30, tzinfo=UTC)


def official_cms_hospital(**overrides: object) -> Hospital:
    """Return a validated record captured from the official CMS dataset."""

    values: dict[str, object] = {
        "facility_id": "010001",
        "facility_name": "SOUTHEAST HEALTH MEDICAL CENTER",
        "address": "1108 ROSS CLARK CIRCLE",
        "city": "DOTHAN",
        "state": "AL",
        "zip_code": "36301",
        "county": "HOUSTON",
        "telephone": "(334) 793-8701",
        "hospital_type": "Acute Care Hospitals",
        "ownership": "Government - Hospital District or Authority",
        "emergency_services": True,
        "birthing_friendly": True,
        "overall_rating": 4,
    }
    return Hospital.model_validate(values | overrides)


def test_snapshot_upsert_is_idempotent_and_refreshes_same_day() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session, session.begin():
        assert (
            upsert_hospital_snapshots(
                session,
                [official_cms_hospital()],
                source_dataset_id="xubh-q36u",
                retrieved_at=RETRIEVED_AT,
            )
            == 1
        )
        assert (
            upsert_hospital_snapshots(
                session,
                [official_cms_hospital(overall_rating=5)],
                source_dataset_id="xubh-q36u",
                retrieved_at=RETRIEVED_AT,
            )
            == 1
        )

    with Session(engine) as session:
        snapshot = session.scalars(select(HospitalSnapshot)).one()
        count = session.scalar(select(func.count()).select_from(HospitalSnapshot))

    assert count == 1
    assert snapshot.snapshot_date == RETRIEVED_AT.date()
    assert snapshot.facility_name == "SOUTHEAST HEALTH MEDICAL CENTER"
    assert snapshot.overall_rating == 5
    engine.dispose()


def test_snapshot_upsert_accepts_empty_batch_and_rejects_duplicates() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        assert (
            upsert_hospital_snapshots(
                session,
                [],
                source_dataset_id="xubh-q36u",
                retrieved_at=RETRIEVED_AT,
            )
            == 0
        )
        with pytest.raises(ValueError, match="unique facility IDs"):
            upsert_hospital_snapshots(
                session,
                [official_cms_hospital(), official_cms_hospital()],
                source_dataset_id="xubh-q36u",
                retrieved_at=RETRIEVED_AT,
            )
    engine.dispose()


def test_snapshot_completion_requires_exact_retrieval_batch() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session, session.begin():
        upsert_hospital_snapshots(
            session,
            [official_cms_hospital()],
            source_dataset_id="xubh-q36u",
            retrieved_at=RETRIEVED_AT,
        )
        completion = mark_hospital_snapshot_complete(
            session,
            source_dataset_id="xubh-q36u",
            retrieved_at=RETRIEVED_AT,
            record_count=1,
        )
        assert completion.record_count == 1

    with (
        Session(engine) as session,
        pytest.raises(ValueError, match="expected 2 rows but found 1"),
    ):
        mark_hospital_snapshot_complete(
            session,
            source_dataset_id="xubh-q36u",
            retrieved_at=RETRIEVED_AT,
            record_count=2,
        )
    engine.dispose()


@pytest.mark.parametrize(
    ("source_dataset_id", "retrieved_at", "record_count", "message"),
    [
        ("xubh-q36u", datetime(2026, 7, 19), 0, "include a timezone"),
        ("", RETRIEVED_AT, 0, "1 to 32 characters"),
        ("xubh-q36u", RETRIEVED_AT, -1, "cannot be negative"),
    ],
)
def test_snapshot_completion_rejects_invalid_identity(
    source_dataset_id: str,
    retrieved_at: datetime,
    record_count: int,
    message: str,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session, pytest.raises(ValueError, match=message):
        mark_hospital_snapshot_complete(
            session,
            source_dataset_id=source_dataset_id,
            retrieved_at=retrieved_at,
            record_count=record_count,
        )
    engine.dispose()


def test_upsert_builder_compiles_for_postgresql_and_rejects_unknown_dialect() -> None:
    snapshot = HospitalSnapshot.from_hospital(
        official_cms_hospital(),
        source_dataset_id="xubh-q36u",
        retrieved_at=RETRIEVED_AT,
    )
    table = HospitalSnapshot.__table__
    values = [{column.name: getattr(snapshot, column.name) for column in table.columns}]

    statement = _upsert_statement(table, values, "postgresql")
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT" in sql
    assert "source_dataset_id" in sql
    with pytest.raises(ValueError, match=r"Unsupported.*mysql"):
        _upsert_statement(table, values, "mysql")


def test_snapshot_normalizes_utc_date_and_rejects_invalid_identity() -> None:
    retrieved_at = datetime(2026, 7, 20, 1, tzinfo=timezone(timedelta(hours=2)))

    snapshot = HospitalSnapshot.from_hospital(
        official_cms_hospital(),
        source_dataset_id="xubh-q36u",
        retrieved_at=retrieved_at,
    )

    assert snapshot.retrieved_at == datetime(2026, 7, 19, 23, tzinfo=UTC)
    assert snapshot.snapshot_date.isoformat() == "2026-07-19"
    with pytest.raises(ValueError, match="include a timezone"):
        HospitalSnapshot.from_hospital(
            official_cms_hospital(),
            source_dataset_id="xubh-q36u",
            retrieved_at=datetime(2026, 7, 19),
        )
    with pytest.raises(ValueError, match="1 to 32 characters"):
        HospitalSnapshot.from_hospital(
            official_cms_hospital(),
            source_dataset_id="",
            retrieved_at=RETRIEVED_AT,
        )


def test_cached_engine_and_transactional_session_use_configured_database(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'sessions.db'}"
    settings = Settings(environment="test", database_url=database_url)
    get_session_factory.cache_clear()
    get_engine.cache_clear()

    with patch("healthscope.database.get_settings", return_value=settings):
        engine = get_engine()
        assert engine is get_engine()
        standalone_engine = create_database_engine(database_url)
        assert standalone_engine.pool is not None
        standalone_engine.dispose()
        Base.metadata.create_all(engine)
        session_iterator = get_session()
        session = next(session_iterator)
        session.add(
            HospitalSnapshot.from_hospital(
                official_cms_hospital(),
                source_dataset_id="xubh-q36u",
                retrieved_at=RETRIEVED_AT,
            )
        )
        with pytest.raises(StopIteration):
            next(session_iterator)

    with Session(engine) as verification_session:
        assert verification_session.scalar(select(func.count()).select_from(HospitalSnapshot)) == 1
    engine.dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()


def test_migration_upgrades_and_downgrades_empty_database(tmp_path: Path) -> None:
    backend_root = Path(__file__).parents[1]
    config = Config(backend_root / "alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'migration.db'}")

    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    inspector = inspect(engine)

    assert "hospital_snapshots" in inspector.get_table_names()
    assert "hospital_snapshot_completions" in inspector.get_table_names()
    assert set(inspector.get_pk_constraint("hospital_snapshots")["constrained_columns"]) == {
        "source_dataset_id",
        "snapshot_date",
        "facility_id",
    }
    assert {
        constraint["name"] for constraint in inspector.get_check_constraints("hospital_snapshots")
    } == {
        "ck_hospital_snapshots_overall_rating_range",
        "ck_hospital_snapshots_state_length",
    }
    assert {
        constraint["name"]
        for constraint in inspector.get_check_constraints("hospital_snapshot_completions")
    } == {"ck_hospital_snapshot_completions_record_count_nonnegative"}

    command.downgrade(config, "base")
    assert "hospital_snapshots" not in inspect(engine).get_table_names()
    assert "hospital_snapshot_completions" not in inspect(engine).get_table_names()
    engine.dispose()
