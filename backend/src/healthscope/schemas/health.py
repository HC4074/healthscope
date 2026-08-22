"""Health-check response models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Public liveness response for the API service."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: str
    version: str
    release_sha: str
    environment: str


class ReadinessResponse(BaseModel):
    """Database-backed readiness state for traffic routing."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "not_ready"]
    database: Literal["available", "unavailable"]
