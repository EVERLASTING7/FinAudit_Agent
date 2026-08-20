"""审核任务、执行版本和人工复核 API。"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response

from app.api.dependencies.audits import AuditManagementServiceDependency
from app.api.dependencies.auth import require_permission
from app.core.errors import AppError
from app.core.responses import utc_timestamp
from app.schemas.audits import (
    AuditCancelData,
    AuditCancelRequest,
    AuditExecutionCreateRequest,
    AuditExecutionMutationData,
    AuditFinanceReviewRequest,
    AuditRetryData,
    AuditRetryRequest,
    AuditReviewDecisionRequest,
    AuditRiskMutationData,
    AuditRiskReviewRequest,
    AuditTaskCreateRequest,
    AuditTaskDetailData,
    AuditTaskListData,
    AuditTaskListQuery,
    AuditTaskMutationData,
)
from app.schemas.common import ErrorResponse, SuccessResponse
from app.services.audit_management import (
    AuditExecutionMutationResult,
    AuditRiskMutationResult,
    AuditTaskMutationResult,
)
from app.services.auth import AuthenticatedActor

router = APIRouter(tags=["审核"])

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
AuditReadActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("audits.read")),
]
AuditCreateActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("audits.create")),
]
FinanceReviewActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("risks.review_non_high")),
]
AuditReviewActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("risks.review_high")),
]
AuditCompleteActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("audits.complete")),
]

_READ_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少审核读取权限", "model": ErrorResponse},
    404: {"description": "审核资源不存在或不可见", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "审核运行服务尚未配置", "model": ErrorResponse},
}
_WRITE_ERRORS: dict[int | str, dict[str, Any]] = {
    **_READ_ERRORS,
    409: {"description": "幂等、并发、状态、事实或职责分离冲突", "model": ErrorResponse},
}


def _uuid(value: str) -> UUID:
    parsed = UUID(value)
    if str(parsed) != value:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
        )
    return parsed


def _task_mutation_response(
    request: Request,
    response: Response,
    result: AuditTaskMutationResult,
) -> SuccessResponse[AuditTaskMutationData]:
    response.status_code = result.status_code
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[AuditTaskMutationData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


def _execution_mutation_response(
    request: Request,
    response: Response,
    result: AuditExecutionMutationResult,
) -> SuccessResponse[AuditExecutionMutationData]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[AuditExecutionMutationData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


def _risk_mutation_response(
    request: Request,
    response: Response,
    result: AuditRiskMutationResult,
) -> SuccessResponse[AuditRiskMutationData]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[AuditRiskMutationData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/audit-tasks",
    operation_id="list_audit_tasks_v1",
    response_model=SuccessResponse[AuditTaskListData],
    responses={key: value for key, value in _READ_ERRORS.items() if key != 404},
)
def list_audit_tasks(
    query: Annotated[AuditTaskListQuery, Query()],
    request: Request,
    response: Response,
    actor: AuditReadActor,
    service: AuditManagementServiceDependency,
) -> SuccessResponse[AuditTaskListData]:
    data = service.list_tasks(actor.organization_id, query.cursor, query.page_size)
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[AuditTaskListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/audit-tasks",
    operation_id="create_audit_task_v1",
    status_code=202,
    response_model=SuccessResponse[AuditTaskMutationData],
    responses=_WRITE_ERRORS,
)
def create_audit_task(
    payload: AuditTaskCreateRequest,
    request: Request,
    response: Response,
    actor: AuditCreateActor,
    service: AuditManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[AuditTaskMutationData]:
    return _task_mutation_response(
        request,
        response,
        service.create_task(
            actor,
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@router.get(
    "/audit-tasks/{task_id}",
    operation_id="get_audit_task_v1",
    response_model=SuccessResponse[AuditTaskDetailData],
    responses=_READ_ERRORS,
)
def get_audit_task(
    task_id: CanonicalId,
    request: Request,
    response: Response,
    actor: AuditReadActor,
    service: AuditManagementServiceDependency,
) -> SuccessResponse[AuditTaskDetailData]:
    data = service.get_task(actor.organization_id, _uuid(task_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[AuditTaskDetailData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/audit-tasks/{task_id}/executions",
    operation_id="create_audit_execution_v1",
    status_code=202,
    response_model=SuccessResponse[AuditTaskMutationData],
    responses=_WRITE_ERRORS,
)
def create_audit_execution(
    task_id: CanonicalId,
    payload: AuditExecutionCreateRequest,
    request: Request,
    response: Response,
    actor: AuditCreateActor,
    service: AuditManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[AuditTaskMutationData]:
    return _task_mutation_response(
        request,
        response,
        service.create_execution(
            actor,
            _uuid(task_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@router.get(
    "/audit-executions/{execution_id}",
    operation_id="get_audit_execution_v1",
    response_model=SuccessResponse[AuditExecutionMutationData],
    responses=_READ_ERRORS,
)
def get_audit_execution(
    execution_id: CanonicalId,
    request: Request,
    response: Response,
    actor: AuditReadActor,
    service: AuditManagementServiceDependency,
) -> SuccessResponse[AuditExecutionMutationData]:
    data = service.get_execution(actor.organization_id, _uuid(execution_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[AuditExecutionMutationData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/audit-risks/{risk_id}/reviews/non-high",
    operation_id="review_non_high_audit_risk_v1",
    response_model=SuccessResponse[AuditRiskMutationData],
    responses=_WRITE_ERRORS,
)
def review_non_high_audit_risk(
    risk_id: CanonicalId,
    payload: AuditRiskReviewRequest,
    request: Request,
    response: Response,
    actor: FinanceReviewActor,
    service: AuditManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[AuditRiskMutationData]:
    return _risk_mutation_response(
        request,
        response,
        service.review_risk(
            actor,
            _uuid(risk_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
            high_risk=False,
        ),
    )


@router.post(
    "/audit-risks/{risk_id}/reviews/high",
    operation_id="review_high_audit_risk_v1",
    response_model=SuccessResponse[AuditRiskMutationData],
    responses=_WRITE_ERRORS,
)
def review_high_audit_risk(
    risk_id: CanonicalId,
    payload: AuditRiskReviewRequest,
    request: Request,
    response: Response,
    actor: AuditReviewActor,
    service: AuditManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[AuditRiskMutationData]:
    return _risk_mutation_response(
        request,
        response,
        service.review_risk(
            actor,
            _uuid(risk_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
            high_risk=True,
        ),
    )


@router.post(
    "/audit-executions/{execution_id}/finance-review",
    operation_id="complete_finance_audit_review_v1",
    response_model=SuccessResponse[AuditExecutionMutationData],
    responses=_WRITE_ERRORS,
)
def complete_finance_audit_review(
    execution_id: CanonicalId,
    payload: AuditFinanceReviewRequest,
    request: Request,
    response: Response,
    actor: AuditCompleteActor,
    service: AuditManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[AuditExecutionMutationData]:
    return _execution_mutation_response(
        request,
        response,
        service.finance_review(
            actor,
            _uuid(execution_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@router.post(
    "/audit-executions/{execution_id}/audit-review",
    operation_id="complete_high_audit_review_v1",
    response_model=SuccessResponse[AuditExecutionMutationData],
    responses=_WRITE_ERRORS,
)
def complete_high_audit_review(
    execution_id: CanonicalId,
    payload: AuditReviewDecisionRequest,
    request: Request,
    response: Response,
    actor: AuditReviewActor,
    service: AuditManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[AuditExecutionMutationData]:
    return _execution_mutation_response(
        request,
        response,
        service.audit_review(
            actor,
            _uuid(execution_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@router.post(
    "/audit-executions/{execution_id}/retry",
    status_code=202,
    operation_id="retry_audit_execution_v1",
    response_model=SuccessResponse[AuditRetryData],
    responses=_WRITE_ERRORS,
)
def retry_audit_execution(
    execution_id: CanonicalId,
    payload: AuditRetryRequest,
    request: Request,
    response: Response,
    actor: AuditCompleteActor,
    service: AuditManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[AuditRetryData]:
    result = service.retry_execution(
        actor,
        _uuid(execution_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[AuditRetryData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/audit-executions/{execution_id}/cancel",
    operation_id="cancel_audit_execution_v1",
    response_model=SuccessResponse[AuditCancelData],
    responses=_WRITE_ERRORS,
)
def cancel_audit_execution(
    execution_id: CanonicalId,
    payload: AuditCancelRequest,
    request: Request,
    response: Response,
    actor: AuditCompleteActor,
    service: AuditManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[AuditCancelData]:
    result = service.cancel_execution(
        actor,
        _uuid(execution_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[AuditCancelData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


__all__ = ["router"]
