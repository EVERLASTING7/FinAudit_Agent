"""组织范围内的供应商候选读取、来源解析与人工处理 API。"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response

from app.api.dependencies.auth import require_permission
from app.api.dependencies.suppliers import SupplierManagementServiceDependency
from app.core.responses import utc_timestamp
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.suppliers import (
    SupplierCandidateUpdateRequest,
    SupplierData,
    SupplierListData,
    SupplierListQuery,
    SupplierMutationData,
    SupplierReadQuery,
    SupplierResolveData,
    SupplierSourceResolveRequest,
)
from app.services.auth import AuthenticatedActor
from app.services.supplier_management import SupplierMutationResult, SupplierResolveResult

router = APIRouter(prefix="/suppliers", tags=["供应商"])

CanonicalSupplierId = Annotated[
    str,
    Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
FinancialReadActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("financial.read")),
]
SupplierCorrectActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("suppliers.correct")),
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
_READ_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少财务读取权限", "model": ErrorResponse},
    404: {"description": "供应商不存在或不可见", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "供应商服务尚未配置", "model": ErrorResponse},
}
_LIST_ERRORS = {status: value for status, value in _READ_ERRORS.items() if status != 404}
_WRITE_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少供应商修正权限", "model": ErrorResponse},
    404: {"description": "供应商或来源不存在或不可见", "model": ErrorResponse},
    409: {"description": "幂等、版本、状态或税务身份冲突", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "供应商服务尚未配置", "model": ErrorResponse},
}


def _resolve_response(
    request: Request,
    response: Response,
    result: SupplierResolveResult,
) -> SuccessResponse[SupplierResolveData]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[SupplierResolveData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


def _mutation_response(
    request: Request,
    response: Response,
    result: SupplierMutationResult,
) -> SuccessResponse[SupplierMutationData]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[SupplierMutationData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "",
    operation_id="list_suppliers_v1",
    summary="读取供应商列表",
    response_model=SuccessResponse[SupplierListData],
    responses=_LIST_ERRORS,
)
def list_suppliers(
    query: Annotated[SupplierListQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: SupplierManagementServiceDependency,
) -> SuccessResponse[SupplierListData]:
    data = service.list_page(actor.organization_id, query.cursor, query.page_size)
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[SupplierListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/source-candidates",
    operation_id="resolve_supplier_source_candidate_v1",
    summary="从已确认合同或发票解析供应商候选",
    response_model=SuccessResponse[SupplierResolveData],
    responses=_WRITE_ERRORS,
)
def resolve_supplier_source_candidate(
    payload: SupplierSourceResolveRequest,
    request: Request,
    response: Response,
    actor: SupplierCorrectActor,
    service: SupplierManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[SupplierResolveData]:
    result = service.resolve_source(
        actor,
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _resolve_response(request, response, result)


@router.get(
    "/{supplier_id}",
    operation_id="get_supplier_v1",
    summary="读取供应商详情",
    response_model=SuccessResponse[SupplierData],
    responses=_READ_ERRORS,
)
def get_supplier(
    supplier_id: CanonicalSupplierId,
    query: Annotated[SupplierReadQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: SupplierManagementServiceDependency,
) -> SuccessResponse[SupplierData]:
    del query
    data = service.get_detail(actor.organization_id, UUID(supplier_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[SupplierData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.patch(
    "/{supplier_id}",
    operation_id="update_supplier_candidate_v1",
    summary="修正、确认或拒绝供应商候选",
    response_model=SuccessResponse[SupplierMutationData],
    responses=_WRITE_ERRORS,
)
def update_supplier_candidate(
    supplier_id: CanonicalSupplierId,
    payload: SupplierCandidateUpdateRequest,
    request: Request,
    response: Response,
    actor: SupplierCorrectActor,
    service: SupplierManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[SupplierMutationData]:
    result = service.update_candidate(
        actor,
        UUID(supplier_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _mutation_response(request, response, result)


__all__ = ["router"]
