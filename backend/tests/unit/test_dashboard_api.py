from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.dashboard import get_dashboard_service
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.dashboard import (
    DashboardAuditSection,
    DashboardAuditTaskItem,
    DashboardData,
    DashboardFailedJobItem,
    DashboardFailedJobSection,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.dashboard import DashboardService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("7a000000-0000-4000-8000-000000000001")
USER_ID = UUID("7a000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("7a000000-0000-4000-8000-000000000003")
TASK_ID = UUID("7a000000-0000-4000-8000-000000000004")
EXECUTION_ID = UUID("7a000000-0000-4000-8000-000000000005")
JOB_ID = UUID("7a000000-0000-4000-8000-000000000006")
RESOURCE_ID = UUID("7a000000-0000-4000-8000-000000000007")
NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def _auth_service(permissions: tuple[str, ...]) -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("finance_reviewer",),
        permissions,
    )
    current = CurrentUserData(
        id=USER_ID,
        display_name="工作台用户",
        roles=("finance_reviewer",),
        permissions=permissions,
    )
    service.authenticate.return_value = actor, current
    return service


def _application(policy_file: Path, auth: Mock, dashboard: Mock) -> FastAPI:
    app = create_app(build_startup_settings(policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_dashboard_service] = lambda: dashboard
    return app


def test_dashboard_returns_private_permission_trimmed_summary(
    exact_policy_file: Path,
) -> None:
    service = Mock(spec=DashboardService)
    service.read.return_value = DashboardData(
        item_limit=5,
        audit_tasks=DashboardAuditSection(
            open_count=1,
            pending_review_count=1,
            items=(
                DashboardAuditTaskItem(
                    id=TASK_ID,
                    task_no="AUDIT-001",
                    name="月度审核",
                    status="open",
                    current_execution_id=EXECUTION_ID,
                    updated_at=NOW,
                ),
            ),
        ),
        files=None,
        failed_jobs=None,
    )
    auth = _auth_service(("audits.read",))
    with TestClient(_application(exact_policy_file, auth, service)) as client:
        response = client.get(
            "/api/v1/dashboard?item_limit=5",
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["data"]["audit_tasks"]["items"][0]["task_no"] == "AUDIT-001"
    assert response.json()["data"]["failed_jobs"] is None
    service.read.assert_called_once_with(auth.authenticate.return_value[0], 5)


def test_dashboard_failed_jobs_exclude_error_message_and_input(
    exact_policy_file: Path,
) -> None:
    service = Mock(spec=DashboardService)
    service.read.return_value = DashboardData(
        item_limit=5,
        audit_tasks=None,
        files=None,
        failed_jobs=DashboardFailedJobSection(
            failed_count=1,
            items=(
                DashboardFailedJobItem(
                    id=JOB_ID,
                    job_type="file_process",
                    resource_type="file",
                    resource_id=RESOURCE_ID,
                    status="failed",
                    stage="parse",
                    attempt_no=3,
                    max_attempts=3,
                    error_code="DEPENDENCY_UNAVAILABLE",
                    next_retry_at=None,
                    created_at=NOW,
                    row_version="4",
                ),
            ),
        ),
    )
    with TestClient(
        _application(exact_policy_file, _auth_service(("jobs.recover",)), service)
    ) as client:
        response = client.get(
            "/api/v1/dashboard",
            headers={"Authorization": "Bearer token"},
        )

    payload = response.json()["data"]["failed_jobs"]["items"][0]
    assert payload["error_code"] == "DEPENDENCY_UNAVAILABLE"
    assert "error_message" not in payload
    assert "input_json" not in payload


def test_dashboard_rejects_unknown_query_and_freezes_openapi(
    exact_policy_file: Path,
) -> None:
    service = Mock(spec=DashboardService)
    app = _application(exact_policy_file, _auth_service(("audits.read",)), service)
    with TestClient(app) as client:
        invalid = client.get(
            "/api/v1/dashboard?unknown=true",
            headers={"Authorization": "Bearer token"},
        )
        paths = client.get("/openapi.json").json()["paths"]

    assert invalid.status_code == 422
    service.read.assert_not_called()
    assert paths["/api/v1/dashboard"]["get"]["operationId"] == "get_dashboard_summary_v1"
