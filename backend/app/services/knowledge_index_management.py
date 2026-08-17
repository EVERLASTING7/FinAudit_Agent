"""候选索引、评测数据集、评测运行与技术激活用例。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.adapters.deterministic_hash import DETERMINISTIC_HASH_ADAPTER_ID
from app.core.config import Settings
from app.core.errors import AppError
from app.models.reliability import (
    JOB_LEASE_POLICY_HASH,
    JOB_LEASE_POLICY_VERSION,
    JOB_RETRY_POLICY_HASH,
    JOB_RETRY_POLICY_VERSION,
    AsyncJob,
    OutboxEvent,
)
from app.models.retrieval import (
    DocumentIndexItem,
    DocumentIndexVersion,
    RetrievalEvalCase,
    RetrievalEvalDataset,
    RetrievalEvalRun,
)
from app.repositories.operation_log import OperationLogRepository
from app.repositories.retrieval_runtime import RetrievalRuntimeRepository
from app.repositories.user_write import IdempotencyClaim
from app.schemas.retrieval import (
    EvaluationDatasetCreateRequest,
    EvaluationDatasetData,
    EvaluationRunData,
    EvaluationRunRequest,
    EvaluationTier,
    IndexStatus,
    IndexVersionData,
    VersionedTransitionRequest,
)
from app.services.auth import AuthenticatedActor
from app.workers.knowledge_handler_registry import (
    KNOWLEDGE_INPUT_SCHEMA_VERSION,
    KnowledgeJobType,
    load_knowledge_handler,
)

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_IDEMPOTENCY_TTL = timedelta(hours=24)
_GENERATOR_ID = "deterministic_citation_v1"
_TIER_MINIMUMS = {
    EvaluationTier.SMOKE: 5,
    EvaluationTier.MVP_UAT: 50,
    EvaluationTier.FORMAL_RELEASE: 100,
}


@dataclass(frozen=True, slots=True)
class IndexMutationResult:
    data: IndexVersionData
    replayed: bool
    status_code: int


@dataclass(frozen=True, slots=True)
class DatasetMutationResult:
    data: EvaluationDatasetData
    replayed: bool
    status_code: int


@dataclass(frozen=True, slots=True)
class EvaluationRunMutationResult:
    data: EvaluationRunData
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


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _request_hash(method: str, path: str, body: dict[str, object]) -> str:
    return hashlib.sha256(
        _canonical_json({"body": body, "method": method, "path": path})
    ).hexdigest()


def _project_index(
    repository: RetrievalRuntimeRepository, index: DocumentIndexVersion
) -> IndexVersionData:
    job = repository.job_for_resource("document_index_version", index.id)
    return IndexVersionData(
        id=index.id,
        knowledge_base_id=index.knowledge_base_id,
        version_no=index.version_no,
        status=IndexStatus(index.status),
        collection_name=index.collection_name,
        embedding_adapter_id=index.embedding_adapter_id,
        embedding_model_id=index.embedding_model_id,
        vector_dimension=index.vector_dimension,
        distance=index.distance,
        member_count=index.member_count,
        manifest_sha256=index.manifest_sha256,
        consistency=dict(index.consistency_json),
        failure_code=index.failure_code,
        row_version=str(index.row_version),
        job_id=None if job is None else job.id,
        job_status=None if job is None else job.status,
        created_at=index.created_at,
        activated_at=index.activated_at,
    )


def _project_dataset(dataset: RetrievalEvalDataset) -> EvaluationDatasetData:
    return EvaluationDatasetData(
        id=dataset.id,
        knowledge_base_id=dataset.knowledge_base_id,
        version_no=dataset.version_no,
        name=dataset.name,
        tier=EvaluationTier(dataset.tier),
        status=dataset.status,
        answer_score_threshold=format(dataset.answer_score_threshold, "f"),
        case_count=dataset.case_count,
        manifest_sha256=dataset.manifest_sha256,
        submitted_by=dataset.submitted_by,
        submitted_at=dataset.submitted_at,
        approved_by=dataset.approved_by,
        approved_at=dataset.approved_at,
        row_version=str(dataset.row_version),
    )


def _project_run(
    repository: RetrievalRuntimeRepository, run: RetrievalEvalRun
) -> EvaluationRunData:
    job = repository.job_for_resource("retrieval_eval_run", run.id)
    if job is None:
        raise RuntimeError("evaluation run has no job")
    return EvaluationRunData(
        id=run.id,
        knowledge_base_id=run.knowledge_base_id,
        index_version_id=run.index_version_id,
        dataset_id=run.dataset_id,
        tier=EvaluationTier(run.tier),
        status=run.status,
        case_count=run.case_count,
        completed_case_count=run.completed_case_count,
        metrics=dict(run.metrics_json),
        failure_code=run.failure_code,
        job_id=job.id,
        job_status=job.status,
    )


def _new_job(
    *,
    organization_id: UUID,
    actor_id: UUID,
    trace_id: UUID,
    job_type: KnowledgeJobType,
    resource_type: str,
    resource_id: UUID,
    input_json: dict[str, object],
    idempotency_record_id: UUID,
    now: datetime,
) -> tuple[AsyncJob, OutboxEvent]:
    handler = load_knowledge_handler(job_type)
    handler.validate_input(input_json)
    job = AsyncJob(
        id=uuid4(),
        organization_id=organization_id,
        job_type=job_type,
        resource_type=resource_type,
        resource_id=resource_id,
        status="queued",
        stage=None,
        attempt_no=0,
        max_attempts=handler.handler.max_attempts,
        current_attempt_start_step_code=handler.handler.steps[0].step_code,
        input_hash=hashlib.sha256(_canonical_json(input_json)).hexdigest(),
        input_json=input_json,
        input_schema_version=KNOWLEDGE_INPUT_SCHEMA_VERSION,
        idempotency_record_id=idempotency_record_id,
        handler_registry_version=handler.registry_version,
        handler_registry_hash=handler.registry_hash,
        retry_policy_version=JOB_RETRY_POLICY_VERSION,
        retry_policy_hash=JOB_RETRY_POLICY_HASH,
        lease_policy_version=JOB_LEASE_POLICY_VERSION,
        lease_policy_hash=JOB_LEASE_POLICY_HASH,
        row_version=1,
        trace_id=trace_id,
        created_by=actor_id,
        created_at=now,
    )
    outbox = OutboxEvent(
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
    return job, outbox


class KnowledgeIndexManagementService:
    def __init__(self, session_factory: sessionmaker[Session], settings: Settings) -> None:
        self._session_factory = session_factory
        self._collection_name = settings.qdrant_collection
        self._vector_dimension = settings.qdrant_vector_size
        self._distance = settings.qdrant_distance
        self._embedding_model_id = settings.embedding_model

    def build_index(
        self,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        idempotency_key: str,
        trace_id: UUID,
    ) -> IndexMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/knowledge-bases/{knowledge_base_id}/index-versions"
        digest = _request_hash("POST", path, {})
        try:
            with self._session_factory.begin() as session:
                repository, claim, now = self._claim(
                    session, actor, idempotency_key, "POST", path, digest
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._replay_index(claim)
                if repository.lock_knowledge_base(actor.organization_id, knowledge_base_id) is None:
                    raise _not_found()
                members = repository.frozen_index_members(knowledge_base_id)
                if not members:
                    raise _conflict("INDEX_MEMBERS_EMPTY", "知识库没有可索引的活动分块")
                if len(members) > 10_000:
                    raise _conflict("INDEX_MEMBERS_LIMIT_EXCEEDED", "候选索引成员超过上限")
                manifest = [
                    {
                        "chunk_id": str(member.chunk_id),
                        "chunk_set_id": str(member.chunk_set_id),
                        "content_sha256": member.content_sha256,
                        "markdown_version_id": str(member.markdown_version_id),
                        "policy_id": str(member.policy_id),
                    }
                    for member in members
                ]
                manifest_sha256 = hashlib.sha256(_canonical_json(manifest)).hexdigest()
                index_id = uuid4()
                index = DocumentIndexVersion(
                    id=index_id,
                    organization_id=actor.organization_id,
                    knowledge_base_id=knowledge_base_id,
                    version_no=repository.next_index_version_no(knowledge_base_id),
                    status="building",
                    collection_name=self._collection_name,
                    embedding_adapter_id=DETERMINISTIC_HASH_ADAPTER_ID,
                    embedding_model_id=self._embedding_model_id,
                    vector_dimension=self._vector_dimension,
                    distance=self._distance,
                    member_count=len(members),
                    manifest_sha256=manifest_sha256,
                    consistency_json={},
                    failure_code=None,
                    row_version=1,
                    created_by=actor.user_id,
                    created_at=now,
                    activated_by=None,
                    activated_at=None,
                    superseded_at=None,
                    trace_id=trace_id,
                )
                items = tuple(
                    DocumentIndexItem(
                        id=uuid4(),
                        organization_id=actor.organization_id,
                        knowledge_base_id=knowledge_base_id,
                        index_version_id=index_id,
                        policy_document_id=member.policy_id,
                        markdown_version_id=member.markdown_version_id,
                        chunk_set_id=member.chunk_set_id,
                        chunk_id=member.chunk_id,
                        qdrant_point_id=uuid5(index_id, str(member.chunk_id)),
                        content_sha256=member.content_sha256,
                        vector_sha256=None,
                        payload_sha256=None,
                        vector_dimension=self._vector_dimension,
                        created_at=now,
                    )
                    for member in members
                )
                repository.add(index)
                repository.flush()
                repository.add_all(items)
                repository.flush()
                input_json: dict[str, object] = {
                    "knowledge_base_id": str(knowledge_base_id),
                    "index_version_id": str(index.id),
                }
                job, outbox = _new_job(
                    organization_id=actor.organization_id,
                    actor_id=actor.user_id,
                    trace_id=trace_id,
                    job_type="knowledge_index_build",
                    resource_type="document_index_version",
                    resource_id=index.id,
                    input_json=input_json,
                    idempotency_record_id=claim.record.id,
                    now=now,
                )
                repository.add(job)
                repository.add(outbox)
                repository.flush()
                data = _project_index(repository, index)
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="knowledge.index_build_queued",
                    outcome="succeeded",
                    resource_type="document_index_version",
                    resource_id=index.id,
                    trace_id=trace_id,
                    change_summary={
                        "manifest_sha256": manifest_sha256,
                        "member_count": len(members),
                        "status": "building",
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_status=202,
                    response_body=data.model_dump(mode="json"),
                    resource_type="document_index_version",
                    resource_id=index.id,
                )
                return IndexMutationResult(data, False, 202)
        except IntegrityError as error:
            raise self._integrity_error(error) from None

    def get_index(
        self,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        index_version_id: UUID,
    ) -> IndexVersionData:
        with self._session_factory() as session:
            repository = RetrievalRuntimeRepository(session)
            index = repository.get_index(actor.organization_id, knowledge_base_id, index_version_id)
            if index is None:
                raise _not_found()
            return _project_index(repository, index)

    def activate_index(
        self,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        index_version_id: UUID,
        payload: VersionedTransitionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> IndexMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = (
            f"/api/v1/knowledge-bases/{knowledge_base_id}/index-versions/"
            f"{index_version_id}/activate"
        )
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        with self._session_factory.begin() as session:
            repository, claim, now = self._claim(
                session, actor, idempotency_key, "POST", path, digest
            )
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return self._replay_index(claim)
            if repository.lock_knowledge_base(actor.organization_id, knowledge_base_id) is None:
                raise _not_found()
            index = repository.lock_index(actor.organization_id, index_version_id)
            if index is None or index.knowledge_base_id != knowledge_base_id:
                raise _not_found()
            if index.row_version != int(payload.row_version):
                raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
            if index.status != "ready":
                raise _conflict("INDEX_STATE_CONFLICT", "当前索引状态不可激活")
            if repository.formal_passed_run(index.id) is None:
                raise _conflict("FORMAL_EVALUATION_REQUIRED", "正式评测门禁尚未通过")
            if not repository.activate_index(index, actor_id=actor.user_id, activated_at=now):
                raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
            data = _project_index(repository, index)
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code="knowledge.index_activated",
                outcome="succeeded",
                resource_type="document_index_version",
                resource_id=index.id,
                trace_id=trace_id,
                change_summary={
                    "from_status": "ready",
                    "row_version": str(index.row_version),
                    "to_status": "active",
                },
            )
            repository.complete_idempotency(
                claim,
                response_status=200,
                response_body=data.model_dump(mode="json"),
                resource_type="document_index_version",
                resource_id=index.id,
            )
            return IndexMutationResult(data, False, 200)

    def create_dataset(
        self,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        payload: EvaluationDatasetCreateRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> DatasetMutationResult:
        _validate_idempotency_key(idempotency_key)
        minimum = _TIER_MINIMUMS[payload.tier]
        if len(payload.cases) < minimum:
            raise _conflict("EVALUATION_CASE_GATE_FAILED", "评测用例数未达到所选层级")
        path = f"/api/v1/knowledge-bases/{knowledge_base_id}/retrieval-eval-datasets"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository, claim, now = self._claim(
                    session, actor, idempotency_key, "POST", path, digest
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._replay_dataset(claim)
                if repository.lock_knowledge_base(actor.organization_id, knowledge_base_id) is None:
                    raise _not_found()
                canonical_cases: list[dict[str, object]] = []
                seen_queries: set[str] = set()
                for case in payload.cases:
                    query_sha256 = hashlib.sha256(case.query_text.encode("utf-8")).hexdigest()
                    if query_sha256 in seen_queries:
                        raise _conflict("EVALUATION_CASE_DUPLICATE", "评测查询不得重复")
                    seen_queries.add(query_sha256)
                    allowed = tuple(sorted(case.allowed_policy_ids, key=str))
                    expected = tuple(sorted(case.expected_chunk_ids, key=str))
                    forbidden = tuple(sorted(case.forbidden_chunk_ids, key=str))
                    if not repository.validate_case_references(
                        knowledge_base_id=knowledge_base_id,
                        allowed_policy_ids=allowed,
                        expected_chunk_ids=expected,
                        forbidden_chunk_ids=forbidden,
                    ):
                        raise _conflict(
                            "EVALUATION_GROUND_TRUTH_INVALID",
                            "评测用例引用不属于当前知识库活动事实",
                        )
                    canonical_cases.append(
                        {
                            "allowed_policy_ids": [str(value) for value in allowed],
                            "baseline_date": case.baseline_date.isoformat(),
                            "expected_chunk_ids": [str(value) for value in expected],
                            "forbidden_chunk_ids": [str(value) for value in forbidden],
                            "label": case.label.value,
                            "query_sha256": query_sha256,
                        }
                    )
                manifest_sha256 = hashlib.sha256(
                    _canonical_json(
                        {
                            "answer_score_threshold": payload.answer_score_threshold,
                            "cases": canonical_cases,
                            "tier": payload.tier.value,
                        }
                    )
                ).hexdigest()
                dataset = RetrievalEvalDataset(
                    id=uuid4(),
                    organization_id=actor.organization_id,
                    knowledge_base_id=knowledge_base_id,
                    version_no=repository.next_dataset_version_no(
                        knowledge_base_id, payload.tier.value
                    ),
                    name=payload.name,
                    tier=payload.tier.value,
                    status="draft",
                    answer_score_threshold=payload.threshold_decimal(),
                    case_count=len(payload.cases),
                    manifest_sha256=manifest_sha256,
                    row_version=1,
                    submitted_by=None,
                    submitted_at=None,
                    submission_reason=None,
                    approved_by=None,
                    approved_at=None,
                    approval_reason=None,
                    created_by=actor.user_id,
                    created_at=now,
                    trace_id=trace_id,
                )
                repository.add(dataset)
                repository.flush()
                cases = tuple(
                    RetrievalEvalCase(
                        id=uuid4(),
                        dataset_id=dataset.id,
                        case_no=index,
                        label=case.label.value,
                        query_text=case.query_text,
                        query_sha256=canonical_cases[index - 1]["query_sha256"],
                        baseline_date=case.baseline_date,
                        allowed_policy_ids=sorted(case.allowed_policy_ids, key=str),
                        expected_chunk_ids=sorted(case.expected_chunk_ids, key=str),
                        forbidden_chunk_ids=sorted(case.forbidden_chunk_ids, key=str),
                    )
                    for index, case in enumerate(payload.cases, start=1)
                )
                repository.add_all(cases)
                repository.flush()
                data = _project_dataset(dataset)
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="knowledge.eval_dataset_created",
                    outcome="succeeded",
                    resource_type="retrieval_eval_dataset",
                    resource_id=dataset.id,
                    trace_id=trace_id,
                    change_summary={
                        "case_count": dataset.case_count,
                        "row_version": str(dataset.row_version),
                        "status": "draft",
                        "tier": dataset.tier,
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_status=201,
                    response_body=data.model_dump(mode="json"),
                    resource_type="retrieval_eval_dataset",
                    resource_id=dataset.id,
                )
                return DatasetMutationResult(data, False, 201)
        except IntegrityError as error:
            raise self._integrity_error(error) from None

    def transition_dataset(
        self,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        dataset_id: UUID,
        payload: VersionedTransitionRequest,
        idempotency_key: str,
        trace_id: UUID,
        *,
        action: str,
    ) -> DatasetMutationResult:
        _validate_idempotency_key(idempotency_key)
        suffix = "submit-review" if action == "submit" else "approve"
        path = (
            f"/api/v1/knowledge-bases/{knowledge_base_id}/retrieval-eval-datasets/"
            f"{dataset_id}/{suffix}"
        )
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        with self._session_factory.begin() as session:
            repository, claim, now = self._claim(
                session, actor, idempotency_key, "POST", path, digest
            )
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return self._replay_dataset(claim)
            if repository.lock_knowledge_base(actor.organization_id, knowledge_base_id) is None:
                raise _not_found()
            dataset = repository.lock_dataset(actor.organization_id, dataset_id)
            if dataset is None or dataset.knowledge_base_id != knowledge_base_id:
                raise _not_found()
            if dataset.row_version != int(payload.row_version):
                raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
            expected_status = "draft" if action == "submit" else "submitted"
            target_status = "submitted" if action == "submit" else "approved"
            if dataset.status != expected_status:
                raise _conflict("EVALUATION_DATASET_STATE_CONFLICT", "当前评测集状态不可转换")
            if action == "approve" and dataset.submitted_by == actor.user_id:
                raise _conflict(
                    "EVALUATION_SELF_APPROVAL_FORBIDDEN",
                    "评测集提交人与批准人必须不同",
                )
            values: dict[str, object] = {"status": target_status}
            if action == "submit":
                values.update(
                    submitted_by=actor.user_id,
                    submitted_at=now,
                    submission_reason=payload.reason,
                )
            else:
                values.update(
                    approved_by=actor.user_id,
                    approved_at=now,
                    approval_reason=payload.reason,
                )
            if not repository.transition_dataset(
                dataset,
                expected_row_version=int(payload.row_version),
                values=values,
            ):
                raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
            data = _project_dataset(dataset)
            action_code = (
                "knowledge.eval_dataset_submitted"
                if action == "submit"
                else "knowledge.eval_dataset_approved"
            )
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code=action_code,
                outcome="succeeded",
                resource_type="retrieval_eval_dataset",
                resource_id=dataset.id,
                trace_id=trace_id,
                change_summary={
                    "case_count": dataset.case_count,
                    "row_version": str(dataset.row_version),
                    "status": target_status,
                    "tier": dataset.tier,
                },
            )
            repository.complete_idempotency(
                claim,
                response_status=200,
                response_body=data.model_dump(mode="json"),
                resource_type="retrieval_eval_dataset",
                resource_id=dataset.id,
            )
            return DatasetMutationResult(data, False, 200)

    def get_dataset(
        self,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        dataset_id: UUID,
    ) -> EvaluationDatasetData:
        with self._session_factory() as session:
            dataset = RetrievalRuntimeRepository(session).get_dataset(
                actor.organization_id,
                knowledge_base_id,
                dataset_id,
            )
            if dataset is None:
                raise _not_found()
            return _project_dataset(dataset)

    def create_evaluation_run(
        self,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        index_version_id: UUID,
        payload: EvaluationRunRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> EvaluationRunMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = (
            f"/api/v1/knowledge-bases/{knowledge_base_id}/index-versions/"
            f"{index_version_id}/evaluations"
        )
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        with self._session_factory.begin() as session:
            repository, claim, now = self._claim(
                session, actor, idempotency_key, "POST", path, digest
            )
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return self._replay_run(claim)
            if repository.lock_knowledge_base(actor.organization_id, knowledge_base_id) is None:
                raise _not_found()
            index = repository.lock_index(actor.organization_id, index_version_id)
            dataset = repository.lock_dataset(actor.organization_id, payload.dataset_id)
            if (
                index is None
                or dataset is None
                or index.knowledge_base_id != knowledge_base_id
                or dataset.knowledge_base_id != knowledge_base_id
            ):
                raise _not_found()
            if index.status not in {"ready", "active"}:
                raise _conflict("INDEX_STATE_CONFLICT", "索引尚未完成一致性校验")
            if dataset.status != "approved":
                raise _conflict("EVALUATION_DATASET_NOT_APPROVED", "评测集尚未独立批准")
            parameters = {
                "answer_score_threshold": format(dataset.answer_score_threshold, "f"),
                "collection_name": index.collection_name,
                "distance": index.distance,
                "top_k": 5,
                "vector_dimension": index.vector_dimension,
            }
            run = RetrievalEvalRun(
                id=uuid4(),
                organization_id=actor.organization_id,
                knowledge_base_id=knowledge_base_id,
                index_version_id=index.id,
                dataset_id=dataset.id,
                tier=dataset.tier,
                status="running",
                embedding_adapter_id=index.embedding_adapter_id,
                embedding_model_id=index.embedding_model_id,
                generator_id=_GENERATOR_ID,
                parameters_json=parameters,
                parameters_sha256=hashlib.sha256(_canonical_json(parameters)).hexdigest(),
                case_count=dataset.case_count,
                completed_case_count=0,
                metrics_json={},
                failure_code=None,
                created_by=actor.user_id,
                started_at=now,
                finished_at=None,
                trace_id=trace_id,
            )
            repository.add(run)
            repository.flush()
            input_json: dict[str, object] = {
                "dataset_id": str(dataset.id),
                "index_version_id": str(index.id),
                "knowledge_base_id": str(knowledge_base_id),
                "run_id": str(run.id),
            }
            job, outbox = _new_job(
                organization_id=actor.organization_id,
                actor_id=actor.user_id,
                trace_id=trace_id,
                job_type="retrieval_eval",
                resource_type="retrieval_eval_run",
                resource_id=run.id,
                input_json=input_json,
                idempotency_record_id=claim.record.id,
                now=now,
            )
            repository.add(job)
            repository.add(outbox)
            repository.flush()
            data = _project_run(repository, run)
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code="knowledge.eval_queued",
                outcome="succeeded",
                resource_type="retrieval_eval_run",
                resource_id=run.id,
                trace_id=trace_id,
                change_summary={
                    "case_count": run.case_count,
                    "passed": False,
                    "tier": run.tier,
                },
            )
            repository.complete_idempotency(
                claim,
                response_status=202,
                response_body=data.model_dump(mode="json"),
                resource_type="retrieval_eval_run",
                resource_id=run.id,
            )
            return EvaluationRunMutationResult(data, False, 202)

    def get_evaluation_run(
        self,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        run_id: UUID,
    ) -> EvaluationRunData:
        with self._session_factory() as session:
            repository = RetrievalRuntimeRepository(session)
            run = repository.get_run(actor.organization_id, knowledge_base_id, run_id)
            if run is None:
                raise _not_found()
            return _project_run(repository, run)

    @staticmethod
    def _claim(
        session: Session,
        actor: AuthenticatedActor,
        idempotency_key: str,
        method: str,
        path: str,
        digest: str,
    ) -> tuple[RetrievalRuntimeRepository, IdempotencyClaim, datetime]:
        repository = RetrievalRuntimeRepository(session)
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
    def _replay_index(claim: IdempotencyClaim) -> IndexMutationResult:
        if claim.replay_status not in {200, 202} or claim.replay_body is None:
            raise RuntimeError("index replay does not match the contract")
        data = IndexVersionData.model_validate_json(_canonical_json(claim.replay_body))
        return IndexMutationResult(data, True, claim.replay_status)

    @staticmethod
    def _replay_dataset(claim: IdempotencyClaim) -> DatasetMutationResult:
        if claim.replay_status not in {200, 201} or claim.replay_body is None:
            raise RuntimeError("dataset replay does not match the contract")
        data = EvaluationDatasetData.model_validate_json(_canonical_json(claim.replay_body))
        return DatasetMutationResult(data, True, claim.replay_status)

    @staticmethod
    def _replay_run(claim: IdempotencyClaim) -> EvaluationRunMutationResult:
        if claim.replay_status != 202 or claim.replay_body is None:
            raise RuntimeError("evaluation run replay does not match the contract")
        data = EvaluationRunData.model_validate_json(_canonical_json(claim.replay_body))
        return EvaluationRunMutationResult(data, True, claim.replay_status)

    @staticmethod
    def _integrity_error(error: IntegrityError) -> AppError:
        diagnostic = getattr(error.orig, "diag", None)
        constraint = getattr(diagnostic, "constraint_name", None)
        if constraint in {"uq_index_input_identity", "uq_eval_dataset_manifest"}:
            return _conflict("IMMUTABLE_INPUT_ALREADY_EXISTS", "相同不可变输入已经存在")
        return _conflict("WRITE_CONFLICT", "并发写入冲突")


__all__ = [
    "DatasetMutationResult",
    "EvaluationRunMutationResult",
    "IndexMutationResult",
    "KnowledgeIndexManagementService",
]
