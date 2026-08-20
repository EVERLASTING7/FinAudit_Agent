from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from datetime import date
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.adapters.minio_quarantine import MinioQuarantineAdapter  # noqa: E402
from app.adapters.qdrant_vector import QdrantVectorAdapter  # noqa: E402
from app.ai.adapters.openai_compatible import (  # noqa: E402
    OPENAI_EMBEDDINGS_ADAPTER_ID,
    OpenAiCompatibleProfile,
    OpenAiEmbeddingsAdapter,
)
from app.ai.contracts import ModelTarget, TransportPolicy  # noqa: E402
from app.ai.embedding_runtime import (  # noqa: E402
    AuditedEmbeddingResult,
    EmbeddingCallIdentity,
    EmbeddingInvocationError,
    EmbeddingRuntime,
)
from app.ai.gateway import AiGateway  # noqa: E402
from app.ai.live_policy import (  # noqa: E402
    LIVE_EMBEDDING_POLICY,
    LIVE_POLICY_HASH,
    LIVE_POLICY_ID,
    LIVE_POLICY_RAW_SHA256,
)
from app.ai.network_policy import OutboundNetworkPolicy  # noqa: E402
from app.ai.policy_loader import ValidatedPolicySnapshot  # noqa: E402
from app.core.config import Settings, parse_database_url  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.db.migration import create_migration_engine  # noqa: E402
from app.db.session import create_session_factory  # noqa: E402
from app.models.audit import AiCallLog  # noqa: E402
from app.models.knowledge import DocumentChunk, DocumentChunkSet  # noqa: E402
from app.models.retrieval import RetrievalEvalResult  # noqa: E402
from app.repositories.retrieval_runtime import RetrievalRuntimeRepository  # noqa: E402
from app.schemas.retrieval import (  # noqa: E402
    EvaluationCaseInput,
    EvaluationDatasetCreateRequest,
    EvaluationLabel,
    EvaluationRunRequest,
    EvaluationTier,
    VersionedTransitionRequest,
)
from app.services.ai_call_audit import AiCallAuditService  # noqa: E402
from app.services.file_intake import FileIntakeService  # noqa: E402
from app.services.knowledge_index_management import (  # noqa: E402
    KnowledgeIndexManagementService,
)
from app.services.knowledge_job_executor import KnowledgeJobExecutor  # noqa: E402
from tests.integration.database.test_file_intake_service import (  # noqa: E402
    ACTOR_ID,
    ORGANIZATION_ID,
    MemoryQuarantineStorage,
    _seed_actor,
)
from tests.integration.database.test_file_job_executor import _dispatch_pending  # noqa: E402
from tests.integration.database.test_knowledge_runtime import (  # noqa: E402
    _approved_policy,
    _publisher,
)
from tests.integration.database.test_policy_management import (  # noqa: E402
    APPROVER_ID,
    KNOWLEDGE_BASE_ID,
    _actor,
    _seed_knowledge_subjects,
)

_CONFIRMATION = "ALLOW_ONE_BOUNDED_BAILIAN_KNOWLEDGE_E2E_V1"
_REUSE_CONFIRMATION = "REUSE_REPOSITORY_BAILIAN_KEY"
_DESTRUCTIVE_CONFIRMATION = "RESET_DISPOSABLE_FINAUDIT_TEST_DATABASE"
_DATABASE_MARKER = "finaudit:disposable-migration-test"
_DATABASE_REVISION = "20260818_027"
_SAFE_DATABASE_NAME = re.compile(r"^finaudit_[a-z0-9_]+_test$")
_REGISTRY_SHA256 = "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"

_MAX_PROVIDER_REQUESTS = 20
_MAX_INPUT_TOKENS = 50_000
_MAX_COST_MICROCNY = 1_000_000
_SMOKE_CASE_COUNT = 5
_EMBEDDING_BATCH_SIZE = 20

_SECTION_FACTS = (
    (
        "Travel receipt controls",
        "Receipts and manager approval are retained before reimbursing travel expenses.",
    ),
    (
        "Supplier onboarding controls",
        "Supplier identity and bank account evidence are reviewed before activation.",
    ),
    (
        "Invoice approval controls",
        "Invoice totals and tax identifiers are matched before payment approval.",
    ),
    (
        "Contract amendment controls",
        "Signed amendments are linked to the effective contract before obligations change.",
    ),
    (
        "Payment reconciliation controls",
        "Payment records are reconciled to approved invoices and contract terms.",
    ),
    (
        "Audit evidence controls",
        "Review decisions preserve traceable evidence and an append-only operation history.",
    ),
)


class LiveBailianKnowledgeE2EError(RuntimeError):
    pass


def _ceil_cost_microunits(input_tokens: int) -> int:
    numerator = input_tokens * LIVE_EMBEDDING_POLICY.input_price_microunits_per_million
    return (numerator + 1_000_000 - 1) // 1_000_000


class _BoundedEmbeddingRuntime:
    """只允许预先冻结的调用序列，并累计 Provider 返回的 CNY 事实。"""

    def __init__(
        self,
        delegate: EmbeddingRuntime,
        planned_calls: tuple[tuple[str, ...], ...],
        *,
        max_provider_requests: int = _MAX_PROVIDER_REQUESTS,
        max_input_tokens: int = _MAX_INPUT_TOKENS,
        max_cost_microunits: int = _MAX_COST_MICROCNY,
    ) -> None:
        if (
            max_provider_requests <= 0
            or max_input_tokens <= 0
            or max_cost_microunits <= 0
        ):
            raise LiveBailianKnowledgeE2EError("PROVIDER_BUDGET_INVALID")
        if not planned_calls or len(planned_calls) > max_provider_requests:
            raise LiveBailianKnowledgeE2EError(
                "PROVIDER_REQUEST_BUDGET_PREFLIGHT_REJECTED"
            )
        upper_bound = sum(
            len(value.encode("utf-8")) for call in planned_calls for value in call
        )
        if upper_bound > max_input_tokens:
            raise LiveBailianKnowledgeE2EError("INPUT_TOKEN_BUDGET_PREFLIGHT_REJECTED")
        if _ceil_cost_microunits(upper_bound) > max_cost_microunits:
            raise LiveBailianKnowledgeE2EError("CNY_BUDGET_PREFLIGHT_REJECTED")
        self._delegate = delegate
        self._planned_calls = planned_calls
        self._max_input_tokens = max_input_tokens
        self._max_cost_microunits = max_cost_microunits
        self.provider_request_count = 0
        self.input_token_upper_bound = upper_bound
        self.actual_input_tokens = 0
        self.actual_cost_microunits = 0

    @property
    def target(self) -> ModelTarget:
        return self._delegate.target

    @property
    def transport_policy(self) -> TransportPolicy:
        return self._delegate.transport_policy

    @property
    def requires_audit(self) -> bool:
        return True

    def embed_texts_audited(
        self,
        *,
        trace_id: str,
        input_texts: tuple[str, ...],
        identity: EmbeddingCallIdentity,
        deadline_monotonic: float,
    ) -> AuditedEmbeddingResult:
        call_index = self.provider_request_count
        if call_index >= len(self._planned_calls):
            raise EmbeddingInvocationError(
                "EMBEDDING_AGGREGATE_REQUEST_LIMIT", retryable=False
            )
        if input_texts != self._planned_calls[call_index]:
            raise EmbeddingInvocationError(
                "EMBEDDING_UNPLANNED_REQUEST", retryable=False
            )
        self.provider_request_count += 1
        result = self._delegate.embed_texts_audited(
            trace_id=trace_id,
            input_texts=input_texts,
            identity=identity,
            deadline_monotonic=deadline_monotonic,
        )
        if result.cost_currency != "CNY":
            raise EmbeddingInvocationError("EMBEDDING_CURRENCY_DRIFT", retryable=False)
        self.actual_input_tokens += result.input_tokens
        self.actual_cost_microunits += result.actual_cost_microunits
        if (
            self.actual_input_tokens > self._max_input_tokens
            or self.actual_cost_microunits > self._max_cost_microunits
        ):
            raise EmbeddingInvocationError(
                "EMBEDDING_AGGREGATE_BUDGET_EXCEEDED", retryable=False
            )
        return result

    def assert_consumed(self) -> None:
        if self.provider_request_count != len(self._planned_calls):
            raise LiveBailianKnowledgeE2EError("PROVIDER_REQUEST_PLAN_NOT_CONSUMED")


def _api_key() -> SecretStr:
    value = os.environ.get("EMBEDDING_API_KEY", "").strip()
    if not value and os.environ.get("FINAUDIT_REUSE_REPOSITORY_BAILIAN_KEY") == (
        _REUSE_CONFIRMATION
    ):
        configured = Settings().embedding_api_key
        value = "" if configured is None else configured.get_secret_value().strip()
    if (
        not value
        or value.upper().startswith("REPLACE_")
        or value.lower().startswith("disabled-local-")
    ):
        raise LiveBailianKnowledgeE2EError("EMBEDDING_API_KEY_REQUIRED")
    return SecretStr(value)


def _database_url() -> str:
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS") != (
        _DESTRUCTIVE_CONFIRMATION
    ):
        raise LiveBailianKnowledgeE2EError("DISPOSABLE_TEST_DATABASE_REQUIRED")
    try:
        parsed = make_url(raw)
    except Exception:
        raise LiveBailianKnowledgeE2EError(
            "DISPOSABLE_TEST_DATABASE_REQUIRED"
        ) from None
    if (
        parsed.drivername != "postgresql+psycopg"
        or parsed.host not in {"127.0.0.1", "localhost"}
        or parsed.query
        or _SAFE_DATABASE_NAME.fullmatch((parsed.database or "").lower()) is None
    ):
        raise LiveBailianKnowledgeE2EError("DISPOSABLE_TEST_DATABASE_REQUIRED")
    return raw


def _qdrant_url() -> str:
    raw = os.environ.get("TEST_QDRANT_URL", "")
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise LiveBailianKnowledgeE2EError("DISPOSABLE_TEST_QDRANT_REQUIRED")
    return raw.rstrip("/")


def _settings(
    *,
    api_key: SecretStr,
    database_url: str,
    qdrant_url: str,
    collection_name: str,
) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        secret_key="synthetic-local-e2e-signing-key-0000000000000000",
        database_url=database_url,
        redis_url="redis://:synthetic@127.0.0.1:6379/0",
        celery_broker_url="redis://:synthetic@127.0.0.1:6379/0",
        celery_result_backend="redis://:synthetic@127.0.0.1:6379/1",
        minio_endpoint="http://127.0.0.1:9000",
        minio_access_key="synthetic-local-e2e-minio-access",
        minio_secret_key="synthetic-local-e2e-minio-secret",
        qdrant_url=qdrant_url,
        qdrant_api_key=None,
        qdrant_collection=collection_name,
        qdrant_vector_size=LIVE_EMBEDDING_POLICY.embedding_dimension,
        ai_provider_calls_enabled=True,
        ai_policy_file="D:\\synthetic\\ai-policy-v2.json",
        llm_base_url="https://api.minimaxi.com/v1",
        llm_api_key="synthetic-local-e2e-unused-llm-key",
        llm_extraction_model="MiniMax-M3",
        llm_generation_model="MiniMax-M3",
        embedding_base_url=LIVE_EMBEDDING_POLICY.base_url,
        embedding_api_key=api_key,
        embedding_model=LIVE_EMBEDDING_POLICY.model_id,
        embedding_vector_size=LIVE_EMBEDDING_POLICY.embedding_dimension,
        embedding_batch_size=_EMBEDDING_BATCH_SIZE,
        metrics_internal_token="synthetic-local-e2e-metrics-token",
    )


def _adapter(api_key: SecretStr) -> OpenAiEmbeddingsAdapter:
    registry_bytes = (
        resources.files("app.ai.artifacts.cr011_v1")
        .joinpath("ip-deny-cidrs-v1.json")
        .read_bytes()
    )
    network_policy = OutboundNetworkPolicy(
        endpoint_id=LIVE_EMBEDDING_POLICY.endpoint_id,
        network_scope="external_public",
        base_url=LIVE_EMBEDDING_POLICY.base_url,
        approved_hostnames=LIVE_EMBEDDING_POLICY.approved_hostnames,
        allowed_cidrs=LIVE_EMBEDDING_POLICY.allowed_cidrs,
        billing_mode="external_cny",
        address_policy_version="ip-deny-cidrs-v1",
        registry_sha256=_REGISTRY_SHA256,
    )
    return OpenAiEmbeddingsAdapter(
        OpenAiCompatibleProfile(
            profile_type="embedding",
            base_url=LIVE_EMBEDDING_POLICY.base_url,
            model_id=LIVE_EMBEDDING_POLICY.model_id,
            allowed_response_model_ids=LIVE_EMBEDDING_POLICY.allowed_response_model_ids,
            api_key=api_key,
            network_policy=network_policy,
            registry_bytes=registry_bytes,
            max_request_bytes=LIVE_EMBEDDING_POLICY.max_request_bytes,
            max_response_header_bytes=LIVE_EMBEDDING_POLICY.max_response_header_bytes,
            max_response_body_bytes=LIVE_EMBEDDING_POLICY.max_response_body_bytes,
            embedding_dimension=LIVE_EMBEDDING_POLICY.embedding_dimension,
        )
    )


def _runtime(
    adapter: OpenAiEmbeddingsAdapter,
    audit: AiCallAuditService,
) -> EmbeddingRuntime:
    return EmbeddingRuntime(
        gateway=AiGateway(
            llm_adapters={},
            embedding_adapters={OPENAI_EMBEDDINGS_ADAPTER_ID: adapter},
        ),
        target=adapter.target,
        transport_policy=TransportPolicy(
            connect_timeout_seconds=5,
            read_timeout_seconds=LIVE_EMBEDDING_POLICY.operation.deadline_seconds,
            total_timeout_seconds=LIVE_EMBEDDING_POLICY.operation.deadline_seconds,
            max_attempts=1,
        ),
        policy_snapshot=ValidatedPolicySnapshot(
            policy_version=2,
            policy_hash=LIVE_POLICY_HASH,
            raw_sha256=LIVE_POLICY_RAW_SHA256,
            provider_calls_enabled=True,
            runtime_profile_id=LIVE_POLICY_ID,
        ),
        embedding_policy=LIVE_EMBEDDING_POLICY,
        audit_writer=audit,
    )


def _knowledge_pdf() -> bytes:
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=(800, 800), invariant=1)
    for section_no, (title, fact) in enumerate(_SECTION_FACTS, start=1):
        document.drawString(24, 760, title)
        y = 720
        for control_no in range(1, 11):
            document.drawString(
                24,
                y,
                f"{title} {control_no:02d}. {fact} Synthetic evidence "
                f"S{section_no:02d}-{control_no:02d}.",
            )
            y -= 58
        document.showPage()
    document.save()
    return output.getvalue()


def _verify_database(engine: Engine) -> None:
    with engine.connect() as connection:
        marker, revision = connection.execute(
            text(
                "SELECT shobj_description(database_catalog.oid, 'pg_database'), "
                "(SELECT version_num FROM alembic_version) "
                "FROM pg_database AS database_catalog "
                "WHERE database_catalog.datname=current_database()"
            )
        ).one()
    if marker != _DATABASE_MARKER or revision != _DATABASE_REVISION:
        raise LiveBailianKnowledgeE2EError("DISPOSABLE_TEST_DATABASE_REQUIRED")


def _create_collection(client: httpx.Client, collection_name: str) -> None:
    health = client.get("/healthz")
    if health.status_code != 200:
        raise LiveBailianKnowledgeE2EError("DISPOSABLE_TEST_QDRANT_NOT_READY")
    response = client.put(
        f"/collections/{collection_name}",
        json={
            "vectors": {
                "size": LIVE_EMBEDDING_POLICY.embedding_dimension,
                "distance": "Cosine",
            }
        },
    )
    if response.status_code != 200:
        raise LiveBailianKnowledgeE2EError("QDRANT_COLLECTION_CREATE_FAILED")


def _delete_collection(client: httpx.Client, collection_name: str) -> None:
    response = client.delete(f"/collections/{collection_name}")
    if response.status_code != 200:
        raise LiveBailianKnowledgeE2EError("QDRANT_COLLECTION_CLEANUP_FAILED")
    if client.get(f"/collections/{collection_name}").status_code != 404:
        raise LiveBailianKnowledgeE2EError("QDRANT_COLLECTION_CLEANUP_FAILED")


def _project_audit(audit: AiCallAuditService, expected_requests: int) -> int:
    projected = 0
    for _ in range(expected_requests * 2 + 1):
        result = audit.project_once()
        if result.event_id is None:
            break
        if result.status.value != "projected":
            raise LiveBailianKnowledgeE2EError("EMBEDDING_AUDIT_PROJECTION_FAILED")
        projected += 1
    if projected != expected_requests * 2:
        raise LiveBailianKnowledgeE2EError("EMBEDDING_AUDIT_PROJECTION_FAILED")
    return projected


def _execute(
    *,
    settings: Settings,
    api_key: SecretStr,
    vector_store: QdrantVectorAdapter,
) -> dict[str, object]:
    engine = create_migration_engine(
        parse_database_url(settings.database_url.get_secret_value())
    )
    adapter: OpenAiEmbeddingsAdapter | None = None
    try:
        _verify_database(engine)
        factory = create_session_factory(engine)
        _seed_actor(factory)
        _seed_knowledge_subjects(factory)
        quarantine = MemoryQuarantineStorage()
        intake = FileIntakeService(
            factory,
            cast(MinioQuarantineAdapter, quarantine),
            cast(
                Settings, SimpleNamespace(max_upload_size_mb=1, max_batch_file_count=20)
            ),
        )
        _, policy_id = _approved_policy(
            factory,
            intake,
            quarantine,
            payload=_knowledge_pdf(),
            file_name="synthetic-live-embedding-e2e.pdf",
            key_suffix="live-embedding-e2e",
            policy_code="SYNTH-LIVE-EMBEDDING-E2E",
            policy_name="Synthetic live embedding E2E policy",
        )
        with factory() as session:
            chunks = tuple(
                session.scalars(
                    select(DocumentChunk)
                    .join(
                        DocumentChunkSet,
                        DocumentChunkSet.id == DocumentChunk.chunk_set_id,
                    )
                    .where(DocumentChunkSet.policy_document_id == policy_id)
                    .order_by(DocumentChunk.chunk_index)
                ).all()
            )
        if not _SMOKE_CASE_COUNT <= len(chunks) <= _EMBEDDING_BATCH_SIZE:
            raise LiveBailianKnowledgeE2EError("SYNTHETIC_CHUNK_PLAN_OUT_OF_BOUNDS")

        target = ModelTarget(
            adapter_id=OPENAI_EMBEDDINGS_ADAPTER_ID,
            model_id=LIVE_EMBEDDING_POLICY.model_id,
        )
        management = KnowledgeIndexManagementService(
            factory,
            settings,
            embedding_target=target,
        )
        index = management.build_index(
            _publisher(),
            KNOWLEDGE_BASE_ID,
            "live-embedding-index-build-001",
            uuid4(),
        )
        with factory() as session:
            items = RetrievalRuntimeRepository(session).materialization_items(
                index.data.id
            )
        if len(items) != len(chunks):
            raise LiveBailianKnowledgeE2EError("INDEX_MEMBER_PLAN_DRIFT")

        cases = tuple(
            EvaluationCaseInput(
                label=EvaluationLabel.ANSWERABLE,
                query_text=(
                    f"{' '.join(chunk.content_text.split())} Synthetic smoke query {case_no}"
                ),
                baseline_date=date(2026, 8, 17),
                allowed_policy_ids=(policy_id,),
                expected_chunk_ids=(chunk.id,),
                forbidden_chunk_ids=(),
            )
            for case_no, chunk in enumerate(chunks[:_SMOKE_CASE_COUNT], start=1)
        )
        retrieval_text = cases[0].query_text
        planned_calls = (
            tuple(item.content_text for item in items),
            *(tuple([case.query_text]) for case in cases),
            (retrieval_text,),
        )

        audit = AiCallAuditService(factory)
        adapter = _adapter(api_key)
        bounded = _BoundedEmbeddingRuntime(_runtime(adapter, audit), planned_calls)
        executor = KnowledgeJobExecutor(
            factory,
            vector_store,
            cast(EmbeddingRuntime, bounded),
            embedding_batch_size=_EMBEDDING_BATCH_SIZE,
        )
        build_outbox = _dispatch_pending(factory, cast(UUID, index.data.job_id))
        built = executor.execute(
            job_id=cast(UUID, index.data.job_id),
            event_id=build_outbox.event_id,
            event_schema_version=build_outbox.event_version,
            worker_id="live-embedding-index-worker",
        )
        if built.outcome != "succeeded":
            raise LiveBailianKnowledgeE2EError("LIVE_INDEX_BUILD_FAILED")
        ready = management.get_index(_publisher(), KNOWLEDGE_BASE_ID, index.data.id)
        if ready.status.value != "ready" or ready.member_count != len(chunks):
            raise LiveBailianKnowledgeE2EError("LIVE_INDEX_READY_FACT_INVALID")

        dataset = management.create_dataset(
            _actor(ACTOR_ID),
            KNOWLEDGE_BASE_ID,
            EvaluationDatasetCreateRequest(
                name="Synthetic live embedding smoke v1",
                tier=EvaluationTier.SMOKE,
                answer_score_threshold="0",
                cases=cases,
            ),
            "live-embedding-dataset-create-001",
            uuid4(),
        )
        submitted = management.transition_dataset(
            _actor(ACTOR_ID),
            KNOWLEDGE_BASE_ID,
            dataset.data.id,
            VersionedTransitionRequest(
                row_version="1", reason="提交一次性真实 smoke 评测"
            ),
            "live-embedding-dataset-submit-001",
            uuid4(),
            action="submit",
        )
        approved = management.transition_dataset(
            _actor(APPROVER_ID),
            KNOWLEDGE_BASE_ID,
            dataset.data.id,
            VersionedTransitionRequest(
                row_version=submitted.data.row_version,
                reason="独立批准一次性真实 smoke 评测",
            ),
            "live-embedding-dataset-approve-001",
            uuid4(),
            action="approve",
        )
        if approved.data.status != "approved":
            raise LiveBailianKnowledgeE2EError("SMOKE_DATASET_APPROVAL_FAILED")

        run = management.create_evaluation_run(
            _publisher(),
            KNOWLEDGE_BASE_ID,
            ready.id,
            EvaluationRunRequest(dataset_id=dataset.data.id),
            "live-embedding-eval-run-001",
            uuid4(),
        )
        eval_outbox = _dispatch_pending(factory, run.data.job_id)
        evaluated = executor.execute(
            job_id=run.data.job_id,
            event_id=eval_outbox.event_id,
            event_schema_version=eval_outbox.event_version,
            worker_id="live-embedding-evaluation-worker",
        )
        evaluated_run = management.get_evaluation_run(
            _publisher(), KNOWLEDGE_BASE_ID, run.data.id
        )
        if (
            evaluated.outcome != "succeeded"
            or evaluated_run.status != "passed"
            or evaluated_run.completed_case_count != _SMOKE_CASE_COUNT
            or evaluated_run.metrics.get("case_pass_count") != _SMOKE_CASE_COUNT
        ):
            raise LiveBailianKnowledgeE2EError("LIVE_SMOKE_EVALUATION_FAILED")

        with factory() as session:
            allowed_ids = RetrievalRuntimeRepository(session).eval_allowed_point_ids(
                index_version_id=ready.id,
                baseline_date=date(2026, 8, 17),
                allowed_policy_ids=(policy_id,),
            )
        trace_id = uuid4()
        retrieval = bounded.embed_texts_audited(
            trace_id=str(trace_id),
            input_texts=(retrieval_text,),
            identity=EmbeddingCallIdentity(
                organization_id=ORGANIZATION_ID,
                business_operation_id=uuid4(),
                job_id=None,
                request_id=trace_id,
                resource_type="document_index_version",
                resource_id=ready.id,
                trace_id=trace_id,
            ),
            deadline_monotonic=time.monotonic()
            + LIVE_EMBEDDING_POLICY.operation.deadline_seconds,
        )
        try:
            hits = vector_store.query_authorized(
                retrieval.vectors[0],
                allowed_point_ids=allowed_ids,
                limit=5,
            )
            if len(hits) != 5:
                raise LiveBailianKnowledgeE2EError("TOP_5_RETRIEVAL_FAILED")
            with factory.begin() as session:
                retrieval.adoption.adopt_in_transaction(session)
        except Exception:
            with factory.begin() as session:
                retrieval.adoption.reject_in_transaction(
                    session,
                    safe_error_code="TOP_5_RETRIEVAL_FAILED",
                )
            raise

        try:
            management.activate_index(
                _publisher(),
                KNOWLEDGE_BASE_ID,
                ready.id,
                VersionedTransitionRequest(
                    row_version=ready.row_version,
                    reason="验证 smoke 不得越过正式发布门禁",
                ),
                "live-embedding-index-activate-001",
                uuid4(),
            )
        except AppError as error:
            if error.code != "FORMAL_EVALUATION_REQUIRED":
                raise
        else:
            raise LiveBailianKnowledgeE2EError("FORMAL_ACTIVATION_GATE_BYPASSED")
        final_index = management.get_index(_publisher(), KNOWLEDGE_BASE_ID, ready.id)
        if final_index.status.value != "ready":
            raise LiveBailianKnowledgeE2EError("FORMAL_ACTIVATION_GATE_BYPASSED")

        bounded.assert_consumed()
        projected_event_count = _project_audit(audit, bounded.provider_request_count)
        with factory() as session:
            logs = tuple(
                session.scalars(
                    select(AiCallLog)
                    .where(
                        AiCallLog.organization_id == ORGANIZATION_ID,
                        AiCallLog.call_type == "embedding",
                    )
                    .order_by(AiCallLog.started_at, AiCallLog.id)
                ).all()
            )
            evaluation_result_count = session.scalar(
                select(func.count()).select_from(RetrievalEvalResult)
            )
        if (
            len(logs) != bounded.provider_request_count
            or any(
                log.event_version != 2
                or log.event_sequence != 2
                or log.status != "succeeded"
                or log.cost_currency != "CNY"
                or log.input_tokens is None
                or log.actual_cost_microunits is None
                for log in logs
            )
            or sum(cast(int, log.input_tokens) for log in logs)
            != bounded.actual_input_tokens
            or sum(cast(int, log.actual_cost_microunits) for log in logs)
            != bounded.actual_cost_microunits
            or evaluation_result_count != _SMOKE_CASE_COUNT
        ):
            raise LiveBailianKnowledgeE2EError("EMBEDDING_AUDIT_VERIFICATION_FAILED")

        return {
            "actual_cost_microunits": bounded.actual_cost_microunits,
            "actual_input_tokens": bounded.actual_input_tokens,
            "activation_gate": "formal_evaluation_required",
            "audit_attempt_count": len(logs),
            "audit_projected_event_count": projected_event_count,
            "cost_currency": "CNY",
            "index_member_count": ready.member_count,
            "index_status": final_index.status.value,
            "input_token_upper_bound": bounded.input_token_upper_bound,
            "provider_request_count": bounded.provider_request_count,
            "qdrant_collection_verified": True,
            "smoke_case_count": _SMOKE_CASE_COUNT,
            "smoke_pass_count": _SMOKE_CASE_COUNT,
            "status": "passed",
            "top_k": 5,
            "top_k_retrieved_count": len(hits),
            "vector_dimension": settings.qdrant_vector_size,
            "worker_index_outcome": built.outcome,
        }
    finally:
        if adapter is not None:
            adapter.close()
        engine.dispose()


def _run() -> dict[str, object]:
    if sys.argv != [sys.argv[0]]:
        raise LiveBailianKnowledgeE2EError("ARGUMENTS_NOT_SUPPORTED")
    if os.environ.get("FINAUDIT_LIVE_BAILIAN_KNOWLEDGE_E2E") != _CONFIRMATION:
        raise LiveBailianKnowledgeE2EError(
            "LIVE_BAILIAN_KNOWLEDGE_E2E_CONFIRMATION_REQUIRED"
        )
    api_key = _api_key()
    database_url = _database_url()
    qdrant_url = _qdrant_url()
    collection_name = f"finaudit_live_bailian_e2e_{uuid4().hex}"
    settings = _settings(
        api_key=api_key,
        database_url=database_url,
        qdrant_url=qdrant_url,
        collection_name=collection_name,
    )
    admin_client = httpx.Client(base_url=qdrant_url, timeout=10.0, trust_env=False)
    vector_store: QdrantVectorAdapter | None = None
    collection_created = False
    summary: dict[str, object] | None = None
    try:
        _create_collection(admin_client, collection_name)
        collection_created = True
        vector_store = QdrantVectorAdapter(settings)
        vector_store.verify_collection()
        summary = _execute(
            settings=settings, api_key=api_key, vector_store=vector_store
        )
    finally:
        if vector_store is not None:
            vector_store.close()
        if collection_created:
            _delete_collection(admin_client, collection_name)
        admin_client.close()
    if summary is None:
        raise LiveBailianKnowledgeE2EError("LIVE_BAILIAN_KNOWLEDGE_E2E_FAILED")
    summary["qdrant_collection_deleted"] = True
    return summary


def main() -> int:
    try:
        summary = _run()
    except LiveBailianKnowledgeE2EError as error:
        print(
            json.dumps({"code": str(error), "status": "failed"}, separators=(",", ":"))
        )
        return 1
    except EmbeddingInvocationError as error:
        print(
            json.dumps({"code": error.code, "status": "failed"}, separators=(",", ":"))
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {"code": "LIVE_BAILIAN_KNOWLEDGE_E2E_UNEXPECTED", "status": "failed"},
                separators=(",", ":"),
            )
        )
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
