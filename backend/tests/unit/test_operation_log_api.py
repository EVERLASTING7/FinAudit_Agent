from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.operation_logs import get_operation_log_query_service
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.operation_logs import OperationLogItemData, OperationLogListData
from app.services.auth import AuthenticatedActor, AuthService
from app.services.operation_log_query import OperationLogQueryService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("71000000-0000-4000-8000-000000000001")
ACTOR_ID = UUID("71000000-0000-4000-8000-000000000002")


@pytest.fixture
def auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        ACTOR_ID,
        ORGANIZATION_ID,
        UUID("71000000-0000-4000-8000-000000000003"),
        ("system_admin",),
        ("operations.read",),
    )
    service.authenticate.return_value = (
        actor,
        CurrentUserData(
            id=ACTOR_ID,
            display_name="操作管理员",
            roles=("system_admin",),
            permissions=("operations.read",),
        ),
    )
    return service


@pytest.fixture
def query_service() -> Mock:
    service = Mock(spec=OperationLogQueryService)
    service.list_page.return_value = OperationLogListData(
        items=(
            OperationLogItemData(
                id=UUID("71000000-0000-4000-8000-000000000004"),
                actor_kind="anonymous",
                actor_id=None,
                action_code="auth.login.failed",
                outcome="denied",
                resource_type=None,
                resource_id=None,
                trace_id=UUID("71000000-0000-4000-8000-000000000005"),
                change_summary={"failure_code": "invalid_credentials"},
                created_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
            ),
        ),
        page_size=20,
        next_cursor=None,
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
    app.dependency_overrides[get_operation_log_query_service] = lambda: query_service
    return app


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_operation_log_list_is_private_scoped_and_minimal(
    client: TestClient,
    query_service: Mock,
) -> None:
    response = client.get(
        "/api/v1/operation-logs?page_size=20",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    query_service.list_page.assert_called_once_with(ORGANIZATION_ID, None, 20)
    assert response.json()["data"]["items"][0]["actor_id"] is None
    for private_name in ("username", "password", "cookie", "reason"):
        assert private_name not in response.text.lower()


@pytest.mark.parametrize("query", ("page=1", "page_size=0", "page_size=101", "cursor=abc="))
def test_operation_log_list_rejects_unknown_or_invalid_query(
    client: TestClient,
    query_service: Mock,
    query: str,
) -> None:
    response = client.get(
        f"/api/v1/operation-logs?{query}",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    query_service.list_page.assert_not_called()


def test_operation_log_openapi_is_frozen(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/operation-logs"]["get"]
    assert operation["operationId"] == "list_operation_logs_v1"
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "cursor",
        "page_size",
    ]
    assert set(operation["responses"]) == {"200", "401", "403", "422", "503"}
