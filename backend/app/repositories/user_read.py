"""Organization-scoped read repository for user-list-read-v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_CODES
from app.models.auth import Organization, Role, User, UserRole


@dataclass(frozen=True, slots=True)
class UserListReadView:
    id: UUID
    username: str = field(repr=False)
    display_name: str = field(repr=False)
    status: str
    fixed_roles: tuple[str, ...]
    row_version: int


class UserReadRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def read_page(
        self,
        organization_id: UUID,
        page_size: int,
        cursor_username: str | None = None,
        cursor_id: UUID | None = None,
    ) -> tuple[tuple[UserListReadView, ...], bool]:
        """Read one bounded page and only its current fixed role assignments."""

        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be an integer between 1 and 100")
        if cursor_username is not None and type(cursor_username) is not str:
            raise ValueError("cursor_username must be an exact str")
        if cursor_id is not None and type(cursor_id) is not UUID:
            raise ValueError("cursor_id must be an exact uuid.UUID")
        if (cursor_username is None) != (cursor_id is None):
            raise ValueError("cursor username and id must be provided together")

        statement = (
            select(
                User.id,
                User.username,
                User.display_name,
                User.status,
                User.row_version,
            )
            .join(Organization, Organization.id == User.organization_id)
            .where(
                User.organization_id == organization_id,
                User.deleted_at.is_(None),
                Organization.id == organization_id,
                Organization.deleted_at.is_(None),
                Organization.status == "active",
            )
        )
        if cursor_username is not None and cursor_id is not None:
            statement = statement.where(
                or_(
                    User.username > cursor_username,
                    and_(User.username == cursor_username, User.id > cursor_id),
                )
            )
        user_rows = self._session.execute(
            statement.order_by(User.username.asc(), User.id.asc()).limit(page_size + 1)
        ).all()
        has_more = len(user_rows) > page_size
        page_rows = user_rows[:page_size]
        if not page_rows:
            return (), has_more

        database_now = cast(
            datetime,
            self._session.execute(select(func.clock_timestamp())).scalar_one(),
        )
        page_user_ids = tuple(row.id for row in page_rows)
        role_rows = self._session.execute(
            select(UserRole.user_id, Role.code)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                UserRole.user_id.in_(page_user_ids),
                UserRole.assignment_source.in_(("bootstrap", "user")),
                UserRole.assigned_at <= database_now,
                UserRole.expires_at.is_(None),
                UserRole.revoked_at.is_(None),
                Role.is_enabled.is_(True),
            )
        ).all()
        roles_by_user: dict[UUID, set[str]] = {user_id: set() for user_id in page_user_ids}
        valid_roles = set(ROLE_CODES)
        for user_id, role_code in role_rows:
            if role_code not in valid_roles:
                raise RuntimeError("database contains an unknown fixed role")
            roles_by_user[user_id].add(role_code)

        return (
            tuple(
                UserListReadView(
                    id=row.id,
                    username=row.username,
                    display_name=row.display_name,
                    status=row.status,
                    fixed_roles=tuple(sorted(roles_by_user[row.id])),
                    row_version=row.row_version,
                )
                for row in page_rows
            ),
            has_more,
        )


__all__ = ["UserListReadView", "UserReadRepository"]
