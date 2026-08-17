"""operation-log-read-v1 的公开 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.operations import OPERATION_LOG_ACTION_CODES


class OperationLogListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=20, ge=1, le=100)


class OperationLogItemData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    actor_kind: Literal["anonymous", "user", "system"]
    actor_id: UUID | None
    action_code: str
    outcome: Literal["succeeded", "denied", "failed"]
    resource_type: str | None
    resource_id: UUID | None
    trace_id: UUID
    change_summary: dict[str, object]
    created_at: datetime

    @field_validator("action_code")
    @classmethod
    def validate_action_code(cls, value: str) -> str:
        if value not in OPERATION_LOG_ACTION_CODES:
            raise ValueError("action_code is not registered")
        return value

    @model_validator(mode="after")
    def validate_identity_shape(self) -> OperationLogItemData:
        if (self.actor_kind == "user") != (self.actor_id is not None):
            raise ValueError("actor identity shape is invalid")
        if (self.resource_type is None) != (self.resource_id is None):
            raise ValueError("resource identity shape is invalid")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return self


class OperationLogListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[OperationLogItemData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_page(self) -> OperationLogListData:
        if len(self.items) > self.page_size:
            raise ValueError("items exceed page_size")
        if self.next_cursor is not None and len(self.items) != self.page_size:
            raise ValueError("next_cursor requires a full page")
        identities = tuple(item.id for item in self.items)
        if len(identities) != len(set(identities)):
            raise ValueError("items contain duplicate ids")
        return self


__all__ = ["OperationLogItemData", "OperationLogListData", "OperationLogListQuery"]
