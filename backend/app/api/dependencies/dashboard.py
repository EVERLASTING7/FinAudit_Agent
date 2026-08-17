"""工作台摘要服务依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.dashboard import DashboardService


def get_dashboard_service(request: Request) -> DashboardService:
    service = getattr(request.app.state, "dashboard_service", None)
    if not isinstance(service, DashboardService):
        raise AppError(
            status_code=503,
            code="DASHBOARD_NOT_CONFIGURED",
            message="工作台摘要服务尚未配置",
        )
    return service


DashboardServiceDependency = Annotated[DashboardService, Depends(get_dashboard_service)]

__all__ = ["DashboardServiceDependency", "get_dashboard_service"]
