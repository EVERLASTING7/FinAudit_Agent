"""正式报告服务依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.report_management import ReportManagementService


def get_report_management_service(request: Request) -> ReportManagementService:
    service = getattr(request.app.state, "report_management_service", None)
    if not isinstance(service, ReportManagementService):
        raise AppError(
            status_code=503,
            code="REPORT_RUNTIME_NOT_CONFIGURED",
            message="报告运行服务尚未配置",
        )
    return service


ReportManagementServiceDependency = Annotated[
    ReportManagementService,
    Depends(get_report_management_service),
]

__all__ = ["ReportManagementServiceDependency", "get_report_management_service"]
