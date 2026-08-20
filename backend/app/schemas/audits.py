"""审核任务、执行版本和人工复核的 API 合同。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.jobs import JobActionProjectionData

PositiveIntegerString = Annotated[str, Field(pattern=r"^[1-9]\d*$")]
AuditTaskStatus = Literal["open", "completed", "archived"]
AuditExecutionStatus = Literal[
    "draft",
    "validating",
    "queued",
    "running",
    "pending_finance_review",
    "pending_audit_review",
    "returned_for_correction",
    "completed",
    "failed",
    "cancelled",
    "outdated",
]
RuleExecutionStatus = Literal["passed", "failed", "not_applicable", "error"]
RiskLevel = Literal["none", "notice", "low", "medium", "high"]
RiskReviewStatus = Literal["pending", "confirmed", "dismissed", "adjusted", "returned"]
AiArtifactStatus = Literal["disabled", "succeeded", "degraded"]


def _canonical_uuid(value: object, field_name: str) -> object:
    if value is None or type(value) is UUID:
        return value
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError(f"{field_name} must be a canonical UUID") from None
    if str(parsed) != value:
        raise ValueError(f"{field_name} must be a canonical UUID")
    return parsed


def _canonical_date(value: object, field_name: str) -> object:
    if type(value) is date:
        return value
    if type(value) is not str:
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    return parsed


def _trimmed(value: str, field_name: str) -> str:
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain outer whitespace")
    return value


class AuditTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task_no: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z0-9][A-Z0-9._/-]*$")
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, min_length=1, max_length=4000)
    baseline_date: date
    contract_id: UUID | None = None
    invoice_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)

    @field_validator("baseline_date", mode="before")
    @classmethod
    def parse_baseline_date(cls, value: object) -> object:
        return _canonical_date(value, "baseline_date")

    @field_validator("contract_id", mode="before")
    @classmethod
    def parse_contract_id(cls, value: object) -> object:
        return _canonical_uuid(value, "contract_id")

    @field_validator("invoice_ids", mode="before")
    @classmethod
    def parse_invoice_ids(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("invoice_ids must be an array")
        return tuple(_canonical_uuid(item, "invoice_ids") for item in value)

    @field_validator("name", "description")
    @classmethod
    def validate_text(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return None
        field_name = getattr(info, "field_name", "text")
        return _trimmed(value, field_name)

    @model_validator(mode="after")
    def validate_invoice_order(self) -> AuditTaskCreateRequest:
        if len(set(self.invoice_ids)) != len(self.invoice_ids) or self.invoice_ids != tuple(
            sorted(self.invoice_ids, key=lambda item: item.bytes)
        ):
            raise ValueError("invoice_ids must be unique and sorted")
        return self


class AuditExecutionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task_row_version: PositiveIntegerString
    baseline_date: date
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("baseline_date", mode="before")
    @classmethod
    def parse_baseline_date(cls, value: object) -> object:
        return _canonical_date(value, "baseline_date")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _trimmed(value, "reason")


class AuditRiskReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    decision: Literal["confirmed", "dismissed", "adjusted"]
    effective_level: RiskLevel | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _trimmed(value, "reason")

    @model_validator(mode="after")
    def validate_decision(self) -> AuditRiskReviewRequest:
        if (self.decision == "adjusted") != (self.effective_level is not None):
            raise ValueError("adjusted decision alone requires effective_level")
        return self


class AuditFinanceReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    decision: Literal["submit", "return"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _trimmed(value, "reason")


class AuditReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    decision: Literal["complete", "return"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _trimmed(value, "reason")


class AuditCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    execution_row_version: PositiveIntegerString
    job_row_version: PositiveIntegerString | None
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _trimmed(value, "reason")


class AuditRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    execution_row_version: PositiveIntegerString
    job_row_version: PositiveIntegerString
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _trimmed(value, "reason")


class AuditTaskListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=20, ge=1, le=100)


class AuditTaskData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    task_no: str
    name: str
    description: str | None
    owner_id: UUID
    current_execution_id: UUID | None
    status: AuditTaskStatus
    row_version: PositiveIntegerString
    created_at: datetime
    updated_at: datetime


class AuditExecutionData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    audit_task_id: UUID
    version_no: int = Field(ge=1)
    baseline_date: date
    status: AuditExecutionStatus
    snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    job_id: UUID | None
    job: JobActionProjectionData | None = None
    finance_reviewer_id: UUID | None
    finance_reviewed_at: datetime | None
    audit_reviewer_id: UUID | None
    audit_reviewed_at: datetime | None
    retryable: bool
    failure_code: str | None
    cancel_reason: str | None
    return_reason: str | None
    row_version: PositiveIntegerString
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    outdated_at: datetime | None


class AuditRuleExecutionData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    rule_code: str
    status: RuleExecutionStatus
    actual_value: str | None
    expected_value: str | None
    applicability_reason: str | None
    included_item_ids: tuple[UUID, ...]
    excluded_item_ids: tuple[UUID, ...]


class AuditRiskExplanationCitationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: UUID
    policy_document_id: UUID
    chunk_id: UUID
    quote: str


class AuditRiskExplanationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    summary: str
    reasoning_summary: str
    business_impact: str | None
    recommended_action: str
    citations: tuple[AuditRiskExplanationCitationData, ...]
    evidence_sufficient: bool
    warnings: tuple[str, ...]


class AuditRiskData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    rule_code: str
    title: str
    original_level: RiskLevel
    effective_level: RiskLevel
    review_status: RiskReviewStatus
    actual_value: str | None
    expected_value: str | None
    review_reason: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    row_version: PositiveIntegerString
    ai_explanation_status: AiArtifactStatus = "disabled"
    ai_explanation: AuditRiskExplanationData | None = None

    @model_validator(mode="after")
    def validate_ai_explanation(self) -> AuditRiskData:
        if (self.ai_explanation_status == "succeeded") != (self.ai_explanation is not None):
            raise ValueError("AI explanation must match its status")
        return self


class AuditTaskDetailData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task: AuditTaskData
    execution: AuditExecutionData
    rules: tuple[AuditRuleExecutionData, ...]
    risks: tuple[AuditRiskData, ...]


class AuditTaskListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[AuditTaskData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None


class AuditTaskMutationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task: AuditTaskData
    execution: AuditExecutionData


class AuditExecutionMutationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    execution: AuditExecutionData


class AuditRetryData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    execution_id: UUID
    status: Literal["queued"] = "queued"
    preserved_results: Literal[True] = True
    execution_row_version: PositiveIntegerString
    job_id: UUID
    job_status: Literal["queued"] = "queued"
    attempt_no: int = Field(ge=0)
    scheduled_attempt_no: int = Field(ge=1)
    stage: Literal["evaluate"] = "evaluate"
    job_row_version: PositiveIntegerString

    @model_validator(mode="after")
    def validate_attempts(self) -> AuditRetryData:
        if self.scheduled_attempt_no != self.attempt_no + 1:
            raise ValueError("scheduled attempt must follow current attempt")
        return self


class AuditCancelData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    execution_id: UUID
    execution_status: Literal["cancelled"] = "cancelled"
    cancelled_at: datetime
    execution_row_version: PositiveIntegerString
    job_id: UUID | None
    job_status: Literal["cancel_requested", "cancelled", "succeeded"] | None
    job_row_version: PositiveIntegerString | None

    @model_validator(mode="after")
    def validate_job_projection(self) -> AuditCancelData:
        populated = (
            self.job_id is not None,
            self.job_status is not None,
            self.job_row_version is not None,
        )
        if len(set(populated)) != 1:
            raise ValueError("cancel Job projection is incomplete")
        return self


class AuditRiskMutationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    risk: AuditRiskData


class AuditWriteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


__all__ = [
    "AiArtifactStatus",
    "AuditCancelRequest",
    "AuditCancelData",
    "AuditExecutionCreateRequest",
    "AuditExecutionData",
    "AuditExecutionMutationData",
    "AuditFinanceReviewRequest",
    "AuditReviewDecisionRequest",
    "AuditRetryData",
    "AuditRetryRequest",
    "AuditRiskData",
    "AuditRiskExplanationCitationData",
    "AuditRiskExplanationData",
    "AuditRiskMutationData",
    "AuditRiskReviewRequest",
    "AuditRuleExecutionData",
    "AuditTaskCreateRequest",
    "AuditTaskData",
    "AuditTaskDetailData",
    "AuditTaskListData",
    "AuditTaskListQuery",
    "AuditTaskMutationData",
    "AuditWriteQuery",
]
