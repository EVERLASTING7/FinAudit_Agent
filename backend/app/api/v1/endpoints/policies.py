"""制度元数据、业务审批与结构分块 API。"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status

from app.api.dependencies.auth import require_permission
from app.api.dependencies.policies import PolicyManagementServiceDependency
from app.core.responses import utc_timestamp
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.policies import (
    PolicyCreateRequest,
    PolicyData,
    PolicyListData,
    PolicyListQuery,
    PolicyReadQuery,
    PolicyTransitionRequest,
    PolicyWriteData,
)
from app.services.auth import AuthenticatedActor
from app.services.policy_management import PolicyMutationResult

router = APIRouter(prefix="/policy-documents", tags=["制度知识库"])

CanonicalPolicyId = Annotated[
    str,
    Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
KnowledgeReadActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("knowledge.use")),
]
KnowledgeSubmitActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("knowledge.submit")),
]
KnowledgeApproveActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("knowledge.approve")),
]
KnowledgePublishActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("knowledge.publish")),
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
    403: {"description": "缺少制度读取权限", "model": ErrorResponse},
    404: {"description": "制度不存在或不可见", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "制度服务尚未配置", "model": ErrorResponse},
}
_WRITE_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少制度提交或审批权限", "model": ErrorResponse},
    404: {"description": "制度、知识库或来源文件不存在或不可见", "model": ErrorResponse},
    409: {"description": "幂等、版本、状态、职责分离或质量门禁冲突", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "制度服务尚未配置", "model": ErrorResponse},
}
_LIST_ERRORS = {key: value for key, value in _READ_ERRORS.items() if key != 404}


def _mutation_response(
    request: Request,
    response: Response,
    result: PolicyMutationResult,
) -> SuccessResponse[PolicyWriteData]:
    response.status_code = result.status_code
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[PolicyWriteData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "",
    operation_id="list_policy_documents_v1",
    summary="读取制度列表",
    response_model=SuccessResponse[PolicyListData],
    responses=_LIST_ERRORS,
)
def list_policy_documents(
    query: Annotated[PolicyListQuery, Query()],
    request: Request,
    response: Response,
    actor: KnowledgeReadActor,
    service: PolicyManagementServiceDependency,
) -> SuccessResponse[PolicyListData]:
    data = service.list_page(
        actor,
        query.cursor,
        query.page_size,
        knowledge_base_id=query.knowledge_base_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[PolicyListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    operation_id="create_policy_document_v1",
    summary="从已处理制度文件创建草稿",
    response_model=SuccessResponse[PolicyWriteData],
    responses=_WRITE_ERRORS,
)
def create_policy_document(
    payload: PolicyCreateRequest,
    request: Request,
    response: Response,
    actor: KnowledgeSubmitActor,
    service: PolicyManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[PolicyWriteData]:
    return _mutation_response(
        request,
        response,
        service.create(actor, payload, idempotency_key, UUID(request.state.trace_id)),
    )


@router.get(
    "/{policy_id}",
    operation_id="get_policy_document_v1",
    summary="读取制度详情",
    response_model=SuccessResponse[PolicyData],
    responses=_READ_ERRORS,
)
def get_policy_document(
    policy_id: CanonicalPolicyId,
    query: Annotated[PolicyReadQuery, Query()],
    request: Request,
    response: Response,
    actor: KnowledgeReadActor,
    service: PolicyManagementServiceDependency,
) -> SuccessResponse[PolicyData]:
    del query
    data = service.get_detail(actor, UUID(policy_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[PolicyData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/{policy_id}/submit-review",
    operation_id="submit_policy_document_v1",
    summary="提交制度业务审批",
    response_model=SuccessResponse[PolicyWriteData],
    responses=_WRITE_ERRORS,
)
def submit_policy_document(
    policy_id: CanonicalPolicyId,
    payload: PolicyTransitionRequest,
    request: Request,
    response: Response,
    actor: KnowledgeSubmitActor,
    service: PolicyManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[PolicyWriteData]:
    return _mutation_response(
        request,
        response,
        service.submit(
            actor,
            UUID(policy_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@router.post(
    "/{policy_id}/approve",
    operation_id="approve_policy_document_v1",
    summary="独立批准制度并激活结构分块",
    response_model=SuccessResponse[PolicyWriteData],
    responses=_WRITE_ERRORS,
)
def approve_policy_document(
    policy_id: CanonicalPolicyId,
    payload: PolicyTransitionRequest,
    request: Request,
    response: Response,
    actor: KnowledgeApproveActor,
    service: PolicyManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[PolicyWriteData]:
    return _mutation_response(
        request,
        response,
        service.approve(
            actor,
            UUID(policy_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@router.post(
    "/{policy_id}/publish",
    operation_id="publish_policy_document_v1",
    summary="通过正式检索评测门禁后技术发布制度",
    response_model=SuccessResponse[PolicyWriteData],
    responses=_WRITE_ERRORS,
)
def publish_policy_document(
    policy_id: CanonicalPolicyId,
    payload: PolicyTransitionRequest,
    request: Request,
    response: Response,
    actor: KnowledgePublishActor,
    service: PolicyManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[PolicyWriteData]:
    return _mutation_response(
        request,
        response,
        service.publish(
            actor,
            UUID(policy_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


__all__ = ["router"]
