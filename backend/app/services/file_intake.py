"""file-upload-intake-v1 的上传事务、去重、幂等与读取用例。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.minio_quarantine import (
    MinioQuarantineAdapter,
    QuarantineCleanupRequiredError,
    QuarantineObject,
    QuarantineStorageError,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.models.documents import FileRecord
from app.models.reliability import (
    JOB_LEASE_POLICY_HASH,
    JOB_LEASE_POLICY_VERSION,
    JOB_RETRY_POLICY_HASH,
    JOB_RETRY_POLICY_VERSION,
    AsyncJob,
    IdempotencyRecord,
    OutboxEvent,
)
from app.repositories.file_intake import FileIntakeRepository, FileJobView
from app.repositories.operation_log import OperationLogRepository
from app.schemas.files import (
    FileBatchErrorData,
    FileBatchItemData,
    FileBatchUploadData,
    FileListData,
    FileListItemData,
    FileStatus,
    FileUploadData,
    FileUploadIntent,
    IntendedBusinessType,
    SecurityScanStatus,
)
from app.services.auth import AuthenticatedActor
from app.services.file_service import (
    prepare_quarantine_intake,
    require_file_upload_scope,
    validate_file_batch_count,
)
from app.services.job_projection import project_job_action
from app.workers.file_handler_registry import (
    FILE_HANDLER_REGISTRY_HASH,
    FILE_HANDLER_REGISTRY_VERSION,
    FILE_INPUT_SCHEMA_VERSION,
    load_file_handler,
)

_IDEMPOTENCY_TTL = timedelta(hours=24)
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_CURSOR_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_SAFE_FILE_NAME = re.compile(r"^[^/\\\x00-\x1f\x7f]{1,500}$")


class FileUploadResult:
    __slots__ = ("data", "replayed")

    def __init__(self, data: FileUploadData, replayed: bool) -> None:
        self.data = data
        self.replayed = replayed


@dataclass(frozen=True, slots=True)
class FileBatchUploadInput:
    file_name: str
    declared_mime: str
    stream: BinaryIO


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _validate_idempotency_key(value: str) -> None:
    if type(value) is not str or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise _error(422, "VALIDATION_ERROR", "请求参数不符合约束")


def sanitize_file_name(value: str) -> str:
    if (
        type(value) is not str
        or _SAFE_FILE_NAME.fullmatch(value) is None
        or value != value.strip()
        or PurePath(value).name != value
        or value in {".", ".."}
    ):
        raise _error(422, "VALIDATION_ERROR", "请求参数不符合约束")
    return value


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _request_hash(
    *,
    file_name: str,
    declared_mime: str,
    size_bytes: int,
    sha256: str,
    intent: FileUploadIntent,
) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "auto_process_requested": intent.auto_process_requested,
                "declared_mime": declared_mime,
                "file_name": file_name,
                "intended_business_type": intent.intended_business_type.value,
                "sha256": sha256,
                "size_bytes": size_bytes,
                "target_knowledge_base_id": (
                    str(intent.target_knowledge_base_id)
                    if intent.target_knowledge_base_id is not None
                    else None
                ),
            }
        )
    ).hexdigest()


def _job_input(file: FileRecord, intent: FileUploadIntent, scope: str) -> dict[str, object]:
    return {
        "auto_process_requested": intent.auto_process_requested,
        "file_id": str(file.id),
        "intended_business_type": intent.intended_business_type.value,
        "processing_scope": scope,
        "target_knowledge_base_id": (
            str(intent.target_knowledge_base_id)
            if intent.target_knowledge_base_id is not None
            else None
        ),
    }


def _scope(job: AsyncJob) -> Literal["full", "scan_only"]:
    scope = job.input_json.get("processing_scope")
    if scope not in {"full", "scan_only"}:
        raise RuntimeError("file job has invalid processing scope")
    return scope


def _upload_projection(file: FileRecord, job: AsyncJob, *, reused: bool) -> FileUploadData:
    return FileUploadData(
        file_id=file.id,
        original_name=file.original_name,
        status=FileStatus(file.status),
        security_scan_status=SecurityScanStatus(file.security_scan_status),
        reused=reused,
        intended_business_type=IntendedBusinessType(file.intended_business_type),
        target_knowledge_base_id=file.target_knowledge_base_id,
        auto_process_requested=file.auto_process_requested,
        job_id=job.id,
        job_status=cast(
            Literal[
                "queued",
                "running",
                "cancel_requested",
                "succeeded",
                "failed",
                "cancelled",
            ],
            job.status,
        ),
        job_scope=_scope(job),
        next_stage="scan",
        row_version=str(file.row_version),
    )


def _list_projection(view: FileJobView, database_now: datetime) -> FileListItemData:
    return FileListItemData(
        **_upload_projection(view.file, view.job, reused=False).model_dump(),
        size_bytes=str(view.file.size_bytes),
        created_at=view.file.created_at,
        job=project_job_action(view.job, database_now),
    )


def project_file_list_item(view: FileJobView, database_now: datetime) -> FileListItemData:
    return _list_projection(view, database_now)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise RuntimeError("file timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _encode_cursor(created_at: datetime, identity: UUID) -> str:
    raw = _canonical_json({"created_at": _utc_text(created_at), "id": str(identity), "v": 1})
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _invalid_cursor() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=[{"field": "query.cursor", "reason": "invalid"}],
    )


def _decode_cursor(value: str) -> tuple[datetime, UUID]:
    if not value or len(value) > 256 or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise _invalid_cursor()
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != value:
            raise ValueError
        payload = json.loads(raw.decode("utf-8"))
        if type(payload) is not dict or set(payload) != {"created_at", "id", "v"}:
            raise ValueError
        created_at_text = payload["created_at"]
        identity_text = payload["id"]
        if (
            type(payload["v"]) is not int
            or payload["v"] != 1
            or type(created_at_text) is not str
            or _CURSOR_TIMESTAMP.fullmatch(created_at_text) is None
            or type(identity_text) is not str
        ):
            raise ValueError
        created_at = datetime.fromisoformat(created_at_text.replace("Z", "+00:00"))
        identity = UUID(identity_text)
        if str(identity) != identity_text or _encode_cursor(created_at, identity) != value:
            raise ValueError
        return created_at, identity
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError):
        raise _invalid_cursor() from None


class FileIntakeService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        storage: MinioQuarantineAdapter,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._max_size_bytes = settings.max_upload_size_mb * 1024 * 1024
        self._max_batch_file_count = settings.max_batch_file_count

    def upload_batch(
        self,
        actor: AuthenticatedActor,
        intent: FileUploadIntent,
        items: tuple[FileBatchUploadInput, ...],
        *,
        idempotency_key: str,
        trace_id: UUID,
    ) -> FileBatchUploadData:
        require_file_upload_scope(actor, intent.intended_business_type)
        _validate_idempotency_key(idempotency_key)
        validate_file_batch_count(
            len(items),
            max_batch_file_count=self._max_batch_file_count,
        )
        results: list[FileBatchItemData] = []
        for index, item in enumerate(items):
            child_key = (
                "batch."
                + hashlib.sha256(
                    _canonical_json({"batch_key": idempotency_key, "index": index})
                ).hexdigest()
            )
            try:
                result = self.upload(
                    actor,
                    intent,
                    file_name=item.file_name,
                    declared_mime=item.declared_mime,
                    stream=item.stream,
                    idempotency_key=child_key,
                    trace_id=trace_id,
                )
            except AppError as error:
                try:
                    display_name = sanitize_file_name(item.file_name)
                except AppError:
                    display_name = f"file-{index + 1}"
                results.append(
                    FileBatchItemData(
                        index=index,
                        original_name=display_name,
                        outcome="rejected",
                        http_status=error.status_code,
                        replayed=False,
                        data=None,
                        error=FileBatchErrorData(code=error.code, message=error.message),
                    )
                )
                continue
            results.append(
                FileBatchItemData(
                    index=index,
                    original_name=result.data.original_name,
                    outcome="accepted",
                    http_status=202,
                    replayed=result.replayed,
                    data=result.data,
                    error=None,
                )
            )
        accepted_count = sum(item.outcome == "accepted" for item in results)
        return FileBatchUploadData(
            items=tuple(results),
            accepted_count=accepted_count,
            rejected_count=len(results) - accepted_count,
        )

    def upload(
        self,
        actor: AuthenticatedActor,
        intent: FileUploadIntent,
        *,
        file_name: str,
        declared_mime: str,
        stream: BinaryIO,
        idempotency_key: str,
        trace_id: UUID,
    ) -> FileUploadResult:
        require_file_upload_scope(actor, intent.intended_business_type)
        _validate_idempotency_key(idempotency_key)
        safe_name = sanitize_file_name(file_name)
        with SpooledTemporaryFile(
            max_size=min(self._max_size_bytes, 1024 * 1024),
            mode="w+b",
        ) as spool:
            binary_spool = cast(BinaryIO, spool)
            while True:
                chunk = stream.read(1024 * 1024)
                if type(chunk) is not bytes:
                    raise TypeError("upload stream must return bytes")
                if not chunk:
                    break
                spool.write(chunk)
                if spool.tell() > self._max_size_bytes:
                    raise _error(413, "FILE_TOO_LARGE", "上传文件超过允许大小")
            spool.seek(0)
            facts = prepare_quarantine_intake(
                binary_spool,
                file_name=safe_name,
                declared_mime=declared_mime,
                max_size_bytes=self._max_size_bytes,
            )
            digest = _request_hash(
                file_name=safe_name,
                declared_mime=facts.declared_mime,
                size_bytes=facts.size_bytes,
                sha256=facts.sha256,
                intent=intent,
            )
            return self._persist(
                actor,
                intent,
                safe_name,
                binary_spool,
                facts.extension,
                facts.declared_mime,
                facts.detected_mime,
                facts.size_bytes,
                facts.sha256,
                idempotency_key,
                digest,
                trace_id,
            )

    def _persist(
        self,
        actor: AuthenticatedActor,
        intent: FileUploadIntent,
        file_name: str,
        stream: BinaryIO,
        extension: str,
        declared_mime: str,
        detected_mime: str,
        size_bytes: int,
        sha256: str,
        idempotency_key: str,
        request_hash: str,
        trace_id: UUID,
    ) -> FileUploadResult:
        locator: QuarantineObject | None = None
        try:
            with self._session_factory.begin() as session:
                repository = FileIntakeRepository(session)
                repository.acquire_idempotency_lock(
                    actor.organization_id, actor.user_id, idempotency_key
                )
                if repository.lock_active_organization(actor.organization_id) is None:
                    raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
                now = repository.database_now()
                idempotency, replayed, conflict = repository.claim_idempotency(
                    organization_id=actor.organization_id,
                    actor_id=actor.user_id,
                    idempotency_key=idempotency_key,
                    request_method="POST",
                    request_path="/api/v1/files",
                    request_hash=request_hash,
                    now=now,
                    expires_at=now + _IDEMPOTENCY_TTL,
                )
                if conflict:
                    raise _error(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if replayed:
                    assert idempotency.response_body_json is not None
                    encoded = json.dumps(
                        idempotency.response_body_json,
                        ensure_ascii=True,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    return FileUploadResult(FileUploadData.model_validate_json(encoded), True)
                if intent.target_knowledge_base_id is not None:
                    knowledge_base = repository.lock_active_knowledge_base(
                        actor.organization_id, intent.target_knowledge_base_id
                    )
                    if knowledge_base is None:
                        raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
                    if knowledge_base.status != "active":
                        raise _error(409, "KNOWLEDGE_BASE_NOT_ACTIVE", "知识库未处于活动状态")

                repository.acquire_content_lock(actor.organization_id, sha256, size_bytes)
                duplicate = repository.lock_duplicate(actor.organization_id, sha256, size_bytes)
                if duplicate is not None:
                    if duplicate.status == "archived":
                        raise _error(409, "FILE_ARCHIVED_DUPLICATE", "归档文件内容已存在")
                    if duplicate.status == "rejected":
                        raise _error(409, "FILE_REJECTED_DUPLICATE", "拒绝文件内容已存在")
                    if (
                        duplicate.intended_business_type != intent.intended_business_type.value
                        or duplicate.target_knowledge_base_id != intent.target_knowledge_base_id
                        or duplicate.auto_process_requested != intent.auto_process_requested
                    ):
                        raise _error(409, "FILE_CLASSIFICATION_CONFLICT", "文件分类与既有事实冲突")
                    job = repository.job_for_file(duplicate.id, lock=True)
                    if job is None:
                        raise RuntimeError("duplicate file has no job")
                    data = _upload_projection(duplicate, job, reused=True)
                    self._complete_idempotency(idempotency, data)
                    return FileUploadResult(data, False)

                file_id = uuid4()
                try:
                    locator = self._storage.put_quarantine(
                        organization_id=actor.organization_id,
                        file_id=file_id,
                        sha256=sha256,
                        data=stream,
                        length=size_bytes,
                        content_type=detected_mime,
                    )
                except QuarantineCleanupRequiredError:
                    raise _error(
                        503,
                        "FILE_STORAGE_OUTCOME_UNKNOWN",
                        "文件存储结果不确定",
                    ) from None
                except QuarantineStorageError:
                    raise _error(503, "FILE_STORAGE_UNAVAILABLE", "文件存储不可用") from None

                file = FileRecord(
                    id=file_id,
                    organization_id=actor.organization_id,
                    original_name=file_name,
                    extension=extension,
                    mime_type=declared_mime,
                    detected_mime_type=detected_mime,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    minio_bucket=locator.bucket_name,
                    minio_object_key=locator.object_key,
                    status="uploaded",
                    intended_business_type=intent.intended_business_type.value,
                    target_knowledge_base_id=intent.target_knowledge_base_id,
                    auto_process_requested=intent.auto_process_requested,
                    security_scan_status="pending",
                    uploaded_by=actor.user_id,
                    row_version=1,
                    created_at=now,
                    created_by=actor.user_id,
                    updated_at=now,
                    updated_by=actor.user_id,
                )
                repository.add(file)
                repository.flush()
                scope = "full" if intent.auto_process_requested else "scan_only"
                job_type = "file_process" if intent.auto_process_requested else "file_scan"
                input_json = _job_input(file, intent, scope)
                handler = load_file_handler(job_type)
                handler.validate_input(input_json)
                job = AsyncJob(
                    id=uuid4(),
                    organization_id=actor.organization_id,
                    job_type=job_type,
                    resource_type="file",
                    resource_id=file.id,
                    status="queued",
                    stage=None,
                    attempt_no=0,
                    max_attempts=handler.handler.max_attempts,
                    current_attempt_start_step_code="scan",
                    input_hash=hashlib.sha256(_canonical_json(input_json)).hexdigest(),
                    input_json=input_json,
                    input_schema_version=FILE_INPUT_SCHEMA_VERSION,
                    idempotency_record_id=idempotency.id,
                    handler_registry_version=handler.registry_version,
                    handler_registry_hash=handler.registry_hash,
                    retry_policy_version=JOB_RETRY_POLICY_VERSION,
                    retry_policy_hash=JOB_RETRY_POLICY_HASH,
                    lease_policy_version=JOB_LEASE_POLICY_VERSION,
                    lease_policy_hash=JOB_LEASE_POLICY_HASH,
                    row_version=1,
                    trace_id=trace_id,
                    created_by=actor.user_id,
                    created_at=now,
                )
                repository.add(job)
                repository.flush()
                repository.add(
                    OutboxEvent(
                        id=uuid4(),
                        aggregate_type="async_job",
                        aggregate_id=job.id,
                        event_id=uuid4(),
                        event_type="job.dispatch.requested",
                        event_version=1,
                        event_sequence=1,
                        # event_version 是 Outbox schema 版本；Dispatcher 再生成
                        # Celery 消息中的 event_schema_version，避免两处版本事实源。
                        payload_json={"job_id": str(job.id)},
                        status="pending",
                        attempt_count=0,
                        trace_id=trace_id,
                        created_at=now,
                    )
                )
                data = _upload_projection(file, job, reused=False)
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="files.uploaded",
                    outcome="succeeded",
                    resource_type="file",
                    resource_id=file.id,
                    trace_id=trace_id,
                    change_summary={
                        "intended_business_type": intent.intended_business_type.value,
                        "job_scope": scope,
                        "row_version": data.row_version,
                    },
                )
                self._complete_idempotency(idempotency, data)
                return FileUploadResult(data, False)
        except IntegrityError as error:
            self._compensate(locator)
            constraint = getattr(error.orig, "diag", None)
            constraint_name = getattr(constraint, "constraint_name", None)
            if constraint_name == "uq_files_content_active":
                raise _error(409, "FILE_DUPLICATE_CONFLICT", "文件内容已存在") from None
            raise
        except AppError:
            self._compensate(locator)
            raise
        except Exception:
            self._compensate(locator)
            raise

    def _compensate(self, locator: QuarantineObject | None) -> None:
        if locator is None:
            return
        try:
            self._storage.delete_quarantine(locator)
        except QuarantineStorageError:
            raise _error(
                503,
                "FILE_STORAGE_CLEANUP_REQUIRED",
                "文件存储补偿未完成",
            ) from None

    @staticmethod
    def _complete_idempotency(record: IdempotencyRecord, data: FileUploadData) -> None:
        record.response_status = 202
        record.response_body_json = data.model_dump(mode="json")
        record.resource_type = "file"
        record.resource_id = data.file_id


class FileQueryService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, organization_id: UUID, file_id: UUID) -> FileListItemData:
        with self._session_factory() as session:
            repository = FileIntakeRepository(session)
            view = repository.read_file(organization_id, file_id)
            database_now = repository.database_now()
        if view is None:
            raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
        return _list_projection(view, database_now)

    def list_page(
        self,
        organization_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> FileListData:
        cursor_time: datetime | None = None
        cursor_id: UUID | None = None
        if cursor is not None:
            cursor_time, cursor_id = _decode_cursor(cursor)
        with self._session_factory() as session:
            repository = FileIntakeRepository(session)
            views, has_more = repository.read_page(
                organization_id, page_size, cursor_time, cursor_id
            )
            database_now = repository.database_now()
        items = tuple(_list_projection(view, database_now) for view in views)
        return FileListData(
            items=items,
            page_size=page_size,
            next_cursor=(
                _encode_cursor(views[-1].file.created_at, views[-1].file.id) if has_more else None
            ),
        )


__all__ = [
    "FILE_HANDLER_REGISTRY_HASH",
    "FILE_HANDLER_REGISTRY_VERSION",
    "FileBatchUploadInput",
    "FileIntakeService",
    "FileQueryService",
    "FileUploadResult",
    "project_file_list_item",
    "sanitize_file_name",
]
