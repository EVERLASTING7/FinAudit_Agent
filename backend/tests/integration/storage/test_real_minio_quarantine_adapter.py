from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from io import BytesIO
from typing import BinaryIO
from uuid import UUID

import pytest
from minio import Minio
from minio.error import S3Error

from app.adapters.minio_quarantine import (
    MinioQuarantineAdapter,
    QuarantineCleanupRequiredError,
    QuarantineObject,
    QuarantineStorageError,
    _build_http_client,
)
from app.core.config import Settings
from app.services.file_service import prepare_quarantine_intake

pytestmark = pytest.mark.integration

GATE_ENV = "FINAUDIT_LOCAL_MINIO_ADAPTER_INTEGRATION"
GATE_VALUE = "VERIFY_SYNTHETIC_STORAGE_V2"
LOCAL_ENDPOINT = "http://127.0.0.1:9000"
LOCAL_AUTHORITY = "127.0.0.1:9000"
MISSING_OBJECT_CODES = frozenset({"NoSuchKey", "NoSuchObject"})
PDF_CONTENT = b"%PDF-1.7\nsynthetic real MinIO adapter integration"
ORGANIZATION_ID = UUID("91000000-0000-4000-8000-000000000001")
HAPPY_FILE_ID = UUID("92000000-0000-4000-8000-000000000001")
INTEGRITY_FILE_ID = UUID("92000000-0000-4000-8000-000000000002")
POST_COMMIT_FILE_ID = UUID("92000000-0000-4000-8000-000000000003")
BUCKET_ENV = (
    ("MINIO_BUCKET_QUARANTINE", "quarantine"),
    ("MINIO_BUCKET_ORIGINALS", "originals"),
    ("MINIO_BUCKET_ASSETS", "assets"),
    ("MINIO_BUCKET_PREVIEWS", "previews"),
    ("MINIO_BUCKET_REPORTS", "reports"),
    ("MINIO_BUCKET_EXPORTS", "exports"),
    ("MINIO_BUCKET_TEMP", "temp"),
)


@dataclass(frozen=True, slots=True)
class LocalMinioGate:
    settings: Settings
    root_user: str = field(repr=False)
    root_password: str = field(repr=False)


class PostCommitExceptionClient:
    """真实 PUT 已返回后注入异常；仅证明该确定性补偿路径。"""

    def __init__(self, client: Minio) -> None:
        self._client = client

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str | list[str] | tuple[str]] | None = None,
    ) -> object:
        self._client.put_object(
            bucket_name,
            object_name,
            data,
            length,
            content_type=content_type,
            metadata=metadata,
        )
        raise TimeoutError("synthetic post-commit exception")

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        self._client.remove_object(bucket_name, object_name)


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        pytest.fail(f"local MinIO gate requires {name}", pytrace=False)
    return value


def _load_gate() -> LocalMinioGate:
    gate = os.environ.get(GATE_ENV)
    if gate is None:
        pytest.skip("real local MinIO adapter integration is explicitly opt-in")
    if gate != GATE_VALUE:
        pytest.fail("local MinIO adapter integration confirmation is invalid", pytrace=False)

    if (
        _required_environment("APP_ENV") != "local"
        or _required_environment("MINIO_ENDPOINT") != LOCAL_ENDPOINT
        or _required_environment("MINIO_SECURE").lower() != "false"
        or any(_required_environment(name) != expected for name, expected in BUCKET_ENV)
    ):
        pytest.fail("local MinIO adapter integration profile is unsafe", pytrace=False)

    root_user = _required_environment("MINIO_ROOT_USER")
    root_password = _required_environment("MINIO_ROOT_PASSWORD")
    app_access_key = _required_environment("MINIO_ACCESS_KEY")
    app_secret_key = _required_environment("MINIO_SECRET_KEY")
    if root_user == app_access_key:
        pytest.fail("local MinIO root and application identities must differ", pytrace=False)

    bucket_values = {name.lower(): expected for name, expected in BUCKET_ENV}
    settings = Settings(
        _env_file=None,
        **{
            "app_env": "local",
            "secret_key": "synthetic-local-integration-signing-key",
            "database_url": "postgresql+psycopg://synthetic:synthetic@127.0.0.1/finaudit_unused",
            "redis_url": "redis://:synthetic@127.0.0.1:6379/0",
            "celery_broker_url": "redis://:synthetic@127.0.0.1:6379/0",
            "celery_result_backend": "redis://:synthetic@127.0.0.1:6379/1",
            "minio_endpoint": LOCAL_ENDPOINT,
            "minio_access_key": app_access_key,
            "minio_secret_key": app_secret_key,
            "minio_secure": False,
            **bucket_values,
            "qdrant_collection": "finaudit_local_minio_integration_e1024_v1",
            "ai_policy_file": "D:\\synthetic\\ai-policy-v1.json",
            "llm_api_key": "synthetic-local-integration-llm",
            "llm_extraction_model": "synthetic-extraction-model",
            "llm_generation_model": "synthetic-generation-model",
            "embedding_base_url": "http://127.0.0.1:8000/v1",
            "embedding_api_key": "synthetic-local-integration-embedding",
            "embedding_model": "synthetic-embedding-model",
            "metrics_internal_token": "synthetic-local-integration-metrics",
        },
    )
    return LocalMinioGate(settings, root_user, root_password)


def _root_client(gate: LocalMinioGate) -> Minio:
    return Minio(
        LOCAL_AUTHORITY,
        access_key=gate.root_user,
        secret_key=gate.root_password,
        secure=False,
        http_client=_build_http_client(),
    )


def _assert_root_reads_exact_object(
    client: Minio,
    locator: QuarantineObject,
    *,
    payload: bytes,
    sha256: str,
    content_type: str,
) -> None:
    try:
        result = client.stat_object(locator.bucket_name, locator.object_key)
        response = client.get_object(locator.bucket_name, locator.object_key)
        try:
            stored_payload = response.read()
        finally:
            response.close()
            response.release_conn()
    except Exception:
        pytest.fail("local MinIO root object verification failed", pytrace=False)

    assert result.size == len(payload)
    assert result.content_type == content_type
    assert result.metadata is not None
    assert result.metadata.get("x-amz-meta-sha256") == sha256
    assert stored_payload == payload


def _assert_root_confirms_missing(client: Minio, locator: QuarantineObject) -> None:
    try:
        client.stat_object(locator.bucket_name, locator.object_key)
    except S3Error as error:
        if error.code in MISSING_OBJECT_CODES:
            return
    except Exception:
        pass
    pytest.fail("local MinIO root absence verification failed", pytrace=False)


def _root_cleanup(client: Minio, locator: QuarantineObject) -> None:
    try:
        client.remove_object(locator.bucket_name, locator.object_key)
        _assert_root_confirms_missing(client, locator)
    except Exception:
        pytest.fail("local MinIO exact-object cleanup failed", pytrace=False)


def _prepare_exact_object(client: Minio, locator: QuarantineObject) -> None:
    _root_cleanup(client, locator)


def _expected_locator(organization_id: UUID, file_id: UUID) -> QuarantineObject:
    return QuarantineObject(
        "quarantine",
        f"organizations/{organization_id.hex}/files/{file_id.hex}/source",
    )


def test_prepare_put_verify_and_delete_real_local_minio_object() -> None:
    gate = _load_gate()
    root = _root_client(gate)
    adapter = MinioQuarantineAdapter(gate.settings)
    locator = _expected_locator(ORGANIZATION_ID, HAPPY_FILE_ID)
    stream = BytesIO(PDF_CONTENT)

    _prepare_exact_object(root, locator)
    try:
        facts = prepare_quarantine_intake(
            stream,
            file_name="synthetic.pdf",
            declared_mime="application/pdf",
            max_size_bytes=len(PDF_CONTENT),
        )
        actual_locator = adapter.put_quarantine(
            organization_id=ORGANIZATION_ID,
            file_id=HAPPY_FILE_ID,
            sha256=facts.sha256,
            data=stream,
            length=facts.size_bytes,
            content_type=facts.detected_mime,
        )
        assert actual_locator == locator
        _assert_root_reads_exact_object(
            root,
            locator,
            payload=PDF_CONTENT,
            sha256=facts.sha256,
            content_type=facts.detected_mime,
        )
        adapter.delete_quarantine(locator)
        _assert_root_confirms_missing(root, locator)
    finally:
        _root_cleanup(root, locator)


def test_completed_put_integrity_failure_is_compensated_in_real_local_minio() -> None:
    gate = _load_gate()
    root = _root_client(gate)
    adapter = MinioQuarantineAdapter(gate.settings)
    locator = _expected_locator(ORGANIZATION_ID, INTEGRITY_FILE_ID)
    stream = BytesIO(PDF_CONTENT)

    _prepare_exact_object(root, locator)
    try:
        facts = prepare_quarantine_intake(
            stream,
            file_name="synthetic.pdf",
            declared_mime="application/pdf",
            max_size_bytes=len(PDF_CONTENT),
        )
        wrong_sha256 = hashlib.sha256(PDF_CONTENT + b"-different").hexdigest()
        with pytest.raises(QuarantineStorageError) as exc_info:
            adapter.put_quarantine(
                organization_id=ORGANIZATION_ID,
                file_id=INTEGRITY_FILE_ID,
                sha256=wrong_sha256,
                data=stream,
                length=facts.size_bytes,
                content_type=facts.detected_mime,
            )

        assert type(exc_info.value) is QuarantineStorageError
        _assert_root_confirms_missing(root, locator)
    finally:
        _root_cleanup(root, locator)


def test_post_commit_exception_triggers_exact_compensation_in_real_local_minio() -> None:
    gate = _load_gate()
    root = _root_client(gate)
    real_app_client = Minio(
        LOCAL_AUTHORITY,
        access_key=gate.settings.minio_access_key.get_secret_value(),
        secret_key=gate.settings.minio_secret_key.get_secret_value(),
        secure=False,
        http_client=_build_http_client(),
    )
    adapter = MinioQuarantineAdapter(
        gate.settings,
        client=PostCommitExceptionClient(real_app_client),
    )
    locator = _expected_locator(ORGANIZATION_ID, POST_COMMIT_FILE_ID)
    stream = BytesIO(PDF_CONTENT)

    _prepare_exact_object(root, locator)
    try:
        facts = prepare_quarantine_intake(
            stream,
            file_name="synthetic.pdf",
            declared_mime="application/pdf",
            max_size_bytes=len(PDF_CONTENT),
        )
        with pytest.raises(QuarantineCleanupRequiredError) as exc_info:
            adapter.put_quarantine(
                organization_id=ORGANIZATION_ID,
                file_id=POST_COMMIT_FILE_ID,
                sha256=facts.sha256,
                data=stream,
                length=facts.size_bytes,
                content_type=facts.detected_mime,
            )

        assert exc_info.value.locator == locator
        _assert_root_confirms_missing(root, locator)
    finally:
        _root_cleanup(root, locator)


def test_local_minio_gate_repr_hides_root_credentials() -> None:
    sentinel_user = "root-user-sentinel"
    sentinel_password = "root-password-sentinel"
    gate = LocalMinioGate(
        settings=Settings.model_construct(),
        root_user=sentinel_user,
        root_password=sentinel_password,
    )

    rendered = repr(gate)
    assert sentinel_user not in rendered
    assert sentinel_password not in rendered
