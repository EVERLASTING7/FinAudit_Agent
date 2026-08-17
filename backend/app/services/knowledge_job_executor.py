"""知识索引与检索评测 Job 的 Qdrant I/O、fencing 和完成事实。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.qdrant_vector import (
    QdrantHit,
    QdrantPoint,
    QdrantStoredPoint,
    QdrantVectorStoreError,
)
from app.ai.adapters.deterministic_hash import DeterministicHashEmbeddingAdapter
from app.evaluation.retrieval_metrics import (
    EvidenceIdentity,
    RankedRetrievalHit,
    RetrievalCaseLabel,
    RetrievalCaseResult,
    calculate_no_answer_false_positive_rate,
    calculate_retrieval_metrics,
)
from app.models.retrieval import RetrievalEvalCase, RetrievalEvalResult
from app.repositories.job_runtime import ClaimedJob, JobRuntimeRepository, JobSnapshot
from app.repositories.operation_log import OperationLogRepository
from app.repositories.retrieval_runtime import MaterializationItem, RetrievalRuntimeRepository
from app.services.vector_integrity import payload_sha256, point_payload, vector_sha256
from app.workers.handler_registry import HandlerRegistryError
from app.workers.knowledge_handler_registry import (
    KnowledgeHandlerRuntime,
    KnowledgeJobType,
    load_knowledge_handler,
)


class VectorStore(Protocol):
    def upsert(self, points: tuple[QdrantPoint, ...]) -> None: ...

    def retrieve(self, point_ids: tuple[UUID, ...]) -> tuple[QdrantStoredPoint, ...]: ...

    def query_authorized(
        self,
        vector: tuple[float, ...],
        *,
        allowed_point_ids: tuple[UUID, ...],
        limit: int,
    ) -> tuple[QdrantHit, ...]: ...


class KnowledgeJobExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class KnowledgeJobExecutionResult:
    outcome: Literal["succeeded", "failed", "duplicate_or_stale"]
    job_id: UUID


@dataclass(frozen=True, slots=True)
class _CaseOutcome:
    case_id: UUID
    passed: bool
    authorization_leak: bool
    ranked_hits: list[object]
    miss_reason: str | None
    metric_case: RetrievalCaseResult | None


def _canonical_uuid(value: object) -> UUID:
    if type(value) is not str:
        raise ValueError
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError
    return parsed


class KnowledgeJobExecutor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        vector_store: VectorStore,
        embedding: DeterministicHashEmbeddingAdapter,
        *,
        embedding_batch_size: int,
    ) -> None:
        if not 1 <= embedding_batch_size <= 256:
            raise ValueError("embedding batch size is invalid")
        self._session_factory = session_factory
        self._vector_store = vector_store
        self._embedding = embedding
        self._batch_size = embedding_batch_size

    def execute(
        self,
        *,
        job_id: UUID,
        event_id: UUID,
        event_schema_version: int,
        worker_id: str,
    ) -> KnowledgeJobExecutionResult:
        if not worker_id or len(worker_id) > 100:
            raise KnowledgeJobExecutionError("WORKER_ID_INVALID")
        with self._session_factory.begin() as session:
            job_repository = JobRuntimeRepository(session)
            snapshot = job_repository.peek_job(job_id)
            if snapshot is None:
                raise KnowledgeJobExecutionError("JOB_NOT_FOUND")
            handler = self._validated_handler(snapshot.job_type, snapshot.input_json)
            if not self._snapshot_matches(snapshot, handler):
                raise KnowledgeJobExecutionError("HANDLER_REGISTRY_INVALID")
            claim = job_repository.claim_job(
                job_id=job_id,
                event_id=event_id,
                event_schema_version=event_schema_version,
                worker_id=worker_id,
                start_step_seq=1,
            )
            if claim is None:
                return KnowledgeJobExecutionResult("duplicate_or_stale", job_id)
        return self._execute_claimed(claim, handler)

    def execute_claimed(self, claim: ClaimedJob) -> KnowledgeJobExecutionResult:
        handler = self._validated_handler(claim.job.job_type, claim.job.input_json)
        if not self._snapshot_matches(claim.job, handler):
            raise KnowledgeJobExecutionError("HANDLER_REGISTRY_INVALID")
        return self._execute_claimed(claim, handler)

    def _execute_claimed(
        self, claim: ClaimedJob, handler: KnowledgeHandlerRuntime
    ) -> KnowledgeJobExecutionResult:
        if claim.job.job_type == "knowledge_index_build":
            return self._build_index(claim, handler)
        if claim.job.job_type == "retrieval_eval":
            return self._evaluate(claim, handler)
        raise KnowledgeJobExecutionError("HANDLER_REGISTRY_INVALID")

    def _build_index(
        self, claim: ClaimedJob, handler: KnowledgeHandlerRuntime
    ) -> KnowledgeJobExecutionResult:
        try:
            index_id = _canonical_uuid(claim.job.input_json.get("index_version_id"))
            knowledge_base_id = _canonical_uuid(claim.job.input_json.get("knowledge_base_id"))
        except (TypeError, ValueError):
            return self._fail_index(claim, "INDEX_BUILD_INVALID", retryable=False)
        with self._session_factory() as session:
            repository = RetrievalRuntimeRepository(session)
            index = repository.get_index(claim.job.organization_id, knowledge_base_id, index_id)
            items = repository.materialization_items(index_id)
        if (
            index is None
            or index.id != claim.job.resource_id
            or index.status != "building"
            or index.embedding_adapter_id != self._embedding.target.adapter_id
            or index.embedding_model_id != self._embedding.target.model_id
            or index.vector_dimension <= 0
            or len(items) != index.member_count
        ):
            return self._fail_index(claim, "INDEX_BUILD_INVALID", retryable=False)

        current_claim = claim
        try:
            for offset in range(0, len(items), self._batch_size):
                batch = items[offset : offset + self._batch_size]
                vectors = tuple(self._embedding.embed_text(item.content_text) for item in batch)
                points = tuple(
                    QdrantPoint(
                        id=item.point_id,
                        vector=vector,
                        payload=point_payload(index.id, item.content_sha256),
                    )
                    for item, vector in zip(batch, vectors, strict=True)
                )
                self._vector_store.upsert(points)
                with self._session_factory.begin() as session:
                    repository = RetrievalRuntimeRepository(session)
                    locked = repository.lock_index(claim.job.organization_id, index.id)
                    if locked is None or locked.status != "building":
                        raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
                    for item, vector, upsert_point in zip(batch, vectors, points, strict=True):
                        if not repository.materialize_item(
                            item.item_id,
                            vector_sha256(vector),
                            payload_sha256(upsert_point.payload),
                        ):
                            raise KnowledgeJobExecutionError("INDEX_MEMBER_DRIFT")
                    heartbeat = JobRuntimeRepository(session).heartbeat(current_claim)
                    if heartbeat is None:
                        raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
                    current_claim = heartbeat

            expected = {item.point_id: item for item in items}
            observed: dict[UUID, QdrantStoredPoint] = {}
            point_ids = tuple(expected)
            for offset in range(0, len(point_ids), 256):
                batch_ids = point_ids[offset : offset + 256]
                for stored_point in self._vector_store.retrieve(batch_ids):
                    observed[stored_point.id] = stored_point
                with self._session_factory.begin() as session:
                    heartbeat = JobRuntimeRepository(session).heartbeat(current_claim)
                    if heartbeat is None:
                        raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
                    current_claim = heartbeat
            if set(observed) != set(expected):
                raise KnowledgeJobExecutionError("INDEX_MEMBER_DRIFT")
            materialized = self._materialized_hashes(index.id, items)
            for point_id, stored in observed.items():
                vector_hash, payload_hash = materialized[point_id]
                if (
                    vector_sha256(stored.vector) != vector_hash
                    or payload_sha256(stored.payload) != payload_hash
                ):
                    raise KnowledgeJobExecutionError("INDEX_MEMBER_DRIFT")
        except QdrantVectorStoreError:
            return self._fail_index(current_claim, "DEPENDENCY_UNAVAILABLE", retryable=True)
        except KnowledgeJobExecutionError as error:
            if error.code == "JOB_FENCING_REJECTED":
                raise
            return self._fail_index(current_claim, error.code, retryable=False)

        consistency: dict[str, object] = {
            "checked_point_count": len(items),
            "member_count_match": True,
            "payload_hash_match": True,
            "vector_hash_match": True,
        }
        summary = {
            "index_version_id": str(index.id),
            "manifest_sha256": index.manifest_sha256,
            "member_count": len(items),
        }
        handler.validate_summary(summary)
        with self._session_factory.begin() as session:
            repository = RetrievalRuntimeRepository(session)
            locked = repository.lock_index(claim.job.organization_id, index.id)
            if locked is None or not repository.mark_index_ready(locked, consistency):
                raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
            OperationLogRepository(session).append(
                organization_id=claim.job.organization_id,
                actor_kind="system",
                actor_id=None,
                action_code="knowledge.index_ready",
                outcome="succeeded",
                resource_type="document_index_version",
                resource_id=index.id,
                trace_id=claim.job.trace_id,
                change_summary={
                    "manifest_sha256": index.manifest_sha256,
                    "member_count": len(items),
                    "status": "ready",
                },
            )
            if not JobRuntimeRepository(session).finish_job(
                current_claim, status="succeeded", summary=summary
            ):
                raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
        return KnowledgeJobExecutionResult("succeeded", claim.job.id)

    def _evaluate(
        self, claim: ClaimedJob, handler: KnowledgeHandlerRuntime
    ) -> KnowledgeJobExecutionResult:
        try:
            run_id = _canonical_uuid(claim.job.input_json.get("run_id"))
            dataset_id = _canonical_uuid(claim.job.input_json.get("dataset_id"))
            index_id = _canonical_uuid(claim.job.input_json.get("index_version_id"))
            knowledge_base_id = _canonical_uuid(claim.job.input_json.get("knowledge_base_id"))
        except (TypeError, ValueError):
            return self._fail_evaluation(claim, None, "EVALUATION_INPUT_INVALID", False)
        with self._session_factory() as session:
            repository = RetrievalRuntimeRepository(session)
            run = repository.get_run(claim.job.organization_id, knowledge_base_id, run_id)
            dataset = repository.get_dataset(
                claim.job.organization_id, knowledge_base_id, dataset_id
            )
            index = repository.get_index(claim.job.organization_id, knowledge_base_id, index_id)
            cases = repository.dataset_cases(dataset_id)
        if (
            run is None
            or dataset is None
            or index is None
            or run.id != claim.job.resource_id
            or run.status != "running"
            or dataset.status != "approved"
            or index.status not in {"ready", "active"}
            or run.dataset_id != dataset.id
            or run.index_version_id != index.id
            or run.embedding_adapter_id != self._embedding.target.adapter_id
            or run.embedding_model_id != self._embedding.target.model_id
            or len(cases) != run.case_count
        ):
            return self._fail_evaluation(claim, run_id, "EVALUATION_INPUT_INVALID", False)

        current_claim = claim
        outcomes: list[_CaseOutcome] = []
        threshold = dataset.answer_score_threshold
        try:
            for case in cases:
                with self._session_factory() as session:
                    repository = RetrievalRuntimeRepository(session)
                    allowed_ids = repository.eval_allowed_point_ids(
                        index_version_id=index.id,
                        baseline_date=case.baseline_date,
                        allowed_policy_ids=tuple(case.allowed_policy_ids),
                    )
                    expected_identity = repository.index_chunk_identity(
                        index.id, tuple(case.expected_chunk_ids)
                    )
                vector = self._embedding.embed_text(case.query_text)
                hits = (
                    ()
                    if not allowed_ids
                    else self._vector_store.query_authorized(
                        vector,
                        allowed_point_ids=allowed_ids,
                        limit=min(5, len(allowed_ids)),
                    )
                )
                with self._session_factory.begin() as session:
                    repository = RetrievalRuntimeRepository(session)
                    identities = repository.eval_hit_identity(
                        index.id, tuple(hit.id for hit in hits)
                    )
                    if len(identities) != len(hits) or set(expected_identity) != set(
                        case.expected_chunk_ids
                    ):
                        outcome = self._member_drift_outcome(case)
                    else:
                        outcome = self._case_outcome(
                            case,
                            hits,
                            identities,
                            expected_identity,
                            threshold,
                        )
                    heartbeat = JobRuntimeRepository(session).heartbeat(current_claim)
                    if heartbeat is None:
                        raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
                    current_claim = heartbeat
                outcomes.append(outcome)
        except QdrantVectorStoreError:
            return self._fail_evaluation(current_claim, run.id, "DEPENDENCY_UNAVAILABLE", True)

        metrics = self._metrics(outcomes, threshold)
        passed = all(outcome.passed for outcome in outcomes)
        summary = {"case_count": len(outcomes), "passed": passed, "run_id": str(run.id)}
        handler.validate_summary(summary)
        with self._session_factory.begin() as session:
            repository = RetrievalRuntimeRepository(session)
            locked_run = repository.lock_run(claim.job.organization_id, run.id)
            if locked_run is None or locked_run.status != "running":
                raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
            existing_result = session.scalar(
                select(RetrievalEvalResult.id).where(RetrievalEvalResult.run_id == run.id).limit(1)
            )
            if existing_result is not None:
                raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
            repository.add_all(
                tuple(
                    RetrievalEvalResult(
                        case_id=outcome.case_id,
                        run_id=run.id,
                        passed=outcome.passed,
                        authorization_leak=outcome.authorization_leak,
                        ranked_hits_json=outcome.ranked_hits,
                        miss_reason=outcome.miss_reason,
                    )
                    for outcome in outcomes
                )
            )
            repository.flush()
            locked_run.status = "passed" if passed else "failed"
            locked_run.completed_case_count = len(outcomes)
            locked_run.metrics_json = metrics
            locked_run.failure_code = None if passed else "QUALITY_GATE_FAILED"
            locked_run.finished_at = repository.database_now()
            repository.flush()
            OperationLogRepository(session).append(
                organization_id=claim.job.organization_id,
                actor_kind="system",
                actor_id=None,
                action_code="knowledge.eval_completed",
                outcome="succeeded",
                resource_type="retrieval_eval_run",
                resource_id=run.id,
                trace_id=claim.job.trace_id,
                change_summary={
                    "case_count": len(outcomes),
                    "passed": passed,
                    "tier": run.tier,
                },
            )
            if not JobRuntimeRepository(session).finish_job(
                current_claim, status="succeeded", summary=summary
            ):
                raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
        return KnowledgeJobExecutionResult("succeeded", claim.job.id)

    def _fail_index(
        self, claim: ClaimedJob, error_code: str, *, retryable: bool
    ) -> KnowledgeJobExecutionResult:
        terminal = not retryable or claim.job.attempt_no >= claim.job.max_attempts
        with self._session_factory.begin() as session:
            repository = RetrievalRuntimeRepository(session)
            index = repository.lock_index(claim.job.organization_id, claim.job.resource_id)
            if terminal and index is not None and index.status == "building":
                if not repository.mark_index_failed(index, error_code):
                    raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
            if not JobRuntimeRepository(session).finish_job(
                claim,
                status="failed",
                summary={},
                error_code="DEPENDENCY_UNAVAILABLE" if retryable else error_code,
                error_message="knowledge index build failed",
            ):
                raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
        return KnowledgeJobExecutionResult("failed", claim.job.id)

    def _fail_evaluation(
        self,
        claim: ClaimedJob,
        run_id: UUID | None,
        error_code: str,
        retryable: bool,
    ) -> KnowledgeJobExecutionResult:
        terminal = not retryable or claim.job.attempt_no >= claim.job.max_attempts
        with self._session_factory.begin() as session:
            repository = RetrievalRuntimeRepository(session)
            run = None if run_id is None else repository.lock_run(claim.job.organization_id, run_id)
            if terminal and run is not None and run.status == "running":
                run.status = "failed"
                run.failure_code = error_code
                run.finished_at = repository.database_now()
                repository.flush()
            if not JobRuntimeRepository(session).finish_job(
                claim,
                status="failed",
                summary={},
                error_code="DEPENDENCY_UNAVAILABLE" if retryable else error_code,
                error_message="retrieval evaluation failed",
            ):
                raise KnowledgeJobExecutionError("JOB_FENCING_REJECTED")
        return KnowledgeJobExecutionResult("failed", claim.job.id)

    @staticmethod
    def _validated_handler(job_type: str, input_json: dict[str, object]) -> KnowledgeHandlerRuntime:
        if job_type not in {"knowledge_index_build", "retrieval_eval"}:
            raise KnowledgeJobExecutionError("HANDLER_REGISTRY_INVALID")
        try:
            handler = load_knowledge_handler(cast(KnowledgeJobType, job_type))
            handler.validate_input(input_json)
        except (HandlerRegistryError, ValueError):
            raise KnowledgeJobExecutionError("HANDLER_REGISTRY_INVALID") from None
        return handler

    @staticmethod
    def _snapshot_matches(snapshot: JobSnapshot, handler: KnowledgeHandlerRuntime) -> bool:
        return bool(
            snapshot.resource_type in {"document_index_version", "retrieval_eval_run"}
            and snapshot.handler_registry_version == handler.registry_version
            and snapshot.handler_registry_hash == handler.registry_hash
            and snapshot.input_schema_version == 1
            and snapshot.current_attempt_start_step_code == handler.handler.steps[0].step_code
        )

    def _materialized_hashes(
        self, index_version_id: UUID, items: tuple[MaterializationItem, ...]
    ) -> dict[UUID, tuple[str, str]]:
        return {
            item.point_id: (
                vector_sha256(self._embedding.embed_text(item.content_text)),
                payload_sha256(point_payload(index_version_id, item.content_sha256)),
            )
            for item in items
        }

    @staticmethod
    def _case_outcome(
        case: RetrievalEvalCase,
        hits: tuple[QdrantHit, ...],
        identities: dict[UUID, tuple[UUID, UUID, str]],
        expected_identity: dict[UUID, tuple[UUID, str]],
        threshold: Decimal,
    ) -> _CaseOutcome:
        case_id = case.id
        label_text = case.label
        expected_chunk_ids = tuple(case.expected_chunk_ids)
        forbidden_chunk_ids = set(case.forbidden_chunk_ids)
        ranked: list[object] = []
        metric_hits: list[RankedRetrievalHit] = []
        qualified_chunks: set[UUID] = set()
        authorization_leak = False
        for rank, hit in enumerate(hits, start=1):
            policy_id, chunk_id, policy_version = identities[hit.id]
            score = Decimal(str(hit.score))
            ranked.append(
                {
                    "chunk_id": str(chunk_id),
                    "permission_allowed": True,
                    "point_id": str(hit.id),
                    "policy_id": str(policy_id),
                    "rank": rank,
                    "score": format(score, "f"),
                }
            )
            if score > threshold:
                qualified_chunks.add(chunk_id)
                metric_hits.append(
                    RankedRetrievalHit(
                        rank=rank,
                        document_version=f"{policy_id}:{policy_version}",
                        evidence_anchor_ids=(str(chunk_id),),
                        permission_allowed=True,
                        score=score,
                    )
                )

        if label_text == "answerable":
            expected_evidence = tuple(
                EvidenceIdentity(
                    f"{expected_identity[chunk_id][0]}:{expected_identity[chunk_id][1]}",
                    str(chunk_id),
                )
                for chunk_id in expected_chunk_ids
                if chunk_id in expected_identity
            )
            expected_documents = tuple(
                sorted({evidence.document_version for evidence in expected_evidence})
            )
            passed = len(expected_evidence) == len(expected_chunk_ids) and bool(
                qualified_chunks.intersection(expected_chunk_ids)
            )
            miss_reason = None if passed else "expected_evidence_missing"
            label = RetrievalCaseLabel.ANSWERABLE
        elif label_text == "no_answer":
            expected_evidence = ()
            expected_documents = ()
            passed = not metric_hits
            miss_reason = None if passed else "false_positive"
            label = RetrievalCaseLabel.NO_ANSWER
        else:
            expected_evidence = ()
            expected_documents = ()
            authorization_leak = bool(qualified_chunks.intersection(forbidden_chunk_ids))
            passed = not authorization_leak
            miss_reason = None if passed else "authorization_leak"
            label = RetrievalCaseLabel.UNAUTHORIZED
        metric_case = RetrievalCaseResult(
            case_id=str(case_id),
            label=label,
            expected_document_versions=expected_documents,
            expected_evidence=expected_evidence,
            hits=tuple(metric_hits),
        )
        return _CaseOutcome(
            case_id,
            passed,
            authorization_leak,
            ranked,
            miss_reason,
            metric_case,
        )

    @staticmethod
    def _member_drift_outcome(case: RetrievalEvalCase) -> _CaseOutcome:
        case_id = case.id
        return _CaseOutcome(case_id, False, False, [], "member_drift", None)

    @staticmethod
    def _metrics(outcomes: list[_CaseOutcome], threshold: Decimal) -> dict[str, object]:
        metric_cases = tuple(
            outcome.metric_case for outcome in outcomes if outcome.metric_case is not None
        )
        answerable = tuple(
            case for case in metric_cases if case.label is RetrievalCaseLabel.ANSWERABLE
        )
        no_answer = tuple(
            case for case in metric_cases if case.label is RetrievalCaseLabel.NO_ANSWER
        )
        metrics: dict[str, object] = {
            "authorization_leak_count": sum(outcome.authorization_leak for outcome in outcomes),
            "case_count": len(outcomes),
            "case_pass_count": sum(outcome.passed for outcome in outcomes),
            "case_pass_rate": sum(outcome.passed for outcome in outcomes) / len(outcomes),
        }
        if answerable:
            relevance = calculate_retrieval_metrics(answerable, k=5)
            metrics.update(
                document_hit_at_5=relevance.document_hit_at_k,
                evidence_hit_at_5=relevance.evidence_hit_at_k,
                recall_at_5=relevance.recall_at_k,
                precision_at_5=relevance.precision_at_k,
                mrr=relevance.mrr,
            )
        if no_answer:
            false_positive = calculate_no_answer_false_positive_rate(no_answer, threshold=threshold)
            metrics["no_answer_false_positive_rate"] = float(false_positive.rate)
        return metrics


__all__ = [
    "KnowledgeJobExecutionError",
    "KnowledgeJobExecutionResult",
    "KnowledgeJobExecutor",
    "VectorStore",
]
