import base64
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.user_read import UserListReadView, UserReadRepository
from app.schemas.users import UserListData, UserListItemData, UserListQuery
from app.services.user_query import UserQueryService, _decode_cursor, _encode_cursor_values

ORGANIZATION_ID = UUID("7b000000-0000-4000-8000-000000000001")
USER_ID = UUID("7b000000-0000-4000-8000-000000000002")


def _view(
    *,
    identity: UUID = USER_ID,
    username: str = "admin.ops",
    status: str = "active",
    roles: tuple[str, ...] = ("system_admin",),
    row_version: int = 3,
) -> UserListReadView:
    return UserListReadView(
        id=identity,
        username=username,
        display_name="平台管理员",
        status=status,
        fixed_roles=roles,
        row_version=row_version,
    )


def _service(repository: Mock, monkeypatch: pytest.MonkeyPatch) -> UserQueryService:
    context = MagicMock()
    context.__enter__.return_value = Mock(spec=Session)
    monkeypatch.setattr(
        "app.services.user_query.UserReadRepository",
        Mock(return_value=repository),
    )
    return UserQueryService(cast(sessionmaker[Session], Mock(return_value=context)))


def _raw_cursor(payload: str) -> str:
    return base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()


def _raw_bytes_cursor(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def _alias_pad_bits(cursor: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    return cursor[:-1] + alphabet[alphabet.index(cursor[-1]) | 1]


def test_service_projects_exact_minimal_user_page(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = Mock()
    repository.read_page.return_value = ((_view(),), True)
    service = _service(repository, monkeypatch)

    result = service.list_page(ORGANIZATION_ID, None, 1)

    repository.read_page.assert_called_once_with(ORGANIZATION_ID, 1, None, None)
    assert result.model_dump(mode="json")["items"] == [
        {
            "id": str(USER_ID),
            "username": "admin.ops",
            "display_name": "平台管理员",
            "status": "active",
            "fixed_roles": ["system_admin"],
            "row_version": "3",
        }
    ]
    assert result.next_cursor is not None
    assert _decode_cursor(result.next_cursor) == ("admin.ops", USER_ID)
    rendered = result.model_dump_json()
    for private_name in (
        "organization_id",
        "email",
        "password_hash",
        "failed_login_count",
        "locked_until",
        "force_change_on_login",
        "permissions",
    ):
        assert private_name not in rendered


@pytest.mark.parametrize(
    "view",
    [
        _view(status="archived"),
        _view(roles=("unknown",)),
        _view(username="Admin.Ops"),
        _view(row_version=0),
    ],
)
def test_projection_fails_closed_for_invalid_persisted_public_values(
    view: UserListReadView,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock()
    repository.read_page.return_value = ((view,), False)

    with pytest.raises(ValidationError):
        _service(repository, monkeypatch).list_page(ORGANIZATION_ID, None, 20)


def test_public_schemas_are_strict_frozen_and_enforce_page_shape() -> None:
    item = UserListItemData(
        id=USER_ID,
        username="admin.ops",
        display_name="平台管理员",
        status="active",
        fixed_roles=("system_admin",),
        row_version="3",
    )
    data = UserListData(items=(item,), page_size=20, next_cursor=None)

    with pytest.raises(ValidationError):
        UserListQuery.model_validate({"page": 1})
    with pytest.raises(ValidationError):
        UserListItemData(
            **item.model_dump(),
            private="sentinel",  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        UserListData(items=(item,), page_size=20, next_cursor="invalid")
    with pytest.raises(ValidationError):
        UserListData(items=(item, item), page_size=20, next_cursor=None)
    with pytest.raises(ValidationError):
        data.next_cursor = "mutated"


@pytest.mark.parametrize(
    "cursor",
    [
        "not+url",
        "abc=",
        "a" * 257,
        "e30",
        _alias_pad_bits("e30"),
        _raw_cursor(
            '{"id":"7b000000-0000-4000-8000-000000000002","username":"admin.ops","v":1,"v":1}'
        ),
        _raw_cursor(
            '{"extra":null,"id":"7b000000-0000-4000-8000-000000000002",'
            '"username":"admin.ops","v":1}'
        ),
        _raw_cursor(
            '{"id":"7b000000-0000-4000-8000-000000000002","username":"admin.ops","v":true}'
        ),
        _raw_cursor('{"id":"7b000000-0000-4000-8000-000000000002","username":"admin.ops","v":2}'),
        _raw_cursor('{"id":"7B000000-0000-4000-8000-000000000002","username":"admin.ops","v":1}'),
        _raw_cursor('{"id":"7b000000000040008000000000000002","username":"admin.ops","v":1}'),
        _raw_cursor('{"id":"7b000000-0000-4000-8000-000000000002","username":"Admin.Ops","v":1}'),
        _raw_cursor('{"v":1,"username":"admin.ops","id":"7b000000-0000-4000-8000-000000000002"}'),
        _raw_cursor(
            '{ "id": "7b000000-0000-4000-8000-000000000002", "username": "admin.ops", "v": 1 }'
        ),
        _raw_bytes_cursor(b"\xff"),
    ],
)
def test_service_rejects_untrusted_cursor(cursor: str) -> None:
    service = UserQueryService(cast(sessionmaker[Session], Mock()))

    with pytest.raises(AppError) as captured:
        service.list_page(ORGANIZATION_ID, cursor, 20)

    assert captured.value.status_code == 422
    assert captured.value.code == "VALIDATION_ERROR"
    assert captured.value.details == [{"field": "query.cursor", "reason": "invalid"}]
    assert cursor not in str(captured.value)


def test_cursor_round_trips_canonical_position() -> None:
    cursor = _encode_cursor_values("admin.ops", USER_ID)

    assert "=" not in cursor
    assert _decode_cursor(cursor) == ("admin.ops", USER_ID)


def test_repository_uses_bounded_scoped_projection_and_fixed_roles() -> None:
    session = Mock(spec=Session)
    user_result = Mock()
    user_result.all.return_value = [
        SimpleNamespace(
            id=USER_ID,
            username="admin.ops",
            display_name="平台管理员",
            status="active",
            row_version=3,
        )
    ]
    now_result = Mock()
    now_result.scalar_one.return_value = datetime(2026, 8, 13, tzinfo=timezone.utc)
    role_result = Mock()
    role_result.all.return_value = [(USER_ID, "system_admin")]
    session.execute.side_effect = [user_result, now_result, role_result]

    result = UserReadRepository(session).read_page(
        ORGANIZATION_ID,
        1,
        "admin.ops",
        UUID(int=USER_ID.int - 1),
    )

    assert result == ((_view(),), False)
    user_sql = str(
        session.execute.call_args_list[0]
        .args[0]
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    role_sql = str(
        session.execute.call_args_list[2]
        .args[0]
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "users.organization_id" in user_sql
    assert "users.deleted_at IS NULL" in user_sql
    assert "organizations.deleted_at IS NULL" in user_sql
    assert "organizations.status = 'active'" in user_sql
    assert "users.username > 'admin.ops'" in user_sql
    assert "ORDER BY users.username ASC, users.id ASC" in user_sql
    assert "LIMIT 2" in user_sql
    assert "OFFSET" not in user_sql
    for private_column in (
        "users.email",
        "users.password_hash",
        "users.failed_login_count",
        "users.locked_until",
        "users.force_change_on_login",
        "users.token_invalid_before",
    ):
        assert private_column not in user_sql.split("FROM", 1)[0]
    assert "user_roles.assignment_source IN ('bootstrap', 'user')" in role_sql
    assert "user_roles.assigned_at <=" in role_sql
    assert "user_roles.expires_at IS NULL" in role_sql
    assert "user_roles.revoked_at IS NULL" in role_sql
    assert "roles.is_enabled IS true" in role_sql


def test_repository_rejects_unknown_role_code() -> None:
    session = Mock(spec=Session)
    user_result = Mock()
    user_result.all.return_value = [
        SimpleNamespace(
            id=USER_ID,
            username="admin.ops",
            display_name="平台管理员",
            status="active",
            row_version=3,
        )
    ]
    now_result = Mock()
    now_result.scalar_one.return_value = datetime.now(timezone.utc)
    role_result = Mock()
    role_result.all.return_value = [(USER_ID, "owner")]
    session.execute.side_effect = [user_result, now_result, role_result]

    with pytest.raises(RuntimeError, match="unknown fixed role"):
        UserReadRepository(session).read_page(ORGANIZATION_ID, 20)
