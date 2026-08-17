from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import resources
from threading import Barrier
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies.auth import get_auth_service
from app.bootstrap import create_app
from app.core.auth_security import hash_password
from app.core.config import Settings
from app.core.errors import AppError
from app.core.refresh_tokens import RefreshToken
from app.db.session import create_application_engine, create_session_factory
from app.models.auth import Organization, Role, TokenSession, User, UserRole
from app.repositories.auth import AuthRepository
from app.services.auth import (
    AuthKeyring,
    AuthService,
    AuthSessionResult,
    PasswordChangeRequired,
)
from app.services.user_query import UserQueryService
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
)

pytestmark = pytest.mark.integration

ORGANIZATION_ID = UUID("73000000-0000-4000-8000-000000000001")
USER_ID = UUID("74000000-0000-4000-8000-000000000001")
FINANCE_USER_ROLE_ID = UUID("75000000-0000-4000-8000-000000000001")
READ_ONLY_USER_ROLE_ID = UUID("75000000-0000-4000-8000-000000000002")
USERNAME = "auth.integration"
OLD_PASSWORD = "Strong-Old-Password-2026!"
NEW_PASSWORD = "Strong-New-Password-2026!"
EXPECTED_ROLES = ("finance_reviewer", "read_only")
EXPECTED_PERMISSIONS = (
    "audits.read",
    "files.read",
    "financial.read",
    "knowledge.use",
    "reports.read",
)


def _runtime_settings(database_url: URL) -> Settings:
    policy_file = resources.files("app.ai.artifacts.cr011_v1").joinpath(
        "ai-policy-v1.positive.json"
    )
    return Settings(
        _env_file=None,
        **{
            "app_env": "test",
            "secret_key": "auth-integration-signing-key-32-chars",
            "database_url": database_url.render_as_string(hide_password=False),
            "redis_url": "redis://:test-password@redis:6379/0",
            "celery_broker_url": "redis://:test-password@redis:6379/0",
            "celery_result_backend": "redis://:test-password@redis:6379/1",
            "minio_access_key": "test-minio-access",
            "minio_secret_key": "test-minio-secret",
            "qdrant_collection": "finaudit_policy_chunks_test_e1024_v1",
            "ai_policy_file": str(policy_file),
            "llm_api_key": "test-llm-key",
            "llm_base_url": "http://synthetic-extraction:8000/v1",
            "llm_extraction_model": "synthetic-extraction-model",
            "llm_generation_model": "synthetic-generation-model",
            "llm_fallback_model": "synthetic-fallback-model",
            "embedding_base_url": "http://synthetic-embedding:8003/v1",
            "embedding_api_key": "test-embedding-key",
            "embedding_model": "synthetic-embedding-model",
            "metrics_internal_token": "test-metrics-token",
        },
    )


def _seed_auth_subject(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        repository = AuthRepository(session)
        now = repository.database_now()
        session.add(
            Organization(
                id=ORGANIZATION_ID,
                name="Synthetic auth integration organization",
                unified_social_credit_code="SYNTH-AUTH-INTEGRATION-USCC",
                tax_number="SYNTH-AUTH-INTEGRATION-TAX",
                status="active",
            )
        )
        session.flush()
        session.add(
            User(
                id=USER_ID,
                organization_id=ORGANIZATION_ID,
                username=USERNAME,
                display_name="Synthetic auth integration user",
                password_hash=hash_password(OLD_PASSWORD),
                status="active",
                password_changed_at=now,
            )
        )
        session.flush()
        roles = {
            role.code: role.id
            for role in session.execute(select(Role).where(Role.code.in_(EXPECTED_ROLES))).scalars()
        }
        assert set(roles) == set(EXPECTED_ROLES)
        session.add_all(
            [
                UserRole(
                    id=FINANCE_USER_ROLE_ID,
                    user_id=USER_ID,
                    role_id=roles["finance_reviewer"],
                    assigned_by=None,
                    assignment_source="bootstrap",
                    assignment_reason="system_bootstrap",
                ),
                UserRole(
                    id=READ_ONLY_USER_ROLE_ID,
                    user_id=USER_ID,
                    role_id=roles["read_only"],
                    assigned_by=None,
                    assignment_source="bootstrap",
                    assignment_reason="system_bootstrap",
                ),
            ]
        )


def _build_service(factory: sessionmaker[Session]) -> AuthService:
    private_key = Ed25519PrivateKey.generate()
    return AuthService(
        factory,
        AuthKeyring(
            active_kid="auth-test-v1",
            private_key=private_key,
            public_keys={"auth-test-v1": private_key.public_key()},
        ),
        hash_password("Synthetic-Dummy-Password-2026!"),
    )


def _bound_test_transaction_waits(
    session: Session,
    transaction: object,
    connection: Connection,
) -> None:
    del session, transaction
    connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
    connection.exec_driver_sql("SET LOCAL statement_timeout = '10s'")


def _clear_auth_subject(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE operation_logs DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM operation_logs WHERE actor_id = %s OR actor_kind = 'anonymous'",
                (USER_ID,),
            )
        finally:
            connection.exec_driver_sql("ALTER TABLE operation_logs ENABLE TRIGGER USER")
        connection.exec_driver_sql("ALTER TABLE token_sessions DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM token_sessions WHERE user_id = %s",
                (USER_ID,),
            )
        finally:
            connection.exec_driver_sql("ALTER TABLE token_sessions ENABLE TRIGGER USER")
        connection.exec_driver_sql("ALTER TABLE user_roles DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM user_roles WHERE user_id = %s",
                (USER_ID,),
            )
        finally:
            connection.exec_driver_sql("ALTER TABLE user_roles ENABLE TRIGGER USER")
        connection.exec_driver_sql("DELETE FROM users WHERE id = %s", (USER_ID,))
        connection.exec_driver_sql(
            "DELETE FROM organizations WHERE id = %s",
            (ORGANIZATION_ID,),
        )


def _session_count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return session.execute(select(func.count()).select_from(TokenSession)).scalar_one()


def _token_session(factory: sessionmaker[Session], refresh: RefreshToken) -> TokenSession:
    with factory() as session:
        token_session = session.get(TokenSession, refresh.session_id)
        assert token_session is not None
        session.expunge(token_session)
        return token_session


def _assert_app_error(code: str, action: Callable[[], object]) -> None:
    with pytest.raises(AppError) as captured:
        action()
    assert captured.value.code == code


def _concurrent_refresh(
    service: AuthService,
    refresh: RefreshToken,
    barrier: Barrier,
) -> tuple[str, AuthSessionResult | str]:
    barrier.wait(timeout=10)
    try:
        return "refreshed", service.refresh(refresh.wire_value)
    except AppError as error:
        return "error", error.code


def _concurrent_password_change(
    service: AuthService,
    password_change_token: str,
    barrier: Barrier,
) -> str:
    barrier.wait(timeout=10)
    service.change_password(password_change_token, NEW_PASSWORD)
    return "changed"


def _concurrent_login_failure(service: AuthService, barrier: Barrier) -> str:
    barrier.wait(timeout=10)
    try:
        service.login(USERNAME, "Wrong-Password-2026!", remember_me=False)
    except AppError as error:
        return error.code
    raise AssertionError("invalid credentials unexpectedly created a session")


def test_user_query_service_reads_current_fixed_roles_from_real_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_application_engine(_runtime_settings(database_url))
    factory = create_session_factory(engine)
    event.listen(factory, "after_begin", _bound_test_transaction_waits)
    seeded = False
    try:
        _seed_auth_subject(factory)
        seeded = True
        service = UserQueryService(factory)

        first_page = service.list_page(ORGANIZATION_ID, None, 20)

        assert first_page.next_cursor is None
        assert first_page.model_dump(mode="json")["items"] == [
            {
                "id": str(USER_ID),
                "username": USERNAME,
                "display_name": "Synthetic auth integration user",
                "status": "active",
                "fixed_roles": ["finance_reviewer", "read_only"],
                "row_version": "1",
            }
        ]
        assert service.list_page(UUID(int=ORGANIZATION_ID.int + 1), None, 20).items == ()

        with factory.begin() as session:
            user = session.get(User, USER_ID)
            assert user is not None
            user.deleted_at = AuthRepository(session).database_now()
            user.deleted_by = USER_ID
            user.delete_reason = "synthetic user list soft delete"
        assert service.list_page(ORGANIZATION_ID, None, 20).items == ()
    finally:
        if seeded:
            _clear_auth_subject(engine)
        engine.dispose()


def test_auth_repository_service_core_chains_use_real_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    settings = _runtime_settings(database_url)
    engine: Engine = create_application_engine(settings)
    factory = create_session_factory(engine)
    event.listen(factory, "after_begin", _bound_test_transaction_waits)

    try:
        _seed_auth_subject(factory)
        service = _build_service(factory)

        standard_login = service.login(USERNAME, OLD_PASSWORD, remember_me=False)
        remembered_login = service.login(USERNAME, OLD_PASSWORD, remember_me=True)
        assert isinstance(standard_login, AuthSessionResult)
        assert isinstance(remembered_login, AuthSessionResult)
        assert standard_login.refresh_max_age_seconds == 7 * 24 * 60 * 60
        assert remembered_login.refresh_max_age_seconds == 30 * 24 * 60 * 60
        standard_session = _token_session(factory, standard_login.refresh)
        remembered_session = _token_session(factory, remembered_login.refresh)
        assert standard_session.expires_at - standard_session.issued_at == timedelta(days=7)
        assert remembered_session.expires_at - remembered_session.issued_at == timedelta(days=30)
        standard_rotated = service.refresh(standard_login.refresh.wire_value)
        assert standard_rotated.refresh_expires_at == standard_session.expires_at
        assert standard_rotated.refresh_max_age_seconds <= standard_login.refresh_max_age_seconds
        assert (
            _token_session(factory, standard_rotated.refresh).expires_at
            == standard_session.expires_at
        )

        failure_barrier = Barrier(4)
        with ThreadPoolExecutor(max_workers=4) as executor:
            failure_futures = tuple(
                executor.submit(_concurrent_login_failure, service, failure_barrier)
                for _ in range(4)
            )
            failure_codes = tuple(future.result(timeout=15) for future in failure_futures)
        assert failure_codes == ("AUTH_INVALID_CREDENTIALS",) * 4
        with factory() as session:
            user_after_four_failures = session.get(User, USER_ID)
            assert user_after_four_failures is not None
            assert user_after_four_failures.status == "active"
            assert user_after_four_failures.failed_login_count == 4

        with factory() as session:
            repository = AuthRepository(session)
            fifth_failure_started_at = repository.database_now()
        _assert_app_error(
            "AUTH_INVALID_CREDENTIALS",
            lambda: service.login(USERNAME, "Wrong-Password-2026!", remember_me=False),
        )
        with factory() as session:
            repository = AuthRepository(session)
            fifth_failure_finished_at = repository.database_now()
            locked_user = session.get(User, USER_ID)
            assert locked_user is not None
            assert locked_user.status == "locked"
            assert locked_user.failed_login_count == 5
            assert locked_user.locked_until is not None
            locked_until = locked_user.locked_until
            assert locked_until >= fifth_failure_started_at + timedelta(minutes=15)
            assert locked_until <= fifth_failure_finished_at + timedelta(minutes=15)
        _assert_app_error(
            "AUTH_INVALID_CREDENTIALS",
            lambda: service.login(USERNAME, OLD_PASSWORD, remember_me=False),
        )
        with factory.begin() as session:
            repository = AuthRepository(session)
            locked_user = repository.lock_user_by_id(USER_ID)
            assert locked_user is not None
            now = repository.database_now()
            locked_user.locked_until = now - timedelta(seconds=1)
            locked_user.row_version += 1
        recovered_login = service.login(USERNAME, OLD_PASSWORD, remember_me=False)
        assert isinstance(recovered_login, AuthSessionResult)
        with factory() as session:
            recovered_user = session.get(User, USER_ID)
            assert recovered_user is not None
            assert recovered_user.status == "active"
            assert recovered_user.failed_login_count == 0
            assert recovered_user.locked_until is None

        concurrent_login = service.login(USERNAME, OLD_PASSWORD, remember_me=False)
        assert isinstance(concurrent_login, AuthSessionResult)
        same_token_barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_refresh = executor.submit(
                _concurrent_refresh,
                service,
                concurrent_login.refresh,
                same_token_barrier,
            )
            second_refresh = executor.submit(
                _concurrent_refresh,
                service,
                concurrent_login.refresh,
                same_token_barrier,
            )
            same_token_outcomes = (
                first_refresh.result(timeout=10),
                second_refresh.result(timeout=10),
            )
        assert sorted(outcome[0] for outcome in same_token_outcomes) == ["error", "refreshed"]
        concurrent_error = next(
            outcome[1] for outcome in same_token_outcomes if outcome[0] == "error"
        )
        assert concurrent_error == "AUTH_REUSE_DETECTED"
        concurrent_winner = next(
            outcome[1] for outcome in same_token_outcomes if outcome[0] == "refreshed"
        )
        assert isinstance(concurrent_winner, AuthSessionResult)
        concurrent_session = _token_session(factory, concurrent_login.refresh)
        assert concurrent_session.revoked_at is not None
        assert concurrent_session.revoke_reason == "refresh_reuse"
        _assert_app_error(
            "AUTH_TOKEN_REVOKED",
            lambda: service.authenticate(concurrent_winner.data.access_token),
        )
        _assert_app_error(
            "AUTH_TOKEN_REVOKED",
            lambda: service.refresh(concurrent_winner.refresh.wire_value),
        )

        application = create_app(settings)
        application.dependency_overrides[get_auth_service] = lambda: service
        with TestClient(application, base_url="https://testserver") as client:
            http_login = client.post(
                "/api/v1/auth/login",
                headers={"Origin": "https://testserver"},
                json={
                    "username": USERNAME,
                    "password": OLD_PASSWORD,
                    "remember_me": False,
                },
            )
            assert http_login.status_code == 200
            http_login_data = http_login.json()["data"]
            assert http_login_data["user"]["roles"] == list(EXPECTED_ROLES)
            assert http_login_data["user"]["permissions"] == list(EXPECTED_PERMISSIONS)
            first_cookie = http_login.cookies.get("finaudit_refresh")
            assert first_cookie is not None
            assert "Secure" in http_login.headers["set-cookie"]
            assert "HttpOnly" in http_login.headers["set-cookie"]

            http_me = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {http_login_data['access_token']}"},
            )
            assert http_me.status_code == 200
            assert http_me.json()["data"] == http_login_data["user"]

            http_refresh = client.post(
                "/api/v1/auth/refresh",
                headers={"Origin": "https://testserver"},
            )
            assert http_refresh.status_code == 200
            assert http_refresh.cookies.get("finaudit_refresh") != first_cookie
            refreshed_access = http_refresh.json()["data"]["access_token"]
            refreshed_me = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {refreshed_access}"},
            )
            assert refreshed_me.status_code == 200
            assert refreshed_me.json()["data"]["permissions"] == list(EXPECTED_PERMISSIONS)

        login = service.login(USERNAME, OLD_PASSWORD, remember_me=False)
        assert isinstance(login, AuthSessionResult)
        assert login.data.user.id == USER_ID
        assert login.data.user.roles == EXPECTED_ROLES
        assert login.data.user.permissions == EXPECTED_PERMISSIONS
        assert login.refresh.wire_value not in repr(login)

        actor, current_user = service.authenticate(login.data.access_token)
        assert actor.user_id == USER_ID
        assert actor.organization_id == ORGANIZATION_ID
        assert actor.session_id == login.refresh.session_id
        assert actor.roles == EXPECTED_ROLES
        assert actor.permissions == EXPECTED_PERMISSIONS
        assert current_user == login.data.user

        rotated = service.refresh(login.refresh.wire_value)
        assert rotated.refresh.session_id == login.refresh.session_id
        assert rotated.refresh.wire_value != login.refresh.wire_value
        assert _token_session(factory, rotated.refresh).refresh_token_hash == rotated.refresh.digest
        _assert_app_error(
            "AUTH_REUSE_DETECTED",
            lambda: service.refresh(login.refresh.wire_value),
        )
        replay_revoked = _token_session(factory, rotated.refresh)
        assert replay_revoked.revoked_at is not None
        assert replay_revoked.revoke_reason == "refresh_reuse"
        _assert_app_error(
            "AUTH_TOKEN_REVOKED",
            lambda: service.authenticate(rotated.data.access_token),
        )

        logout_login = service.login(USERNAME, OLD_PASSWORD, remember_me=False)
        assert isinstance(logout_login, AuthSessionResult)
        service.logout(logout_login.refresh.wire_value)
        logged_out = _token_session(factory, logout_login.refresh)
        assert logged_out.revoked_at is not None
        assert logged_out.revoke_reason == "logout"
        forged_wire = f"{logout_login.refresh.session_id}.{'A' * 43}"
        _assert_app_error(
            "AUTH_TOKEN_REVOKED",
            lambda: service.refresh(forged_wire),
        )
        service.logout(forged_wire)
        after_forgery = _token_session(factory, logout_login.refresh)
        assert after_forgery.revoked_at == logged_out.revoked_at
        assert after_forgery.revoke_reason == "logout"

        existing_login = service.login(USERNAME, OLD_PASSWORD, remember_me=False)
        assert isinstance(existing_login, AuthSessionResult)
        old_access_token = existing_login.data.access_token
        with factory.begin() as session:
            repository = AuthRepository(session)
            user = repository.lock_user_by_id(USER_ID)
            assert user is not None
            now = repository.database_now()
            user.force_change_on_login = True
            user.updated_at = now
            user.row_version += 1

        sessions_before_force_login = _session_count(factory)
        force_change_login = service.login(USERNAME, OLD_PASSWORD, remember_me=False)
        assert isinstance(force_change_login, PasswordChangeRequired)
        assert _session_count(factory) == sessions_before_force_login

        with factory.begin() as session:
            repository = AuthRepository(session)
            disabled_user = repository.lock_user_by_id(USER_ID)
            assert disabled_user is not None
            disabled_user.status = "disabled"
            disabled_user.row_version += 1
        _assert_app_error(
            "AUTH_TOKEN_REVOKED",
            lambda: service.change_password(force_change_login.token, NEW_PASSWORD),
        )
        with factory.begin() as session:
            repository = AuthRepository(session)
            disabled_user = repository.lock_user_by_id(USER_ID)
            assert disabled_user is not None
            assert disabled_user.status == "disabled"
            disabled_user.status = "active"
            disabled_user.row_version += 1

        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            refresh_future = executor.submit(
                _concurrent_refresh,
                service,
                existing_login.refresh,
                barrier,
            )
            password_future = executor.submit(
                _concurrent_password_change,
                service,
                force_change_login.token,
                barrier,
            )
            refresh_outcome = refresh_future.result(timeout=10)
            assert password_future.result(timeout=10) == "changed"

        assert refresh_outcome[0] in {"refreshed", "error"}
        if refresh_outcome[0] == "error":
            assert refresh_outcome[1] == "AUTH_TOKEN_REVOKED"
        else:
            assert isinstance(refresh_outcome[1], AuthSessionResult)
        changed_session = _token_session(factory, existing_login.refresh)
        assert changed_session.revoked_at is not None
        assert changed_session.revoke_reason == "password_changed"

        _assert_app_error(
            "AUTH_TOKEN_REVOKED",
            lambda: service.change_password(force_change_login.token, NEW_PASSWORD),
        )
        _assert_app_error(
            "AUTH_TOKEN_REVOKED",
            lambda: service.authenticate(old_access_token),
        )
        _assert_app_error(
            "AUTH_INVALID_CREDENTIALS",
            lambda: service.login(USERNAME, OLD_PASSWORD, remember_me=False),
        )
        new_login = service.login(USERNAME, NEW_PASSWORD, remember_me=False)
        assert isinstance(new_login, AuthSessionResult)
        assert new_login.data.user.roles == EXPECTED_ROLES
        assert new_login.data.user.permissions == EXPECTED_PERMISSIONS
    finally:
        try:
            _clear_auth_subject(engine)
        finally:
            engine.dispose()
