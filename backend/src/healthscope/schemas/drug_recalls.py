"""Public FDA drug recall enforcement response models."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RecallClassification = Literal["Class I", "Class II", "Class III"]
RecallRecordClassification = Literal["Class I", "Class II", "Class III", "Not Yet Classified"]
RecallStatus = Literal["Ongoing", "Completed", "Terminated"]
OPENFDA_MAX_SKIP = 25_000


class DrugRecall(BaseModel):
    """One publicly releasable FDA drug recall enforcement report."""

    model_config = ConfigDict(frozen=True)

    recall_number: str | None
    event_id: str | None
    classification: RecallRecordClassification
    status: RecallStatus | None
    recalling_firm: str
    city: str | None
    state: str | None = Field(pattern=r"^[A-Z]{2}$")
    country: str | None
    product_description: str
    reason_for_recall: str
    voluntary_mandated: str | None
    distribution_pattern: str
    product_quantity: str | None
    recall_initiation_date: date | None
    report_date: date


class DrugRecallDataSource(BaseModel):
    """Provenance and use constraints for an openFDA response."""

    model_config = ConfigDict(frozen=True)

    name: str
    dataset_name: str
    dataset_url: str
    retrieved_at: datetime
    last_updated: date
    disclaimer: str
    terms_url: str
    license_url: str


class DrugRecallPage(BaseModel):
    """A bounded page of live FDA drug recall enforcement reports."""

    model_config = ConfigDict(frozen=True)

    items: list[DrugRecall]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0, le=OPENFDA_MAX_SKIP)
    classification: RecallClassification | None
    source: DrugRecallDataSource
