"""Community health endpoints backed by live CDC PLACES data."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from healthscope.clients.cdc import (
    CDCClientError,
    CDCPlacesClientDependency,
    CDCUpstreamTimeoutError,
)
from healthscope.schemas.community_health import CommunityHealthMeasureCatalog, CountyHealthPage

router = APIRouter(prefix="/community-health", tags=["community health"])
StateCode = Annotated[str, Query(pattern=r"^[A-Z]{2}$")]
MeasureId = Annotated[str, Query(pattern=r"^[A-Z0-9_]{2,32}$")]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0)]


@router.get(
    "/measures",
    response_model=CommunityHealthMeasureCatalog,
    status_code=status.HTTP_200_OK,
    summary="List CDC county health measures",
)
async def list_community_health_measures(
    cdc_client: CDCPlacesClientDependency,
) -> CommunityHealthMeasureCatalog:
    """Return measures currently available from live CDC PLACES data."""

    try:
        return await cdc_client.fetch_measure_catalog()
    except CDCUpstreamTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="CDC PLACES did not respond before the request deadline.",
        ) from exc
    except CDCClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="CDC PLACES data is temporarily unavailable.",
        ) from exc


@router.get(
    "/counties",
    response_model=CountyHealthPage,
    status_code=status.HTTP_200_OK,
    summary="List CDC county health estimates",
)
async def list_county_health_estimates(
    cdc_client: CDCPlacesClientDependency,
    state: StateCode,
    measure_id: MeasureId,
    limit: PageLimit = 25,
    offset: PageOffset = 0,
) -> CountyHealthPage:
    """Return age-adjusted county prevalence estimates from CDC PLACES."""

    try:
        return await cdc_client.fetch_county_estimates(
            state=state,
            measure_id=measure_id,
            limit=limit,
            offset=offset,
        )
    except CDCUpstreamTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="CDC PLACES did not respond before the request deadline.",
        ) from exc
    except CDCClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="CDC PLACES data is temporarily unavailable.",
        ) from exc
