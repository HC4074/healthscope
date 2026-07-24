"""Orchestration for reproducible CMS hospital snapshot ingestion."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from healthscope.clients.cms import CMSUpstreamError, CMSUpstreamTimeoutError
from healthscope.repositories.hospitals import (
    mark_hospital_snapshot_complete,
    upsert_hospital_snapshots,
)
from healthscope.schemas.hospitals import HospitalPage


class HospitalPageClient(Protocol):
    """Boundary required from a paginated hospital source client."""

    async def fetch_hospitals(self, *, limit: int, offset: int) -> HospitalPage:
        """Fetch one validated page of hospital records."""


class HospitalIngestionError(Exception):
    """A snapshot could not be completed consistently."""


@dataclass(frozen=True)
class HospitalIngestionResult:
    """Counts and provenance reported by a completed ingestion run."""

    source_dataset_id: str
    retrieved_at: datetime
    expected_count: int
    fetched_count: int
    upserted_count: int
    pages: int
    request_attempts: int


async def _fetch_page_with_retries(
    client: HospitalPageClient,
    *,
    limit: int,
    offset: int,
    attempts_remaining: int,
    retry_delay_seconds: float,
) -> tuple[HospitalPage, int]:
    """Fetch one CMS page with bounded exponential retries."""

    try:
        return await client.fetch_hospitals(limit=limit, offset=offset), 1
    except (CMSUpstreamError, CMSUpstreamTimeoutError):
        if attempts_remaining == 1:
            raise
        await asyncio.sleep(retry_delay_seconds)
        page, attempts = await _fetch_page_with_retries(
            client,
            limit=limit,
            offset=offset,
            attempts_remaining=attempts_remaining - 1,
            retry_delay_seconds=retry_delay_seconds * 2,
        )
        return page, attempts + 1


async def ingest_hospital_snapshots(
    client: HospitalPageClient,
    session_factory: sessionmaker[Session],
    *,
    source_dataset_id: str,
    page_size: int = 100,
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
    retrieved_at: datetime | None = None,
) -> HospitalIngestionResult:
    """Page through CMS and persist one timestamp-consistent daily snapshot."""

    if not 1 <= page_size <= 100:
        raise ValueError("CMS hospital ingestion page size must be between 1 and 100")
    if not 1 <= max_attempts <= 10:
        raise ValueError("CMS hospital ingestion attempts must be between 1 and 10")
    if not 0 <= retry_delay_seconds <= 60:
        raise ValueError("CMS hospital ingestion retry delay must be between 0 and 60 seconds")
    if not 1 <= len(source_dataset_id) <= 32:
        raise ValueError("Hospital snapshot dataset IDs must contain 1 to 32 characters")

    snapshot_retrieved_at = retrieved_at or datetime.now(UTC)
    if snapshot_retrieved_at.tzinfo is None or snapshot_retrieved_at.utcoffset() is None:
        raise ValueError("Hospital ingestion timestamps must include a timezone")
    snapshot_retrieved_at = snapshot_retrieved_at.astimezone(UTC)

    expected_count: int | None = None
    fetched_count = 0
    upserted_count = 0
    pages = 0
    request_attempts = 0
    seen_facility_ids: set[str] = set()

    while expected_count is None or fetched_count < expected_count:
        page, page_attempts = await _fetch_page_with_retries(
            client,
            limit=page_size,
            offset=fetched_count,
            attempts_remaining=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )
        request_attempts += page_attempts
        pages += 1

        if expected_count is None:
            expected_count = page.total
        elif page.total != expected_count:
            raise HospitalIngestionError(
                f"CMS record count changed during ingestion: {expected_count} to {page.total}"
            )

        remaining_count = expected_count - fetched_count
        if len(page.items) > remaining_count:
            raise HospitalIngestionError(
                "CMS returned more hospital records than its reported total"
            )
        if not page.items:
            if remaining_count:
                raise HospitalIngestionError(
                    f"CMS returned an empty page at offset {fetched_count} "
                    f"before the reported total of {expected_count}"
                )
            break

        facility_ids = {hospital.facility_id for hospital in page.items}
        if len(facility_ids) != len(page.items) or facility_ids & seen_facility_ids:
            raise HospitalIngestionError("CMS returned duplicate facility IDs during ingestion")

        with session_factory.begin() as session:
            upserted_count += upsert_hospital_snapshots(
                session,
                page.items,
                source_dataset_id=source_dataset_id,
                retrieved_at=snapshot_retrieved_at,
            )

        seen_facility_ids.update(facility_ids)
        fetched_count += len(page.items)

    assert expected_count is not None
    with session_factory.begin() as session:
        mark_hospital_snapshot_complete(
            session,
            source_dataset_id=source_dataset_id,
            retrieved_at=snapshot_retrieved_at,
            record_count=expected_count,
        )

    return HospitalIngestionResult(
        source_dataset_id=source_dataset_id,
        retrieved_at=snapshot_retrieved_at,
        expected_count=expected_count,
        fetched_count=fetched_count,
        upserted_count=upserted_count,
        pages=pages,
        request_attempts=request_attempts,
    )
