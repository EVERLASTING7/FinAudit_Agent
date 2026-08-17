"""Break-glass application service dependency boundary."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.break_glass import BreakGlassService


def get_break_glass_service(request: Request) -> BreakGlassService:
    service = getattr(request.app.state, "break_glass_service", None)
    if not isinstance(service, BreakGlassService):
        raise AppError(
            status_code=503,
            code="BREAK_GLASS_NOT_CONFIGURED",
            message="临时授权服务尚未配置",
        )
    return service


BreakGlassServiceDependency = Annotated[
    BreakGlassService,
    Depends(get_break_glass_service),
]

__all__ = ["BreakGlassServiceDependency", "get_break_glass_service"]
