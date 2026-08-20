from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import ANY, Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.files import (
    get_file_intake_service,
    get_file_management_service,
    get_file_query_service,
)
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.files import (
    FileBatchItemData,
    FileBatchUploadData,
    FileListData,
    FileListItemData,
    FileStatus,
    FileTextPreviewData,
    FileUploadData,
    IntendedBusinessType,
    SecurityScanStatus,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.file_intake import FileIntakeService, FileQueryService, FileUploadResult
from app.services.file_management import (
    FileManagementService,
    FileMutationResult,
    FilePreviewResult,
)
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("6f000000-0000-4000-8000-000000000001")
ACTOR_ID = UUID("6f000000-0000-4000-8000-000000000002")
FILE_ID = UUID("6f000000-0000-4000-8000-000000000003")
JOB_ID = UUID("6f000000-0000-4000-8000-000000000004")


@pytest.fixture
def auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        ACTOR_ID,
        ORGANIZATION_ID,
        UUID("6f000000-0000-4000-8000-000000000005"),
        ("system_admin",),
        ("files.manage", "files.read", "files.upload"),
    )
    service.authenticate.return_value = (
        actor,
        CurrentUserData(
            id=ACTOR_ID,
            display_name="文件管理员",
            roles=("system_admin",),
            permissions=("files.manage", "files.read", "files.upload"),
        ),
    )
    return service


def _upload_data(*, reused: bool = False) -> FileUploadData:
    return FileUploadData.model_validate(
        {
            "file_id": FILE_ID,
            "original_name": "contract.pdf",
            "status": FileStatus.UPLOADED,
            "security_scan_status": SecurityScanStatus.PENDING,
            "reused": reused,
            "intended_business_type": IntendedBusinessType.CONTRACT,
            "target_knowledge_base_id": None,
            "auto_process_requested": True,
            "job_id": JOB_ID,
            "job_status": "queued",
            "job_scope": "full",
            "next_stage": "scan",
            "row_version": "1",
        }
    )


@pytest.fixture
def intake_service() -> Mock:
    service = Mock(spec=FileIntakeService)
    service.upload.return_value = FileUploadResult(_upload_data(), False)
    service.upload_batch.return_value = FileBatchUploadData(
        items=(
            FileBatchItemData(
                index=0,
                original_name="contract.pdf",
                outcome="accepted",
                http_status=202,
                replayed=False,
                data=_upload_data(),
                error=None,
            ),
        ),
        accepted_count=1,
        rejected_count=0,
    )
    return service


@pytest.fixture
def query_service() -> Mock:
    service = Mock(spec=FileQueryService)
    item = FileListItemData.model_validate(
        _upload_data().model_dump()
        | {
            "size_bytes": "25",
            "created_at": datetime(2026, 8, 13, 1, 2, 3, tzinfo=timezone.utc),
        }
    )
    service.get.return_value = item
    service.list_page.return_value = FileListData(items=(item,), page_size=20)
    return service


@pytest.fixture
def management_service(query_service: Mock) -> Mock:
    service = Mock(spec=FileManagementService)
    item = query_service.get.return_value
    service.archive.return_value = FileMutationResult(item, False)
    service.retry.return_value = FileMutationResult(item, False)
    service.preview_original.return_value = FilePreviewResult(
        content=b"%PDF-1.7\npreview",
        filename="contract.pdf",
        mime_type="application/pdf",
        sha256="a" * 64,
        status="stored",
    )
    service.text_preview.return_value = FileTextPreviewData(
        file_id=FILE_ID,
        markdown_version_id=UUID("6f000000-0000-4000-8000-000000000006"),
        content_sha256="b" * 64,
        markdown_text="# 合同",
        char_count=4,
        truncated=False,
    )
    return service


@pytest.fixture
def application(
    exact_policy_file: Path,
    auth_service: Mock,
    intake_service: Mock,
    management_service: Mock,
    query_service: Mock,
) -> FastAPI:
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_file_intake_service] = lambda: intake_service
    app.dependency_overrides[get_file_management_service] = lambda: management_service
    app.dependency_overrides[get_file_query_service] = lambda: query_service
    return app


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_upload_is_strict_private_idempotent_and_forwards_stream(
    client: TestClient,
    intake_service: Mock,
) -> None:
    response = client.post(
        "/api/v1/files",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "file-upload-001",
        },
        data={
            "intended_business_type": "contract",
            "auto_process_requested": "true",
        },
        files={"file": ("contract.pdf", b"%PDF-1.7\nsynthetic", "application/pdf")},
    )

    assert response.status_code == 202, response.json()
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["idempotency-replayed"] == "false"
    assert response.json()["data"] == _upload_data().model_dump(mode="json")
    intake_service.upload.assert_called_once_with(
        ANY,
        ANY,
        file_name="contract.pdf",
        declared_mime="application/pdf",
        stream=ANY,
        idempotency_key="file-upload-001",
        trace_id=ANY,
    )
    actor, intent = intake_service.upload.call_args.args
    assert actor.organization_id == ORGANIZATION_ID
    assert intent.model_dump(mode="json") == {
        "intended_business_type": "contract",
        "target_knowledge_base_id": None,
        "auto_process_requested": True,
    }


@pytest.mark.parametrize(
    "multipart",
    (
        [
            ("file", ("contract.pdf", b"%PDF-1.7\none", "application/pdf")),
            ("file", ("duplicate.pdf", b"%PDF-1.7\ntwo", "application/pdf")),
            ("intended_business_type", (None, "contract")),
        ],
        [
            ("file", ("contract.pdf", b"%PDF-1.7\none", "application/pdf")),
            ("intended_business_type", (None, "contract")),
            ("unexpected", (None, "secret-must-not-be-accepted")),
        ],
        [
            ("file", ("contract.pdf", b"%PDF-1.7\none", "application/pdf")),
            ("intended_business_type", (None, "contract")),
            ("auto_process_requested", (None, "TRUE")),
        ],
    ),
)
def test_upload_rejects_duplicate_unknown_or_noncanonical_parts_before_service(
    client: TestClient,
    intake_service: Mock,
    multipart: list[tuple[str, tuple[str | None, str | bytes] | tuple[str, bytes, str]]],
) -> None:
    response = client.post(
        "/api/v1/files",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "file-upload-002",
        },
        files=multipart,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "secret" not in response.text
    intake_service.upload.assert_not_called()


def test_upload_requires_permission_before_service(
    client: TestClient,
    auth_service: Mock,
    intake_service: Mock,
) -> None:
    actor, current = auth_service.authenticate.return_value
    auth_service.authenticate.return_value = (
        AuthenticatedActor(
            actor.user_id,
            actor.organization_id,
            actor.session_id,
            actor.roles,
            ("files.read",),
        ),
        current,
    )

    response = client.post(
        "/api/v1/files",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "file-upload-003",
        },
        data={"intended_business_type": "contract"},
        files={"file": ("contract.pdf", b"%PDF-1.7\nsynthetic", "application/pdf")},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    intake_service.upload.assert_not_called()


def test_batch_upload_is_strict_and_forwards_all_files(
    client: TestClient,
    intake_service: Mock,
) -> None:
    response = client.post(
        "/api/v1/files/batch",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "file-batch-001"},
        files=[
            ("files", ("contract.pdf", b"%PDF-1.7\none", "application/pdf")),
            ("files", ("contract-2.pdf", b"%PDF-1.7\ntwo", "application/pdf")),
            ("intended_business_type", (None, "contract")),
            ("auto_process_requested", (None, "true")),
        ],
    )

    assert response.status_code == 207, response.text
    assert response.headers["cache-control"] == "private, no-store"
    intake_service.upload_batch.assert_called_once()
    actor, intent, items = intake_service.upload_batch.call_args.args
    assert actor.organization_id == ORGANIZATION_ID
    assert intent.intended_business_type is IntendedBusinessType.CONTRACT
    assert tuple(item.file_name for item in items) == ("contract.pdf", "contract-2.pdf")
    assert intake_service.upload_batch.call_args.kwargs["idempotency_key"] == "file-batch-001"


def test_file_preview_text_archive_and_retry_are_authorized_and_private(
    client: TestClient,
    management_service: Mock,
) -> None:
    preview = client.get(
        f"/api/v1/files/{FILE_ID}/preview",
        headers={"Authorization": "Bearer token"},
    )
    text_preview = client.get(
        f"/api/v1/files/{FILE_ID}/text-preview?max_chars=1000",
        headers={"Authorization": "Bearer token"},
    )
    archive = client.post(
        f"/api/v1/files/{FILE_ID}/archive",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "archive-file-001"},
        json={"row_version": "1", "reason": "归档测试文件"},
    )
    retry = client.post(
        f"/api/v1/files/{FILE_ID}/retry",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "retry-file-001"},
        json={
            "file_row_version": "1",
            "job_id": str(JOB_ID),
            "job_row_version": "1",
            "reason": "重试失败任务",
        },
    )

    assert preview.status_code == 200
    assert preview.content == b"%PDF-1.7\npreview"
    assert preview.headers["cache-control"] == "private, no-store"
    assert preview.headers["x-content-type-options"] == "nosniff"
    assert preview.headers["x-file-id"] == str(FILE_ID)
    assert text_preview.status_code == 200
    assert text_preview.json()["data"]["markdown_text"] == "# 合同"
    assert archive.status_code == 200
    assert retry.status_code == 200, retry.text
    assert archive.headers["idempotency-replayed"] == "false"
    assert retry.headers["idempotency-replayed"] == "false"
    management_service.preview_original.assert_called_once_with(ANY, FILE_ID, ANY)
    management_service.text_preview.assert_called_once_with(ANY, FILE_ID, 1000, ANY)
    management_service.archive.assert_called_once_with(
        ANY,
        FILE_ID,
        ANY,
        "archive-file-001",
        ANY,
    )
    management_service.retry.assert_called_once_with(
        ANY,
        FILE_ID,
        ANY,
        "retry-file-001",
        ANY,
    )


def test_file_reads_are_org_scoped_strict_and_private(
    client: TestClient,
    query_service: Mock,
) -> None:
    list_response = client.get(
        "/api/v1/files?page_size=20",
        headers={"Authorization": "Bearer token"},
    )
    detail_response = client.get(
        f"/api/v1/files/{FILE_ID}",
        headers={"Authorization": "Bearer token"},
    )

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert list_response.headers["cache-control"] == "private, no-store"
    assert detail_response.headers["cache-control"] == "private, no-store"
    query_service.list_page.assert_called_once_with(ORGANIZATION_ID, None, 20)
    query_service.get.assert_called_once_with(ORGANIZATION_ID, FILE_ID)
    assert "minio" not in list_response.text.lower()
    assert "sha256" not in detail_response.text.lower()


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/files?unknown=true",
        "/api/v1/files?page_size=0",
        f"/api/v1/files/{FILE_ID}?unknown=true",
        "/api/v1/files/6F000000-0000-4000-8000-000000000003",
    ),
)
def test_file_reads_reject_unknown_or_noncanonical_inputs_without_service(
    client: TestClient,
    query_service: Mock,
    path: str,
) -> None:
    response = client.get(path, headers={"Authorization": "Bearer token"})

    assert response.status_code == 422
    query_service.get.assert_not_called()
    query_service.list_page.assert_not_called()


def test_file_openapi_freezes_all_operations(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert paths["/api/v1/files"]["post"]["operationId"] == "upload_file_v1"
    assert paths["/api/v1/files"]["get"]["operationId"] == "list_files_v1"
    assert paths["/api/v1/files/{file_id}"]["get"]["operationId"] == "get_file_v1"
    assert paths["/api/v1/files/batch"]["post"]["operationId"] == "upload_file_batch_v1"
    assert paths["/api/v1/files/{file_id}/preview"]["get"]["operationId"] == (
        "preview_file_original_v1"
    )
    assert paths["/api/v1/files/{file_id}/text-preview"]["get"]["operationId"] == (
        "preview_file_text_v1"
    )
    assert paths["/api/v1/files/{file_id}/archive"]["post"]["operationId"] == "archive_file_v1"
    assert paths["/api/v1/files/{file_id}/retry"]["post"]["operationId"] == "retry_file_job_v1"
    request_schema = paths["/api/v1/files"]["post"]["requestBody"]["content"]
    assert set(request_schema) == {"multipart/form-data"}
    assert request_schema["multipart/form-data"]["schema"]["additionalProperties"] is False
