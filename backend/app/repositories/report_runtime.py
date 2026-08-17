"""正式报告元数据的组织隔离读取。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditReport, AuditTaskExecution


class ReportRuntimeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def execution_exists(self, organization_id: UUID, execution_id: UUID) -> bool:
        return (
            self._session.scalar(
                select(AuditTaskExecution.id).where(
                    AuditTaskExecution.id == execution_id,
                    AuditTaskExecution.organization_id == organization_id,
                )
            )
            is not None
        )

    def list_reports(
        self,
        organization_id: UUID,
        execution_id: UUID,
    ) -> tuple[AuditReport, ...]:
        return tuple(
            self._session.scalars(
                select(AuditReport)
                .where(
                    AuditReport.organization_id == organization_id,
                    AuditReport.execution_id == execution_id,
                )
                .order_by(AuditReport.report_version.desc(), AuditReport.id)
            ).all()
        )

    def get_report(self, organization_id: UUID, report_id: UUID) -> AuditReport | None:
        return self._session.scalar(
            select(AuditReport).where(
                AuditReport.id == report_id,
                AuditReport.organization_id == organization_id,
            )
        )


__all__ = ["ReportRuntimeRepository"]
