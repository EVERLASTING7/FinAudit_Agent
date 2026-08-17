"""User directory query dependency boundary."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.user_management import UserManagementService
from app.services.user_query import UserQueryService


def get_user_query_service(request: Request) -> UserQueryService:
    service = getattr(request.app.state, "user_query_service", None)
    if not isinstance(service, UserQueryService):
        raise AppError(
            status_code=503,
            code="USER_DIRECTORY_NOT_CONFIGURED",
            message="用户目录查询服务尚未配置",
        )
    return service


UserQueryServiceDependency = Annotated[
    UserQueryService,
    Depends(get_user_query_service),
]


def get_user_management_service(request: Request) -> UserManagementService:
    service = getattr(request.app.state, "user_management_service", None)
    if not isinstance(service, UserManagementService):
        raise AppError(
            status_code=503,
            code="USER_MANAGEMENT_NOT_CONFIGURED",
            message="用户管理服务尚未配置",
        )
    return service


UserManagementServiceDependency = Annotated[
    UserManagementService,
    Depends(get_user_management_service),
]

__all__ = [
    "UserManagementServiceDependency",
    "UserQueryServiceDependency",
    "get_user_management_service",
    "get_user_query_service",
]
