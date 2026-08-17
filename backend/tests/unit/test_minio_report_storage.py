from __future__ import annotations

import hashlib
from typing import BinaryIO
from uuid import UUID

import pytest

from app.adapters.minio_report_storage import (
    MemoryReportStorageAdapter,
    MinioReportStorageAdapter,
    ReportObjectLocator,
    ReportStorageError,
    ReportStorageOutcomeUnknownError,
    report_object_locators,
)
from app.core.config import Settings

_ORGANIZATION_ID = UUID("5e6425f5-1db8-401e-ac05-f82c51baffee")
_REPORT_ID = UUID("f008d39f-031a-4649-8937-cb2c7560b3e2")
_PAYLOAD = b"formal-report-payload"
_SHA256 = hashlib.sha256(_PAYLOAD).hexdigest()


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        **{
            "app_env": "test",
            "secret_key": "test-signing-key-with-at-least-32-characters",
            "database_url": "postgresql+psycopg://test:test-password@postgresql:5432/test",
            "redis_url": "redis://:test-password@redis:6379/0",
            "celery_broker_url": "redis://:test-password@redis:6379/0",
            "celery_result_backend": "redis://:test-password@redis:6379/1",
            "minio_access_key": "test-minio-access",
            "minio_secret_key": "test-minio-secret",
            "minio_worker_access_key": "test-worker-access",
            "minio_worker_secret_key": "test-worker-secret",
            "qdrant_collection": "finaudit_policy_chunks_test_e1024_v1",
            "ai_policy_file": "D:\\synthetic\\ai-policy-v1.json",
            "llm_api_key": "test-llm-key",
            "llm_extraction_model": "test-extraction-model",
            "llm_generation_model": "test-generation-model",
            "embedding_base_url": "http://embedding:8000/v1",
            "embedding_api_key": "test-embedding-key",
            "embedding_model": "test-embedding-model",
            "metrics_internal_token": "test-metrics-token",
        },
    )


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.closed = False
        self.released = False

    def read(self, size: int = -1) -> bytes:
        return self.payload[:size] if size >= 0 else self.payload

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class _Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.put_calls: list[tuple[str, str, str, dict[str, str] | None]] = []
        self.remove_calls: list[tuple[str, str]] = []
        self.read_override: bytes | None = None
        self.remove_error: Exception | None = None

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> object:
        self.objects[(bucket_name, object_name)] = data.read(length)
        self.put_calls.append((bucket_name, object_name, content_type, metadata))
        return object()

    def get_object(self, bucket_name: str, object_name: str) -> _Response:
        payload = (
            self.read_override
            if self.read_override is not None
            else self.objects[(bucket_name, object_name)]
        )
        return _Response(payload)

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        self.remove_calls.append((bucket_name, object_name))
        if self.remove_error is not None:
            raise self.remove_error
        self.objects.pop((bucket_name, object_name), None)


def _adapter(client: _Client, *, scope: str = "worker") -> MinioReportStorageAdapter:
    return MinioReportStorageAdapter(
        _settings(),
        credential_scope=scope,  # type: ignore[arg-type]
        client=client,
    )


def test_server_locators_are_exact_and_separate_pdf_from_export() -> None:
    pdf, xlsx = report_object_locators(
        organization_id=_ORGANIZATION_ID,
        report_id=_REPORT_ID,
        report_version=2,
        reports_bucket="reports",
        exports_bucket="exports",
    )

    prefix = f"organizations/{_ORGANIZATION_ID.hex}/reports/{_REPORT_ID.hex}/v2"
    assert pdf == ReportObjectLocator("reports", f"{prefix}/report.pdf")
    assert xlsx == ReportObjectLocator("exports", f"{prefix}/risks.xlsx")


def test_worker_put_verifies_readback_and_api_scope_is_read_only() -> None:
    client = _Client()
    pdf, _xlsx = report_object_locators(
        organization_id=_ORGANIZATION_ID,
        report_id=_REPORT_ID,
        report_version=1,
        reports_bucket="reports",
        exports_bucket="exports",
    )

    _adapter(client).put_verified(
        pdf,
        _PAYLOAD,
        expected_sha256=_SHA256,
        content_type="application/pdf",
        max_bytes=1024,
    )

    assert client.put_calls == [("reports", pdf.object_key, "application/pdf", {"sha256": _SHA256})]
    assert (
        _adapter(client, scope="api").read_verified(
            pdf,
            expected_size=len(_PAYLOAD),
            expected_sha256=_SHA256,
            max_bytes=1024,
        )
        == _PAYLOAD
    )
    with pytest.raises(ReportStorageError):
        _adapter(client, scope="api").put_verified(
            pdf,
            _PAYLOAD,
            expected_sha256=_SHA256,
            content_type="application/pdf",
            max_bytes=1024,
        )


def test_readback_hash_mismatch_compensates_exact_object() -> None:
    client = _Client()
    client.read_override = b"tampered"
    pdf, _xlsx = report_object_locators(
        organization_id=_ORGANIZATION_ID,
        report_id=_REPORT_ID,
        report_version=1,
        reports_bucket="reports",
        exports_bucket="exports",
    )

    with pytest.raises(ReportStorageError):
        _adapter(client).put_verified(
            pdf,
            _PAYLOAD,
            expected_sha256=_SHA256,
            content_type="application/pdf",
            max_bytes=1024,
        )

    assert client.remove_calls == [("reports", pdf.object_key)]


def test_compensation_failure_reports_unknown_outcome_without_provider_details() -> None:
    client = _Client()
    client.read_override = b"tampered"
    client.remove_error = RuntimeError("secret-provider-detail")
    pdf, _xlsx = report_object_locators(
        organization_id=_ORGANIZATION_ID,
        report_id=_REPORT_ID,
        report_version=1,
        reports_bucket="reports",
        exports_bucket="exports",
    )

    with pytest.raises(ReportStorageOutcomeUnknownError) as exc_info:
        _adapter(client).put_verified(
            pdf,
            _PAYLOAD,
            expected_sha256=_SHA256,
            content_type="application/pdf",
            max_bytes=1024,
        )

    assert exc_info.value.locator == pdf
    assert "secret-provider-detail" not in repr(exc_info.value)


def test_bucket_or_object_key_substitution_fails_closed() -> None:
    client = _Client()
    adapter = _adapter(client)
    valid_pdf_key = f"organizations/{_ORGANIZATION_ID.hex}/reports/{_REPORT_ID.hex}/v1/report.pdf"
    invalid = (
        ReportObjectLocator("exports", valid_pdf_key),
        ReportObjectLocator("reports", "../reports/report.pdf"),
    )

    for locator in invalid:
        with pytest.raises(ReportStorageError):
            adapter.read_verified(
                locator,
                expected_size=len(_PAYLOAD),
                expected_sha256=_SHA256,
                max_bytes=1024,
            )


def test_memory_storage_enforces_hash_on_read() -> None:
    storage = MemoryReportStorageAdapter()
    locator = ReportObjectLocator("reports", "ignored-by-memory-adapter")
    storage.put_verified(
        locator,
        _PAYLOAD,
        expected_sha256=_SHA256,
        content_type="application/pdf",
        max_bytes=1024,
    )

    assert (
        storage.read_verified(
            locator,
            expected_size=len(_PAYLOAD),
            expected_sha256=_SHA256,
            max_bytes=1024,
        )
        == _PAYLOAD
    )
    storage.objects[locator] = b"tampered"
    with pytest.raises(ReportStorageError):
        storage.read_verified(
            locator,
            expected_size=len(_PAYLOAD),
            expected_sha256=_SHA256,
            max_bytes=1024,
        )
