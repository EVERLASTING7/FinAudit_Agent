"""PG 允许集、Qdrant must-filter、PG 终审和确定性引用回答。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import monotonic
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.qdrant_vector import QdrantHit, QdrantVectorStoreError
from app.ai.embedding_runtime import (
    AuditedEmbeddingAdoption,
    EmbeddingCallIdentity,
    EmbeddingInvocationError,
    EmbeddingRuntime,
)
from app.ai.output_validation import (
    CitationValidationError,
    RagAnswerOutput,
    RagCitation,
    validate_rag_answer,
)
from app.ai.rag_prompts import RagPromptCandidate
from app.core.config import Settings
from app.core.errors import AppError
from app.models.retrieval import QaFeedback, QaQuery
from app.repositories.operation_log import OperationLogRepository
from app.repositories.retrieval_runtime import AuthorizedIndexHit, RetrievalRuntimeRepository
from app.repositories.user_write import IdempotencyClaim
from app.schemas.retrieval import (
    QaCitationData,
    QaFeedbackData,
    QaFeedbackRequest,
    QaQueryData,
    QaQueryRequest,
)
from app.services.auth import AuthenticatedActor
from app.services.vector_integrity import point_payload

if TYPE_CHECKING:
    from app.services.ai_rag_answer import AiRagAnswerService, AuditedRagAnswer

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_IDEMPOTENCY_TTL = timedelta(hours=24)
_WORD_PATTERN = re.compile(r"[a-z0-9]{2,}|[\u3400-\u9fff]", re.ASCII)
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?", re.I),
    re.compile(r"(?:system|developer)\s+prompt", re.I),
    re.compile(r"(?:reveal|print|show)\s+(?:the\s+)?(?:hidden\s+)?instructions?", re.I),
    re.compile(r"(?:<|\[)(?:system|developer)(?:>|\])", re.I),
    re.compile(r"忽略.{0,12}(?:以上|之前|前述|所有).{0,12}(?:指令|规则|要求)"),
    re.compile(r"(?:泄露|显示|输出).{0,12}(?:系统提示|隐藏指令|开发者消息)"),
)


class VectorQuery(Protocol):
    def query_authorized(
        self,
        vector: tuple[float, ...],
        *,
        allowed_point_ids: tuple[UUID, ...],
        limit: int,
    ) -> tuple[QdrantHit, ...]: ...


@dataclass(frozen=True, slots=True)
class QaQueryMutationResult:
    data: QaQueryData
    replayed: bool
    status_code: int = 200


@dataclass(frozen=True, slots=True)
class QaFeedbackMutationResult:
    data: QaFeedbackData
    replayed: bool
    status_code: int = 201


@dataclass(frozen=True, slots=True)
class _PreparedRetrieval:
    index_version_id: UUID | None
    hits: tuple[QdrantHit, ...]
    status: Literal["pending", "refused", "service_degraded"]
    reason_code: str | None
    embedding_adoption: AuditedEmbeddingAdoption | None = None


@dataclass(frozen=True, slots=True)
class _RagResolution:
    status: Literal["answered", "refused", "service_degraded"]
    reason_code: str | None
    deterministic_answer: str | None
    candidates: tuple[RagCitation, ...]
    prompt_candidates: tuple[RagPromptCandidate, ...]
    confidence: str | None
    retrieved_count: int
    index_version_id: UUID | None


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


def _contains_prompt_injection(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    return any(pattern.search(normalized) is not None for pattern in _INJECTION_PATTERNS)


def _lexical_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    raw = _WORD_PATTERN.findall(normalized)
    latin = {token for token in raw if token.isascii()}
    cjk = "".join(token for token in raw if not token.isascii())
    return latin | {cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))}


def _is_relevant(question: str, content: str) -> bool:
    question_tokens = _lexical_tokens(question)
    return bool(question_tokens and question_tokens.intersection(_lexical_tokens(content)))


def _quote(content: str) -> str:
    value = content[:500].strip()
    if not value:
        raise ValueError("empty evidence quote")
    return value


def _page_range(hit: AuthorizedIndexHit) -> str:
    if hit.start_page_no == hit.end_page_no:
        return str(hit.start_page_no)
    return f"{hit.start_page_no}-{hit.end_page_no}"


def _project_query(query: QaQuery) -> QaQueryData:
    citations = tuple(
        QaCitationData.model_validate_json(_canonical_json(value)) for value in query.citations_json
    )
    return QaQueryData.model_validate(
        {
            "id": query.id,
            "knowledge_base_id": query.knowledge_base_id,
            "index_version_id": query.index_version_id,
            "baseline_date": query.baseline_date,
            "status": query.status,
            "answer": query.answer_text,
            "reason_code": query.reason_code,
            "citations": citations,
            "retrieved_count": query.retrieved_count,
            "created_at": query.created_at,
        }
    )


def _project_feedback(feedback: QaFeedback) -> QaFeedbackData:
    return QaFeedbackData(
        id=feedback.id,
        qa_query_id=feedback.qa_query_id,
        rating=feedback.rating,
        correction_text=feedback.correction_text,
        created_at=feedback.created_at,
    )


class RagQueryService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        vector_store: VectorQuery,
        embedding: EmbeddingRuntime,
        settings: Settings,
        ai_answer: AiRagAnswerService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._vector_store = vector_store
        self._embedding = embedding
        self._collection_name = settings.qdrant_collection
        self._distance = settings.qdrant_distance
        self._vector_dimension = settings.qdrant_vector_size
        self._top_k = min(settings.rag_top_k, settings.rag_max_context_chunks, 5)
        self._score_threshold = settings.rag_score_threshold
        self._ai_answer = ai_answer

    def query(
        self,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        payload: QaQueryRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> QaQueryMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/knowledge-bases/{knowledge_base_id}/qa-queries"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        replay = self._preflight_idempotency(
            actor,
            idempotency_key=idempotency_key,
            path=path,
            digest=digest,
        )
        if replay is not None:
            return replay
        query_id = uuid4()
        prepared = self._prepare(actor, knowledge_base_id, payload, trace_id, query_id)
        preflight_resolution: _RagResolution | None = None
        audited_answer: AuditedRagAnswer | None = None
        model_error_code: str | None = None
        if self._ai_answer is not None and prepared.status == "pending":
            with self._session_factory() as session:
                preflight_resolution = self._resolve(
                    RetrievalRuntimeRepository(session),
                    actor,
                    knowledge_base_id,
                    payload,
                    prepared,
                )
            if preflight_resolution.status == "answered":
                try:
                    audited_answer = self._ai_answer.answer(
                        organization_id=actor.organization_id,
                        query_id=query_id,
                        trace_id=trace_id,
                        question=payload.question,
                        candidates=preflight_resolution.prompt_candidates,
                    )
                except Exception as error:
                    from app.services.ai_rag_answer import AiRagAnswerServiceError

                    if not isinstance(error, AiRagAnswerServiceError):
                        raise
                    model_error_code = error.code
        knowledge_base_missing = False
        idempotency_conflict = False
        try:
            with self._session_factory.begin() as session:
                repository, claim, now = self._claim(
                    session, actor, idempotency_key, "POST", path, digest
                )
                if claim.conflict:
                    if prepared.embedding_adoption is not None:
                        prepared.embedding_adoption.reject_in_transaction(
                            session,
                            safe_error_code="EMBEDDING_RESULT_NOT_ADOPTED",
                        )
                    if audited_answer is not None:
                        audited_answer.adoption.reject_in_transaction(
                            session,
                            safe_error_code="AI_RESULT_NOT_ADOPTED",
                        )
                    idempotency_conflict = True
                elif claim.is_replay:
                    if prepared.embedding_adoption is not None:
                        prepared.embedding_adoption.reject_in_transaction(
                            session,
                            safe_error_code="EMBEDDING_RESULT_NOT_ADOPTED",
                        )
                    if audited_answer is not None:
                        audited_answer.adoption.reject_in_transaction(
                            session,
                            safe_error_code="AI_RESULT_NOT_ADOPTED",
                        )
                    return self._replay_query(claim)
                elif (
                    repository.lock_knowledge_base(actor.organization_id, knowledge_base_id) is None
                ):
                    if prepared.embedding_adoption is not None:
                        prepared.embedding_adoption.reject_in_transaction(
                            session,
                            safe_error_code="EMBEDDING_SOURCE_DRIFT",
                        )
                    if audited_answer is not None:
                        audited_answer.adoption.reject_in_transaction(
                            session,
                            safe_error_code="AI_RAG_SOURCE_DRIFT",
                        )
                    knowledge_base_missing = True
                    session.delete(claim.record)
                else:
                    resolution = self._resolve(
                        repository,
                        actor,
                        knowledge_base_id,
                        payload,
                        prepared,
                    )
                    status, reason_code, answer, citations, retrieved_count, active_index_id = (
                        self._adopt_or_project_answer(
                            session,
                            resolution=resolution,
                            preflight_resolution=preflight_resolution,
                            audited_answer=audited_answer,
                            model_error_code=model_error_code,
                        )
                    )
                    if prepared.embedding_adoption is not None:
                        prepared.embedding_adoption.adopt_in_transaction(session)
                if not knowledge_base_missing and not idempotency_conflict:
                    query = QaQuery(
                        id=query_id,
                        organization_id=actor.organization_id,
                        knowledge_base_id=knowledge_base_id,
                        index_version_id=active_index_id,
                        baseline_date=payload.baseline_date,
                        question_text=payload.question,
                        question_sha256=hashlib.sha256(
                            payload.question.encode("utf-8")
                        ).hexdigest(),
                        status=status,
                        answer_text=answer,
                        reason_code=reason_code,
                        citations_json=[item.model_dump(mode="json") for item in citations],
                        retrieved_count=retrieved_count,
                        embedding_adapter_id=self._embedding.target.adapter_id,
                        embedding_model_id=self._embedding.target.model_id,
                        created_by=actor.user_id,
                        created_at=now,
                        trace_id=trace_id,
                    )
                    repository.add(query)
                    repository.flush()
                    data = _project_query(query)
                    OperationLogRepository(session).append(
                        organization_id=actor.organization_id,
                        actor_kind="user",
                        actor_id=actor.user_id,
                        action_code="knowledge.qa_queried",
                        outcome="succeeded",
                        resource_type="qa_query",
                        resource_id=query.id,
                        trace_id=trace_id,
                        change_summary={
                            "retrieved_count": retrieved_count,
                            "status": status,
                        },
                    )
                    repository.complete_idempotency(
                        claim,
                        response_status=200,
                        response_body=data.model_dump(mode="json"),
                        resource_type="qa_query",
                        resource_id=query.id,
                    )
                    return QaQueryMutationResult(data, False)
        except IntegrityError:
            raise _conflict("WRITE_CONFLICT", "问答事实并发写入冲突") from None
        if idempotency_conflict:
            raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
        if knowledge_base_missing:
            raise _not_found()
        raise RuntimeError("RAG query transaction completed without a result")

    def _preflight_idempotency(
        self,
        actor: AuthenticatedActor,
        *,
        idempotency_key: str,
        path: str,
        digest: str,
    ) -> QaQueryMutationResult | None:
        with self._session_factory.begin() as session:
            repository = RetrievalRuntimeRepository(session)
            repository.acquire_api_locks(
                actor.organization_id,
                actor.user_id,
                idempotency_key,
            )
            if repository.lock_active_organization(actor.organization_id) is None:
                raise _not_found()
            inspected = repository.inspect_idempotency(
                organization_id=actor.organization_id,
                actor_id=actor.user_id,
                idempotency_key=idempotency_key,
                request_method="POST",
                request_path=path,
                request_hash=digest,
                now=repository.database_now(),
            )
            if inspected is None:
                return None
            if inspected.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            return self._replay_query(inspected)

    def feedback(
        self,
        actor: AuthenticatedActor,
        query_id: UUID,
        payload: QaFeedbackRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> QaFeedbackMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/qa-queries/{query_id}/feedback"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository, claim, now = self._claim(
                    session, actor, idempotency_key, "POST", path, digest
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._replay_feedback(claim)
                query = repository.lock_qa_query(actor.organization_id, query_id)
                if query is None or query.created_by != actor.user_id:
                    raise _not_found()
                if repository.feedback_for_actor(query.id, actor.user_id) is not None:
                    raise _conflict("QA_FEEDBACK_ALREADY_EXISTS", "当前用户已提交反馈")
                feedback = QaFeedback(
                    id=uuid4(),
                    organization_id=actor.organization_id,
                    qa_query_id=query.id,
                    rating=payload.rating,
                    correction_text=payload.correction_text,
                    created_by=actor.user_id,
                    created_at=now,
                    trace_id=trace_id,
                )
                repository.add(feedback)
                repository.flush()
                data = _project_feedback(feedback)
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="knowledge.qa_feedback",
                    outcome="succeeded",
                    resource_type="qa_query",
                    resource_id=query.id,
                    trace_id=trace_id,
                    change_summary={"rating": payload.rating},
                )
                repository.complete_idempotency(
                    claim,
                    response_status=201,
                    response_body=data.model_dump(mode="json"),
                    resource_type="qa_feedback",
                    resource_id=feedback.id,
                )
                return QaFeedbackMutationResult(data, False)
        except IntegrityError:
            raise _conflict("QA_FEEDBACK_ALREADY_EXISTS", "当前用户已提交反馈") from None

    def _prepare(
        self,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        payload: QaQueryRequest,
        trace_id: UUID,
        query_id: UUID,
    ) -> _PreparedRetrieval:
        if _contains_prompt_injection(payload.question):
            return _PreparedRetrieval(None, (), "refused", "PROMPT_INJECTION_DETECTED")
        with self._session_factory() as session:
            repository = RetrievalRuntimeRepository(session)
            if repository.get_knowledge_base(actor.organization_id, knowledge_base_id) is None:
                raise _not_found()
            index = repository.get_active_index(actor.organization_id, knowledge_base_id)
            if index is None:
                return _PreparedRetrieval(None, (), "refused", "INDEX_NOT_ACTIVE")
            if not self._index_identity_matches(index):
                return _PreparedRetrieval(index.id, (), "refused", "INDEX_DRIFT_DETECTED")
            allowed_ids = repository.active_point_ids(
                organization_id=actor.organization_id,
                knowledge_base_id=knowledge_base_id,
                baseline_date=payload.baseline_date,
                actor_roles=actor.roles,
            )
        if not allowed_ids:
            return _PreparedRetrieval(index.id, (), "refused", "NO_RELEVANT_EVIDENCE")
        adoption: AuditedEmbeddingAdoption | None = None
        try:
            if self._embedding.requires_audit:
                embedded = self._embedding.embed_texts_audited(
                    trace_id=str(trace_id),
                    input_texts=(payload.question,),
                    identity=EmbeddingCallIdentity(
                        organization_id=actor.organization_id,
                        business_operation_id=query_id,
                        job_id=None,
                        request_id=trace_id,
                        resource_type="knowledge_base",
                        resource_id=knowledge_base_id,
                        trace_id=trace_id,
                    ),
                    deadline_monotonic=(
                        monotonic() + self._embedding.transport_policy.total_timeout_seconds
                    ),
                )
                vector = embedded.vectors[0]
                adoption = embedded.adoption
            else:
                vector = self._embedding.embed_texts(
                    trace_id=str(trace_id),
                    input_texts=(payload.question,),
                )[0]
            hits = self._vector_store.query_authorized(
                vector,
                allowed_point_ids=allowed_ids,
                limit=min(self._top_k, len(allowed_ids)),
            )
        except EmbeddingInvocationError:
            return _PreparedRetrieval(index.id, (), "service_degraded", "RETRIEVAL_UNAVAILABLE")
        except QdrantVectorStoreError:
            if adoption is not None:
                try:
                    with self._session_factory.begin() as session:
                        adoption.reject_in_transaction(
                            session,
                            safe_error_code="EMBEDDING_RESULT_NOT_ADOPTED",
                        )
                except EmbeddingInvocationError:
                    pass
            return _PreparedRetrieval(index.id, (), "service_degraded", "RETRIEVAL_UNAVAILABLE")
        return _PreparedRetrieval(index.id, hits, "pending", None, adoption)

    def _finalize(
        self,
        repository: RetrievalRuntimeRepository,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        payload: QaQueryRequest,
        prepared: _PreparedRetrieval,
    ) -> tuple[
        str,
        str | None,
        str | None,
        tuple[QaCitationData, ...],
        int,
        UUID | None,
    ]:
        return self._project_resolution(
            self._resolve(repository, actor, knowledge_base_id, payload, prepared)
        )

    def _resolve(
        self,
        repository: RetrievalRuntimeRepository,
        actor: AuthenticatedActor,
        knowledge_base_id: UUID,
        payload: QaQueryRequest,
        prepared: _PreparedRetrieval,
    ) -> _RagResolution:
        active_index = repository.get_active_index(actor.organization_id, knowledge_base_id)
        if prepared.status != "pending":
            active_id = None if active_index is None else active_index.id
            if prepared.index_version_id is not None and active_id != prepared.index_version_id:
                return self._refused_resolution("INDEX_DRIFT_DETECTED", active_id)
            status: Literal["refused", "service_degraded"] = (
                "refused" if prepared.status == "refused" else "service_degraded"
            )
            return _RagResolution(
                status,
                prepared.reason_code,
                None,
                (),
                (),
                None,
                0,
                active_id,
            )
        if (
            active_index is None
            or active_index.id != prepared.index_version_id
            or not self._index_identity_matches(active_index)
        ):
            active_id = None if active_index is None else active_index.id
            return self._refused_resolution("INDEX_DRIFT_DETECTED", active_id)
        point_ids = tuple(hit.id for hit in prepared.hits)
        if not point_ids:
            return self._refused_resolution("NO_RELEVANT_EVIDENCE", active_index.id)
        authorized = repository.final_authorized_hits(
            organization_id=actor.organization_id,
            knowledge_base_id=knowledge_base_id,
            baseline_date=payload.baseline_date,
            actor_roles=actor.roles,
            point_ids=point_ids,
        )
        if len(authorized) != len(prepared.hits):
            return self._refused_resolution("INDEX_DRIFT_DETECTED", active_index.id)
        if any(
            hit.payload != point_payload(active_index.id, fact.content_sha256)
            for hit, fact in zip(prepared.hits, authorized, strict=True)
        ):
            return self._refused_resolution("INDEX_DRIFT_DETECTED", active_index.id)
        if any(_contains_prompt_injection(fact.content_text) for fact in authorized):
            return self._refused_resolution("PROMPT_INJECTION_DETECTED", active_index.id)
        selected = tuple(
            (hit, fact)
            for hit, fact in zip(prepared.hits, authorized, strict=True)
            if _is_relevant(payload.question, fact.content_text)
            and (self._score_threshold is None or hit.score >= self._score_threshold)
        )
        if not selected:
            return self._refused_resolution("NO_RELEVANT_EVIDENCE", active_index.id)
        internal_candidates = tuple(
            RagCitation(
                candidate_id=str(hit.id),
                policy_document_id=str(fact.policy_id),
                policy_version=fact.policy_version,
                markdown_version_id=str(fact.markdown_version_id),
                chunk_id=str(fact.chunk_id),
                block_ids=tuple(str(value) for value in fact.block_ids),
                index_version_id=str(active_index.id),
                page_range=_page_range(fact),
                title_path=fact.title_path,
                quote=_quote(fact.content_text),
                content_sha256=fact.content_sha256,
            )
            for hit, fact in selected
        )
        answer = "\n".join(
            f"根据《{fact.policy_name}》（{fact.policy_version}）：{citation.quote}"
            for citation, (_, fact) in zip(internal_candidates, selected, strict=True)
        )
        return _RagResolution(
            "answered",
            None,
            answer,
            internal_candidates,
            tuple(
                RagPromptCandidate(
                    citation=citation,
                    policy_name=fact.policy_name,
                    content=fact.content_text.strip(),
                )
                for citation, (_, fact) in zip(internal_candidates, selected, strict=True)
            ),
            f"{max(0.0, min(1.0, max(hit.score for hit, _ in selected))):.6f}",
            len(selected),
            active_index.id,
        )

    @staticmethod
    def _refused_resolution(reason_code: str, index_id: UUID | None) -> _RagResolution:
        return _RagResolution("refused", reason_code, None, (), (), None, 0, index_id)

    @staticmethod
    def _project_citations(citations: tuple[RagCitation, ...]) -> tuple[QaCitationData, ...]:
        return tuple(
            QaCitationData(
                policy_document_id=UUID(citation.policy_document_id),
                policy_version=citation.policy_version,
                markdown_version_id=UUID(citation.markdown_version_id),
                chunk_id=UUID(citation.chunk_id),
                block_ids=tuple(UUID(value) for value in citation.block_ids),
                index_version_id=UUID(citation.index_version_id),
                page_range=citation.page_range,
                title_path=citation.title_path,
                quote=citation.quote,
                content_sha256=citation.content_sha256,
            )
            for citation in citations
        )

    def _project_resolution(
        self,
        resolution: _RagResolution,
    ) -> tuple[str, str | None, str | None, tuple[QaCitationData, ...], int, UUID | None]:
        if resolution.status != "answered":
            return (
                resolution.status,
                resolution.reason_code,
                None,
                (),
                resolution.retrieved_count,
                resolution.index_version_id,
            )
        output = validate_rag_answer(
            RagAnswerOutput(
                answer_status="answered",
                answer=resolution.deterministic_answer,
                reason_code=None,
                citations=resolution.candidates,
                confidence=resolution.confidence,
                warnings=("deterministic_local_generator",),
            ),
            candidates=resolution.candidates,
        )
        return self._project_model_output(resolution, output)

    def _project_model_output(
        self,
        resolution: _RagResolution,
        output: RagAnswerOutput,
    ) -> tuple[str, str | None, str | None, tuple[QaCitationData, ...], int, UUID | None]:
        validated = validate_rag_answer(output, candidates=resolution.candidates)
        citations = tuple(self._project_citations(validated.citations))
        return (
            validated.answer_status,
            validated.reason_code,
            validated.answer,
            citations,
            resolution.retrieved_count,
            resolution.index_version_id,
        )

    def _adopt_or_project_answer(
        self,
        session: Session,
        *,
        resolution: _RagResolution,
        preflight_resolution: _RagResolution | None,
        audited_answer: AuditedRagAnswer | None,
        model_error_code: str | None,
    ) -> tuple[str, str | None, str | None, tuple[QaCitationData, ...], int, UUID | None]:
        if audited_answer is None:
            if model_error_code is not None and resolution.status == "answered":
                reason = (
                    "CITATION_VALIDATION_FAILED"
                    if model_error_code == "AI_STRUCTURED_OUTPUT_INVALID"
                    else "MODEL_UNAVAILABLE"
                )
                status = "refused" if reason == "CITATION_VALIDATION_FAILED" else "service_degraded"
                return (
                    status,
                    reason,
                    None,
                    (),
                    resolution.retrieved_count,
                    resolution.index_version_id,
                )
            return self._project_resolution(resolution)

        if preflight_resolution is None or resolution != preflight_resolution:
            audited_answer.adoption.reject_in_transaction(
                session,
                safe_error_code="AI_RAG_SOURCE_DRIFT",
            )
            if resolution.status != "answered":
                return self._project_resolution(resolution)
            return self._project_resolution(
                self._refused_resolution(
                    "INDEX_DRIFT_DETECTED",
                    resolution.index_version_id,
                )
            )

        try:
            projected = self._project_model_output(resolution, audited_answer.output)
        except (CitationValidationError, TypeError, ValueError):
            audited_answer.adoption.reject_in_transaction(
                session,
                safe_error_code="AI_CITATION_VALIDATION_FAILED",
            )
            return (
                "refused",
                "CITATION_VALIDATION_FAILED",
                None,
                (),
                resolution.retrieved_count,
                resolution.index_version_id,
            )
        audited_answer.adoption.adopt_in_transaction(session)
        return projected

    def _index_identity_matches(self, index: object) -> bool:
        return bool(
            getattr(index, "collection_name", None) == self._collection_name
            and getattr(index, "embedding_adapter_id", None) == self._embedding.target.adapter_id
            and getattr(index, "embedding_model_id", None) == self._embedding.target.model_id
            and getattr(index, "vector_dimension", None) == self._vector_dimension
            and getattr(index, "distance", None) == self._distance
        )

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
    def _replay_query(claim: IdempotencyClaim) -> QaQueryMutationResult:
        if claim.replay_status != 200 or claim.replay_body is None:
            raise RuntimeError("qa query replay does not match the contract")
        return QaQueryMutationResult(
            QaQueryData.model_validate_json(_canonical_json(claim.replay_body)), True
        )

    @staticmethod
    def _replay_feedback(claim: IdempotencyClaim) -> QaFeedbackMutationResult:
        if claim.replay_status != 201 or claim.replay_body is None:
            raise RuntimeError("qa feedback replay does not match the contract")
        return QaFeedbackMutationResult(
            QaFeedbackData.model_validate_json(_canonical_json(claim.replay_body)), True
        )


__all__ = [
    "QaFeedbackMutationResult",
    "QaQueryMutationResult",
    "RagQueryService",
    "VectorQuery",
]
