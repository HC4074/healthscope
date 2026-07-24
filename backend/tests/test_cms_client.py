"""Tests for the CMS Provider Data Catalog client."""

import asyncio
from collections.abc import Callable

import httpx
import pytest

from healthscope.clients.cms import (
    CMSClient,
    CMSDataError,
    CMSUpstreamError,
    CMSUpstreamTimeoutError,
)


def cms_record(**overrides: str) -> dict[str, str]:
    """Return a captured July 2026 CMS hospital row with selected overrides."""

    record = {
        "facility_id": "010001",
        "facility_name": "SOUTHEAST HEALTH MEDICAL CENTER",
        "address": "1108 ROSS CLARK CIRCLE",
        "citytown": "DOTHAN",
        "state": "AL",
        "zip_code": "36301",
        "countyparish": "HOUSTON",
        "telephone_number": "(334) 793-8701",
        "hospital_type": "Acute Care Hospitals",
        "hospital_ownership": "Government - Hospital District or Authority",
        "emergency_services": "Yes",
        "meets_criteria_for_birthing_friendly_designation": "Y",
        "hospital_overall_rating": "4",
    }
    return record | overrides


def build_client(handler: Callable[[httpx.Request], httpx.Response]) -> CMSClient:
    """Build a client whose HTTP layer is deterministic."""

    return CMSClient(
        base_url="https://cms.example/api/1/",
        dataset_id="xubh-q36u",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )


def test_fetch_hospitals_validates_and_maps_live_cms_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/1/datastore/query/xubh-q36u/0"
        assert request.url.params["limit"] == "3"
        assert request.url.params["offset"] == "10"
        assert request.headers["user-agent"] == "HealthScope/0.1"
        return httpx.Response(
            200,
            json={
                "results": [
                    cms_record(),
                    cms_record(
                        facility_id="010007",
                        facility_name="MIZELL MEMORIAL HOSPITAL",
                        meets_criteria_for_birthing_friendly_designation="",
                        hospital_overall_rating="1",
                    ),
                    cms_record(
                        facility_id="01021F",
                        facility_name="TUSCALOOSA VA MEDICAL CENTER",
                        emergency_services="No",
                        meets_criteria_for_birthing_friendly_designation="",
                        hospital_overall_rating="Not Available",
                    ),
                ],
                "count": 5432,
            },
        )

    page = asyncio.run(build_client(handler).fetch_hospitals(limit=3, offset=10))

    assert page.total == 5432
    assert page.limit == 3
    assert page.offset == 10
    assert page.items[0].overall_rating == 4
    assert page.items[0].emergency_services is True
    assert page.items[0].birthing_friendly is True
    assert page.items[1].birthing_friendly is None
    assert page.items[2].overall_rating is None
    assert page.items[2].emergency_services is False
    assert page.source.name == "Centers for Medicare & Medicaid Services"
    assert page.source.retrieved_at.tzinfo is not None


def test_cms_client_reuses_and_closes_workflow_connection_pool() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [cms_record()], "count": 1})

    client = build_client(handler)

    async def fetch_in_workflow() -> None:
        assert await client.__aenter__() is client
        assert await client.__aenter__() is client
        page = await client.fetch_hospitals(limit=1, offset=0)
        assert page.total == 1
        await client.__aexit__()
        await client.__aexit__()

    asyncio.run(fetch_in_workflow())


def test_fetch_hospitals_maps_timeout_to_domain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("CMS took too long", request=request)

    with pytest.raises(CMSUpstreamTimeoutError):
        asyncio.run(build_client(handler).fetch_hospitals(limit=1, offset=0))


def test_fetch_hospitals_maps_http_failure_to_domain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    with pytest.raises(CMSUpstreamError):
        asyncio.run(build_client(handler).fetch_hospitals(limit=1, offset=0))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"results": [cms_record(state="Alabama")], "count": 1}),
    ],
)
def test_fetch_hospitals_rejects_invalid_cms_payload(response: httpx.Response) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response.request = request
        return response

    with pytest.raises(CMSDataError):
        asyncio.run(build_client(handler).fetch_hospitals(limit=1, offset=0))
