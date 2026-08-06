"""Tests for environment-specific application configuration safety."""

import pytest
from pydantic import ValidationError

from healthscope.config import Settings

PRODUCTION_DATABASE_URL = (
    "postgresql+psycopg://healthscope:unique-production-value@db.internal:5432/healthscope"
)


def test_production_settings_accept_safe_postgresql_configuration() -> None:
    settings = Settings(environment="production", database_url=PRODUCTION_DATABASE_URL)

    assert settings.environment == "production"
    assert settings.debug is False
    assert settings.database_url == PRODUCTION_DATABASE_URL


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"debug": True}, "HEALTHSCOPE_DEBUG must be false"),
        ({"database_url": "sqlite:///healthscope.db"}, "must use PostgreSQL"),
        (
            {
                "database_url": (
                    "postgresql+psycopg://healthscope:healthscope-local-only@db.internal/healthscope"
                )
            },
            "unsafe placeholder or default password",
        ),
        (
            {
                "database_url": (
                    "postgresql+psycopg://healthscope:safe-value@database.example.com/healthscope"
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
        Settings(environment="production", **overrides)


def test_non_production_settings_keep_local_test_database_support() -> None:
    settings = Settings(environment="test", debug=True, database_url="sqlite://")

    assert settings.debug is True
    assert settings.database_url == "sqlite://"


def test_production_validation_error_hides_database_credential() -> None:
    secret_value = "replace-with-a-secret"

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            environment="production",
            database_url=(
                f"postgresql+psycopg://healthscope:{secret_value}@db.internal/healthscope"
            ),
        )

    assert secret_value not in str(exc_info.value)
    assert "unsafe placeholder or default password" in str(exc_info.value)
