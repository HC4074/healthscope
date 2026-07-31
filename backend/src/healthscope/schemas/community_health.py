"""Public county-level community health response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CountyHealthEstimate(BaseModel):
    """One CDC PLACES age-adjusted county prevalence estimate."""

    model_config = ConfigDict(frozen=True)

    year: int = Field(ge=2000, le=2100)
    state: str = Field(pattern=r"^[A-Z]{2}$")
    state_name: str
    county: str
    county_fips: str = Field(pattern=r"^\d{5}$")
    measure_id: str = Field(pattern=r"^[A-Z0-9_]{2,32}$")
    measure: str
    category: str
    prevalence_percent: float = Field(ge=0, le=100)
    low_confidence_limit: float = Field(ge=0, le=100)
    high_confidence_limit: float = Field(ge=0, le=100)
    population: int = Field(ge=0)
    adult_population: int = Field(ge=0)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class CommunityHealthDataSource(BaseModel):
    """Provenance for a CDC PLACES county response."""

    model_config = ConfigDict(frozen=True)

    name: str
    dataset_name: str
    dataset_url: str
    retrieved_at: datetime
    estimate_type: str


class CountyHealthPage(BaseModel):
    """A bounded page of live CDC PLACES county estimates."""

    model_config = ConfigDict(frozen=True)

    items: list[CountyHealthEstimate]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    state: str = Field(pattern=r"^[A-Z]{2}$")
    measure_id: str = Field(pattern=r"^[A-Z0-9_]{2,32}$")
    source: CommunityHealthDataSource
