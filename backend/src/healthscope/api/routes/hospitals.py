"""Hospital intelligence endpoints backed by live CMS data."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from healthscope.api.dependencies import SettingsDependency
from healthscope.clients.cms import (
    CMSClientDependency,
    CMSClientError,
    CMSUpstreamTimeoutError,
)
from healthscope.database import SessionDependency
from healthscope.repositories.hospitals import get_latest_complete_hospital_snapshot
from healthscope.repositories.ingestion_runs import get_latest_hospital_ingestion_status
from healthscope.schemas.hospitals import (
    HospitalIngestionHealth,
    HospitalIngestionHealthReason,
    HospitalIngestionRunState,
    HospitalIngestionStatus,
    HospitalPage,
    HospitalSnapshotStatus,
)

router = APIRouter(prefix="/hospitals", tags=["hospitals"])
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0)]


def _hospital_ingestion_health(
    ingestion_status: HospitalIngestionStatus | None,
) -> HospitalIngestionHealth:
    """Map ingestion lifecycle and freshness to a stable monitoring result."""

    if ingestion_status is None:
        return HospitalIngestionHealth(
            healthy=False,
            reason=HospitalIngestionHealthReason.NO_RUNS,
            latest_run=None,
        )
    if ingestion_status.status is HospitalIngestionRunState.FAILED:
        return HospitalIngestionHealth(
            healthy=False,
            reason=HospitalIngestionHealthReason.LATEST_RUN_FAILED,
            latest_run=ingestion_status,
        )
    if ingestion_status.is_stale:
        return HospitalIngestionHealth(
            healthy=False,
            reason=HospitalIngestionHealthReason.STALE,
            latest_run=ingestion_status,
        )
    if ingestion_status.status is HospitalIngestionRunState.STARTED:
        return HospitalIngestionHealth(
            healthy=True,
            reason=HospitalIngestionHealthReason.INGESTION_IN_PROGRESS,
            latest_run=ingestion_status,
        )
    return HospitalIngestionHealth(
        healthy=True,
        reason=HospitalIngestionHealthReason.HEALTHY,
        latest_run=ingestion_status,
    )


@router.get(
    "/ingestion/health",
    response_model=HospitalIngestionHealth,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": HospitalIngestionHealth,
            "description": "Hospital ingestion has failed, is stale, or has never run.",
        }
    },
    summary="Check hospital ingestion health",
)
def hospital_ingestion_health(
    response: Response,
    session: SessionDependency,
    settings: SettingsDependency,
) -> HospitalIngestionHealth:
    """Return an HTTP monitor-compatible ingestion health result."""

    ingestion_status = get_latest_hospital_ingestion_status(
        session,
        source_dataset_id=settings.cms_hospital_dataset_id,
        stale_after=timedelta(hours=settings.cms_ingestion_stale_after_hours),
    )
    health = _hospital_ingestion_health(ingestion_status)
    if not health.healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health


@router.get(
    "/ingestion/latest",
    response_model=HospitalIngestionStatus,
    status_code=status.HTTP_200_OK,
    summary="Get the latest hospital ingestion run",
)
def latest_hospital_ingestion(
    session: SessionDependency,
    settings: SettingsDependency,
) -> HospitalIngestionStatus:
    """Return the latest run and freshness of the newest successful snapshot."""

    ingestion_status = get_latest_hospital_ingestion_status(
        session,
        source_dataset_id=settings.cms_hospital_dataset_id,
        stale_after=timedelta(hours=settings.cms_ingestion_stale_after_hours),
    )
    if ingestion_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No CMS hospital ingestion run is available.",
        )
    return ingestion_status


@router.get(
    "/snapshots/latest",
    response_model=HospitalSnapshotStatus,
    status_code=status.HTTP_200_OK,
    summary="Get the latest complete hospital snapshot",
)
def latest_hospital_snapshot(
    session: SessionDependency,
    settings: SettingsDependency,
) -> HospitalSnapshotStatus:
    """Return metadata and state coverage for the newest complete CMS snapshot."""

    snapshot = get_latest_complete_hospital_snapshot(
        session,
        source_dataset_id=settings.cms_hospital_dataset_id,
    )
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No complete CMS hospital snapshot is available.",
        )
    return snapshot


@router.get(
    "",
    response_model=HospitalPage,
    status_code=status.HTTP_200_OK,
    summary="List current Medicare-registered hospitals",
)
async def list_hospitals(
    cms_client: CMSClientDependency,
    limit: PageLimit = 25,
    offset: PageOffset = 0,
) -> HospitalPage:
    """Return a validated page from CMS Hospital General Information."""

    try:
        return await cms_client.fetch_hospitals(limit=limit, offset=offset)
    except CMSUpstreamTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="CMS Provider Data did not respond before the request deadline.",
        ) from exc
    except CMSClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="CMS Provider Data is temporarily unavailable.",
        ) from exc
