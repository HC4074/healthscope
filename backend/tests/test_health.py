"""Tests for public liveness and readiness endpoints."""

from unittest.mock import MagicMock

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
