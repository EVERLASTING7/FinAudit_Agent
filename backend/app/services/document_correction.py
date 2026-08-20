"""CR-005-R2 文档结构块纠错、候选 Parse 与独立激活。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.policy import canonicalize_jcs
from app.core.errors import AppError
from app.models.document_processing import (
    DocumentAsset,
    DocumentBlock,
    DocumentPage,
    DocumentParseVersion,
)
from app.models.documents import FileRecord
from app.models.knowledge import DocumentBlockCorrection
from app.models.reliability import (
    JOB_LEASE_POLICY_HASH,
    JOB_LEASE_POLICY_VERSION,
    JOB_RETRY_POLICY_HASH,
    JOB_RETRY_POLICY_VERSION,
    AsyncJob,
    OutboxEvent,
)
from app.repositories.markdown_write import MarkdownWriteRepository
from app.repositories.operation_log import OperationLogRepository
from app.repositories.scanner_registry import ScannerRegistryRepository
from app.repositories.user_write import IdempotencyClaim, UserWriteRepository
from app.schemas.document_corrections import (
    AcceptedJobData,
    DocumentBlockCorrectionRequest,
    DocumentCorrectionAcceptedData,
    DocumentCorrectionBlockItemData,
    DocumentCorrectionBlockListData,
    DocumentParseActivationData,
    DocumentParseActivationRequest,
    SecurityRevalidationRequest,
)
from app.services.auth import AuthenticatedActor
from app.workers.file_handler_registry import load_file_handler

_IDEMPOTENCY_TTL = timedelta(hours=24)
_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$", re.ASCII)
_ROLE_MATRIX = {
    "invoice": frozenset({"finance_reviewer", "system_admin"}),
    "contract": frozenset({"finance_reviewer", "contract_admin", "system_admin"}),
    "supplementary_agreement": frozenset({"contract_admin", "system_admin"}),
    "policy": frozenset({"audit_reviewer", "system_admin"}),
}


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _validate_idempotency_key(value: str) -> None:
    if type(value) is not str or _IDEMPOTENCY_PATTERN.fullmatch(value) is None:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": "header.Idempotency-Key", "reason": "invalid"}],
        )


def _request_hash(method: str, path: str, body: dict[str, object]) -> str:
    return hashlib.sha256(
        canonicalize_jcs({"body": body, "method": method, "path": path})
    ).hexdigest()


def _invalid_cursor() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=[{"field": "query.cursor", "reason": "invalid"}],
    )


def _encode_block_cursor(
    parse_version_id: UUID,
    page_no: int,
    block_index: int,
    block_id: UUID,
) -> str:
    payload = json.dumps(
        {
            "block_id": str(block_id),
            "block_index": block_index,
            "page_no": page_no,
            "parse_version_id": str(parse_version_id),
            "v": 1,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_block_cursor(value: str) -> tuple[UUID, int, int, UUID]:
    if not value or len(value) > 256 or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise _invalid_cursor()
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
        if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
            raise ValueError("noncanonical base64url")

        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, child in pairs:
                if key in result:
                    raise ValueError("duplicate cursor key")
                result[key] = child
            return result

        payload = json.loads(decoded.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
        if type(payload) is not dict or set(payload) != {
            "block_id",
            "block_index",
            "page_no",
            "parse_version_id",
            "v",
        }:
            raise ValueError("invalid cursor object")
        if (
            type(payload["v"]) is not int
            or payload["v"] != 1
            or type(payload["page_no"]) is not int
            or payload["page_no"] < 1
            or type(payload["block_index"]) is not int
            or payload["block_index"] < 0
            or type(payload["parse_version_id"]) is not str
            or type(payload["block_id"]) is not str
        ):
            raise ValueError("invalid cursor fields")
        parse_version_id = UUID(payload["parse_version_id"])
        block_id = UUID(payload["block_id"])
        page_no = payload["page_no"]
        block_index = payload["block_index"]
        if (
            str(parse_version_id) != payload["parse_version_id"]
            or str(block_id) != payload["block_id"]
            or _encode_block_cursor(parse_version_id, page_no, block_index, block_id) != value
        ):
            raise ValueError("noncanonical cursor")
        return parse_version_id, page_no, block_index, block_id
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None


def _require_correction_scope(actor: AuthenticatedActor, file: FileRecord) -> None:
    if not {"files.manage", "system.configure"}.intersection(actor.permissions):
        raise _error(403, "AUTH_FORBIDDEN", "无权执行该操作")
    allowed_roles = _ROLE_MATRIX.get(file.intended_business_type)
    if allowed_roles is None or not allowed_roles.intersection(actor.roles):
        raise _error(403, "AUTH_FORBIDDEN", "无权执行该操作")
    if file.status != "stored" or file.security_scan_status != "clean":
        raise _error(409, "FILE_STATE_CONFLICT", "当前文件状态不能执行文档版本操作")


def _before_value(block: DocumentBlock, field_name: str) -> object:
    return cast(
        object,
        {
            "text_content": block.text_content,
            "block_type": block.block_type,
            "reading_order": block.reading_order,
            "bbox": block.bbox_json,
        }[field_name],
    )


def _validate_bbox_against_page(value: object, page: DocumentPage) -> None:
    if value is None:
        return
    bbox = cast(dict[str, int], value)
    if page.width is None or page.height is None:
        return
    if bbox["left"] + bbox["width"] > page.width or bbox["top"] + bbox["height"] > page.height:
        raise _error(422, "CORRECTION_VALUE_INVALID", "修正值不符合字段约束")


@dataclass(frozen=True, slots=True)
class DocumentCorrectionMutationResult:
    data: DocumentCorrectionAcceptedData
    replayed: bool
    status_code: int = 202


@dataclass(frozen=True, slots=True)
class DocumentActivationMutationResult:
    data: DocumentParseActivationData
    replayed: bool


@dataclass(frozen=True, slots=True)
class SecurityRevalidationMutationResult:
    data: AcceptedJobData
    replayed: bool
    status_code: int = 202


class DocumentCorrectionService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_blocks(
        self,
        actor: AuthenticatedActor,
        file_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> DocumentCorrectionBlockListData:
        cursor_values = _decode_block_cursor(cursor) if cursor is not None else None
        with self._session_factory() as session:
            file = session.execute(
                select(FileRecord)
                .where(
                    FileRecord.id == file_id,
                    FileRecord.organization_id == actor.organization_id,
                    FileRecord.deleted_at.is_(None),
                )
                .with_for_update(read=True, of=FileRecord)
            ).scalar_one_or_none()
            if file is None:
                raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
            _require_correction_scope(actor, file)
            parse_version = session.execute(
                select(DocumentParseVersion).where(
                    DocumentParseVersion.file_id == file.id,
                    DocumentParseVersion.status == "active",
                    DocumentParseVersion.archived_at.is_(None),
                )
            ).scalar_one_or_none()
            if parse_version is None:
                raise _error(409, "DOCUMENT_PARSE_NOT_READY", "文档活动解析版本尚未就绪")

            statement = (
                select(DocumentBlock, DocumentPage.page_no)
                .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
                .where(
                    DocumentBlock.parse_version_id == parse_version.id,
                    DocumentPage.parse_version_id == parse_version.id,
                    DocumentBlock.is_effective_content.is_(True),
                    DocumentBlock.text_content.is_not(None),
                )
            )
            if cursor_values is not None:
                cursor_parse_id, cursor_page_no, cursor_block_index, cursor_block_id = cursor_values
                if cursor_parse_id != parse_version.id:
                    cursor_file_id = session.scalar(
                        select(DocumentParseVersion.file_id).where(
                            DocumentParseVersion.id == cursor_parse_id
                        )
                    )
                    if cursor_file_id != file.id:
                        raise _invalid_cursor()
                    raise _error(409, "PARSE_VERSION_CHANGED", "活动解析版本已变化")
                anchor = session.execute(
                    select(DocumentBlock.id)
                    .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
                    .where(
                        DocumentBlock.id == cursor_block_id,
                        DocumentBlock.parse_version_id == parse_version.id,
                        DocumentBlock.block_index == cursor_block_index,
                        DocumentBlock.is_effective_content.is_(True),
                        DocumentBlock.text_content.is_not(None),
                        DocumentPage.parse_version_id == parse_version.id,
                        DocumentPage.page_no == cursor_page_no,
                    )
                ).scalar_one_or_none()
                if anchor is None:
                    raise _invalid_cursor()
                statement = statement.where(
                    or_(
                        DocumentPage.page_no > cursor_page_no,
                        and_(
                            DocumentPage.page_no == cursor_page_no,
                            DocumentBlock.block_index > cursor_block_index,
                        ),
                        and_(
                            DocumentPage.page_no == cursor_page_no,
                            DocumentBlock.block_index == cursor_block_index,
                            DocumentBlock.id > cursor_block_id,
                        ),
                    )
                )
            rows = tuple(
                session.execute(
                    statement.order_by(
                        DocumentPage.page_no,
                        DocumentBlock.block_index,
                        DocumentBlock.id,
                    ).limit(page_size + 1)
                ).all()
            )
            has_more = len(rows) > page_size
            page = rows[:page_size]
            items = tuple(
                DocumentCorrectionBlockItemData.model_validate(
                    {
                        "block_id": block.id,
                        "page_no": page_no,
                        "block_index": block.block_index,
                        "block_type": block.block_type,
                        "text_content": block.text_content,
                        "reading_order": block.reading_order,
                        "bbox": block.bbox_json,
                    }
                )
                for block, page_no in page
            )
            next_cursor = None
            if has_more:
                last_block, last_page_no = page[-1]
                next_cursor = _encode_block_cursor(
                    parse_version.id,
                    last_page_no,
                    last_block.block_index,
                    last_block.id,
                )
            return DocumentCorrectionBlockListData.model_validate(
                {
                    "file_id": file.id,
                    "business_type": file.intended_business_type,
                    "parse_version_id": parse_version.id,
                    "items": items,
                    "page_size": page_size,
                    "next_cursor": next_cursor,
                }
            )

    def correct_block(
        self,
        actor: AuthenticatedActor,
        block_id: UUID,
        payload: DocumentBlockCorrectionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> DocumentCorrectionMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/document-blocks/{block_id}/correct"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                idempotency, now = self._claim(
                    session,
                    actor,
                    idempotency_key,
                    path,
                    digest,
                )
                if idempotency.conflict:
                    raise _error(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if idempotency.is_replay:
                    assert idempotency.replay_body is not None
                    return DocumentCorrectionMutationResult(
                        DocumentCorrectionAcceptedData.model_validate(
                            idempotency.replay_body,
                            strict=False,
                        ),
                        True,
                        cast(int, idempotency.replay_status),
                    )
                anchor = session.execute(
                    select(DocumentBlock.id, DocumentParseVersion.file_id)
                    .join(
                        DocumentParseVersion,
                        DocumentParseVersion.id == DocumentBlock.parse_version_id,
                    )
                    .join(FileRecord, FileRecord.id == DocumentParseVersion.file_id)
                    .where(
                        DocumentBlock.id == block_id,
                        FileRecord.organization_id == actor.organization_id,
                    )
                ).one_or_none()
                if anchor is None:
                    raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
                file = session.execute(
                    select(FileRecord)
                    .where(FileRecord.id == anchor.file_id)
                    .with_for_update(of=FileRecord)
                ).scalar_one()
                _require_correction_scope(actor, file)
                source = session.execute(
                    select(DocumentParseVersion)
                    .where(
                        DocumentParseVersion.id == payload.source_parse_version_id,
                        DocumentParseVersion.file_id == file.id,
                        DocumentParseVersion.status == "active",
                        DocumentParseVersion.archived_at.is_(None),
                    )
                    .with_for_update(of=DocumentParseVersion)
                ).scalar_one_or_none()
                if source is None:
                    raise _error(409, "PARSE_VERSION_NOT_CURRENT", "来源解析版本已变化")
                block = session.execute(
                    select(DocumentBlock)
                    .where(
                        DocumentBlock.id == block_id,
                        DocumentBlock.parse_version_id == source.id,
                    )
                    .with_for_update(of=DocumentBlock)
                ).scalar_one_or_none()
                if block is None:
                    raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
                page = session.get(DocumentPage, block.page_id)
                if page is None:
                    raise RuntimeError("document block page is missing")
                if payload.field_name == "bbox":
                    _validate_bbox_against_page(payload.after_value, page)
                before = _before_value(block, payload.field_name)
                if before == payload.after_value:
                    raise _error(422, "CORRECTION_VALUE_INVALID", "修正值未发生变化")

                version_no = (
                    cast(
                        int,
                        session.scalar(
                            select(
                                func.coalesce(func.max(DocumentParseVersion.version_no), 0)
                            ).where(DocumentParseVersion.file_id == file.id)
                        ),
                    )
                    + 1
                )
                result_parse_id = uuid4()
                correction_id = uuid4()
                result_parse = DocumentParseVersion(
                    id=result_parse_id,
                    file_id=file.id,
                    version_no=version_no,
                    parent_version_id=source.id,
                    source_type="manual_correction",
                    parser_name=source.parser_name,
                    parser_version=source.parser_version,
                    ocr_name=source.ocr_name,
                    ocr_version=source.ocr_version,
                    code_version="manual-correction-snapshot-v1",
                    status="queued",
                    page_count=0,
                    raw_text_object_key=None,
                    raw_text_sha256=None,
                    average_confidence=None,
                    error_code=None,
                    error_message=None,
                    activated_at=None,
                    superseded_at=None,
                    created_by=actor.user_id,
                    trace_id=trace_id,
                    archived_at=None,
                )
                correction = DocumentBlockCorrection(
                    id=correction_id,
                    source_parse_version_id=source.id,
                    source_block_id=block.id,
                    result_parse_version_id=result_parse.id,
                    field_name=payload.field_name,
                    before_value_json=before,
                    after_value_json=payload.after_value,
                    reason=payload.reason,
                    corrected_by=actor.user_id,
                    trace_id=trace_id,
                )
                session.add_all((result_parse, correction))
                session.flush()
                handler = load_file_handler("manual_correction_snapshot")
                input_json: dict[str, object] = {
                    "file_id": str(file.id),
                    "source_parse_version_id": str(source.id),
                    "result_parse_version_id": str(result_parse.id),
                    "correction_id": str(correction.id),
                    "handler_code_version": handler.handler.handler_code_version,
                    "handler_registry_version": handler.registry_version,
                    "handler_registry_hash": handler.registry_hash,
                }
                handler.validate_input(input_json)
                job = AsyncJob(
                    id=uuid4(),
                    organization_id=actor.organization_id,
                    job_type="manual_correction_snapshot",
                    resource_type="document_parse_version",
                    resource_id=result_parse.id,
                    status="queued",
                    stage=None,
                    attempt_no=0,
                    max_attempts=1,
                    current_attempt_start_step_code="snapshot_rebuild",
                    input_hash=hashlib.sha256(canonicalize_jcs(input_json)).hexdigest(),
                    input_json=input_json,
                    input_schema_version=1,
                    idempotency_record_id=idempotency.record.id,
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
                session.add(job)
                session.flush()
                session.add(
                    OutboxEvent(
                        id=uuid4(),
                        aggregate_type="async_job",
                        aggregate_id=job.id,
                        event_id=uuid4(),
                        event_type="job.dispatch.requested",
                        event_version=1,
                        event_sequence=1,
                        payload_json={"job_id": str(job.id)},
                        status="pending",
                        attempt_count=0,
                        trace_id=trace_id,
                        created_at=now,
                    )
                )
                data = DocumentCorrectionAcceptedData(
                    correction_id=correction.id,
                    result_parse_version_id=result_parse.id,
                    job_id=job.id,
                    status="queued",
                )
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="document_block.correction_requested",
                    outcome="succeeded",
                    resource_type="document_parse_version",
                    resource_id=result_parse.id,
                    trace_id=trace_id,
                    change_summary={
                        "field_name": payload.field_name,
                        "source_parse_version_id": str(source.id),
                        "status": "queued",
                    },
                )
                UserWriteRepository.complete_idempotency(
                    idempotency,
                    response_status=202,
                    response_body=data.model_dump(mode="json"),
                    resource_id=result_parse.id,
                    resource_type="document_parse_version",
                )
                return DocumentCorrectionMutationResult(data, False)
        except IntegrityError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint in {
                "uq_document_block_corrections_result_parse",
                "uq_parse_versions_file_version",
            }:
                raise _error(409, "RESOURCE_VERSION_CONFLICT", "资源版本已变化") from None
            raise

    def activate_parse(
        self,
        actor: AuthenticatedActor,
        parse_version_id: UUID,
        payload: DocumentParseActivationRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> DocumentActivationMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/document-parse-versions/{parse_version_id}/activate"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        with self._session_factory.begin() as session:
            idempotency, _now = self._claim(
                session,
                actor,
                idempotency_key,
                path,
                digest,
            )
            if idempotency.conflict:
                raise _error(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if idempotency.is_replay:
                assert idempotency.replay_body is not None
                return DocumentActivationMutationResult(
                    DocumentParseActivationData.model_validate(
                        idempotency.replay_body,
                        strict=False,
                    ),
                    True,
                )
            anchor = session.execute(
                select(DocumentParseVersion.file_id)
                .join(FileRecord, FileRecord.id == DocumentParseVersion.file_id)
                .where(
                    DocumentParseVersion.id == parse_version_id,
                    FileRecord.organization_id == actor.organization_id,
                )
            ).scalar_one_or_none()
            if anchor is None:
                raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
            file = session.execute(
                select(FileRecord).where(FileRecord.id == anchor).with_for_update(of=FileRecord)
            ).scalar_one()
            _require_correction_scope(actor, file)
            current = session.execute(
                select(DocumentParseVersion)
                .where(
                    DocumentParseVersion.file_id == file.id,
                    DocumentParseVersion.status == "active",
                    DocumentParseVersion.archived_at.is_(None),
                )
                .with_for_update(of=DocumentParseVersion)
            ).scalar_one_or_none()
            target = session.execute(
                select(DocumentParseVersion)
                .where(
                    DocumentParseVersion.id == parse_version_id,
                    DocumentParseVersion.file_id == file.id,
                    DocumentParseVersion.archived_at.is_(None),
                )
                .with_for_update(of=DocumentParseVersion)
            ).scalar_one()
            superseded_id: UUID | None = None
            if current is None:
                raise _error(409, "PARSE_VERSION_NOT_CURRENT", "当前活动解析版本不存在")
            if target.id != current.id:
                if target.status != "succeeded":
                    raise _error(409, "PARSE_STATE_CONFLICT", "候选解析版本尚未通过质量门禁")
                if target.parent_version_id != current.id:
                    raise _error(409, "PARSE_PARENT_STALE", "候选解析版本的父版本已过期")
                superseded_id = current.id
                result = MarkdownWriteRepository(session).generate_and_activate(
                    organization_id=actor.organization_id,
                    file_id=file.id,
                    parse_version_id=target.id,
                    trace_id=trace_id,
                    actor_id=actor.user_id,
                )
                if result.outcome != "active":
                    raise _error(409, "PARSE_QUALITY_GATE_FAILED", "候选解析质量门禁未通过")
                session.refresh(target)
            if target.activated_at is None:
                raise RuntimeError("active parse has no activation timestamp")
            data = DocumentParseActivationData(
                id=target.id,
                status="active",
                superseded_version_id=superseded_id,
                activated_at=target.activated_at,
            )
            if superseded_id is not None:
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="document_parse.activated",
                    outcome="succeeded",
                    resource_type="document_parse_version",
                    resource_id=target.id,
                    trace_id=trace_id,
                    change_summary={
                        "source_parse_version_id": str(superseded_id),
                        "status": "active",
                    },
                )
            UserWriteRepository.complete_idempotency(
                idempotency,
                response_status=200,
                response_body=data.model_dump(mode="json"),
                resource_id=target.id,
                resource_type="document_parse_version",
            )
            return DocumentActivationMutationResult(data, False)

    def request_security_revalidation(
        self,
        actor: AuthenticatedActor,
        parse_version_id: UUID,
        payload: SecurityRevalidationRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> SecurityRevalidationMutationResult:
        _validate_idempotency_key(idempotency_key)
        if "system.configure" not in actor.permissions or "system_admin" not in actor.roles:
            raise _error(403, "AUTH_FORBIDDEN", "无权执行该操作")
        path = f"/api/v1/document-parse-versions/{parse_version_id}/security-revalidations"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                idempotency, now = self._claim(
                    session,
                    actor,
                    idempotency_key,
                    path,
                    digest,
                )
                if idempotency.conflict:
                    raise _error(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if idempotency.is_replay:
                    assert idempotency.replay_body is not None
                    return SecurityRevalidationMutationResult(
                        AcceptedJobData.model_validate(idempotency.replay_body, strict=False),
                        True,
                        cast(int, idempotency.replay_status),
                    )
                anchor = session.execute(
                    select(DocumentParseVersion.file_id)
                    .join(FileRecord, FileRecord.id == DocumentParseVersion.file_id)
                    .where(
                        DocumentParseVersion.id == parse_version_id,
                        FileRecord.organization_id == actor.organization_id,
                    )
                ).scalar_one_or_none()
                if anchor is None:
                    raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
                file = session.execute(
                    select(FileRecord).where(FileRecord.id == anchor).with_for_update(of=FileRecord)
                ).scalar_one()
                _require_correction_scope(actor, file)
                source = session.execute(
                    select(DocumentParseVersion)
                    .where(
                        DocumentParseVersion.id == parse_version_id,
                        DocumentParseVersion.file_id == file.id,
                        DocumentParseVersion.status == "active",
                        DocumentParseVersion.archived_at.is_(None),
                    )
                    .with_for_update(of=DocumentParseVersion)
                ).scalar_one_or_none()
                if source is None:
                    raise _error(409, "PARSE_VERSION_NOT_ACTIVE", "目标解析版本已非活动版本")
                target = ScannerRegistryRepository(session).current_asset_target()
                if target is None:
                    raise _error(
                        503,
                        "SECURITY_REVALIDATION_CONFIGURATION_ERROR",
                        "资源安全重评环境尚未配置",
                    )
                in_progress = session.scalar(
                    select(DocumentParseVersion.id).where(
                        DocumentParseVersion.file_id == file.id,
                        DocumentParseVersion.parent_version_id == source.id,
                        DocumentParseVersion.source_type == "security_revalidation",
                        DocumentParseVersion.status.in_(("queued", "running")),
                    )
                )
                if in_progress is not None:
                    raise _error(409, "ASSET_REVALIDATION_IN_PROGRESS", "已有安全重评正在执行")
                assets = tuple(
                    session.scalars(
                        select(DocumentAsset)
                        .where(DocumentAsset.parse_version_id == source.id)
                        .order_by(DocumentAsset.id)
                    ).all()
                )
                frozen_identity = (
                    target.profile_class,
                    target.registry_version,
                    target.scanner_registry_hash,
                    target.adapter_code,
                    target.scanner_version,
                    target.definition_version,
                )
                needs_revalidation = payload.force_recheck or any(
                    asset.security_status in {"scan_failed", "not_configured"}
                    or asset.security_policy_version != payload.security_policy_version
                    or asset.security_policy_hash
                    != "b074e9cb6af5e20b57cb14f042977417bcf6f9d9eb35c47abf6a13de3823efe0"
                    or (
                        asset.security_scanner_profile_class,
                        asset.security_scanner_registry_version,
                        asset.security_scanner_registry_hash,
                        asset.security_scanner_adapter_code,
                        asset.security_scanner_version,
                        asset.security_scanner_definition_version,
                    )
                    != frozen_identity
                    for asset in assets
                )
                if not assets or not needs_revalidation:
                    raise _error(409, "ASSET_REVALIDATION_NOT_REQUIRED", "当前资源无需安全重评")

                handler = load_file_handler("asset_security_revalidation")
                version_no = (
                    cast(
                        int,
                        session.scalar(
                            select(
                                func.coalesce(func.max(DocumentParseVersion.version_no), 0)
                            ).where(DocumentParseVersion.file_id == file.id)
                        ),
                    )
                    + 1
                )
                result_parse = DocumentParseVersion(
                    id=uuid4(),
                    file_id=file.id,
                    version_no=version_no,
                    parent_version_id=source.id,
                    source_type="security_revalidation",
                    parser_name=source.parser_name,
                    parser_version=source.parser_version,
                    ocr_name=source.ocr_name,
                    ocr_version=source.ocr_version,
                    code_version="asset-security-revalidation-v1",
                    status="queued",
                    page_count=0,
                    raw_text_object_key=None,
                    raw_text_sha256=None,
                    average_confidence=None,
                    error_code=None,
                    error_message=None,
                    activated_at=None,
                    superseded_at=None,
                    created_by=actor.user_id,
                    trace_id=trace_id,
                    archived_at=None,
                )
                session.add(result_parse)
                session.flush()
                input_json: dict[str, object] = {
                    "file_id": str(file.id),
                    "source_parse_version_id": str(source.id),
                    "result_parse_version_id": str(result_parse.id),
                    "security_policy_version": "asset-security-v1",
                    "security_policy_hash": (
                        "b074e9cb6af5e20b57cb14f042977417bcf6f9d9eb35c47abf6a13de3823efe0"
                    ),
                    "handler_code_version": handler.handler.handler_code_version,
                    "handler_registry_version": handler.registry_version,
                    "handler_registry_hash": handler.registry_hash,
                    "scanner_profile_class": target.profile_class,
                    "scanner_registry_version": target.registry_version,
                    "scanner_registry_hash": target.scanner_registry_hash,
                    "scanner_adapter_code": target.adapter_code,
                    "scanner_version": target.scanner_version,
                    "scanner_definition_version": target.definition_version,
                }
                handler.validate_input(input_json)
                job = AsyncJob(
                    id=uuid4(),
                    organization_id=actor.organization_id,
                    job_type="asset_security_revalidation",
                    resource_type="document_parse_version",
                    resource_id=result_parse.id,
                    status="queued",
                    stage=None,
                    attempt_no=0,
                    max_attempts=1,
                    current_attempt_start_step_code="asset_security_revalidation",
                    input_hash=hashlib.sha256(canonicalize_jcs(input_json)).hexdigest(),
                    input_json=input_json,
                    input_schema_version=1,
                    idempotency_record_id=idempotency.record.id,
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
                session.add(job)
                session.flush()
                session.add(
                    OutboxEvent(
                        id=uuid4(),
                        aggregate_type="async_job",
                        aggregate_id=job.id,
                        event_id=uuid4(),
                        event_type="job.dispatch.requested",
                        event_version=1,
                        event_sequence=1,
                        payload_json={"job_id": str(job.id)},
                        status="pending",
                        attempt_count=0,
                        trace_id=trace_id,
                        created_at=now,
                    )
                )
                data = AcceptedJobData(
                    job_id=job.id,
                    resource_type="document_parse_version",
                    resource_id=result_parse.id,
                    status="queued",
                    stage=None,
                    next_stage="asset_security_revalidation",
                )
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="document_parse.security_revalidation.requested",
                    outcome="succeeded",
                    resource_type="document_parse_version",
                    resource_id=result_parse.id,
                    trace_id=trace_id,
                    change_summary={
                        "source_parse_version_id": str(source.id),
                        "status": "queued",
                    },
                )
                UserWriteRepository.complete_idempotency(
                    idempotency,
                    response_status=202,
                    response_body=data.model_dump(mode="json"),
                    resource_id=result_parse.id,
                    resource_type="document_parse_version",
                )
                return SecurityRevalidationMutationResult(data, False)
        except IntegrityError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint in {
                "uq_parse_security_revalidation_in_progress",
                "uq_parse_versions_file_version",
            }:
                raise _error(
                    409,
                    "ASSET_REVALIDATION_IN_PROGRESS",
                    "已有安全重评正在执行",
                ) from None
            raise

    @staticmethod
    def _claim(
        session: Session,
        actor: AuthenticatedActor,
        idempotency_key: str,
        path: str,
        request_hash: str,
    ) -> tuple[IdempotencyClaim, datetime]:
        repository = UserWriteRepository(session)
        repository.acquire_idempotency_lock(actor.organization_id, actor.user_id, idempotency_key)
        if repository.lock_active_organization(actor.organization_id) is None:
            raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
        now = repository.database_now()
        return (
            repository.claim_idempotency(
                organization_id=actor.organization_id,
                actor_id=actor.user_id,
                idempotency_key=idempotency_key,
                request_method="POST",
                request_path=path,
                request_hash=request_hash,
                now=now,
                expires_at=now + _IDEMPOTENCY_TTL,
            ),
            now,
        )


__all__ = [
    "DocumentActivationMutationResult",
    "DocumentCorrectionMutationResult",
    "DocumentCorrectionService",
    "SecurityRevalidationMutationResult",
]
