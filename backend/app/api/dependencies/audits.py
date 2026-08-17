"""审核任务与人工复核服务依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.audit_management import AuditManagementService


def get_audit_management_service(request: Request) -> AuditManagementService:
    service = getattr(request.app.state, "audit_management_service", None)
    if not isinstance(service, AuditManagementService):
        raise AppError(
            status_code=503,
            code="AUDIT_RUNTIME_NOT_CONFIGURED",
            message="审核运行服务尚未配置",
        )
    return service


AuditManagementServiceDependency = Annotated[
    AuditManagementService,
    Depends(get_audit_management_service),
]

__all__ = ["AuditManagementServiceDependency", "get_audit_management_service"]
