"""文件上传与读取应用服务依赖边界。"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from starlette.datastructures import UploadFile

from app.core.errors import AppError
from app.services.file_intake import FileIntakeService, FileQueryService
from app.services.file_management import FileManagementService

_UPLOAD_PARTS = frozenset(
    {
        "file",
        "intended_business_type",
        "auto_process_requested",
        "target_knowledge_base_id",
    }
)
_BATCH_UPLOAD_PARTS = frozenset(
    {
        "files",
        "intended_business_type",
        "auto_process_requested",
        "target_knowledge_base_id",
    }
)


@dataclass(frozen=True, slots=True)
class StrictFileUploadParts:
    upload: UploadFile
    intended_business_type: str
    auto_process_requested: str
    target_knowledge_base_id: str | None


@dataclass(frozen=True, slots=True)
class StrictFileBatchUploadParts:
    uploads: tuple[UploadFile, ...]
    intended_business_type: str
    auto_process_requested: str
    target_knowledge_base_id: str | None


def _invalid_multipart() -> AppError:
    return AppError(status_code=422, code="VALIDATION_ERROR", message="请求参数不符合约束")


async def parse_strict_file_upload(request: Request) -> StrictFileUploadParts:
    """只接受合同冻结的四个 multipart part，拒绝未知或重复 part。"""

    try:
        form = await request.form(max_files=1, max_fields=3, max_part_size=64 * 1024)
    except Exception:
        raise _invalid_multipart() from None
    values: dict[str, list[object]] = {}
    for name, value in form.multi_items():
        if name not in _UPLOAD_PARTS:
            raise _invalid_multipart()
        values.setdefault(name, []).append(value)
    if any(len(items) != 1 for items in values.values()):
        raise _invalid_multipart()
    if "file" not in values or "intended_business_type" not in values:
        raise _invalid_multipart()

    upload = values["file"][0]
    intended_business_type = values["intended_business_type"][0]
    auto_process_requested = values.get("auto_process_requested", ["true"])[0]
    target_knowledge_base_id = values.get("target_knowledge_base_id", [None])[0]
    if (
        not isinstance(upload, UploadFile)
        or type(intended_business_type) is not str
        or type(auto_process_requested) is not str
        or (target_knowledge_base_id is not None and type(target_knowledge_base_id) is not str)
    ):
        raise _invalid_multipart()
    return StrictFileUploadParts(
        upload=upload,
        intended_business_type=intended_business_type,
        auto_process_requested=auto_process_requested,
        target_knowledge_base_id=target_knowledge_base_id,
    )


async def parse_strict_file_batch_upload(request: Request) -> StrictFileBatchUploadParts:
    """允许重复 files part，但元数据只能各出现一次。"""

    settings = getattr(request.app.state, "settings", None)
    max_files = getattr(settings, "max_batch_file_count", None)
    if type(max_files) is not int or not 1 <= max_files <= 100:
        raise AppError(
            status_code=503,
            code="FILE_INTAKE_NOT_CONFIGURED",
            message="文件上传服务尚未配置",
        )
    try:
        form = await request.form(max_files=max_files, max_fields=3, max_part_size=64 * 1024)
    except Exception as error:
        detail = str(getattr(error, "detail", error))
        if "Too many files" in detail:
            raise AppError(
                status_code=413,
                code="BATCH_LIMIT_EXCEEDED",
                message="超过单批文件数",
            ) from None
        raise _invalid_multipart() from None
    uploads: list[UploadFile] = []
    values: dict[str, list[object]] = {}
    for name, value in form.multi_items():
        if name not in _BATCH_UPLOAD_PARTS:
            raise _invalid_multipart()
        if name == "files":
            if not isinstance(value, UploadFile):
                raise _invalid_multipart()
            uploads.append(value)
        else:
            values.setdefault(name, []).append(value)
    if not uploads or "intended_business_type" not in values:
        raise _invalid_multipart()
    if any(len(items) != 1 for items in values.values()):
        raise _invalid_multipart()

    intended_business_type = values["intended_business_type"][0]
    auto_process_requested = values.get("auto_process_requested", ["true"])[0]
    target_knowledge_base_id = values.get("target_knowledge_base_id", [None])[0]
    if (
        type(intended_business_type) is not str
        or type(auto_process_requested) is not str
        or (target_knowledge_base_id is not None and type(target_knowledge_base_id) is not str)
    ):
        raise _invalid_multipart()
    return StrictFileBatchUploadParts(
        uploads=tuple(uploads),
        intended_business_type=intended_business_type,
        auto_process_requested=auto_process_requested,
        target_knowledge_base_id=target_knowledge_base_id,
    )


def get_file_intake_service(request: Request) -> FileIntakeService:
    service = getattr(request.app.state, "file_intake_service", None)
    if not isinstance(service, FileIntakeService):
        raise AppError(
            status_code=503,
            code="FILE_INTAKE_NOT_CONFIGURED",
            message="文件上传服务尚未配置",
        )
    return service


def get_file_query_service(request: Request) -> FileQueryService:
    service = getattr(request.app.state, "file_query_service", None)
    if not isinstance(service, FileQueryService):
        raise AppError(
            status_code=503,
            code="FILE_QUERY_NOT_CONFIGURED",
            message="文件查询服务尚未配置",
        )
    return service


def get_file_management_service(request: Request) -> FileManagementService:
    service = getattr(request.app.state, "file_management_service", None)
    if not isinstance(service, FileManagementService):
        raise AppError(
            status_code=503,
            code="FILE_MANAGEMENT_NOT_CONFIGURED",
            message="文件管理服务尚未配置",
        )
    return service


FileIntakeServiceDependency = Annotated[
    FileIntakeService,
    Depends(get_file_intake_service),
]
FileQueryServiceDependency = Annotated[
    FileQueryService,
    Depends(get_file_query_service),
]
FileManagementServiceDependency = Annotated[
    FileManagementService,
    Depends(get_file_management_service),
]
StrictFileUploadDependency = Annotated[
    StrictFileUploadParts,
    Depends(parse_strict_file_upload),
]
StrictFileBatchUploadDependency = Annotated[
    StrictFileBatchUploadParts,
    Depends(parse_strict_file_batch_upload),
]

__all__ = [
    "FileIntakeServiceDependency",
    "FileManagementServiceDependency",
    "FileQueryServiceDependency",
    "StrictFileBatchUploadDependency",
    "StrictFileBatchUploadParts",
    "StrictFileUploadDependency",
    "StrictFileUploadParts",
    "get_file_intake_service",
    "get_file_management_service",
    "get_file_query_service",
    "parse_strict_file_upload",
    "parse_strict_file_batch_upload",
]
