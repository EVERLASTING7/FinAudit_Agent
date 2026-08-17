"""user-list-read-v1 public request and response schemas."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.permissions import RoleCode

UserStatus = Literal["active", "disabled", "locked"]
PositiveIntegerString = Annotated[str, Field(pattern=r"^[1-9]\d*$")]
_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")


def _validate_fixed_role_values(value: tuple[RoleCode, ...]) -> tuple[RoleCode, ...]:
    if not value or value != tuple(sorted(set(value))):
        raise ValueError("fixed_roles must be non-empty, unique and sorted")
    return value


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    username: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    initial_password: str = Field(min_length=1, max_length=512, repr=False)
    fixed_roles: tuple[RoleCode, ...] = Field(min_length=1, max_length=5)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if _USERNAME_PATTERN.fullmatch(value) is None:
            raise ValueError("username format is invalid")
        return value

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        if value != value.strip() or any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("display_name format is invalid")
        return value

    @field_validator("fixed_roles", mode="before")
    @classmethod
    def require_json_role_array(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("fixed_roles must be an array")
        return tuple(value)

    @field_validator("fixed_roles")
    @classmethod
    def validate_fixed_roles(cls, value: tuple[RoleCode, ...]) -> tuple[RoleCode, ...]:
        return _validate_fixed_role_values(value)


class UserStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["active", "disabled"]
    row_version: PositiveIntegerString


class UserPasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    new_password: str = Field(min_length=1, max_length=512, repr=False)
    row_version: PositiveIntegerString


class UserRolesReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    fixed_roles: tuple[RoleCode, ...] = Field(min_length=1, max_length=5)
    row_version: PositiveIntegerString

    @field_validator("fixed_roles", mode="before")
    @classmethod
    def require_json_role_array(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("fixed_roles must be an array")
        return tuple(value)

    @field_validator("fixed_roles")
    @classmethod
    def validate_fixed_roles(cls, value: tuple[RoleCode, ...]) -> tuple[RoleCode, ...]:
        return _validate_fixed_role_values(value)


class UserListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=20, ge=1, le=100)


class UserWriteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UserListItemData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    username: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,99}$",
    )
    display_name: str
    status: UserStatus
    fixed_roles: tuple[RoleCode, ...]
    row_version: PositiveIntegerString

    @field_validator("fixed_roles")
    @classmethod
    def validate_fixed_roles(cls, value: tuple[RoleCode, ...]) -> tuple[RoleCode, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("fixed_roles must be unique and sorted")
        return value


class UserListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[UserListItemData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_page_shape(self) -> UserListData:
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size")
        if self.next_cursor is not None and len(self.items) != self.page_size:
            raise ValueError("next_cursor requires a full page")
        item_ids = tuple(item.id for item in self.items)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("items cannot contain duplicate ids")
        return self


__all__ = [
    "UserCreateRequest",
    "UserListData",
    "UserListItemData",
    "UserListQuery",
    "UserPasswordResetRequest",
    "UserRolesReplaceRequest",
    "UserStatus",
    "UserStatusUpdateRequest",
    "UserWriteQuery",
]
