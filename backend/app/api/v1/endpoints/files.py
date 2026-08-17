"""file-upload-intake-v1 与 file-read-v1 HTTP 边界。"""

from __future__ import annotations

from pathlib import PurePath
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Path,
    Query,
    Request,
    Response,
)
from pydantic import ValidationError

from app.api.dependencies.auth import require_permission
from app.api.dependencies.files import (
    FileIntakeServiceDependency,
    FileManagementServiceDependency,
    FileQueryServiceDependency,
    StrictFileBatchUploadDependency,
    StrictFileUploadDependency,
)
from app.core.errors import AppError
from app.core.responses import utc_timestamp
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.files import (
    FileArchiveRequest,
    FileBatchUploadData,
    FileListData,
    FileListItemData,
    FileListQuery,
    FileRetryRequest,
    FileTextPreviewData,
    FileUploadData,
    FileUploadIntent,
    FileWriteQuery,
)
from app.services.auth import AuthenticatedActor
from app.services.file_intake import FileBatchUploadInput
from app.services.file_management import FileMutationResult, FilePreviewResult

router = APIRouter(prefix="/files", tags=["文件管理"])

UploadActor = Annotated[AuthenticatedActor, Depends(require_permission("files.upload"))]
ReadActor = Annotated[AuthenticatedActor, Depends(require_permission("files.read"))]
ManageActor = Annotated[AuthenticatedActor, Depends(require_permission("files.manage"))]
CanonicalFileId = Annotated[
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
    400: {"description": "文件内容或格式不合法", "model": ErrorResponse},
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少文件权限", "model": ErrorResponse},
    404: {"description": "资源不存在或不可见", "model": ErrorResponse},
    409: {"description": "幂等、去重、分类或状态冲突", "model": ErrorResponse},
    413: {"description": "文件超过大小限制", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "文件服务或存储不可用", "model": ErrorResponse},
}


def _parse_boolean(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise AppError(status_code=422, code="VALIDATION_ERROR", message="请求参数不符合约束")


def _parse_intent(
    intended_business_type: str,
    auto_process_requested: str,
    target_knowledge_base_id: str | None,
) -> FileUploadIntent:
    try:
        return FileUploadIntent.model_validate(
            {
                "intended_business_type": intended_business_type,
                "target_knowledge_base_id": target_knowledge_base_id,
                "auto_process_requested": _parse_boolean(auto_process_requested),
            }
        )
    except ValidationError:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
        ) from None


def _mutation_response(
    request: Request,
    response: Response,
    result: FileMutationResult,
) -> SuccessResponse[FileListItemData]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[FileListItemData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "",
    status_code=202,
    operation_id="upload_file_v1",
    summary="上传单个文件",
    response_model=SuccessResponse[FileUploadData],
    responses=_ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["file", "intended_business_type"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "intended_business_type": {
                                "type": "string",
                                "enum": [
                                    "contract",
                                    "supplementary_agreement",
                                    "invoice",
                                    "policy",
                                ],
                            },
                            "auto_process_requested": {
                                "type": "string",
                                "enum": ["true", "false"],
                                "default": "true",
                            },
                            "target_knowledge_base_id": {
                                "type": "string",
                                "format": "uuid",
                            },
                        },
                    }
                }
            },
        }
    },
)
def upload_file(
    request: Request,
    response: Response,
    query: Annotated[FileWriteQuery, Query()],
    actor: UploadActor,
    service: FileIntakeServiceDependency,
    idempotency_key: IdempotencyKey,
    parts: StrictFileUploadDependency,
) -> SuccessResponse[FileUploadData]:
    del query
    intent = _parse_intent(
        parts.intended_business_type,
        parts.auto_process_requested,
        parts.target_knowledge_base_id,
    )
    if parts.upload.filename is None or parts.upload.content_type is None:
        raise AppError(status_code=422, code="VALIDATION_ERROR", message="请求参数不符合约束")
    result = service.upload(
        actor,
        intent,
        file_name=parts.upload.filename,
        declared_mime=parts.upload.content_type,
        stream=parts.upload.file,
        idempotency_key=idempotency_key,
        trace_id=UUID(request.state.trace_id),
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[FileUploadData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/batch",
    status_code=207,
    operation_id="upload_file_batch_v1",
    summary="批量上传文件并逐项返回结果",
    response_model=SuccessResponse[FileBatchUploadData],
    responses=_ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["files", "intended_business_type"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 100,
                                "items": {"type": "string", "format": "binary"},
                            },
                            "intended_business_type": {
                                "type": "string",
                                "enum": [
                                    "contract",
                                    "supplementary_agreement",
                                    "invoice",
                                    "policy",
                                ],
                            },
                            "auto_process_requested": {
                                "type": "string",
                                "enum": ["true", "false"],
                                "default": "true",
                            },
                            "target_knowledge_base_id": {
                                "type": "string",
                                "format": "uuid",
                            },
                        },
                    }
                }
            },
        }
    },
)
def upload_file_batch(
    request: Request,
    response: Response,
    query: Annotated[FileWriteQuery, Query()],
    actor: UploadActor,
    service: FileIntakeServiceDependency,
    idempotency_key: IdempotencyKey,
    parts: StrictFileBatchUploadDependency,
) -> SuccessResponse[FileBatchUploadData]:
    del query
    intent = _parse_intent(
        parts.intended_business_type,
        parts.auto_process_requested,
        parts.target_knowledge_base_id,
    )
    data = service.upload_batch(
        actor,
        intent,
        tuple(
            FileBatchUploadInput(
                file_name=upload.filename or "",
                declared_mime=upload.content_type or "",
                stream=upload.file,
            )
            for upload in parts.uploads
        ),
        idempotency_key=idempotency_key,
        trace_id=UUID(request.state.trace_id),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[FileBatchUploadData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "",
    operation_id="list_files_v1",
    summary="读取文件列表",
    response_model=SuccessResponse[FileListData],
    responses=_ERROR_RESPONSES,
)
def list_files(
    query: Annotated[FileListQuery, Query()],
    request: Request,
    response: Response,
    actor: ReadActor,
    service: FileQueryServiceDependency,
) -> SuccessResponse[FileListData]:
    data = service.list_page(actor.organization_id, query.cursor, query.page_size)
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[FileListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.get(
    "/{file_id}",
    operation_id="get_file_v1",
    summary="读取文件详情",
    response_model=SuccessResponse[FileListItemData],
    responses=_ERROR_RESPONSES,
)
def get_file(
    file_id: CanonicalFileId,
    query: Annotated[FileWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: ReadActor,
    service: FileQueryServiceDependency,
) -> SuccessResponse[FileListItemData]:
    del query
    data = service.get(actor.organization_id, UUID(file_id))
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[FileListItemData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


def _preview_response(file_id: UUID, result: FilePreviewResult) -> Response:
    extension = PurePath(result.filename).suffix.lower()
    fallback_name = f"file-{file_id}{extension}"
    encoded_name = quote(result.filename, safe="")
    return Response(
        content=result.content,
        media_type=result.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": (
                f"inline; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded_name}"
            ),
            "ETag": f'"{result.sha256}"',
            "X-Content-Type-Options": "nosniff",
            "X-File-Id": str(file_id),
            "X-File-Status": result.status,
        },
    )


@router.get(
    "/{file_id}/preview",
    operation_id="preview_file_original_v1",
    summary="预览已通过安全扫描的原文件",
    response_class=Response,
    responses=_ERROR_RESPONSES,
)
def preview_file_original(
    file_id: CanonicalFileId,
    request: Request,
    actor: ReadActor,
    service: FileManagementServiceDependency,
) -> Response:
    identity = UUID(file_id)
    return _preview_response(
        identity,
        service.preview_original(actor, identity, UUID(request.state.trace_id)),
    )


@router.get(
    "/{file_id}/text-preview",
    operation_id="preview_file_text_v1",
    summary="读取活动 Markdown 文本预览",
    response_model=SuccessResponse[FileTextPreviewData],
    responses=_ERROR_RESPONSES,
)
def preview_file_text(
    file_id: CanonicalFileId,
    request: Request,
    response: Response,
    actor: ReadActor,
    service: FileManagementServiceDependency,
    max_chars: Annotated[int, Query(ge=1000, le=200_000)] = 100_000,
) -> SuccessResponse[FileTextPreviewData]:
    data = service.text_preview(
        actor,
        UUID(file_id),
        max_chars,
        UUID(request.state.trace_id),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[FileTextPreviewData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "/{file_id}/archive",
    operation_id="archive_file_v1",
    summary="不可逆归档已存储文件",
    response_model=SuccessResponse[FileListItemData],
    responses=_ERROR_RESPONSES,
)
def archive_file(
    file_id: CanonicalFileId,
    payload: FileArchiveRequest,
    request: Request,
    response: Response,
    actor: ManageActor,
    service: FileManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[FileListItemData]:
    return _mutation_response(
        request,
        response,
        service.archive(
            actor,
            UUID(file_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


@router.post(
    "/{file_id}/retry",
    operation_id="retry_file_job_v1",
    summary="显式重试失败的文件处理任务",
    response_model=SuccessResponse[FileListItemData],
    responses=_ERROR_RESPONSES,
)
def retry_file_job(
    file_id: CanonicalFileId,
    payload: FileRetryRequest,
    request: Request,
    response: Response,
    actor: ManageActor,
    service: FileManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[FileListItemData]:
    return _mutation_response(
        request,
        response,
        service.retry(
            actor,
            UUID(file_id),
            payload,
            idempotency_key,
            UUID(request.state.trace_id),
        ),
    )


__all__ = ["router"]
