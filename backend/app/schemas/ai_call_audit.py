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
    event_version: Literal[1, 2] = 1
    reserved_input_tokens: int = Field(ge=0)
    reserved_output_tokens: int = Field(ge=0)
    reserved_cost_micro_usd: int | None = Field(default=None, ge=0)
    cost_currency: Literal["USD", "CNY"] | None = None
    reserved_cost_microunits: int | None = Field(default=None, ge=0)
    actual_cost_microunits: int | None = Field(default=None, ge=0)
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
        if self.event_version == 1:
            if (
                self.reserved_cost_micro_usd is None
                or self.cost_currency is not None
                or self.reserved_cost_microunits is not None
                or self.actual_cost_microunits is not None
            ):
                raise ValueError("Event v1 cost fields are invalid")
        elif (
            self.reserved_cost_micro_usd is not None
            or self.reserved_cost_microunits is None
            or (
                self.cost_currency is None
                and (
                    self.reserved_cost_microunits != 0
                    or self.actual_cost_microunits not in (None, 0)
                )
            )
            or (self.status == "succeeded" and self.actual_cost_microunits is None)
            or (
                self.status in {"pending", "outcome_unknown"}
                and self.actual_cost_microunits is not None
            )
        ):
            raise ValueError("Event v2 cost fields are invalid")
        return self


class AiCallAuditSummaryData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    business_operation_id: UUID
    attempt_count: int = Field(ge=0)
    reserved_input_tokens: int = Field(ge=0)
    reserved_output_tokens: int = Field(ge=0)
    reserved_cost_micro_usd: int | None = Field(default=None, ge=0)
    cost_currency: Literal["USD", "CNY"] | None = None
    reserved_cost_microunits: int | None = Field(default=None, ge=0)
    actual_cost_microunits: int | None = Field(default=None, ge=0)
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
        versions = {item.event_version for item in self.attempts}
        if versions == {1}:
            if (
                self.reserved_cost_micro_usd is None
                or self.cost_currency is not None
                or self.reserved_cost_microunits is not None
                or self.actual_cost_microunits is not None
            ):
                raise ValueError("Event v1 summary cost fields are invalid")
        elif versions == {2}:
            currencies = {item.cost_currency for item in self.attempts}
            authoritative = all(item.actual_cost_microunits is not None for item in self.attempts)
            if (
                len(currencies) != 1
                or self.reserved_cost_micro_usd is not None
                or self.cost_currency != next(iter(currencies))
                or self.reserved_cost_microunits is None
                or authoritative != (self.actual_cost_microunits is not None)
            ):
                raise ValueError("Event v2 summary cost fields are invalid")
        else:
            raise ValueError("AI audit summary cannot mix Event versions")
        return self


__all__ = [
    "AiCallAttemptData",
    "AiCallAuditQuery",
    "AiCallAuditSummaryData",
    "AiCallStatus",
]
