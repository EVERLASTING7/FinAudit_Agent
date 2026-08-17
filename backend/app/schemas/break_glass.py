"""break-glass-write-v1 的严格公开 Schema。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.users import PositiveIntegerString

BreakGlassRoleCode = Literal[
    "system_admin",
    "finance_reviewer",
    "audit_reviewer",
    "contract_admin",
]
BreakGlassStatus = Literal["pending", "approved", "rejected", "revoked", "expired"]


def _trim_reason(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise ValueError("reason is invalid")
    return normalized


class BreakGlassCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: UUID
    target_role_code: BreakGlassRoleCode
    requested_duration_seconds: int = Field(ge=1, le=14_400, strict=True)
    reason: str = Field(min_length=1, max_length=500, repr=False, strict=True)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _trim_reason(value)


class BreakGlassDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=500, repr=False)
    row_version: PositiveIntegerString

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _trim_reason(value)


class BreakGlassRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reason: str = Field(min_length=1, max_length=500, repr=False)
    row_version: PositiveIntegerString

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _trim_reason(value)


class BreakGlassData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    target_user_id: UUID
    target_role_code: BreakGlassRoleCode
    requested_duration_seconds: int = Field(ge=1, le=14_400)
    status: BreakGlassStatus
    effective_from: datetime | None
    expires_at: datetime | None
    row_version: PositiveIntegerString


class BreakGlassWriteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


__all__ = [
    "BreakGlassCreateRequest",
    "BreakGlassData",
    "BreakGlassDecisionRequest",
    "BreakGlassRevokeRequest",
    "BreakGlassRoleCode",
    "BreakGlassStatus",
    "BreakGlassWriteQuery",
]
