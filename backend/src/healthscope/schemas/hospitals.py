"""Public hospital response models."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class Hospital(BaseModel):
    """Selected CMS attributes for a Medicare-registered hospital."""

    model_config = ConfigDict(frozen=True)

    facility_id: str
    facility_name: str
    address: str
    city: str
    state: str = Field(pattern=r"^[A-Z]{2}$")
    zip_code: str
    county: str
    telephone: str
    hospital_type: str
    ownership: str
    emergency_services: bool
    birthing_friendly: bool | None
    overall_rating: int | None = Field(ge=1, le=5)


class HospitalDataSource(BaseModel):
    """Provenance for a hospital page returned by HealthScope."""

    model_config = ConfigDict(frozen=True)

    name: str
    dataset_name: str
    dataset_url: str
    retrieved_at: datetime


class HospitalPage(BaseModel):
    """A bounded page of live CMS hospital records."""

    model_config = ConfigDict(frozen=True)

    items: list[Hospital]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    source: HospitalDataSource


class HospitalStateCoverage(BaseModel):
    """Hospital count for one state or territory in a completed snapshot."""

    model_config = ConfigDict(frozen=True)

    state: str = Field(pattern=r"^[A-Z]{2}$")
    hospital_count: int = Field(ge=0)


class HospitalSnapshotStatus(BaseModel):
    """Metadata and geographic coverage for a completed hospital snapshot."""

    model_config = ConfigDict(frozen=True)

    source_dataset_id: str
    snapshot_date: date
    retrieved_at: datetime
    completed_at: datetime
    record_count: int = Field(ge=0)
    state_count: int = Field(ge=0)
    state_coverage: list[HospitalStateCoverage]
