"""Operation log query dependency boundary."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.operation_log_query import OperationLogQueryService


def get_operation_log_query_service(request: Request) -> OperationLogQueryService:
    service = getattr(request.app.state, "operation_log_query_service", None)
    if not isinstance(service, OperationLogQueryService):
        raise AppError(
            status_code=503,
            code="OPERATION_LOG_QUERY_NOT_CONFIGURED",
            message="操作日志查询服务尚未配置",
        )
    return service


OperationLogQueryServiceDependency = Annotated[
    OperationLogQueryService,
    Depends(get_operation_log_query_service),
]

__all__ = ["OperationLogQueryServiceDependency", "get_operation_log_query_service"]
