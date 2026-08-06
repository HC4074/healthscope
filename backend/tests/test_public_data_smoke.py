"""Tests for the live public-source compatibility smoke check."""

import asyncio
import json
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from healthscope.config import Settings
from healthscope.public_data_smoke import (
    PublicDataSmokeError,
    PublicDataSmokeResult,
    check_public_sources,
    main,
)
from healthscope.schemas.community_health import (
    CommunityHealthDataSource,
    CommunityHealthMeasure,
    CommunityHealthMeasureCatalog,
)
from healthscope.schemas.drug_recalls import DrugRecall, DrugRecallDataSource, DrugRecallPage
from healthscope.schemas.hospitals import Hospital, HospitalDataSource, HospitalPage

RETRIEVED_AT = datetime(2026, 8, 6, 20, tzinfo=UTC)


def hospital_page(*, total: int = 5432, include_item: bool = True) -> HospitalPage:
    """Build a bounded CMS response matching the public contract."""

    item = Hospital(
        facility_id="010001",
        facility_name="Southeast Health Medical Center",
        address="1108 Ross Clark Circle",
        city="Dothan",
        state="AL",
        zip_code="36301",
        county="Houston",
        telephone="3347938701",
        hospital_type="Acute Care Hospitals",
        ownership="Government - Hospital District or Authority",
        emergency_services=True,
        birthing_friendly=True,
        overall_rating=3,
    )
    return HospitalPage(
        items=[item] if include_item else [],
        total=total,
        limit=1,
        offset=0,
        source=HospitalDataSource(
            name="Centers for Medicare & Medicaid Services",
            dataset_name="Hospital General Information",
            dataset_url="https://data.cms.gov/provider-data/dataset/xubh-q36u",
            retrieved_at=RETRIEVED_AT,
        ),
    )


def measure_catalog() -> CommunityHealthMeasureCatalog:
    """Build a small CDC catalog response matching the public contract."""

    return CommunityHealthMeasureCatalog(
        items=[
            CommunityHealthMeasure(
                measure_id="DIABETES",
                measure="Diabetes among adults",
                category="Health Outcomes",
                latest_year=2023,
                county_count=2957,
            )
        ],
        total=1,
        source=CommunityHealthDataSource(
            name="Centers for Disease Control and Prevention",
            dataset_name="PLACES county data",
            dataset_url="https://data.cdc.gov/d/swc5-untb",
            retrieved_at=RETRIEVED_AT,
            estimate_type="Age-adjusted prevalence",
        ),
    )


def recall_page() -> DrugRecallPage:
    """Build a bounded openFDA response matching the public contract."""

    return DrugRecallPage(
        items=[
            DrugRecall(
                recall_number="D-0716-2026",
                event_id="99440",
                classification="Class II",
                status="Ongoing",
                recalling_firm="Rohto-Mentholatum (Vietnam) Co., Ltd.",
                city="Ho Chi Minh",
                state=None,
                country="Vietnam",
                product_description="Drug product",
                reason_for_recall="CGMP deviations",
                voluntary_mandated="Voluntary: Firm initiated",
                distribution_pattern="Nationwide",
                product_quantity=None,
                recall_initiation_date=date(2026, 7, 8),
                report_date=date(2026, 7, 29),
            )
        ],
        total=17860,
        limit=1,
        offset=0,
        classification=None,
        source=DrugRecallDataSource(
            name="U.S. Food and Drug Administration",
            dataset_name="Drug Recall Enforcement Reports",
            dataset_url="https://api.fda.gov/drug/enforcement.json",
            retrieved_at=RETRIEVED_AT,
            last_updated=date(2026, 7, 29),
            disclaimer="Do not rely on openFDA to make decisions regarding medical care.",
            terms_url="https://open.fda.gov/terms/",
            license_url="https://open.fda.gov/license/",
        ),
    )


def configured_clients(
    cms_response: HospitalPage,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Build deterministic async clients for all three public sources."""

    cms_client = MagicMock()
    cms_client.__aenter__ = AsyncMock(return_value=cms_client)
    cms_client.__aexit__ = AsyncMock(return_value=None)
    cms_client.fetch_hospitals = AsyncMock(return_value=cms_response)
    cdc_client = MagicMock()
    cdc_client.fetch_measure_catalog = AsyncMock(return_value=measure_catalog())
    fda_client = MagicMock()
    fda_client.fetch_drug_recalls = AsyncMock(return_value=recall_page())
    return cms_client, cdc_client, fda_client


def test_check_public_sources_queries_bounded_official_contracts() -> None:
    settings = Settings(environment="test")
    cms_client, cdc_client, fda_client = configured_clients(hospital_page())

    with (
        patch("healthscope.public_data_smoke.get_cms_client", return_value=cms_client),
        patch("healthscope.public_data_smoke.get_cdc_places_client", return_value=cdc_client),
        patch("healthscope.public_data_smoke.get_fda_client", return_value=fda_client),
    ):
        result = asyncio.run(check_public_sources(settings))

    assert result.cms_records == 5432
    assert result.cdc_measures == 1
    assert result.cdc_latest_year == 2023
    assert result.fda_records == 17860
    assert result.fda_last_updated == date(2026, 7, 29)
    assert result.checked_at.tzinfo is UTC
    cms_client.fetch_hospitals.assert_awaited_once_with(limit=1, offset=0)
    cdc_client.fetch_measure_catalog.assert_awaited_once_with()
    fda_client.fetch_drug_recalls.assert_awaited_once_with(limit=1, offset=0, classification=None)
    cms_client.__aexit__.assert_awaited_once()


def test_check_public_sources_rejects_empty_cms_dataset() -> None:
    settings = Settings(environment="test")
    clients = configured_clients(hospital_page(total=0, include_item=False))

    with (
        patch("healthscope.public_data_smoke.get_cms_client", return_value=clients[0]),
        patch("healthscope.public_data_smoke.get_cdc_places_client", return_value=clients[1]),
        patch("healthscope.public_data_smoke.get_fda_client", return_value=clients[2]),
        pytest.raises(PublicDataSmokeError, match="CMS returned no hospital sample"),
    ):
        asyncio.run(check_public_sources(settings))


def test_public_data_smoke_cli_reports_structured_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = PublicDataSmokeResult(
        checked_at=RETRIEVED_AT,
        cms_dataset_id="xubh-q36u",
        cms_records=5432,
        cdc_dataset_id="swc5-untb",
        cdc_measures=40,
        cdc_latest_year=2023,
        fda_records=17860,
        fda_last_updated=date(2026, 7, 29),
    )

    with patch(
        "healthscope.public_data_smoke.check_public_sources",
        new=AsyncMock(return_value=result),
    ):
        main()

    assert json.loads(capsys.readouterr().out) == {
        "status": "ok",
        "checked_at": "2026-08-06T20:00:00+00:00",
        "cms_dataset_id": "xubh-q36u",
        "cms_records": 5432,
        "cdc_dataset_id": "swc5-untb",
        "cdc_measures": 40,
        "cdc_latest_year": 2023,
        "fda_records": 17860,
        "fda_last_updated": "2026-07-29",
    }


def test_public_data_smoke_cli_reports_structured_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(
            "healthscope.public_data_smoke.check_public_sources",
            new=AsyncMock(side_effect=PublicDataSmokeError("CMS returned no hospital sample")),
        ),
        pytest.raises(SystemExit) as exit_info,
    ):
        main()

    assert exit_info.value.code == 1
    assert json.loads(capsys.readouterr().err) == {
        "status": "error",
        "error_type": "PublicDataSmokeError",
        "message": "CMS returned no hospital sample",
    }
