from importlib import resources

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from tests.integration.database.test_migrations import (
    assert_disposable_database_marker,
    read_safe_test_database_url,
)


@pytest.mark.integration
def test_runtime_session_executes_read_only_postgresql_query() -> None:
    database_url = read_safe_test_database_url()
    assert_disposable_database_marker(database_url)
    policy_file = resources.files("app.ai.artifacts.cr011_v1").joinpath(
        "ai-policy-v1.positive.json"
    )
    settings = Settings(
        _env_file=None,
        **{
            "app_env": "test",
            "secret_key": "runtime-session-test-signing-key-32-chars",
            "database_url": database_url.render_as_string(hide_password=False),
            "redis_url": "redis://:test-password@redis:6379/0",
            "celery_broker_url": "redis://:test-password@redis:6379/0",
            "celery_result_backend": "redis://:test-password@redis:6379/1",
            "minio_access_key": "test-minio-access",
            "minio_secret_key": "test-minio-secret",
            "qdrant_collection": "finaudit_policy_chunks_test_e1024_v1",
            "ai_policy_file": str(policy_file),
            "llm_api_key": "test-llm-key",
            "llm_extraction_model": "test-extraction-model",
            "llm_generation_model": "test-generation-model",
            "embedding_base_url": "http://embedding:8000/v1",
            "embedding_api_key": "test-embedding-key",
            "embedding_model": "test-embedding-model",
            "metrics_internal_token": "test-metrics-token",
        },
    )
    engine = create_application_engine(settings)
    factory = create_session_factory(engine)

    try:
        with factory.begin() as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1
            assert session.execute(text("SHOW TimeZone")).scalar_one() == "UTC"
    finally:
        engine.dispose()
