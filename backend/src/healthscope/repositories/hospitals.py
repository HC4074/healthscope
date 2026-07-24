"""Persistence and read operations for CMS hospital snapshots."""

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Table, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from healthscope.models.hospitals import HospitalSnapshot, HospitalSnapshotCompletion
from healthscope.schemas.hospitals import (
    Hospital,
    HospitalSnapshotStatus,
    HospitalStateCoverage,
)

_KEY_COLUMNS = ("source_dataset_id", "snapshot_date", "facility_id")


def _snapshot_values(snapshot: HospitalSnapshot) -> dict[str, object]:
    """Convert an ORM snapshot into values accepted by a bulk insert."""

    table = HospitalSnapshot.__table__
    return {column.name: getattr(snapshot, column.name) for column in table.columns}


def _upsert_statement(
    table: Table,
    values: list[dict[str, object]],
    dialect_name: str,
) -> Executable:
    """Build a native idempotent upsert for supported database dialects."""

    if dialect_name == "postgresql":
        statement = postgresql_insert(table).values(values)
        update_values = {
            column.name: getattr(statement.excluded, column.name)
            for column in table.columns
            if column.name not in _KEY_COLUMNS
        }
        return statement.on_conflict_do_update(
            index_elements=[table.c[column] for column in _KEY_COLUMNS],
            set_=update_values,
        )
    if dialect_name == "sqlite":
        statement_sqlite = sqlite_insert(table).values(values)
        update_values = {
            column.name: getattr(statement_sqlite.excluded, column.name)
            for column in table.columns
            if column.name not in _KEY_COLUMNS
        }
        return statement_sqlite.on_conflict_do_update(
            index_elements=[table.c[column] for column in _KEY_COLUMNS],
            set_=update_values,
        )
    raise ValueError(f"Unsupported hospital snapshot database dialect: {dialect_name}")


def upsert_hospital_snapshots(
    session: Session,
    hospitals: list[Hospital],
    *,
    source_dataset_id: str,
    retrieved_at: datetime,
) -> int:
    """Insert or refresh one daily snapshot batch and return its record count."""

    snapshots = [
        HospitalSnapshot.from_hospital(
            hospital,
            source_dataset_id=source_dataset_id,
            retrieved_at=retrieved_at,
        )
        for hospital in hospitals
    ]
    facility_ids = [snapshot.facility_id for snapshot in snapshots]
    if len(facility_ids) != len(set(facility_ids)):
        raise ValueError("Hospital snapshot batches must contain unique facility IDs")
    if not snapshots:
        return 0

    table = cast(Table, HospitalSnapshot.__table__)
    statement = _upsert_statement(
        table,
        [_snapshot_values(snapshot) for snapshot in snapshots],
        session.get_bind().dialect.name,
    )
    session.execute(statement)
    return len(snapshots)


def mark_hospital_snapshot_complete(
    session: Session,
    *,
    source_dataset_id: str,
    retrieved_at: datetime,
    record_count: int,
) -> HospitalSnapshotCompletion:
    """Record completion after verifying every expected row was persisted."""

    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("Hospital snapshot completion timestamps must include a timezone")
    if not 1 <= len(source_dataset_id) <= 32:
        raise ValueError("Hospital snapshot dataset IDs must contain 1 to 32 characters")
    if record_count < 0:
        raise ValueError("Hospital snapshot record counts cannot be negative")

    retrieved_at_utc = retrieved_at.astimezone(UTC)
    snapshot_date = retrieved_at_utc.date()
    persisted_count = session.scalar(
        select(func.count())
        .select_from(HospitalSnapshot)
        .where(
            HospitalSnapshot.source_dataset_id == source_dataset_id,
            HospitalSnapshot.snapshot_date == snapshot_date,
            HospitalSnapshot.retrieved_at == retrieved_at_utc,
        )
    )
    if persisted_count != record_count:
        raise ValueError(
            "Hospital snapshot cannot be completed: "
            f"expected {record_count} rows but found {persisted_count}"
        )

    completion = HospitalSnapshotCompletion(
        source_dataset_id=source_dataset_id,
        snapshot_date=snapshot_date,
        retrieved_at=retrieved_at_utc,
        completed_at=datetime.now(UTC),
        record_count=record_count,
    )
    return session.merge(completion)


def get_latest_complete_hospital_snapshot(
    session: Session,
    *,
    source_dataset_id: str,
) -> HospitalSnapshotStatus | None:
    """Return the newest completion whose exact persisted row count still matches."""

    matching_row_count = (
        select(func.count())
        .select_from(HospitalSnapshot)
        .where(
            HospitalSnapshot.source_dataset_id == HospitalSnapshotCompletion.source_dataset_id,
            HospitalSnapshot.snapshot_date == HospitalSnapshotCompletion.snapshot_date,
            HospitalSnapshot.retrieved_at == HospitalSnapshotCompletion.retrieved_at,
        )
        .correlate(HospitalSnapshotCompletion)
        .scalar_subquery()
    )
    completion = session.scalar(
        select(HospitalSnapshotCompletion)
        .where(
            HospitalSnapshotCompletion.source_dataset_id == source_dataset_id,
            matching_row_count == HospitalSnapshotCompletion.record_count,
        )
        .order_by(
            HospitalSnapshotCompletion.snapshot_date.desc(),
            HospitalSnapshotCompletion.retrieved_at.desc(),
        )
        .limit(1)
    )
    if completion is None:
        return None

    coverage_rows = session.execute(
        select(HospitalSnapshot.state, func.count())
        .where(
            HospitalSnapshot.source_dataset_id == completion.source_dataset_id,
            HospitalSnapshot.snapshot_date == completion.snapshot_date,
            HospitalSnapshot.retrieved_at == completion.retrieved_at,
        )
        .group_by(HospitalSnapshot.state)
        .order_by(HospitalSnapshot.state)
    ).all()
    state_coverage = [
        HospitalStateCoverage(state=state, hospital_count=hospital_count)
        for state, hospital_count in coverage_rows
    ]
    retrieved_at = completion.retrieved_at.replace(
        tzinfo=completion.retrieved_at.tzinfo or UTC
    ).astimezone(UTC)
    completed_at = completion.completed_at.replace(
        tzinfo=completion.completed_at.tzinfo or UTC
    ).astimezone(UTC)
    return HospitalSnapshotStatus(
        source_dataset_id=completion.source_dataset_id,
        snapshot_date=completion.snapshot_date,
        retrieved_at=retrieved_at,
        completed_at=completed_at,
        record_count=completion.record_count,
        state_count=len(state_coverage),
        state_coverage=state_coverage,
    )
