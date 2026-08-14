"""Drug recall endpoints backed by live FDA enforcement data."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from healthscope.clients.fda import FDAClientDependency, FDAClientError, FDAUpstreamTimeoutError
from healthscope.schemas.drug_recalls import (
    OPENFDA_MAX_SKIP,
    DrugRecallPage,
    RecallClassification,
)

router = APIRouter(prefix="/drug-recalls", tags=["drug recalls"])
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0, le=OPENFDA_MAX_SKIP)]


@router.get(
    "",
    response_model=DrugRecallPage,
    status_code=status.HTTP_200_OK,
    summary="List FDA drug recall enforcement reports",
)
async def list_drug_recalls(
    fda_client: FDAClientDependency,
    classification: RecallClassification | None = None,
    limit: PageLimit = 25,
    offset: PageOffset = 0,
) -> DrugRecallPage:
    """Return newest-first public drug recall reports from FDA."""

    try:
        return await fda_client.fetch_drug_recalls(
            classification=classification,
            limit=limit,
            offset=offset,
        )
    except FDAUpstreamTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="FDA drug recall data did not respond before the request deadline.",
        ) from exc
    except FDAClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="FDA drug recall data is temporarily unavailable.",
        ) from exc
