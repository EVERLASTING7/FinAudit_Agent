"""文件预览、归档与显式失败重试用例。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, Protocol, cast
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.minio_original_storage import (
    OriginalObjectLocator,
    OriginalStorageError,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.models.reliability import IdempotencyRecord
from app.repositories.file_intake import FileIntakeRepository, FileJobView
from app.repositories.job_runtime import JobRuntimeRepository
from app.repositories.operation_log import OperationLogRepository
from app.schemas.files import (
    FileArchiveRequest,
    FileListItemData,
    FileRetryRequest,
    FileTextPreviewData,
)
from app.services.auth import AuthenticatedActor
from app.services.file_intake import project_file_list_item
from app.workers.file_handler_registry import FileJobType, load_file_handler
from app.workers.handler_registry import HandlerRegistryError

_IDEMPOTENCY_TTL = timedelta(hours=24)
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")


class OriginalArtifactReader(Protocol):
    def read_verified(
        self,
        locator: OriginalObjectLocator,
        *,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class FileMutationResult:
    data: FileListItemData
    replayed: bool


@dataclass(frozen=True, slots=True)
class FilePreviewResult:
    content: bytes
    filename: str
    mime_type: str
    sha256: str
    status: Literal["stored", "archived"]


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_manage(actor: AuthenticatedActor) -> None:
    if "files.manage" not in actor.permissions:
        raise _error(403, "FILE_MANAGE_FORBIDDEN", "无权执行文件管理操作")


def _require_idempotency_key(value: str) -> None:
    if type(value) is not str or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise _error(422, "VALIDATION_ERROR", "请求参数不符合约束")


class FileManagementService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        storage: OriginalArtifactReader,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._max_size_bytes = settings.max_upload_size_mb * 1024 * 1024

    def preview_original(
        self,
        actor: AuthenticatedActor,
        file_id: UUID,
        trace_id: UUID,
    ) -> FilePreviewResult:
        with self._session_factory() as session:
            view = FileIntakeRepository(session).read_file(actor.organization_id, file_id)
            if view is None:
                raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
            source = view.file
            if (
                source.status not in {"stored", "archived"}
                or source.security_scan_status != "clean"
                or source.original_minio_bucket is None
                or source.original_minio_object_key is None
            ):
                raise _error(409, "FILE_PREVIEW_NOT_READY", "文件原文尚未就绪")
            locator = OriginalObjectLocator(
                source.original_minio_bucket,
                source.original_minio_object_key,
            )
            size = source.size_bytes
            sha256 = source.sha256
            mime_type = source.detected_mime_type
            filename = source.original_name
            row_version = source.row_version
            status = cast(Literal["stored", "archived"], source.status)
        try:
            content = self._storage.read_verified(
                locator,
                expected_size=size,
                expected_sha256=sha256,
                max_bytes=self._max_size_bytes,
            )
        except OriginalStorageError:
            raise _error(503, "FILE_PREVIEW_UNAVAILABLE", "文件原文暂不可用") from None

        with self._session_factory.begin() as session:
            repository = FileIntakeRepository(session)
            current = repository.lock_file(actor.organization_id, file_id)
            if (
                current is None
                or current.status != status
                or current.security_scan_status != "clean"
                or current.original_minio_bucket != locator.bucket_name
                or current.original_minio_object_key != locator.object_key
                or current.size_bytes != size
                or current.sha256 != sha256
                or current.detected_mime_type != mime_type
                or current.row_version != row_version
            ):
                raise _error(409, "FILE_STATE_CHANGED", "文件状态已变化，请重试")
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code="files.previewed",
                outcome="succeeded",
                resource_type="file",
                resource_id=current.id,
                trace_id=trace_id,
                change_summary={
                    "format": "original",
                    "status": current.status,
                    "row_version": str(current.row_version),
                },
            )
        return FilePreviewResult(
            content=content,
            filename=filename,
            mime_type=mime_type,
            sha256=sha256,
            status=status,
        )

    def text_preview(
        self,
        actor: AuthenticatedActor,
        file_id: UUID,
        max_chars: int,
        trace_id: UUID,
    ) -> FileTextPreviewData:
        if type(max_chars) is not int or not 1000 <= max_chars <= 200_000:
            raise _error(422, "VALIDATION_ERROR", "请求参数不符合约束")
        with self._session_factory.begin() as session:
            repository = FileIntakeRepository(session)
            source = repository.lock_file(actor.organization_id, file_id)
            if source is None:
                raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
            if (
                source.status not in {"stored", "archived"}
                or source.security_scan_status != "clean"
            ):
                raise _error(409, "FILE_TEXT_PREVIEW_NOT_READY", "解析文本尚未就绪")
            markdown = repository.active_markdown(actor.organization_id, file_id)
            if markdown is None:
                raise _error(409, "FILE_TEXT_PREVIEW_NOT_READY", "解析文本尚未就绪")
            text = markdown.markdown_text[:max_chars]
            data = FileTextPreviewData(
                file_id=file_id,
                markdown_version_id=markdown.id,
                content_sha256=markdown.content_sha256,
                markdown_text=text,
                char_count=markdown.char_count,
                truncated=len(text) < markdown.char_count,
            )
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code="files.previewed",
                outcome="succeeded",
                resource_type="file",
                resource_id=source.id,
                trace_id=trace_id,
                change_summary={
                    "format": "markdown",
                    "status": source.status,
                    "row_version": str(source.row_version),
                },
            )
            return data

    def archive(
        self,
        actor: AuthenticatedActor,
        file_id: UUID,
        payload: FileArchiveRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> FileMutationResult:
        _require_manage(actor)
        _require_idempotency_key(idempotency_key)
        path = f"/api/v1/files/{file_id}/archive"
        digest = _canonical_hash(
            {
                "method": "POST",
                "path": path,
                "reason": payload.reason,
                "row_version": payload.row_version,
            }
        )
        with self._session_factory.begin() as session:
            repository, idempotency, replayed = self._claim(
                session,
                actor,
                idempotency_key,
                path,
                digest,
            )
            if replayed:
                return FileMutationResult(self._replay(idempotency), True)
            source = repository.lock_file(actor.organization_id, file_id)
            if source is None:
                raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
            if source.row_version != int(payload.row_version):
                raise _error(409, "ROW_VERSION_CONFLICT", "文件版本已变化")
            if source.status != "stored" or source.security_scan_status != "clean":
                raise _error(409, "FILE_STATE_CONFLICT", "当前文件状态不能归档")
            job = repository.job_for_file(source.id, lock=True)
            if job is None:
                raise RuntimeError("file has no authoritative intake job")
            now = repository.database_now()
            source.status = "archived"
            source.archived_at = now
            source.row_version += 1
            source.updated_at = now
            source.updated_by = actor.user_id
            repository.flush()
            data = project_file_list_item(FileJobView(source, job))
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code="files.archived",
                outcome="succeeded",
                resource_type="file",
                resource_id=source.id,
                trace_id=trace_id,
                change_summary={
                    "reason_sha256": hashlib.sha256(payload.reason.encode("utf-8")).hexdigest(),
                    "status": source.status,
                    "row_version": data.row_version,
                },
            )
            self._complete(idempotency, data)
            return FileMutationResult(data, False)

    def retry(
        self,
        actor: AuthenticatedActor,
        file_id: UUID,
        payload: FileRetryRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> FileMutationResult:
        _require_manage(actor)
        _require_idempotency_key(idempotency_key)
        path = f"/api/v1/files/{file_id}/retry"
        digest = _canonical_hash(
            {
                "job_id": str(payload.job_id),
                "method": "POST",
                "path": path,
                "reason": payload.reason,
                "row_version": payload.row_version,
            }
        )
        with self._session_factory.begin() as session:
            repository, idempotency, replayed = self._claim(
                session,
                actor,
                idempotency_key,
                path,
                digest,
            )
            if replayed:
                return FileMutationResult(self._replay(idempotency), True)
            source = repository.lock_file(actor.organization_id, file_id)
            if source is None:
                raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
            if source.row_version != int(payload.row_version):
                raise _error(409, "ROW_VERSION_CONFLICT", "文件版本已变化")
            job = repository.job_for_file(source.id, lock=True)
            if job is None or job.id != payload.job_id:
                raise _error(409, "FILE_JOB_CONFLICT", "文件处理任务已变化")
            if (
                job.job_type not in {"file_scan", "file_process"}
                or job.status != "failed"
                or job.stage is None
                or job.next_retry_at is None
                or job.attempt_no >= job.max_attempts
            ):
                raise _error(409, "FILE_JOB_NOT_RETRYABLE", "文件处理任务当前不可重试")
            try:
                handler = load_file_handler(cast(FileJobType, job.job_type))
                handler.validate_input(job.input_json)
            except (HandlerRegistryError, ValueError):
                raise _error(409, "FILE_JOB_NOT_RETRYABLE", "文件处理任务当前不可重试") from None
            if (
                job.handler_registry_version != handler.registry_version
                or job.handler_registry_hash != handler.registry_hash
                or not any(
                    scope.start_step_code == job.stage for scope in handler.handler.retry_scopes
                )
            ):
                raise _error(409, "FILE_JOB_NOT_RETRYABLE", "文件处理任务当前不可重试")
            start_step = job.stage
            if not JobRuntimeRepository(session).requeue_failed_file_job(
                job_id=job.id,
                start_step_code=start_step,
                allow_before_next_retry=True,
            ):
                raise _error(409, "FILE_JOB_NOT_RETRYABLE", "文件处理任务当前不可重试")
            refreshed = repository.job_for_file(source.id, lock=True)
            if refreshed is None or refreshed.id != job.id or refreshed.status != "queued":
                raise RuntimeError("requeued file job projection is inconsistent")
            data = project_file_list_item(FileJobView(source, refreshed))
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code="files.retry_queued",
                outcome="succeeded",
                resource_type="file",
                resource_id=source.id,
                trace_id=trace_id,
                change_summary={
                    "job_id": str(refreshed.id),
                    "reason_sha256": hashlib.sha256(payload.reason.encode("utf-8")).hexdigest(),
                    "stage": start_step,
                    "row_version": data.row_version,
                },
            )
            self._complete(idempotency, data)
            return FileMutationResult(data, False)

    @staticmethod
    def _claim(
        session: Session,
        actor: AuthenticatedActor,
        idempotency_key: str,
        path: str,
        digest: str,
    ) -> tuple[FileIntakeRepository, IdempotencyRecord, bool]:
        repository = FileIntakeRepository(session)
        repository.acquire_idempotency_lock(
            actor.organization_id,
            actor.user_id,
            idempotency_key,
        )
        if repository.lock_active_organization(actor.organization_id) is None:
            raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
        now = repository.database_now()
        idempotency, replayed, conflict = repository.claim_idempotency(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            idempotency_key=idempotency_key,
            request_method="POST",
            request_path=path,
            request_hash=digest,
            now=now,
            expires_at=now + _IDEMPOTENCY_TTL,
        )
        if conflict:
            raise _error(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
        return repository, idempotency, replayed

    @staticmethod
    def _replay(record: IdempotencyRecord) -> FileListItemData:
        if record.response_status != 200 or record.response_body_json is None:
            raise RuntimeError("file management idempotency record is incomplete")
        return FileListItemData.model_validate_json(_canonical_json(record.response_body_json))

    @staticmethod
    def _complete(record: IdempotencyRecord, data: FileListItemData) -> None:
        record.response_status = 200
        record.response_body_json = data.model_dump(mode="json")
        record.resource_type = "file"
        record.resource_id = data.file_id


__all__ = [
    "FileManagementService",
    "FileMutationResult",
    "FilePreviewResult",
    "OriginalArtifactReader",
]
