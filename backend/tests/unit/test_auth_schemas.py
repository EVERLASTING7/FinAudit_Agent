from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.permissions import PERMISSION_CODES, ROLE_CODES
from app.schemas.auth import AuthSessionData, CurrentUserData, LoginRequest


def test_login_request_accepts_canonical_numeric_username() -> None:
    request = LoginRequest(username="123", password="x" * 15, remember_me=False)

    assert request.username == "123"


@pytest.mark.parametrize("username", ("Admin", " user", "用户", "a/b", ""))
def test_login_request_rejects_noncanonical_username(username: str) -> None:
    with pytest.raises(ValidationError):
        LoginRequest(username=username, password="x" * 15, remember_me=False)


def test_session_schema_uses_the_closed_role_and_permission_dictionaries() -> None:
    user = CurrentUserData(
        id=UUID("60000000-0000-4000-8000-000000000001"),
        display_name="Test User",
        roles=tuple(sorted(ROLE_CODES)),
        permissions=PERMISSION_CODES,
    )

    session = AuthSessionData(access_token="synthetic-token", user=user)

    assert session.expires_in == 900
    assert session.token_type == "Bearer"


def test_current_user_rejects_unknown_permission() -> None:
    with pytest.raises(ValidationError):
        CurrentUserData(
            id=UUID("60000000-0000-4000-8000-000000000001"),
            display_name="Test User",
            roles=("read_only",),
            permissions=("wildcard.*",),
        )


@pytest.mark.parametrize(
    ("roles", "permissions"),
    (
        (("read_only", "read_only"), ("audits.read", "reports.read")),
        (("read_only",), ("reports.read", "audits.read")),
    ),
)
def test_current_user_rejects_duplicate_or_unsorted_codes(
    roles: tuple[str, ...], permissions: tuple[str, ...]
) -> None:
    with pytest.raises(ValidationError):
        CurrentUserData(
            id=UUID("60000000-0000-4000-8000-000000000001"),
            display_name="Test User",
            roles=roles,
            permissions=permissions,
        )
