"""Authenticated invoice read endpoints."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response

from app.api.dependencies.auth import require_permission
from app.api.dependencies.contract_invoice_management import (
    ContractInvoiceManagementServiceDependency,
)
from app.api.dependencies.invoice_management import InvoiceManagementServiceDependency
from app.api.dependencies.invoice_primary_contract import (
    InvoicePrimaryContractQueryServiceDependency,
)
from app.api.dependencies.invoices import InvoiceQueryServiceDependency
from app.core.errors import AppError
from app.core.responses import utc_timestamp
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.invoices import (
    ContractInvoiceCandidateListData,
    ContractInvoiceHistoryData,
    ContractInvoiceMutationData,
    ContractInvoiceWriteQuery,
    ContractLinkSuggestionRequest,
    InvoiceCorrectionHistoryData,
    InvoiceDecisionRequest,
    InvoiceDetailData,
    InvoiceDuplicateCandidateListData,
    InvoiceDuplicateCandidateListQuery,
    InvoiceDuplicateCheckRequest,
    InvoiceDuplicateDecisionRequest,
    InvoiceEvidenceResponseData,
    InvoiceExactDuplicatePairData,
    InvoiceExactDuplicatePairQuery,
    InvoiceFactsReplaceRequest,
    InvoiceListData,
    InvoiceListQuery,
    InvoiceMutationData,
    InvoicePrimaryContractData,
    InvoiceWriteQuery,
    PrimaryContractCancelRequest,
    PrimaryContractSetRequest,
)
from app.services.auth import AuthenticatedActor
from app.services.contract_invoice_management import ContractInvoiceMutationResult
from app.services.invoice_management import InvoiceMutationResult

router = APIRouter(prefix="/invoices", tags=["发票"])

CanonicalInvoiceId = Annotated[
    str,
    Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
FinancialReadActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("financial.read")),
]
LinkSuggestActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("links.suggest")),
]
PrimaryManageActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("links.manage_primary")),
]
InvoiceManageActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("invoices.manage")),
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
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少财务读取权限", "model": ErrorResponse},
    404: {"description": "发票不存在或不可见", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "财务查询服务未配置", "model": ErrorResponse},
}
_LIST_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: response for status, response in _ERROR_RESPONSES.items() if status != 404
}
_LINK_WRITE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少合同发票关系写权限", "model": ErrorResponse},
    404: {"description": "发票、合同或关系不存在或不可见", "model": ErrorResponse},
    409: {"description": "幂等、并发、状态或关系冲突", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "财务写入服务未配置", "model": ErrorResponse},
}
_INVOICE_WRITE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少发票写权限", "model": ErrorResponse},
    404: {"description": "发票、候选或来源不存在或不可见", "model": ErrorResponse},
    409: {"description": "幂等、并发、状态、证据或重复事实冲突", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "发票写服务尚未配置", "model": ErrorResponse},
}


def _link_mutation_response(
    request: Request,
    response: Response,
    result: ContractInvoiceMutationResult,
) -> SuccessResponse[ContractInvoiceMutationData]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[ContractInvoiceMutationData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


def _invoice_mutation_response(
    request: Request,
    response: Response,
    result: InvoiceMutationResult,
) -> SuccessResponse[InvoiceMutationData]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[InvoiceMutationData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "",
    operation_id="list_invoices_v1",
    summary="读取发票列表",
    description="只返回当前 Actor 组织内未软删除的发票摘要；不支持筛选、客户端排序或聚合统计。",
    response_model=SuccessResponse[InvoiceListData],
    responses=_LIST_ERROR_RESPONSES,
)
def list_invoices(
    query: Annotated[InvoiceListQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: InvoiceQueryServiceDependency,
) -> SuccessResponse[InvoiceListData]:
    data = service.list_page(actor.organization_id, query.cursor, query.page_size)
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[InvoiceListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{invoice_id}/duplicate-candidates/{candidate_id}",
    operation_id="get_invoice_exact_duplicate_pair_v1",
    summary="读取发票精确重复对",
    description=(
        "使用单条数据库语句核对两个已知发票 UUID 是否仍属于当前 Actor 组织、可见、非作废，"
        "并共享原样非 NULL 的发票代码、发票号码和销售方税号。任一条件不满足统一返回 404；"
        "成功只证明该语句快照中的当前持久化精确等值，不执行真伪、唯一性或重复状态写入。"
    ),
    response_model=SuccessResponse[InvoiceExactDuplicatePairData],
    responses=_ERROR_RESPONSES,
)
def get_invoice_exact_duplicate_pair(
    invoice_id: CanonicalInvoiceId,
    candidate_id: CanonicalInvoiceId,
    query: Annotated[InvoiceExactDuplicatePairQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: InvoiceQueryServiceDependency,
) -> SuccessResponse[InvoiceExactDuplicatePairData]:
    del query
    data = service.get_exact_duplicate_pair(
        actor.organization_id,
        UUID(invoice_id),
        UUID(candidate_id),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[InvoiceExactDuplicatePairData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{invoice_id}/duplicate-candidates",
    operation_id="list_invoice_duplicate_candidates_v1",
    summary="读取发票精确重复候选",
    description=(
        "基于可见源发票当前持久化的发票代码、发票号码和销售方税号逐字段精确匹配；"
        "不做清理、归一化、模糊匹配或重复状态写入。源发票不存在、跨组织或软删除统一返回 404。"
    ),
    response_model=SuccessResponse[InvoiceDuplicateCandidateListData],
    responses=_ERROR_RESPONSES,
)
def list_invoice_duplicate_candidates(
    invoice_id: CanonicalInvoiceId,
    query: Annotated[InvoiceDuplicateCandidateListQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: InvoiceQueryServiceDependency,
) -> SuccessResponse[InvoiceDuplicateCandidateListData]:
    data = service.list_duplicate_candidates(
        actor.organization_id,
        UUID(invoice_id),
        query.cursor,
        query.page_size,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[InvoiceDuplicateCandidateListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{invoice_id}/contract-candidates",
    operation_id="list_invoice_contract_candidates_v1",
    summary="读取发票的可解释合同候选",
    description=(
        "按税号、名称和日期三个独立依据稳定排序同组织可见合同；不生成总分、不自动确认、不写入关系。"
    ),
    response_model=SuccessResponse[ContractInvoiceCandidateListData],
    responses=_ERROR_RESPONSES,
)
def list_invoice_contract_candidates(
    invoice_id: CanonicalInvoiceId,
    query: Annotated[ContractInvoiceWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: ContractInvoiceManagementServiceDependency,
) -> SuccessResponse[ContractInvoiceCandidateListData]:
    del query
    data = service.list_candidates(actor.organization_id, UUID(invoice_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[ContractInvoiceCandidateListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/{invoice_id}/contract-link-suggestions",
    operation_id="suggest_invoice_contract_link_v1",
    summary="建议发票合同关系",
    response_model=SuccessResponse[ContractInvoiceMutationData],
    responses=_LINK_WRITE_ERROR_RESPONSES,
)
def suggest_invoice_contract_link(
    invoice_id: CanonicalInvoiceId,
    payload: ContractLinkSuggestionRequest,
    query: Annotated[ContractInvoiceWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: LinkSuggestActor,
    service: ContractInvoiceManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[ContractInvoiceMutationData]:
    del query
    result = service.suggest(
        actor,
        UUID(invoice_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _link_mutation_response(request, response, result)


@router.get(
    "/{invoice_id}/contract-link-history",
    operation_id="get_invoice_contract_link_history_v1",
    summary="读取发票合同关系历史",
    response_model=SuccessResponse[ContractInvoiceHistoryData],
    responses=_ERROR_RESPONSES,
)
def get_invoice_contract_link_history(
    invoice_id: CanonicalInvoiceId,
    query: Annotated[ContractInvoiceWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: ContractInvoiceManagementServiceDependency,
) -> SuccessResponse[ContractInvoiceHistoryData]:
    del query
    data = service.get_history(actor.organization_id, UUID(invoice_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[ContractInvoiceHistoryData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.put(
    "/{invoice_id}/primary-contract",
    operation_id="set_invoice_primary_contract_v1",
    summary="确认或替换发票主合同",
    response_model=SuccessResponse[ContractInvoiceMutationData],
    responses=_LINK_WRITE_ERROR_RESPONSES,
)
def set_invoice_primary_contract(
    invoice_id: CanonicalInvoiceId,
    payload: PrimaryContractSetRequest,
    query: Annotated[ContractInvoiceWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: PrimaryManageActor,
    service: ContractInvoiceManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[ContractInvoiceMutationData]:
    del query
    result = service.set_primary(
        actor,
        UUID(invoice_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _link_mutation_response(request, response, result)


@router.post(
    "/{invoice_id}/primary-contract/cancel",
    operation_id="cancel_invoice_primary_contract_v1",
    summary="取消发票当前主合同",
    response_model=SuccessResponse[ContractInvoiceMutationData],
    responses=_LINK_WRITE_ERROR_RESPONSES,
)
def cancel_invoice_primary_contract(
    invoice_id: CanonicalInvoiceId,
    payload: PrimaryContractCancelRequest,
    query: Annotated[ContractInvoiceWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: PrimaryManageActor,
    service: ContractInvoiceManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[ContractInvoiceMutationData]:
    del query
    result = service.cancel_primary(
        actor,
        UUID(invoice_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _link_mutation_response(request, response, result)


@router.get(
    "/{invoice_id}/evidence",
    operation_id="get_invoice_evidence_v1",
    summary="读取发票字段与明细证据",
    response_model=SuccessResponse[InvoiceEvidenceResponseData],
    responses=_INVOICE_WRITE_ERROR_RESPONSES,
)
def get_invoice_evidence(
    invoice_id: CanonicalInvoiceId,
    query: Annotated[InvoiceWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: InvoiceManagementServiceDependency,
) -> SuccessResponse[InvoiceEvidenceResponseData]:
    del query
    data = service.get_evidence(actor.organization_id, UUID(invoice_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[InvoiceEvidenceResponseData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{invoice_id}/history",
    operation_id="get_invoice_correction_history_v1",
    summary="读取发票人工修正历史",
    response_model=SuccessResponse[InvoiceCorrectionHistoryData],
    responses=_INVOICE_WRITE_ERROR_RESPONSES,
)
def get_invoice_correction_history(
    invoice_id: CanonicalInvoiceId,
    query: Annotated[InvoiceWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: InvoiceManagementServiceDependency,
) -> SuccessResponse[InvoiceCorrectionHistoryData]:
    del query
    data = service.get_history(actor.organization_id, UUID(invoice_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[InvoiceCorrectionHistoryData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.put(
    "/{invoice_id}/facts",
    operation_id="replace_invoice_facts_v1",
    summary="完整替换未确认发票事实",
    response_model=SuccessResponse[InvoiceMutationData],
    responses=_INVOICE_WRITE_ERROR_RESPONSES,
)
def replace_invoice_facts(
    invoice_id: CanonicalInvoiceId,
    payload: InvoiceFactsReplaceRequest,
    query: Annotated[InvoiceWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: InvoiceManageActor,
    service: InvoiceManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[InvoiceMutationData]:
    del query
    result = service.replace_facts(
        actor,
        UUID(invoice_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _invoice_mutation_response(request, response, result)


@router.post(
    "/{invoice_id}/decision",
    operation_id="decide_invoice_v1",
    summary="确认或拒绝发票候选事实",
    response_model=SuccessResponse[InvoiceMutationData],
    responses=_INVOICE_WRITE_ERROR_RESPONSES,
)
def decide_invoice(
    invoice_id: CanonicalInvoiceId,
    payload: InvoiceDecisionRequest,
    query: Annotated[InvoiceWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: InvoiceManageActor,
    service: InvoiceManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[InvoiceMutationData]:
    del query
    result = service.decide(
        actor,
        UUID(invoice_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _invoice_mutation_response(request, response, result)


@router.post(
    "/{invoice_id}/duplicate-check",
    operation_id="check_invoice_duplicate_v1",
    summary="重新检测发票精确重复状态",
    response_model=SuccessResponse[InvoiceMutationData],
    responses=_INVOICE_WRITE_ERROR_RESPONSES,
)
def check_invoice_duplicate(
    invoice_id: CanonicalInvoiceId,
    payload: InvoiceDuplicateCheckRequest,
    query: Annotated[InvoiceWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: InvoiceManageActor,
    service: InvoiceManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[InvoiceMutationData]:
    del query
    result = service.check_duplicate(
        actor,
        UUID(invoice_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _invoice_mutation_response(request, response, result)


@router.post(
    "/{invoice_id}/duplicate-decision",
    operation_id="decide_invoice_duplicate_v1",
    summary="人工确认重复或批准例外",
    response_model=SuccessResponse[InvoiceMutationData],
    responses=_INVOICE_WRITE_ERROR_RESPONSES,
)
def decide_invoice_duplicate(
    invoice_id: CanonicalInvoiceId,
    payload: InvoiceDuplicateDecisionRequest,
    query: Annotated[InvoiceWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: InvoiceManageActor,
    service: InvoiceManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[InvoiceMutationData]:
    del query
    result = service.decide_duplicate(
        actor,
        UUID(invoice_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _invoice_mutation_response(request, response, result)


@router.get(
    "/{invoice_id}/primary-contract",
    operation_id="get_invoice_primary_contract_v1",
    summary="读取发票当前主合同",
    description=(
        "只返回当前 Actor 组织内可见发票唯一已确认主合同的 accepted 当前行摘要；"
        "发票不存在、跨组织或软删除统一返回 404。没有已确认主合同时返回 null，"
        "不返回候选、匹配依据、关系行或任何写能力。"
    ),
    response_model=SuccessResponse[InvoicePrimaryContractData],
    responses=_ERROR_RESPONSES,
)
def get_invoice_primary_contract(
    invoice_id: CanonicalInvoiceId,
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: InvoicePrimaryContractQueryServiceDependency,
) -> SuccessResponse[InvoicePrimaryContractData]:
    if request.query_params:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": "query.*", "reason": "invalid"}],
        )
    data = service.get(actor.organization_id, UUID(invoice_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[InvoicePrimaryContractData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{invoice_id}",
    operation_id="get_invoice_detail_v1",
    summary="读取发票详情",
    description=(
        "只返回当前 Actor 组织内可见的发票与明细事实；不存在、跨组织和软删除统一返回 "
        "404 以避免资源枚举。响应不包含证据、供应商标识、关键哈希、Actor 标识或写能力。"
    ),
    response_model=SuccessResponse[InvoiceDetailData],
    responses=_ERROR_RESPONSES,
)
def get_invoice_detail(
    invoice_id: CanonicalInvoiceId,
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: InvoiceQueryServiceDependency,
) -> SuccessResponse[InvoiceDetailData]:
    data = service.get_detail(actor.organization_id, UUID(invoice_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[InvoiceDetailData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


__all__ = ["router"]
