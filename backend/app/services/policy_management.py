"""制度草稿、独立业务审批与确定性分块用例。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.chunking.config import CHUNK_PROFILE_HASH, CHUNK_PROFILE_VERSION
from app.core.errors import AppError
from app.models.documents import FilePrimaryBusinessObject
from app.models.knowledge import PolicyApprovalRecord, PolicyDocument
from app.repositories.chunk_write import ChunkWriteRepository, ChunkWriteResult
from app.repositories.operation_log import OperationLogRepository
from app.repositories.policy_write import PolicyWriteRepository
from app.repositories.retrieval_runtime import RetrievalRuntimeRepository
from app.repositories.user_write import IdempotencyClaim
from app.schemas.policies import (
    PendingPolicyRevocationItemData,
    PendingPolicyRevocationListData,
    PolicyChunkSetData,
    PolicyCreateRequest,
    PolicyData,
    PolicyListData,
    PolicyRevocationRequestData,
    PolicyRevokeRequest,
    PolicyStatus,
    PolicyTransitionRequest,
    PolicyWriteData,
)
from app.services.auth import AuthenticatedActor

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_IDEMPOTENCY_TTL = timedelta(hours=24)
_UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


@dataclass(frozen=True, slots=True)
class PolicyMutationResult:
    data: PolicyWriteData
    replayed: bool
    status_code: int


@dataclass(frozen=True, slots=True)
class PolicyRevocationRequestMutationResult:
    data: PolicyRevocationRequestData
    replayed: bool
    status_code: int


def _not_found() -> AppError:
    return AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )


def _conflict(code: str, message: str) -> AppError:
    return AppError(status_code=409, code=code, message=message)


def _validate_idempotency_key(value: str) -> None:
    if type(value) is not str or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": "header.Idempotency-Key", "reason": "invalid"}],
        )


def _request_hash(method: str, path: str, body: dict[str, object]) -> str:
    encoded = json.dumps(
        {"method": method, "path": path, "body": body},
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _invalid_cursor() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=[{"field": "query.cursor", "reason": "invalid"}],
    )


def _encode_cursor(policy_id: UUID) -> str:
    payload = json.dumps(
        {"id": str(policy_id), "v": 1},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor(value: str) -> UUID:
    if not value or len(value) > 256 or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise _invalid_cursor()
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
            raise ValueError("noncanonical base64url")
        payload = json.loads(decoded.decode("utf-8"))
        if type(payload) is not dict or set(payload) != {"id", "v"} or payload["v"] != 1:
            raise ValueError("invalid cursor object")
        raw_id = payload["id"]
        if type(raw_id) is not str:
            raise ValueError("invalid cursor id")
        policy_id = UUID(raw_id)
        if str(policy_id) != raw_id or _encode_cursor(policy_id) != value:
            raise ValueError("noncanonical cursor id")
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None
    return policy_id


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise RuntimeError("revocation request timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _encode_pending_revocation_cursor(
    knowledge_base_id: UUID,
    requested_at: datetime,
    request_id: UUID,
) -> str:
    payload = json.dumps(
        {
            "id": str(request_id),
            "knowledge_base_id": str(knowledge_base_id),
            "requested_at": _utc_text(requested_at),
            "v": 1,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_pending_revocation_cursor(
    value: str,
    knowledge_base_id: UUID,
) -> tuple[datetime, UUID]:
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
            "id",
            "knowledge_base_id",
            "requested_at",
            "v",
        }:
            raise ValueError("invalid cursor object")
        raw_id = payload["id"]
        raw_knowledge_base_id = payload["knowledge_base_id"]
        raw_requested_at = payload["requested_at"]
        if (
            type(payload["v"]) is not int
            or payload["v"] != 1
            or type(raw_id) is not str
            or type(raw_knowledge_base_id) is not str
            or type(raw_requested_at) is not str
            or _UTC_TIMESTAMP_PATTERN.fullmatch(raw_requested_at) is None
        ):
            raise ValueError("invalid cursor fields")
        request_id = UUID(raw_id)
        cursor_knowledge_base_id = UUID(raw_knowledge_base_id)
        requested_at = datetime.fromisoformat(raw_requested_at.replace("Z", "+00:00"))
        if (
            str(request_id) != raw_id
            or str(cursor_knowledge_base_id) != raw_knowledge_base_id
            or cursor_knowledge_base_id != knowledge_base_id
            or _encode_pending_revocation_cursor(
                cursor_knowledge_base_id,
                requested_at,
                request_id,
            )
            != value
        ):
            raise ValueError("noncanonical cursor")
        return requested_at, request_id
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None


def _project_policy(policy: PolicyDocument) -> PolicyData:
    return PolicyData.model_validate(
        {
            "id": policy.id,
            "knowledge_base_id": policy.knowledge_base_id,
            "source_file_id": policy.source_file_id,
            "policy_code": policy.policy_code,
            "name": policy.name,
            "version": policy.version,
            "issuing_department": policy.issuing_department,
            "effective_from": policy.effective_from,
            "effective_to": policy.effective_to,
            "scope": dict(policy.scope_json),
            "status": PolicyStatus(policy.status),
            "submitted_by": policy.submitted_by,
            "submitted_at": policy.submitted_at,
            "business_approved_by": policy.business_approved_by,
            "business_approved_at": policy.business_approved_at,
            "technical_published_by": policy.technical_published_by,
            "technical_published_at": policy.technical_published_at,
            "revoked_at": policy.revoked_at,
            "revoked_by": policy.revoked_by,
            "revoke_reason": policy.revoke_reason,
            "row_version": str(policy.row_version),
        }
    )


def _project_chunk(result: ChunkWriteResult) -> PolicyChunkSetData:
    return PolicyChunkSetData(
        id=result.chunk_set_id,
        markdown_version_id=result.markdown_version_id,
        version_no=result.version_no,
        status="active",
        profile_version=CHUNK_PROFILE_VERSION,
        profile_hash=CHUNK_PROFILE_HASH,
        chunk_count=result.chunk_count,
        content_manifest_hash=result.content_manifest_hash,
    )


def _actor_role(actor: AuthenticatedActor) -> str:
    if "audit_reviewer" not in actor.roles:
        raise AppError(
            status_code=403,
            code="AUTH_FORBIDDEN",
            message="当前角色无权执行制度业务确认",
        )
    return "audit_reviewer"


def _publisher_role(actor: AuthenticatedActor) -> str:
    if "system_admin" not in actor.roles:
        raise AppError(
            status_code=403,
            code="AUTH_FORBIDDEN",
            message="当前角色无权执行制度技术操作",
        )
    return "system_admin"


def _require_pending_revocation_reader(actor: AuthenticatedActor) -> None:
    audit_reader = "knowledge.approve" in actor.permissions and "audit_reviewer" in actor.roles
    admin_reader = "knowledge.publish" in actor.permissions and "system_admin" in actor.roles
    if not audit_reader and not admin_reader:
        raise AppError(
            status_code=403,
            code="AUTH_FORBIDDEN",
            message="当前角色无权读取制度撤销待办",
        )


def _can_read_unpublished(actor: AuthenticatedActor) -> bool:
    return bool(
        {"knowledge.submit", "knowledge.approve", "knowledge.publish"}.intersection(
            actor.permissions
        )
    )


def _integrity_error(error: IntegrityError) -> AppError:
    original = error.orig
    sqlstate = getattr(original, "sqlstate", None)
    diagnostic = getattr(original, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    if sqlstate == "23505" and constraint_name == "uq_policy_code_version":
        return _conflict("POLICY_VERSION_CONFLICT", "制度编号与版本已存在")
    if sqlstate == "23505" and constraint_name in {
        "uq_policy_source_file",
        "uq_file_primary_business_objects_file_id",
        "uq_file_primary_business_objects_policy_document_id",
    }:
        return _conflict("POLICY_SOURCE_FILE_CONFLICT", "来源文件已绑定其他主业务对象")
    if sqlstate == "23P01" and constraint_name == "ex_policy_effective_range_no_overlap":
        return _conflict("POLICY_EFFECTIVE_RANGE_CONFLICT", "制度发布有效期发生重叠")
    if sqlstate == "23505" and constraint_name == "uq_policy_revocation_request":
        return _conflict("POLICY_REVOCATION_ALREADY_REQUESTED", "制度撤销确认已存在")
    if sqlstate == "23505" and constraint_name == "uq_policy_revocation_execution":
        return _conflict("POLICY_REVOCATION_ALREADY_EXECUTED", "制度撤销确认已执行")
    return AppError(status_code=500, code="INTERNAL_ERROR", message="服务暂时不可用")


def _chunk_error(error: ValueError) -> AppError:
    code = str(error)
    if code == "ACTIVE_MARKDOWN_NOT_FOUND":
        return _conflict("POLICY_MARKDOWN_NOT_READY", "制度活动 Markdown 尚未就绪")
    return _conflict("POLICY_CHUNKING_FAILED", "制度分块未通过完整性门禁")


class PolicyManagementService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_page(
        self,
        actor: AuthenticatedActor,
        cursor: str | None,
        page_size: int,
        *,
        knowledge_base_id: UUID | None = None,
    ) -> PolicyListData:
        cursor_id = _decode_cursor(cursor) if cursor is not None else None
        with self._session_factory() as session:
            rows = PolicyWriteRepository(session).list_policies(
                actor.organization_id,
                cursor_id,
                page_size + 1,
                include_unpublished=_can_read_unpublished(actor),
                knowledge_base_id=knowledge_base_id,
            )
        has_more = len(rows) > page_size
        page = rows[:page_size]
        return PolicyListData(
            items=tuple(_project_policy(row) for row in page),
            page_size=page_size,
            next_cursor=_encode_cursor(page[-1].id) if has_more else None,
        )

    def list_pending_revocations(
        self,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> PendingPolicyRevocationListData:
        _require_pending_revocation_reader(actor)
        cursor_values = (
            _decode_pending_revocation_cursor(cursor, knowledge_base_id)
            if cursor is not None
            else (None, None)
        )
        with self._session_factory() as session:
            repository = PolicyWriteRepository(session)
            if repository.get_knowledge_base(actor.organization_id, knowledge_base_id) is None:
                raise _not_found()
            rows = repository.list_pending_revocations(
                actor.organization_id,
                knowledge_base_id,
                cursor_values[0],
                cursor_values[1],
                page_size + 1,
            )
        has_more = len(rows) > page_size
        page = rows[:page_size]
        items = tuple(
            PendingPolicyRevocationItemData(
                revocation_request_id=request.id,
                policy_id=policy.id,
                policy_code=policy.policy_code,
                policy_name=policy.name,
                policy_row_version=str(policy.row_version),
                requested_by=request.actor_id,
                requested_at=request.created_at,
            )
            for request, policy in page
        )
        next_cursor = None
        if has_more:
            last_request, _last_policy = page[-1]
            next_cursor = _encode_pending_revocation_cursor(
                knowledge_base_id,
                last_request.created_at,
                last_request.id,
            )
        return PendingPolicyRevocationListData(
            items=items,
            page_size=page_size,
            next_cursor=next_cursor,
        )

    def get_detail(self, actor: AuthenticatedActor, policy_document_id: UUID) -> PolicyData:
        with self._session_factory() as session:
            policy = PolicyWriteRepository(session).get_policy(
                actor.organization_id,
                policy_document_id,
                include_unpublished=_can_read_unpublished(actor),
            )
            if policy is None:
                raise _not_found()
            return _project_policy(policy)

    def create(
        self,
        actor: AuthenticatedActor,
        payload: PolicyCreateRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> PolicyMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = "/api/v1/policy-documents"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository, claim, now = self._claim(
                    session, actor, idempotency_key, "POST", path, digest
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._replay(claim)

                knowledge_base = repository.lock_knowledge_base(
                    actor.organization_id, payload.knowledge_base_id
                )
                if knowledge_base is None:
                    raise _not_found()
                if knowledge_base.status != "active":
                    raise _conflict("KNOWLEDGE_BASE_NOT_ACTIVE", "知识库当前不可写入")
                source_file = repository.lock_source_file(
                    actor.organization_id, payload.source_file_id
                )
                if source_file is None:
                    raise _not_found()
                if (
                    source_file.intended_business_type != "policy"
                    or source_file.target_knowledge_base_id != payload.knowledge_base_id
                ):
                    raise _conflict("POLICY_SOURCE_FILE_CONFLICT", "来源文件分类不匹配")
                if (
                    source_file.status != "stored"
                    or source_file.security_scan_status != "clean"
                    or repository.active_markdown(actor.organization_id, source_file.id) is None
                ):
                    raise _conflict("POLICY_MARKDOWN_NOT_READY", "制度活动 Markdown 尚未就绪")
                if repository.source_binding(source_file.id) is not None:
                    raise _conflict("POLICY_SOURCE_FILE_CONFLICT", "来源文件已绑定主业务对象")

                policy_id = uuid4()
                policy = PolicyDocument(
                    id=policy_id,
                    organization_id=actor.organization_id,
                    knowledge_base_id=payload.knowledge_base_id,
                    source_file_id=payload.source_file_id,
                    policy_code=payload.policy_code,
                    name=payload.name,
                    version=payload.version,
                    issuing_department=payload.issuing_department,
                    effective_from=payload.effective_from,
                    effective_to=payload.effective_to,
                    scope_json=payload.scope,
                    access_scope="internal",
                    allowed_role_codes=[],
                    status="draft",
                    submitted_by=None,
                    submitted_at=None,
                    business_approved_by=None,
                    business_approved_at=None,
                    technical_published_by=None,
                    technical_published_at=None,
                    superseded_by_policy_id=None,
                    revoked_at=None,
                    revoked_by=None,
                    revoke_reason=None,
                    row_version=1,
                    created_at=now,
                    created_by=actor.user_id,
                    updated_at=now,
                    updated_by=actor.user_id,
                    deleted_at=None,
                    deleted_by=None,
                    delete_reason=None,
                )
                repository.add(policy)
                repository.flush()
                repository.add(
                    FilePrimaryBusinessObject(
                        file_id=source_file.id,
                        business_type="policy",
                        contract_id=None,
                        invoice_id=None,
                        supplementary_agreement_id=None,
                        policy_document_id=policy.id,
                        bound_at=now,
                        bound_by=actor.user_id,
                    )
                )
                repository.flush()
                data = PolicyWriteData(policy=_project_policy(policy), chunk_set=None)
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="policy.created",
                    outcome="succeeded",
                    resource_type="policy_document",
                    resource_id=policy.id,
                    trace_id=trace_id,
                    change_summary={"status": "draft", "row_version": str(policy.row_version)},
                )
                repository.complete_idempotency(
                    claim,
                    response_status=201,
                    response_body=data.model_dump(mode="json"),
                    resource_id=policy.id,
                )
                return PolicyMutationResult(data, False, 201)
        except IntegrityError as error:
            raise _integrity_error(error) from None

    def submit(
        self,
        actor: AuthenticatedActor,
        policy_document_id: UUID,
        payload: PolicyTransitionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> PolicyMutationResult:
        return self._transition(
            actor,
            policy_document_id,
            payload,
            idempotency_key,
            trace_id,
            action="submit",
        )

    def approve(
        self,
        actor: AuthenticatedActor,
        policy_document_id: UUID,
        payload: PolicyTransitionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> PolicyMutationResult:
        return self._transition(
            actor,
            policy_document_id,
            payload,
            idempotency_key,
            trace_id,
            action="approve",
        )

    def publish(
        self,
        actor: AuthenticatedActor,
        policy_document_id: UUID,
        payload: PolicyTransitionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> PolicyMutationResult:
        """在已激活且正式评测通过的索引中发布制度。"""

        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/policy-documents/{policy_document_id}/publish"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository, claim, now = self._claim(
                    session, actor, idempotency_key, "POST", path, digest
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._replay(claim)
                policy = repository.lock_policy(actor.organization_id, policy_document_id)
                if policy is None:
                    raise _not_found()
                if policy.row_version != int(payload.row_version):
                    raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
                if policy.status != "business_approved":
                    raise _conflict("POLICY_STATE_CONFLICT", "当前制度状态不可发布")
                if policy.business_approved_by == actor.user_id:
                    raise _conflict(
                        "POLICY_SELF_PUBLICATION_FORBIDDEN",
                        "制度业务批准人与技术发布人必须不同",
                    )
                retrieval = RetrievalRuntimeRepository(session)
                active_index = retrieval.active_index_contains_policy(
                    policy.knowledge_base_id, policy.id
                )
                if active_index is None or retrieval.formal_passed_run(active_index.id) is None:
                    raise _conflict(
                        "POLICY_RETRIEVAL_GATE_FAILED",
                        "制度尚未进入正式评测通过的活动索引",
                    )
                if not repository.cas_policy(
                    policy,
                    int(payload.row_version),
                    {
                        "status": "published",
                        "technical_published_by": actor.user_id,
                        "technical_published_at": now,
                        "updated_at": now,
                        "updated_by": actor.user_id,
                    },
                ):
                    raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
                repository.add(
                    PolicyApprovalRecord(
                        id=uuid4(),
                        policy_document_id=policy.id,
                        action="publish",
                        from_status="business_approved",
                        to_status="published",
                        actor_id=actor.user_id,
                        actor_role_code=_publisher_role(actor),
                        reason=payload.reason,
                        created_at=now,
                        trace_id=trace_id,
                    )
                )
                repository.flush()
                data = PolicyWriteData(
                    policy=_project_policy(policy),
                    chunk_set=None,
                )
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="policy.published",
                    outcome="succeeded",
                    resource_type="policy_document",
                    resource_id=policy.id,
                    trace_id=trace_id,
                    change_summary={
                        "from_status": "business_approved",
                        "index_version_id": str(active_index.id),
                        "row_version": str(policy.row_version),
                        "to_status": "published",
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_status=200,
                    response_body=data.model_dump(mode="json"),
                    resource_id=policy.id,
                )
                return PolicyMutationResult(data, False, 200)
        except IntegrityError as error:
            raise _integrity_error(error) from None

    def request_revocation(
        self,
        actor: AuthenticatedActor,
        policy_document_id: UUID,
        payload: PolicyTransitionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> PolicyRevocationRequestMutationResult:
        """由审计复核角色追加唯一撤销确认，不改变制度状态。"""

        _actor_role(actor)
        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/policy-documents/{policy_document_id}/revocation-requests"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository, claim, now = self._claim(
                    session, actor, idempotency_key, "POST", path, digest
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._replay_revocation_request(claim)
                policy = repository.lock_policy(actor.organization_id, policy_document_id)
                if policy is None:
                    raise _not_found()
                if policy.row_version != int(payload.row_version):
                    raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
                if policy.status != "published":
                    raise _conflict("POLICY_STATE_CONFLICT", "当前制度状态不可提交撤销确认")
                if repository.revocation_request(policy.id) is not None:
                    raise _conflict(
                        "POLICY_REVOCATION_ALREADY_REQUESTED",
                        "制度撤销确认已存在",
                    )
                request_record = PolicyApprovalRecord(
                    id=uuid4(),
                    policy_document_id=policy.id,
                    action="revoke_request",
                    from_status="published",
                    to_status="revoked",
                    actor_id=actor.user_id,
                    actor_role_code="audit_reviewer",
                    related_record_id=None,
                    reason=payload.reason,
                    created_at=now,
                    trace_id=trace_id,
                )
                repository.add(request_record)
                repository.flush()
                data = PolicyRevocationRequestData(
                    revocation_request_id=request_record.id,
                    policy_id=policy.id,
                    status="pending_execution",
                    requested_by=actor.user_id,
                    requested_at=now,
                )
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="policy.revocation_requested",
                    outcome="succeeded",
                    resource_type="policy_document",
                    resource_id=policy.id,
                    trace_id=trace_id,
                    change_summary={
                        "revocation_request_id": str(request_record.id),
                        "status": "pending_execution",
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_status=201,
                    response_body=data.model_dump(mode="json"),
                    resource_id=policy.id,
                )
                return PolicyRevocationRequestMutationResult(data, False, 201)
        except IntegrityError as error:
            raise _integrity_error(error) from None

    def revoke(
        self,
        actor: AuthenticatedActor,
        policy_document_id: UUID,
        payload: PolicyRevokeRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> PolicyMutationResult:
        """由 system_admin 执行已确认的 published → revoked。"""

        _publisher_role(actor)
        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/policy-documents/{policy_document_id}/revoke"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository, claim, now = self._claim(
                    session, actor, idempotency_key, "POST", path, digest
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._replay(claim)
                policy = repository.lock_policy(actor.organization_id, policy_document_id)
                if policy is None:
                    raise _not_found()
                if policy.row_version != int(payload.row_version):
                    raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
                if policy.status != "published":
                    raise _conflict("POLICY_STATE_CONFLICT", "当前制度状态不可撤销")
                request_record = repository.lock_revocation_request(
                    policy.id,
                    payload.revocation_request_id,
                )
                if request_record is None:
                    raise _conflict(
                        "POLICY_REVOCATION_REQUEST_CONFLICT",
                        "撤销确认与当前制度不匹配",
                    )
                if repository.revocation_execution(request_record.id) is not None:
                    raise _conflict(
                        "POLICY_REVOCATION_ALREADY_EXECUTED",
                        "制度撤销确认已执行",
                    )
                if request_record.actor_id == actor.user_id:
                    raise _conflict(
                        "POLICY_SELF_REVOCATION_FORBIDDEN",
                        "撤销确认人与执行人必须不同",
                    )
                if not repository.cas_policy(
                    policy,
                    int(payload.row_version),
                    {
                        "status": "revoked",
                        "revoked_at": now,
                        "revoked_by": actor.user_id,
                        "revoke_reason": payload.reason,
                        "updated_at": now,
                        "updated_by": actor.user_id,
                    },
                ):
                    raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
                execution_record = PolicyApprovalRecord(
                    id=uuid4(),
                    policy_document_id=policy.id,
                    action="revoke",
                    from_status="published",
                    to_status="revoked",
                    actor_id=actor.user_id,
                    actor_role_code="system_admin",
                    related_record_id=request_record.id,
                    reason=payload.reason,
                    created_at=now,
                    trace_id=trace_id,
                )
                repository.add(execution_record)
                repository.flush()
                data = PolicyWriteData(policy=_project_policy(policy), chunk_set=None)
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="policy.revoked",
                    outcome="succeeded",
                    resource_type="policy_document",
                    resource_id=policy.id,
                    trace_id=trace_id,
                    change_summary={
                        "from_status": "published",
                        "revocation_request_id": str(request_record.id),
                        "row_version": str(policy.row_version),
                        "to_status": "revoked",
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_status=200,
                    response_body=data.model_dump(mode="json"),
                    resource_id=policy.id,
                )
                return PolicyMutationResult(data, False, 200)
        except IntegrityError as error:
            raise _integrity_error(error) from None

    def _transition(
        self,
        actor: AuthenticatedActor,
        policy_document_id: UUID,
        payload: PolicyTransitionRequest,
        idempotency_key: str,
        trace_id: UUID,
        *,
        action: str,
    ) -> PolicyMutationResult:
        _validate_idempotency_key(idempotency_key)
        suffix = "submit-review" if action == "submit" else "approve"
        path = f"/api/v1/policy-documents/{policy_document_id}/{suffix}"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository, claim, now = self._claim(
                    session, actor, idempotency_key, "POST", path, digest
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._replay(claim)
                policy = repository.lock_policy(actor.organization_id, policy_document_id)
                if policy is None:
                    raise _not_found()
                if policy.row_version != int(payload.row_version):
                    raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
                expected_status = "draft" if action == "submit" else "submitted"
                target_status = "submitted" if action == "submit" else "business_approved"
                if policy.status != expected_status:
                    raise _conflict("POLICY_STATE_CONFLICT", "当前制度状态不可执行该操作")
                if repository.active_markdown(actor.organization_id, policy.source_file_id) is None:
                    raise _conflict("POLICY_MARKDOWN_NOT_READY", "制度活动 Markdown 尚未就绪")
                if action == "approve" and policy.submitted_by == actor.user_id:
                    raise _conflict(
                        "POLICY_SELF_APPROVAL_FORBIDDEN",
                        "制度提交人与业务批准人必须不同",
                    )

                values: dict[str, object] = {
                    "status": target_status,
                    "updated_at": now,
                    "updated_by": actor.user_id,
                }
                if action == "submit":
                    values.update(submitted_by=actor.user_id, submitted_at=now)
                else:
                    values.update(
                        business_approved_by=actor.user_id,
                        business_approved_at=now,
                    )
                if not repository.cas_policy(policy, int(payload.row_version), values):
                    raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
                repository.add(
                    PolicyApprovalRecord(
                        id=uuid4(),
                        policy_document_id=policy.id,
                        action=action,
                        from_status=expected_status,
                        to_status=target_status,
                        actor_id=actor.user_id,
                        actor_role_code=_actor_role(actor),
                        reason=payload.reason,
                        created_at=now,
                        trace_id=trace_id,
                    )
                )
                repository.flush()

                chunk_result: ChunkWriteResult | None = None
                if action == "approve":
                    try:
                        chunk_result = ChunkWriteRepository(session).generate_and_activate(
                            organization_id=actor.organization_id,
                            policy_document_id=policy.id,
                            trace_id=trace_id,
                            actor_id=actor.user_id,
                        )
                    except ValueError as error:
                        raise _chunk_error(error) from None
                data = PolicyWriteData(
                    policy=_project_policy(policy),
                    chunk_set=None if chunk_result is None else _project_chunk(chunk_result),
                )
                action_code = (
                    "policy.submitted" if action == "submit" else "policy.business_approved"
                )
                summary: dict[str, object] = {
                    "from_status": expected_status,
                    "to_status": target_status,
                    "row_version": str(policy.row_version),
                }
                if chunk_result is not None:
                    summary.update(
                        chunk_count=chunk_result.chunk_count,
                        profile_hash=CHUNK_PROFILE_HASH,
                    )
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code=action_code,
                    outcome="succeeded",
                    resource_type="policy_document",
                    resource_id=policy.id,
                    trace_id=trace_id,
                    change_summary=summary,
                )
                repository.complete_idempotency(
                    claim,
                    response_status=200,
                    response_body=data.model_dump(mode="json"),
                    resource_id=policy.id,
                )
                return PolicyMutationResult(data, False, 200)
        except IntegrityError as error:
            raise _integrity_error(error) from None

    @staticmethod
    def _claim(
        session: Session,
        actor: AuthenticatedActor,
        idempotency_key: str,
        method: str,
        path: str,
        digest: str,
    ) -> tuple[PolicyWriteRepository, IdempotencyClaim, datetime]:
        repository = PolicyWriteRepository(session)
        repository.acquire_api_locks(actor.organization_id, actor.user_id, idempotency_key)
        if repository.lock_active_organization(actor.organization_id) is None:
            raise _not_found()
        now = repository.database_now()
        claim = repository.claim_idempotency(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            idempotency_key=idempotency_key,
            request_method=method,
            request_path=path,
            request_hash=digest,
            now=now,
            expires_at=now + _IDEMPOTENCY_TTL,
        )
        return repository, claim, now

    @staticmethod
    def _replay(claim: IdempotencyClaim) -> PolicyMutationResult:
        if claim.replay_status not in {200, 201} or claim.replay_body is None:
            raise RuntimeError("policy replay does not match the contract")
        return PolicyMutationResult(
            PolicyWriteData.model_validate_json(
                json.dumps(
                    claim.replay_body,
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            ),
            True,
            claim.replay_status,
        )

    @staticmethod
    def _replay_revocation_request(
        claim: IdempotencyClaim,
    ) -> PolicyRevocationRequestMutationResult:
        if claim.replay_status != 201 or claim.replay_body is None:
            raise RuntimeError("policy revocation request replay does not match the contract")
        return PolicyRevocationRequestMutationResult(
            PolicyRevocationRequestData.model_validate_json(
                json.dumps(
                    claim.replay_body,
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            ),
            True,
            201,
        )


__all__ = [
    "PolicyManagementService",
    "PolicyMutationResult",
    "PolicyRevocationRequestMutationResult",
]
