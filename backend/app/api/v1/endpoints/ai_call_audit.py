"""OPS-005 authenticated AI call audit summary endpoint。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies.ai_call_audit import AiCallAuditQueryServiceDependency
from app.api.dependencies.auth import require_permission
from app.core.responses import utc_timestamp
from app.schemas.ai_call_audit import AiCallAuditQuery, AiCallAuditSummaryData
from app.schemas.common import ErrorResponse, SuccessResponse
from app.services.auth import AuthenticatedActor

router = APIRouter(prefix="/ai-call-logs", tags=["AI 调用审计"])

AiAuditReadActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("operations.read")),
]
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少 AI 调用审计读取权限", "model": ErrorResponse},
    404: {"description": "调用摘要不存在或无权访问", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "AI 调用审计查询服务未配置", "model": ErrorResponse},
}


@router.get(
    "",
    operation_id="get_ai_call_audit_summary_v1",
    summary="查询 AI 调用摘要",
    response_model=SuccessResponse[AiCallAuditSummaryData],
    responses=_ERROR_RESPONSES,
)
def get_ai_call_audit_summary(
    query: Annotated[AiCallAuditQuery, Query()],
    request: Request,
    response: Response,
    actor: AiAuditReadActor,
    service: AiCallAuditQueryServiceDependency,
) -> SuccessResponse[AiCallAuditSummaryData]:
    data = service.get_summary(actor.organization_id, query.business_operation_id)
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[AiCallAuditSummaryData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


__all__ = ["router"]
