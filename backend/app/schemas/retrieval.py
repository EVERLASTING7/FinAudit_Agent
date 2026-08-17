"""知识索引、检索评测与 RAG 的严格公共合同。"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PositiveIntegerString = Annotated[str, Field(pattern=r"^[1-9]\d*$")]
ScoreString = Annotated[str, Field(pattern=r"^(?:0(?:\.\d{1,6})?|1(?:\.0{1,6})?)$")]
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class IndexStatus(str, Enum):
    BUILDING = "building"
    READY = "ready"
    ACTIVE = "active"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class EvaluationTier(str, Enum):
    SMOKE = "smoke"
    MVP_UAT = "mvp_uat"
    FORMAL_RELEASE = "formal_release"


class EvaluationLabel(str, Enum):
    ANSWERABLE = "answerable"
    NO_ANSWER = "no_answer"
    UNAUTHORIZED = "unauthorized"


class IndexBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class VersionedTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if value != value.strip() or _CONTROL_CHARACTER_PATTERN.search(value) is not None:
            raise ValueError("reason is not normalized")
        return value


class IndexVersionData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    knowledge_base_id: UUID
    version_no: int = Field(ge=1)
    status: IndexStatus
    collection_name: str
    embedding_adapter_id: str
    embedding_model_id: str
    vector_dimension: int = Field(ge=1)
    distance: str
    member_count: int = Field(ge=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consistency: dict[str, object]
    failure_code: str | None
    row_version: PositiveIntegerString
    job_id: UUID | None
    job_status: str | None
    created_at: datetime
    activated_at: datetime | None


def _canonical_uuid(value: object) -> object:
    if type(value) is UUID:
        return value
    if type(value) is not str:
        raise ValueError("identifier must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("identifier must be a canonical UUID") from None
    if str(parsed) != value:
        raise ValueError("identifier must be a canonical UUID")
    return parsed


def _canonical_date(value: object) -> object:
    if type(value) is date:
        return value
    if type(value) is not str:
        raise ValueError("date must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("date must use YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise ValueError("date must use YYYY-MM-DD")
    return parsed


class EvaluationCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    label: EvaluationLabel
    query_text: str = Field(min_length=1, max_length=2000)
    baseline_date: date
    allowed_policy_ids: tuple[UUID, ...] = Field(max_length=1000)
    expected_chunk_ids: tuple[UUID, ...] = Field(max_length=1000)
    forbidden_chunk_ids: tuple[UUID, ...] = Field(max_length=1000)

    @field_validator("label", mode="before")
    @classmethod
    def parse_label(cls, value: object) -> object:
        if type(value) is EvaluationLabel:
            return value
        if type(value) is not str:
            raise ValueError("label is invalid")
        try:
            return EvaluationLabel(value)
        except ValueError:
            raise ValueError("label is invalid") from None

    @field_validator("baseline_date", mode="before")
    @classmethod
    def parse_date(cls, value: object) -> object:
        return _canonical_date(value)

    @field_validator(
        "allowed_policy_ids", "expected_chunk_ids", "forbidden_chunk_ids", mode="before"
    )
    @classmethod
    def parse_ids(cls, value: object) -> object:
        if type(value) not in {list, tuple}:
            raise ValueError("identifiers must be an array")
        values = cast(list[object] | tuple[object, ...], value)
        return tuple(_canonical_uuid(item) for item in values)

    @field_validator("query_text")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if value != value.strip() or _CONTROL_CHARACTER_PATTERN.search(value) is not None:
            raise ValueError("query is not normalized")
        return value

    @model_validator(mode="after")
    def validate_ground_truth(self) -> EvaluationCaseInput:
        id_groups = (
            self.allowed_policy_ids,
            self.expected_chunk_ids,
            self.forbidden_chunk_ids,
        )
        if any(len(values) != len(set(values)) for values in id_groups):
            raise ValueError("identifier arrays must not contain duplicates")
        if self.label is EvaluationLabel.ANSWERABLE:
            valid = bool(self.allowed_policy_ids and self.expected_chunk_ids) and not bool(
                self.forbidden_chunk_ids
            )
        elif self.label is EvaluationLabel.NO_ANSWER:
            valid = not self.expected_chunk_ids and not self.forbidden_chunk_ids
        else:
            valid = bool(self.forbidden_chunk_ids) and not self.expected_chunk_ids
        if not valid:
            raise ValueError("evaluation label and ground truth do not match")
        return self


class EvaluationDatasetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=200)
    tier: EvaluationTier
    answer_score_threshold: ScoreString
    cases: tuple[EvaluationCaseInput, ...] = Field(min_length=1, max_length=1000)

    @field_validator("tier", mode="before")
    @classmethod
    def parse_tier(cls, value: object) -> object:
        if type(value) is EvaluationTier:
            return value
        if type(value) is not str:
            raise ValueError("tier is invalid")
        try:
            return EvaluationTier(value)
        except ValueError:
            raise ValueError("tier is invalid") from None

    @field_validator("cases", mode="before")
    @classmethod
    def parse_cases(cls, value: object) -> object:
        if type(value) not in {list, tuple}:
            raise ValueError("cases must be an array")
        values = cast(list[object] | tuple[object, ...], value)
        return tuple(values)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if value != value.strip() or _CONTROL_CHARACTER_PATTERN.search(value) is not None:
            raise ValueError("name is not normalized")
        return value

    def threshold_decimal(self) -> Decimal:
        try:
            return Decimal(self.answer_score_threshold)
        except InvalidOperation:
            raise ValueError("invalid threshold") from None


class EvaluationDatasetData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    knowledge_base_id: UUID
    version_no: int = Field(ge=1)
    name: str
    tier: EvaluationTier
    status: str
    answer_score_threshold: ScoreString
    case_count: int = Field(ge=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    submitted_by: UUID | None
    submitted_at: datetime | None
    approved_by: UUID | None
    approved_at: datetime | None
    row_version: PositiveIntegerString


class EvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    dataset_id: UUID

    @field_validator("dataset_id", mode="before")
    @classmethod
    def parse_id(cls, value: object) -> object:
        return _canonical_uuid(value)


class EvaluationRunData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    knowledge_base_id: UUID
    index_version_id: UUID
    dataset_id: UUID
    tier: EvaluationTier
    status: str
    case_count: int = Field(ge=1)
    completed_case_count: int = Field(ge=0)
    metrics: dict[str, object]
    failure_code: str | None
    job_id: UUID
    job_status: str


class QaQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    question: str = Field(min_length=1, max_length=4000)
    baseline_date: date

    @field_validator("baseline_date", mode="before")
    @classmethod
    def parse_date(cls, value: object) -> object:
        return _canonical_date(value)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        if value != value.strip() or _CONTROL_CHARACTER_PATTERN.search(value) is not None:
            raise ValueError("question is not normalized")
        return value


class QaCitationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_document_id: UUID
    policy_version: str
    markdown_version_id: UUID
    chunk_id: UUID
    block_ids: tuple[UUID, ...] = Field(min_length=1)
    index_version_id: UUID
    page_range: str
    title_path: tuple[str, ...]
    quote: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class QaQueryData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    knowledge_base_id: UUID
    index_version_id: UUID | None
    baseline_date: date
    status: str
    answer: str | None
    reason_code: str | None
    citations: tuple[QaCitationData, ...]
    retrieved_count: int = Field(ge=0)
    created_at: datetime


class QaFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rating: str = Field(pattern=r"^(helpful|unhelpful)$")
    correction_text: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("correction_text")
    @classmethod
    def validate_correction(cls, value: str | None) -> str | None:
        if value is not None and (
            value != value.strip() or _CONTROL_CHARACTER_PATTERN.search(value) is not None
        ):
            raise ValueError("correction is not normalized")
        return value


class QaFeedbackData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    qa_query_id: UUID
    rating: str
    correction_text: str | None
    created_at: datetime


__all__ = [
    "EvaluationCaseInput",
    "EvaluationDatasetCreateRequest",
    "EvaluationDatasetData",
    "EvaluationLabel",
    "EvaluationRunData",
    "EvaluationRunRequest",
    "EvaluationTier",
    "IndexBuildRequest",
    "IndexStatus",
    "IndexVersionData",
    "QaCitationData",
    "QaFeedbackData",
    "QaFeedbackRequest",
    "QaQueryData",
    "QaQueryRequest",
    "VersionedTransitionRequest",
]
