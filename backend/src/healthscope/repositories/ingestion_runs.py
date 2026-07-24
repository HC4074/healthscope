"""Persistence operations for CMS hospital ingestion run observability."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthscope.models.ingestion import HospitalIngestionRun
from healthscope.repositories.hospitals import get_latest_complete_hospital_snapshot
from healthscope.schemas.hospitals import (
    HospitalIngestionRunState,
    HospitalIngestionStatus,
)

_MAX_ERROR_MESSAGE_LENGTH = 1000


def _utc_timestamp(value: datetime, *, field_name: str) -> datetime:
    """Validate and normalize a timestamp to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _stored_utc_timestamp(value: datetime) -> datetime:
    """Normalize timestamps from databases that discard timezone metadata."""

    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _validate_counts(
    *,
    expected_count: int | None,
    fetched_count: int,
    upserted_count: int,
    pages: int,
    request_attempts: int,
) -> None:
    """Reject impossible negative ingestion counters."""

    counts = {
        "expected_count": expected_count,
        "fetched_count": fetched_count,
        "upserted_count": upserted_count,
        "pages": pages,
        "request_attempts": request_attempts,
    }
    if any(value is not None and value < 0 for value in counts.values()):
        raise ValueError("Hospital ingestion run counts cannot be negative")


def start_hospital_ingestion_run(
    session: Session,
    *,
    source_dataset_id: str,
    retrieved_at: datetime,
    started_at: datetime | None = None,
) -> HospitalIngestionRun:
    """Create a durable started record before the first upstream request."""

    if not 1 <= len(source_dataset_id) <= 32:
        raise ValueError("Hospital ingestion dataset IDs must contain 1 to 32 characters")
    run = HospitalIngestionRun(
        run_id=str(uuid4()),
        source_dataset_id=source_dataset_id,
        retrieved_at=_utc_timestamp(retrieved_at, field_name="Hospital ingestion retrieved_at"),
        started_at=_utc_timestamp(
            started_at or datetime.now(UTC),
            field_name="Hospital ingestion started_at",
        ),
        status=HospitalIngestionRunState.STARTED.value,
        expected_count=None,
        fetched_count=0,
        upserted_count=0,
        pages=0,
        request_attempts=0,
    )
    session.add(run)
    session.flush()
    return run


def _started_run(session: Session, run_id: str) -> HospitalIngestionRun:
    """Load a mutable started run or reject an invalid lifecycle transition."""

    run = session.get(HospitalIngestionRun, run_id)
    if run is None:
        raise ValueError(f"Hospital ingestion run does not exist: {run_id}")
    if run.status != HospitalIngestionRunState.STARTED.value:
        raise ValueError(f"Hospital ingestion run is already {run.status}: {run_id}")
    return run


def update_hospital_ingestion_run(
    session: Session,
    *,
    run_id: str,
    expected_count: int | None,
    fetched_count: int,
    upserted_count: int,
    pages: int,
    request_attempts: int,
) -> HospitalIngestionRun:
    """Persist the latest committed progress for a running ingestion."""

    _validate_counts(
        expected_count=expected_count,
        fetched_count=fetched_count,
        upserted_count=upserted_count,
        pages=pages,
        request_attempts=request_attempts,
    )
    run = _started_run(session, run_id)
    run.expected_count = expected_count
    run.fetched_count = fetched_count
    run.upserted_count = upserted_count
    run.pages = pages
    run.request_attempts = request_attempts
    return run


def finish_hospital_ingestion_run(
    session: Session,
    *,
    run_id: str,
    status: HospitalIngestionRunState,
    expected_count: int | None,
    fetched_count: int,
    upserted_count: int,
    pages: int,
    request_attempts: int,
    error: Exception | None = None,
    finished_at: datetime | None = None,
) -> HospitalIngestionRun:
    """Finalize one started ingestion as succeeded or failed."""

    if status is HospitalIngestionRunState.STARTED:
        raise ValueError("A finished hospital ingestion run cannot remain started")
    if status is HospitalIngestionRunState.SUCCEEDED and error is not None:
        raise ValueError("A successful hospital ingestion run cannot include an error")
    if status is HospitalIngestionRunState.FAILED and error is None:
        raise ValueError("A failed hospital ingestion run must include an error")

    run = update_hospital_ingestion_run(
        session,
        run_id=run_id,
        expected_count=expected_count,
        fetched_count=fetched_count,
        upserted_count=upserted_count,
        pages=pages,
        request_attempts=request_attempts,
    )
    run.status = status.value
    run.finished_at = _utc_timestamp(
        finished_at or datetime.now(UTC),
        field_name="Hospital ingestion finished_at",
    )
    run.error_type = type(error).__name__ if error is not None else None
    run.error_message = str(error)[:_MAX_ERROR_MESSAGE_LENGTH] if error is not None else None
    return run


def get_latest_hospital_ingestion_status(
    session: Session,
    *,
    source_dataset_id: str,
    stale_after: timedelta,
    now: datetime | None = None,
) -> HospitalIngestionStatus | None:
    """Return the newest run and freshness of the most recent successful snapshot."""

    if stale_after <= timedelta(0):
        raise ValueError("Hospital ingestion stale threshold must be positive")
    observed_at = _utc_timestamp(
        now or datetime.now(UTC),
        field_name="Hospital ingestion status timestamp",
    )
    latest_run = session.scalar(
        select(HospitalIngestionRun)
        .where(HospitalIngestionRun.source_dataset_id == source_dataset_id)
        .order_by(HospitalIngestionRun.started_at.desc(), HospitalIngestionRun.run_id.desc())
        .limit(1)
    )
    if latest_run is None:
        return None

    latest_complete_snapshot = get_latest_complete_hospital_snapshot(
        session,
        source_dataset_id=source_dataset_id,
    )
    successful_retrieved_at = (
        latest_complete_snapshot.retrieved_at if latest_complete_snapshot is not None else None
    )
    freshness_seconds = (
        max(0, int((observed_at - successful_retrieved_at).total_seconds()))
        if successful_retrieved_at is not None
        else None
    )
    stale_after_seconds = int(stale_after.total_seconds())

    return HospitalIngestionStatus(
        run_id=latest_run.run_id,
        source_dataset_id=latest_run.source_dataset_id,
        status=HospitalIngestionRunState(latest_run.status),
        retrieved_at=_stored_utc_timestamp(latest_run.retrieved_at),
        started_at=_stored_utc_timestamp(latest_run.started_at),
        finished_at=(
            _stored_utc_timestamp(latest_run.finished_at)
            if latest_run.finished_at is not None
            else None
        ),
        expected_count=latest_run.expected_count,
        fetched_count=latest_run.fetched_count,
        upserted_count=latest_run.upserted_count,
        pages=latest_run.pages,
        request_attempts=latest_run.request_attempts,
        error_type=latest_run.error_type,
        error_message=latest_run.error_message,
        latest_successful_retrieved_at=successful_retrieved_at,
        freshness_seconds=freshness_seconds,
        stale_after_seconds=stale_after_seconds,
        is_stale=(freshness_seconds is None or freshness_seconds > stale_after_seconds),
    )
