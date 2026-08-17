from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth_security import hash_password, verify_password
from app.core.errors import AppError
from app.db.migration import create_migration_engine
from app.db.session import create_session_factory
from app.models.auth import Organization, Role, TokenSession, User, UserRole
from app.models.operations import OperationLog
from app.models.reliability import IdempotencyRecord
from app.repositories.auth import AuthRepository
from app.schemas.users import (
    UserCreateRequest,
    UserPasswordResetRequest,
    UserRolesReplaceRequest,
    UserStatusUpdateRequest,
)
from app.services.auth import AuthenticatedActor
from app.services.user_management import UserManagementService
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
)

pytestmark = pytest.mark.integration

ORGANIZATION_ID = UUID("7d000000-0000-4000-8000-000000000001")
ACTOR_ID = UUID("7d000000-0000-4000-8000-000000000002")
TARGET_ID = UUID("7d000000-0000-4000-8000-000000000003")
ACTOR_ROLE_ID = UUID("7d000000-0000-4000-8000-000000000004")
TARGET_ROLE_ID = UUID("7d000000-0000-4000-8000-000000000005")
TARGET_SESSION_ID = UUID("7d000000-0000-4000-8000-000000000006")
OLD_PASSWORD = "Strong-Target-Password-2026!"
RESET_PASSWORD = "Strong-Reset-Password-2026!"


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=("system_admin",),
        permissions=("users.manage",),
    )


def _seed_subjects(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        repository = AuthRepository(session)
        now = repository.database_now()
        session.add(
            Organization(
                id=ORGANIZATION_ID,
                name="Synthetic user-management organization",
                unified_social_credit_code="SYNTH-USER-MANAGEMENT-USCC",
                tax_number="SYNTH-USER-MANAGEMENT-TAX",
                status="active",
            )
        )
        session.flush()
        session.add_all(
            [
                User(
                    id=ACTOR_ID,
                    organization_id=ORGANIZATION_ID,
                    username="admin.user-management",
                    display_name="用户管理管理员",
                    password_hash=hash_password("Strong-Admin-Password-2026!"),
                    status="active",
                    password_changed_at=now,
                ),
                User(
                    id=TARGET_ID,
                    organization_id=ORGANIZATION_ID,
                    username="target.user-management",
                    display_name="目标用户",
                    password_hash=hash_password(OLD_PASSWORD),
                    status="active",
                    password_changed_at=now,
                ),
            ]
        )
        session.flush()
        roles = {
            role.code: role.id
            for role in session.execute(
                select(Role).where(Role.code.in_(("system_admin", "read_only")))
            ).scalars()
        }
        session.add_all(
            [
                UserRole(
                    id=ACTOR_ROLE_ID,
                    user_id=ACTOR_ID,
                    role_id=roles["system_admin"],
                    assigned_by=None,
                    assignment_source="bootstrap",
                    assignment_reason="system_bootstrap",
                ),
                UserRole(
                    id=TARGET_ROLE_ID,
                    user_id=TARGET_ID,
                    role_id=roles["read_only"],
                    assigned_by=None,
                    assignment_source="bootstrap",
                    assignment_reason="system_bootstrap",
                ),
                TokenSession(
                    id=TARGET_SESSION_ID,
                    user_id=TARGET_ID,
                    refresh_token_hash="a" * 64,
                    issued_at=now,
                    expires_at=now + timedelta(days=7),
                    last_seen_at=now,
                ),
            ]
        )


def _clear_subjects(engine: Engine) -> None:
    with engine.begin() as connection:
        for table_name in ("operation_logs", "user_roles"):
            connection.exec_driver_sql(f"ALTER TABLE {table_name} DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql("DELETE FROM operation_logs")
            connection.exec_driver_sql("DELETE FROM idempotency_records")
            connection.exec_driver_sql("DELETE FROM token_sessions")
            connection.exec_driver_sql("DELETE FROM user_roles")
            connection.exec_driver_sql(
                "DELETE FROM users WHERE organization_id = %s",
                (ORGANIZATION_ID,),
            )
            connection.exec_driver_sql(
                "DELETE FROM organizations WHERE id = %s",
                (ORGANIZATION_ID,),
            )
        finally:
            for table_name in reversed(("operation_logs", "user_roles")):
                connection.exec_driver_sql(f"ALTER TABLE {table_name} ENABLE TRIGGER USER")


def _setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Engine, sessionmaker[Session], UserManagementService]:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    factory = create_session_factory(engine)
    _seed_subjects(factory)
    return engine, factory, UserManagementService(factory)


def _assert_app_error(code: str, action: Callable[[], object]) -> None:
    with pytest.raises(AppError) as captured:
        action()
    assert captured.value.code == code


def test_create_user_is_transactional_audited_and_replayable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service = _setup(monkeypatch)
    payload = UserCreateRequest.model_validate(
        {
            "username": "created.user",
            "display_name": "创建用户",
            "initial_password": "Strong-Initial-Password-2026!",
            "fixed_roles": ["read_only"],
        }
    )
    trace_id = uuid4()
    try:
        created = service.create_user(_actor(), payload, "create-user-001", trace_id)
        replayed = service.create_user(_actor(), payload, "create-user-001", uuid4())

        assert created.status_code == 201
        assert created.replayed is False
        assert replayed.replayed is True
        assert replayed.data == created.data
        with factory() as session:
            user = session.get(User, created.data.id)
            assert user is not None
            assert user.force_change_on_login is True
            assert verify_password("Strong-Initial-Password-2026!", user.password_hash)
            assert (
                session.execute(
                    select(func.count())
                    .select_from(User)
                    .where(User.organization_id == ORGANIZATION_ID)
                ).scalar_one()
                == 3
            )
            record = session.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.idempotency_key == "create-user-001"
                )
            ).scalar_one()
            assert record.response_status == 201
            assert "password" not in json_text(record.response_body_json)
            log = session.execute(
                select(OperationLog).where(OperationLog.resource_id == created.data.id)
            ).scalar_one()
            assert log.action_code == "users.created"
            assert log.trace_id == trace_id
            assert log.change_summary_json == {
                "fixed_roles": ["read_only"],
                "row_version": "1",
            }

        changed = payload.model_copy(update={"display_name": "另一个显示名"})
        _assert_app_error(
            "IDEMPOTENCY_KEY_REUSED",
            lambda: service.create_user(_actor(), changed, "create-user-001", uuid4()),
        )
    finally:
        _clear_subjects(engine)
        engine.dispose()


def test_status_and_password_reset_revoke_sessions_and_use_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service = _setup(monkeypatch)
    try:
        disabled = service.update_status(
            _actor(),
            TARGET_ID,
            UserStatusUpdateRequest(status="disabled", row_version="1"),
            "disable-user-001",
            uuid4(),
        )
        assert disabled.data.status == "disabled"
        assert disabled.data.row_version == "2"

        reset = service.reset_password(
            _actor(),
            TARGET_ID,
            UserPasswordResetRequest(new_password=RESET_PASSWORD, row_version="2"),
            "reset-user-0001",
            uuid4(),
        )
        assert reset.data.status == "disabled"
        assert reset.data.row_version == "3"
        assert service.reset_password(
            _actor(),
            TARGET_ID,
            UserPasswordResetRequest(new_password=RESET_PASSWORD, row_version="2"),
            "reset-user-0001",
            uuid4(),
        ).replayed

        _assert_app_error(
            "ROW_VERSION_CONFLICT",
            lambda: service.update_status(
                _actor(),
                TARGET_ID,
                UserStatusUpdateRequest(status="active", row_version="2"),
                "enable-user-001",
                uuid4(),
            ),
        )
        with factory() as session:
            user = session.get(User, TARGET_ID)
            token_session = session.get(TokenSession, TARGET_SESSION_ID)
            assert user is not None and token_session is not None
            assert user.force_change_on_login is True
            assert user.failed_login_count == 0
            assert user.locked_until is None
            assert verify_password(RESET_PASSWORD, user.password_hash)
            assert token_session.revoked_at is not None
            assert token_session.revoke_reason == "user_status_changed"
            actions = tuple(
                session.execute(
                    select(OperationLog.action_code)
                    .where(OperationLog.resource_id == TARGET_ID)
                    .order_by(OperationLog.created_at, OperationLog.id)
                ).scalars()
            )
            assert actions == ("users.status_changed", "users.password_reset")
    finally:
        _clear_subjects(engine)
        engine.dispose()


def test_role_replacement_preserves_history_and_last_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service = _setup(monkeypatch)
    try:
        replaced = service.replace_roles(
            _actor(),
            TARGET_ID,
            UserRolesReplaceRequest.model_validate(
                {"fixed_roles": ["contract_admin"], "row_version": "1"}
            ),
            "replace-role-001",
            uuid4(),
        )
        assert replaced.data.fixed_roles == ("contract_admin",)
        assert replaced.data.row_version == "2"

        _assert_app_error(
            "ROLE_SEPARATION_CONFLICT",
            lambda: service.replace_roles(
                _actor(),
                TARGET_ID,
                UserRolesReplaceRequest.model_validate(
                    {
                        "fixed_roles": ["audit_reviewer", "system_admin"],
                        "row_version": "2",
                    }
                ),
                "replace-role-002",
                uuid4(),
            ),
        )
        _assert_app_error(
            "LAST_SYSTEM_ADMIN_REQUIRED",
            lambda: service.update_status(
                _actor(),
                ACTOR_ID,
                UserStatusUpdateRequest(status="disabled", row_version="1"),
                "disable-admin-01",
                uuid4(),
            ),
        )
        _assert_app_error(
            "LAST_SYSTEM_ADMIN_REQUIRED",
            lambda: service.replace_roles(
                _actor(),
                ACTOR_ID,
                UserRolesReplaceRequest.model_validate(
                    {"fixed_roles": ["read_only"], "row_version": "1"}
                ),
                "replace-admin-01",
                uuid4(),
            ),
        )

        with factory() as session:
            rows = session.execute(
                select(UserRole, Role.code)
                .join(Role, Role.id == UserRole.role_id)
                .where(UserRole.user_id == TARGET_ID)
                .order_by(UserRole.assigned_at, UserRole.id)
            ).all()
            assert len(rows) == 2
            assert {str(row[1]) for row in rows if cast(UserRole, row[0]).revoked_at is None} == {
                "contract_admin"
            }
            assert {
                str(row[1]) for row in rows if cast(UserRole, row[0]).revoked_at is not None
            } == {"read_only"}
            assert (
                session.execute(
                    select(func.count())
                    .select_from(OperationLog)
                    .where(OperationLog.action_code == "users.roles_replaced")
                ).scalar_one()
                == 1
            )
    finally:
        _clear_subjects(engine)
        engine.dispose()


def test_concurrent_same_create_key_commits_one_user_and_one_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service = _setup(monkeypatch)
    payload = UserCreateRequest.model_validate(
        {
            "username": "concurrent.user",
            "display_name": "并发用户",
            "initial_password": "Strong-Concurrent-Password-2026!",
            "fixed_roles": ["read_only"],
        }
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                executor.map(
                    lambda _: service.create_user(
                        _actor(), payload, "concurrent-create-01", uuid4()
                    ),
                    range(2),
                )
            )
        assert sorted(result.replayed for result in results) == [False, True]
        assert len({result.data.id for result in results}) == 1
        created_id = results[0].data.id
        with factory() as session:
            assert (
                session.execute(
                    select(func.count()).select_from(User).where(User.username == "concurrent.user")
                ).scalar_one()
                == 1
            )
            assert (
                session.execute(
                    select(func.count())
                    .select_from(OperationLog)
                    .where(
                        OperationLog.resource_id == created_id,
                        OperationLog.action_code == "users.created",
                    )
                ).scalar_one()
                == 1
            )
    finally:
        _clear_subjects(engine)
        engine.dispose()


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)
