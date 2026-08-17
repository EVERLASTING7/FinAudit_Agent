from __future__ import annotations

import hashlib
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from app.adapters.minio_file_runtime import FileStorageError, MinioFileRuntimeAdapter
from app.core.config import Settings


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
        "qdrant_collection": "finaudit_policy_chunks_test_e1024_v1",
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


@dataclass
class _Response:
    payload: bytes
    closed: bool = False
    released: bool = False

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class _Client:
    def __init__(self, objects: dict[tuple[str, str], bytes]) -> None:
        self.objects = objects
        self.copies: list[tuple[str, str, object]] = []
        self.removals: list[tuple[str, str]] = []
        self.responses: list[_Response] = []

    def get_object(self, bucket_name: str, object_name: str) -> _Response:
        response = _Response(self.objects[(bucket_name, object_name)])
        self.responses.append(response)
        return response

    def copy_object(self, bucket_name: str, object_name: str, source: object) -> object:
        self.copies.append((bucket_name, object_name, source))
        self.objects[(bucket_name, object_name)] = self.objects[("quarantine", object_name)]
        return object()

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        self.removals.append((bucket_name, object_name))
        self.objects.pop((bucket_name, object_name), None)


def _adapter(client: _Client) -> MinioFileRuntimeAdapter:
    return MinioFileRuntimeAdapter(
        build_settings(),
        client=client,
    )


def test_runtime_client_requires_dedicated_worker_credentials() -> None:
    with pytest.raises(FileStorageError):
        MinioFileRuntimeAdapter(build_settings())

    settings = build_settings(
        minio_worker_access_key="worker-access",
        minio_worker_secret_key="worker-secret",
    )
    with patch("app.adapters.minio_file_runtime.Minio") as constructor:
        MinioFileRuntimeAdapter(settings)

    kwargs = constructor.call_args.kwargs
    assert kwargs["access_key"] == "worker-access"
    assert kwargs["secret_key"] == "worker-secret"
    assert kwargs["access_key"] != settings.minio_access_key.get_secret_value()


def test_read_verified_closes_response_and_checks_size_and_digest() -> None:
    payload = b"verified payload"
    client = _Client({("quarantine", "org/file"): payload})
    adapter = _adapter(client)

    result = adapter.read_verified(
        bucket_name="quarantine",
        object_key="org/file",
        expected_size=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        max_bytes=1024,
    )

    assert result == payload
    assert client.responses[0].closed is True
    assert client.responses[0].released is True

    with pytest.raises(FileStorageError):
        adapter.read_verified(
            bucket_name="quarantine",
            object_key="org/file",
            expected_size=len(payload),
            expected_sha256="0" * 64,
            max_bytes=1024,
        )


def test_promote_verifies_target_and_keeps_source_until_explicit_cleanup() -> None:
    payload = b"clean payload"
    key = "org/file"
    client = _Client({("quarantine", key): payload})
    adapter = _adapter(client)

    stored = adapter.promote_clean(
        source_bucket="quarantine",
        source_key=key,
        expected_size=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
    )

    assert (stored.bucket_name, stored.object_key) == ("originals", key)
    assert ("quarantine", key) in client.objects
    assert ("originals", key) in client.objects

    adapter.delete_quarantine_after_commit(key)
    assert ("quarantine", key) not in client.objects


def test_failed_target_verification_uses_compensating_delete() -> None:
    payload = b"clean payload"
    key = "org/file"
    client = _Client({("quarantine", key): payload})
    adapter = _adapter(client)

    with pytest.raises(FileStorageError):
        adapter.promote_clean(
            source_bucket="quarantine",
            source_key=key,
            expected_size=len(payload),
            expected_sha256="f" * 64,
        )

    assert ("originals", key) not in client.objects
    assert ("originals", key) in client.removals
