"""Typed client for FDA drug recall enforcement reports."""

import asyncio
from datetime import UTC, date, datetime
from itertools import pairwise
from typing import Annotated

import httpx
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from healthscope.api.dependencies import SettingsDependency
from healthscope.schemas.drug_recalls import (
    DrugRecall,
    DrugRecallDataSource,
    DrugRecallPage,
    RecallClassification,
    RecallRecordClassification,
    RecallStatus,
)

FDA_SOURCE_NAME = "U.S. Food and Drug Administration"
FDA_DRUG_RECALL_DATASET_NAME = "Drug Recall Enforcement Reports"
FDA_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class FDAClientError(Exception):
    """Base exception for failures while querying FDA data."""


class FDAUpstreamError(FDAClientError):
    """FDA data could not be reached or returned an unsuccessful status."""


class FDAUpstreamTimeoutError(FDAClientError):
    """FDA data did not respond within the configured deadline."""


class FDADataError(FDAClientError):
    """FDA returned data that did not match the documented contract."""


def _parse_optional_text(value: object) -> object:
    """Normalize openFDA's missing-value sentinels for optional fields."""

    if value in {None, "", "N/A"}:
        return None
    return value


class _FDARecall(BaseModel):
    """Validated subset of an FDA recall enforcement report."""

    model_config = ConfigDict(extra="ignore")

    recall_number: str | None = Field(min_length=1)
    event_id: str | None = Field(default=None, pattern=r"^\d+$")
    classification: RecallRecordClassification
    status: RecallStatus | None = None
    recalling_firm: str = Field(min_length=1)
    city: str | None = None
    state: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    country: str | None = None
    product_type: str = Field(pattern=r"^Drugs$")
    product_description: str = Field(min_length=1)
    reason_for_recall: str = Field(min_length=1)
    voluntary_mandated: str | None = None
    distribution_pattern: str = Field(min_length=1)
    product_quantity: str | None = None
    recall_initiation_date: date | None = None
    report_date: date

    @field_validator(
        "event_id",
        "recall_number",
        "city",
        "state",
        "country",
        "voluntary_mandated",
        "product_quantity",
        mode="before",
    )
    @classmethod
    def parse_optional_text(cls, value: object) -> object:
        """Map blank optional fields in legacy FDA reports to null."""

        return _parse_optional_text(value)

    @field_validator("recall_initiation_date", mode="before")
    @classmethod
    def parse_optional_date(cls, value: object) -> object:
        """Parse an optional FDA compact date."""

        if value in {None, ""}:
            return None
        if not isinstance(value, str):
            return value
        return datetime.strptime(value, "%Y%m%d").date()

    @field_validator("report_date", mode="before")
    @classmethod
    def parse_report_date(cls, value: object) -> object:
        """Parse the required FDA compact report date."""

        if not isinstance(value, str):
            return value
        return datetime.strptime(value, "%Y%m%d").date()

    def to_public(self) -> DrugRecall:
        """Map FDA field names to the stable public API schema."""

        return DrugRecall(**self.model_dump(exclude={"product_type"}))


class _FDAPageMetadata(BaseModel):
    """Pagination metadata included in an FDA search response."""

    skip: int = Field(ge=0)
    limit: int = Field(ge=1, le=1000)
    total: int = Field(ge=0)


class _FDAMetadata(BaseModel):
    """Source and pagination metadata included by openFDA."""

    disclaimer: str = Field(min_length=1)
    terms: str = Field(pattern=r"^https://")
    license: str = Field(pattern=r"^https://")
    last_updated: date
    results: _FDAPageMetadata


class _FDAEnvelope(BaseModel):
    """Validated openFDA search envelope."""

    meta: _FDAMetadata
    results: list[_FDARecall]


class FDAClient:
    """Retrieve current drug recall enforcement reports from openFDA."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.5,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._api_key = api_key
        self._transport = transport

    def _build_http_client(self) -> httpx.AsyncClient:
        """Build an HTTP client with the FDA transport policy."""

        return httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            headers={"User-Agent": "HealthScope/0.1"},
        )

    async def _get_with_retries(
        self,
        client: httpx.AsyncClient,
        *,
        url: str,
        params: dict[str, str | int],
    ) -> httpx.Response:
        """Retry only failures that can reasonably recover without caller action."""

        retry_delay_seconds = self._retry_delay_seconds
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response
            except httpx.TimeoutException as exc:
                if attempt == self._max_attempts:
                    raise FDAUpstreamTimeoutError from exc
            except httpx.HTTPStatusError as exc:
                if (
                    attempt == self._max_attempts
                    or exc.response.status_code not in FDA_TRANSIENT_STATUS_CODES
                ):
                    raise FDAUpstreamError from exc
            except httpx.RequestError as exc:
                if attempt == self._max_attempts:
                    raise FDAUpstreamError from exc

            await asyncio.sleep(retry_delay_seconds)
            retry_delay_seconds *= 2

        raise AssertionError("FDA retry loop exhausted without returning or raising")

    async def fetch_drug_recalls(
        self,
        *,
        limit: int,
        offset: int,
        classification: RecallClassification | None,
    ) -> DrugRecallPage:
        """Fetch and validate one newest-first page of FDA drug recalls."""

        url = f"{self._base_url}/drug/enforcement.json"
        params: dict[str, str | int] = {
            "limit": limit,
            "skip": offset,
            "sort": "report_date:desc",
        }
        if classification is not None:
            params["search"] = f'classification:"{classification}"'
        if self._api_key is not None:
            params["api_key"] = self._api_key

        async with self._build_http_client() as client:
            response = await self._get_with_retries(client, url=url, params=params)

        try:
            payload = _FDAEnvelope.model_validate(response.json())
        except (TypeError, ValueError, ValidationError) as exc:
            raise FDADataError from exc

        records = payload.results
        metadata = payload.meta.results
        record_keys = [
            ("recall", record.recall_number)
            if record.recall_number is not None
            else (
                "pending",
                record.event_id,
                record.product_description,
                record.report_date,
            )
            for record in records
        ]
        if metadata.skip != offset or metadata.limit != limit:
            raise FDADataError("FDA returned inconsistent pagination metadata")
        if not records or len(records) > limit or offset + len(records) > metadata.total:
            raise FDADataError("FDA returned an inconsistent recall page")
        if len(record_keys) != len(set(record_keys)):
            raise FDADataError("FDA returned duplicate recall records")
        if classification is not None and any(
            record.classification != classification for record in records
        ):
            raise FDADataError("FDA returned records outside the requested classification")
        if any(
            previous.report_date < current.report_date for previous, current in pairwise(records)
        ):
            raise FDADataError("FDA returned records outside newest-first order")

        return DrugRecallPage(
            items=[record.to_public() for record in records],
            total=metadata.total,
            limit=limit,
            offset=offset,
            classification=classification,
            source=DrugRecallDataSource(
                name=FDA_SOURCE_NAME,
                dataset_name=FDA_DRUG_RECALL_DATASET_NAME,
                dataset_url=url,
                retrieved_at=datetime.now(UTC),
                last_updated=payload.meta.last_updated,
                disclaimer=payload.meta.disclaimer,
                terms_url=payload.meta.terms,
                license_url=payload.meta.license,
            ),
        )


def get_fda_client(settings: SettingsDependency) -> FDAClient:
    """Build a request-scoped FDA client from application settings."""

    api_key = settings.fda_api_key.get_secret_value() if settings.fda_api_key is not None else None
    return FDAClient(
        base_url=settings.fda_api_base_url,
        timeout_seconds=settings.fda_request_timeout_seconds,
        max_attempts=settings.fda_request_max_attempts,
        retry_delay_seconds=settings.fda_request_retry_delay_seconds,
        api_key=api_key,
    )


FDAClientDependency = Annotated[FDAClient, Depends(get_fda_client)]
