from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.ai_call_audit import get_ai_call_audit_query_service
from app.api.dependencies.auth import get_auth_service
from app.bootstrap import create_app
from app.core.errors import AppError
from app.schemas.ai_call_audit import AiCallAttemptData, AiCallAuditSummaryData
from app.schemas.auth import CurrentUserData
from app.services.ai_call_audit_query import AiCallAuditQueryService
from app.services.auth import AuthenticatedActor, AuthService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

_ORGANIZATION_ID = UUID("81000000-0000-4000-8000-000000000001")
_ACTOR_ID = UUID("81000000-0000-4000-8000-000000000002")
_OPERATION_ID = UUID("81000000-0000-4000-8000-000000000003")


@pytest.fixture
def auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        _ACTOR_ID,
        _ORGANIZATION_ID,
        UUID("81000000-0000-4000-8000-000000000004"),
        ("system_admin",),
        ("operations.read",),
    )
    service.authenticate.return_value = (
        actor,
        CurrentUserData(
            id=_ACTOR_ID,
            display_name="AI 审计管理员",
            roles=("system_admin",),
            permissions=("operations.read",),
        ),
    )
    return service


@pytest.fixture
def query_service() -> Mock:
    service = Mock(spec=AiCallAuditQueryService)
    service.get_summary.return_value = AiCallAuditSummaryData(
        business_operation_id=_OPERATION_ID,
        attempt_count=1,
        reserved_input_tokens=5000,
        reserved_output_tokens=2500,
        reserved_cost_micro_usd=5000,
        actual_input_tokens=100,
        actual_output_tokens=20,
        attempts=(
            AiCallAttemptData(
                event_id=UUID("81000000-0000-4000-8000-000000000005"),
                provider_attempt_no=1,
                logical_generation_no=1,
                model_id="MiniMax-M3",
                is_fallback=False,
                status="succeeded",
                reserved_input_tokens=5000,
                reserved_output_tokens=2500,
                reserved_cost_micro_usd=5000,
                input_tokens=100,
                output_tokens=20,
                trace_id=UUID("81000000-0000-4000-8000-000000000006"),
                started_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
                completed_at=datetime(2026, 8, 16, 0, 0, 1, tzinfo=timezone.utc),
                safe_error_code=None,
            ),
        ),
    )
    return service


@pytest.fixture
def application(
    exact_policy_file: Path,
    auth_service: Mock,
    query_service: Mock,
) -> FastAPI:
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_ai_call_audit_query_service] = lambda: query_service
    return app


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_ops_005_is_private_organization_scoped_and_redacted(
    client: TestClient,
    query_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/ai-call-logs?business_operation_id={_OPERATION_ID}",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    query_service.get_summary.assert_called_once_with(_ORGANIZATION_ID, _OPERATION_ID)
    assert response.json()["data"]["attempts"][0]["model_id"] == "MiniMax-M3"
    for forbidden in ("api_key", "prompt", "input_hash", "output_hash", "document"):
        assert forbidden not in response.text.lower()


@pytest.mark.parametrize("query", ("", "business_operation_id=bad", "page=1"))
def test_ops_005_rejects_missing_invalid_or_unknown_query(
    client: TestClient,
    query_service: Mock,
    query: str,
) -> None:
    suffix = f"?{query}" if query else ""
    response = client.get(
        f"/api/v1/ai-call-logs{suffix}",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    query_service.get_summary.assert_not_called()


def test_ops_005_preserves_existence_hiding_404(
    client: TestClient,
    query_service: Mock,
) -> None:
    query_service.get_summary.side_effect = AppError(
        status_code=404,
        code="AI_CALL_AUDIT_NOT_FOUND",
        message="AI 调用摘要不存在或无权访问",
    )

    response = client.get(
        f"/api/v1/ai-call-logs?business_operation_id={_OPERATION_ID}",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "AI_CALL_AUDIT_NOT_FOUND"


def test_ops_005_openapi_is_frozen(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/ai-call-logs"]["get"]
    assert operation["operationId"] == "get_ai_call_audit_summary_v1"
    assert [parameter["name"] for parameter in operation["parameters"]] == ["business_operation_id"]
    assert set(operation["responses"]) == {"200", "401", "403", "404", "422", "503"}
