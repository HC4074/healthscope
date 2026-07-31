"""Tests for the public CDC community health endpoint."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from healthscope.clients.cdc import (
    CDCDataError,
    CDCPlacesClient,
    CDCUpstreamTimeoutError,
    get_cdc_places_client,
)
from healthscope.config import Settings
from healthscope.main import create_app
from healthscope.schemas.community_health import (
    CommunityHealthDataSource,
    CountyHealthEstimate,
    CountyHealthPage,
)


def county_health_page() -> CountyHealthPage:
    """Return a response page based on an official CDC PLACES record."""

    return CountyHealthPage(
        items=[
            CountyHealthEstimate(
                year=2023,
                state="AL",
                state_name="Alabama",
                county="Autauga",
                county_fips="01001",
                measure_id="DIABETES",
                measure="Diagnosed diabetes among adults",
                category="Health Outcomes",
                prevalence_percent=11.4,
                low_confidence_limit=9.8,
                high_confidence_limit=13.2,
                population=60342,
                adult_population=46253,
                latitude=32.5350016195151,
                longitude=-86.6428164158396,
            )
        ],
        total=67,
        limit=1,
        offset=3,
        state="AL",
        measure_id="DIABETES",
        source=CommunityHealthDataSource(
            name="Centers for Disease Control and Prevention",
            dataset_name="PLACES: Local Data for Better Health, County Data, 2025 release",
            dataset_url="https://data.cdc.gov/d/swc5-untb",
            retrieved_at=datetime(2026, 7, 31, tzinfo=UTC),
            estimate_type="Age-adjusted prevalence",
        ),
    )


class StubCDCPlacesClient:
    """Controllable CDC PLACES client used by endpoint tests."""

    def __init__(self, result: CountyHealthPage | Exception) -> None:
        self.result = result

    async def fetch_county_estimates(
        self,
        *,
        state: str,
        measure_id: str,
        limit: int,
        offset: int,
    ) -> CountyHealthPage:
        assert state == "AL"
        assert measure_id == "DIABETES"
        assert limit == 1
        assert offset == 3
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def client_for(result: CountyHealthPage | Exception) -> TestClient:
    """Create an app with its CDC boundary replaced by a stub."""

    app = create_app(Settings(environment="test"))
    app.dependency_overrides[get_cdc_places_client] = lambda: StubCDCPlacesClient(result)
    return TestClient(app)


def test_county_health_endpoint_returns_paginated_live_data_contract() -> None:
    with client_for(county_health_page()) as client:
        response = client.get(
            "/api/v1/community-health/counties?state=AL&measure_id=DIABETES&limit=1&offset=3"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 67
    assert payload["items"][0]["county_fips"] == "01001"
    assert payload["items"][0]["prevalence_percent"] == 11.4
    assert payload["source"]["estimate_type"] == "Age-adjusted prevalence"


def test_county_health_endpoint_rejects_invalid_filters_and_pagination() -> None:
    with client_for(county_health_page()) as client:
        response = client.get(
            "/api/v1/community-health/counties"
            "?state=Alabama&measure_id=DIABETES%27%20OR%201=1&limit=101&offset=-1"
        )

    assert response.status_code == 422


def test_county_health_endpoint_returns_gateway_timeout_for_slow_cdc() -> None:
    with client_for(CDCUpstreamTimeoutError()) as client:
        response = client.get(
            "/api/v1/community-health/counties?state=AL&measure_id=DIABETES&limit=1&offset=3"
        )

    assert response.status_code == 504
    assert "request deadline" in response.json()["detail"]


def test_county_health_endpoint_returns_bad_gateway_for_invalid_cdc_data() -> None:
    with client_for(CDCDataError()) as client:
        response = client.get(
            "/api/v1/community-health/counties?state=AL&measure_id=DIABETES&limit=1&offset=3"
        )

    assert response.status_code == 502
    assert "temporarily unavailable" in response.json()["detail"]


def test_openapi_schema_exposes_county_health_endpoint() -> None:
    with client_for(county_health_page()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/community-health/counties" in response.json()["paths"]


def test_cdc_dependency_builds_client_from_settings() -> None:
    client = get_cdc_places_client(Settings(environment="test"))

    assert isinstance(client, CDCPlacesClient)
