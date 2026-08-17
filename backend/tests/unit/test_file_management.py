from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from app.models.reliability import IdempotencyRecord
from app.schemas.files import (
    FileListItemData,
    FileStatus,
    IntendedBusinessType,
    SecurityScanStatus,
)
from app.services.file_management import FileManagementService


def test_file_management_replay_parses_jsonb_using_json_semantics() -> None:
    data = FileListItemData(
        file_id=UUID("72000000-0000-4000-8000-000000000001"),
        original_name="contract.pdf",
        status=FileStatus.ARCHIVED,
        security_scan_status=SecurityScanStatus.CLEAN,
        reused=False,
        intended_business_type=IntendedBusinessType.CONTRACT,
        target_knowledge_base_id=None,
        auto_process_requested=True,
        job_id=UUID("72000000-0000-4000-8000-000000000002"),
        job_status="succeeded",
        job_scope="full",
        next_stage="scan",
        row_version="3",
        size_bytes="128",
        created_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
    )
    record = cast(
        IdempotencyRecord,
        SimpleNamespace(
            response_status=200,
            response_body_json=data.model_dump(mode="json"),
        ),
    )

    assert FileManagementService._replay(record) == data
