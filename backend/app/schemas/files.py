"""文件 API 可复用的纯数据合同。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)


class IntendedBusinessType(str, Enum):
    """上传文件的 P0 固定业务分类。"""

    CONTRACT = "contract"
    SUPPLEMENTARY_AGREEMENT = "supplementary_agreement"
    INVOICE = "invoice"
    POLICY = "policy"


class FileUploadIntent(BaseModel):
    """上传意图的纯结构合同，不验证知识库运行时状态。"""

    model_config = ConfigDict(extra="forbid")

    intended_business_type: IntendedBusinessType
    target_knowledge_base_id: UUID | None = None
    auto_process_requested: StrictBool = True

    @model_validator(mode="after")
    def validate_knowledge_base_target(self) -> FileUploadIntent:
        is_policy = self.intended_business_type is IntendedBusinessType.POLICY
        has_target = self.target_knowledge_base_id is not None
        if is_policy != has_target:
            raise ValueError("target_knowledge_base_id is required only for policy uploads")
        return self


class FileStatus(str, Enum):
    """文件上传与存储生命周期的 P0 固定五态。"""

    UPLOADED = "uploaded"
    VALIDATING = "validating"
    STORED = "stored"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class SecurityScanStatus(str, Enum):
    """文件安全扫描的 P0 固定六态。"""

    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    SCAN_FAILED = "scan_failed"
    UNSUPPORTED = "unsupported"
    NOT_CONFIGURED = "not_configured"


class ParseVersionStatus(str, Enum):
    """文档解析版本的 P0 固定七态。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    ACTIVE = "active"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class MarkdownVersionStatus(str, Enum):
    """Markdown 版本的 P0 固定九态。"""

    QUEUED = "queued"
    CONVERTING = "converting"
    VALIDATING = "validating"
    REVIEW_REQUIRED = "review_required"
    READY = "ready"
    ACTIVE = "active"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class FileLifecycleStatuses(BaseModel):
    """分别返回文件、安全扫描、解析和 Markdown 的权威状态。"""

    model_config = ConfigDict(extra="forbid")

    file_status: FileStatus
    security_scan_status: SecurityScanStatus
    parse_status: ParseVersionStatus | None
    markdown_status: MarkdownVersionStatus | None


class FileUploadData(BaseModel):
    """file-upload-intake-v1 成功响应。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    file_id: UUID
    original_name: str = Field(min_length=1, max_length=500)
    status: FileStatus
    security_scan_status: SecurityScanStatus
    reused: bool
    intended_business_type: IntendedBusinessType
    target_knowledge_base_id: UUID | None
    auto_process_requested: bool
    job_id: UUID
    job_status: Literal[
        "queued",
        "running",
        "cancel_requested",
        "succeeded",
        "failed",
        "cancelled",
    ]
    job_scope: Literal["full", "scan_only"]
    next_stage: Literal["scan"]
    row_version: str = Field(pattern=r"^[1-9]\d*$")

    @model_validator(mode="after")
    def validate_target_and_scope(self) -> FileUploadData:
        if (self.intended_business_type is IntendedBusinessType.POLICY) != (
            self.target_knowledge_base_id is not None
        ):
            raise ValueError("target_knowledge_base_id matrix is invalid")
        if self.auto_process_requested != (self.job_scope == "full"):
            raise ValueError("job_scope does not match processing intent")
        return self


class FileListItemData(FileUploadData):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    size_bytes: str = Field(pattern=r"^[1-9]\d*$")
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class FileListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[FileListItemData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_page(self) -> FileListData:
        if len(self.items) > self.page_size:
            raise ValueError("items exceed page_size")
        if self.next_cursor is not None and len(self.items) != self.page_size:
            raise ValueError("next_cursor requires a full page")
        if len({item.file_id for item in self.items}) != len(self.items):
            raise ValueError("items contain duplicate files")
        return self


class FileBatchErrorData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    message: str = Field(min_length=1, max_length=200)


class FileBatchItemData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    index: int = Field(ge=0, le=999)
    original_name: str = Field(min_length=1, max_length=500)
    outcome: Literal["accepted", "rejected"]
    http_status: int = Field(ge=200, le=599)
    replayed: bool
    data: FileUploadData | None = None
    error: FileBatchErrorData | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> FileBatchItemData:
        if self.outcome == "accepted":
            if self.http_status != 202 or self.data is None or self.error is not None:
                raise ValueError("accepted batch item is invalid")
        elif self.data is not None or self.error is None or self.replayed:
            raise ValueError("rejected batch item is invalid")
        return self


class FileBatchUploadData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[FileBatchItemData, ...] = Field(min_length=1, max_length=100)
    accepted_count: int = Field(ge=0, le=100)
    rejected_count: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_counts_and_order(self) -> FileBatchUploadData:
        if tuple(item.index for item in self.items) != tuple(range(len(self.items))):
            raise ValueError("batch item indexes are not contiguous")
        accepted = sum(item.outcome == "accepted" for item in self.items)
        rejected = len(self.items) - accepted
        if self.accepted_count != accepted or self.rejected_count != rejected:
            raise ValueError("batch item counts are invalid")
        return self


class FileArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    row_version: str = Field(pattern=r"^[1-9]\d*$")
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if value != value.strip() or any(
            ord(character) < 32 or ord(character) == 127 for character in value
        ):
            raise ValueError("reason must not have surrounding whitespace")
        return value


class FileRetryRequest(FileArchiveRequest):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    job_id: UUID

    @field_validator("job_id", mode="before")
    @classmethod
    def parse_job_id(cls, value: object) -> object:
        if type(value) is UUID:
            return value
        if type(value) is not str:
            raise ValueError("job_id must be a canonical UUID")
        try:
            parsed = UUID(value)
        except ValueError:
            raise ValueError("job_id must be a canonical UUID") from None
        if str(parsed) != value:
            raise ValueError("job_id must be a canonical UUID")
        return parsed


class FileTextPreviewData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    file_id: UUID
    markdown_version_id: UUID
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    markdown_text: str
    char_count: int = Field(ge=0)
    truncated: bool

    @model_validator(mode="after")
    def validate_content(self) -> FileTextPreviewData:
        if len(self.markdown_text) > self.char_count:
            raise ValueError("preview text exceeds source character count")
        if self.truncated != (len(self.markdown_text) < self.char_count):
            raise ValueError("preview truncation flag is invalid")
        return self


class FileListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=20, ge=1, le=100)


class FileWriteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


__all__ = [
    "FileArchiveRequest",
    "FileBatchErrorData",
    "FileBatchItemData",
    "FileBatchUploadData",
    "FileLifecycleStatuses",
    "FileListData",
    "FileListItemData",
    "FileListQuery",
    "FileStatus",
    "FileRetryRequest",
    "FileTextPreviewData",
    "FileUploadData",
    "FileUploadIntent",
    "FileWriteQuery",
    "IntendedBusinessType",
    "MarkdownVersionStatus",
    "ParseVersionStatus",
    "SecurityScanStatus",
]
