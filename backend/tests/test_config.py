"""Tests for environment-specific application configuration safety."""

import pytest
from pydantic import ValidationError

from healthscope.config import Settings

PRODUCTION_DATABASE_URL = (
    "postgresql+psycopg://healthscope:unique-production-value@db.internal:5432/healthscope"
    "?sslmode=require"
)
RELEASE_SHA = "0123456789abcdef0123456789abcdef01234567"


def test_production_settings_accept_safe_postgresql_configuration() -> None:
    settings = Settings(
        environment="production",
        release_sha=RELEASE_SHA,
        database_url=PRODUCTION_DATABASE_URL,
    )

    assert settings.environment == "production"
    assert settings.debug is False
    assert settings.database_url == PRODUCTION_DATABASE_URL


@pytest.mark.parametrize("ssl_mode", ["require", "verify-ca", "verify-full"])
def test_production_settings_accept_tls_required_postgresql_modes(ssl_mode: str) -> None:
    database_url = (
        "postgresql+psycopg://healthscope:unique-production-value@db.internal/healthscope"
        f"?sslmode={ssl_mode}"
    )

    settings = Settings(
        environment="production",
        release_sha=RELEASE_SHA,
        database_url=database_url,
    )

    assert settings.database_url == database_url


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"release_sha": "development"}, "must identify the full source commit"),
        ({"debug": True}, "HEALTHSCOPE_DEBUG must be false"),
        ({"database_url": "sqlite:///healthscope.db"}, "must use PostgreSQL"),
        (
            {
                "database_url": (
                    "postgresql+psycopg://healthscope:unique-production-value@db.internal/"
                    "healthscope"
                )
            },
            "must require TLS",
        ),
        (
            {
                "database_url": (
                    "postgresql+psycopg://healthscope:unique-production-value@db.internal/"
                    "healthscope?sslmode=prefer"
                )
            },
            "must require TLS",
        ),
        (
            {
                "database_url": (
                    "postgresql+psycopg://healthscope:unique-production-value@db.internal/"
                    "healthscope?sslmode=require&sslmode=disable"
                )
            },
            "must require TLS",
        ),
        (
            {
                "database_url": (
                    "postgresql+psycopg://healthscope:healthscope-local-only@db.internal/healthscope"
                    "?sslmode=require"
                )
            },
            "unsafe placeholder or default password",
        ),
        (
            {
                "database_url": (
                    "postgresql+psycopg://healthscope:safe-value@database.example.com/healthscope"
                    "?sslmode=require"
                )
            },
            "placeholder database host",
        ),
        ({"database_url": "not a database URL"}, "valid SQLAlchemy database URL"),
    ],
)
def test_production_settings_reject_unsafe_configuration(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(environment="production", **({"release_sha": RELEASE_SHA} | overrides))


def test_non_production_settings_keep_local_test_database_support() -> None:
    settings = Settings(environment="test", debug=True, database_url="sqlite://")

    assert settings.debug is True
    assert settings.database_url == "sqlite://"


@pytest.mark.parametrize("release_sha", ["short", "A" * 40, "0" * 39, "0" * 41])
def test_settings_reject_malformed_release_sha(release_sha: str) -> None:
    with pytest.raises(ValidationError, match="release_sha"):
        Settings(environment="test", release_sha=release_sha)


def test_production_validation_error_hides_database_credential() -> None:
    secret_value = "replace-with-a-secret"

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            environment="production",
            release_sha=RELEASE_SHA,
            database_url=(
                f"postgresql+psycopg://healthscope:{secret_value}@db.internal/healthscope"
                "?sslmode=require"
            ),
        )

    assert secret_value not in str(exc_info.value)
    assert "unsafe placeholder or default password" in str(exc_info.value)
