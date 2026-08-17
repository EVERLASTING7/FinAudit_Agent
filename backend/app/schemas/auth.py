"""auth-mvp-v1 HTTP 请求、会话和当前用户合同。"""

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.permissions import PermissionCode, RoleCode

_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=512)
    remember_me: bool = False

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if _USERNAME_PATTERN.fullmatch(value) is None:
            raise ValueError("username format is invalid")
        return value


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    new_password: str = Field(min_length=1, max_length=512)


class CurrentUserData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    display_name: str
    roles: tuple[RoleCode, ...]
    permissions: tuple[PermissionCode, ...]

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, value: tuple[RoleCode, ...]) -> tuple[RoleCode, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("roles must be unique and sorted")
        return value

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, value: tuple[PermissionCode, ...]) -> tuple[PermissionCode, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("permissions must be unique and sorted")
        return value


class AuthSessionData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    access_token: str = Field(repr=False)
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: Literal[900] = 900
    user: CurrentUserData


__all__ = [
    "AuthSessionData",
    "CurrentUserData",
    "LoginRequest",
    "PasswordChangeRequest",
]
