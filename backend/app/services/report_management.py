"""正式报告元数据、授权预览与导出用例。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, cast
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.minio_report_storage import (
    ReportObjectLocator,
    ReportStorageError,
)
from app.ai.policy import canonicalize_jcs
from app.ai.report_draft import ReportDraftOutput
from app.core.errors import AppError
from app.models.audit import AuditReport
from app.reports.pdf_writer import MAX_PDF_BYTES
from app.reports.xlsx_writer import MAX_XLSX_BYTES
from app.repositories.audit_runtime import AuditRuntimeRepository, LockedAuditCluster
from app.repositories.operation_log import OperationLogRepository
from app.repositories.report_runtime import ReportRuntimeRepository
from app.schemas.reports import (
    AiDraftStatus,
    AuditReportData,
    AuditReportListData,
    AuditReportStatus,
    ReportDraftData,
)
from app.services.auth import AuthenticatedActor

_PDF_MIME_TYPE = "application/pdf"
_XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_READABLE_STATUSES = frozenset({"ready", "outdated", "archived"})


class ReportArtifactReader(Protocol):
    def read_verified(
        self,
        locator: ReportObjectLocator,
        *,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ReportArtifactResult:
    content: bytes
    filename: str
    mime_type: str
    sha256: str
    status: str
    is_outdated: bool


def _not_found() -> AppError:
    return AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )


def _project(report: AuditReport) -> AuditReportData:
    draft = None
    if report.ai_draft_status == "succeeded":
        if report.ai_draft_json is None or report.ai_draft_sha256 is None:
            raise RuntimeError("succeeded AI report draft is missing")
        parsed = ReportDraftOutput.model_validate_json(canonicalize_jcs(report.ai_draft_json))
        draft = ReportDraftData(
            executive_summary=parsed.executive_summary,
            scope_summary=parsed.scope_summary,
            risk_summary=parsed.risk_summary,
            recommendations=parsed.recommendations,
            warnings=parsed.warnings,
        )
    return AuditReportData(
        id=report.id,
        audit_task_id=report.audit_task_id,
        execution_id=report.execution_id,
        report_version=report.report_version,
        status=cast(AuditReportStatus, report.status),
        payload_sha256=report.payload_sha256,
        generator_version=report.generator_version,
        pdf_sha256=report.pdf_sha256,
        pdf_size_bytes=report.pdf_size_bytes,
        pdf_mime_type=report.pdf_mime_type,
        xlsx_sha256=report.xlsx_sha256,
        xlsx_size_bytes=report.xlsx_size_bytes,
        xlsx_mime_type=report.xlsx_mime_type,
        job_id=report.job_id,
        failure_code=report.failure_code,
        row_version=str(report.row_version),
        created_by=report.created_by,
        created_at=report.created_at,
        generated_at=report.generated_at,
        outdated_at=report.outdated_at,
        archived_at=report.archived_at,
        is_outdated=report.outdated_at is not None,
        ai_draft_status=cast(AiDraftStatus, report.ai_draft_status),
        ai_draft_sha256=report.ai_draft_sha256,
        ai_draft=draft,
    )


def _cluster_report(cluster: LockedAuditCluster, report_id: UUID) -> AuditReport | None:
    return next((report for report in cluster.reports if report.id == report_id), None)


class ReportManagementService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        storage: ReportArtifactReader,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage

    def list_reports(
        self,
        organization_id: UUID,
        execution_id: UUID,
    ) -> AuditReportListData:
        with self._session_factory() as session:
            repository = ReportRuntimeRepository(session)
            if not repository.execution_exists(organization_id, execution_id):
                raise _not_found()
            reports = repository.list_reports(organization_id, execution_id)
        return AuditReportListData(
            execution_id=execution_id,
            items=tuple(_project(report) for report in reports),
        )

    def get_report(self, organization_id: UUID, report_id: UUID) -> AuditReportData:
        with self._session_factory() as session:
            report = ReportRuntimeRepository(session).get_report(organization_id, report_id)
            if report is None:
                raise _not_found()
            return _project(report)

    def preview_pdf(
        self,
        actor: AuthenticatedActor,
        report_id: UUID,
        trace_id: UUID,
    ) -> ReportArtifactResult:
        return self._read_artifact(actor, report_id, trace_id, artifact_format="pdf")

    def download_xlsx(
        self,
        actor: AuthenticatedActor,
        report_id: UUID,
        trace_id: UUID,
    ) -> ReportArtifactResult:
        return self._read_artifact(actor, report_id, trace_id, artifact_format="xlsx")

    def _read_artifact(
        self,
        actor: AuthenticatedActor,
        report_id: UUID,
        trace_id: UUID,
        *,
        artifact_format: Literal["pdf", "xlsx"],
    ) -> ReportArtifactResult:
        with self._session_factory() as session:
            report = ReportRuntimeRepository(session).get_report(
                actor.organization_id,
                report_id,
            )
            if report is None:
                raise _not_found()
            if report.status not in _READABLE_STATUSES:
                raise AppError(
                    status_code=409,
                    code="REPORT_NOT_READY",
                    message="报告制品尚未就绪",
                )
            if artifact_format == "pdf":
                locator, sha256, size, mime_type, max_bytes = (
                    ReportObjectLocator(report.pdf_bucket or "", report.pdf_object_key or ""),
                    report.pdf_sha256,
                    report.pdf_size_bytes,
                    report.pdf_mime_type,
                    MAX_PDF_BYTES,
                )
            else:
                locator, sha256, size, mime_type, max_bytes = (
                    ReportObjectLocator(report.xlsx_bucket or "", report.xlsx_object_key or ""),
                    report.xlsx_sha256,
                    report.xlsx_size_bytes,
                    report.xlsx_mime_type,
                    MAX_XLSX_BYTES,
                )
            if (
                sha256 is None
                or size is None
                or size <= 0
                or mime_type != (_PDF_MIME_TYPE if artifact_format == "pdf" else _XLSX_MIME_TYPE)
            ):
                raise AppError(
                    status_code=503,
                    code="REPORT_ARTIFACT_UNAVAILABLE",
                    message="报告制品暂不可用",
                )
            execution_id = report.execution_id
            report_version = report.report_version
        try:
            content = self._storage.read_verified(
                locator,
                expected_size=size,
                expected_sha256=sha256,
                max_bytes=max_bytes,
            )
        except ReportStorageError:
            raise AppError(
                status_code=503,
                code="REPORT_ARTIFACT_UNAVAILABLE",
                message="报告制品暂不可用",
            ) from None

        with self._session_factory.begin() as session:
            cluster = AuditRuntimeRepository(session).lock_cluster(
                actor.organization_id,
                execution_id,
            )
            current = None if cluster is None else _cluster_report(cluster, report_id)
            if (
                current is None
                or current.status not in _READABLE_STATUSES
                or (
                    artifact_format == "pdf"
                    and (
                        current.pdf_bucket != locator.bucket_name
                        or current.pdf_object_key != locator.object_key
                        or current.pdf_sha256 != sha256
                        or current.pdf_size_bytes != size
                    )
                )
                or (
                    artifact_format == "xlsx"
                    and (
                        current.xlsx_bucket != locator.bucket_name
                        or current.xlsx_object_key != locator.object_key
                        or current.xlsx_sha256 != sha256
                        or current.xlsx_size_bytes != size
                    )
                )
            ):
                raise AppError(
                    status_code=409,
                    code="REPORT_STATE_CHANGED",
                    message="报告状态已变化，请重试",
                )
            is_outdated = current.outdated_at is not None
            action_code = (
                "reports.pdf_previewed" if artifact_format == "pdf" else "reports.xlsx_downloaded"
            )
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code=action_code,
                outcome="succeeded",
                resource_type="audit_report",
                resource_id=current.id,
                trace_id=trace_id,
                change_summary={
                    "format": artifact_format,
                    "is_outdated": is_outdated,
                    "status": current.status,
                },
            )
            status = current.status
        return ReportArtifactResult(
            content=content,
            filename=(
                f"audit-report-{report_id}-v{report_version}.pdf"
                if artifact_format == "pdf"
                else f"audit-report-{report_id}-v{report_version}-risks.xlsx"
            ),
            mime_type=mime_type,
            sha256=sha256,
            status=status,
            is_outdated=is_outdated,
        )


__all__ = [
    "ReportArtifactReader",
    "ReportArtifactResult",
    "ReportManagementService",
]
