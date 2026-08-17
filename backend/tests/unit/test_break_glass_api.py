from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import ANY, Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.break_glass import get_break_glass_service
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.break_glass import BreakGlassData
from app.services.auth import AuthenticatedActor, AuthService
from app.services.break_glass import BreakGlassMutationResult, BreakGlassService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("7e000000-0000-4000-8000-000000000001")
ACTOR_ID = UUID("7e000000-0000-4000-8000-000000000002")
TARGET_ID = UUID("7e000000-0000-4000-8000-000000000003")
REQUEST_ID = UUID("7e000000-0000-4000-8000-000000000004")


@pytest.fixture
def auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        ACTOR_ID,
        ORGANIZATION_ID,
        UUID("7e000000-0000-4000-8000-000000000005"),
        ("system_admin",),
        ("temporary_roles.decide", "temporary_roles.request"),
    )
    service.authenticate.return_value = (
        actor,
        CurrentUserData(
            id=ACTOR_ID,
            display_name="临时授权管理员",
            roles=("system_admin",),
            permissions=("temporary_roles.decide", "temporary_roles.request"),
        ),
    )
    return service


@pytest.fixture
def break_glass_service() -> Mock:
    service = Mock(spec=BreakGlassService)
    data = BreakGlassData(
        id=REQUEST_ID,
        target_user_id=TARGET_ID,
        target_role_code="finance_reviewer",
        requested_duration_seconds=600,
        status="approved",
        effective_from=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        row_version="2",
    )
    service.create.return_value = BreakGlassMutationResult(
        data.model_copy(update={"status": "pending", "effective_from": None, "expires_at": None}),
        201,
        False,
    )
    service.decide.return_value = BreakGlassMutationResult(data, 200, False)
    service.revoke.return_value = BreakGlassMutationResult(
        data.model_copy(update={"status": "revoked", "row_version": "3"}),
        200,
        False,
    )
    return service


@pytest.fixture
def application(
    exact_policy_file: Path,
    auth_service: Mock,
    break_glass_service: Mock,
) -> FastAPI:
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_break_glass_service] = lambda: break_glass_service
    return app


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_break_glass_create_is_strict_private_and_idempotent(
    client: TestClient,
    break_glass_service: Mock,
) -> None:
    response = client.post(
        "/api/v1/break-glass-requests",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "break-glass-create-01",
        },
        json={
            "target_user_id": str(TARGET_ID),
            "target_role_code": "finance_reviewer",
            "requested_duration_seconds": 600,
            "reason": "临时财务处置",
        },
    )

    assert response.status_code == 201, response.json()
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["idempotency-replayed"] == "false"
    assert response.json()["data"]["status"] == "pending"
    assert "reason" not in response.text
    break_glass_service.create.assert_called_once_with(
        ANY,
        ANY,
        "break-glass-create-01",
        ANY,
    )


@pytest.mark.parametrize(
    ("suffix", "body", "method_name", "expected_status"),
    (
        (
            "decision",
            {"decision": "approved", "reason": "独立批准", "row_version": "1"},
            "decide",
            "approved",
        ),
        (
            "revoke",
            {"reason": "提前结束", "row_version": "2"},
            "revoke",
            "revoked",
        ),
    ),
)
def test_break_glass_transitions_forward_canonical_cas(
    client: TestClient,
    break_glass_service: Mock,
    suffix: str,
    body: dict[str, object],
    method_name: str,
    expected_status: str,
) -> None:
    response = client.post(
        f"/api/v1/break-glass-requests/{REQUEST_ID}/{suffix}",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": f"break-glass-{suffix}-01",
        },
        json=body,
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == expected_status
    called = getattr(break_glass_service, method_name)
    assert called.call_args.args[1] == REQUEST_ID
    assert called.call_args.args[2].row_version == body["row_version"]


def test_break_glass_rejects_unknown_query_and_noncanonical_id_without_service(
    client: TestClient,
    break_glass_service: Mock,
) -> None:
    unknown = client.post(
        "/api/v1/break-glass-requests?unexpected=true",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "break-glass-create-02",
        },
        json={
            "target_user_id": str(TARGET_ID),
            "target_role_code": "finance_reviewer",
            "requested_duration_seconds": 600,
            "reason": "临时财务处置",
        },
    )
    uppercase = client.post(
        f"/api/v1/break-glass-requests/{str(REQUEST_ID).upper()}/revoke",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "break-glass-revoke-02",
        },
        json={"reason": "提前结束", "row_version": "2"},
    )

    assert unknown.status_code == 422
    assert uppercase.status_code == 422
    break_glass_service.create.assert_not_called()
    break_glass_service.revoke.assert_not_called()


def test_break_glass_openapi_freezes_three_operations(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    operations = (
        paths["/api/v1/break-glass-requests"]["post"],
        paths["/api/v1/break-glass-requests/{request_id}/decision"]["post"],
        paths["/api/v1/break-glass-requests/{request_id}/revoke"]["post"],
    )
    assert {operation["operationId"] for operation in operations} == {
        "create_break_glass_request_v1",
        "decide_break_glass_request_v1",
        "revoke_break_glass_request_v1",
    }
    for operation in operations:
        assert "Idempotency-Key" in {parameter["name"] for parameter in operation["parameters"]}
        assert set(operation["responses"]).issuperset({"401", "403", "404", "409", "422", "503"})
