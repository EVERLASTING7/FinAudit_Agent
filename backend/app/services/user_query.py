"""user-list-read-v1 organization-scoped query use case."""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.core.permissions import RoleCode
from app.repositories.user_read import UserListReadView, UserReadRepository
from app.schemas.users import UserListData, UserListItemData, UserStatus

_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")


def _invalid_cursor() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=[{"field": "query.cursor", "reason": "invalid"}],
    )


def _encode_cursor_values(username: str, user_id: UUID) -> str:
    payload = json.dumps(
        {"v": 1, "username": username, "id": str(user_id)},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor(value: str) -> tuple[str, UUID]:
    if not value or len(value) > 256 or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise _invalid_cursor()
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
        if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
            raise ValueError("noncanonical base64url")
        raw = decoded.decode("utf-8")

        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            parsed: dict[str, object] = {}
            for key, child in pairs:
                if key in parsed:
                    raise ValueError("duplicate cursor key")
                parsed[key] = child
            return parsed

        payload = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
        if type(payload) is not dict or set(payload) != {"v", "username", "id"}:
            raise ValueError("invalid cursor object")
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError("unsupported cursor version")
        username = payload["username"]
        if type(username) is not str or _USERNAME_PATTERN.fullmatch(username) is None:
            raise ValueError("invalid cursor username")
        raw_id = payload["id"]
        if type(raw_id) is not str:
            raise ValueError("invalid cursor id")
        user_id = UUID(raw_id)
        if str(user_id) != raw_id:
            raise ValueError("noncanonical cursor id")
        if _encode_cursor_values(username, user_id) != value:
            raise ValueError("noncanonical cursor json")
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None
    return username, user_id


def _project_user(user: UserListReadView) -> UserListItemData:
    return UserListItemData(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        status=cast(UserStatus, user.status),
        fixed_roles=cast(tuple[RoleCode, ...], user.fixed_roles),
        row_version=str(user.row_version),
    )


class UserQueryService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_page(
        self,
        organization_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> UserListData:
        cursor_username: str | None = None
        cursor_id: UUID | None = None
        if cursor is not None:
            cursor_username, cursor_id = _decode_cursor(cursor)
        with self._session_factory() as session:
            users, has_more = UserReadRepository(session).read_page(
                organization_id,
                page_size,
                cursor_username,
                cursor_id,
            )
        return UserListData(
            items=tuple(_project_user(user) for user in users),
            page_size=page_size,
            next_cursor=(
                _encode_cursor_values(users[-1].username, users[-1].id) if has_more else None
            ),
        )


__all__ = ["UserQueryService"]
