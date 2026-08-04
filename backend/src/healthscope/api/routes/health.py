"""Service liveness and readiness endpoints."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from healthscope import __version__
from healthscope.api.dependencies import SettingsDependency
from healthscope.database import EngineDependency
from healthscope.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Check API liveness",
)
def health_check(settings: SettingsDependency) -> HealthResponse:
    """Return process metadata when the API is accepting requests."""

    return HealthResponse(
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessResponse,
            "description": "The API cannot currently reach its database.",
        }
    },
    summary="Check API readiness",
)
def readiness_check(engine: EngineDependency) -> ReadinessResponse | JSONResponse:
    """Report whether the API can reach the database required for stored insights."""

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response = ReadinessResponse(status="not_ready", database="unavailable")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(),
        )

    return ReadinessResponse(status="ready", database="available")
