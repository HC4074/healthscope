"""Bounded compatibility checks for HealthScope's live public data sources."""

import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

from pydantic import ValidationError

from healthscope.clients.cdc import CDCClientError, get_cdc_places_client
from healthscope.clients.cms import CMSClientError, get_cms_client
from healthscope.clients.fda import FDAClientError, get_fda_client
from healthscope.config import Settings, get_settings


class PublicDataSmokeError(Exception):
    """A public source returned a valid but unusable smoke-check result."""


@dataclass(frozen=True)
class PublicDataSmokeResult:
    """Small, JSON-safe summary of the current official source contracts."""

    checked_at: datetime
    cms_dataset_id: str
    cms_records: int
    cdc_dataset_id: str
    cdc_measures: int
    cdc_latest_year: int
    fda_records: int
    fda_last_updated: date


async def check_public_sources(settings: Settings) -> PublicDataSmokeResult:
    """Query bounded live samples from CMS, CDC PLACES, and openFDA."""

    cdc_client = get_cdc_places_client(settings)
    fda_client = get_fda_client(settings)
    async with get_cms_client(settings) as cms_client:
        cms_page, cdc_catalog, fda_page = await asyncio.gather(
            cms_client.fetch_hospitals(limit=1, offset=0),
            cdc_client.fetch_measure_catalog(),
            fda_client.fetch_drug_recalls(limit=1, offset=0, classification=None),
        )

    if cms_page.total < 1 or len(cms_page.items) != 1:
        raise PublicDataSmokeError("CMS returned no hospital sample")

    return PublicDataSmokeResult(
        checked_at=datetime.now(UTC),
        cms_dataset_id=settings.cms_hospital_dataset_id,
        cms_records=cms_page.total,
        cdc_dataset_id=settings.cdc_places_county_dataset_id,
        cdc_measures=cdc_catalog.total,
        cdc_latest_year=max(measure.latest_year for measure in cdc_catalog.items),
        fda_records=fda_page.total,
        fda_last_updated=fda_page.source.last_updated,
    )


def _result_payload(result: PublicDataSmokeResult) -> dict[str, object]:
    """Convert a smoke-check result to a stable JSON payload."""

    payload: dict[str, object] = asdict(result)
    payload["checked_at"] = result.checked_at.isoformat()
    payload["fda_last_updated"] = result.fda_last_updated.isoformat()
    payload["status"] = "ok"
    return payload


def main() -> None:
    """Check the live public source contracts and report structured JSON."""

    try:
        result = asyncio.run(check_public_sources(get_settings()))
    except (
        CDCClientError,
        CMSClientError,
        FDAClientError,
        PublicDataSmokeError,
        ValidationError,
        ValueError,
    ) as exc:
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
