from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass
from uuid import UUID

from smoke_local_audit_execution_crash_recovery import _client, _client_profile
from smoke_local_file_upload import SmokeError, _login, _read_password
from smoke_local_security import (
    SecurityGateError,
    _authorization,
    _create_user,
    _mutation_headers,
    _poll_data,
    _prompt_injection_pdf,
    _require_success,
    _stable_id,
)
from smoke_local_worker_crash_recovery import (
    _POLL_INTERVAL_SECONDS,
    CrashRecoveryError,
    _canonical_uuid,
    _required_environment,
)
from sqlalchemy import func, select

from app.adapters.qdrant_vector import QdrantStoredPoint, QdrantVectorAdapter
from app.ai.adapters.deterministic_hash import DeterministicHashEmbeddingAdapter
from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.models.auth import User
from app.models.documents import KnowledgeBase
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, AsyncJobStep, OutboxEvent
from app.models.retrieval import DocumentIndexItem, DocumentIndexVersion
from app.repositories.retrieval_runtime import (
    MaterializationItem,
    RetrievalRuntimeRepository,
)
from app.services.vector_integrity import payload_sha256, point_payload, vector_sha256

_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_INDEX_RUNNING_TIMEOUT_SECONDS = 90
_INDEX_RECOVERY_TIMEOUT_SECONDS = 180


class KnowledgeCrashRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _IndexProfile:
    run_id: str
    knowledge_base_id: UUID
    policy_id: UUID
    index_id: UUID
    job_id: UUID
    member_count: int
    manifest_sha256: str


def _validate_run_id(run_id: str) -> None:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise KnowledgeCrashRecoveryError("RUN_ID_INVALID")


def _lock_application_name(run_id: str) -> str:
    _validate_run_id(run_id)
    identity = f"finaudit-knowledge-crash-{run_id}"
    if len(identity.encode("ascii")) > 63:
        raise KnowledgeCrashRecoveryError("LOCK_IDENTITY_INVALID")
    return identity


def _reviewer_credentials(
    admin_password: str, run_id: str, kind: str
) -> tuple[str, str]:
    _validate_run_id(run_id)
    prefix = {"submitter": "submit", "approver": "approve"}.get(kind)
    if prefix is None:
        raise KnowledgeCrashRecoveryError("REVIEWER_KIND_INVALID")
    digest = hashlib.sha256(
        f"{admin_password}\0{run_id}\0knowledge-crash-{kind}".encode()
    ).hexdigest()
    return f"knowledge-crash-{prefix}-{run_id[:12]}", f"Kx9!{digest[:24]}"


def _required_positive_integer(name: str) -> int:
    value = _required_environment(name)
    if not value.isascii() or not value.isdigit() or int(value) <= 0:
        raise KnowledgeCrashRecoveryError(f"{name}_INVALID")
    return int(value)


def _required_sha256(name: str) -> str:
    value = _required_environment(name)
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise KnowledgeCrashRecoveryError(f"{name}_INVALID")
    return value


def _run_id() -> str:
    run_id = _required_environment("FINAUDIT_CRASH_RUN_ID")
    _validate_run_id(run_id)
    return run_id


def _index_profile() -> _IndexProfile:
    return _IndexProfile(
        run_id=_run_id(),
        knowledge_base_id=_canonical_uuid(
            _required_environment("FINAUDIT_KNOWLEDGE_BASE_ID"),
            "KNOWLEDGE_BASE_ID_INVALID",
        ),
        policy_id=_canonical_uuid(
            _required_environment("FINAUDIT_POLICY_ID"), "POLICY_ID_INVALID"
        ),
        index_id=_canonical_uuid(
            _required_environment("FINAUDIT_INDEX_ID"), "INDEX_ID_INVALID"
        ),
        job_id=_canonical_uuid(
            _required_environment("FINAUDIT_INDEX_JOB_ID"), "INDEX_JOB_ID_INVALID"
        ),
        member_count=_required_positive_integer("FINAUDIT_INDEX_MEMBER_COUNT"),
        manifest_sha256=_required_sha256("FINAUDIT_INDEX_MANIFEST_SHA256"),
    )


def _expected_consistency(member_count: int) -> dict[str, object]:
    if type(member_count) is not int or member_count <= 0:
        raise KnowledgeCrashRecoveryError("MEMBER_COUNT_INVALID")
    return {
        "checked_point_count": member_count,
        "member_count_match": True,
        "payload_hash_match": True,
        "vector_hash_match": True,
    }


def _index_matches_profile(index: DocumentIndexVersion, profile: _IndexProfile) -> bool:
    return bool(
        index.id == profile.index_id
        and index.knowledge_base_id == profile.knowledge_base_id
        and index.member_count == profile.member_count
        and index.manifest_sha256 == profile.manifest_sha256
        and index.failure_code is None
    )


def _materialization_digest(items: tuple[MaterializationItem, ...]) -> str:
    digest = hashlib.sha256()
    for item in items:
        if item.vector_sha256 is None or item.payload_sha256 is None:
            raise KnowledgeCrashRecoveryError("INDEX_ITEM_NOT_MATERIALIZED")
        digest.update(
            (
                f"{item.point_id}:{item.content_sha256}:"
                f"{item.vector_sha256}:{item.payload_sha256}\n"
            ).encode("ascii")
        )
    return digest.hexdigest()


def _verify_materialized_points(
    settings: Settings,
    index: DocumentIndexVersion,
    items: tuple[MaterializationItem, ...],
) -> str:
    if not items or len(items) != index.member_count:
        raise KnowledgeCrashRecoveryError("INDEX_ITEM_CARDINALITY_INVALID")
    embedding = DeterministicHashEmbeddingAdapter(
        model_id=settings.embedding_model,
        vector_size=settings.qdrant_vector_size,
    )
    if (
        index.embedding_adapter_id != embedding.target.adapter_id
        or index.embedding_model_id != embedding.target.model_id
        or index.vector_dimension != settings.qdrant_vector_size
        or index.collection_name != settings.qdrant_collection
        or index.distance != settings.qdrant_distance
    ):
        raise KnowledgeCrashRecoveryError("INDEX_EMBEDDING_TARGET_DRIFT")
    expected_by_point: dict[UUID, tuple[str, str]] = {}
    for item in items:
        vector = embedding.embed_text(item.content_text)
        payload = point_payload(index.id, item.content_sha256)
        expected_hashes = (vector_sha256(vector), payload_sha256(payload))
        if (item.vector_sha256, item.payload_sha256) != expected_hashes:
            raise KnowledgeCrashRecoveryError("INDEX_ITEM_HASH_DRIFT")
        expected_by_point[item.point_id] = expected_hashes
    if len(expected_by_point) != len(items):
        raise KnowledgeCrashRecoveryError("INDEX_POINT_ID_DUPLICATE")

    vector_store = QdrantVectorAdapter(settings)
    observed: dict[UUID, QdrantStoredPoint] = {}
    try:
        point_ids = tuple(expected_by_point)
        for offset in range(0, len(point_ids), 256):
            for point in vector_store.retrieve(point_ids[offset : offset + 256]):
                if point.id in observed:
                    raise KnowledgeCrashRecoveryError("QDRANT_POINT_DUPLICATE")
                observed[point.id] = point
    finally:
        vector_store.close()
    if set(observed) != set(expected_by_point):
        raise KnowledgeCrashRecoveryError("QDRANT_POINT_CARDINALITY_INVALID")
    for point_id, point in observed.items():
        if (
            vector_sha256(point.vector),
            payload_sha256(point.payload),
        ) != expected_by_point[point_id]:
            raise KnowledgeCrashRecoveryError("QDRANT_POINT_HASH_DRIFT")
    return _materialization_digest(items)


def seed_database() -> None:
    settings = Settings()
    run_id = _run_id()
    admin_username = _required_environment("BOOTSTRAP_ADMIN_USERNAME")
    knowledge_base_id = _stable_id(run_id, "knowledge-base")
    engine = create_application_engine(settings)
    try:
        factory = create_session_factory(engine)
        with factory.begin() as session:
            actor = session.scalar(
                select(User).where(
                    User.username == admin_username, User.deleted_at.is_(None)
                )
            )
            if actor is None or actor.status != "active":
                raise KnowledgeCrashRecoveryError("ADMIN_SUBJECT_INVALID")
            if session.get(KnowledgeBase, knowledge_base_id) is not None:
                raise KnowledgeCrashRecoveryError("KNOWLEDGE_SEED_COLLISION")
            now = session.scalar(select(func.clock_timestamp()))
            if now is None:
                raise KnowledgeCrashRecoveryError("DATABASE_CLOCK_UNAVAILABLE")
            session.add(
                KnowledgeBase(
                    id=knowledge_base_id,
                    organization_id=actor.organization_id,
                    code=f"CRASH-KB-{run_id[:12].upper()}",
                    name="本地知识索引崩溃恢复知识库",
                    description="仅用于隔离的 Qdrant 与 PostgreSQL 崩溃恢复门禁",
                    status="active",
                    default_top_k=5,
                    default_score_threshold=None,
                    row_version=1,
                    created_at=now,
                    created_by=actor.id,
                    updated_at=now,
                    updated_by=actor.id,
                    deleted_at=None,
                    deleted_by=None,
                    delete_reason=None,
                )
            )
    finally:
        engine.dispose()
    print(f"LOCAL_KNOWLEDGE_INDEX_KNOWLEDGE_BASE_ID={knowledge_base_id}")
    print("LOCAL_KNOWLEDGE_INDEX_SEED_GATE=PASS")


def run_prepare_policy_client() -> None:
    base_url, origin, admin_username, run_id = _client_profile()
    bootstrap_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    submitter_username, submitter_password = _reviewer_credentials(
        bootstrap_password, run_id, "submitter"
    )
    approver_username, approver_password = _reviewer_credentials(
        bootstrap_password, run_id, "approver"
    )
    knowledge_base_id = _stable_id(run_id, "knowledge-base")
    pdf = _prompt_injection_pdf(run_id)
    with _client(base_url, origin) as client:
        admin_token = _login(client, admin_username, bootstrap_password)
        _create_user(
            client,
            admin_token=admin_token,
            run_id=run_id,
            kind="knowledge-crash-submitter",
            username=submitter_username,
            password=submitter_password,
            role="audit_reviewer",
        )
        _create_user(
            client,
            admin_token=admin_token,
            run_id=run_id,
            kind="knowledge-crash-approver",
            username=approver_username,
            password=approver_password,
            role="audit_reviewer",
        )
        submitter_token = _login(client, submitter_username, submitter_password)
        approver_token = _login(client, approver_username, approver_password)
        upload = _require_success(
            client.post(
                "/api/v1/files",
                headers=_mutation_headers(
                    submitter_token, run_id, "knowledge-crash-upload"
                ),
                data={
                    "intended_business_type": "policy",
                    "target_knowledge_base_id": str(knowledge_base_id),
                    "auto_process_requested": "true",
                },
                files={
                    "file": (
                        f"knowledge-index-crash-{run_id[:12]}.pdf",
                        pdf,
                        "application/pdf",
                    )
                },
            ),
            202,
        )
        file_id = upload.get("file_id")
        if type(file_id) is not str:
            raise KnowledgeCrashRecoveryError("FILE_ID_INVALID")
        file_data = _poll_data(
            client,
            f"/api/v1/files/{file_id}",
            _authorization(submitter_token),
            ready=lambda value: value.get("job_status") == "succeeded",
            failed=lambda value: value.get("job_status") in {"failed", "cancelled"},
        )
        if (
            file_data.get("status") != "stored"
            or file_data.get("security_scan_status") != "clean"
        ):
            raise KnowledgeCrashRecoveryError("FILE_PROCESSING_INVALID")
        created = _require_success(
            client.post(
                "/api/v1/policy-documents",
                headers=_mutation_headers(
                    submitter_token, run_id, "knowledge-crash-policy-create"
                ),
                json={
                    "knowledge_base_id": str(knowledge_base_id),
                    "source_file_id": file_id,
                    "policy_code": f"CRASH-{run_id[:12].upper()}",
                    "name": "本地知识索引崩溃恢复制度",
                    "version": "1.0",
                    "issuing_department": "本地可靠性测试部",
                    "effective_from": "2026-01-01",
                    "effective_to": None,
                    "scope": {"environment": "local-crash-recovery"},
                },
            ),
            201,
        )
        policy = created.get("policy")
        if type(policy) is not dict or type(policy.get("id")) is not str:
            raise KnowledgeCrashRecoveryError("POLICY_CREATE_INVALID")
        policy_id = _canonical_uuid(policy["id"], "POLICY_ID_INVALID")
        submitted = _require_success(
            client.post(
                f"/api/v1/policy-documents/{policy_id}/submit-review",
                headers=_mutation_headers(
                    submitter_token, run_id, "knowledge-crash-policy-submit"
                ),
                json={"row_version": "1", "reason": "提交知识索引崩溃恢复制度审批"},
            ),
            200,
        )
        submitted_policy = submitted.get("policy")
        if (
            type(submitted_policy) is not dict
            or type(submitted_policy.get("row_version")) is not str
        ):
            raise KnowledgeCrashRecoveryError("POLICY_SUBMIT_INVALID")
        approved = _require_success(
            client.post(
                f"/api/v1/policy-documents/{policy_id}/approve",
                headers=_mutation_headers(
                    approver_token, run_id, "knowledge-crash-policy-approve"
                ),
                json={
                    "row_version": submitted_policy["row_version"],
                    "reason": "独立批准知识索引崩溃恢复制度",
                },
            ),
            200,
        )
        approved_policy = approved.get("policy")
        approved_chunk_set = approved.get("chunk_set")
        if (
            type(approved_policy) is not dict
            or approved_policy.get("id") != str(policy_id)
            or approved_policy.get("status") != "business_approved"
            or type(approved_chunk_set) is not dict
            or approved_chunk_set.get("status") != "active"
        ):
            raise KnowledgeCrashRecoveryError("POLICY_APPROVE_INVALID")
    print(f"LOCAL_KNOWLEDGE_INDEX_POLICY_ID={policy_id}")
    print("LOCAL_KNOWLEDGE_INDEX_POLICY_READY_GATE=PASS")


def run_queue_index_client() -> None:
    base_url, origin, admin_username, run_id = _client_profile()
    bootstrap_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    knowledge_base_id = _canonical_uuid(
        _required_environment("FINAUDIT_KNOWLEDGE_BASE_ID"),
        "KNOWLEDGE_BASE_ID_INVALID",
    )
    if knowledge_base_id != _stable_id(run_id, "knowledge-base"):
        raise KnowledgeCrashRecoveryError("KNOWLEDGE_BASE_ID_DRIFT")
    with _client(base_url, origin) as client:
        admin_token = _login(client, admin_username, bootstrap_password)
        index = _require_success(
            client.post(
                f"/api/v1/knowledge-bases/{knowledge_base_id}/index-versions",
                headers=_mutation_headers(
                    admin_token, run_id, "knowledge-crash-index-build"
                ),
                json={},
            ),
            202,
        )
    index_id = _canonical_uuid(index.get("id"), "INDEX_ID_INVALID")
    job_id = _canonical_uuid(index.get("job_id"), "INDEX_JOB_ID_INVALID")
    member_count = index.get("member_count")
    manifest_sha256 = index.get("manifest_sha256")
    if (
        index.get("knowledge_base_id") != str(knowledge_base_id)
        or index.get("version_no") != 1
        or index.get("status") != "building"
        or type(member_count) is not int
        or member_count <= 0
        or type(manifest_sha256) is not str
        or _SHA256_PATTERN.fullmatch(manifest_sha256) is None
        or index.get("consistency") != {}
        or index.get("failure_code") is not None
        or index.get("row_version") != "1"
        or index.get("job_status") != "queued"
    ):
        raise KnowledgeCrashRecoveryError("INDEX_QUEUE_RESULT_INVALID")
    print(f"LOCAL_KNOWLEDGE_INDEX_ID={index_id}")
    print(f"LOCAL_KNOWLEDGE_INDEX_JOB_ID={job_id}")
    print(f"LOCAL_KNOWLEDGE_INDEX_MEMBER_COUNT={member_count}")
    print(f"LOCAL_KNOWLEDGE_INDEX_MANIFEST_SHA256={manifest_sha256}")
    print("LOCAL_KNOWLEDGE_INDEX_QUEUE_GATE=PASS")


def run_wait_for_index_running() -> None:
    profile = _index_profile()
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        deadline = time.monotonic() + _INDEX_RUNNING_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with factory() as session:
                index = session.get(DocumentIndexVersion, profile.index_id)
                job = session.get(AsyncJob, profile.job_id)
                steps = tuple(
                    session.scalars(
                        select(AsyncJobStep)
                        .where(AsyncJobStep.job_id == profile.job_id)
                        .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                    ).all()
                )
                if job is not None and job.status in {
                    "succeeded",
                    "failed",
                    "cancelled",
                }:
                    raise KnowledgeCrashRecoveryError("INDEX_FINISHED_BEFORE_CRASH")
                if (
                    index is not None
                    and _index_matches_profile(index, profile)
                    and index.status == "building"
                    and index.consistency_json == {}
                    and index.row_version == 1
                    and job is not None
                    and job.status == "running"
                    and job.attempt_no == 1
                    and [
                        (step.attempt_no, step.step_code, step.status) for step in steps
                    ]
                    == [(1, "build_index", "running")]
                ):
                    print(f"LOCAL_KNOWLEDGE_INDEX_RUNNING_JOB_ID={job.id}")
                    print("LOCAL_KNOWLEDGE_INDEX_RUNNING_GATE=PASS")
                    return
            time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        engine.dispose()
    raise KnowledgeCrashRecoveryError("INDEX_RUNNING_TIMEOUT")


def _verify_pre_recovery_state(marker: str, *, verify_ready_log: bool) -> None:
    profile = _index_profile()
    settings = Settings()
    engine = create_application_engine(settings)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            index = session.get(DocumentIndexVersion, profile.index_id)
            job = session.get(AsyncJob, profile.job_id)
            steps = tuple(
                session.scalars(
                    select(AsyncJobStep)
                    .where(AsyncJobStep.job_id == profile.job_id)
                    .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                ).all()
            )
            items = RetrievalRuntimeRepository(session).materialization_items(
                profile.index_id
            )
            ready_log_count = (
                session.scalar(
                    select(func.count())
                    .select_from(OperationLog)
                    .where(
                        OperationLog.resource_type == "document_index_version",
                        OperationLog.resource_id == profile.index_id,
                        OperationLog.action_code == "knowledge.index_ready",
                    )
                )
                if verify_ready_log
                else None
            )
    finally:
        engine.dispose()
    if (
        index is None
        or not _index_matches_profile(index, profile)
        or index.status != "building"
        or index.consistency_json != {}
        or index.row_version != 1
        or job is None
        or job.status != "running"
        or job.attempt_no != 1
        or [(step.attempt_no, step.step_code, step.status) for step in steps]
        != [(1, "build_index", "running")]
        or (verify_ready_log and ready_log_count != 0)
    ):
        raise KnowledgeCrashRecoveryError("PRE_RECOVERY_DATABASE_STATE_INVALID")
    digest = _verify_materialized_points(settings, index, items)
    print(f"LOCAL_KNOWLEDGE_INDEX_MATERIALIZATION_SHA256={digest}")
    print(marker)


def run_verify_materialized_before_crash() -> None:
    _verify_pre_recovery_state(
        "LOCAL_KNOWLEDGE_INDEX_MATERIALIZED_BEFORE_CRASH_GATE=PASS",
        verify_ready_log=False,
    )


def run_before_recovery_verification() -> None:
    _verify_pre_recovery_state(
        "LOCAL_KNOWLEDGE_INDEX_ORPHAN_POINTS_PRESERVED_GATE=PASS",
        verify_ready_log=True,
    )
    print("LOCAL_KNOWLEDGE_INDEX_ZERO_READY_FACTS_BEFORE_RECOVERY_GATE=PASS")


def run_verify_client() -> None:
    base_url, origin, admin_username, run_id = _client_profile()
    profile = _index_profile()
    if profile.run_id != run_id:
        raise KnowledgeCrashRecoveryError("RUN_ID_DRIFT")
    bootstrap_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    with _client(base_url, origin) as client:
        admin_token = _login(client, admin_username, bootstrap_password)
        authorization = _authorization(admin_token)
        deadline = time.monotonic() + _INDEX_RECOVERY_TIMEOUT_SECONDS
        ready_index: dict[str, object] | None = None
        while time.monotonic() < deadline:
            current = _require_success(
                client.get(
                    f"/api/v1/knowledge-bases/{profile.knowledge_base_id}/"
                    f"index-versions/{profile.index_id}",
                    headers=authorization,
                ),
                200,
            )
            if current.get("status") == "failed" or current.get("job_status") in {
                "failed",
                "cancelled",
            }:
                raise KnowledgeCrashRecoveryError("INDEX_RECOVERY_FAILED")
            if (
                current.get("status") == "ready"
                and current.get("job_status") == "succeeded"
            ):
                ready_index = current
                break
            time.sleep(_POLL_INTERVAL_SECONDS)
    if ready_index is None:
        raise KnowledgeCrashRecoveryError("INDEX_RECOVERY_TIMEOUT")
    if (
        ready_index.get("id") != str(profile.index_id)
        or ready_index.get("knowledge_base_id") != str(profile.knowledge_base_id)
        or ready_index.get("version_no") != 1
        or ready_index.get("status") != "ready"
        or ready_index.get("member_count") != profile.member_count
        or ready_index.get("manifest_sha256") != profile.manifest_sha256
        or ready_index.get("consistency") != _expected_consistency(profile.member_count)
        or ready_index.get("failure_code") is not None
        or ready_index.get("row_version") != "2"
        or ready_index.get("job_id") != str(profile.job_id)
        or ready_index.get("job_status") != "succeeded"
        or ready_index.get("activated_at") is not None
    ):
        raise KnowledgeCrashRecoveryError("INDEX_CLIENT_RESULT_INVALID")
    print("LOCAL_KNOWLEDGE_INDEX_CRASH_CLIENT_GATE=PASS")


def run_final_database_verification() -> None:
    profile = _index_profile()
    settings = Settings()
    engine = create_application_engine(settings)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            indexes = tuple(
                session.scalars(
                    select(DocumentIndexVersion).where(
                        DocumentIndexVersion.knowledge_base_id
                        == profile.knowledge_base_id
                    )
                ).all()
            )
            job = session.get(AsyncJob, profile.job_id)
            steps = tuple(
                session.scalars(
                    select(AsyncJobStep)
                    .where(AsyncJobStep.job_id == profile.job_id)
                    .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                ).all()
            )
            outbox = tuple(
                session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_type == "async_job",
                        OutboxEvent.aggregate_id == profile.job_id,
                    )
                ).all()
            )
            logs = tuple(
                session.scalars(
                    select(OperationLog)
                    .where(
                        OperationLog.resource_type == "document_index_version",
                        OperationLog.resource_id == profile.index_id,
                    )
                    .order_by(OperationLog.created_at, OperationLog.id)
                ).all()
            )
            items = RetrievalRuntimeRepository(session).materialization_items(
                profile.index_id
            )
            policy_item_count = session.scalar(
                select(func.count())
                .select_from(DocumentIndexItem)
                .where(
                    DocumentIndexItem.index_version_id == profile.index_id,
                    DocumentIndexItem.policy_document_id == profile.policy_id,
                )
            )
    finally:
        engine.dispose()
    if (
        len(indexes) != 1
        or indexes[0].id != profile.index_id
        or job is None
        or len(steps) != 2
        or len(outbox) != 1
        or outbox[0].status != "published"
        or policy_item_count != profile.member_count
    ):
        raise KnowledgeCrashRecoveryError("FINAL_INDEX_CLUSTER_CARDINALITY_INVALID")
    index = indexes[0]
    if (
        not _index_matches_profile(index, profile)
        or index.status != "ready"
        or index.consistency_json != _expected_consistency(profile.member_count)
        or index.row_version != 2
        or index.activated_by is not None
        or index.activated_at is not None
        or index.superseded_at is not None
    ):
        raise KnowledgeCrashRecoveryError("FINAL_INDEX_ROW_INVALID")
    expected_summary: dict[str, object] = {
        "index_version_id": str(profile.index_id),
        "manifest_sha256": profile.manifest_sha256,
        "member_count": profile.member_count,
    }
    if (
        job.job_type != "knowledge_index_build"
        or job.resource_type != "document_index_version"
        or job.resource_id != profile.index_id
        or job.status != "succeeded"
        or job.attempt_no != 2
        or job.stage != "build_index"
        or job.current_attempt_start_step_code != "build_index"
        or job.input_json
        != {
            "knowledge_base_id": str(profile.knowledge_base_id),
            "index_version_id": str(profile.index_id),
        }
        or job.error_code is not None
        or job.error_message is not None
    ):
        raise KnowledgeCrashRecoveryError("FINAL_INDEX_JOB_INVALID")
    if [
        (
            step.attempt_no,
            step.step_code,
            step.status,
            step.error_code,
            step.summary_json,
        )
        for step in steps
    ] != [
        (1, "build_index", "failed", "LEASE_EXPIRED", {}),
        (2, "build_index", "succeeded", None, expected_summary),
    ]:
        raise KnowledgeCrashRecoveryError("FINAL_INDEX_ATTEMPT_HISTORY_INVALID")
    if [log.action_code for log in logs] != [
        "knowledge.index_build_queued",
        "knowledge.index_ready",
    ]:
        raise KnowledgeCrashRecoveryError("FINAL_INDEX_OPERATION_LOG_INVALID")
    if [log.change_summary_json for log in logs] != [
        {
            "manifest_sha256": profile.manifest_sha256,
            "member_count": profile.member_count,
            "status": "building",
        },
        {
            "manifest_sha256": profile.manifest_sha256,
            "member_count": profile.member_count,
            "status": "ready",
        },
    ]:
        raise KnowledgeCrashRecoveryError("FINAL_INDEX_OPERATION_SUMMARY_INVALID")
    ready_log = logs[1]
    if ready_log.trace_id != job.trace_id or ready_log.outcome != "succeeded":
        raise KnowledgeCrashRecoveryError("FINAL_INDEX_READY_LOG_INVALID")
    digest = _verify_materialized_points(settings, index, items)
    print(f"LOCAL_KNOWLEDGE_INDEX_FINAL_MATERIALIZATION_SHA256={digest}")
    print("LOCAL_KNOWLEDGE_INDEX_ATTEMPT_HISTORY_DATABASE_GATE=PASS")
    print("LOCAL_KNOWLEDGE_INDEX_UNIQUE_FACTS_DATABASE_GATE=PASS")
    print("LOCAL_KNOWLEDGE_INDEX_CRASH_DATABASE_GATE=PASS")


def main() -> int:
    try:
        if sys.argv == [sys.argv[0], "seed"]:
            seed_database()
        elif sys.argv == [sys.argv[0], "prepare-policy"]:
            run_prepare_policy_client()
        elif sys.argv == [sys.argv[0], "queue-index"]:
            run_queue_index_client()
        elif sys.argv == [sys.argv[0], "wait-running"]:
            run_wait_for_index_running()
        elif sys.argv == [sys.argv[0], "verify-materialized"]:
            run_verify_materialized_before_crash()
        elif sys.argv == [sys.argv[0], "before-recovery"]:
            run_before_recovery_verification()
        elif sys.argv == [sys.argv[0], "verify-client"]:
            run_verify_client()
        elif sys.argv == [sys.argv[0], "database"]:
            run_final_database_verification()
        else:
            raise KnowledgeCrashRecoveryError("ARGUMENTS_INVALID")
    except (
        CrashRecoveryError,
        KnowledgeCrashRecoveryError,
        SecurityGateError,
        SmokeError,
    ) as error:
        print("LOCAL_KNOWLEDGE_INDEX_CRASH_RECOVERY=FAIL")
        print(f"LOCAL_KNOWLEDGE_INDEX_CRASH_REASON={error}")
        return 1
    except Exception as error:
        print("LOCAL_KNOWLEDGE_INDEX_CRASH_RECOVERY=FAIL")
        print(
            f"LOCAL_KNOWLEDGE_INDEX_CRASH_REASON=UNEXPECTED_{type(error).__name__.upper()}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
