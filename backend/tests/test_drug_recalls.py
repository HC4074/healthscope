"""Tests for the public FDA drug recall endpoint."""

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from healthscope.clients.fda import (
    FDAClient,
    FDADataError,
    FDAUpstreamTimeoutError,
    get_fda_client,
)
from healthscope.config import Settings
from healthscope.main import create_app
from healthscope.schemas.drug_recalls import DrugRecall, DrugRecallDataSource, DrugRecallPage


def drug_recall_page() -> DrugRecallPage:
    """Return a response page based on an official FDA enforcement report."""

    return DrugRecallPage(
        items=[
            DrugRecall(
                recall_number="D-0689-2026",
                event_id="99376",
                classification="Class II",
                status="Ongoing",
                recalling_firm="Chiesi USA, Inc.",
                city="Cary",
                state="NC",
                country="United States",
                product_description="CLEVIPREX (clevidipine injectable emulsion), Rx Only",
                reason_for_recall="Lack of Assurance of Sterility",
                voluntary_mandated="Voluntary: Firm initiated",
                distribution_pattern="Nationwide within the United States",
                product_quantity="44280 vials",
                recall_initiation_date=date(2026, 7, 6),
                report_date=date(2026, 7, 22),
            )
        ],
        total=14398,
        limit=1,
        offset=2,
        classification="Class II",
        source=DrugRecallDataSource(
            name="U.S. Food and Drug Administration",
            dataset_name="Drug Recall Enforcement Reports",
            dataset_url="https://api.fda.gov/drug/enforcement.json",
            retrieved_at=datetime(2026, 8, 2, tzinfo=UTC),
            last_updated=date(2026, 7, 22),
            disclaimer="Do not rely on openFDA to make decisions regarding medical care.",
            terms_url="https://open.fda.gov/terms/",
            license_url="https://open.fda.gov/license/",
        ),
    )


class StubFDAClient:
    """Controllable FDA client used by endpoint tests."""

    def __init__(self, result: DrugRecallPage | Exception) -> None:
        self.result = result

    async def fetch_drug_recalls(
        self,
        *,
        classification: str | None,
        limit: int,
        offset: int,
    ) -> DrugRecallPage:
        assert classification == "Class II"
        assert limit == 1
        assert offset == 2
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def client_for(result: DrugRecallPage | Exception) -> TestClient:
    """Create an app with its FDA boundary replaced by a stub."""

    app = create_app(Settings(environment="test"))
    app.dependency_overrides[get_fda_client] = lambda: StubFDAClient(result)
    return TestClient(app)


def test_drug_recall_endpoint_returns_paginated_live_data_contract() -> None:
    with client_for(drug_recall_page()) as client:
        response = client.get("/api/v1/drug-recalls?classification=Class%20II&limit=1&offset=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 14398
    assert payload["items"][0]["recall_number"] == "D-0689-2026"
    assert payload["items"][0]["report_date"] == "2026-07-22"
    assert payload["source"]["last_updated"] == "2026-07-22"
    assert "medical care" in payload["source"]["disclaimer"]


def test_drug_recall_endpoint_rejects_invalid_filters_and_pagination() -> None:
    with client_for(drug_recall_page()) as client:
        response = client.get("/api/v1/drug-recalls?classification=Critical&limit=101&offset=25901")

    assert response.status_code == 422


def test_drug_recall_endpoint_maps_fda_failures() -> None:
    with client_for(FDAUpstreamTimeoutError()) as client:
        timeout_response = client.get(
            "/api/v1/drug-recalls?classification=Class%20II&limit=1&offset=2"
        )
    with client_for(FDADataError()) as client:
        invalid_response = client.get(
            "/api/v1/drug-recalls?classification=Class%20II&limit=1&offset=2"
        )

    assert timeout_response.status_code == 504
    assert "request deadline" in timeout_response.json()["detail"]
    assert invalid_response.status_code == 502
    assert "temporarily unavailable" in invalid_response.json()["detail"]


def test_openapi_schema_exposes_drug_recall_endpoint() -> None:
    with client_for(drug_recall_page()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/drug-recalls" in response.json()["paths"]


def test_fda_dependency_builds_client_from_settings() -> None:
    client = get_fda_client(Settings(environment="test", fda_api_key="secret"))

    assert isinstance(client, FDAClient)
