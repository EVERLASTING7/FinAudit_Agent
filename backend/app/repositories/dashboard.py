"""权限裁剪工作台摘要的组织范围 SQL。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.audit import AuditTask, AuditTaskExecution
from app.models.documents import FileRecord
from app.models.reliability import AsyncJob


@dataclass(frozen=True, slots=True)
class DashboardFileView:
    file: FileRecord
    job: AsyncJob


class DashboardRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def audit_counts(self, organization_id: UUID) -> tuple[int, int]:
        open_count = self._session.scalar(
            select(func.count())
            .select_from(AuditTask)
            .where(
                AuditTask.organization_id == organization_id,
                AuditTask.deleted_at.is_(None),
                AuditTask.status == "open",
            )
        )
        pending_count = self._session.scalar(
            select(func.count())
            .select_from(AuditTask)
            .join(
                AuditTaskExecution,
                AuditTaskExecution.id == AuditTask.current_execution_id,
            )
            .where(
                AuditTask.organization_id == organization_id,
                AuditTask.deleted_at.is_(None),
                AuditTaskExecution.status.in_(("pending_finance_review", "pending_audit_review")),
            )
        )
        return int(open_count or 0), int(pending_count or 0)

    def recent_audit_tasks(
        self,
        organization_id: UUID,
        limit: int,
    ) -> tuple[AuditTask, ...]:
        return tuple(
            self._session.scalars(
                select(AuditTask)
                .where(
                    AuditTask.organization_id == organization_id,
                    AuditTask.deleted_at.is_(None),
                    AuditTask.status != "archived",
                )
                .order_by(AuditTask.updated_at.desc(), AuditTask.id.desc())
                .limit(limit)
            ).all()
        )

    @staticmethod
    def _preferred_file_job() -> object:
        return (
            select(AsyncJob.id)
            .where(
                AsyncJob.resource_type == "file",
                AsyncJob.resource_id == FileRecord.id,
                AsyncJob.job_type.in_(("file_scan", "file_process")),
            )
            .order_by(
                (AsyncJob.job_type == "file_process").desc(),
                AsyncJob.id.desc(),
            )
            .limit(1)
            .correlate(FileRecord)
            .scalar_subquery()
        )

    def file_counts(self, organization_id: UUID) -> tuple[int, int]:
        preferred_job = self._preferred_file_job()
        row = self._session.execute(
            select(
                func.count().filter(AsyncJob.status.in_(("queued", "running", "cancel_requested"))),
                func.count().filter(
                    or_(AsyncJob.status == "failed", FileRecord.status == "rejected")
                ),
            )
            .select_from(FileRecord)
            .join(
                AsyncJob,
                and_(
                    AsyncJob.resource_id == FileRecord.id,
                    AsyncJob.id == preferred_job,
                ),
            )
            .where(
                FileRecord.organization_id == organization_id,
                FileRecord.deleted_at.is_(None),
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    def recent_files(
        self,
        organization_id: UUID,
        limit: int,
    ) -> tuple[DashboardFileView, ...]:
        preferred_job = self._preferred_file_job()
        rows = self._session.execute(
            select(FileRecord, AsyncJob)
            .join(
                AsyncJob,
                and_(
                    AsyncJob.resource_id == FileRecord.id,
                    AsyncJob.id == preferred_job,
                ),
            )
            .where(
                FileRecord.organization_id == organization_id,
                FileRecord.deleted_at.is_(None),
            )
            .order_by(FileRecord.created_at.desc(), FileRecord.id.desc())
            .limit(limit)
        ).all()
        return tuple(
            DashboardFileView(file=cast(FileRecord, row[0]), job=cast(AsyncJob, row[1]))
            for row in rows
        )

    def failed_jobs(
        self,
        organization_id: UUID,
        limit: int,
    ) -> tuple[int, tuple[AsyncJob, ...]]:
        conditions = (
            AsyncJob.organization_id == organization_id,
            AsyncJob.status == "failed",
        )
        count = self._session.scalar(select(func.count()).select_from(AsyncJob).where(*conditions))
        rows = tuple(
            self._session.scalars(
                select(AsyncJob)
                .where(*conditions)
                .order_by(AsyncJob.created_at.desc(), AsyncJob.id.desc())
                .limit(limit)
            ).all()
        )
        return int(count or 0), rows


__all__ = ["DashboardFileView", "DashboardRepository"]
