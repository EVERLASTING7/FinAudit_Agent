"""auth-mvp-v1 的 PostgreSQL 用户、角色与会话访问。"""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from app.models.auth import Organization, Role, TokenSession, User, UserRole


class AuthRepository:
    """封装认证事务所需的固定锁序和组织边界查询。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def database_now(self) -> datetime:
        return cast(
            datetime,
            self._session.execute(select(func.clock_timestamp())).scalar_one(),
        )

    def _active_user_query(self) -> Select[tuple[User]]:
        return (
            select(User)
            .join(Organization, Organization.id == User.organization_id)
            .where(
                User.deleted_at.is_(None),
                Organization.deleted_at.is_(None),
                Organization.status == "active",
            )
        )

    def lock_user_by_username(self, username: str) -> User | None:
        return self._session.execute(
            self._active_user_query().where(User.username == username).with_for_update(of=User)
        ).scalar_one_or_none()

    def lock_user_by_id(self, user_id: UUID) -> User | None:
        return self._session.execute(
            self._active_user_query().where(User.id == user_id).with_for_update(of=User)
        ).scalar_one_or_none()

    def read_user_by_id(self, user_id: UUID) -> User | None:
        return self._session.execute(
            self._active_user_query().where(User.id == user_id)
        ).scalar_one_or_none()

    def read_user_identity_by_id(self, user_id: UUID) -> User | None:
        """读取日志归属所需身份；不把该方法用于授权决定。"""

        return self._session.get(User, user_id)

    def find_session_user_id(self, session_id: UUID) -> UUID | None:
        return self._session.execute(
            select(TokenSession.user_id).where(TokenSession.id == session_id)
        ).scalar_one_or_none()

    def lock_token_session(self, session_id: UUID) -> TokenSession | None:
        return self._session.execute(
            select(TokenSession).where(TokenSession.id == session_id).with_for_update()
        ).scalar_one_or_none()

    def read_token_session(self, session_id: UUID) -> TokenSession | None:
        return self._session.get(TokenSession, session_id)

    def active_role_codes(self, user_id: UUID, now: datetime) -> tuple[str, ...]:
        rows = self._session.execute(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                UserRole.assigned_at <= now,
                UserRole.revoked_at.is_(None),
                (UserRole.expires_at.is_(None) | (UserRole.expires_at > now)),
                Role.is_enabled.is_(True),
            )
            .order_by(Role.code)
        ).scalars()
        return tuple(rows)

    def add_token_session(self, token_session: TokenSession) -> None:
        self._session.add(token_session)

    def revoke_all_user_sessions(self, user_id: UUID, now: datetime, reason: str) -> None:
        self._session.execute(
            update(TokenSession)
            .where(TokenSession.user_id == user_id, TokenSession.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason=reason)
        )


__all__ = ["AuthRepository"]
