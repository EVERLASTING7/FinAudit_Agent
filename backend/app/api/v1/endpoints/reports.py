"""正式审核报告元数据、PDF 预览和 XLSX 下载 API。"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response

from app.api.dependencies.auth import require_permission
from app.api.dependencies.reports import ReportManagementServiceDependency
from app.core.errors import AppError
from app.core.responses import utc_timestamp
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.reports import AuditReportData, AuditReportListData
from app.services.auth import AuthenticatedActor
from app.services.report_management import ReportArtifactResult

router = APIRouter(tags=["审核报告"])

_PDF_MIME_TYPE = "application/pdf"
_XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

CanonicalId = Annotated[
    str,
    Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
ReportReadActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("reports.read")),
]
ReportExportActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("reports.export")),
]

_READ_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少报告读取权限", "model": ErrorResponse},
    404: {"description": "报告不存在或不可见", "model": ErrorResponse},
    409: {"description": "报告尚未就绪或状态已变化", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "报告服务或制品暂不可用", "model": ErrorResponse},
}


def _uuid(value: str) -> UUID:
    parsed = UUID(value)
    if str(parsed) != value:
        raise AppError(status_code=422, code="VALIDATION_ERROR", message="请求参数不符合约束")
    return parsed


@router.get(
    "/audit-executions/{execution_id}/reports",
    operation_id="list_audit_reports_v1",
    response_model=SuccessResponse[AuditReportListData],
    responses=_READ_ERRORS,
)
def list_audit_reports(
    execution_id: CanonicalId,
    request: Request,
    response: Response,
    actor: ReportReadActor,
    service: ReportManagementServiceDependency,
) -> SuccessResponse[AuditReportListData]:
    data = service.list_reports(actor.organization_id, _uuid(execution_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[AuditReportListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/audit-reports/{report_id}",
    operation_id="get_audit_report_v1",
    response_model=SuccessResponse[AuditReportData],
    responses=_READ_ERRORS,
)
def get_audit_report(
    report_id: CanonicalId,
    request: Request,
    response: Response,
    actor: ReportReadActor,
    service: ReportManagementServiceDependency,
) -> SuccessResponse[AuditReportData]:
    data = service.get_report(actor.organization_id, _uuid(report_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[AuditReportData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


def _artifact_response(result: ReportArtifactResult, *, inline: bool) -> Response:
    disposition = "inline" if inline else "attachment"
    return Response(
        content=result.content,
        media_type=result.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'{disposition}; filename="{result.filename}"',
            "ETag": f'"{result.sha256}"',
            "X-Content-Type-Options": "nosniff",
            "X-Report-Outdated": str(result.is_outdated).lower(),
            "X-Report-Status": result.status,
        },
    )


@router.get(
    "/audit-reports/{report_id}/preview",
    operation_id="preview_audit_report_pdf_v1",
    response_class=Response,
    responses={**_READ_ERRORS, 200: {"content": {_PDF_MIME_TYPE: {}}}},
)
def preview_audit_report_pdf(
    report_id: CanonicalId,
    request: Request,
    actor: ReportReadActor,
    service: ReportManagementServiceDependency,
) -> Response:
    return _artifact_response(
        service.preview_pdf(actor, _uuid(report_id), UUID(request.state.trace_id)),
        inline=True,
    )


@router.get(
    "/audit-reports/{report_id}/download",
    operation_id="download_audit_report_xlsx_v1",
    response_class=Response,
    responses={**_READ_ERRORS, 200: {"content": {_XLSX_MIME_TYPE: {}}}},
)
def download_audit_report_xlsx(
    report_id: CanonicalId,
    request: Request,
    actor: ReportExportActor,
    service: ReportManagementServiceDependency,
) -> Response:
    return _artifact_response(
        service.download_xlsx(actor, _uuid(report_id), UUID(request.state.trace_id)),
        inline=False,
    )


__all__ = ["router"]
