from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import ANY, Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.document_corrections import get_document_correction_service
from app.bootstrap import create_app
from app.core.errors import AppError
from app.schemas.auth import CurrentUserData
from app.schemas.document_corrections import (
    AcceptedJobData,
    DocumentCorrectionAcceptedData,
    DocumentCorrectionBlockItemData,
    DocumentCorrectionBlockListData,
    DocumentParseActivationData,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.document_correction import (
    DocumentActivationMutationResult,
    DocumentCorrectionMutationResult,
    DocumentCorrectionService,
    SecurityRevalidationMutationResult,
)
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("7f000000-0000-4000-8000-000000000001")
ACTOR_ID = UUID("7f000000-0000-4000-8000-000000000002")
BLOCK_ID = UUID("7f000000-0000-4000-8000-000000000003")
SOURCE_PARSE_ID = UUID("7f000000-0000-4000-8000-000000000004")
RESULT_PARSE_ID = UUID("7f000000-0000-4000-8000-000000000005")
CORRECTION_ID = UUID("7f000000-0000-4000-8000-000000000006")
JOB_ID = UUID("7f000000-0000-4000-8000-000000000007")
FILE_ID = UUID("7f000000-0000-4000-8000-000000000009")


@pytest.fixture
def auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        ACTOR_ID,
        ORGANIZATION_ID,
        UUID("7f000000-0000-4000-8000-000000000008"),
        ("system_admin",),
        ("files.manage", "system.configure"),
    )
    service.authenticate.return_value = (
        actor,
        CurrentUserData(
            id=ACTOR_ID,
            display_name="文档纠错管理员",
            roles=("system_admin",),
            permissions=("files.manage", "system.configure"),
        ),
    )
    return service


@pytest.fixture
def correction_service() -> Mock:
    service = Mock(spec=DocumentCorrectionService)
    service.list_blocks.return_value = DocumentCorrectionBlockListData(
        file_id=FILE_ID,
        business_type="policy",
        parse_version_id=SOURCE_PARSE_ID,
        items=(
            DocumentCorrectionBlockItemData(
                block_id=BLOCK_ID,
                page_no=1,
                block_index=0,
                block_type="paragraph",
                text_content="合成制度文本",
                reading_order=0,
                bbox=None,
            ),
        ),
        page_size=50,
        next_cursor=None,
    )
    service.correct_block.return_value = DocumentCorrectionMutationResult(
        DocumentCorrectionAcceptedData(
            correction_id=CORRECTION_ID,
            result_parse_version_id=RESULT_PARSE_ID,
            job_id=JOB_ID,
        ),
        False,
    )
    service.activate_parse.return_value = DocumentActivationMutationResult(
        DocumentParseActivationData(
            id=RESULT_PARSE_ID,
            superseded_version_id=SOURCE_PARSE_ID,
            activated_at=datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc),
        ),
        False,
    )
    service.request_security_revalidation.side_effect = AppError(
        status_code=503,
        code="SECURITY_REVALIDATION_CONFIGURATION_ERROR",
        message="资源安全重评环境尚未配置",
    )
    return service


@pytest.fixture
def application(
    exact_policy_file: Path,
    auth_service: Mock,
    correction_service: Mock,
) -> FastAPI:
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_document_correction_service] = lambda: correction_service
    return app


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_correct_document_block_contract_is_strict_and_idempotent(
    client: TestClient,
    correction_service: Mock,
) -> None:
    response = client.post(
        f"/api/v1/document-blocks/{BLOCK_ID}/correct",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "correction-key-001"},
        json={
            "field_name": "text_content",
            "after_value": "修正后的合成文本",
            "reason": "人工核对",
            "source_parse_version_id": str(SOURCE_PARSE_ID),
        },
    )

    assert response.status_code == 202
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["idempotency-replayed"] == "false"
    assert response.json()["data"] == {
        "correction_id": str(CORRECTION_ID),
        "result_parse_version_id": str(RESULT_PARSE_ID),
        "job_id": str(JOB_ID),
        "status": "queued",
    }
    correction_service.correct_block.assert_called_once_with(
        ANY,
        BLOCK_ID,
        ANY,
        "correction-key-001",
        ANY,
    )

    invalid = client.post(
        f"/api/v1/document-blocks/{BLOCK_ID}/correct",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "correction-key-002"},
        json={
            "field_name": "text_content",
            "after_value": "修正后的合成文本",
            "reason": "人工核对",
            "source_parse_version_id": str(SOURCE_PARSE_ID),
            "unexpected": True,
        },
    )
    assert invalid.status_code == 422


def test_list_document_correction_blocks_is_strict_private_and_read_only(
    client: TestClient,
    correction_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/files/{FILE_ID}/document-correction-blocks?page_size=50",
        headers={"Authorization": "Bearer token"},
    )
    invalid = client.get(
        f"/api/v1/files/{FILE_ID}/document-correction-blocks?unknown=1",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert "idempotency-replayed" not in response.headers
    assert response.json()["data"] == {
        "file_id": str(FILE_ID),
        "business_type": "policy",
        "parse_version_id": str(SOURCE_PARSE_ID),
        "items": [
            {
                "block_id": str(BLOCK_ID),
                "page_no": 1,
                "block_index": 0,
                "block_type": "paragraph",
                "text_content": "合成制度文本",
                "reading_order": 0,
                "bbox": None,
            }
        ],
        "page_size": 50,
        "next_cursor": None,
    }
    correction_service.list_blocks.assert_called_once_with(ANY, FILE_ID, None, 50)
    assert invalid.status_code == 422
    assert correction_service.list_blocks.call_count == 1


def test_activate_document_parse_and_security_revalidation_fail_closed(
    client: TestClient,
    correction_service: Mock,
) -> None:
    activated = client.post(
        f"/api/v1/document-parse-versions/{RESULT_PARSE_ID}/activate",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "activation-key-001"},
        json={"reason": "人工复核通过"},
    )
    blocked = client.post(
        f"/api/v1/document-parse-versions/{RESULT_PARSE_ID}/security-revalidations",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "security-key-001"},
        json={
            "reason": "强制重评",
            "security_policy_version": "asset-security-v1",
            "force_recheck": True,
        },
    )

    assert activated.status_code == 200
    assert activated.headers["cache-control"] == "private, no-store"
    assert activated.json()["data"] == {
        "id": str(RESULT_PARSE_ID),
        "status": "active",
        "superseded_version_id": str(SOURCE_PARSE_ID),
        "activated_at": "2026-08-18T08:00:00Z",
    }
    assert blocked.status_code == 503
    assert blocked.json()["code"] == "SECURITY_REVALIDATION_CONFIGURATION_ERROR"
    correction_service.activate_parse.assert_called_once_with(
        ANY,
        RESULT_PARSE_ID,
        ANY,
        "activation-key-001",
        ANY,
    )
    correction_service.request_security_revalidation.assert_called_once_with(
        ANY,
        RESULT_PARSE_ID,
        ANY,
        "security-key-001",
        ANY,
    )

    too_long = client.post(
        f"/api/v1/document-parse-versions/{RESULT_PARSE_ID}/security-revalidations",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "security-key-002"},
        json={
            "reason": "x" * 501,
            "security_policy_version": "asset-security-v1",
            "force_recheck": False,
        },
    )
    assert too_long.status_code == 422
    assert correction_service.request_security_revalidation.call_count == 1


def test_security_revalidation_returns_unified_accepted_job(
    client: TestClient,
    correction_service: Mock,
) -> None:
    correction_service.request_security_revalidation.side_effect = None
    correction_service.request_security_revalidation.return_value = (
        SecurityRevalidationMutationResult(
            AcceptedJobData(
                job_id=JOB_ID,
                resource_type="document_parse_version",
                resource_id=RESULT_PARSE_ID,
                next_stage="asset_security_revalidation",
            ),
            False,
        )
    )
    response = client.post(
        f"/api/v1/document-parse-versions/{SOURCE_PARSE_ID}/security-revalidations",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "security-key-003"},
        json={
            "reason": "隔离合成安全重评",
            "security_policy_version": "asset-security-v1",
            "force_recheck": True,
        },
    )
    assert response.status_code == 202
    assert response.headers["idempotency-replayed"] == "false"
    assert response.json()["data"] == {
        "job_id": str(JOB_ID),
        "resource_type": "document_parse_version",
        "resource_id": str(RESULT_PARSE_ID),
        "status": "queued",
        "stage": None,
        "next_stage": "asset_security_revalidation",
    }


def test_document_correction_openapi_freezes_four_operations(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert (
        paths["/api/v1/files/{file_id}/document-correction-blocks"]["get"]["operationId"]
        == "list_document_correction_blocks_v1"
    )
    assert (
        paths["/api/v1/document-blocks/{block_id}/correct"]["post"]["operationId"]
        == "correct_document_block_v1"
    )
    assert (
        paths["/api/v1/document-parse-versions/{parse_version_id}/activate"]["post"]["operationId"]
        == "activate_document_parse_version_v1"
    )
    assert (
        paths["/api/v1/document-parse-versions/{parse_version_id}/security-revalidations"]["post"][
            "operationId"
        ]
        == "revalidate_document_parse_assets_v1"
    )
