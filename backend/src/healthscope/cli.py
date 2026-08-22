"""Operational command-line entry points for HealthScope data workflows."""

import asyncio
import json
import sys
from dataclasses import asdict

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from healthscope.clients.cms import CMSClientError, get_cms_client
from healthscope.config import Settings, get_settings
from healthscope.database import create_database_engine
from healthscope.services.ingestion import (
    HospitalIngestionError,
    HospitalIngestionResult,
    ingest_hospital_snapshots,
)
from healthscope.services.ingestion_lock import (
    HospitalIngestionAlreadyRunningError,
    acquire_hospital_ingestion_lock,
)


async def _run_configured_ingestion(settings: Settings) -> HospitalIngestionResult:
    """Build configured boundaries and execute one hospital ingestion run."""

    engine = create_database_engine(settings.database_url)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with acquire_hospital_ingestion_lock(
            engine,
            source_dataset_id=settings.cms_hospital_dataset_id,
        ):
            async with get_cms_client(settings) as client:
                return await ingest_hospital_snapshots(
                    client,
                    session_factory,
                    source_dataset_id=settings.cms_hospital_dataset_id,
                    page_size=settings.cms_ingestion_page_size,
                    max_attempts=settings.cms_ingestion_max_attempts,
                    retry_delay_seconds=settings.cms_ingestion_retry_delay_seconds,
                )
    finally:
        engine.dispose()


def _result_payload(result: HospitalIngestionResult, *, release_sha: str) -> dict[str, object]:
    """Convert an ingestion result to a stable JSON-serializable payload."""

    payload: dict[str, object] = asdict(result)
    payload["retrieved_at"] = result.retrieved_at.isoformat()
    payload["release_sha"] = release_sha
    payload["status"] = "ok"
    return payload


def main() -> None:
    """Ingest the current public CMS hospital dataset and report JSON."""

    settings: Settings | None = None
    try:
        settings = get_settings()
        result = asyncio.run(_run_configured_ingestion(settings))
    except (
        CMSClientError,
        HospitalIngestionAlreadyRunningError,
        HospitalIngestionError,
        SQLAlchemyError,
        ValidationError,
        ValueError,
    ) as exc:
        payload = {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        if settings is not None:
            payload["release_sha"] = settings.release_sha
        print(json.dumps(payload), file=sys.stderr)
        raise SystemExit(1) from exc

    assert settings is not None
    print(json.dumps(_result_payload(result, release_sha=settings.release_sha)))
