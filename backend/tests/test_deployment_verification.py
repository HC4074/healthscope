"""Tests for public production deployment verification."""

import json
import sys
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from healthscope.deployment_verification import (
    DeploymentVerificationError,
    DeploymentVerificationResult,
    _result_payload,
    _run_configured_verification,
    main,
    verify_deployment,
)

RELEASE_SHA = "0123456789abcdef0123456789abcdef01234567"
REQUEST_IDS = {
    "/api/v1/health": "11111111111111111111111111111111",
    "/api/v1/ready": "22222222222222222222222222222222",
    "/api/v1/hospitals/ingestion/health": "33333333333333333333333333333333",
    "/api/v1/hospitals/snapshots/latest": "44444444444444444444444444444444",
}
SECURITY_HEADERS = {
    "content-security-policy": (
        "default-src 'self'; base-uri 'self'; connect-src 'self'; form-action 'self'; "
        "frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'"
    ),
    "cross-origin-opener-policy": "same-origin",
    "permissions-policy": "camera=(), geolocation=(), microphone=()",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


def response_payloads() -> dict[str, dict[str, object]]:
    return {
        "/api/v1/health": {
            "status": "ok",
            "service": "HealthScope",
            "version": "0.1.0",
            "release_sha": RELEASE_SHA,
            "environment": "production",
        },
        "/api/v1/ready": {"status": "ready", "database": "available"},
        "/api/v1/hospitals/ingestion/health": {
            "healthy": True,
            "reason": "healthy",
            "latest_run": {
                "run_id": "6ad13daf-b718-489a-bc7e-5da5641fc606",
                "source_dataset_id": "xubh-q36u",
                "status": "succeeded",
                "retrieved_at": "2026-08-29T06:00:00Z",
                "started_at": "2026-08-29T06:00:00Z",
                "finished_at": "2026-08-29T06:02:00Z",
                "expected_count": 5419,
                "fetched_count": 5419,
                "upserted_count": 5419,
                "pages": 55,
                "request_attempts": 55,
                "error_type": None,
                "error_message": None,
                "latest_successful_retrieved_at": "2026-08-29T06:00:00Z",
                "freshness_seconds": 60,
                "stale_after_seconds": 93600,
                "is_stale": False,
            },
        },
        "/api/v1/hospitals/snapshots/latest": {
            "source_dataset_id": "xubh-q36u",
            "snapshot_date": "2026-08-29",
            "retrieved_at": "2026-08-29T06:00:00Z",
            "completed_at": "2026-08-29T06:02:00Z",
            "record_count": 5419,
            "state_count": 2,
            "state_coverage": [
                {"state": "AL", "hospital_count": 3000},
                {"state": "AK", "hospital_count": 2419},
            ],
        },
    }


def deployment_client(
    *,
    payloads: dict[str, dict[str, object]] | None = None,
    missing_header: str | None = None,
) -> httpx.Client:
    configured_payloads = payloads or response_payloads()

    def handler(request: httpx.Request) -> httpx.Response:
        headers = dict(SECURITY_HEADERS)
        if request.url.path == "/overview":
            headers.update({"content-type": "text/html", "cache-control": "no-cache"})
            if missing_header is not None:
                headers.pop(missing_header, None)
            return httpx.Response(200, headers=headers, text='<div id="root"></div>')
        headers.update(
            {
                "cache-control": "no-store",
                "content-type": "application/json",
                "x-request-id": REQUEST_IDS[request.url.path],
            }
        )
        if missing_header is not None:
            headers.pop(missing_header, None)
        return httpx.Response(200, headers=headers, json=configured_payloads[request.url.path])

    return httpx.Client(
        base_url="https://healthscope.example.com",
        transport=httpx.MockTransport(handler),
    )


def test_verify_deployment_returns_aggregate_launch_evidence() -> None:
    with deployment_client() as client:
        result = verify_deployment(client, expected_release_sha=RELEASE_SHA)

    assert result.base_url == "https://healthscope.example.com"
    assert result.release_sha == RELEASE_SHA
    assert result.request_ids == tuple(REQUEST_IDS.values())
    assert result.source_dataset_id == "xubh-q36u"
    assert result.record_count == 5419
    assert result.state_count == 2
    assert result.ingestion_run_id == "6ad13daf-b718-489a-bc7e-5da5641fc606"
    assert result.ingestion_pages == 55
    assert result.ingestion_request_attempts == 55
    assert result.checked_at.tzinfo is UTC


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payloads: payloads["/api/v1/health"].update(release_sha="f" * 40),
            "release SHA did not match",
        ),
        (
            lambda payloads: payloads["/api/v1/hospitals/ingestion/health"]["latest_run"].update(
                upserted_count=5418
            ),
            "counts were incomplete or inconsistent",
        ),
        (
            lambda payloads: payloads["/api/v1/hospitals/snapshots/latest"].update(
                record_count=5418
            ),
            "record counts differed",
        ),
        (
            lambda payloads: payloads["/api/v1/hospitals/snapshots/latest"].update(state_count=3),
            "state coverage was incomplete or inconsistent",
        ),
    ],
)
def test_verify_deployment_rejects_inconsistent_contracts(
    mutate: object,
    message: str,
) -> None:
    payloads = response_payloads()
    assert callable(mutate)
    mutate(payloads)

    with (
        deployment_client(payloads=payloads) as client,
        pytest.raises(DeploymentVerificationError, match=message),
    ):
        verify_deployment(client, expected_release_sha=RELEASE_SHA)


def test_verify_deployment_rejects_missing_public_security_header() -> None:
    with (
        deployment_client(missing_header="x-frame-options") as client,
        pytest.raises(DeploymentVerificationError, match="invalid x-frame-options header"),
    ):
        verify_deployment(client, expected_release_sha=RELEASE_SHA)


def test_verify_deployment_rejects_cacheable_public_api_response() -> None:
    with (
        deployment_client(missing_header="cache-control") as client,
        pytest.raises(DeploymentVerificationError, match="invalid cache-control header"),
    ):
        verify_deployment(client, expected_release_sha=RELEASE_SHA)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://healthscope.example.com", "must use HTTPS"),
        ("https://user:secret@healthscope.example.com", "cannot contain credentials"),
        ("https://healthscope.example.com/overview", "cannot contain a path"),
    ],
)
def test_configured_verification_rejects_unsafe_base_urls(url: str, message: str) -> None:
    with pytest.raises(DeploymentVerificationError, match=message):
        _run_configured_verification(url, RELEASE_SHA, 10)


def test_deployment_verification_cli_reports_structured_success(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked_at = datetime(2026, 8, 29, 20, tzinfo=UTC)
    result = DeploymentVerificationResult(
        checked_at=checked_at,
        base_url="https://healthscope.example.com",
        release_sha=RELEASE_SHA,
        request_ids=tuple(REQUEST_IDS.values()),
        source_dataset_id="xubh-q36u",
        snapshot_retrieved_at=datetime(2026, 8, 29, 6, tzinfo=UTC),
        snapshot_completed_at=datetime(2026, 8, 29, 6, 2, tzinfo=UTC),
        record_count=5419,
        state_count=56,
        ingestion_run_id="6ad13daf-b718-489a-bc7e-5da5641fc606",
        ingestion_finished_at=datetime(2026, 8, 29, 6, 2, tzinfo=UTC),
        ingestion_pages=55,
        ingestion_request_attempts=55,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["healthscope-verify-deployment", "https://healthscope.example.com", RELEASE_SHA],
    )

    with patch(
        "healthscope.deployment_verification._run_configured_verification", return_value=result
    ):
        main()

    assert json.loads(capsys.readouterr().out) == _result_payload(result)


def test_deployment_verification_cli_reports_structured_failure(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["healthscope-verify-deployment", "http://unsafe.example.com", RELEASE_SHA]
    )

    with (
        patch(
            "healthscope.deployment_verification._run_configured_verification",
            side_effect=DeploymentVerificationError("Deployment URL must use HTTPS"),
        ),
        pytest.raises(SystemExit) as exit_info,
    ):
        main()

    assert exit_info.value.code == 1
    assert json.loads(capsys.readouterr().err) == {
        "status": "error",
        "error_type": "DeploymentVerificationError",
        "message": "Deployment URL must use HTTPS",
    }
