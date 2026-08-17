from collections.abc import Iterator
from pathlib import Path
from unittest.mock import ANY, Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.users import (
    get_user_management_service,
    get_user_query_service,
)
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.users import UserListData, UserListItemData
from app.services.auth import AuthenticatedActor, AuthService
from app.services.user_management import UserManagementService, UserMutationResult
from app.services.user_query import UserQueryService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("7c000000-0000-4000-8000-000000000001")
USER_ID = UUID("7c000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("7c000000-0000-4000-8000-000000000003")


@pytest.fixture
def auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("system_admin",),
        ("users.manage",),
    )
    current = CurrentUserData(
        id=USER_ID,
        display_name="平台管理员",
        roles=("system_admin",),
        permissions=("users.manage",),
    )
    service.authenticate.return_value = (actor, current)
    return service


@pytest.fixture
def user_query_service() -> Mock:
    service = Mock(spec=UserQueryService)
    service.list_page.return_value = UserListData(
        items=(
            UserListItemData(
                id=USER_ID,
                username="admin.ops",
                display_name="平台管理员",
                status="active",
                fixed_roles=("system_admin",),
                row_version="3",
            ),
        ),
        page_size=20,
        next_cursor=None,
    )
    return service


@pytest.fixture
def user_management_service() -> Mock:
    service = Mock(spec=UserManagementService)
    item = UserListItemData(
        id=USER_ID,
        username="admin.ops",
        display_name="平台管理员",
        status="active",
        fixed_roles=("system_admin",),
        row_version="3",
    )
    service.create_user.return_value = UserMutationResult(item, 201, False)
    service.update_status.return_value = UserMutationResult(item, 200, False)
    service.reset_password.return_value = UserMutationResult(item, 200, False)
    service.replace_roles.return_value = UserMutationResult(item, 200, False)
    return service


@pytest.fixture
def application(
    exact_policy_file: Path,
    auth_service: Mock,
    user_query_service: Mock,
    user_management_service: Mock,
) -> FastAPI:
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_user_query_service] = lambda: user_query_service
    app.dependency_overrides[get_user_management_service] = lambda: user_management_service
    return app


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_user_list_is_actor_scoped_exact_and_private(
    client: TestClient,
    user_query_service: Mock,
) -> None:
    response = client.get(
        "/api/v1/users?page_size=20",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    user_query_service.list_page.assert_called_once_with(ORGANIZATION_ID, None, 20)
    assert response.json()["data"] == {
        "items": [
            {
                "id": str(USER_ID),
                "username": "admin.ops",
                "display_name": "平台管理员",
                "status": "active",
                "fixed_roles": ["system_admin"],
                "row_version": "3",
            }
        ],
        "page_size": 20,
        "next_cursor": None,
    }
    for private_name in (
        "organization_id",
        "email",
        "password_hash",
        "locked_until",
        "force_change_on_login",
        "permissions",
    ):
        assert private_name not in response.text


@pytest.mark.parametrize(
    "query",
    ["page=1", "sort=username", "status=active", "page_size=0", "page_size=101", "cursor=abc="],
)
def test_user_list_rejects_unknown_or_invalid_query_without_service(
    client: TestClient,
    user_query_service: Mock,
    query: str,
) -> None:
    response = client.get(
        f"/api/v1/users?{query}",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    user_query_service.list_page.assert_not_called()


def test_user_list_requires_users_manage_before_service(
    client: TestClient,
    auth_service: Mock,
    user_query_service: Mock,
) -> None:
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("system_admin", "read_only"),
        ("operations.read",),
    )
    auth_service.authenticate.return_value = (actor, auth_service.authenticate.return_value[1])

    response = client.get(
        "/api/v1/users",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    user_query_service.list_page.assert_not_called()


def test_user_list_requires_bearer_authentication(
    client: TestClient,
    user_query_service: Mock,
) -> None:
    response = client.get("/api/v1/users")

    assert response.status_code == 401
    user_query_service.list_page.assert_not_called()


def test_user_list_reports_unconfigured_service(application: FastAPI) -> None:
    application.dependency_overrides.pop(get_user_query_service)
    with TestClient(application) as client:
        response = client.get(
            "/api/v1/users",
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "USER_DIRECTORY_NOT_CONFIGURED"


def test_user_list_redacts_invalid_projection(
    application: FastAPI,
    user_query_service: Mock,
) -> None:
    with pytest.raises(ValidationError) as captured:
        UserListData(items="sentinel-private", page_size=20)  # type: ignore[arg-type]
    user_query_service.list_page.side_effect = captured.value
    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/v1/users",
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "sentinel" not in response.text
    assert "private" not in response.text


def test_user_list_openapi_freezes_operation(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/users"]["get"]

    assert operation["operationId"] == "list_users_v1"
    assert operation["summary"] == "读取用户列表"
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "cursor",
        "page_size",
    ]
    assert set(operation["responses"]) == {"200", "401", "403", "422", "503"}


def test_create_user_requires_idempotency_and_returns_private_projection(
    client: TestClient,
    user_management_service: Mock,
) -> None:
    response = client.post(
        "/api/v1/users",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "create-user-001",
        },
        json={
            "username": "new.user",
            "display_name": "新用户",
            "initial_password": "Strong-Initial-Password-2026!",
            "fixed_roles": ["read_only"],
        },
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["idempotency-replayed"] == "false"
    assert "password" not in response.text
    user_management_service.create_user.assert_called_once_with(
        ANY,
        ANY,
        "create-user-001",
        ANY,
    )
    args = user_management_service.create_user.call_args.args
    assert args[0].organization_id == ORGANIZATION_ID
    assert args[1].fixed_roles == ("read_only",)
    assert isinstance(args[3], UUID)


@pytest.mark.parametrize(
    ("method", "path", "body", "service_method"),
    (
        (
            "patch",
            f"/api/v1/users/{USER_ID}/status",
            {"status": "disabled", "row_version": "3"},
            "update_status",
        ),
        (
            "post",
            f"/api/v1/users/{USER_ID}/password/reset",
            {"new_password": "Strong-Reset-Password-2026!", "row_version": "3"},
            "reset_password",
        ),
        (
            "put",
            f"/api/v1/users/{USER_ID}/roles",
            {"fixed_roles": ["read_only"], "row_version": "3"},
            "replace_roles",
        ),
    ),
)
def test_user_mutations_forward_canonical_target_and_cas(
    client: TestClient,
    user_management_service: Mock,
    method: str,
    path: str,
    body: dict[str, object],
    service_method: str,
) -> None:
    response = client.request(
        method,
        path,
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": f"{service_method}-001",
        },
        json=body,
    )

    assert response.status_code == 200
    called = getattr(user_management_service, service_method)
    called.assert_called_once()
    args = called.call_args.args
    assert args[0].organization_id == ORGANIZATION_ID
    assert args[1] == USER_ID
    assert args[2].row_version == "3"
    assert args[3] == f"{service_method}-001"
    assert isinstance(args[4], UUID)


@pytest.mark.parametrize(
    ("path", "headers", "body"),
    (
        (
            "/api/v1/users",
            {"Authorization": "Bearer token"},
            {
                "username": "new.user",
                "display_name": "新用户",
                "initial_password": "Strong-Initial-Password-2026!",
                "fixed_roles": ["read_only"],
            },
        ),
        (
            "/api/v1/users?unexpected=true",
            {
                "Authorization": "Bearer token",
                "Idempotency-Key": "create-user-002",
            },
            {
                "username": "new.user",
                "display_name": "新用户",
                "initial_password": "Strong-Initial-Password-2026!",
                "fixed_roles": ["read_only"],
            },
        ),
        (
            "/api/v1/users",
            {
                "Authorization": "Bearer token",
                "Idempotency-Key": "create-user-003",
            },
            {
                "username": "new.user",
                "display_name": "新用户",
                "initial_password": "Strong-Initial-Password-2026!",
                "fixed_roles": ["read_only"],
                "organization_id": str(ORGANIZATION_ID),
            },
        ),
    ),
)
def test_user_create_rejects_missing_key_or_unknown_inputs_without_service(
    client: TestClient,
    user_management_service: Mock,
    path: str,
    headers: dict[str, str],
    body: dict[str, object],
) -> None:
    response = client.post(path, headers=headers, json=body)

    assert response.status_code == 422
    user_management_service.create_user.assert_not_called()


def test_user_write_openapi_freezes_four_operations(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    operations = {
        "create_user_v1": paths["/api/v1/users"]["post"],
        "update_user_status_v1": paths["/api/v1/users/{user_id}/status"]["patch"],
        "reset_user_password_v1": paths["/api/v1/users/{user_id}/password/reset"]["post"],
        "replace_user_roles_v1": paths["/api/v1/users/{user_id}/roles"]["put"],
    }

    assert {operation["operationId"] for operation in operations.values()} == set(operations)
    for operation in operations.values():
        parameters = {parameter["name"] for parameter in operation["parameters"]}
        assert "Idempotency-Key" in parameters
        assert set(operation["responses"]).issuperset({"401", "403", "404", "409", "422", "503"})
