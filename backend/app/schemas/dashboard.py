"""权限裁剪工作台摘要的严格公共合同。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.audits import AuditTaskStatus
from app.schemas.files import FileStatus, IntendedBusinessType, SecurityScanStatus

PositiveIntegerString = Annotated[str, Field(pattern=r"^[1-9]\d*$")]


class DashboardQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_limit: int = Field(default=5, ge=1, le=20)


class DashboardAuditTaskItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    task_no: str
    name: str
    status: AuditTaskStatus
    current_execution_id: UUID | None
    updated_at: datetime


class DashboardAuditSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    open_count: int = Field(ge=0)
    pending_review_count: int = Field(ge=0)
    items: tuple[DashboardAuditTaskItem, ...]


class DashboardFileItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    file_id: UUID
    original_name: str
    status: FileStatus
    security_scan_status: SecurityScanStatus
    intended_business_type: IntendedBusinessType
    job_id: UUID
    job_status: Literal[
        "queued",
        "running",
        "cancel_requested",
        "succeeded",
        "failed",
        "cancelled",
    ]
    created_at: datetime


class DashboardFileSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    active_processing_count: int = Field(ge=0)
    failed_processing_count: int = Field(ge=0)
    items: tuple[DashboardFileItem, ...]


class DashboardFailedJobItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    job_type: str
    resource_type: str
    resource_id: UUID
    status: Literal["failed"]
    stage: str | None
    attempt_no: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    error_code: str
    next_retry_at: datetime | None
    created_at: datetime
    row_version: PositiveIntegerString


class DashboardFailedJobSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    failed_count: int = Field(ge=0)
    items: tuple[DashboardFailedJobItem, ...]


class DashboardData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    item_limit: int = Field(ge=1, le=20)
    audit_tasks: DashboardAuditSection | None
    files: DashboardFileSection | None
    failed_jobs: DashboardFailedJobSection | None

    @model_validator(mode="after")
    def validate_section_bounds(self) -> DashboardData:
        sections = (self.audit_tasks, self.files, self.failed_jobs)
        if any(
            section is not None and len(section.items) > self.item_limit for section in sections
        ):
            raise ValueError("dashboard section exceeds item_limit")
        return self


__all__ = [
    "DashboardAuditSection",
    "DashboardAuditTaskItem",
    "DashboardData",
    "DashboardFailedJobItem",
    "DashboardFailedJobSection",
    "DashboardFileItem",
    "DashboardFileSection",
    "DashboardQuery",
]
