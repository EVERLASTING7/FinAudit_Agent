"""CR-005-R2 结构块纠错、候选 Parse 激活与资源安全重评边界。"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Request, Response

from app.api.dependencies.auth import CurrentActorDependency
from app.api.dependencies.document_corrections import (
    DocumentCorrectionServiceDependency,
)
from app.core.responses import utc_timestamp
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.document_corrections import (
    AcceptedJobData,
    DocumentBlockCorrectionRequest,
    DocumentCorrectionAcceptedData,
    DocumentCorrectionBlockListData,
    DocumentCorrectionBlockListQuery,
    DocumentParseActivationData,
    DocumentParseActivationRequest,
    SecurityRevalidationRequest,
)

router = APIRouter(tags=["文档纠错"])

CanonicalUuid = Annotated[
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
    403: {"description": "缺少文件权限或业务角色", "model": ErrorResponse},
    404: {"description": "资源不存在或不可见", "model": ErrorResponse},
    409: {"description": "幂等、解析版本或父版本冲突", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "文档纠错或资源安全重评环境不可用", "model": ErrorResponse},
}


@router.get(
    "/files/{file_id}/document-correction-blocks",
    operation_id="list_document_correction_blocks_v1",
    summary="读取当前活动解析版本的可纠错文本块",
    response_model=SuccessResponse[DocumentCorrectionBlockListData],
    responses=_ERROR_RESPONSES,
)
def list_document_correction_blocks(
    file_id: CanonicalUuid,
    query: Annotated[DocumentCorrectionBlockListQuery, Query()],
    request: Request,
    response: Response,
    actor: CurrentActorDependency,
    service: DocumentCorrectionServiceDependency,
) -> SuccessResponse[DocumentCorrectionBlockListData]:
    data = service.list_blocks(actor, UUID(file_id), query.cursor, query.page_size)
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[DocumentCorrectionBlockListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/document-blocks/{block_id}/correct",
    status_code=202,
    operation_id="correct_document_block_v1",
    summary="纠正文档结构块并创建候选解析版本",
    response_model=SuccessResponse[DocumentCorrectionAcceptedData],
    responses=_ERROR_RESPONSES,
)
def correct_document_block(
    block_id: CanonicalUuid,
    payload: DocumentBlockCorrectionRequest,
    request: Request,
    response: Response,
    actor: CurrentActorDependency,
    service: DocumentCorrectionServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[DocumentCorrectionAcceptedData]:
    result = service.correct_block(
        actor,
        UUID(block_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[DocumentCorrectionAcceptedData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/document-parse-versions/{parse_version_id}/activate",
    operation_id="activate_document_parse_version_v1",
    summary="独立激活已通过质量门禁的候选解析版本",
    response_model=SuccessResponse[DocumentParseActivationData],
    responses=_ERROR_RESPONSES,
)
def activate_document_parse_version(
    parse_version_id: CanonicalUuid,
    payload: DocumentParseActivationRequest,
    request: Request,
    response: Response,
    actor: CurrentActorDependency,
    service: DocumentCorrectionServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[DocumentParseActivationData]:
    result = service.activate_parse(
        actor,
        UUID(parse_version_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[DocumentParseActivationData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/document-parse-versions/{parse_version_id}/security-revalidations",
    status_code=202,
    operation_id="revalidate_document_parse_assets_v1",
    summary="创建文档资源安全重评候选",
    response_model=SuccessResponse[AcceptedJobData],
    responses=_ERROR_RESPONSES,
)
def revalidate_document_parse_assets(
    parse_version_id: CanonicalUuid,
    payload: SecurityRevalidationRequest,
    request: Request,
    response: Response,
    actor: CurrentActorDependency,
    service: DocumentCorrectionServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[AcceptedJobData]:
    result = service.request_security_revalidation(
        actor,
        UUID(parse_version_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[AcceptedJobData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


__all__ = ["router"]
