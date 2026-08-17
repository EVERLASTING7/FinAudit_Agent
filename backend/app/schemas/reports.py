"""正式审核报告元数据 API 合同。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

AuditReportStatus = Literal["queued", "generating", "ready", "failed", "outdated", "archived"]
AiDraftStatus = Literal["disabled", "succeeded", "degraded"]


class ReportDraftData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    executive_summary: str
    scope_summary: str
    risk_summary: str
    recommendations: tuple[str, ...]
    warnings: tuple[str, ...]


class AuditReportData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    audit_task_id: UUID
    execution_id: UUID
    report_version: int
    status: AuditReportStatus
    payload_sha256: str
    generator_version: str
    pdf_sha256: str | None
    pdf_size_bytes: int | None
    pdf_mime_type: str
    xlsx_sha256: str | None
    xlsx_size_bytes: int | None
    xlsx_mime_type: str
    job_id: UUID | None
    failure_code: str | None
    row_version: str
    created_by: UUID
    created_at: datetime
    generated_at: datetime | None
    outdated_at: datetime | None
    archived_at: datetime | None
    is_outdated: bool
    ai_draft_status: AiDraftStatus = "disabled"
    ai_draft_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    ai_draft: ReportDraftData | None = None

    @model_validator(mode="after")
    def validate_ai_draft(self) -> AuditReportData:
        succeeded = self.ai_draft_status == "succeeded"
        if succeeded != (self.ai_draft is not None) or succeeded != (
            self.ai_draft_sha256 is not None
        ):
            raise ValueError("AI draft must match its status and hash")
        return self


class AuditReportListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    execution_id: UUID
    items: tuple[AuditReportData, ...]


__all__ = [
    "AiDraftStatus",
    "AuditReportData",
    "AuditReportListData",
    "AuditReportStatus",
    "ReportDraftData",
]
