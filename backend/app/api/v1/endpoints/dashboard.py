"""登录后权限裁剪工作台摘要 API。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response

from app.api.dependencies.auth import CurrentActorDependency
from app.api.dependencies.dashboard import DashboardServiceDependency
from app.core.responses import utc_timestamp
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.dashboard import DashboardData, DashboardQuery

router = APIRouter(prefix="/dashboard", tags=["工作台"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "工作台服务尚未配置", "model": ErrorResponse},
}


@router.get(
    "",
    operation_id="get_dashboard_summary_v1",
    summary="读取权限裁剪工作台摘要",
    response_model=SuccessResponse[DashboardData],
    responses=_ERRORS,
)
def get_dashboard_summary(
    query: Annotated[DashboardQuery, Query()],
    request: Request,
    response: Response,
    actor: CurrentActorDependency,
    service: DashboardServiceDependency,
) -> SuccessResponse[DashboardData]:
    data = service.read(actor, query.item_limit)
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[DashboardData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


__all__ = ["router"]
