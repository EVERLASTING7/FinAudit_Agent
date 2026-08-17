"""Authenticated contract current-row read endpoints."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response

from app.api.dependencies.auth import require_permission
from app.api.dependencies.contract_management import ContractManagementServiceDependency
from app.api.dependencies.contract_primary_invoices import (
    ContractPrimaryInvoiceQueryServiceDependency,
)
from app.api.dependencies.contracts import ContractQueryServiceDependency
from app.api.dependencies.effective_contracts import (
    EffectiveContractQueryServiceDependency,
)
from app.api.dependencies.supplementary_agreement_management import (
    SupplementaryAgreementManagementServiceDependency,
)
from app.api.dependencies.supplementary_agreements import (
    SupplementaryAgreementQueryServiceDependency,
)
from app.core.responses import utc_timestamp
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.contracts import (
    ContractCorrectionHistoryData,
    ContractDecisionRequest,
    ContractDetailData,
    ContractEvidenceResponseData,
    ContractFactsReplaceRequest,
    ContractListData,
    ContractListQuery,
    ContractMutationData,
    EffectiveContractData,
    EffectiveContractQuery,
    FinancialWriteQuery,
    SupplementaryAgreementDecisionRequest,
    SupplementaryAgreementDetailData,
    SupplementaryAgreementHeaderListData,
    SupplementaryAgreementHeaderListQuery,
    SupplementaryChangesReplaceRequest,
)
from app.schemas.invoices import (
    ContractPrimaryInvoiceListData,
    ContractPrimaryInvoiceListQuery,
)
from app.services.auth import AuthenticatedActor
from app.services.contract_management import ContractMutationResult
from app.services.supplementary_agreement_management import (
    SupplementaryAgreementMutationResult,
)

router = APIRouter(prefix="/contracts", tags=["合同"])
CanonicalContractId = Annotated[
    str,
    Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
FinancialReadActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("financial.read")),
]
ContractsManageActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("contracts.manage")),
]
CanonicalAgreementId = Annotated[
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
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少财务读取权限", "model": ErrorResponse},
    404: {"description": "合同不存在或不可见", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "财务查询服务未配置", "model": ErrorResponse},
}
_LIST_ERROR_RESPONSES = {
    status: model for status, model in _ERROR_RESPONSES.items() if status != 404
}
_EFFECTIVE_ERROR_RESPONSES = {
    **_ERROR_RESPONSES,
    409: {"description": "有效字段存在冲突", "model": ErrorResponse},
}
_SUPPLEMENTARY_WRITE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少合同管理权限", "model": ErrorResponse},
    404: {"description": "合同或补充协议不存在或不可见", "model": ErrorResponse},
    409: {"description": "幂等、并发、状态、字段或证据冲突", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "财务写入服务未配置", "model": ErrorResponse},
}
_CONTRACT_WRITE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少合同管理权限", "model": ErrorResponse},
    404: {"description": "合同或来源不存在或不可见", "model": ErrorResponse},
    409: {"description": "幂等、并发、状态、编号或证据冲突", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "合同写服务尚未配置", "model": ErrorResponse},
}


def _supplementary_mutation_response(
    request: Request,
    response: Response,
    result: SupplementaryAgreementMutationResult,
) -> SuccessResponse[SupplementaryAgreementDetailData]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[SupplementaryAgreementDetailData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


def _contract_mutation_response(
    request: Request,
    response: Response,
    result: ContractMutationResult,
) -> SuccessResponse[ContractMutationData]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[ContractMutationData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "",
    operation_id="list_contracts_v1",
    summary="读取合同列表",
    description="只返回当前 Actor 组织内未软删除的 accepted 合同当前行摘要。",
    response_model=SuccessResponse[ContractListData],
    responses=_LIST_ERROR_RESPONSES,
)
def list_contracts(
    query: Annotated[ContractListQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: ContractQueryServiceDependency,
) -> SuccessResponse[ContractListData]:
    data = service.list_page(actor.organization_id, query.cursor, query.page_size)
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[ContractListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{contract_id}/supplementary-agreements",
    operation_id="list_supplementary_agreement_headers_v1",
    summary="读取补充协议 Header 列表",
    description=(
        "只返回当前 Actor 组织内可见合同下 accepted 009 的当前原始 Header；"
        "不返回字段变更，不计算生效或适用资格，也不表示协议已进入审核快照。"
    ),
    response_model=SuccessResponse[SupplementaryAgreementHeaderListData],
    responses=_ERROR_RESPONSES,
)
def list_supplementary_agreement_headers(
    contract_id: CanonicalContractId,
    query: Annotated[SupplementaryAgreementHeaderListQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: SupplementaryAgreementQueryServiceDependency,
) -> SuccessResponse[SupplementaryAgreementHeaderListData]:
    data = service.list_headers(
        actor.organization_id,
        UUID(contract_id),
        query.cursor,
        query.page_size,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[SupplementaryAgreementHeaderListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{contract_id}/supplementary-agreements/{agreement_id}",
    operation_id="get_supplementary_agreement_detail_v1",
    summary="读取补充协议及字段级变更",
    response_model=SuccessResponse[SupplementaryAgreementDetailData],
    responses=_ERROR_RESPONSES,
)
def get_supplementary_agreement_detail(
    contract_id: CanonicalContractId,
    agreement_id: CanonicalAgreementId,
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: SupplementaryAgreementManagementServiceDependency,
) -> SuccessResponse[SupplementaryAgreementDetailData]:
    data = service.get_detail(actor, UUID(contract_id), UUID(agreement_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[SupplementaryAgreementDetailData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.put(
    "/{contract_id}/supplementary-agreements/{agreement_id}/changes",
    operation_id="replace_supplementary_agreement_changes_v1",
    summary="整组替换补充协议字段级变更",
    response_model=SuccessResponse[SupplementaryAgreementDetailData],
    responses=_SUPPLEMENTARY_WRITE_ERROR_RESPONSES,
)
def replace_supplementary_agreement_changes(
    contract_id: CanonicalContractId,
    agreement_id: CanonicalAgreementId,
    payload: SupplementaryChangesReplaceRequest,
    query: Annotated[FinancialWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: ContractsManageActor,
    service: SupplementaryAgreementManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[SupplementaryAgreementDetailData]:
    del query
    result = service.replace_changes(
        actor,
        UUID(contract_id),
        UUID(agreement_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _supplementary_mutation_response(request, response, result)


@router.post(
    "/{contract_id}/supplementary-agreements/{agreement_id}/decision",
    operation_id="decide_supplementary_agreement_v1",
    summary="确认或拒绝补充协议字段级变更",
    response_model=SuccessResponse[SupplementaryAgreementDetailData],
    responses=_SUPPLEMENTARY_WRITE_ERROR_RESPONSES,
)
def decide_supplementary_agreement(
    contract_id: CanonicalContractId,
    agreement_id: CanonicalAgreementId,
    payload: SupplementaryAgreementDecisionRequest,
    query: Annotated[FinancialWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: ContractsManageActor,
    service: SupplementaryAgreementManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[SupplementaryAgreementDetailData]:
    del query
    result = service.decide(
        actor,
        UUID(contract_id),
        UUID(agreement_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _supplementary_mutation_response(request, response, result)


@router.get(
    "/{contract_id}/primary-invoices",
    operation_id="list_contract_primary_invoices_v1",
    summary="读取合同当前主发票列表",
    description=(
        "只返回当前 Actor 组织内可见合同作为 confirmed_primary 主合同的发票摘要；"
        "不存在、跨组织或软删除的父合同统一返回 404。"
        "不返回候选、关系、匹配依据、历史或任何写能力。"
    ),
    response_model=SuccessResponse[ContractPrimaryInvoiceListData],
    responses=_ERROR_RESPONSES,
)
def list_contract_primary_invoices(
    contract_id: CanonicalContractId,
    query: Annotated[ContractPrimaryInvoiceListQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: ContractPrimaryInvoiceQueryServiceDependency,
) -> SuccessResponse[ContractPrimaryInvoiceListData]:
    data = service.list_page(
        actor.organization_id,
        UUID(contract_id),
        query.cursor,
        query.page_size,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[ContractPrimaryInvoiceListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{contract_id}/effective-fields",
    operation_id="get_effective_contract_fields_v1",
    summary="读取基准日期有效合同字段",
    description=(
        "分别返回合同原始字段和显式基准日期的有效值；只整体应用已确认且已生效的"
        "补充协议，同字段同日冲突时失败关闭。"
    ),
    response_model=SuccessResponse[EffectiveContractData],
    responses=_EFFECTIVE_ERROR_RESPONSES,
)
def get_effective_contract_fields(
    contract_id: CanonicalContractId,
    query: Annotated[EffectiveContractQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: EffectiveContractQueryServiceDependency,
) -> SuccessResponse[EffectiveContractData]:
    data = service.get_effective_contract(
        actor.organization_id,
        UUID(contract_id),
        query.baseline_date,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[EffectiveContractData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{contract_id}/evidence",
    operation_id="get_contract_evidence_v1",
    summary="读取合同候选字段与证据",
    response_model=SuccessResponse[ContractEvidenceResponseData],
    responses=_CONTRACT_WRITE_ERROR_RESPONSES,
)
def get_contract_evidence(
    contract_id: CanonicalContractId,
    query: Annotated[FinancialWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: ContractManagementServiceDependency,
) -> SuccessResponse[ContractEvidenceResponseData]:
    del query
    data = service.get_evidence(actor.organization_id, UUID(contract_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[ContractEvidenceResponseData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{contract_id}/history",
    operation_id="get_contract_correction_history_v1",
    summary="读取合同人工修正历史",
    response_model=SuccessResponse[ContractCorrectionHistoryData],
    responses=_CONTRACT_WRITE_ERROR_RESPONSES,
)
def get_contract_correction_history(
    contract_id: CanonicalContractId,
    query: Annotated[FinancialWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: ContractManagementServiceDependency,
) -> SuccessResponse[ContractCorrectionHistoryData]:
    del query
    data = service.get_history(actor.organization_id, UUID(contract_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[ContractCorrectionHistoryData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.put(
    "/{contract_id}/facts",
    operation_id="replace_contract_facts_v1",
    summary="完整替换未确认合同事实",
    response_model=SuccessResponse[ContractMutationData],
    responses=_CONTRACT_WRITE_ERROR_RESPONSES,
)
def replace_contract_facts(
    contract_id: CanonicalContractId,
    payload: ContractFactsReplaceRequest,
    query: Annotated[FinancialWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: ContractsManageActor,
    service: ContractManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[ContractMutationData]:
    del query
    result = service.replace_facts(
        actor,
        UUID(contract_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _contract_mutation_response(request, response, result)


@router.post(
    "/{contract_id}/decision",
    operation_id="decide_contract_v1",
    summary="确认或拒绝合同候选事实",
    response_model=SuccessResponse[ContractMutationData],
    responses=_CONTRACT_WRITE_ERROR_RESPONSES,
)
def decide_contract(
    contract_id: CanonicalContractId,
    payload: ContractDecisionRequest,
    query: Annotated[FinancialWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: ContractsManageActor,
    service: ContractManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[ContractMutationData]:
    del query
    result = service.decide(
        actor,
        UUID(contract_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    return _contract_mutation_response(request, response, result)


@router.get(
    "/{contract_id}",
    operation_id="get_contract_detail_v1",
    summary="读取合同详情",
    description=(
        "只返回当前 Actor 组织内未软删除的 accepted 合同当前持久化行；不存在、跨组织和"
        "软删除统一返回 404。本接口不应用补充协议有效字段。"
    ),
    response_model=SuccessResponse[ContractDetailData],
    responses=_ERROR_RESPONSES,
)
def get_contract_detail(
    contract_id: CanonicalContractId,
    request: Request,
    response: Response,
    actor: FinancialReadActor,
    service: ContractQueryServiceDependency,
) -> SuccessResponse[ContractDetailData]:
    data = service.get_detail(actor.organization_id, UUID(contract_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[ContractDetailData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


__all__ = ["router"]
