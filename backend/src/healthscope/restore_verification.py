"""Read-only integrity verification for restored HealthScope databases."""

import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from healthscope.config import Settings, get_settings
from healthscope.database import create_database_engine
from healthscope.models.hospitals import HospitalSnapshot, HospitalSnapshotCompletion
from healthscope.models.ingestion import HospitalIngestionRun
from healthscope.schemas.hospitals import HospitalIngestionRunState

EXPECTED_DATABASE_REVISION = "20260724_03"


class RestoreVerificationError(RuntimeError):
    """Raised when a restored database fails an integrity requirement."""


@dataclass(frozen=True)
class RestoreVerificationResult:
    """Aggregate evidence that a restored CMS snapshot is internally consistent."""

    database_revision: str
    source_dataset_id: str
    snapshot_retrieved_at: datetime
    snapshot_completed_at: datetime
    record_count: int
    state_count: int
    ingestion_run_id: str
    ingestion_finished_at: datetime


def _stored_utc_timestamp(value: datetime) -> datetime:
    """Normalize timestamps from databases that discard timezone metadata."""

    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _verify_database_revision(session: Session) -> str:
    """Require the restored schema to match the migration head in this release."""

    revisions = tuple(
        sorted(
            str(revision)
            for revision in session.scalars(text("SELECT version_num FROM alembic_version"))
        )
    )
    expected = (EXPECTED_DATABASE_REVISION,)
    if revisions != expected:
        observed = ", ".join(revisions) if revisions else "none"
        raise RestoreVerificationError(
            "Restored database schema is not at the release migration head: "
            f"expected {EXPECTED_DATABASE_REVISION}, found {observed}"
        )
    return revisions[0]


def verify_restored_database(
    session: Session,
    *,
    source_dataset_id: str,
) -> RestoreVerificationResult:
    """Validate the newest CMS completion and its matching successful run."""

    database_revision = _verify_database_revision(session)
    completion = session.scalar(
        select(HospitalSnapshotCompletion)
        .where(HospitalSnapshotCompletion.source_dataset_id == source_dataset_id)
        .order_by(
            HospitalSnapshotCompletion.snapshot_date.desc(),
            HospitalSnapshotCompletion.retrieved_at.desc(),
        )
        .limit(1)
    )
    if completion is None:
        raise RestoreVerificationError(
            f"No completed hospital snapshot exists for dataset {source_dataset_id}"
        )

    snapshot_filter = (
        HospitalSnapshot.source_dataset_id == completion.source_dataset_id,
        HospitalSnapshot.snapshot_date == completion.snapshot_date,
        HospitalSnapshot.retrieved_at == completion.retrieved_at,
    )
    persisted_count = session.scalar(
        select(func.count()).select_from(HospitalSnapshot).where(*snapshot_filter)
    )
    if persisted_count != completion.record_count or completion.record_count <= 0:
        raise RestoreVerificationError(
            "Newest hospital completion does not match its exact restored snapshot rows: "
            f"completion={completion.record_count}, rows={persisted_count}"
        )

    state_counts = session.scalars(
        select(func.count())
        .select_from(HospitalSnapshot)
        .where(*snapshot_filter)
        .group_by(HospitalSnapshot.state)
    ).all()
    if not state_counts or sum(state_counts) != completion.record_count:
        raise RestoreVerificationError(
            "Restored hospital state coverage does not match the completed snapshot"
        )

    successful_run = session.scalar(
        select(HospitalIngestionRun)
        .where(
            HospitalIngestionRun.source_dataset_id == completion.source_dataset_id,
            HospitalIngestionRun.retrieved_at == completion.retrieved_at,
            HospitalIngestionRun.status == HospitalIngestionRunState.SUCCEEDED.value,
        )
        .order_by(HospitalIngestionRun.finished_at.desc(), HospitalIngestionRun.run_id.desc())
        .limit(1)
    )
    if successful_run is None or successful_run.finished_at is None:
        raise RestoreVerificationError(
            "Newest completed hospital snapshot has no matching successful ingestion run"
        )

    run_counts = (
        successful_run.expected_count,
        successful_run.fetched_count,
        successful_run.upserted_count,
    )
    if any(count != completion.record_count for count in run_counts):
        raise RestoreVerificationError(
            "Matching ingestion counts do not equal the completed snapshot row count: "
            f"expected={successful_run.expected_count}, "
            f"fetched={successful_run.fetched_count}, "
            f"upserted={successful_run.upserted_count}, "
            f"snapshot={completion.record_count}"
        )

    return RestoreVerificationResult(
        database_revision=database_revision,
        source_dataset_id=completion.source_dataset_id,
        snapshot_retrieved_at=_stored_utc_timestamp(completion.retrieved_at),
        snapshot_completed_at=_stored_utc_timestamp(completion.completed_at),
        record_count=completion.record_count,
        state_count=len(state_counts),
        ingestion_run_id=successful_run.run_id,
        ingestion_finished_at=_stored_utc_timestamp(successful_run.finished_at),
    )


def _run_configured_verification(settings: Settings) -> RestoreVerificationResult:
    """Connect to the configured database and run read-only integrity checks."""

    engine = create_database_engine(settings.database_url)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with session_factory() as session:
            return verify_restored_database(
                session,
                source_dataset_id=settings.cms_hospital_dataset_id,
            )
    finally:
        engine.dispose()


def _result_payload(result: RestoreVerificationResult) -> dict[str, object]:
    """Convert verification evidence to stable JSON without restored records."""

    payload: dict[str, object] = asdict(result)
    payload["snapshot_retrieved_at"] = result.snapshot_retrieved_at.isoformat()
    payload["snapshot_completed_at"] = result.snapshot_completed_at.isoformat()
    payload["ingestion_finished_at"] = result.ingestion_finished_at.isoformat()
    payload["status"] = "ok"
    return payload


def main() -> None:
    """Verify an isolated restored database and emit aggregate JSON evidence."""

    try:
        result = _run_configured_verification(get_settings())
    except SQLAlchemyError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": "Could not query the configured restored database",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except (
        RestoreVerificationError,
        ValidationError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    print(json.dumps(_result_payload(result)))
