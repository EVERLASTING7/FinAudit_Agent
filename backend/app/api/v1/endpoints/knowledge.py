"""知识索引与检索评测管理 API。"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status

from app.api.dependencies.auth import require_permission
from app.api.dependencies.knowledge import (
    KnowledgeIndexManagementServiceDependency,
    RagQueryServiceDependency,
)
from app.api.dependencies.knowledge_catalog import KnowledgeCatalogServiceDependency
from app.core.responses import utc_timestamp
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.knowledge_bases import (
    KnowledgeBaseData,
    KnowledgeBaseListData,
    KnowledgeBaseListQuery,
    KnowledgeBaseReadQuery,
)
from app.schemas.retrieval import (
    EvaluationDatasetCreateRequest,
    EvaluationDatasetData,
    EvaluationRunData,
    EvaluationRunRequest,
    IndexBuildRequest,
    IndexVersionData,
    QaFeedbackData,
    QaFeedbackRequest,
    QaQueryData,
    QaQueryRequest,
    VersionedTransitionRequest,
)
from app.services.auth import AuthenticatedActor
from app.services.knowledge_index_management import (
    DatasetMutationResult,
    EvaluationRunMutationResult,
    IndexMutationResult,
)
from app.services.rag_query import QaFeedbackMutationResult, QaQueryMutationResult

router = APIRouter(prefix="/knowledge-bases", tags=["知识检索"])
feedback_router = APIRouter(prefix="/qa-queries", tags=["知识检索"])

CanonicalId = Annotated[
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
KnowledgePublishActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("knowledge.publish")),
]
KnowledgeSubmitActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("knowledge.submit")),
]
KnowledgeApproveActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("knowledge.approve")),
]
KnowledgeUseActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("knowledge.use")),
]

_READ_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少知识索引权限", "model": ErrorResponse},
    404: {"description": "知识库、索引、评测集或评测运行不存在", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "知识索引服务尚未配置", "model": ErrorResponse},
}
_WRITE_ERRORS: dict[int | str, dict[str, Any]] = {
    **_READ_ERRORS,
    409: {"description": "幂等、版本、状态、职责分离或评测门禁冲突", "model": ErrorResponse},
}


def _headers(response: Response, *, replayed: bool | None = None) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    if replayed is not None:
        response.headers["Idempotency-Replayed"] = str(replayed).lower()


def _index_mutation(
    request: Request, response: Response, result: IndexMutationResult
) -> SuccessResponse[IndexVersionData]:
    response.status_code = result.status_code
    _headers(response, replayed=result.replayed)
    return SuccessResponse[IndexVersionData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


def _dataset_mutation(
    request: Request, response: Response, result: DatasetMutationResult
) -> SuccessResponse[EvaluationDatasetData]:
    response.status_code = result.status_code
    _headers(response, replayed=result.replayed)
    return SuccessResponse[EvaluationDatasetData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


def _run_mutation(
    request: Request, response: Response, result: EvaluationRunMutationResult
) -> SuccessResponse[EvaluationRunData]:
    response.status_code = result.status_code
    _headers(response, replayed=result.replayed)
    return SuccessResponse[EvaluationRunData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


def _query_mutation(
    request: Request, response: Response, result: QaQueryMutationResult
) -> SuccessResponse[QaQueryData]:
    response.status_code = result.status_code
    _headers(response, replayed=result.replayed)
    return SuccessResponse[QaQueryData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


def _feedback_mutation(
    request: Request, response: Response, result: QaFeedbackMutationResult
) -> SuccessResponse[QaFeedbackData]:
    response.status_code = result.status_code
    _headers(response, replayed=result.replayed)
    return SuccessResponse[QaFeedbackData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "",
    operation_id="list_knowledge_bases_v1",
    summary="读取知识库目录",
    response_model=SuccessResponse[KnowledgeBaseListData],
    responses={key: value for key, value in _READ_ERRORS.items() if key != 404},
)
def list_knowledge_bases(
    query: Annotated[KnowledgeBaseListQuery, Query()],
    request: Request,
    response: Response,
    actor: KnowledgeUseActor,
    service: KnowledgeCatalogServiceDependency,
) -> SuccessResponse[KnowledgeBaseListData]:
    data = service.list_page(actor.organization_id, query.cursor, query.page_size)
    _headers(response)
    return SuccessResponse[KnowledgeBaseListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{knowledge_base_id}",
    operation_id="get_knowledge_base_v1",
    summary="读取知识库详情",
    response_model=SuccessResponse[KnowledgeBaseData],
    responses=_READ_ERRORS,
)
def get_knowledge_base(
    knowledge_base_id: CanonicalId,
    query: Annotated[KnowledgeBaseReadQuery, Query()],
    request: Request,
    response: Response,
    actor: KnowledgeUseActor,
    service: KnowledgeCatalogServiceDependency,
) -> SuccessResponse[KnowledgeBaseData]:
    del query
    data = service.get_detail(actor.organization_id, UUID(knowledge_base_id))
    _headers(response)
    return SuccessResponse[KnowledgeBaseData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/{knowledge_base_id}/index-versions",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="build_knowledge_index_v1",
    summary="冻结成员并创建候选知识索引",
    response_model=SuccessResponse[IndexVersionData],
    responses=_WRITE_ERRORS,
)
def build_knowledge_index(
    knowledge_base_id: CanonicalId,
    payload: IndexBuildRequest,
    request: Request,
    response: Response,
    actor: KnowledgePublishActor,
    service: KnowledgeIndexManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[IndexVersionData]:
    del payload
    return _index_mutation(
        request,
        response,
        service.build_index(
            actor,
            UUID(knowledge_base_id),
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@router.get(
    "/{knowledge_base_id}/index-versions/{index_version_id}",
    operation_id="get_knowledge_index_v1",
    summary="读取知识索引版本",
    response_model=SuccessResponse[IndexVersionData],
    responses=_READ_ERRORS,
)
def get_knowledge_index(
    knowledge_base_id: CanonicalId,
    index_version_id: CanonicalId,
    request: Request,
    response: Response,
    actor: KnowledgePublishActor,
    service: KnowledgeIndexManagementServiceDependency,
) -> SuccessResponse[IndexVersionData]:
    data = service.get_index(actor, UUID(knowledge_base_id), UUID(index_version_id))
    _headers(response)
    return SuccessResponse[IndexVersionData](
        data=data, trace_id=request.state.trace_id, timestamp=utc_timestamp()
    )


@router.post(
    "/{knowledge_base_id}/index-versions/{index_version_id}/evaluations",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="evaluate_knowledge_index_v1",
    summary="创建冻结检索评测运行",
    response_model=SuccessResponse[EvaluationRunData],
    responses=_WRITE_ERRORS,
)
def evaluate_knowledge_index(
    knowledge_base_id: CanonicalId,
    index_version_id: CanonicalId,
    payload: EvaluationRunRequest,
    request: Request,
    response: Response,
    actor: KnowledgePublishActor,
    service: KnowledgeIndexManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[EvaluationRunData]:
    return _run_mutation(
        request,
        response,
        service.create_evaluation_run(
            actor,
            UUID(knowledge_base_id),
            UUID(index_version_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@router.post(
    "/{knowledge_base_id}/index-versions/{index_version_id}/activate",
    operation_id="activate_knowledge_index_v1",
    summary="通过正式评测门禁后激活索引",
    response_model=SuccessResponse[IndexVersionData],
    responses=_WRITE_ERRORS,
)
def activate_knowledge_index(
    knowledge_base_id: CanonicalId,
    index_version_id: CanonicalId,
    payload: VersionedTransitionRequest,
    request: Request,
    response: Response,
    actor: KnowledgePublishActor,
    service: KnowledgeIndexManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[IndexVersionData]:
    return _index_mutation(
        request,
        response,
        service.activate_index(
            actor,
            UUID(knowledge_base_id),
            UUID(index_version_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@router.post(
    "/{knowledge_base_id}/retrieval-eval-datasets",
    status_code=status.HTTP_201_CREATED,
    operation_id="create_retrieval_eval_dataset_v1",
    summary="创建冻结检索评测集草稿",
    response_model=SuccessResponse[EvaluationDatasetData],
    responses=_WRITE_ERRORS,
)
def create_retrieval_eval_dataset(
    knowledge_base_id: CanonicalId,
    payload: EvaluationDatasetCreateRequest,
    request: Request,
    response: Response,
    actor: KnowledgeSubmitActor,
    service: KnowledgeIndexManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[EvaluationDatasetData]:
    return _dataset_mutation(
        request,
        response,
        service.create_dataset(
            actor,
            UUID(knowledge_base_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@router.get(
    "/{knowledge_base_id}/retrieval-eval-datasets/{dataset_id}",
    operation_id="get_retrieval_eval_dataset_v1",
    summary="读取检索评测集",
    response_model=SuccessResponse[EvaluationDatasetData],
    responses=_READ_ERRORS,
)
def get_retrieval_eval_dataset(
    knowledge_base_id: CanonicalId,
    dataset_id: CanonicalId,
    request: Request,
    response: Response,
    actor: KnowledgePublishActor,
    service: KnowledgeIndexManagementServiceDependency,
) -> SuccessResponse[EvaluationDatasetData]:
    data = service.get_dataset(actor, UUID(knowledge_base_id), UUID(dataset_id))
    _headers(response)
    return SuccessResponse[EvaluationDatasetData](
        data=data, trace_id=request.state.trace_id, timestamp=utc_timestamp()
    )


def _transition_dataset(
    *,
    action: str,
    knowledge_base_id: str,
    dataset_id: str,
    payload: VersionedTransitionRequest,
    request: Request,
    response: Response,
    actor: AuthenticatedActor,
    service: KnowledgeIndexManagementServiceDependency,
    idempotency_key: str,
) -> SuccessResponse[EvaluationDatasetData]:
    return _dataset_mutation(
        request,
        response,
        service.transition_dataset(
            actor,
            UUID(knowledge_base_id),
            UUID(dataset_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
            action=action,
        ),
    )


@router.post(
    "/{knowledge_base_id}/retrieval-eval-datasets/{dataset_id}/submit-review",
    operation_id="submit_retrieval_eval_dataset_v1",
    summary="提交检索评测集独立审批",
    response_model=SuccessResponse[EvaluationDatasetData],
    responses=_WRITE_ERRORS,
)
def submit_retrieval_eval_dataset(
    knowledge_base_id: CanonicalId,
    dataset_id: CanonicalId,
    payload: VersionedTransitionRequest,
    request: Request,
    response: Response,
    actor: KnowledgeSubmitActor,
    service: KnowledgeIndexManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[EvaluationDatasetData]:
    return _transition_dataset(
        action="submit",
        knowledge_base_id=knowledge_base_id,
        dataset_id=dataset_id,
        payload=payload,
        request=request,
        response=response,
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/{knowledge_base_id}/retrieval-eval-datasets/{dataset_id}/approve",
    operation_id="approve_retrieval_eval_dataset_v1",
    summary="独立批准检索评测集",
    response_model=SuccessResponse[EvaluationDatasetData],
    responses=_WRITE_ERRORS,
)
def approve_retrieval_eval_dataset(
    knowledge_base_id: CanonicalId,
    dataset_id: CanonicalId,
    payload: VersionedTransitionRequest,
    request: Request,
    response: Response,
    actor: KnowledgeApproveActor,
    service: KnowledgeIndexManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[EvaluationDatasetData]:
    return _transition_dataset(
        action="approve",
        knowledge_base_id=knowledge_base_id,
        dataset_id=dataset_id,
        payload=payload,
        request=request,
        response=response,
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/{knowledge_base_id}/retrieval-eval-runs/{run_id}",
    operation_id="get_retrieval_eval_run_v1",
    summary="读取检索评测运行",
    response_model=SuccessResponse[EvaluationRunData],
    responses=_READ_ERRORS,
)
def get_retrieval_eval_run(
    knowledge_base_id: CanonicalId,
    run_id: CanonicalId,
    request: Request,
    response: Response,
    actor: KnowledgePublishActor,
    service: KnowledgeIndexManagementServiceDependency,
) -> SuccessResponse[EvaluationRunData]:
    data = service.get_evaluation_run(actor, UUID(knowledge_base_id), UUID(run_id))
    _headers(response)
    return SuccessResponse[EvaluationRunData](
        data=data, trace_id=request.state.trace_id, timestamp=utc_timestamp()
    )


@router.post(
    "/{knowledge_base_id}/qa-queries",
    operation_id="query_knowledge_base_v1",
    summary="执行授权检索并生成可追溯回答",
    response_model=SuccessResponse[QaQueryData],
    responses=_WRITE_ERRORS,
)
def query_knowledge_base(
    knowledge_base_id: CanonicalId,
    payload: QaQueryRequest,
    request: Request,
    response: Response,
    actor: KnowledgeUseActor,
    service: RagQueryServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[QaQueryData]:
    return _query_mutation(
        request,
        response,
        service.query(
            actor,
            UUID(knowledge_base_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@feedback_router.post(
    "/{query_id}/feedback",
    status_code=status.HTTP_201_CREATED,
    operation_id="create_qa_feedback_v1",
    summary="为本人知识问答提交一次反馈",
    response_model=SuccessResponse[QaFeedbackData],
    responses=_WRITE_ERRORS,
)
def create_qa_feedback(
    query_id: CanonicalId,
    payload: QaFeedbackRequest,
    request: Request,
    response: Response,
    actor: KnowledgeUseActor,
    service: RagQueryServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[QaFeedbackData]:
    return _feedback_mutation(
        request,
        response,
        service.feedback(
            actor,
            UUID(query_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


__all__ = ["feedback_router", "router"]
