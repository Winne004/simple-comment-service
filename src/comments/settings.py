"""Single configuration location for the service.

Every environment variable the code reads is declared here as a field on a
pydantic-settings class. Each class owns one bounded concern; nothing else in
`src/` reads `os.environ`.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """DynamoDB configuration (env: TABLE_NAME)."""

    model_config = SettingsConfigDict(frozen=True)

    table_name: str


class ObservabilitySettings(BaseSettings):
    """Powertools logger/tracer/metrics configuration (env: POWERTOOLS_*)."""

    model_config = SettingsConfigDict(env_prefix="POWERTOOLS_", frozen=True)

    service_name: str = "comments"
    metrics_namespace: str = "SimpleCommentService"


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    # ty can't see that pydantic-settings fills table_name from the environment.
    return DatabaseSettings()  # ty: ignore[missing-argument]


@lru_cache(maxsize=1)
def get_observability_settings() -> ObservabilitySettings:
    return ObservabilitySettings()


def reset_settings() -> None:
    """Drop cached settings so the next access re-reads the environment (tests)."""
    get_database_settings.cache_clear()
    get_observability_settings.cache_clear()
