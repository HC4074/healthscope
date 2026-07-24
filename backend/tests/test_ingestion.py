"""Tests for the CMS hospital snapshot ingestion workflow."""

import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from healthscope.clients.cms import CMSUpstreamError, CMSUpstreamTimeoutError
from healthscope.database import Base
from healthscope.models import (
    HospitalIngestionRun,
    HospitalSnapshot,
    HospitalSnapshotCompletion,
)
from healthscope.schemas.hospitals import Hospital, HospitalDataSource, HospitalPage
from healthscope.services.ingestion import HospitalIngestionError, ingest_hospital_snapshots

RETRIEVED_AT = datetime(2026, 7, 19, 18, tzinfo=timezone(timedelta(hours=-4)))


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
    official_cms_hospital("01021F", "TUSCALOOSA VA MEDICAL CENTER"),
]


def hospital_page(items: list[Hospital], *, total: int, offset: int) -> HospitalPage:
    """Return a validated CMS page with deterministic provenance."""

    return HospitalPage(
        items=items,
        total=total,
        limit=max(1, len(items)),
        offset=offset,
        source=HospitalDataSource(
            name="Centers for Medicare & Medicaid Services",
            dataset_name="Hospital General Information",
            dataset_url="https://data.cms.gov/provider-data/dataset/xubh-q36u",
            retrieved_at=datetime(2026, 7, 19, 20, tzinfo=UTC),
        ),
    )


class StubCMSClient:
    """Serve deterministic pages while recording requested pagination."""

    def __init__(self, pages: dict[int, HospitalPage]) -> None:
        self.pages = pages
        self.calls: list[tuple[int, int]] = []

    async def fetch_hospitals(self, *, limit: int, offset: int) -> HospitalPage:
        self.calls.append((limit, offset))
        return self.pages[offset]


class FlakyCMSClient:
    """Return or raise queued CMS responses for retry tests."""

    def __init__(self, responses: list[HospitalPage | Exception]) -> None:
        self.responses = responses

    async def fetch_hospitals(self, *, limit: int, offset: int) -> HospitalPage:
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def sqlite_session_factory() -> tuple[object, sessionmaker[Session]]:
    """Create an in-memory snapshot store for one ingestion test."""

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_ingestion_pages_full_dataset_with_one_utc_timestamp() -> None:
    engine, factory = sqlite_session_factory()
    client = StubCMSClient(
        {
            0: hospital_page(HOSPITALS[:2], total=3, offset=0),
            2: hospital_page(HOSPITALS[2:], total=3, offset=2),
        }
    )

    result = asyncio.run(
        ingest_hospital_snapshots(
            client,
            factory,
            source_dataset_id="xubh-q36u",
            page_size=2,
            retrieved_at=RETRIEVED_AT,
        )
    )

    assert result.expected_count == 3
    assert result.run_id
    assert result.fetched_count == 3
    assert result.upserted_count == 3
    assert result.pages == 2
    assert result.request_attempts == 2
    assert result.retrieved_at == datetime(2026, 7, 19, 22, tzinfo=UTC)
    assert client.calls == [(2, 0), (2, 2)]
    with Session(engine) as session:
        snapshots = session.scalars(select(HospitalSnapshot)).all()
    assert len(snapshots) == 3
    assert {snapshot.snapshot_date.isoformat() for snapshot in snapshots} == {"2026-07-19"}
    assert {snapshot.retrieved_at for snapshot in snapshots} == {datetime(2026, 7, 19, 22)}
    with Session(engine) as session:
        completion = session.scalars(select(HospitalSnapshotCompletion)).one()
        run = session.scalars(select(HospitalIngestionRun)).one()
    assert completion.record_count == 3
    assert completion.retrieved_at == datetime(2026, 7, 19, 22)
    assert run.status == "succeeded"
    assert run.expected_count == 3
    assert run.fetched_count == 3
    assert run.upserted_count == 3
    assert run.pages == 2
    assert run.request_attempts == 2
    assert run.finished_at is not None
    assert run.error_type is None
    engine.dispose()


def test_ingestion_accepts_an_empty_official_dataset() -> None:
    engine, factory = sqlite_session_factory()
    client = StubCMSClient({0: hospital_page([], total=0, offset=0)})

    result = asyncio.run(
        ingest_hospital_snapshots(
            client,
            factory,
            source_dataset_id="xubh-q36u",
        )
    )

    assert result.expected_count == 0
    assert result.fetched_count == 0
    assert result.pages == 1
    assert result.request_attempts == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(HospitalSnapshot)) == 0
        completion = session.scalars(select(HospitalSnapshotCompletion)).one()
        run = session.scalars(select(HospitalIngestionRun)).one()
    assert completion.record_count == 0
    assert run.status == "succeeded"
    assert run.expected_count == 0
    engine.dispose()


@pytest.mark.parametrize(
    ("pages", "message"),
    [
        (
            {
                0: hospital_page(HOSPITALS[:1], total=2, offset=0),
                1: hospital_page(HOSPITALS[1:2], total=3, offset=1),
            },
            "record count changed",
        ),
        ({0: hospital_page(HOSPITALS[:2], total=1, offset=0)}, "more hospital records"),
        ({0: hospital_page([], total=2, offset=0)}, "empty page"),
        (
            {0: hospital_page([HOSPITALS[0], HOSPITALS[0]], total=2, offset=0)},
            "duplicate facility IDs",
        ),
        (
            {
                0: hospital_page(HOSPITALS[:1], total=2, offset=0),
                1: hospital_page(HOSPITALS[:1], total=2, offset=1),
            },
            "duplicate facility IDs",
        ),
    ],
)
def test_ingestion_rejects_inconsistent_pagination(
    pages: dict[int, HospitalPage], message: str
) -> None:
    engine, factory = sqlite_session_factory()

    with pytest.raises(HospitalIngestionError, match=message):
        asyncio.run(
            ingest_hospital_snapshots(
                StubCMSClient(pages),
                factory,
                source_dataset_id="xubh-q36u",
                page_size=2,
                retrieved_at=RETRIEVED_AT,
            )
        )

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(HospitalSnapshotCompletion)) == 0
        run = session.scalars(select(HospitalIngestionRun)).one()
    assert run.status == "failed"
    assert run.error_type == "HospitalIngestionError"
    assert run.error_message is not None
    assert message in run.error_message
    engine.dispose()


def test_ingestion_retries_transient_cms_failure() -> None:
    engine, factory = sqlite_session_factory()
    client = FlakyCMSClient(
        [
            CMSUpstreamTimeoutError(),
            hospital_page(HOSPITALS[:1], total=1, offset=0),
        ]
    )

    result = asyncio.run(
        ingest_hospital_snapshots(
            client,
            factory,
            source_dataset_id="xubh-q36u",
            max_attempts=2,
            retry_delay_seconds=0,
            retrieved_at=RETRIEVED_AT,
        )
    )

    assert result.request_attempts == 2
    assert result.fetched_count == 1
    engine.dispose()


def test_ingestion_reraises_transient_failure_after_attempt_limit() -> None:
    engine, factory = sqlite_session_factory()
    client = FlakyCMSClient([CMSUpstreamError(), CMSUpstreamTimeoutError()])

    with pytest.raises(CMSUpstreamTimeoutError):
        asyncio.run(
            ingest_hospital_snapshots(
                client,
                factory,
                source_dataset_id="xubh-q36u",
                max_attempts=2,
                retry_delay_seconds=0,
                retrieved_at=RETRIEVED_AT,
            )
        )

    with Session(engine) as session:
        run = session.scalars(select(HospitalIngestionRun)).one()
    assert run.status == "failed"
    assert run.request_attempts == 2
    assert run.error_type == "CMSUpstreamTimeoutError"
    engine.dispose()


@pytest.mark.parametrize(
    ("source_dataset_id", "page_size", "retrieved_at", "message"),
    [
        ("xubh-q36u", 0, RETRIEVED_AT, "page size"),
        ("xubh-q36u", 101, RETRIEVED_AT, "page size"),
        ("", 100, RETRIEVED_AT, "dataset IDs"),
        ("x" * 33, 100, RETRIEVED_AT, "dataset IDs"),
        ("xubh-q36u", 100, datetime(2026, 7, 19), "include a timezone"),
    ],
)
def test_ingestion_rejects_invalid_run_identity(
    source_dataset_id: str,
    page_size: int,
    retrieved_at: datetime,
    message: str,
) -> None:
    engine, factory = sqlite_session_factory()

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            ingest_hospital_snapshots(
                StubCMSClient({}),
                factory,
                source_dataset_id=source_dataset_id,
                page_size=page_size,
                retrieved_at=retrieved_at,
            )
        )

    engine.dispose()


@pytest.mark.parametrize(
    ("max_attempts", "retry_delay_seconds", "message"),
    [
        (0, 1, "attempts"),
        (11, 1, "attempts"),
        (3, -1, "retry delay"),
        (3, 61, "retry delay"),
    ],
)
def test_ingestion_rejects_invalid_retry_policy(
    max_attempts: int, retry_delay_seconds: float, message: str
) -> None:
    engine, factory = sqlite_session_factory()

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            ingest_hospital_snapshots(
                StubCMSClient({}),
                factory,
                source_dataset_id="xubh-q36u",
                max_attempts=max_attempts,
                retry_delay_seconds=retry_delay_seconds,
                retrieved_at=RETRIEVED_AT,
            )
        )

    engine.dispose()
