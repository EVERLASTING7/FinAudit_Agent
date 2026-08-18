from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from unittest.mock import ANY, Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service, require_permission
from app.bootstrap import create_app
from app.core.errors import AppError
from app.core.refresh_tokens import RefreshToken
from app.schemas.auth import AuthSessionData, CurrentUserData
from app.services.auth import (
    AuthenticatedActor,
    AuthService,
    AuthSessionResult,
    PasswordChangeRequired,
)
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401 - imported fixture registration
    build_startup_settings,
)

USER_ID = UUID("60000000-0000-4000-8000-000000000001")
SESSION_ID = UUID("60000000-0000-4000-8000-000000000002")


def _current_user() -> CurrentUserData:
    return CurrentUserData(
        id=USER_ID,
        display_name="测试用户",
        roles=("finance_reviewer",),
        permissions=("financial.read",),
    )


def _session_result() -> AuthSessionResult:
    return AuthSessionResult(
        data=AuthSessionData(access_token="access-token", user=_current_user()),
        refresh=RefreshToken(
            session_id=SESSION_ID,
            wire_value=f"{SESSION_ID}." + "a" * 43,
            digest="0" * 64,
        ),
        refresh_expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        refresh_max_age_seconds=7 * 24 * 60 * 60,
    )


@pytest.fixture
def auth_service() -> Mock:
    return Mock(spec=AuthService)


@pytest.fixture
def client(exact_policy_file: Path, auth_service: Mock) -> Iterator[TestClient]:
    application = create_app(build_startup_settings(exact_policy_file))
    application.dependency_overrides[get_auth_service] = lambda: auth_service
    with TestClient(application) as test_client:
        yield test_client


def test_auth_openapi_freezes_all_operation_identities(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        ("/api/v1/auth/login", "post"): "login_api_v1_auth_login_post",
        ("/api/v1/auth/refresh", "post"): "refresh_api_v1_auth_refresh_post",
        ("/api/v1/auth/logout", "post"): "logout_api_v1_auth_logout_post",
        ("/api/v1/auth/me", "get"): "me_api_v1_auth_me_get",
        (
            "/api/v1/auth/password/change",
            "post",
        ): "change_password_api_v1_auth_password_change_post",
    }

    for (path, method), operation_id in expected.items():
        assert paths[path][method]["operationId"] == operation_id


def test_login_returns_session_and_strict_refresh_cookie(
    client: TestClient, auth_service: Mock
) -> None:
    auth_service.login.return_value = _session_result()

    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": "finance.user", "password": "x" * 15, "remember_me": False},
    )

    assert response.status_code == 200
    assert response.json()["data"]["expires_in"] == 900
    cookie = response.headers["set-cookie"]
    assert "finaudit_refresh=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "Domain=" not in cookie
    assert "Secure" not in cookie
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_auth_results_hide_credentials_from_repr() -> None:
    session = _session_result()
    change = PasswordChangeRequired(token="password-change-sentinel")

    assert "access-token" not in repr(session)
    assert session.refresh.wire_value not in repr(session)
    assert "password-change-sentinel" not in repr(change)


def test_force_change_uses_safe_error_data_without_creating_a_cookie(
    client: TestClient, auth_service: Mock
) -> None:
    auth_service.login.return_value = PasswordChangeRequired(token="pwd-token")

    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": "finance.user", "password": "x" * 15, "remember_me": False},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_PASSWORD_CHANGE_REQUIRED"
    assert response.json()["data"] == {
        "password_change_token": "pwd-token",
        "expires_in": 300,
    }
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_refresh_requires_cookie(client: TestClient) -> None:
    response = client.post("/api/v1/auth/refresh", headers={"Origin": "http://testserver"})

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REFRESH_EXPIRED"


def test_logout_is_idempotent_and_clears_cookie(client: TestClient, auth_service: Mock) -> None:
    response = client.post("/api/v1/auth/logout", headers={"Origin": "http://testserver"})

    assert response.status_code == 204
    auth_service.logout.assert_called_once_with(None, trace_id=ANY)
    assert isinstance(auth_service.logout.call_args.kwargs["trace_id"], UUID)
    assert "finaudit_refresh=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_me_returns_database_authenticated_projection(
    client: TestClient, auth_service: Mock
) -> None:
    actor = AuthenticatedActor(
        user_id=USER_ID,
        organization_id=UUID("60000000-0000-4000-8000-000000000003"),
        session_id=SESSION_ID,
        roles=("finance_reviewer",),
        permissions=("financial.read",),
    )
    auth_service.authenticate.return_value = (actor, _current_user())

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["permissions"] == ["financial.read"]


def test_permission_dependency_enforces_backend_capability_boundary() -> None:
    actor = AuthenticatedActor(
        user_id=USER_ID,
        organization_id=UUID("60000000-0000-4000-8000-000000000003"),
        session_id=SESSION_ID,
        roles=("finance_reviewer",),
        permissions=("financial.read",),
    )

    request = Mock()
    request.state.trace_id = "60000000-0000-4000-8000-000000000004"
    service = Mock(spec=AuthService)

    assert require_permission("financial.read")(request, actor, service) is actor
    service.record_authorization_denied.assert_not_called()
    with pytest.raises(AppError) as captured:
        require_permission("users.manage")(request, actor, service)
    assert captured.value.status_code == 403
    assert captured.value.code == "AUTH_FORBIDDEN"
    service.record_authorization_denied.assert_called_once_with(
        actor,
        "users.manage",
        UUID(request.state.trace_id),
    )


def test_password_change_uses_bearer_token_and_returns_204(
    client: TestClient, auth_service: Mock
) -> None:
    response = client.post(
        "/api/v1/auth/password/change",
        headers={
            "Authorization": "Bearer pwd-token",
            "Origin": "http://testserver",
        },
        json={"new_password": "new-safe-password-value"},
    )

    assert response.status_code == 204
    auth_service.change_password.assert_called_once_with("pwd-token", "new-safe-password-value")


def test_auth_app_error_preserves_www_authenticate(client: TestClient, auth_service: Mock) -> None:
    auth_service.authenticate.side_effect = AppError(
        status_code=401,
        code="AUTH_ACCESS_EXPIRED",
        message="认证已失效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer expired-token"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == "AUTH_ACCESS_EXPIRED"


def test_local_non_test_requests_require_same_origin(exact_policy_file: Path) -> None:
    application = create_app(build_startup_settings(exact_policy_file, environment="local"))
    service = cast(Mock, Mock(spec=AuthService))
    application.dependency_overrides[get_auth_service] = lambda: service
    with TestClient(application) as local_client:
        missing = local_client.post(
            "/api/v1/auth/login",
            json={"username": "finance.user", "password": "x" * 15, "remember_me": False},
        )
        cross_origin = local_client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://evil.invalid"},
            json={"username": "finance.user", "password": "x" * 15, "remember_me": False},
        )

    assert missing.status_code == 403
    assert cross_origin.status_code == 403
    service.login.assert_not_called()


def test_local_loopback_http_uses_non_secure_cookie(
    exact_policy_file: Path,
) -> None:
    application = create_app(build_startup_settings(exact_policy_file, environment="local"))
    service = cast(Mock, Mock(spec=AuthService))
    service.login.return_value = _session_result()
    application.dependency_overrides[get_auth_service] = lambda: service
    with TestClient(application, base_url="http://127.0.0.1") as local_client:
        response = local_client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://127.0.0.1"},
            json={"username": "finance.user", "password": "x" * 15, "remember_me": False},
        )

    assert response.status_code == 200
    assert "Secure" not in response.headers["set-cookie"]


def test_test_profile_http_uses_non_secure_cookie(
    exact_policy_file: Path,
) -> None:
    application = create_app(build_startup_settings(exact_policy_file, environment="test"))
    service = cast(Mock, Mock(spec=AuthService))
    service.login.return_value = _session_result()
    application.dependency_overrides[get_auth_service] = lambda: service
    with TestClient(application, base_url="http://127.0.0.1") as test_client:
        response = test_client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://127.0.0.1"},
            json={"username": "finance.user", "password": "x" * 15, "remember_me": False},
        )

    assert response.status_code == 200
    assert "Secure" not in response.headers["set-cookie"]


def test_test_environment_does_not_create_an_origin_bypass(
    client: TestClient, auth_service: Mock
) -> None:
    missing = client.post(
        "/api/v1/auth/login",
        json={"username": "finance.user", "password": "x" * 15, "remember_me": False},
    )

    assert missing.status_code == 403
    auth_service.login.assert_not_called()


def test_configured_public_origin_handles_tls_termination_without_trusting_forwarded_headers(
    exact_policy_file: Path,
) -> None:
    application = create_app(
        build_startup_settings(
            exact_policy_file,
            auth_public_origin="https://audit.example",
        )
    )
    service = cast(Mock, Mock(spec=AuthService))
    service.login.return_value = _session_result()
    application.dependency_overrides[get_auth_service] = lambda: service
    payload = {
        "username": "finance.user",
        "password": "x" * 15,
        "remember_me": False,
    }
    with TestClient(application, base_url="http://127.0.0.1") as proxy_client:
        accepted = proxy_client.post(
            "/api/v1/auth/login",
            headers={
                "Origin": "https://audit.example",
                "Forwarded": "host=evil.invalid;proto=http",
                "X-Forwarded-Host": "evil.invalid",
                "X-Forwarded-Proto": "http",
            },
            json=payload,
        )
        rejected = proxy_client.post(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://127.0.0.1",
                "Forwarded": "host=audit.example;proto=https",
                "X-Forwarded-Host": "audit.example",
                "X-Forwarded-Proto": "https",
            },
            json=payload,
        )

    assert accepted.status_code == 200
    assert "Secure" in accepted.headers["set-cookie"]
    assert rejected.status_code == 403
    assert service.login.call_count == 1


def test_local_public_loopback_http_stays_usable_behind_internal_proxy(
    exact_policy_file: Path,
) -> None:
    application = create_app(
        build_startup_settings(
            exact_policy_file,
            environment="local",
            auth_public_origin="http://127.0.0.1",
        )
    )
    service = cast(Mock, Mock(spec=AuthService))
    service.login.return_value = _session_result()
    application.dependency_overrides[get_auth_service] = lambda: service
    with TestClient(application, base_url="http://backend-internal") as proxy_client:
        response = proxy_client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://127.0.0.1"},
            json={
                "username": "finance.user",
                "password": "x" * 15,
                "remember_me": False,
            },
        )

    assert response.status_code == 200
    assert "Secure" not in response.headers["set-cookie"]
