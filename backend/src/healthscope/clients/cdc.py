"""Typed client for the CDC PLACES public dataset."""

from datetime import UTC, datetime
from typing import Annotated, Literal

import httpx
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from healthscope.api.dependencies import SettingsDependency
from healthscope.schemas.community_health import (
    CommunityHealthDataSource,
    CountyHealthEstimate,
    CountyHealthPage,
)

CDC_SOURCE_NAME = "Centers for Disease Control and Prevention"
CDC_PLACES_COUNTY_DATASET_NAME = "PLACES: Local Data for Better Health, County Data, 2025 release"
CDC_AGE_ADJUSTED_ESTIMATE_TYPE = "Age-adjusted prevalence"


class CDCClientError(Exception):
    """Base exception for failures while querying CDC data."""


class CDCUpstreamError(CDCClientError):
    """CDC data could not be reached or returned an unsuccessful status."""


class CDCUpstreamTimeoutError(CDCClientError):
    """CDC data did not respond within the configured deadline."""


class CDCDataError(CDCClientError):
    """CDC returned data that did not match the documented contract."""


class _CDCGeolocation(BaseModel):
    """Socrata point representation used by CDC PLACES."""

    type: Literal["Point"]
    coordinates: tuple[float, float]


class _CDCCountyEstimate(BaseModel):
    """Validated subset of a CDC PLACES county estimate."""

    model_config = ConfigDict(extra="ignore")

    year: int = Field(ge=2000, le=2100)
    stateabbr: str = Field(pattern=r"^[A-Z]{2}$")
    statedesc: str = Field(min_length=1)
    locationname: str = Field(min_length=1)
    datasource: Literal["BRFSS"]
    category: str = Field(min_length=1)
    measure: str = Field(min_length=1)
    data_value_unit: Literal["%"]
    data_value_type: Literal["Age-adjusted prevalence"]
    data_value: float = Field(ge=0, le=100)
    low_confidence_limit: float = Field(ge=0, le=100)
    high_confidence_limit: float = Field(ge=0, le=100)
    totalpopulation: int = Field(ge=0)
    totalpop18plus: int = Field(ge=0)
    locationid: str = Field(pattern=r"^\d{5}$")
    measureid: str = Field(pattern=r"^[A-Z0-9_]{2,32}$")
    datavaluetypeid: Literal["AgeAdjPrv"]
    geolocation: _CDCGeolocation

    @model_validator(mode="after")
    def validate_confidence_interval(self) -> "_CDCCountyEstimate":
        """Reject estimates that fall outside their reported confidence interval."""

        if not self.low_confidence_limit <= self.data_value <= self.high_confidence_limit:
            raise ValueError("CDC estimate must fall within its confidence interval")
        return self

    def to_public(self) -> CountyHealthEstimate:
        """Map CDC field names to the stable public API schema."""

        longitude, latitude = self.geolocation.coordinates
        return CountyHealthEstimate(
            year=self.year,
            state=self.stateabbr,
            state_name=self.statedesc,
            county=self.locationname,
            county_fips=self.locationid,
            measure_id=self.measureid,
            measure=self.measure,
            category=self.category,
            prevalence_percent=self.data_value,
            low_confidence_limit=self.low_confidence_limit,
            high_confidence_limit=self.high_confidence_limit,
            population=self.totalpopulation,
            adult_population=self.totalpop18plus,
            latitude=latitude,
            longitude=longitude,
        )


class _CDCCount(BaseModel):
    """Socrata count result for a filtered CDC PLACES query."""

    total: int = Field(ge=0)


class CDCPlacesClient:
    """Retrieve current county estimates from CDC PLACES."""

    def __init__(
        self,
        *,
        base_url: str,
        dataset_id: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._dataset_id = dataset_id
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def _build_http_client(self) -> httpx.AsyncClient:
        """Build an HTTP client with the CDC transport policy."""

        return httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            headers={"User-Agent": "HealthScope/0.1"},
        )

    async def fetch_county_estimates(
        self,
        *,
        state: str,
        measure_id: str,
        limit: int,
        offset: int,
    ) -> CountyHealthPage:
        """Fetch one validated page of age-adjusted county estimates."""

        url = f"{self._base_url}/resource/{self._dataset_id}.json"
        where = (
            f"stateabbr = '{state}' AND measureid = '{measure_id}' "
            "AND datavaluetypeid = 'AgeAdjPrv' AND data_value IS NOT NULL"
        )
        count_params = {"$select": "count(*) as total", "$where": where}
        page_params: dict[str, str | int] = {
            "$limit": limit,
            "$offset": offset,
            "$order": "locationid ASC",
            "$where": where,
        }
        try:
            async with self._build_http_client() as client:
                count_response = await client.get(url, params=count_params)
                count_response.raise_for_status()
                page_response = await client.get(url, params=page_params)
                page_response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise CDCUpstreamTimeoutError from exc
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise CDCUpstreamError from exc

        try:
            count_payload = count_response.json()
            if not isinstance(count_payload, list) or len(count_payload) != 1:
                raise ValueError("CDC count response must contain exactly one row")
            count = _CDCCount.model_validate(count_payload[0])
            records = [_CDCCountyEstimate.model_validate(record) for record in page_response.json()]
        except (TypeError, ValueError, ValidationError) as exc:
            raise CDCDataError from exc

        county_ids = [record.locationid for record in records]
        if len(county_ids) != len(set(county_ids)):
            raise CDCDataError("CDC returned duplicate county estimates")
        if any(record.stateabbr != state or record.measureid != measure_id for record in records):
            raise CDCDataError("CDC returned estimates outside the requested filter")
        if len(records) > limit or (offset < count.total and not records):
            raise CDCDataError("CDC returned inconsistent pagination")

        return CountyHealthPage(
            items=[record.to_public() for record in records],
            total=count.total,
            limit=limit,
            offset=offset,
            state=state,
            measure_id=measure_id,
            source=CommunityHealthDataSource(
                name=CDC_SOURCE_NAME,
                dataset_name=CDC_PLACES_COUNTY_DATASET_NAME,
                dataset_url=f"{self._base_url}/d/{self._dataset_id}",
                retrieved_at=datetime.now(UTC),
                estimate_type=CDC_AGE_ADJUSTED_ESTIMATE_TYPE,
            ),
        )


def get_cdc_places_client(settings: SettingsDependency) -> CDCPlacesClient:
    """Build a request-scoped CDC PLACES client from application settings."""

    return CDCPlacesClient(
        base_url=settings.cdc_data_base_url,
        dataset_id=settings.cdc_places_county_dataset_id,
        timeout_seconds=settings.cdc_request_timeout_seconds,
    )


CDCPlacesClientDependency = Annotated[CDCPlacesClient, Depends(get_cdc_places_client)]
