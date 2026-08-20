"""CR-005-R2 结构块纠错、解析激活与安全重评合同。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

CorrectionFieldName = Literal["text_content", "block_type", "reading_order", "bbox"]
CorrectableBlockType = Literal["title", "paragraph", "list", "table", "quote", "other"]
DocumentBlockType = Literal["title", "paragraph", "list", "table", "quote", "asset", "other"]
DocumentBusinessType = Literal["contract", "supplementary_agreement", "invoice", "policy"]


def _canonical_uuid(value: object, field: str) -> UUID:
    if type(value) is not str:
        raise ValueError(f"{field} must be a canonical UUID")
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError(f"{field} must be a canonical UUID")
    return parsed


def _reason(value: object) -> str:
    if type(value) is not str:
        raise ValueError("reason must be a string")
    normalized = value.strip()
    if not 1 <= len(normalized) <= 1000:
        raise ValueError("reason length is invalid")
    return normalized


class DocumentBlockCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    field_name: CorrectionFieldName
    after_value: object
    reason: str
    source_parse_version_id: UUID

    @field_validator("reason", mode="before")
    @classmethod
    def validate_reason(cls, value: object) -> str:
        return _reason(value)

    @field_validator("source_parse_version_id", mode="before")
    @classmethod
    def validate_source_parse_version_id(cls, value: object) -> UUID:
        return _canonical_uuid(value, "source_parse_version_id")

    @model_validator(mode="after")
    def validate_after_value(self) -> Self:
        value = self.after_value
        if self.field_name == "text_content":
            if type(value) is not str or not 1 <= len(value) <= 1_000_000 or "\x00" in value:
                raise ValueError("text_content correction is invalid")
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as error:
                raise ValueError("text_content correction is invalid") from error
        elif self.field_name == "block_type":
            if value not in {"title", "paragraph", "list", "table", "quote", "other"}:
                raise ValueError("block_type correction is invalid")
        elif self.field_name == "reading_order":
            if type(value) is not int or not 0 <= value <= 2_147_483_647:
                raise ValueError("reading_order correction is invalid")
        elif value is not None:
            if type(value) is not dict or set(value) != {"left", "top", "width", "height"}:
                raise ValueError("bbox correction is invalid")
            left, top, width, height = (
                value["left"],
                value["top"],
                value["width"],
                value["height"],
            )
            if (
                any(type(item) is not int for item in (left, top, width, height))
                or left < 0
                or top < 0
                or width <= 0
                or height <= 0
            ):
                raise ValueError("bbox correction is invalid")
        return self


class DocumentCorrectionAcceptedData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    correction_id: UUID
    result_parse_version_id: UUID
    job_id: UUID
    status: Literal["queued"] = "queued"


class DocumentParseActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reason: str

    @field_validator("reason", mode="before")
    @classmethod
    def validate_reason(cls, value: object) -> str:
        return _reason(value)


class DocumentParseActivationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    status: Literal["active"] = "active"
    superseded_version_id: UUID | None
    activated_at: datetime


class DocumentCorrectionBlockListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=50, ge=1, le=100)


class DocumentCorrectionBlockBboxData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    left: int = Field(ge=0)
    top: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class DocumentCorrectionBlockItemData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    block_id: UUID
    page_no: int = Field(ge=1)
    block_index: int = Field(ge=0)
    block_type: DocumentBlockType
    text_content: str = Field(max_length=20_000_000)
    reading_order: int = Field(ge=0)
    bbox: DocumentCorrectionBlockBboxData | None


class DocumentCorrectionBlockListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    file_id: UUID
    business_type: DocumentBusinessType
    parse_version_id: UUID
    items: tuple[DocumentCorrectionBlockItemData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_page_shape(self) -> Self:
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size")
        if self.next_cursor is not None and len(self.items) != self.page_size:
            raise ValueError("next_cursor requires a full page")
        identities = tuple(
            (item.page_no, item.block_index, item.block_id.int) for item in self.items
        )
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("items must be strictly ordered")
        return self


class SecurityRevalidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reason: str
    security_policy_version: Literal["asset-security-v1"]
    force_recheck: bool = False

    @field_validator("reason", mode="before")
    @classmethod
    def validate_reason(cls, value: object) -> str:
        normalized = _reason(value)
        if len(normalized) > 500:
            raise ValueError("security revalidation reason length is invalid")
        return normalized


class AcceptedJobData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    job_id: UUID
    resource_type: str = Field(min_length=1, max_length=80)
    resource_id: UUID
    status: Literal["queued"] = "queued"
    stage: None = None
    next_stage: str = Field(min_length=1, max_length=80)


__all__ = [
    "AcceptedJobData",
    "CorrectionFieldName",
    "DocumentBlockCorrectionRequest",
    "DocumentCorrectionBlockItemData",
    "DocumentCorrectionBlockListData",
    "DocumentCorrectionBlockListQuery",
    "DocumentCorrectionAcceptedData",
    "DocumentParseActivationData",
    "DocumentParseActivationRequest",
    "SecurityRevalidationRequest",
]
