"""Tests for the CDC PLACES public-data client."""

import asyncio
from collections.abc import Callable

import httpx
import pytest

from healthscope.clients.cdc import (
    CDCDataError,
    CDCPlacesClient,
    CDCUpstreamError,
    CDCUpstreamTimeoutError,
)


def cdc_record(**overrides: object) -> dict[str, object]:
    """Return a captured July 2026 response row from the official CDC dataset."""

    record: dict[str, object] = {
        "year": "2023",
        "stateabbr": "AL",
        "statedesc": "Alabama",
        "locationname": "Autauga",
        "datasource": "BRFSS",
        "category": "Health Outcomes",
        "measure": "Diagnosed diabetes among adults",
        "data_value_unit": "%",
        "data_value_type": "Age-adjusted prevalence",
        "data_value": "11.4",
        "low_confidence_limit": "9.8",
        "high_confidence_limit": "13.2",
        "totalpopulation": "60342",
        "totalpop18plus": "46253",
        "locationid": "01001",
        "measureid": "DIABETES",
        "datavaluetypeid": "AgeAdjPrv",
        "geolocation": {
            "type": "Point",
            "coordinates": [-86.6428164158396, 32.5350016195151],
        },
    }
    return record | overrides


def build_client(handler: Callable[[httpx.Request], httpx.Response]) -> CDCPlacesClient:
    """Build a client whose HTTP layer is deterministic."""

    return CDCPlacesClient(
        base_url="https://cdc.example/",
        dataset_id="swc5-untb",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )


def test_fetch_county_estimates_validates_and_maps_live_cdc_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/resource/swc5-untb.json"
        assert request.headers["user-agent"] == "HealthScope/0.1"
        assert "stateabbr = 'AL'" in request.url.params["$where"]
        assert "measureid = 'DIABETES'" in request.url.params["$where"]
        assert "datavaluetypeid = 'AgeAdjPrv'" in request.url.params["$where"]
        if "$select" in request.url.params:
            assert request.url.params["$select"] == "count(*) as total"
            return httpx.Response(200, json=[{"total": "67"}])
        assert request.url.params["$limit"] == "1"
        assert request.url.params["$offset"] == "3"
        assert request.url.params["$order"] == "locationid ASC"
        return httpx.Response(200, json=[cdc_record()])

    page = asyncio.run(
        build_client(handler).fetch_county_estimates(
            state="AL", measure_id="DIABETES", limit=1, offset=3
        )
    )

    assert len(requests) == 2
    assert page.total == 67
    assert page.state == "AL"
    assert page.measure_id == "DIABETES"
    assert page.items[0].county_fips == "01001"
    assert page.items[0].prevalence_percent == 11.4
    assert page.items[0].latitude == pytest.approx(32.5350016195151)
    assert page.items[0].longitude == pytest.approx(-86.6428164158396)
    assert page.source.name == "Centers for Disease Control and Prevention"
    assert page.source.retrieved_at.tzinfo is not None


def test_fetch_county_estimates_maps_timeout_to_domain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("CDC took too long", request=request)

    with pytest.raises(CDCUpstreamTimeoutError):
        asyncio.run(
            build_client(handler).fetch_county_estimates(
                state="AL", measure_id="DIABETES", limit=1, offset=0
            )
        )


def test_fetch_county_estimates_maps_http_failure_to_domain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    with pytest.raises(CDCUpstreamError):
        asyncio.run(
            build_client(handler).fetch_county_estimates(
                state="AL", measure_id="DIABETES", limit=1, offset=0
            )
        )


@pytest.mark.parametrize(
    ("count_payload", "page_payload"),
    [
        ([], [cdc_record()]),
        ([{"total": "invalid"}], [cdc_record()]),
        ([{"total": "1"}], [cdc_record(data_value="not available")]),
        ([{"total": "1"}], [cdc_record(low_confidence_limit="12.0")]),
        ([{"total": "1"}], [cdc_record(stateabbr="GA")]),
        (
            [{"total": "2"}],
            [cdc_record(), cdc_record(locationname="Baldwin")],
        ),
        ([{"total": "1"}], []),
    ],
)
def test_fetch_county_estimates_rejects_invalid_or_inconsistent_payloads(
    count_payload: object,
    page_payload: object,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = count_payload if "$select" in request.url.params else page_payload
        return httpx.Response(200, json=payload)

    with pytest.raises(CDCDataError):
        asyncio.run(
            build_client(handler).fetch_county_estimates(
                state="AL", measure_id="DIABETES", limit=2, offset=0
            )
        )


def test_fetch_county_estimates_allows_empty_filtered_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload: list[dict[str, str]] = [{"total": "0"}] if "$select" in request.url.params else []
        return httpx.Response(200, json=payload)

    page = asyncio.run(
        build_client(handler).fetch_county_estimates(
            state="AL", measure_id="UNKNOWN", limit=10, offset=0
        )
    )

    assert page.total == 0
    assert page.items == []
