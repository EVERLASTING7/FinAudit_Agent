"""OPS-005 service dependency boundary。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.ai_call_audit_query import AiCallAuditQueryService


def get_ai_call_audit_query_service(request: Request) -> AiCallAuditQueryService:
    service = getattr(request.app.state, "ai_call_audit_query_service", None)
    if not isinstance(service, AiCallAuditQueryService):
        raise AppError(
            status_code=503,
            code="AI_CALL_AUDIT_QUERY_NOT_CONFIGURED",
            message="AI 调用审计查询服务尚未配置",
        )
    return service


AiCallAuditQueryServiceDependency = Annotated[
    AiCallAuditQueryService,
    Depends(get_ai_call_audit_query_service),
]

__all__ = [
    "AiCallAuditQueryServiceDependency",
    "get_ai_call_audit_query_service",
]
