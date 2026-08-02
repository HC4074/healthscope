"""Tests for the FDA drug recall public-data client."""

import asyncio
from collections.abc import Callable

import httpx
import pytest

from healthscope.clients.fda import (
    FDAClient,
    FDADataError,
    FDAUpstreamError,
    FDAUpstreamTimeoutError,
)


def fda_record(**overrides: object) -> dict[str, object]:
    """Return a captured August 2026 row from the official openFDA dataset."""

    record: dict[str, object] = {
        "status": "Ongoing",
        "city": "Cary",
        "state": "NC",
        "country": "United States",
        "classification": "Class II",
        "product_type": "Drugs",
        "event_id": "99376",
        "recalling_firm": "Chiesi USA, Inc.",
        "voluntary_mandated": "Voluntary: Firm initiated",
        "distribution_pattern": "Nationwide within the United States",
        "recall_number": "D-0689-2026",
        "product_description": "CLEVIPREX (clevidipine injectable emulsion), Rx Only",
        "product_quantity": "44280 vials",
        "reason_for_recall": "Lack of Assurance of Sterility",
        "recall_initiation_date": "20260706",
        "report_date": "20260722",
    }
    return record | overrides


def fda_payload(
    *,
    results: object | None = None,
    skip: object = 0,
    limit: object = 2,
    total: object = 17832,
) -> dict[str, object]:
    """Return an envelope reflecting the official openFDA response shape."""

    return {
        "meta": {
            "disclaimer": "Do not rely on openFDA to make decisions regarding medical care.",
            "terms": "https://open.fda.gov/terms/",
            "license": "https://open.fda.gov/license/",
            "last_updated": "2026-07-22",
            "results": {"skip": skip, "limit": limit, "total": total},
        },
        "results": [fda_record()] if results is None else results,
    }


def build_client(
    handler: Callable[[httpx.Request], httpx.Response], *, api_key: str | None = None
) -> FDAClient:
    """Build a client whose HTTP layer is deterministic."""

    return FDAClient(
        base_url="https://fda.example/",
        timeout_seconds=1,
        api_key=api_key,
        transport=httpx.MockTransport(handler),
    )


def test_fetch_drug_recalls_validates_and_maps_live_fda_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/drug/enforcement.json"
        assert request.url.params["sort"] == "report_date:desc"
        assert request.url.params["skip"] == "0"
        assert request.url.params["limit"] == "2"
        assert request.headers["user-agent"] == "HealthScope/0.1"
        return httpx.Response(200, json=fda_payload())

    page = asyncio.run(
        build_client(handler).fetch_drug_recalls(limit=2, offset=0, classification=None)
    )

    assert len(requests) == 1
    assert page.total == 17832
    assert page.items[0].recall_number == "D-0689-2026"
    assert page.items[0].classification == "Class II"
    assert page.items[0].report_date.isoformat() == "2026-07-22"
    assert page.items[0].recall_initiation_date is not None
    assert page.source.last_updated.isoformat() == "2026-07-22"
    assert page.source.dataset_url == "https://fda.example/drug/enforcement.json"


def test_fetch_drug_recalls_applies_exact_classification_and_optional_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["search"] == 'classification:"Class II"'
        assert request.url.params["api_key"] == "test-key"
        return httpx.Response(200, json=fda_payload())

    page = asyncio.run(
        build_client(handler, api_key="test-key").fetch_drug_recalls(
            limit=2,
            offset=0,
            classification="Class II",
        )
    )

    assert page.classification == "Class II"


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ConnectError])
def test_fetch_drug_recalls_maps_network_failures_to_domain_errors(
    failure: type[httpx.RequestError],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise failure("FDA request failed", request=request)

    expected_error = FDAUpstreamTimeoutError if failure is httpx.ReadTimeout else FDAUpstreamError
    with pytest.raises(expected_error):
        asyncio.run(
            build_client(handler).fetch_drug_recalls(limit=2, offset=0, classification=None)
        )


def test_fetch_drug_recalls_maps_http_failure_to_domain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    with pytest.raises(FDAUpstreamError):
        asyncio.run(
            build_client(handler).fetch_drug_recalls(limit=2, offset=0, classification=None)
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"not": "an FDA envelope"},
        fda_payload(results=[fda_record(report_date="invalid")]),
        fda_payload(skip=1),
        fda_payload(limit=3),
        fda_payload(results=[]),
        fda_payload(results=[fda_record(), fda_record(recall_number="D-0688-2026")], total=1),
        fda_payload(results=[fda_record(), fda_record()], total=2),
        fda_payload(
            results=[
                fda_record(report_date="20260721"),
                fda_record(recall_number="D-0688-2026", report_date="20260722"),
            ],
            total=2,
        ),
    ],
)
def test_fetch_drug_recalls_rejects_invalid_or_inconsistent_payloads(
    payload: dict[str, object],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(FDADataError):
        asyncio.run(
            build_client(handler).fetch_drug_recalls(limit=2, offset=0, classification=None)
        )


def test_fetch_drug_recalls_rejects_records_outside_filter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fda_payload())

    with pytest.raises(FDADataError):
        asyncio.run(
            build_client(handler).fetch_drug_recalls(
                limit=2,
                offset=0,
                classification="Class I",
            )
        )


def test_fetch_drug_recalls_normalizes_blank_legacy_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=fda_payload(
                results=[
                    fda_record(
                        event_id="",
                        status=None,
                        city="",
                        state="",
                        country="",
                        voluntary_mandated="",
                        product_quantity="",
                        recall_initiation_date="",
                    )
                ]
            ),
        )

    page = asyncio.run(
        build_client(handler).fetch_drug_recalls(limit=2, offset=0, classification=None)
    )

    recall = page.items[0]
    assert recall.event_id is None
    assert recall.status is None
    assert recall.state is None
    assert recall.recall_initiation_date is None
    assert recall.product_quantity is None
