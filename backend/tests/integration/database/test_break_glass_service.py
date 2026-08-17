from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth_security import hash_password
from app.core.errors import AppError
from app.db.migration import create_migration_engine
from app.db.session import create_session_factory
from app.models.auth import BreakGlassRequest, Organization, Role, User, UserRole
from app.models.operations import OperationLog
from app.repositories.auth import AuthRepository
from app.repositories.operation_log import OperationLogRepository
from app.schemas.break_glass import (
    BreakGlassCreateRequest,
    BreakGlassDecisionRequest,
    BreakGlassRevokeRequest,
)
from app.services.auth import AuthenticatedActor
from app.services.break_glass import BreakGlassMutationResult, BreakGlassService
from app.services.operation_log_query import OperationLogQueryService
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
)

pytestmark = pytest.mark.integration

ORGANIZATION_ID = UUID("7f000000-0000-4000-8000-000000000001")
REQUESTER_ID = UUID("7f000000-0000-4000-8000-000000000002")
DECIDER_ID = UUID("7f000000-0000-4000-8000-000000000003")
TARGET_ID = UUID("7f000000-0000-4000-8000-000000000004")


def _actor(user_id: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=user_id,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=("system_admin",),
        permissions=("temporary_roles.decide", "temporary_roles.request"),
    )


def _seed(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        now = AuthRepository(session).database_now()
        session.add(
            Organization(
                id=ORGANIZATION_ID,
                name="Synthetic break-glass organization",
                unified_social_credit_code="SYNTH-BREAK-GLASS-USCC",
                tax_number="SYNTH-BREAK-GLASS-TAX",
                status="active",
            )
        )
        session.flush()
        for user_id, username in (
            (REQUESTER_ID, "breakglass.requester"),
            (DECIDER_ID, "breakglass.decider"),
            (TARGET_ID, "breakglass.target"),
        ):
            session.add(
                User(
                    id=user_id,
                    organization_id=ORGANIZATION_ID,
                    username=username,
                    display_name=username,
                    password_hash=hash_password("Strong-Break-Glass-Password-2026!"),
                    status="active",
                    password_changed_at=now,
                )
            )
        session.flush()
        admin_role_id = session.execute(
            select(Role.id).where(Role.code == "system_admin")
        ).scalar_one()
        for user_id in (REQUESTER_ID, DECIDER_ID):
            session.add(
                UserRole(
                    id=uuid4(),
                    user_id=user_id,
                    role_id=admin_role_id,
                    assigned_by=None,
                    assignment_source="bootstrap",
                    assignment_reason="system_bootstrap",
                )
            )


def _clear(engine: Engine) -> None:
    with engine.begin() as connection:
        for table_name in ("operation_logs", "user_roles", "break_glass_requests"):
            connection.exec_driver_sql(f"ALTER TABLE {table_name} DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql("DELETE FROM operation_logs")
            connection.exec_driver_sql("DELETE FROM idempotency_records")
            connection.exec_driver_sql("DELETE FROM user_roles")
            connection.exec_driver_sql("DELETE FROM break_glass_requests")
            connection.exec_driver_sql(
                "DELETE FROM users WHERE organization_id = %s",
                (ORGANIZATION_ID,),
            )
            connection.exec_driver_sql(
                "DELETE FROM organizations WHERE id = %s",
                (ORGANIZATION_ID,),
            )
        finally:
            for table_name in reversed(("operation_logs", "user_roles", "break_glass_requests")):
                connection.exec_driver_sql(f"ALTER TABLE {table_name} ENABLE TRIGGER USER")


def _setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Engine, sessionmaker[Session], BreakGlassService]:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    factory = create_session_factory(engine)
    _seed(factory)
    return engine, factory, BreakGlassService(factory)


def _create(service: BreakGlassService, key: str) -> BreakGlassMutationResult:
    return service.create(
        _actor(REQUESTER_ID),
        BreakGlassCreateRequest.model_validate(
            {
                "target_user_id": str(TARGET_ID),
                "target_role_code": "finance_reviewer",
                "requested_duration_seconds": 600,
                "reason": "临时财务复核",
            }
        ),
        key,
        uuid4(),
    )


def test_break_glass_approve_replay_and_revoke_are_one_audited_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service = _setup(monkeypatch)
    try:
        created = _create(service, "break-glass-create-db-01")
        request_id = created.data.id
        approved = service.decide(
            _actor(DECIDER_ID),
            request_id,
            BreakGlassDecisionRequest(
                decision="approved",
                reason="独立批准临时财务复核",
                row_version="1",
            ),
            "break-glass-decide-db-01",
            uuid4(),
        )
        replayed = service.decide(
            _actor(DECIDER_ID),
            request_id,
            BreakGlassDecisionRequest(
                decision="approved",
                reason="独立批准临时财务复核",
                row_version="1",
            ),
            "break-glass-decide-db-01",
            uuid4(),
        )
        assert approved.data.status == "approved"
        assert approved.data.row_version == "2"
        assert approved.data.effective_from is not None
        assert approved.data.expires_at is not None
        assert (approved.data.expires_at - approved.data.effective_from).total_seconds() == 600
        assert replayed.replayed is True
        assert replayed.data == approved.data

        revoked = service.revoke(
            _actor(DECIDER_ID),
            request_id,
            BreakGlassRevokeRequest(reason="临时任务完成", row_version="2"),
            "break-glass-revoke-db-01",
            uuid4(),
        )
        assert revoked.data.status == "revoked"
        assert revoked.data.row_version == "3"

        with factory() as session:
            request = session.get(BreakGlassRequest, request_id)
            assignment = session.execute(
                select(UserRole).where(UserRole.break_glass_request_id == request_id)
            ).scalar_one()
            assert request is not None
            assert assignment.assignment_source == "break_glass"
            assert assignment.assigned_at == request.effective_from
            assert assignment.expires_at == request.expires_at
            assert assignment.revoked_at == request.revoked_at
            assert assignment.revoked_by == request.revoked_by == DECIDER_ID
            logs = tuple(
                session.execute(
                    select(OperationLog)
                    .where(OperationLog.resource_id == request_id)
                    .order_by(OperationLog.created_at, OperationLog.id)
                ).scalars()
            )
            assert tuple(log.action_code for log in logs) == (
                "break_glass.requested",
                "break_glass.approved",
                "break_glass.revoked",
            )
            assert all("reason" not in log.change_summary_json for log in logs)
    finally:
        _clear(engine)
        engine.dispose()


def test_break_glass_self_decision_is_rejected_and_other_admin_can_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service = _setup(monkeypatch)
    try:
        created = _create(service, "break-glass-create-db-02")
        request_id = created.data.id
        payload = BreakGlassDecisionRequest(
            decision="rejected",
            reason="不满足临时授权条件",
            row_version="1",
        )
        with pytest.raises(AppError) as self_decision:
            service.decide(
                _actor(REQUESTER_ID),
                request_id,
                payload,
                "break-glass-self-db-01",
                uuid4(),
            )
        assert self_decision.value.code == "BREAK_GLASS_NOT_ELIGIBLE"

        rejected = service.decide(
            _actor(DECIDER_ID),
            request_id,
            payload,
            "break-glass-reject-db-01",
            uuid4(),
        )
        assert rejected.data.status == "rejected"
        with factory() as session:
            assert (
                session.execute(
                    select(func.count())
                    .select_from(UserRole)
                    .where(UserRole.break_glass_request_id == request_id)
                ).scalar_one()
                == 0
            )
            assert (
                session.execute(
                    select(func.count())
                    .select_from(OperationLog)
                    .where(OperationLog.resource_id == request_id)
                ).scalar_one()
                == 2
            )

        with pytest.raises(AppError) as repeated_decision:
            service.decide(
                _actor(DECIDER_ID),
                request_id,
                payload.model_copy(update={"row_version": "2"}),
                "break-glass-reject-db-02",
                uuid4(),
            )
        assert repeated_decision.value.code == "BREAK_GLASS_STATE_CONFLICT"
    finally:
        _clear(engine)
        engine.dispose()


def test_operation_log_query_includes_org_and_anonymous_but_excludes_global_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, _ = _setup(monkeypatch)
    try:
        with factory.begin() as session:
            repository = OperationLogRepository(session)
            user_log = repository.append(
                organization_id=ORGANIZATION_ID,
                actor_kind="user",
                actor_id=REQUESTER_ID,
                action_code="auth.login.succeeded",
                outcome="succeeded",
                resource_type="user",
                resource_id=REQUESTER_ID,
                trace_id=uuid4(),
                change_summary={},
            )
            user_log.created_at = datetime(2026, 8, 13, 3, tzinfo=timezone.utc)
            anonymous_log = repository.append(
                organization_id=None,
                actor_kind="anonymous",
                actor_id=None,
                action_code="auth.login.failed",
                outcome="denied",
                resource_type=None,
                resource_id=None,
                trace_id=uuid4(),
                change_summary={"failure_code": "invalid_credentials"},
            )
            anonymous_log.created_at = datetime(2026, 8, 13, 2, tzinfo=timezone.utc)
            system_log = repository.append(
                organization_id=None,
                actor_kind="system",
                actor_id=None,
                action_code="authorization.denied",
                outcome="denied",
                resource_type=None,
                resource_id=None,
                trace_id=uuid4(),
                change_summary={"permission_code": "users.manage"},
            )
            system_log.created_at = datetime(2026, 8, 13, 1, tzinfo=timezone.utc)

        service = OperationLogQueryService(factory)
        first = service.list_page(ORGANIZATION_ID, None, 1)
        assert tuple(item.action_code for item in first.items) == ("auth.login.succeeded",)
        assert first.next_cursor is not None
        second = service.list_page(ORGANIZATION_ID, first.next_cursor, 1)
        assert tuple(item.action_code for item in second.items) == ("auth.login.failed",)
        assert second.items[0].actor_id is None
        assert second.next_cursor is None
        assert all(
            item.action_code != "authorization.denied" for item in first.items + second.items
        )

        with pytest.raises(AppError) as invalid_cursor:
            service.list_page(ORGANIZATION_ID, "bm90LWNhbm9uaWNhbA", 20)
        assert invalid_cursor.value.code == "VALIDATION_ERROR"
    finally:
        _clear(engine)
        engine.dispose()
