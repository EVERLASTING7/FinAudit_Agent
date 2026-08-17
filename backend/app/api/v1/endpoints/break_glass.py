"""Authenticated break-glass-write-v1 endpoints."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response

from app.api.dependencies.auth import require_permission
from app.api.dependencies.break_glass import BreakGlassServiceDependency
from app.core.responses import utc_timestamp
from app.schemas.break_glass import (
    BreakGlassCreateRequest,
    BreakGlassData,
    BreakGlassDecisionRequest,
    BreakGlassRevokeRequest,
    BreakGlassWriteQuery,
)
from app.schemas.common import ErrorResponse, SuccessResponse
from app.services.auth import AuthenticatedActor
from app.services.break_glass import BreakGlassMutationResult

router = APIRouter(prefix="/break-glass-requests", tags=["临时授权"])

CanonicalRequestId = Annotated[
    str,
    Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._~-]+$",
    ),
]
RequestActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("temporary_roles.request")),
]
DecisionActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("temporary_roles.decide")),
]
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少临时授权权限", "model": ErrorResponse},
    404: {"description": "目标或申请不存在", "model": ErrorResponse},
    409: {"description": "幂等、状态、并发或资格冲突", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "临时授权服务未配置", "model": ErrorResponse},
}


def _response(
    request: Request,
    response: Response,
    result: BreakGlassMutationResult,
) -> SuccessResponse[BreakGlassData]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[BreakGlassData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "",
    status_code=201,
    operation_id="create_break_glass_request_v1",
    summary="创建临时授权申请",
    response_model=SuccessResponse[BreakGlassData],
    responses=_ERROR_RESPONSES,
)
def create_break_glass_request(
    payload: BreakGlassCreateRequest,
    query: Annotated[BreakGlassWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: RequestActor,
    service: BreakGlassServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[BreakGlassData]:
    del query
    result = service.create(
        actor,
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    if result.status_code != 201:
        raise RuntimeError("break-glass create service returned an invalid status")
    return _response(request, response, result)


@router.post(
    "/{request_id}/decision",
    operation_id="decide_break_glass_request_v1",
    summary="决定临时授权申请",
    response_model=SuccessResponse[BreakGlassData],
    responses=_ERROR_RESPONSES,
)
def decide_break_glass_request(
    request_id: CanonicalRequestId,
    payload: BreakGlassDecisionRequest,
    query: Annotated[BreakGlassWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: DecisionActor,
    service: BreakGlassServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[BreakGlassData]:
    del query
    result = service.decide(
        actor,
        UUID(request_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    if result.status_code != 200:
        raise RuntimeError("break-glass decision service returned an invalid status")
    return _response(request, response, result)


@router.post(
    "/{request_id}/revoke",
    operation_id="revoke_break_glass_request_v1",
    summary="撤销临时授权",
    response_model=SuccessResponse[BreakGlassData],
    responses=_ERROR_RESPONSES,
)
def revoke_break_glass_request(
    request_id: CanonicalRequestId,
    payload: BreakGlassRevokeRequest,
    query: Annotated[BreakGlassWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: DecisionActor,
    service: BreakGlassServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[BreakGlassData]:
    del query
    result = service.revoke(
        actor,
        UUID(request_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    if result.status_code != 200:
        raise RuntimeError("break-glass revoke service returned an invalid status")
    return _response(request, response, result)


__all__ = ["router"]
