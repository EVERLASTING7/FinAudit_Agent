from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import ANY, Mock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.audits import get_audit_management_service
from app.api.dependencies.auth import get_auth_service
from app.bootstrap import create_app
from app.schemas.audits import (
    AuditExecutionData,
    AuditExecutionMutationData,
    AuditRiskData,
    AuditRiskMutationData,
    AuditTaskData,
    AuditTaskDetailData,
    AuditTaskListData,
    AuditTaskMutationData,
)
from app.schemas.auth import CurrentUserData
from app.services.audit_management import (
    AuditExecutionMutationResult,
    AuditManagementService,
    AuditRiskMutationResult,
    AuditTaskMutationResult,
)
from app.services.auth import AuthenticatedActor, AuthService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("a5000000-0000-4000-8000-000000000001")
USER_ID = UUID("a5000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("a5000000-0000-4000-8000-000000000003")
TASK_ID = UUID("a5000000-0000-4000-8000-000000000004")
EXECUTION_ID = UUID("a5000000-0000-4000-8000-000000000005")
JOB_ID = UUID("a5000000-0000-4000-8000-000000000006")
RISK_ID = UUID("a5000000-0000-4000-8000-000000000007")
CONTRACT_ID = UUID("a5000000-0000-4000-8000-000000000008")
INVOICE_ID = UUID("a5000000-0000-4000-8000-000000000009")
NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)

_ALL_PERMISSIONS = (
    "audits.complete",
    "audits.create",
    "audits.read",
    "risks.review_high",
    "risks.review_non_high",
)


def _task() -> AuditTaskData:
    return AuditTaskData(
        id=TASK_ID,
        task_no="AUDIT-API-001",
        name="审核 API 合同验证",
        description="仅使用脱敏合成数据",
        owner_id=USER_ID,
        current_execution_id=EXECUTION_ID,
        status="open",
        row_version="2",
        created_at=NOW,
        updated_at=NOW,
    )


def _execution() -> AuditExecutionData:
    return AuditExecutionData(
        id=EXECUTION_ID,
        audit_task_id=TASK_ID,
        version_no=1,
        baseline_date=date(2026, 8, 14),
        status="queued",
        snapshot_sha256="a" * 64,
        job_id=JOB_ID,
        finance_reviewer_id=None,
        finance_reviewed_at=None,
        audit_reviewer_id=None,
        audit_reviewed_at=None,
        retryable=False,
        failure_code=None,
        cancel_reason=None,
        return_reason=None,
        row_version="3",
        created_at=NOW,
        started_at=None,
        finished_at=None,
        outdated_at=None,
    )


def _risk() -> AuditRiskData:
    return AuditRiskData(
        id=RISK_ID,
        rule_code="RULE-001",
        title="主合同校验",
        original_level="high",
        effective_level="high",
        review_status="pending",
        actual_value="missing",
        expected_value="confirmed",
        review_reason=None,
        reviewed_by=None,
        reviewed_at=None,
        row_version="1",
    )


def _auth_service(*, permissions: tuple[str, ...] = _ALL_PERMISSIONS) -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("audit_reviewer",),
        permissions,
    )
    current = CurrentUserData(
        id=USER_ID,
        display_name="审计复核员",
        roles=("audit_reviewer",),
        permissions=permissions,
    )
    service.authenticate.return_value = actor, current
    return service


def _audit_service() -> Mock:
    service = Mock(spec=AuditManagementService)
    task_mutation = AuditTaskMutationData(task=_task(), execution=_execution())
    execution_mutation = AuditExecutionMutationData(execution=_execution())
    risk_mutation = AuditRiskMutationData(risk=_risk())
    service.list_tasks.return_value = AuditTaskListData(
        items=(_task(),),
        page_size=20,
        next_cursor=None,
    )
    service.get_task.return_value = AuditTaskDetailData(
        task=_task(),
        execution=_execution(),
        rules=(),
        risks=(_risk(),),
    )
    service.get_execution.return_value = execution_mutation
    service.create_task.return_value = AuditTaskMutationResult(task_mutation, False, 202)
    service.create_execution.return_value = AuditTaskMutationResult(task_mutation, False, 202)
    service.review_risk.return_value = AuditRiskMutationResult(risk_mutation, False)
    service.finance_review.return_value = AuditExecutionMutationResult(
        execution_mutation,
        False,
    )
    service.audit_review.return_value = AuditExecutionMutationResult(
        execution_mutation,
        False,
    )
    service.cancel_execution.return_value = AuditExecutionMutationResult(
        execution_mutation,
        False,
    )
    return service


def _application(policy_file: Path, auth: Mock, audits: Mock) -> FastAPI:
    app = create_app(build_startup_settings(policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_audit_management_service] = lambda: audits
    return app


def _headers(key: str | None = None) -> dict[str, str]:
    values = {"Authorization": "Bearer token"}
    if key is not None:
        values["Idempotency-Key"] = key
    return values


def test_audit_reads_are_private_and_organization_scoped(exact_policy_file: Path) -> None:
    audits = _audit_service()
    with TestClient(_application(exact_policy_file, _auth_service(), audits)) as client:
        listing = client.get("/api/v1/audit-tasks?page_size=20", headers=_headers())
        detail = client.get(f"/api/v1/audit-tasks/{TASK_ID}", headers=_headers())
        execution = client.get(
            f"/api/v1/audit-executions/{EXECUTION_ID}",
            headers=_headers(),
        )
    assert [response.status_code for response in (listing, detail, execution)] == [200, 200, 200]
    assert all(
        response.headers["cache-control"] == "private, no-store"
        for response in (listing, detail, execution)
    )
    audits.list_tasks.assert_called_once_with(ORGANIZATION_ID, None, 20)
    audits.get_task.assert_called_once_with(ORGANIZATION_ID, TASK_ID)
    audits.get_execution.assert_called_once_with(ORGANIZATION_ID, EXECUTION_ID)


def test_audit_create_and_reaudit_are_accepted_and_idempotent(exact_policy_file: Path) -> None:
    audits = _audit_service()
    body = {
        "task_no": "AUDIT-API-001",
        "name": "审核 API 合同验证",
        "description": "仅使用脱敏合成数据",
        "baseline_date": "2026-08-14",
        "contract_id": str(CONTRACT_ID),
        "invoice_ids": [str(INVOICE_ID)],
    }
    with TestClient(_application(exact_policy_file, _auth_service(), audits)) as client:
        created = client.post(
            "/api/v1/audit-tasks",
            headers=_headers("audit-create-01"),
            json=body,
        )
        reaudit = client.post(
            f"/api/v1/audit-tasks/{TASK_ID}/executions",
            headers=_headers("audit-reaudit-01"),
            json={
                "task_row_version": "2",
                "baseline_date": "2026-08-15",
                "reason": "关键事实变化后重审",
            },
        )
    assert created.status_code == 202, created.text
    assert reaudit.status_code == 202, reaudit.text
    assert created.headers["idempotency-replayed"] == "false"
    assert reaudit.headers["idempotency-replayed"] == "false"
    assert created.json()["data"]["execution"]["snapshot_sha256"] == "a" * 64
    audits.create_task.assert_called_once_with(ANY, ANY, "audit-create-01", ANY)
    audits.create_execution.assert_called_once_with(
        ANY,
        TASK_ID,
        ANY,
        "audit-reaudit-01",
        ANY,
    )


def test_audit_review_and_cancel_routes_preserve_lane_and_idempotency(
    exact_policy_file: Path,
) -> None:
    audits = _audit_service()
    requests = (
        (
            f"/api/v1/audit-risks/{RISK_ID}/reviews/non-high",
            "audit-risk-non-high-01",
            {"row_version": "1", "decision": "confirmed", "reason": "财务确认"},
        ),
        (
            f"/api/v1/audit-risks/{RISK_ID}/reviews/high",
            "audit-risk-high-01",
            {"row_version": "1", "decision": "confirmed", "reason": "审计确认"},
        ),
        (
            f"/api/v1/audit-executions/{EXECUTION_ID}/finance-review",
            "audit-finance-review-01",
            {"row_version": "3", "decision": "submit", "reason": "提交审计复核"},
        ),
        (
            f"/api/v1/audit-executions/{EXECUTION_ID}/audit-review",
            "audit-high-review-01",
            {"row_version": "3", "decision": "complete", "reason": "完成独立复核"},
        ),
        (
            f"/api/v1/audit-executions/{EXECUTION_ID}/cancel",
            "audit-cancel-01",
            {"row_version": "3", "reason": "取消排队执行"},
        ),
    )
    with TestClient(_application(exact_policy_file, _auth_service(), audits)) as client:
        responses = tuple(
            client.post(path, headers=_headers(key), json=body) for path, key, body in requests
        )
    assert all(response.status_code == 200 for response in responses)
    assert all(response.headers["idempotency-replayed"] == "false" for response in responses)
    assert audits.review_risk.call_count == 2
    assert audits.review_risk.call_args_list[0].kwargs == {"high_risk": False}
    assert audits.review_risk.call_args_list[1].kwargs == {"high_risk": True}
    audits.finance_review.assert_called_once_with(
        ANY,
        EXECUTION_ID,
        ANY,
        "audit-finance-review-01",
        ANY,
    )
    audits.audit_review.assert_called_once_with(
        ANY,
        EXECUTION_ID,
        ANY,
        "audit-high-review-01",
        ANY,
    )
    audits.cancel_execution.assert_called_once_with(
        ANY,
        EXECUTION_ID,
        ANY,
        "audit-cancel-01",
        ANY,
    )


def test_audit_permissions_and_strict_bodies_fail_before_service(
    exact_policy_file: Path,
) -> None:
    audits = _audit_service()
    auth = _auth_service(permissions=("audits.read",))
    with TestClient(_application(exact_policy_file, auth, audits)) as client:
        forbidden = client.post(
            "/api/v1/audit-tasks",
            headers=_headers("audit-forbidden-01"),
            json={
                "task_no": "AUDIT-API-001",
                "name": "越权创建",
                "baseline_date": "2026-08-14",
                "invoice_ids": [str(INVOICE_ID)],
            },
        )
        assert forbidden.status_code == 403

        auth.authenticate.return_value = _auth_service().authenticate.return_value
        invalid = client.post(
            f"/api/v1/audit-executions/{EXECUTION_ID}/cancel",
            headers=_headers("audit-invalid-01"),
            json={"row_version": "3", "reason": "非法字段", "unknown": True},
        )
        assert invalid.status_code == 422
    audits.create_task.assert_not_called()
    audits.cancel_execution.assert_not_called()


def test_audit_openapi_freezes_all_operations(exact_policy_file: Path) -> None:
    app = _application(exact_policy_file, _auth_service(), _audit_service())
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/v1/audit-tasks": {
            "get": "list_audit_tasks_v1",
            "post": "create_audit_task_v1",
        },
        "/api/v1/audit-tasks/{task_id}": {"get": "get_audit_task_v1"},
        "/api/v1/audit-tasks/{task_id}/executions": {"post": "create_audit_execution_v1"},
        "/api/v1/audit-executions/{execution_id}": {"get": "get_audit_execution_v1"},
        "/api/v1/audit-risks/{risk_id}/reviews/non-high": {"post": "review_non_high_audit_risk_v1"},
        "/api/v1/audit-risks/{risk_id}/reviews/high": {"post": "review_high_audit_risk_v1"},
        "/api/v1/audit-executions/{execution_id}/finance-review": {
            "post": "complete_finance_audit_review_v1"
        },
        "/api/v1/audit-executions/{execution_id}/audit-review": {
            "post": "complete_high_audit_review_v1"
        },
        "/api/v1/audit-executions/{execution_id}/cancel": {"post": "cancel_audit_execution_v1"},
    }
    for path, methods in expected.items():
        for method, operation_id in methods.items():
            assert paths[path][method]["operationId"] == operation_id
            if method == "post":
                assert "Idempotency-Key" in {
                    parameter["name"] for parameter in paths[path][method]["parameters"]
                }
