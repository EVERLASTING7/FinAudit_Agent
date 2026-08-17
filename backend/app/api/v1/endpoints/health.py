from fastapi import APIRouter, Request, Response, status

from app.api.dependencies.health import DependencyHealthServiceDependency
from app.api.dependencies.settings import SettingsDependency
from app.core.responses import utc_timestamp
from app.schemas.common import SuccessResponse
from app.schemas.health import DependencyHealthData, HealthData

router = APIRouter(tags=["运维"])


@router.get(
    "/health",
    response_model=SuccessResponse[HealthData],
    summary="检查 Backend 进程存活",
    responses={
        200: {
            "description": "Backend 进程正常",
            "content": {
                "application/json": {
                    "example": {
                        "code": "OK",
                        "message": "success",
                        "data": {
                            "status": "ok",
                            "service": "backend",
                            "version": "0.1.0",
                            "timestamp": "2026-01-01T00:00:00Z",
                        },
                        "trace_id": "00000000-0000-4000-8000-000000000001",
                        "timestamp": "2026-01-01T00:00:00Z",
                    }
                }
            },
        }
    },
)
async def health(request: Request, settings: SettingsDependency) -> SuccessResponse[HealthData]:
    """仅报告 Backend 进程存活，不探测或披露外部依赖。"""
    checked_at = utc_timestamp()
    return SuccessResponse[HealthData](
        data=HealthData(
            status="ok",
            service="backend",
            version=settings.app_version,
            timestamp=checked_at,
        ),
        trace_id=request.state.trace_id,
        timestamp=checked_at,
    )


@router.get(
    "/health/dependencies",
    response_model=SuccessResponse[DependencyHealthData],
    summary="检查 Backend 业务依赖就绪状态",
    responses={
        200: {"description": "所有当前 Profile 必需依赖均可用"},
        503: {
            "description": "至少一个当前 Profile 必需依赖不可用",
            "model": SuccessResponse[DependencyHealthData],
        },
    },
)
def dependency_health(
    request: Request,
    response: Response,
    service: DependencyHealthServiceDependency,
) -> SuccessResponse[DependencyHealthData]:
    """只返回固定依赖名与状态，不披露地址、异常、凭据或耗时。"""
    snapshot = service.check()
    checked_at = utc_timestamp()
    if snapshot.status == "unavailable":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return SuccessResponse[DependencyHealthData](
        code="OK" if snapshot.status == "ok" else "DEPENDENCY_UNAVAILABLE",
        message="success" if snapshot.status == "ok" else "required dependency unavailable",
        data=DependencyHealthData(
            status=snapshot.status,
            dependencies=snapshot.dependencies,
            timestamp=checked_at,
        ),
        trace_id=request.state.trace_id,
        timestamp=checked_at,
    )
