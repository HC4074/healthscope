"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the HealthScope API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HEALTHSCOPE_",
        extra="ignore",
    )

    app_name: str = "HealthScope"
    environment: str = Field(default="development", pattern=r"^[a-z][a-z0-9_-]*$")
    api_prefix: str = "/api/v1"
    debug: bool = False
    database_url: str = (
        "postgresql+psycopg://healthscope:healthscope-local-only@localhost:5432/healthscope"
    )
    cms_provider_data_base_url: str = Field(
        default="https://data.cms.gov/provider-data/api/1",
        pattern=r"^https://",
    )
    cms_hospital_dataset_id: str = Field(default="xubh-q36u", pattern=r"^[a-z0-9]+-[a-z0-9]+$")
    cms_request_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    cms_ingestion_page_size: int = Field(default=100, ge=1, le=100)
    cms_ingestion_max_attempts: int = Field(default=3, ge=1, le=10)
    cms_ingestion_retry_delay_seconds: float = Field(default=1.0, ge=0, le=60)
    cms_ingestion_stale_after_hours: int = Field(default=26, ge=1, le=168)
    cdc_data_base_url: str = Field(default="https://data.cdc.gov", pattern=r"^https://")
    cdc_places_county_dataset_id: str = Field(default="swc5-untb", pattern=r"^[a-z0-9]+-[a-z0-9]+$")
    cdc_request_timeout_seconds: float = Field(default=10.0, gt=0, le=30)


@lru_cache
def get_settings() -> Settings:
    """Return the cached process-wide application settings."""

    return Settings()
