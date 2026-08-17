"""Authenticated operation-log-read-v1 endpoint."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies.auth import require_permission
from app.api.dependencies.operation_logs import OperationLogQueryServiceDependency
from app.core.responses import utc_timestamp
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.operation_logs import OperationLogListData, OperationLogListQuery
from app.services.auth import AuthenticatedActor

router = APIRouter(prefix="/operation-logs", tags=["操作日志"])

OperationReadActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("operations.read")),
]
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少操作日志读取权限", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "操作日志查询服务未配置", "model": ErrorResponse},
}


@router.get(
    "",
    operation_id="list_operation_logs_v1",
    summary="读取操作日志",
    response_model=SuccessResponse[OperationLogListData],
    responses=_ERROR_RESPONSES,
)
def list_operation_logs(
    query: Annotated[OperationLogListQuery, Query()],
    request: Request,
    response: Response,
    actor: OperationReadActor,
    service: OperationLogQueryServiceDependency,
) -> SuccessResponse[OperationLogListData]:
    data = service.list_page(actor.organization_id, query.cursor, query.page_size)
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[OperationLogListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


__all__ = ["router"]
