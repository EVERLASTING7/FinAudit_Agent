"""制度元数据、业务审批与结构分块的严格公共合同。"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

PositiveIntegerString = Annotated[str, Field(pattern=r"^[1-9]\d*$")]
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class PolicyStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    BUSINESS_APPROVED = "business_approved"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"
    ARCHIVED = "archived"


class PolicyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    knowledge_base_id: UUID
    source_file_id: UUID
    policy_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    version: str = Field(min_length=1, max_length=50)
    issuing_department: str | None = Field(default=None, min_length=1, max_length=200)
    effective_from: date
    effective_to: date | None = None
    scope: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("knowledge_base_id", "source_file_id", mode="before")
    @classmethod
    def parse_canonical_uuid(cls, value: object) -> object:
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

    @field_validator("effective_from", "effective_to", mode="before")
    @classmethod
    def parse_canonical_date(cls, value: object) -> object:
        if value is None or type(value) is date:
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

    @field_validator("policy_code", "name", "version", "issuing_department")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip() or _CONTROL_CHARACTER_PATTERN.search(value) is not None:
            raise ValueError("text is not normalized")
        return value

    @model_validator(mode="after")
    def validate_effective_range(self) -> PolicyCreateRequest:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be later than effective_from")
        return self


class PolicyTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if value != value.strip() or _CONTROL_CHARACTER_PATTERN.search(value) is not None:
            raise ValueError("reason is not normalized")
        return value


class PolicyData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    knowledge_base_id: UUID
    source_file_id: UUID
    policy_code: str
    name: str
    version: str
    issuing_department: str | None
    effective_from: date
    effective_to: date | None
    scope: dict[str, JsonValue]
    status: PolicyStatus
    submitted_by: UUID | None
    submitted_at: datetime | None
    business_approved_by: UUID | None
    business_approved_at: datetime | None
    technical_published_by: UUID | None
    technical_published_at: datetime | None
    row_version: PositiveIntegerString

    @model_validator(mode="after")
    def validate_lifecycle_projection(self) -> PolicyData:
        submitted = self.submitted_by is not None and self.submitted_at is not None
        approved = self.business_approved_by is not None and self.business_approved_at is not None
        published = (
            self.technical_published_by is not None and self.technical_published_at is not None
        )
        if (self.submitted_by is None) != (self.submitted_at is None):
            raise ValueError("submitted metadata is incomplete")
        if (self.business_approved_by is None) != (self.business_approved_at is None):
            raise ValueError("approval metadata is incomplete")
        if (self.technical_published_by is None) != (self.technical_published_at is None):
            raise ValueError("publication metadata is incomplete")
        if self.status is PolicyStatus.DRAFT and (submitted or approved or published):
            raise ValueError("draft policy contains decision metadata")
        if self.status is PolicyStatus.SUBMITTED and (not submitted or approved or published):
            raise ValueError("submitted policy lifecycle is invalid")
        if self.status is PolicyStatus.BUSINESS_APPROVED and (
            not submitted or not approved or published
        ):
            raise ValueError("approved policy lifecycle is invalid")
        if self.status in {PolicyStatus.PUBLISHED, PolicyStatus.SUPERSEDED} and (
            not submitted or not approved or not published
        ):
            raise ValueError("published policy lifecycle is invalid")
        return self


class PolicyChunkSetData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    markdown_version_id: UUID
    version_no: int = Field(ge=1)
    status: str
    profile_version: str
    profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_count: int = Field(ge=1)
    content_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class PolicyWriteData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy: PolicyData
    chunk_set: PolicyChunkSetData | None


class PolicyListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=20, ge=1, le=100)
    knowledge_base_id: UUID | None = None

    @field_validator("knowledge_base_id", mode="before")
    @classmethod
    def parse_knowledge_base_id(cls, value: object) -> object:
        if value is None or type(value) is UUID:
            return value
        if type(value) is not str:
            raise ValueError("knowledge_base_id must be a canonical UUID")
        try:
            parsed = UUID(value)
        except ValueError:
            raise ValueError("knowledge_base_id must be a canonical UUID") from None
        if str(parsed) != value:
            raise ValueError("knowledge_base_id must be a canonical UUID")
        return parsed


class PolicyListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[PolicyData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_page_shape(self) -> PolicyListData:
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size")
        if self.next_cursor is not None and len(self.items) != self.page_size:
            raise ValueError("next_cursor requires a full page")
        return self


class PolicyReadQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


__all__ = [
    "PolicyChunkSetData",
    "PolicyCreateRequest",
    "PolicyData",
    "PolicyListData",
    "PolicyListQuery",
    "PolicyReadQuery",
    "PolicyStatus",
    "PolicyTransitionRequest",
    "PolicyWriteData",
]
