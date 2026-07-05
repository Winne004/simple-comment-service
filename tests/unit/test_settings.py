"""Settings classes read the environment; each covers one bounded concern."""

import pytest

from comments.settings import (
    DatabaseSettings,
    ObservabilitySettings,
    get_database_settings,
    get_observability_settings,
    reset_settings,
)


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Isolate each test from settings cached by other tests, and vice versa."""
    reset_settings()
    yield
    reset_settings()


def test_database_settings_read_table_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TABLE_NAME", "MyTable")
    settings = DatabaseSettings()  # ty: ignore[missing-argument]
    assert settings.table_name == "MyTable"


def test_database_settings_require_table_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TABLE_NAME", raising=False)
    with pytest.raises(ValueError):
        DatabaseSettings()  # ty: ignore[missing-argument]


def test_observability_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POWERTOOLS_SERVICE_NAME", raising=False)
    monkeypatch.delenv("POWERTOOLS_METRICS_NAMESPACE", raising=False)
    settings = ObservabilitySettings()
    assert settings.service_name == "comments"
    assert settings.metrics_namespace == "SimpleCommentService"


def test_observability_settings_read_powertools_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "svc")
    monkeypatch.setenv("POWERTOOLS_METRICS_NAMESPACE", "Ns")
    settings = ObservabilitySettings()
    assert settings.service_name == "svc"
    assert settings.metrics_namespace == "Ns"


def test_getters_cache_and_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TABLE_NAME", "First")
    assert get_database_settings() is get_database_settings()
    assert get_observability_settings() is get_observability_settings()

    monkeypatch.setenv("TABLE_NAME", "Second")
    assert get_database_settings().table_name == "First"  # still cached
    reset_settings()
    assert get_database_settings().table_name == "Second"
