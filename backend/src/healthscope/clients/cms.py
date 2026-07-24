"""Typed client for the CMS Provider Data Catalog."""

from datetime import UTC, datetime
from typing import Annotated, Literal

import httpx
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from healthscope.api.dependencies import SettingsDependency
from healthscope.schemas.hospitals import Hospital, HospitalDataSource, HospitalPage

CMS_SOURCE_NAME = "Centers for Medicare & Medicaid Services"
CMS_HOSPITAL_DATASET_NAME = "Hospital General Information"


class CMSClientError(Exception):
    """Base exception for failures while querying CMS."""


class CMSUpstreamError(CMSClientError):
    """CMS could not be reached or returned an unsuccessful status."""


class CMSUpstreamTimeoutError(CMSClientError):
    """CMS did not respond within the configured deadline."""


class CMSDataError(CMSClientError):
    """CMS returned data that did not match the documented contract."""


class _CMSHospital(BaseModel):
    """Validated subset of a raw CMS hospital record."""

    model_config = ConfigDict(extra="ignore")

    facility_id: str = Field(min_length=1)
    facility_name: str = Field(min_length=1)
    address: str
    citytown: str
    state: str = Field(pattern=r"^[A-Z]{2}$")
    zip_code: str
    countyparish: str
    telephone_number: str
    hospital_type: str
    hospital_ownership: str
    emergency_services: Literal["Yes", "No"]
    meets_criteria_for_birthing_friendly_designation: Literal["Y", "N", ""]
    hospital_overall_rating: int | None = Field(ge=1, le=5)

    @field_validator("hospital_overall_rating", mode="before")
    @classmethod
    def parse_overall_rating(cls, value: object) -> object:
        """Normalize CMS missing-value strings while preserving valid ratings."""

        if value in {"", "Not Available", None}:
            return None
        return value

    def to_public(self) -> Hospital:
        """Map CMS field names and codes to the stable public API schema."""

        designation = self.meets_criteria_for_birthing_friendly_designation
        return Hospital(
            facility_id=self.facility_id,
            facility_name=self.facility_name,
            address=self.address,
            city=self.citytown,
            state=self.state,
            zip_code=self.zip_code,
            county=self.countyparish,
            telephone=self.telephone_number,
            hospital_type=self.hospital_type,
            ownership=self.hospital_ownership,
            emergency_services=self.emergency_services == "Yes",
            birthing_friendly=None if designation == "" else designation == "Y",
            overall_rating=self.hospital_overall_rating,
        )


class _CMSHospitalPayload(BaseModel):
    """Validated envelope returned by the CMS datastore query API."""

    results: list[_CMSHospital]
    count: int = Field(ge=0)


class CMSClient:
    """Retrieve current hospital records from the public CMS API."""

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
        self._client: httpx.AsyncClient | None = None

    def _build_http_client(self) -> httpx.AsyncClient:
        """Build an HTTP client with the CMS transport policy."""

        return httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            headers={"User-Agent": "HealthScope/0.1"},
        )

    async def __aenter__(self) -> "CMSClient":
        """Keep one connection pool open across a multi-page workflow."""

        if self._client is None:
            self._client = self._build_http_client()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """Close the workflow-scoped connection pool."""

        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_hospitals(self, *, limit: int, offset: int) -> HospitalPage:
        """Fetch and validate one page of CMS Hospital General Information."""

        url = f"{self._base_url}/datastore/query/{self._dataset_id}/0"
        params: dict[str, str | int] = {
            "limit": limit,
            "offset": offset,
            "count": "true",
            "results": "true",
            "format": "json",
        }
        try:
            if self._client is None:
                async with self._build_http_client() as client:
                    response = await client.get(url, params=params)
            else:
                response = await self._client.get(url, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise CMSUpstreamTimeoutError from exc
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise CMSUpstreamError from exc

        try:
            payload = _CMSHospitalPayload.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise CMSDataError from exc

        return HospitalPage(
            items=[record.to_public() for record in payload.results],
            total=payload.count,
            limit=limit,
            offset=offset,
            source=HospitalDataSource(
                name=CMS_SOURCE_NAME,
                dataset_name=CMS_HOSPITAL_DATASET_NAME,
                dataset_url=f"https://data.cms.gov/provider-data/dataset/{self._dataset_id}",
                retrieved_at=datetime.now(UTC),
            ),
        )


def get_cms_client(settings: SettingsDependency) -> CMSClient:
    """Build a request-scoped CMS client from application settings."""

    return CMSClient(
        base_url=settings.cms_provider_data_base_url,
        dataset_id=settings.cms_hospital_dataset_id,
        timeout_seconds=settings.cms_request_timeout_seconds,
    )


CMSClientDependency = Annotated[CMSClient, Depends(get_cms_client)]
