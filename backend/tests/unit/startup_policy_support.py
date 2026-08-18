from __future__ import annotations

import stat
from collections.abc import Iterator
from importlib import resources
from pathlib import Path

import pytest

from app.core.config import AppEnvironment, Settings

_POLICY_RESOURCE_PACKAGE = "app.ai.artifacts.cr011_v1"
_POLICY_RESOURCE_NAME = "ai-policy-v1.positive.json"

_STARTUP_SETTINGS: dict[str, object] = {
    "ai_provider_calls_enabled": False,
    "secret_key": "test-signing-key-with-at-least-32-characters",
    "database_url": "postgresql+psycopg://test:test-password@postgresql:5432/test",
    "redis_url": "redis://:test-password@redis:6379/0",
    "celery_broker_url": "redis://:test-password@redis:6379/0",
    "celery_result_backend": "redis://:test-password@redis:6379/1",
    "minio_access_key": "test-minio-access",
    "minio_secret_key": "test-minio-secret",
    "qdrant_collection": "finaudit_policy_chunks_test_e1024_v1",
    "llm_base_url": "http://synthetic-extraction:8000/v1",
    "llm_api_key": "test-llm-key",
    "llm_extraction_model": "synthetic-extraction-model",
    "llm_generation_model": "synthetic-generation-model",
    "llm_fallback_model": "synthetic-fallback-model",
    "embedding_base_url": "http://synthetic-embedding:8003/v1",
    "embedding_api_key": "test-embedding-key",
    "embedding_model": "synthetic-embedding-model",
    "metrics_internal_token": "test-metrics-token",
}


def _environment_value(environment: AppEnvironment | str) -> str:
    return environment.value if isinstance(environment, AppEnvironment) else environment


def startup_settings_values(
    policy_file: Path,
    *,
    environment: AppEnvironment | str = AppEnvironment.TEST,
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    environment_value = _environment_value(environment)
    values = _STARTUP_SETTINGS | {
        "app_env": environment_value,
        "ai_policy_file": str(policy_file.resolve()),
    }
    if environment_value == AppEnvironment.PROD.value:
        values |= {
            "minio_endpoint": "https://minio.example.test:9000",
            "minio_secure": True,
            "scanner_provider": "clamav_instream",
            "scanner_host": "scanner.example.test",
        }
    return values | (overrides or {})


def build_startup_settings(
    policy_file: Path,
    *,
    environment: AppEnvironment | str = AppEnvironment.TEST,
    **overrides: object,
) -> Settings:
    return Settings(
        _env_file=None,
        **startup_settings_values(
            policy_file,
            environment=environment,
            overrides=overrides,
        ),
    )


def install_startup_environment(
    monkeypatch: pytest.MonkeyPatch,
    policy_file: Path,
    *,
    environment: AppEnvironment | str = AppEnvironment.TEST,
) -> None:
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    for field, value in startup_settings_values(
        policy_file,
        environment=environment,
    ).items():
        monkeypatch.setenv(field.upper(), str(value))
    monkeypatch.setenv("AUTH_PUBLIC_ORIGIN", "https://testserver")


@pytest.fixture(name="exact_policy_file")
def _exact_policy_file(tmp_path: Path) -> Iterator[Path]:
    raw_policy = (
        resources.files(_POLICY_RESOURCE_PACKAGE).joinpath(_POLICY_RESOURCE_NAME).read_bytes()
    )
    policy_file = tmp_path / _POLICY_RESOURCE_NAME
    policy_file.write_bytes(raw_policy)
    policy_file.chmod(stat.S_IREAD)
    try:
        yield policy_file.resolve()
    finally:
        if policy_file.exists():
            policy_file.chmod(stat.S_IREAD | stat.S_IWRITE)
