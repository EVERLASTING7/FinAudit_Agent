"""制度业务运行时服务依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.policy_management import PolicyManagementService


def get_policy_management_service(request: Request) -> PolicyManagementService:
    service = getattr(request.app.state, "policy_management_service", None)
    if not isinstance(service, PolicyManagementService):
        raise AppError(
            status_code=503,
            code="KNOWLEDGE_WRITE_NOT_CONFIGURED",
            message="制度运行时尚未配置",
        )
    return service


PolicyManagementServiceDependency = Annotated[
    PolicyManagementService,
    Depends(get_policy_management_service),
]

__all__ = ["PolicyManagementServiceDependency", "get_policy_management_service"]
