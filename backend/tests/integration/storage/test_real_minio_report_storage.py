from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from io import BytesIO
from uuid import UUID

import pytest
from minio import Minio
from minio.error import S3Error

from app.adapters.minio_original_storage import (
    MinioOriginalStorageAdapter,
    OriginalObjectLocator,
)
from app.adapters.minio_quarantine import _build_http_client
from app.adapters.minio_report_storage import (
    MinioReportStorageAdapter,
    ReportObjectLocator,
    ReportStorageError,
    report_object_locators,
)
from app.core.config import Settings

pytestmark = pytest.mark.integration

GATE_ENV = "FINAUDIT_LOCAL_MINIO_ADAPTER_INTEGRATION"
GATE_VALUE = "VERIFY_SYNTHETIC_STORAGE_V2"
LOCAL_ENDPOINT = "http://127.0.0.1:9000"
LOCAL_AUTHORITY = "127.0.0.1:9000"
MISSING_OBJECT_CODES = frozenset({"NoSuchKey", "NoSuchObject"})
ORGANIZATION_ID = UUID("93000000-0000-4000-8000-000000000001")
REPORT_ID = UUID("94000000-0000-4000-8000-000000000001")
TAMPER_REPORT_ID = UUID("94000000-0000-4000-8000-000000000002")
ORIGINAL_FILE_ID = UUID("94000000-0000-4000-8000-000000000003")
PDF_CONTENT = b"%PDF-1.7\nsynthetic formal report"
XLSX_CONTENT = b"PK\x03\x04synthetic formal report workbook"
ORIGINAL_CONTENT = b"%PDF-1.7\nsynthetic stored original"
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


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        pytest.fail(f"local MinIO gate requires {name}", pytrace=False)
    return value


def _load_gate() -> LocalMinioGate:
    gate = os.environ.get(GATE_ENV)
    if gate is None:
        pytest.skip("real local MinIO report integration is explicitly opt-in")
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
    worker_access_key = _required_environment("MINIO_WORKER_ACCESS_KEY")
    worker_secret_key = _required_environment("MINIO_WORKER_SECRET_KEY")
    if len({root_user, app_access_key, worker_access_key}) != 3:
        pytest.fail("local MinIO identities must be distinct", pytrace=False)

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
            "minio_worker_access_key": worker_access_key,
            "minio_worker_secret_key": worker_secret_key,
            "minio_secure": False,
            **{name.lower(): expected for name, expected in BUCKET_ENV},
            "qdrant_collection": "finaudit_local_minio_reports_e1024_v1",
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


def _raw_client(gate: LocalMinioGate, scope: str) -> Minio:
    if scope == "root":
        access_key = gate.root_user
        secret_key = gate.root_password
    elif scope == "worker":
        worker_access_key = gate.settings.minio_worker_access_key
        worker_secret_key = gate.settings.minio_worker_secret_key
        assert worker_access_key is not None and worker_secret_key is not None
        access_key = worker_access_key.get_secret_value()
        secret_key = worker_secret_key.get_secret_value()
    else:
        access_key = gate.settings.minio_access_key.get_secret_value()
        secret_key = gate.settings.minio_secret_key.get_secret_value()
    return Minio(
        LOCAL_AUTHORITY,
        access_key=access_key,
        secret_key=secret_key,
        secure=False,
        http_client=_build_http_client(),
    )


def _assert_missing(client: Minio, locator: ReportObjectLocator) -> None:
    try:
        client.stat_object(locator.bucket_name, locator.object_key)
    except S3Error as error:
        if error.code in MISSING_OBJECT_CODES:
            return
    except Exception:
        pass
    pytest.fail("local MinIO exact report object is not absent", pytrace=False)


def _cleanup(client: Minio, locators: tuple[ReportObjectLocator, ...]) -> None:
    for locator in locators:
        try:
            client.remove_object(locator.bucket_name, locator.object_key)
            _assert_missing(client, locator)
        except Exception:
            pytest.fail("local MinIO exact report cleanup failed", pytrace=False)


def _cleanup_original(client: Minio, locator: OriginalObjectLocator) -> None:
    try:
        client.remove_object(locator.bucket_name, locator.object_key)
        try:
            client.stat_object(locator.bucket_name, locator.object_key)
        except S3Error as error:
            if error.code in MISSING_OBJECT_CODES:
                return
    except Exception:
        pass
    pytest.fail("local MinIO exact original cleanup failed", pytrace=False)


def test_worker_persists_and_api_reads_verified_report_artifacts() -> None:
    gate = _load_gate()
    root = _raw_client(gate, "root")
    worker_raw = _raw_client(gate, "worker")
    app_raw = _raw_client(gate, "api")
    worker = MinioReportStorageAdapter(gate.settings, credential_scope="worker")
    api = MinioReportStorageAdapter(gate.settings, credential_scope="api")
    pdf, xlsx = report_object_locators(
        organization_id=ORGANIZATION_ID,
        report_id=REPORT_ID,
        report_version=1,
        reports_bucket=worker.reports_bucket,
        exports_bucket=worker.exports_bucket,
    )
    artifacts = (
        (pdf, PDF_CONTENT, "application/pdf"),
        (
            xlsx,
            XLSX_CONTENT,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    )

    _cleanup(root, (pdf, xlsx))
    try:
        for locator, payload, content_type in artifacts:
            sha256 = hashlib.sha256(payload).hexdigest()
            worker.put_verified(
                locator,
                payload,
                expected_sha256=sha256,
                content_type=content_type,
                max_bytes=4096,
            )
            assert (
                api.read_verified(
                    locator,
                    expected_size=len(payload),
                    expected_sha256=sha256,
                    max_bytes=4096,
                )
                == payload
            )
            stat = root.stat_object(locator.bucket_name, locator.object_key)
            assert stat.size == len(payload)
            assert stat.content_type == content_type
            assert stat.metadata is not None
            assert stat.metadata.get("x-amz-meta-sha256") == sha256

        with pytest.raises(S3Error) as app_write_error:
            app_raw.put_object(
                pdf.bucket_name,
                pdf.object_key,
                BytesIO(PDF_CONTENT),
                len(PDF_CONTENT),
            )
        assert app_write_error.value.code == "AccessDenied"

        with pytest.raises(S3Error) as worker_scope_error:
            worker_raw.put_object(
                "reports",
                "outside-approved-report-prefix",
                BytesIO(PDF_CONTENT),
                len(PDF_CONTENT),
            )
        assert worker_scope_error.value.code == "AccessDenied"

        with pytest.raises(ReportStorageError):
            api.delete_compensation(pdf)
    finally:
        _cleanup(root, (pdf, xlsx))


def test_api_rejects_root_tampered_report_object() -> None:
    gate = _load_gate()
    root = _raw_client(gate, "root")
    worker = MinioReportStorageAdapter(gate.settings, credential_scope="worker")
    api = MinioReportStorageAdapter(gate.settings, credential_scope="api")
    pdf, _xlsx = report_object_locators(
        organization_id=ORGANIZATION_ID,
        report_id=TAMPER_REPORT_ID,
        report_version=1,
        reports_bucket=worker.reports_bucket,
        exports_bucket=worker.exports_bucket,
    )
    sha256 = hashlib.sha256(PDF_CONTENT).hexdigest()

    _cleanup(root, (pdf,))
    try:
        worker.put_verified(
            pdf,
            PDF_CONTENT,
            expected_sha256=sha256,
            content_type="application/pdf",
            max_bytes=4096,
        )
        tampered = PDF_CONTENT + b"-tampered"
        root.put_object(
            pdf.bucket_name,
            pdf.object_key,
            BytesIO(tampered),
            len(tampered),
            content_type="application/pdf",
        )

        with pytest.raises(ReportStorageError):
            api.read_verified(
                pdf,
                expected_size=len(PDF_CONTENT),
                expected_sha256=sha256,
                max_bytes=4096,
            )
    finally:
        _cleanup(root, (pdf,))


def test_api_identity_reads_verified_original_without_write_permission() -> None:
    gate = _load_gate()
    root = _raw_client(gate, "root")
    app_raw = _raw_client(gate, "api")
    api = MinioOriginalStorageAdapter(gate.settings)
    locator = OriginalObjectLocator(
        "originals",
        f"organizations/{ORGANIZATION_ID.hex}/files/{ORIGINAL_FILE_ID.hex}/source",
    )
    sha256 = hashlib.sha256(ORIGINAL_CONTENT).hexdigest()

    _cleanup_original(root, locator)
    try:
        root.put_object(
            locator.bucket_name,
            locator.object_key,
            BytesIO(ORIGINAL_CONTENT),
            len(ORIGINAL_CONTENT),
            content_type="application/pdf",
        )
        assert (
            api.read_verified(
                locator,
                expected_size=len(ORIGINAL_CONTENT),
                expected_sha256=sha256,
                max_bytes=4096,
            )
            == ORIGINAL_CONTENT
        )

        with pytest.raises(S3Error) as app_write_error:
            app_raw.put_object(
                locator.bucket_name,
                locator.object_key,
                BytesIO(ORIGINAL_CONTENT),
                len(ORIGINAL_CONTENT),
            )
        assert app_write_error.value.code == "AccessDenied"
    finally:
        _cleanup_original(root, locator)
