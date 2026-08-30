"""Public, read-only verification of a deployed HealthScope release."""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from healthscope.schemas.health import HealthResponse, ReadinessResponse
from healthscope.schemas.hospitals import (
    HospitalIngestionHealth,
    HospitalIngestionHealthReason,
    HospitalIngestionRunState,
    HospitalSnapshotStatus,
)

RELEASE_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
API_CACHE_CONTROL = "no-store"
REQUIRED_SECURITY_HEADERS = {
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


class DeploymentVerificationError(RuntimeError):
    """Raised when a public deployment violates the reviewed release contract."""


@dataclass(frozen=True)
class DeploymentVerificationResult:
    """Aggregate, non-secret launch evidence from the public deployment boundary."""

    checked_at: datetime
    base_url: str
    release_sha: str
    request_ids: tuple[str, str, str, str]
    source_dataset_id: str
    snapshot_retrieved_at: datetime
    snapshot_completed_at: datetime
    record_count: int
    state_count: int
    ingestion_run_id: str
    ingestion_finished_at: datetime
    ingestion_pages: int
    ingestion_request_attempts: int


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeploymentVerificationError(message)


def _validated_base_url(value: str) -> str:
    parsed = urlsplit(value)
    _require(parsed.scheme == "https", "Deployment URL must use HTTPS")
    _require(parsed.hostname is not None, "Deployment URL must include a hostname")
    _require(
        parsed.username is None and parsed.password is None,
        "Deployment URL cannot contain credentials",
    )
    _require(
        not parsed.query and not parsed.fragment,
        "Deployment URL cannot contain a query or fragment",
    )
    _require(parsed.path in {"", "/"}, "Deployment URL cannot contain a path")
    return value.rstrip("/")


def _verify_security_headers(response: httpx.Response, path: str) -> None:
    for name, expected in REQUIRED_SECURITY_HEADERS.items():
        _require(
            response.headers.get(name) == expected,
            f"{path} returned an invalid {name} header",
        )


def _verify_request_id(response: httpx.Response, path: str) -> str:
    request_id = str(response.headers.get("x-request-id", ""))
    _require(
        REQUEST_ID_PATTERN.fullmatch(request_id) is not None,
        f"{path} did not return a valid public X-Request-ID",
    )
    return request_id


def _get_response(client: httpx.Client, path: str) -> httpx.Response:
    response = client.get(path, headers={"Accept": "application/json"})
    _require(
        response.status_code == 200,
        f"{path} returned HTTP {response.status_code}; expected 200",
    )
    _verify_security_headers(response, path)
    return response


def _get_model[ResponseModel: BaseModel](
    client: httpx.Client,
    path: str,
    model: type[ResponseModel],
) -> tuple[ResponseModel, str]:
    response = _get_response(client, path)
    _require(
        response.headers.get("cache-control") == API_CACHE_CONTROL,
        f"{path} returned an invalid cache-control header",
    )
    _require(
        response.headers.get("content-type", "").startswith("application/json"),
        f"{path} did not return JSON",
    )
    request_id = _verify_request_id(response, path)
    try:
        return model.model_validate(response.json()), request_id
    except (ValueError, ValidationError) as exc:
        raise DeploymentVerificationError(f"{path} returned an invalid response contract") from exc


def verify_deployment(
    client: httpx.Client,
    *,
    expected_release_sha: str,
) -> DeploymentVerificationResult:
    """Verify release identity, public routing, and the initial CMS ingestion."""

    _require(
        RELEASE_SHA_PATTERN.fullmatch(expected_release_sha) is not None,
        "Expected release SHA must contain exactly 40 lowercase hexadecimal characters",
    )

    health, health_request_id = _get_model(client, "/api/v1/health", HealthResponse)
    _require(
        health.environment == "production",
        "Liveness did not report the production environment",
    )
    _require(
        health.release_sha == expected_release_sha,
        "Liveness release SHA did not match the approved release",
    )

    readiness, readiness_request_id = _get_model(client, "/api/v1/ready", ReadinessResponse)
    _require(
        readiness.status == "ready" and readiness.database == "available",
        "Readiness did not report an available database",
    )

    ingestion, ingestion_request_id = _get_model(
        client,
        "/api/v1/hospitals/ingestion/health",
        HospitalIngestionHealth,
    )
    _require(
        ingestion.healthy and ingestion.reason is HospitalIngestionHealthReason.HEALTHY,
        "Hospital ingestion was not healthy after initialization",
    )
    run = ingestion.latest_run
    _require(
        run is not None
        and run.status is HospitalIngestionRunState.SUCCEEDED
        and run.finished_at is not None,
        "Hospital ingestion did not expose a completed successful run",
    )
    assert run is not None and run.finished_at is not None
    _require(
        run.expected_count is not None
        and run.expected_count > 0
        and run.expected_count == run.fetched_count == run.upserted_count,
        "Hospital ingestion counts were incomplete or inconsistent",
    )

    snapshot, snapshot_request_id = _get_model(
        client,
        "/api/v1/hospitals/snapshots/latest",
        HospitalSnapshotStatus,
    )
    _require(
        snapshot.source_dataset_id == run.source_dataset_id,
        "Snapshot and ingestion dataset IDs differed",
    )
    _require(
        snapshot.retrieved_at == run.retrieved_at,
        "Snapshot and ingestion retrieval timestamps differed",
    )
    _require(
        snapshot.record_count == run.expected_count,
        "Snapshot and ingestion record counts differed",
    )
    _require(
        snapshot.state_count > 0
        and snapshot.state_count == len(snapshot.state_coverage)
        and sum(item.hospital_count for item in snapshot.state_coverage) == snapshot.record_count,
        "Snapshot state coverage was incomplete or inconsistent",
    )

    overview = _get_response(client, "/overview")
    _require(
        overview.headers.get("content-type", "").startswith("text/html"),
        "/overview did not return HTML",
    )
    _require(overview.headers.get("cache-control") == "no-cache", "/overview was not revalidated")
    _require(
        '<div id="root"></div>' in overview.text,
        "/overview did not return the dashboard entry document",
    )

    return DeploymentVerificationResult(
        checked_at=datetime.now(UTC),
        base_url=str(client.base_url).rstrip("/"),
        release_sha=expected_release_sha,
        request_ids=(
            health_request_id,
            readiness_request_id,
            ingestion_request_id,
            snapshot_request_id,
        ),
        source_dataset_id=snapshot.source_dataset_id,
        snapshot_retrieved_at=snapshot.retrieved_at,
        snapshot_completed_at=snapshot.completed_at,
        record_count=snapshot.record_count,
        state_count=snapshot.state_count,
        ingestion_run_id=run.run_id,
        ingestion_finished_at=run.finished_at,
        ingestion_pages=run.pages,
        ingestion_request_attempts=run.request_attempts,
    )


def _run_configured_verification(
    base_url: str,
    expected_release_sha: str,
    timeout_seconds: float,
) -> DeploymentVerificationResult:
    validated_url = _validated_base_url(base_url)
    _require(timeout_seconds > 0, "Request timeout must be greater than zero")
    with httpx.Client(
        base_url=validated_url,
        timeout=timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": "HealthScope deployment verifier"},
    ) as client:
        return verify_deployment(client, expected_release_sha=expected_release_sha)


def _result_payload(result: DeploymentVerificationResult) -> dict[str, object]:
    payload: dict[str, object] = asdict(result)
    payload["checked_at"] = result.checked_at.isoformat()
    payload["request_ids"] = list(result.request_ids)
    payload["snapshot_retrieved_at"] = result.snapshot_retrieved_at.isoformat()
    payload["snapshot_completed_at"] = result.snapshot_completed_at.isoformat()
    payload["ingestion_finished_at"] = result.ingestion_finished_at.isoformat()
    payload["status"] = "ok"
    return payload


def main() -> None:
    """Verify a public production deployment and emit aggregate JSON evidence."""

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("base_url", help="Public HTTPS deployment origin without a path")
    parser.add_argument("release_sha", help="Approved full 40-character release commit SHA")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    arguments = parser.parse_args()

    try:
        result = _run_configured_verification(
            arguments.base_url,
            arguments.release_sha,
            arguments.timeout_seconds,
        )
    except (DeploymentVerificationError, httpx.HTTPError, ValueError) as exc:
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
