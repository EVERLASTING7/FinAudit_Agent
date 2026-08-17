from __future__ import annotations

import inspect
import json
import math
from collections.abc import Callable
from typing import cast
from uuid import UUID

import httpx
import pytest

from app.adapters.qdrant_vector import (
    JsonValue,
    QdrantPoint,
    QdrantVectorAdapter,
    QdrantVectorStoreError,
)
from app.core.config import Settings

POINT_ID = UUID("bf00ad70-cb62-4bd7-a296-a1249857594f")
OTHER_POINT_ID = UUID("a08b05e0-a4c5-497a-bc55-f800a646e163")
API_KEY = "qdrant-test-api-key"


def build_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "secret_key": "test-signing-key-with-at-least-32-characters",
        "database_url": "postgresql+psycopg://test:test-password@postgresql:5432/test",
        "redis_url": "redis://:test-password@redis:6379/0",
        "celery_broker_url": "redis://:test-password@redis:6379/0",
        "celery_result_backend": "redis://:test-password@redis:6379/1",
        "minio_access_key": "test-minio-access",
        "minio_secret_key": "test-minio-secret",
        "qdrant_url": "http://qdrant:6333",
        "qdrant_api_key": API_KEY,
        "qdrant_collection": "existing_test_collection",
        "qdrant_vector_size": 3,
        "embedding_vector_size": 3,
        "ai_policy_file": "D:\\synthetic\\ai-policy-v1.json",
        "llm_api_key": "test-llm-key",
        "llm_extraction_model": "test-extraction-model",
        "llm_generation_model": "test-generation-model",
        "embedding_base_url": "http://embedding:8000/v1",
        "embedding_api_key": "test-embedding-key",
        "embedding_model": "test-embedding-model",
        "metrics_internal_token": "test-metrics-token",
    }
    return Settings(_env_file=None, **(values | overrides))


def collection_response(
    *, status: str = "green", vectors: object | None = None
) -> dict[str, object]:
    vector_config = {"size": 3, "distance": "Cosine"} if vectors is None else vectors
    return {
        "result": {
            "status": status,
            "config": {"params": {"vectors": vector_config}},
        },
        "status": "ok",
        "time": 0.001,
    }


def build_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_public_surface_cannot_create_or_enumerate_collections() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(QdrantVectorAdapter, inspect.isfunction)
        if not name.startswith("_")
    }

    assert public_methods == {
        "close",
        "delete",
        "query_authorized",
        "retrieve",
        "upsert",
        "verify_collection",
    }


def test_real_protocol_shape_and_authorized_filter_are_enforced() -> None:
    requests: list[tuple[str, str, dict[str, object] | None, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] | None = None
        if request.content:
            decoded: object = json.loads(request.content)
            assert type(decoded) is dict
            body = decoded
        requests.append((request.method, str(request.url), body, request.headers.get("api-key")))
        if request.method == "GET":
            return httpx.Response(200, json=collection_response())
        if request.method == "PUT":
            return httpx.Response(
                200,
                json={"result": {"operation_id": 1, "status": "completed"}, "status": "ok"},
            )
        if request.url.path.endswith("/points/query"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "points": [
                            {
                                "id": str(POINT_ID),
                                "score": 0.75,
                                "payload": {"document_id": "doc-1"},
                            }
                        ]
                    },
                    "status": "ok",
                },
            )
        return httpx.Response(
            200,
            json={"result": {"operation_id": 2, "status": "completed"}, "status": "ok"},
        )

    client = build_client(handler)
    adapter = QdrantVectorAdapter(build_settings(), client=client)
    adapter.upsert(
        (
            QdrantPoint(
                id=POINT_ID,
                vector=(1.0, 0.0, 0.0),
                payload={"document_id": "doc-1"},
            ),
        )
    )
    hits = adapter.query_authorized(
        (1.0, 0.0, 0.0),
        allowed_point_ids=(POINT_ID, OTHER_POINT_ID),
        limit=5,
    )
    adapter.delete((POINT_ID,))

    assert len(hits) == 1
    assert hits[0].id == POINT_ID
    assert hits[0].score == pytest.approx(0.75)
    assert hits[0].payload == {"document_id": "doc-1"}
    assert [request[0] for request in requests] == ["GET", "PUT", "POST", "POST"]
    assert all(request[3] == API_KEY for request in requests)
    assert requests[0][1] == "http://qdrant:6333/collections/existing_test_collection"
    assert requests[1][1].endswith("/points?wait=true")
    assert requests[1][2] == {
        "points": [
            {
                "id": str(POINT_ID),
                "vector": [1.0, 0.0, 0.0],
                "payload": {"document_id": "doc-1"},
            }
        ]
    }
    assert requests[2][2] == {
        "query": [1.0, 0.0, 0.0],
        "filter": {"must": [{"has_id": [str(POINT_ID), str(OTHER_POINT_ID)]}]},
        "limit": 2,
        "with_payload": True,
        "with_vector": False,
    }
    assert requests[3][1].endswith("/points/delete?wait=true")
    assert requests[3][2] == {"points": [str(POINT_ID)]}


@pytest.mark.parametrize(
    ("response"),
    [
        collection_response(status="yellow"),
        collection_response(vectors={"size": 4, "distance": "Cosine"}),
        collection_response(vectors={"size": 3, "distance": "Dot"}),
        collection_response(vectors={"named": {"size": 3, "distance": "Cosine"}}),
    ],
)
def test_collection_must_be_green_unnamed_and_exactly_compatible(
    response: dict[str, object],
) -> None:
    client = build_client(lambda request: httpx.Response(200, json=response))
    adapter = QdrantVectorAdapter(build_settings(), client=client)

    with pytest.raises(QdrantVectorStoreError):
        adapter.verify_collection()


@pytest.mark.parametrize(
    ("operation"),
    [
        lambda adapter: adapter.upsert(()),
        lambda adapter: adapter.upsert((QdrantPoint(id=POINT_ID, vector=(1.0, 0.0), payload={}),)),
        lambda adapter: adapter.upsert(
            (QdrantPoint(id=POINT_ID, vector=(1.0, math.nan, 0.0), payload={}),)
        ),
        lambda adapter: adapter.upsert(
            (
                QdrantPoint(
                    id=POINT_ID,
                    vector=(1.0, 0.0, 0.0),
                    payload=cast(dict[str, JsonValue], {"bad": object()}),
                ),
            )
        ),
        lambda adapter: adapter.query_authorized((1.0, 0.0, 0.0), allowed_point_ids=(), limit=1),
        lambda adapter: adapter.query_authorized(
            (1.0, 0.0, 0.0), allowed_point_ids=(POINT_ID,), limit=0
        ),
        lambda adapter: adapter.delete((POINT_ID, POINT_ID)),
        lambda adapter: adapter.retrieve((POINT_ID, POINT_ID)),
    ],
)
def test_invalid_inputs_fail_before_network(
    operation: Callable[[QdrantVectorAdapter], object],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=collection_response())

    adapter = QdrantVectorAdapter(build_settings(), client=build_client(handler))

    with pytest.raises(QdrantVectorStoreError):
        operation(adapter)

    assert requests == []


def test_query_rejects_a_service_result_outside_the_authorized_set() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=collection_response())
        return httpx.Response(
            200,
            json={
                "result": {
                    "points": [
                        {"id": str(OTHER_POINT_ID), "score": 0.9, "payload": {"secret": True}}
                    ]
                },
                "status": "ok",
            },
        )


def test_retrieve_preserves_requested_order_and_validates_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=collection_response())
        assert json.loads(request.content) == {
            "ids": [str(POINT_ID), str(OTHER_POINT_ID)],
            "with_payload": True,
            "with_vector": True,
        }
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "id": str(OTHER_POINT_ID),
                        "vector": [0.0, 1.0, 0.0],
                        "payload": {"kind": "second"},
                    },
                    {
                        "id": str(POINT_ID),
                        "vector": [1.0, 0.0, 0.0],
                        "payload": {"kind": "first"},
                    },
                ],
                "status": "ok",
            },
        )

    adapter = QdrantVectorAdapter(build_settings(), client=build_client(handler))

    points = adapter.retrieve((POINT_ID, OTHER_POINT_ID))

    assert tuple(point.id for point in points) == (POINT_ID, OTHER_POINT_ID)
    assert points[0].vector == (1.0, 0.0, 0.0)
    assert points[1].payload == {"kind": "second"}

    adapter = QdrantVectorAdapter(build_settings(), client=build_client(handler))

    with pytest.raises(QdrantVectorStoreError):
        adapter.query_authorized(
            (1.0, 0.0, 0.0),
            allowed_point_ids=(POINT_ID,),
            limit=1,
        )


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(503, text="internal-secret"),
        lambda request: httpx.Response(200, content=b"not-json"),
        lambda request: httpx.Response(200, json={"status": "error", "result": {}}),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("private-host", request=request)),
    ],
)
def test_transport_and_protocol_errors_are_redacted(
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    adapter = QdrantVectorAdapter(build_settings(), client=build_client(handler))

    with pytest.raises(QdrantVectorStoreError) as raised:
        adapter.verify_collection()

    assert str(raised.value) == "qdrant vector store operation failed"
    assert API_KEY not in str(raised.value)
    assert "private-host" not in str(raised.value)


def test_constructor_rejects_unvalidated_settings() -> None:
    forged = Settings.model_construct(qdrant_url="http://qdrant:6333")

    with pytest.raises(TypeError, match="validated Settings are required"):
        QdrantVectorAdapter(forged)
