from io import BytesIO
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock
from uuid import UUID

import pytest

from app.adapters.minio_quarantine import MinioQuarantineAdapter
from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.files import (
    FileStatus,
    FileUploadData,
    FileUploadIntent,
    IntendedBusinessType,
    SecurityScanStatus,
)
from app.services.auth import AuthenticatedActor
from app.services.file_intake import (
    FileBatchUploadInput,
    FileIntakeService,
    FileUploadResult,
)

ORGANIZATION_ID = UUID("70000000-0000-4000-8000-000000000001")
ACTOR_ID = UUID("70000000-0000-4000-8000-000000000002")


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        organization_id=ORGANIZATION_ID,
        session_id=UUID("70000000-0000-4000-8000-000000000003"),
        roles=("finance_reviewer",),
        permissions=("files.read", "files.upload"),
    )


def _service(max_batch: int = 20) -> FileIntakeService:
    settings = cast(
        Settings,
        SimpleNamespace(max_upload_size_mb=1, max_batch_file_count=max_batch),
    )
    return FileIntakeService(
        Mock(),
        cast(MinioQuarantineAdapter, Mock()),
        settings,
    )


def _accepted() -> FileUploadResult:
    return FileUploadResult(
        FileUploadData.model_validate(
            {
                "file_id": UUID("70000000-0000-4000-8000-000000000004"),
                "original_name": "valid.pdf",
                "status": FileStatus.UPLOADED,
                "security_scan_status": SecurityScanStatus.PENDING,
                "reused": False,
                "intended_business_type": IntendedBusinessType.CONTRACT,
                "target_knowledge_base_id": None,
                "auto_process_requested": True,
                "job_id": UUID("70000000-0000-4000-8000-000000000005"),
                "job_status": "queued",
                "job_scope": "full",
                "next_stage": "scan",
                "row_version": "1",
            }
        ),
        False,
    )


def test_batch_keeps_item_order_and_classifies_expected_item_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    upload = Mock(
        side_effect=[
            _accepted(),
            AppError(
                status_code=400,
                code="FILE_SIGNATURE_MISMATCH",
                message="文件签名不匹配",
            ),
        ]
    )
    monkeypatch.setattr(service, "upload", upload)
    items = (
        FileBatchUploadInput("valid.pdf", "application/pdf", BytesIO(b"valid")),
        FileBatchUploadInput("bad.pdf", "application/pdf", BytesIO(b"bad")),
    )

    result = service.upload_batch(
        _actor(),
        FileUploadIntent(intended_business_type=IntendedBusinessType.CONTRACT),
        items,
        idempotency_key="batch-unit-001",
        trace_id=UUID("70000000-0000-4000-8000-000000000006"),
    )

    assert result.accepted_count == 1
    assert result.rejected_count == 1
    assert tuple(item.index for item in result.items) == (0, 1)
    assert result.items[0].data is not None
    assert result.items[1].error is not None
    assert result.items[1].error.code == "FILE_SIGNATURE_MISMATCH"
    child_keys = tuple(call.kwargs["idempotency_key"] for call in upload.call_args_list)
    assert len(set(child_keys)) == 2
    assert all(key.startswith("batch.") and len(key) == 70 for key in child_keys)


def test_batch_limit_is_rejected_before_any_item_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(max_batch=1)
    upload = Mock()
    monkeypatch.setattr(service, "upload", upload)

    with pytest.raises(AppError) as captured:
        service.upload_batch(
            _actor(),
            FileUploadIntent(intended_business_type=IntendedBusinessType.CONTRACT),
            (
                FileBatchUploadInput("one.pdf", "application/pdf", BytesIO(b"one")),
                FileBatchUploadInput("two.pdf", "application/pdf", BytesIO(b"two")),
            ),
            idempotency_key="batch-unit-002",
            trace_id=UUID("70000000-0000-4000-8000-000000000007"),
        )

    assert captured.value.code == "BATCH_LIMIT_EXCEEDED"
    upload.assert_not_called()
