"""用户管理写事务的锁序、幂等和持久化访问。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.auth import (
    BreakGlassRequest,
    Organization,
    Role,
    TokenSession,
    User,
    UserRole,
)
from app.models.reliability import IdempotencyRecord


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    record: IdempotencyRecord
    replay_status: int | None = None
    replay_body: dict[str, object] | None = None
    conflict: bool = False

    @property
    def is_replay(self) -> bool:
        return self.replay_status is not None


class UserWriteRepository:
    """按组织锁、幂等锁、目标用户、角色行的固定顺序访问数据库。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def database_now(self) -> datetime:
        return cast(
            datetime,
            self._session.execute(select(func.clock_timestamp())).scalar_one(),
        )

    def acquire_organization_lock(self, organization_id: UUID) -> None:
        identity = f"finaudit:user-management:{organization_id}"
        self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(identity, 0)))
        ).one()

    def acquire_idempotency_lock(
        self,
        organization_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> None:
        identity = f"{organization_id}:{actor_id}:{idempotency_key}"
        self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(identity, 1)))
        ).one()

    def lock_active_organization(self, organization_id: UUID) -> Organization | None:
        return self._session.execute(
            select(Organization)
            .where(
                Organization.id == organization_id,
                Organization.status == "active",
                Organization.deleted_at.is_(None),
            )
            .with_for_update(of=Organization)
        ).scalar_one_or_none()

    def claim_idempotency(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
        request_method: str,
        request_path: str,
        request_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> IdempotencyClaim:
        record = self._session.execute(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.organization_id == organization_id,
                IdempotencyRecord.user_id == actor_id,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
            .with_for_update(of=IdempotencyRecord)
        ).scalar_one_or_none()
        if record is not None and record.expires_at > now:
            if (
                record.request_method != request_method
                or record.request_path != request_path
                or record.request_hash != request_hash
            ):
                return IdempotencyClaim(record=record, conflict=True)
            if record.response_status is None or record.response_body_json is None:
                raise RuntimeError("committed idempotency record is incomplete")
            return IdempotencyClaim(
                record=record,
                replay_status=record.response_status,
                replay_body=dict(record.response_body_json),
            )

        if record is None:
            record = IdempotencyRecord(
                organization_id=organization_id,
                user_id=actor_id,
                idempotency_key=idempotency_key,
                request_method=request_method,
                request_path=request_path,
                request_hash=request_hash,
                expires_at=expires_at,
                created_at=now,
            )
            self._session.add(record)
        else:
            record.request_method = request_method
            record.request_path = request_path
            record.request_hash = request_hash
            record.response_status = None
            record.response_body_json = None
            record.resource_type = None
            record.resource_id = None
            record.expires_at = expires_at
            record.created_at = now
        return IdempotencyClaim(record=record)

    def inspect_idempotency(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
        request_method: str,
        request_path: str,
        request_hash: str,
        now: datetime,
    ) -> IdempotencyClaim | None:
        """在短事务锁内识别已完成重放；不存在或已过期时不创建事实。"""

        record = self._session.execute(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.organization_id == organization_id,
                IdempotencyRecord.user_id == actor_id,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
            .with_for_update(of=IdempotencyRecord)
        ).scalar_one_or_none()
        if record is None or record.expires_at <= now:
            return None
        if (
            record.request_method != request_method
            or record.request_path != request_path
            or record.request_hash != request_hash
        ):
            return IdempotencyClaim(record=record, conflict=True)
        if record.response_status is None or record.response_body_json is None:
            raise RuntimeError("committed idempotency record is incomplete")
        return IdempotencyClaim(
            record=record,
            replay_status=record.response_status,
            replay_body=dict(record.response_body_json),
        )

    @staticmethod
    def complete_idempotency(
        claim: IdempotencyClaim,
        *,
        response_status: int,
        response_body: dict[str, object],
        resource_id: UUID,
        resource_type: str = "user",
    ) -> None:
        claim.record.response_status = response_status
        claim.record.response_body_json = response_body
        claim.record.resource_type = resource_type
        claim.record.resource_id = resource_id

    def lock_user(self, organization_id: UUID, user_id: UUID) -> User | None:
        return self._session.execute(
            select(User)
            .where(
                User.id == user_id,
                User.organization_id == organization_id,
                User.deleted_at.is_(None),
            )
            .with_for_update(of=User)
        ).scalar_one_or_none()

    def lock_break_glass_request(
        self,
        organization_id: UUID,
        request_id: UUID,
    ) -> BreakGlassRequest | None:
        return self._session.execute(
            select(BreakGlassRequest)
            .where(
                BreakGlassRequest.id == request_id,
                BreakGlassRequest.organization_id == organization_id,
            )
            .with_for_update(of=BreakGlassRequest)
        ).scalar_one_or_none()

    def lock_break_glass_assignment(self, request_id: UUID) -> UserRole | None:
        return self._session.execute(
            select(UserRole)
            .where(UserRole.break_glass_request_id == request_id)
            .with_for_update(of=UserRole)
        ).scalar_one_or_none()

    def lock_enabled_roles(self, role_codes: tuple[str, ...]) -> dict[str, Role]:
        rows = self._session.execute(
            select(Role)
            .where(Role.code.in_(role_codes), Role.is_enabled.is_(True))
            .order_by(Role.code)
            .with_for_update(of=Role)
        ).scalars()
        return {role.code: role for role in rows}

    def lock_active_fixed_assignments(
        self,
        user_id: UUID,
        now: datetime,
    ) -> tuple[tuple[UserRole, str], ...]:
        rows = self._session.execute(
            select(UserRole, Role.code)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                UserRole.user_id == user_id,
                UserRole.assignment_source.in_(("bootstrap", "user")),
                UserRole.assigned_at <= now,
                UserRole.expires_at.is_(None),
                UserRole.revoked_at.is_(None),
                Role.is_enabled.is_(True),
            )
            .order_by(Role.code, UserRole.id)
            .with_for_update(of=UserRole)
        ).all()
        return tuple((cast(UserRole, row[0]), str(row[1])) for row in rows)

    def active_system_admin_count(self, organization_id: UUID, now: datetime) -> int:
        return int(
            self._session.execute(
                select(func.count(func.distinct(User.id)))
                .join(UserRole, UserRole.user_id == User.id)
                .join(Role, Role.id == UserRole.role_id)
                .where(
                    User.organization_id == organization_id,
                    User.status == "active",
                    User.deleted_at.is_(None),
                    UserRole.assignment_source.in_(("bootstrap", "user")),
                    UserRole.assigned_at <= now,
                    UserRole.expires_at.is_(None),
                    UserRole.revoked_at.is_(None),
                    Role.code == "system_admin",
                    Role.is_enabled.is_(True),
                )
            ).scalar_one()
        )

    def revoke_all_user_sessions(self, user_id: UUID, now: datetime, reason: str) -> None:
        self._session.execute(
            update(TokenSession)
            .where(TokenSession.user_id == user_id, TokenSession.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason=reason)
        )

    def add(self, value: object) -> None:
        self._session.add(value)

    def flush(self) -> None:
        self._session.flush()

    def refresh(self, value: object) -> None:
        self._session.refresh(value)


__all__ = ["IdempotencyClaim", "UserWriteRepository"]
