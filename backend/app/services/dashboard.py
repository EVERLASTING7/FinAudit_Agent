"""权限裁剪工作台摘要读取用例。"""

from __future__ import annotations

from typing import Literal, cast

from sqlalchemy.orm import Session, sessionmaker

from app.repositories.dashboard import DashboardFileView, DashboardRepository
from app.schemas.audits import AuditTaskStatus
from app.schemas.dashboard import (
    DashboardAuditSection,
    DashboardAuditTaskItem,
    DashboardData,
    DashboardFailedJobItem,
    DashboardFailedJobSection,
    DashboardFileItem,
    DashboardFileSection,
)
from app.schemas.files import FileStatus, IntendedBusinessType, SecurityScanStatus
from app.services.auth import AuthenticatedActor

FileJobStatus = Literal[
    "queued",
    "running",
    "cancel_requested",
    "succeeded",
    "failed",
    "cancelled",
]


def _project_file(view: DashboardFileView) -> DashboardFileItem:
    return DashboardFileItem(
        file_id=view.file.id,
        original_name=view.file.original_name,
        status=FileStatus(view.file.status),
        security_scan_status=SecurityScanStatus(view.file.security_scan_status),
        intended_business_type=IntendedBusinessType(view.file.intended_business_type),
        job_id=view.job.id,
        job_status=cast(FileJobStatus, view.job.status),
        created_at=view.file.created_at,
    )


class DashboardService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def read(self, actor: AuthenticatedActor, item_limit: int) -> DashboardData:
        audit_section: DashboardAuditSection | None = None
        file_section: DashboardFileSection | None = None
        failed_job_section: DashboardFailedJobSection | None = None
        with self._session_factory() as session:
            repository = DashboardRepository(session)
            if "audits.read" in actor.permissions:
                open_count, pending_count = repository.audit_counts(actor.organization_id)
                audit_section = DashboardAuditSection(
                    open_count=open_count,
                    pending_review_count=pending_count,
                    items=tuple(
                        DashboardAuditTaskItem(
                            id=row.id,
                            task_no=row.task_no,
                            name=row.name,
                            status=cast(AuditTaskStatus, row.status),
                            current_execution_id=row.current_execution_id,
                            updated_at=row.updated_at,
                        )
                        for row in repository.recent_audit_tasks(
                            actor.organization_id,
                            item_limit,
                        )
                    ),
                )
            if "files.read" in actor.permissions:
                active_count, failed_count = repository.file_counts(actor.organization_id)
                file_section = DashboardFileSection(
                    active_processing_count=active_count,
                    failed_processing_count=failed_count,
                    items=tuple(
                        _project_file(row)
                        for row in repository.recent_files(
                            actor.organization_id,
                            item_limit,
                        )
                    ),
                )
            if "jobs.recover" in actor.permissions:
                failed_count, failed_jobs = repository.failed_jobs(
                    actor.organization_id,
                    item_limit,
                )
                failed_items: list[DashboardFailedJobItem] = []
                for job in failed_jobs:
                    if job.error_code is None:
                        raise RuntimeError("failed dashboard job lacks error_code")
                    failed_items.append(
                        DashboardFailedJobItem(
                            id=job.id,
                            job_type=job.job_type,
                            resource_type=job.resource_type,
                            resource_id=job.resource_id,
                            status="failed",
                            stage=job.stage,
                            attempt_no=job.attempt_no,
                            max_attempts=job.max_attempts,
                            error_code=job.error_code,
                            next_retry_at=job.next_retry_at,
                            created_at=job.created_at,
                            row_version=str(job.row_version),
                        )
                    )
                failed_job_section = DashboardFailedJobSection(
                    failed_count=failed_count,
                    items=tuple(failed_items),
                )
        return DashboardData(
            item_limit=item_limit,
            audit_tasks=audit_section,
            files=file_section,
            failed_jobs=failed_job_section,
        )


__all__ = ["DashboardService"]
