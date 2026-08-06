"""Tests for public liveness and readiness endpoints."""

import json
import re
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from healthscope.config import Settings
from healthscope.database import get_engine
from healthscope.main import create_app


def test_health_check_returns_service_metadata() -> None:
    settings = Settings(app_name="HealthScope Test", environment="test")

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "HealthScope Test",
        "version": "0.1.0",
        "environment": "test",
    }


def test_api_preserves_safe_request_id_and_logs_query_free_access_event() -> None:
    settings = Settings(environment="test")

    with (
        patch("healthscope.observability.access_logger.info") as log_info,
        TestClient(create_app(settings)) as client,
    ):
        response = client.get(
            "/api/v1/health?api_key=must-not-be-logged",
            headers={"X-Request-ID": "monitor-check:42"},
        )

    assert response.headers["X-Request-ID"] == "monitor-check:42"
    event = json.loads(log_info.call_args.args[0])
    assert event == {
        "duration_ms": event["duration_ms"],
        "environment": "test",
        "event": "http_request_completed",
        "method": "GET",
        "path": "/api/v1/health",
        "request_id": "monitor-check:42",
        "service_version": "0.1.0",
        "status_code": 200,
    }
    assert isinstance(event["duration_ms"], float)
    assert event["duration_ms"] >= 0
    assert "api_key" not in log_info.call_args.args[0]
    assert "must-not-be-logged" not in log_info.call_args.args[0]


def test_api_replaces_unsafe_request_id() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get(
            "/api/v1/health",
            headers={"X-Request-ID": "unsafe request id"},
        )

    generated_request_id = response.headers["X-Request-ID"]
    assert generated_request_id != "unsafe request id"
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        generated_request_id,
    )


def test_api_logs_unhandled_failure_with_request_id() -> None:
    app = create_app(Settings(environment="test"))

    @app.get("/failure")
    def fail_request() -> None:
        raise RuntimeError("expected test failure")

    with (
        patch("healthscope.observability.access_logger.exception") as log_exception,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.get("/failure", headers={"X-Request-ID": "failure-check"})

    assert response.status_code == 500
    event = json.loads(log_exception.call_args.args[0])
    assert event["event"] == "http_request_completed"
    assert event["request_id"] == "failure-check"
    assert event["path"] == "/failure"
    assert event["status_code"] == 500


def test_openapi_schema_exposes_health_endpoint() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
    assert "/api/v1/ready" in response.json()["paths"]


def test_readiness_check_returns_ready_when_database_is_available() -> None:
    engine = create_engine("sqlite://")
    app = create_app(Settings(environment="test"))
    app.dependency_overrides[get_engine] = lambda: engine

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "available"}
    engine.dispose()


def test_readiness_check_returns_503_without_leaking_database_details() -> None:
    unavailable_engine = MagicMock(spec=Engine)
    unavailable_engine.connect.side_effect = OperationalError(
        "SELECT 1", {}, ConnectionError("private database host")
    )
    app = create_app(Settings(environment="test"))
    app.dependency_overrides[get_engine] = lambda: unavailable_engine

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}
    assert "private database host" not in response.text
