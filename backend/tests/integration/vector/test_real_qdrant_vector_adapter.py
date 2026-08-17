from __future__ import annotations

import os
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest

from app.adapters.qdrant_vector import QdrantPoint, QdrantVectorAdapter
from app.core.config import Settings

pytestmark = pytest.mark.integration

GATE_ENV = "FINAUDIT_LOCAL_QDRANT_ADAPTER_INTEGRATION"
GATE_VALUE = "VERIFY_SYNTHETIC_QDRANT_V1"
QDRANT_URL_ENV = "TEST_QDRANT_URL"
QDRANT_API_KEY_ENV = "TEST_QDRANT_API_KEY"
POINT_ID = UUID("3439482d-ab01-4b67-9e5b-b9785457b3f5")
BLOCKED_POINT_ID = UUID("8177c86a-a34f-4a42-bc70-e105c46806df")


def _load_settings(collection_name: str) -> Settings:
    gate = os.environ.get(GATE_ENV)
    if gate is None:
        pytest.skip("real local Qdrant adapter integration is explicitly opt-in")
    if gate != GATE_VALUE:
        pytest.fail("local Qdrant adapter integration confirmation is invalid", pytrace=False)
    qdrant_url = os.environ.get(QDRANT_URL_ENV)
    if qdrant_url is None:
        pytest.fail(f"local Qdrant gate requires {QDRANT_URL_ENV}", pytrace=False)
    parsed_url = urlsplit(qdrant_url)
    if (
        parsed_url.scheme != "http"
        or parsed_url.hostname != "127.0.0.1"
        or parsed_url.port is None
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.path not in {"", "/"}
        or parsed_url.query
        or parsed_url.fragment
    ):
        pytest.fail("local Qdrant adapter integration profile is unsafe", pytrace=False)
    api_key = os.environ.get(QDRANT_API_KEY_ENV)
    settings_data: dict[str, object] = {
        "app_env": "test",
        "secret_key": "synthetic-local-integration-signing-key",
        "database_url": "postgresql+psycopg://synthetic:synthetic@127.0.0.1/finaudit_unused",
        "redis_url": "redis://:synthetic@127.0.0.1:6379/0",
        "celery_broker_url": "redis://:synthetic@127.0.0.1:6379/0",
        "celery_result_backend": "redis://:synthetic@127.0.0.1:6379/1",
        "minio_access_key": "synthetic-minio-access",
        "minio_secret_key": "synthetic-minio-secret",
        "qdrant_url": qdrant_url,
        "qdrant_collection": collection_name,
        "qdrant_vector_size": 3,
        "embedding_vector_size": 3,
        "ai_policy_file": "D:\\synthetic\\ai-policy-v1.json",
        "llm_api_key": "synthetic-local-integration-llm",
        "llm_extraction_model": "synthetic-extraction-model",
        "llm_generation_model": "synthetic-generation-model",
        "embedding_base_url": "http://127.0.0.1:8000/v1",
        "embedding_api_key": "synthetic-local-integration-embedding",
        "embedding_model": "synthetic-embedding-model",
        "metrics_internal_token": "synthetic-local-integration-metrics",
    }
    if api_key is not None:
        settings_data["qdrant_api_key"] = api_key
    return Settings(_env_file=None, **settings_data)


def test_real_qdrant_round_trip_keeps_disallowed_points_out() -> None:
    collection_name = f"finaudit_adapter_integration_{uuid4().hex}"
    settings = _load_settings(collection_name)
    api_key = settings.qdrant_api_key
    headers = {} if api_key is None else {"api-key": api_key.get_secret_value()}
    admin_client = httpx.Client(
        base_url=settings.qdrant_url,
        headers=headers,
        timeout=10.0,
        trust_env=False,
    )
    create_response = admin_client.put(
        f"/collections/{collection_name}",
        json={"vectors": {"size": 3, "distance": "Cosine"}},
    )
    assert create_response.status_code == 200
    adapter = QdrantVectorAdapter(settings)
    try:
        adapter.verify_collection()
        adapter.upsert(
            (
                QdrantPoint(
                    id=POINT_ID,
                    vector=(1.0, 0.0, 0.0),
                    payload={"document_id": "allowed"},
                ),
                QdrantPoint(
                    id=BLOCKED_POINT_ID,
                    vector=(1.0, 0.0, 0.0),
                    payload={"document_id": "blocked"},
                ),
            )
        )
        stored = adapter.retrieve((BLOCKED_POINT_ID, POINT_ID))
        assert tuple(point.id for point in stored) == (BLOCKED_POINT_ID, POINT_ID)
        assert tuple(point.vector for point in stored) == (
            (1.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
        )
        assert tuple(point.payload for point in stored) == (
            {"document_id": "blocked"},
            {"document_id": "allowed"},
        )

        hits = adapter.query_authorized(
            (1.0, 0.0, 0.0),
            allowed_point_ids=(POINT_ID,),
            limit=10,
        )

        assert tuple(hit.id for hit in hits) == (POINT_ID,)
        assert hits[0].payload == {"document_id": "allowed"}
        adapter.delete((POINT_ID, BLOCKED_POINT_ID))
        assert (
            adapter.query_authorized(
                (1.0, 0.0, 0.0),
                allowed_point_ids=(POINT_ID, BLOCKED_POINT_ID),
                limit=10,
            )
            == ()
        )
    finally:
        adapter.close()
        delete_response = admin_client.delete(f"/collections/{collection_name}")
        admin_client.close()
        assert delete_response.status_code == 200
