from fastapi import APIRouter, Response

from app.api.dependencies.metrics import MetricsRegistryDependency, MetricsTokenDependency
from app.api.dependencies.settings import SettingsDependency

router = APIRouter(tags=["运维"])


@router.get(
    "/metrics",
    response_class=Response,
    summary="读取 Backend 内部 Prometheus 指标",
    responses={
        200: {
            "description": "低基数进程与 HTTP 指标",
            "content": {"text/plain": {}},
        },
        401: {"description": "缺少或拒绝独立内部指标凭据"},
    },
)
def metrics(
    _authorized: MetricsTokenDependency,
    registry: MetricsRegistryDependency,
    settings: SettingsDependency,
) -> Response:
    payload = registry.render_prometheus(service="backend", version=settings.app_version)
    return Response(
        content=payload,
        media_type="text/plain; version=0.0.4; charset=utf-8",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


__all__ = ["router"]
