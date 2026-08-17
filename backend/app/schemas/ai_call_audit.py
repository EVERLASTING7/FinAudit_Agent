"""OPS-005 AI 调用摘要公开只读契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AiCallStatus: TypeAlias = Literal[
    "pending",
    "succeeded",
    "failed",
    "degraded",
    "rejected",
    "outcome_unknown",
]


class AiCallAuditQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    business_operation_id: UUID


class AiCallAttemptData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: UUID
    provider_attempt_no: int = Field(ge=1)
    logical_generation_no: int = Field(ge=1)
    model_id: str = Field(min_length=1, max_length=200)
    is_fallback: bool
    status: AiCallStatus
    reserved_input_tokens: int = Field(ge=0)
    reserved_output_tokens: int = Field(ge=0)
    reserved_cost_micro_usd: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    trace_id: UUID
    started_at: datetime
    completed_at: datetime | None
    safe_error_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("AI audit timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_completion_shape(self) -> AiCallAttemptData:
        if (self.status == "pending") != (self.completed_at is None):
            raise ValueError("AI audit completion shape is invalid")
        return self


class AiCallAuditSummaryData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    business_operation_id: UUID
    attempt_count: int = Field(ge=0)
    reserved_input_tokens: int = Field(ge=0)
    reserved_output_tokens: int = Field(ge=0)
    reserved_cost_micro_usd: int = Field(ge=0)
    actual_input_tokens: int = Field(ge=0)
    actual_output_tokens: int = Field(ge=0)
    attempts: tuple[AiCallAttemptData, ...]

    @model_validator(mode="after")
    def validate_summary(self) -> AiCallAuditSummaryData:
        if self.attempt_count != len(self.attempts):
            raise ValueError("AI audit attempt count is inconsistent")
        if tuple(item.provider_attempt_no for item in self.attempts) != tuple(
            range(1, self.attempt_count + 1)
        ):
            raise ValueError("AI audit attempts must be continuous and ordered")
        return self


__all__ = [
    "AiCallAttemptData",
    "AiCallAuditQuery",
    "AiCallAuditSummaryData",
    "AiCallStatus",
]
