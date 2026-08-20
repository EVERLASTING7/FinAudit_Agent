from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import ANY, Mock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.policies import get_policy_management_service
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.policies import (
    PendingPolicyRevocationItemData,
    PendingPolicyRevocationListData,
    PolicyChunkSetData,
    PolicyData,
    PolicyListData,
    PolicyRevocationRequestData,
    PolicyStatus,
    PolicyWriteData,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.policy_management import (
    PolicyManagementService,
    PolicyMutationResult,
    PolicyRevocationRequestMutationResult,
)
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("9c000000-0000-4000-8000-000000000001")
USER_ID = UUID("9c000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("9c000000-0000-4000-8000-000000000003")
POLICY_ID = UUID("9c000000-0000-4000-8000-000000000004")
KNOWLEDGE_BASE_ID = UUID("9c000000-0000-4000-8000-000000000005")
FILE_ID = UUID("9c000000-0000-4000-8000-000000000006")
MARKDOWN_ID = UUID("9c000000-0000-4000-8000-000000000007")
CHUNK_SET_ID = UUID("9c000000-0000-4000-8000-000000000008")
REVOCATION_REQUEST_ID = UUID("9c000000-0000-4000-8000-000000000009")
NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _policy(status: PolicyStatus = PolicyStatus.DRAFT) -> PolicyData:
    submitted = status is not PolicyStatus.DRAFT
    approved = status in {
        PolicyStatus.BUSINESS_APPROVED,
        PolicyStatus.PUBLISHED,
        PolicyStatus.SUPERSEDED,
        PolicyStatus.REVOKED,
    }
    published = status in {
        PolicyStatus.PUBLISHED,
        PolicyStatus.SUPERSEDED,
        PolicyStatus.REVOKED,
    }
    return PolicyData(
        id=POLICY_ID,
        knowledge_base_id=KNOWLEDGE_BASE_ID,
        source_file_id=FILE_ID,
        policy_code="TRAVEL-001",
        name="差旅报销制度",
        version="1.0",
        issuing_department="财务部",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        scope={"country": "CN"},
        status=status,
        submitted_by=USER_ID if submitted else None,
        submitted_at=NOW if submitted else None,
        business_approved_by=USER_ID if approved else None,
        business_approved_at=NOW if approved else None,
        technical_published_by=USER_ID if published else None,
        technical_published_at=NOW if published else None,
        revoked_at=NOW if status is PolicyStatus.REVOKED else None,
        revoked_by=USER_ID if status is PolicyStatus.REVOKED else None,
        revoke_reason="制度已失效" if status is PolicyStatus.REVOKED else None,
        row_version={
            PolicyStatus.DRAFT: "1",
            PolicyStatus.SUBMITTED: "2",
            PolicyStatus.BUSINESS_APPROVED: "3",
        }.get(status, "4"),
    )


def _chunk_set() -> PolicyChunkSetData:
    return PolicyChunkSetData(
        id=CHUNK_SET_ID,
        markdown_version_id=MARKDOWN_ID,
        version_no=1,
        status="active",
        profile_version="chunk-profile-v1",
        profile_hash="a" * 64,
        chunk_count=2,
        content_manifest_hash="b" * 64,
    )


def _auth_service() -> Mock:
    service = Mock(spec=AuthService)
    permissions = (
        "files.read",
        "knowledge.approve",
        "knowledge.publish",
        "knowledge.submit",
        "knowledge.use",
    )
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("audit_reviewer", "system_admin"),
        permissions,
    )
    current = CurrentUserData(
        id=USER_ID,
        display_name="审计复核人员",
        roles=("audit_reviewer", "system_admin"),
        permissions=permissions,
    )
    service.authenticate.return_value = actor, current
    return service


def _policy_service() -> Mock:
    service = Mock(spec=PolicyManagementService)
    service.list_page.return_value = PolicyListData(
        items=(_policy(),), page_size=20, next_cursor=None
    )
    service.get_detail.return_value = _policy()
    service.create.return_value = PolicyMutationResult(
        PolicyWriteData(policy=_policy(), chunk_set=None), False, 201
    )
    service.submit.return_value = PolicyMutationResult(
        PolicyWriteData(policy=_policy(PolicyStatus.SUBMITTED), chunk_set=None),
        False,
        200,
    )
    service.approve.return_value = PolicyMutationResult(
        PolicyWriteData(
            policy=_policy(PolicyStatus.BUSINESS_APPROVED),
            chunk_set=_chunk_set(),
        ),
        False,
        200,
    )
    service.publish.return_value = PolicyMutationResult(
        PolicyWriteData(policy=_policy(PolicyStatus.PUBLISHED), chunk_set=None),
        False,
        200,
    )
    service.request_revocation.return_value = PolicyRevocationRequestMutationResult(
        PolicyRevocationRequestData(
            revocation_request_id=REVOCATION_REQUEST_ID,
            policy_id=POLICY_ID,
            status="pending_execution",
            requested_by=USER_ID,
            requested_at=NOW,
        ),
        False,
        201,
    )
    service.list_pending_revocations.return_value = PendingPolicyRevocationListData(
        items=(
            PendingPolicyRevocationItemData(
                revocation_request_id=REVOCATION_REQUEST_ID,
                policy_id=POLICY_ID,
                policy_code="TRAVEL-001",
                policy_name="差旅报销制度",
                policy_row_version="4",
                requested_by=USER_ID,
                requested_at=NOW,
            ),
        ),
        page_size=50,
        next_cursor=None,
    )
    service.revoke.return_value = PolicyMutationResult(
        PolicyWriteData(policy=_policy(PolicyStatus.REVOKED), chunk_set=None),
        False,
        200,
    )
    return service


def _application(policy_file: Path, auth: Mock, policies: Mock) -> FastAPI:
    app = create_app(build_startup_settings(policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_policy_management_service] = lambda: policies
    return app


def test_policy_reads_and_write_lifecycle_are_private_and_idempotent(
    exact_policy_file: Path,
) -> None:
    auth = _auth_service()
    policies = _policy_service()
    with TestClient(_application(exact_policy_file, auth, policies)) as client:
        listing = client.get(
            "/api/v1/policy-documents?page_size=20",
            headers={"Authorization": "Bearer token"},
        )
        detail = client.get(
            f"/api/v1/policy-documents/{POLICY_ID}",
            headers={"Authorization": "Bearer token"},
        )
        created = client.post(
            "/api/v1/policy-documents",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "policy-create-001",
            },
            json={
                "knowledge_base_id": str(KNOWLEDGE_BASE_ID),
                "source_file_id": str(FILE_ID),
                "policy_code": "TRAVEL-001",
                "name": "差旅报销制度",
                "version": "1.0",
                "issuing_department": "财务部",
                "effective_from": "2026-01-01",
                "effective_to": None,
                "scope": {"country": "CN"},
            },
        )
        submitted = client.post(
            f"/api/v1/policy-documents/{POLICY_ID}/submit-review",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "policy-submit-001",
            },
            json={"row_version": "1", "reason": "提交独立审批"},
        )
        approved = client.post(
            f"/api/v1/policy-documents/{POLICY_ID}/approve",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "policy-approve-001",
            },
            json={"row_version": "2", "reason": "独立审批通过"},
        )
        published = client.post(
            f"/api/v1/policy-documents/{POLICY_ID}/publish",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "policy-publish-001",
            },
            json={"row_version": "3", "reason": "正式评测通过后技术发布"},
        )
        revocation_requested = client.post(
            f"/api/v1/policy-documents/{POLICY_ID}/revocation-requests",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "policy-revoke-request-001",
            },
            json={"row_version": "4", "reason": "制度已由新版本替代"},
        )
        pending_revocations = client.get(
            f"/api/v1/policy-documents/revocation-requests?knowledge_base_id={KNOWLEDGE_BASE_ID}",
            headers={"Authorization": "Bearer token"},
        )
        revoked = client.post(
            f"/api/v1/policy-documents/{POLICY_ID}/revoke",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "policy-revoke-001",
            },
            json={
                "row_version": "4",
                "revocation_request_id": str(REVOCATION_REQUEST_ID),
                "reason": "执行独立撤销确认",
            },
        )

    for response in (
        listing,
        detail,
        created,
        submitted,
        approved,
        published,
        revocation_requested,
        pending_revocations,
        revoked,
    ):
        assert response.status_code in {200, 201}, response.text
        assert response.headers["cache-control"] == "private, no-store"
    for response in (created, submitted, approved, published, revocation_requested, revoked):
        assert response.headers["idempotency-replayed"] == "false"
    assert approved.json()["data"]["chunk_set"]["id"] == str(CHUNK_SET_ID)
    assert pending_revocations.json()["data"]["items"] == [
        {
            "revocation_request_id": str(REVOCATION_REQUEST_ID),
            "policy_id": str(POLICY_ID),
            "policy_code": "TRAVEL-001",
            "policy_name": "差旅报销制度",
            "policy_row_version": "4",
            "requested_by": str(USER_ID),
            "requested_at": "2026-08-14T00:00:00Z",
        }
    ]
    policies.list_page.assert_called_once_with(ANY, None, 20, knowledge_base_id=None)
    policies.get_detail.assert_called_once_with(ANY, POLICY_ID)
    policies.create.assert_called_once_with(ANY, ANY, "policy-create-001", ANY)
    policies.submit.assert_called_once_with(ANY, POLICY_ID, ANY, "policy-submit-001", ANY)
    policies.approve.assert_called_once_with(ANY, POLICY_ID, ANY, "policy-approve-001", ANY)
    policies.publish.assert_called_once_with(ANY, POLICY_ID, ANY, "policy-publish-001", ANY)
    policies.request_revocation.assert_called_once_with(
        ANY,
        POLICY_ID,
        ANY,
        "policy-revoke-request-001",
        ANY,
    )
    policies.list_pending_revocations.assert_called_once_with(
        ANY,
        KNOWLEDGE_BASE_ID,
        None,
        50,
    )
    policies.revoke.assert_called_once_with(ANY, POLICY_ID, ANY, "policy-revoke-001", ANY)


def test_policy_permission_and_schema_fail_before_service(exact_policy_file: Path) -> None:
    auth = _auth_service()
    policies = _policy_service()
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("contract_admin",),
        ("knowledge.use",),
    )
    auth.authenticate.return_value = actor, auth.authenticate.return_value[1]
    with TestClient(_application(exact_policy_file, auth, policies)) as client:
        forbidden = client.post(
            f"/api/v1/policy-documents/{POLICY_ID}/approve",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "policy-denied-001",
            },
            json={"row_version": "2", "reason": "越权审批"},
        )
        assert forbidden.status_code == 403

        pending_forbidden = client.get(
            f"/api/v1/policy-documents/revocation-requests?knowledge_base_id={KNOWLEDGE_BASE_ID}",
            headers={"Authorization": "Bearer token"},
        )
        assert pending_forbidden.status_code == 403

        auth.authenticate.return_value = _auth_service().authenticate.return_value
        invalid = client.post(
            f"/api/v1/policy-documents/{POLICY_ID}/submit-review",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "policy-invalid-001",
            },
            json={"row_version": "1", "reason": "提交", "unknown": True},
        )
        assert invalid.status_code == 422
        invalid_pending = client.get(
            "/api/v1/policy-documents/revocation-requests?unknown=1",
            headers={"Authorization": "Bearer token"},
        )
        assert invalid_pending.status_code == 422
    policies.approve.assert_not_called()
    policies.submit.assert_not_called()
    policies.list_pending_revocations.assert_not_called()


def test_policy_openapi_freezes_runtime_paths(exact_policy_file: Path) -> None:
    with TestClient(_application(exact_policy_file, _auth_service(), _policy_service())) as client:
        paths = client.get("/openapi.json").json()["paths"]
    expected = {
        ("/api/v1/policy-documents", "get"): "list_policy_documents_v1",
        ("/api/v1/policy-documents", "post"): "create_policy_document_v1",
        (
            "/api/v1/policy-documents/revocation-requests",
            "get",
        ): "list_pending_policy_revocation_requests_v1",
        ("/api/v1/policy-documents/{policy_id}", "get"): "get_policy_document_v1",
        (
            "/api/v1/policy-documents/{policy_id}/submit-review",
            "post",
        ): "submit_policy_document_v1",
        (
            "/api/v1/policy-documents/{policy_id}/approve",
            "post",
        ): "approve_policy_document_v1",
        (
            "/api/v1/policy-documents/{policy_id}/publish",
            "post",
        ): "publish_policy_document_v1",
        (
            "/api/v1/policy-documents/{policy_id}/revocation-requests",
            "post",
        ): "request_policy_document_revocation_v1",
        (
            "/api/v1/policy-documents/{policy_id}/revoke",
            "post",
        ): "revoke_policy_document_v1",
    }
    for (path, method), operation_id in expected.items():
        assert paths[path][method]["operationId"] == operation_id
    for path, method in (key for key in expected if key[1] == "post"):
        assert "Idempotency-Key" in {
            parameter["name"] for parameter in paths[path][method]["parameters"]
        }
