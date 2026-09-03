"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

UNSAFE_PRODUCTION_DATABASE_PASSWORDS = frozenset(
    {
        "changeme",
        "healthscope-local-only",
        "password",
        "placeholder",
        "postgres",
        "replace-with-a-secret",
        "secret",
    }
)
SECURE_PRODUCTION_DATABASE_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})


class Settings(BaseSettings):
    """Runtime settings for the HealthScope API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HEALTHSCOPE_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "HealthScope"
    environment: str = Field(default="development", pattern=r"^[a-z][a-z0-9_-]*$")
    release_sha: str = Field(default="development", pattern=r"^(?:development|[0-9a-f]{40})$")
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
    fda_api_base_url: str = Field(default="https://api.fda.gov", pattern=r"^https://")
    fda_request_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    fda_request_max_attempts: int = Field(default=3, ge=1, le=10)
    fda_request_retry_delay_seconds: float = Field(default=0.5, ge=0, le=60)
    fda_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_production_safety(self) -> Self:
        """Reject unsafe production-only settings before any work starts."""

        if self.environment != "production":
            return self
        if self.debug:
            raise ValueError("HEALTHSCOPE_DEBUG must be false in production")
        if self.release_sha == "development":
            raise ValueError(
                "HEALTHSCOPE_RELEASE_SHA must identify the full source commit in production"
            )

        try:
            database_url = make_url(self.database_url)
        except ArgumentError as exc:
            raise ValueError(
                "HEALTHSCOPE_DATABASE_URL must be a valid SQLAlchemy database URL"
            ) from exc

        if database_url.get_backend_name() != "postgresql":
            raise ValueError("HEALTHSCOPE_DATABASE_URL must use PostgreSQL in production")

        ssl_mode = database_url.query.get("sslmode")
        if not isinstance(ssl_mode, str) or ssl_mode.lower() not in (
            SECURE_PRODUCTION_DATABASE_SSL_MODES
        ):
            raise ValueError(
                "HEALTHSCOPE_DATABASE_URL must require TLS with sslmode=require, "
                "sslmode=verify-ca, or sslmode=verify-full in production"
            )

        password = database_url.password
        if (
            password is not None
            and password.strip().lower() in UNSAFE_PRODUCTION_DATABASE_PASSWORDS
        ):
            raise ValueError(
                "HEALTHSCOPE_DATABASE_URL contains an unsafe placeholder or default password"
            )

        host = database_url.host
        if host is not None and (
            host.lower() == "example.com" or host.lower().endswith(".example.com")
        ):
            raise ValueError("HEALTHSCOPE_DATABASE_URL contains a placeholder database host")

        return self


@lru_cache
def get_settings() -> Settings:
    """Return the cached process-wide application settings."""

    return Settings()
