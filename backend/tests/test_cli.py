"""Tests for operational HealthScope command-line entry points."""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from healthscope.cli import _run_configured_ingestion, main
from healthscope.config import Settings
from healthscope.services.ingestion import HospitalIngestionError, HospitalIngestionResult
from healthscope.services.ingestion_lock import HospitalIngestionAlreadyRunningError

RESULT = HospitalIngestionResult(
    run_id="11111111-1111-1111-1111-111111111111",
    source_dataset_id="xubh-q36u",
    retrieved_at=datetime(2026, 7, 19, 22, tzinfo=UTC),
    expected_count=5432,
    fetched_count=5432,
    upserted_count=5432,
    pages=55,
    request_attempts=56,
)


def test_configured_ingestion_disposes_database_engine() -> None:
    settings = Settings(environment="test", database_url="sqlite://", cms_ingestion_page_size=25)
    engine = MagicMock()
    session_factory = object()
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("healthscope.cli.create_database_engine", return_value=engine),
        patch("healthscope.cli.sessionmaker", return_value=session_factory),
        patch("healthscope.cli.get_cms_client", return_value=client),
        patch(
            "healthscope.cli.ingest_hospital_snapshots",
            new=AsyncMock(return_value=RESULT),
        ) as ingest,
    ):
        result = asyncio.run(_run_configured_ingestion(settings))

    assert result == RESULT
    ingest.assert_awaited_once_with(
        client,
        session_factory,
        source_dataset_id="xubh-q36u",
        page_size=25,
        max_attempts=3,
        retry_delay_seconds=1.0,
    )
    client.__aenter__.assert_awaited_once_with()
    client.__aexit__.assert_awaited_once()
    engine.dispose.assert_called_once_with()


def test_ingestion_cli_reports_structured_success(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(environment="test")

    with (
        patch("healthscope.cli.get_settings", return_value=settings),
        patch(
            "healthscope.cli._run_configured_ingestion",
            new=AsyncMock(return_value=RESULT),
        ),
    ):
        main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "ok",
        "run_id": "11111111-1111-1111-1111-111111111111",
        "source_dataset_id": "xubh-q36u",
        "retrieved_at": "2026-07-19T22:00:00+00:00",
        "expected_count": 5432,
        "fetched_count": 5432,
        "upserted_count": 5432,
        "pages": 55,
        "request_attempts": 56,
    }


def test_ingestion_cli_reports_structured_failure(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(environment="test")

    with (
        patch("healthscope.cli.get_settings", return_value=settings),
        patch(
            "healthscope.cli._run_configured_ingestion",
            new=AsyncMock(side_effect=HospitalIngestionError("CMS page changed")),
        ),
        pytest.raises(SystemExit) as exit_info,
    ):
        main()

    assert exit_info.value.code == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload == {
        "status": "error",
        "error_type": "HospitalIngestionError",
        "message": "CMS page changed",
    }


def test_ingestion_cli_reports_overlapping_run_without_starting_client(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(environment="test")
    engine = MagicMock()
    client = MagicMock()

    with (
        patch("healthscope.cli.get_settings", return_value=settings),
        patch("healthscope.cli.create_database_engine", return_value=engine),
        patch(
            "healthscope.cli.acquire_hospital_ingestion_lock",
            side_effect=HospitalIngestionAlreadyRunningError("ingestion already running"),
        ),
        patch("healthscope.cli.get_cms_client", return_value=client),
        pytest.raises(SystemExit) as exit_info,
    ):
        main()

    assert exit_info.value.code == 1
    assert json.loads(capsys.readouterr().err) == {
        "status": "error",
        "error_type": "HospitalIngestionAlreadyRunningError",
        "message": "ingestion already running",
    }
    client.__aenter__.assert_not_called()
    engine.dispose.assert_called_once_with()
