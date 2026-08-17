import hashlib
import inspect
from io import BytesIO
from typing import BinaryIO
from uuid import UUID

import pytest
from urllib3 import PoolManager, Retry, Timeout

import app.adapters.minio_quarantine as minio_module
from app.adapters.minio_quarantine import (
    MinioQuarantineAdapter,
    QuarantineCleanupRequiredError,
    QuarantineObject,
    QuarantineStorageError,
)
from app.core.config import Settings

ORGANIZATION_ID = UUID("5e6425f5-1db8-401e-ac05-f82c51baffee")
FILE_ID = UUID("f008d39f-031a-4649-8937-cb2c7560b3e2")
PAYLOAD = b"payload"
SHA256 = hashlib.sha256(PAYLOAD).hexdigest()
OBJECT_KEY = f"organizations/{ORGANIZATION_ID.hex}/files/{FILE_ID.hex}/source"


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


class FakeMinioClient:
    def __init__(self) -> None:
        self.put_calls: list[
            tuple[
                str,
                str,
                bytes,
                int,
                str,
                dict[str, str | list[str] | tuple[str]] | None,
            ]
        ] = []
        self.remove_calls: list[tuple[str, str]] = []
        self.put_error: Exception | None = None
        self.remove_error: Exception | None = None

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str | list[str] | tuple[str]] | None = None,
    ) -> object:
        payload = data.read(length)
        self.put_calls.append((bucket_name, object_name, payload, length, content_type, metadata))
        if self.put_error is not None:
            raise self.put_error
        return object()

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        self.remove_calls.append((bucket_name, object_name))
        if self.remove_error is not None:
            raise self.remove_error


def test_adapter_exposes_only_quarantine_put_and_delete() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(MinioQuarantineAdapter, inspect.isfunction)
        if not name.startswith("_")
    }

    assert public_methods == {"put_quarantine", "delete_quarantine"}
    assert "filename" not in inspect.signature(MinioQuarantineAdapter.put_quarantine).parameters


def test_put_uses_server_identifiers_and_returns_persistable_locator() -> None:
    client = FakeMinioClient()
    adapter = MinioQuarantineAdapter(build_settings(), client=client)
    stream = BytesIO(PAYLOAD)

    locator = adapter.put_quarantine(
        organization_id=ORGANIZATION_ID,
        file_id=FILE_ID,
        sha256=SHA256,
        data=stream,
        length=len(PAYLOAD),
        content_type="application/pdf",
    )

    assert locator == QuarantineObject(bucket_name="quarantine", object_key=OBJECT_KEY)
    assert client.put_calls == [
        (
            "quarantine",
            OBJECT_KEY,
            PAYLOAD,
            len(PAYLOAD),
            "application/pdf",
            {"sha256": SHA256},
        )
    ]
    assert "client-supplied-name.pdf" not in locator.object_key
    assert stream.tell() == 0
    assert not stream.closed


def test_delete_is_limited_to_the_configured_quarantine_bucket() -> None:
    client = FakeMinioClient()
    adapter = MinioQuarantineAdapter(build_settings(), client=client)
    locator = QuarantineObject("quarantine", OBJECT_KEY)

    adapter.delete_quarantine(locator)

    assert client.remove_calls == [("quarantine", locator.object_key)]
    for invalid_locator in (
        QuarantineObject("originals", locator.object_key),
        QuarantineObject("quarantine", "../originals/other-object"),
    ):
        with pytest.raises(ValueError):
            adapter.delete_quarantine(invalid_locator)
    assert len(client.remove_calls) == 1


@pytest.mark.parametrize(
    ("sha256", "length", "content_type"),
    [
        ("A" * 64, 7, "application/pdf"),
        ("a" * 63, 7, "application/pdf"),
        (SHA256, 0, "application/pdf"),
        (SHA256, True, "application/pdf"),
        (SHA256, 7, "application/pdf\r\nx-test: injected"),
    ],
)
def test_put_rejects_invalid_server_metadata(
    sha256: str,
    length: int,
    content_type: str,
) -> None:
    client = FakeMinioClient()
    adapter = MinioQuarantineAdapter(build_settings(), client=client)

    with pytest.raises((TypeError, ValueError)):
        adapter.put_quarantine(
            organization_id=ORGANIZATION_ID,
            file_id=FILE_ID,
            sha256=sha256,
            data=BytesIO(b"payload"),
            length=length,
            content_type=content_type,
        )

    assert client.put_calls == []


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_sdk_failures_are_normalized_without_provider_error_context(operation: str) -> None:
    sentinel = "provider-secret-sentinel"
    client = FakeMinioClient()
    adapter = MinioQuarantineAdapter(build_settings(), client=client)
    locator = QuarantineObject("quarantine", OBJECT_KEY)
    stream = BytesIO(PAYLOAD)
    stream.seek(3)
    if operation == "put":
        client.put_error = RuntimeError(sentinel)
        call = lambda: adapter.put_quarantine(  # noqa: E731
            organization_id=ORGANIZATION_ID,
            file_id=FILE_ID,
            sha256=SHA256,
            data=stream,
            length=len(PAYLOAD),
            content_type="application/pdf",
        )
    else:
        client.remove_error = RuntimeError(sentinel)
        call = lambda: adapter.delete_quarantine(locator)  # noqa: E731

    with pytest.raises(QuarantineStorageError) as exc_info:
        call()

    rendered = f"{exc_info.value!s}\n{exc_info.value!r}"
    assert sentinel not in rendered
    assert exc_info.value.__context__ is None
    assert exc_info.value.__cause__ is None
    if operation == "put":
        assert stream.tell() == 0
        assert not stream.closed
        assert client.remove_calls == [("quarantine", OBJECT_KEY)]
        assert isinstance(exc_info.value, QuarantineCleanupRequiredError)
        assert exc_info.value.locator == locator


def test_unknown_put_outcome_requires_reconciliation_when_best_effort_delete_fails() -> None:
    client = FakeMinioClient()
    client.put_error = RuntimeError("put-provider-secret")
    client.remove_error = RuntimeError("delete-provider-secret")
    adapter = MinioQuarantineAdapter(build_settings(), client=client)

    with pytest.raises(QuarantineCleanupRequiredError) as exc_info:
        adapter.put_quarantine(
            organization_id=ORGANIZATION_ID,
            file_id=FILE_ID,
            sha256=SHA256,
            data=BytesIO(PAYLOAD),
            length=len(PAYLOAD),
            content_type="application/pdf",
        )

    assert exc_info.value.locator == QuarantineObject("quarantine", OBJECT_KEY)
    assert client.remove_calls == [("quarantine", OBJECT_KEY)]
    rendered = f"{exc_info.value!s}\n{exc_info.value!r}"
    assert "provider-secret" not in rendered


@pytest.mark.parametrize(
    ("payload", "length", "sha256"),
    [
        (PAYLOAD, len(PAYLOAD), "a" * 64),
        (PAYLOAD[:-1], len(PAYLOAD), SHA256),
        (PAYLOAD + b"-extra", len(PAYLOAD), SHA256),
    ],
    ids=["wrong-digest", "short-read", "over-read"],
)
def test_put_rejects_content_integrity_mismatch_and_compensates_exact_object(
    payload: bytes,
    length: int,
    sha256: str,
) -> None:
    client = FakeMinioClient()
    adapter = MinioQuarantineAdapter(build_settings(), client=client)
    stream = BytesIO(payload)

    with pytest.raises(QuarantineStorageError) as exc_info:
        adapter.put_quarantine(
            organization_id=ORGANIZATION_ID,
            file_id=FILE_ID,
            sha256=sha256,
            data=stream,
            length=length,
            content_type="application/pdf",
        )

    assert client.remove_calls == [("quarantine", OBJECT_KEY)]
    assert stream.tell() == 0
    assert not stream.closed
    assert exc_info.value.__context__ is None
    assert exc_info.value.__cause__ is None


def test_integrity_compensation_failure_is_sanitized_and_rewinds_stream() -> None:
    endpoint = "https://minio.internal.example:9000"
    sentinel = "compensation-provider-secret"
    client = FakeMinioClient()
    client.remove_error = RuntimeError(
        f"{endpoint} {sentinel} {ORGANIZATION_ID} {FILE_ID} {OBJECT_KEY}"
    )
    adapter = MinioQuarantineAdapter(build_settings(), client=client)
    stream = BytesIO(PAYLOAD)

    with pytest.raises(QuarantineCleanupRequiredError) as exc_info:
        adapter.put_quarantine(
            organization_id=ORGANIZATION_ID,
            file_id=FILE_ID,
            sha256="a" * 64,
            data=stream,
            length=len(PAYLOAD),
            content_type="application/pdf",
        )

    assert client.remove_calls == [("quarantine", OBJECT_KEY)]
    assert stream.tell() == 0
    assert not stream.closed
    error = exc_info.value
    rendered = f"{error!s}\n{error!r}\n{error.args!r}"
    for sensitive_value in (
        endpoint,
        sentinel,
        str(ORGANIZATION_ID),
        str(FILE_ID),
        OBJECT_KEY,
    ):
        assert sensitive_value not in rendered
    assert error.args == ("MinIO quarantine cleanup required",)
    assert error.locator == QuarantineObject("quarantine", OBJECT_KEY)
    with pytest.raises(AttributeError):
        error.locator = QuarantineObject("quarantine", OBJECT_KEY)  # type: ignore[misc]
    assert error.__context__ is None
    assert error.__cause__ is None


def test_sdk_initialization_uses_origin_authority_and_hides_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    client = FakeMinioClient()

    def build_client(
        endpoint: str,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool = True,
        http_client: PoolManager | None = None,
    ) -> FakeMinioClient:
        captured.update(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            http_client=http_client,
        )
        return client

    monkeypatch.setattr(minio_module, "Minio", build_client)
    settings = build_settings(
        minio_endpoint="https://minio.example.test:9000",
        minio_secure=True,
    )

    adapter = MinioQuarantineAdapter(settings)

    assert captured["endpoint"] == "minio.example.test:9000"
    assert captured["access_key"] == "test-minio-access"
    assert captured["secret_key"] == "test-minio-secret"
    assert captured["secure"] is True
    http_client = captured["http_client"]
    assert isinstance(http_client, PoolManager)
    timeout = http_client.connection_pool_kw["timeout"]
    retry = http_client.connection_pool_kw["retries"]
    assert isinstance(timeout, Timeout)
    assert timeout.connect_timeout == 3
    assert timeout.read_timeout == 30
    assert isinstance(retry, Retry)
    assert retry.total == 2
    assert http_client.connection_pool_kw["cert_reqs"] == "CERT_REQUIRED"
    rendered = repr(adapter)
    assert "test-minio-access" not in rendered
    assert "test-minio-secret" not in rendered


def test_sdk_initialization_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = "sdk-initialization-secret"

    def fail_client(*_args: object, **_kwargs: object) -> FakeMinioClient:
        raise RuntimeError(sentinel)

    monkeypatch.setattr(minio_module, "Minio", fail_client)

    with pytest.raises(QuarantineStorageError) as exc_info:
        MinioQuarantineAdapter(build_settings())

    assert sentinel not in str(exc_info.value)
    assert sentinel not in repr(exc_info.value)
    assert exc_info.value.__context__ is None
    assert exc_info.value.__cause__ is None
