from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import zipfile
from datetime import date
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4
from xml.sax.saxutils import escape

import httpx
from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import smoke_live_bailian_knowledge_e2e as smoke  # noqa: E402

from app.adapters.minio_quarantine import MinioQuarantineAdapter  # noqa: E402
from app.adapters.qdrant_vector import QdrantVectorAdapter  # noqa: E402
from app.ai.adapters.openai_compatible import OPENAI_EMBEDDINGS_ADAPTER_ID  # noqa: E402
from app.ai.contracts import ModelTarget  # noqa: E402
from app.ai.embedding_runtime import EmbeddingInvocationError, EmbeddingRuntime  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.db.migration import create_migration_engine  # noqa: E402
from app.db.session import create_session_factory  # noqa: E402
from app.models.audit import AiCallLog  # noqa: E402
from app.models.knowledge import DocumentChunk, DocumentChunkSet  # noqa: E402
from app.models.retrieval import (  # noqa: E402
    DocumentIndexVersion,
    RetrievalEvalDataset,
    RetrievalEvalResult,
    RetrievalEvalRun,
)
from app.repositories.retrieval_runtime import RetrievalRuntimeRepository  # noqa: E402
from app.schemas.files import (  # noqa: E402
    FileUploadIntent,
    IntendedBusinessType,
)
from app.schemas.policies import PolicyCreateRequest, PolicyTransitionRequest  # noqa: E402
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
from app.services.policy_management import PolicyManagementService  # noqa: E402
from tests.integration.database.test_contract_extraction_management import (  # noqa: E402
    _CleanDocumentScanner,
)
from tests.integration.database.test_file_intake_service import (  # noqa: E402
    ACTOR_ID,
    ORGANIZATION_ID,
    MemoryQuarantineStorage,
)
from tests.integration.database.test_file_job_executor import (  # noqa: E402
    _dispatch_pending,
    _executor,
    _RuntimeStorage,
)
from tests.integration.database.test_policy_management import (  # noqa: E402
    APPROVER_ID,
    KNOWLEDGE_BASE_ID,
    _actor,
)

_CONFIRMATION = "ALLOW_ONE_BOUNDED_BAILIAN_SYNTHETIC_BENCHMARK_V2_BATCHED_100"
_REVIEW_PATH = (
    PROJECT_ROOT / "tests" / "evaluation" / "synthetic-benchmark-owner-delegated-review-v1.json"
)
_CORPUS_PATH = PROJECT_ROOT / "tests" / "evaluation" / "synthetic-policy-corpus-v1.json"
_REVIEW_SHA256 = "87F5627F0306AA4D5B89E148EB0B4C8D970E80956CFAE624F0783BB66B3DA70F"
_CORPUS_SHA256 = "2CE2BE5118ADAC7D185D239AFD4713D3F637BDF9D12D314D7690732A8DFAD9E3"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_ANSWER_SCORE_THRESHOLD = "0.650000"
_MAX_PROVIDER_REQUESTS = 100
_MAX_INPUT_TOKENS = 50_000
_MAX_COST_MICROCNY = 10_000_000
_EMBEDDING_BATCH_SIZE = 20
_EVALUATION_EMBEDDING_BATCH_SIZE = 20
_EXPECTED_PROVIDER_REQUESTS = 10
_SAFE_FAILURE_TELEMETRY: dict[str, object] = {}


class LiveSyntheticBenchmarkError(RuntimeError):
    pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _batched_texts(values: tuple[str, ...], batch_size: int) -> tuple[tuple[str, ...], ...]:
    if not values or not 1 <= batch_size <= _EMBEDDING_BATCH_SIZE:
        raise LiveSyntheticBenchmarkError("PROVIDER_REQUEST_PLAN_INVALID")
    return tuple(
        values[offset : offset + batch_size] for offset in range(0, len(values), batch_size)
    )


def _object(path: Path, expected_sha256: str) -> dict[str, object]:
    payload = path.read_bytes()
    if _sha256(payload) != expected_sha256:
        raise LiveSyntheticBenchmarkError("SYNTHETIC_ASSET_HASH_DRIFT")
    value = json.loads(payload)
    if type(value) is not dict:
        raise LiveSyntheticBenchmarkError("SYNTHETIC_ASSET_INVALID")
    return value


def _load_assets() -> tuple[dict[str, object], dict[str, object]]:
    review = _object(_REVIEW_PATH, _REVIEW_SHA256)
    corpus = _object(_CORPUS_PATH, _CORPUS_SHA256)
    if (
        review.get("schema_version") != "synthetic-benchmark-owner-delegated-review-v1"
        or corpus.get("schema_version") != "synthetic-policy-corpus-v1"
    ):
        raise LiveSyntheticBenchmarkError("SYNTHETIC_ASSET_INVALID")
    authority = cast(dict[str, object], review.get("review_authority"))
    authorization = cast(dict[str, object], review.get("runtime_authorization"))
    boundaries = cast(dict[str, object], review.get("boundaries"))
    expected_authorization = {
        "activate_disposable_index": True,
        "automatic_scope_expansion": False,
        "cost_cap_cny": "1.000000",
        "create_disposable_approved_datasets": True,
        "input_token_cap": 50_000,
        "no_fx": True,
        "production": False,
        "provider_request_cap": 152,
        "run_formal_release": True,
        "run_mvp_uat": True,
        "single_run": True,
    }
    if (
        authority.get("human_review_claimed") is not False
        or authorization != expected_authorization
        or boundaries.get("may_mark_ac_accepted") is not False
    ):
        raise LiveSyntheticBenchmarkError("SYNTHETIC_REVIEW_AUTHORIZATION_INVALID")
    return review, corpus


def _clause_docx(title: str, clause_ref: str, heading: str, topic: str, text: str) -> bytes:
    lines = (title, f"证据编号 {clause_ref}；主题 {topic}；条款标题 {heading}。{text}")
    paragraphs = "".join(f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>" for line in lines)
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>'
        f"{paragraphs}<w:sectPr/></w:body></w:document>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def _approved_clause_policy(
    *,
    factory: object,
    intake: FileIntakeService,
    file_executor: object,
    policies: PolicyManagementService,
    ordinal: int,
    family: dict[str, object],
    policy: dict[str, object],
    clause: dict[str, object],
) -> tuple[UUID, UUID]:
    policy_ref = str(policy["policy_ref"])
    clause_ref = str(clause["clause_ref"])
    payload = _clause_docx(
        str(policy["title"]),
        clause_ref,
        str(clause["heading"]),
        str(clause["topic"]),
        str(clause["text"]),
    )
    uploaded = intake.upload(
        _actor(ACTOR_ID),
        FileUploadIntent(
            intended_business_type=IntendedBusinessType.POLICY,
            target_knowledge_base_id=KNOWLEDGE_BASE_ID,
        ),
        file_name=f"synthetic-benchmark-clause-{ordinal:03d}.docx",
        declared_mime=_DOCX_MIME,
        stream=io.BytesIO(payload),
        idempotency_key=f"synthetic-benchmark-file-{ordinal:03d}",
        trace_id=uuid4(),
    )
    outbox = _dispatch_pending(factory, uploaded.data.job_id)  # type: ignore[arg-type]
    executed = file_executor.execute(
        job_id=uploaded.data.job_id,
        event_id=outbox.event_id,
        event_schema_version=outbox.event_version,
        worker_id="synthetic-benchmark-document-worker",
    )
    if executed.outcome != "succeeded":
        raise LiveSyntheticBenchmarkError("SYNTHETIC_POLICY_PROCESSING_FAILED")

    version_no = int(policy["version_no"])
    policy_code = clause_ref.replace("#", "-").replace(".", "-")
    created = policies.create(
        _actor(ACTOR_ID),
        PolicyCreateRequest(
            knowledge_base_id=KNOWLEDGE_BASE_ID,
            source_file_id=uploaded.data.file_id,
            policy_code=policy_code,
            name=f"{family['title']} / {clause['heading']}",
            version=f"{version_no}.0",
            issuing_department="虚构测试制度管理部",
            effective_from=date.fromisoformat(str(policy["valid_from"])),
            effective_to=(
                None if policy["valid_to"] is None else date.fromisoformat(str(policy["valid_to"]))
            ),
            scope={"classification": "synthetic", "source_policy_ref": policy_ref},
        ),
        f"synthetic-benchmark-policy-create-{ordinal:03d}",
        uuid4(),
    )
    submitted = policies.submit(
        _actor(ACTOR_ID),
        created.data.policy.id,
        PolicyTransitionRequest(
            row_version=created.data.policy.row_version,
            reason="提交 BOSS 委托的 local/test 合成评测条款",
        ),
        f"synthetic-benchmark-policy-submit-{ordinal:03d}",
        uuid4(),
    )
    approved = policies.approve(
        _actor(APPROVER_ID),
        created.data.policy.id,
        PolicyTransitionRequest(
            row_version=submitted.data.policy.row_version,
            reason="独立 Actor 批准 BOSS 委托的 local/test 合成评测条款",
        ),
        f"synthetic-benchmark-policy-approve-{ordinal:03d}",
        uuid4(),
    )
    if approved.data.policy.status.value != "business_approved":
        raise LiveSyntheticBenchmarkError("SYNTHETIC_POLICY_APPROVAL_FAILED")

    with factory() as session:  # type: ignore[operator]
        chunks = tuple(
            session.scalars(
                select(DocumentChunk)
                .join(DocumentChunkSet, DocumentChunkSet.id == DocumentChunk.chunk_set_id)
                .where(
                    DocumentChunkSet.policy_document_id == created.data.policy.id,
                    DocumentChunkSet.status == "active",
                )
            ).all()
        )
    matching = tuple(chunk for chunk in chunks if str(clause["text"]) in chunk.content_text)
    if len(chunks) != 1 or len(matching) != 1:
        raise LiveSyntheticBenchmarkError("SYNTHETIC_CLAUSE_MAPPING_FAILED")
    return created.data.policy.id, matching[0].id


def _runtime_case(
    case: dict[str, object],
    *,
    policy_ids: dict[str, tuple[UUID, ...]],
    chunk_ids: dict[str, UUID],
) -> EvaluationCaseInput:
    label = EvaluationLabel(str(case["label"]))
    allowed = tuple(
        policy_id
        for policy_ref in cast(list[str], case["allowed_policy_refs"])
        for policy_id in policy_ids[policy_ref]
    )
    expected = tuple(chunk_ids[ref] for ref in cast(list[str], case["expected_evidence_refs"]))
    forbidden = (
        tuple(chunk_ids[ref] for ref in cast(list[str], case["forbidden_evidence_refs"]))
        if label is EvaluationLabel.UNAUTHORIZED
        else ()
    )
    return EvaluationCaseInput(
        label=label,
        query_text=str(case["query_text"]),
        baseline_date=date.fromisoformat(str(case["benchmark_date"])),
        allowed_policy_ids=allowed,
        expected_chunk_ids=expected,
        forbidden_chunk_ids=forbidden,
    )


def _create_approved_dataset(
    management: KnowledgeIndexManagementService,
    *,
    tier: EvaluationTier,
    cases: tuple[EvaluationCaseInput, ...],
    source_case_ids: tuple[str, ...],
    suffix: str,
) -> tuple[UUID, dict[UUID, str]]:
    if len(source_case_ids) != len(cases) or len(set(source_case_ids)) != len(cases):
        raise LiveSyntheticBenchmarkError("SYNTHETIC_SOURCE_CASE_MAPPING_INVALID")
    dataset = management.create_dataset(
        _actor(ACTOR_ID),
        KNOWLEDGE_BASE_ID,
        EvaluationDatasetCreateRequest(
            name=f"Synthetic owner-delegated {tier.value} v1",
            tier=tier,
            answer_score_threshold=_ANSWER_SCORE_THRESHOLD,
            cases=cases,
        ),
        f"synthetic-benchmark-dataset-create-{suffix}",
        uuid4(),
    )
    submitted = management.transition_dataset(
        _actor(ACTOR_ID),
        KNOWLEDGE_BASE_ID,
        dataset.data.id,
        VersionedTransitionRequest(
            row_version=dataset.data.row_version,
            reason="提交 BOSS 委托的 local/test 合成检索评测集",
        ),
        f"synthetic-benchmark-dataset-submit-{suffix}",
        uuid4(),
        action="submit",
    )
    approved = management.transition_dataset(
        _actor(APPROVER_ID),
        KNOWLEDGE_BASE_ID,
        dataset.data.id,
        VersionedTransitionRequest(
            row_version=submitted.data.row_version,
            reason="独立 Actor 批准 BOSS 委托的 local/test 合成检索评测集",
        ),
        f"synthetic-benchmark-dataset-approve-{suffix}",
        uuid4(),
        action="approve",
    )
    if (
        approved.data.status != "approved"
        or approved.data.approved_by == approved.data.submitted_by
    ):
        raise LiveSyntheticBenchmarkError("SYNTHETIC_DATASET_APPROVAL_FAILED")
    with management._session_factory() as session:
        stored_cases = RetrievalRuntimeRepository(session).dataset_cases(approved.data.id)
    if len(stored_cases) != len(source_case_ids):
        raise LiveSyntheticBenchmarkError("SYNTHETIC_SOURCE_CASE_MAPPING_INVALID")
    return approved.data.id, {
        stored.id: source_id
        for stored, source_id in zip(stored_cases, source_case_ids, strict=True)
    }


def _execute_run(
    *,
    management: KnowledgeIndexManagementService,
    executor: KnowledgeJobExecutor,
    index_id: UUID,
    dataset_id: UUID,
    case_source_ids: dict[UUID, str],
    suffix: str,
    expected_count: int,
) -> tuple[UUID, dict[str, object]]:
    run = management.create_evaluation_run(
        smoke._publisher(),
        KNOWLEDGE_BASE_ID,
        index_id,
        EvaluationRunRequest(dataset_id=dataset_id),
        f"synthetic-benchmark-eval-run-{suffix}",
        uuid4(),
    )
    outbox = _dispatch_pending(management._session_factory, run.data.job_id)
    executed = executor.execute(
        job_id=run.data.job_id,
        event_id=outbox.event_id,
        event_schema_version=outbox.event_version,
        worker_id=f"synthetic-benchmark-evaluation-{suffix}",
    )
    final = management.get_evaluation_run(smoke._publisher(), KNOWLEDGE_BASE_ID, run.data.id)
    if (
        executed.outcome != "succeeded"
        or final.status != "passed"
        or final.completed_case_count != expected_count
        or final.metrics.get("case_pass_count") != expected_count
        or final.metrics.get("authorization_leak_count") != 0
    ):
        with management._session_factory() as session:
            failed_runtime_case_ids = tuple(
                session.scalars(
                    select(RetrievalEvalResult.case_id)
                    .where(
                        RetrievalEvalResult.run_id == final.id,
                        RetrievalEvalResult.passed.is_(False),
                    )
                    .order_by(RetrievalEvalResult.case_id)
                ).all()
            )
        try:
            failed_case_ids = tuple(case_source_ids[value] for value in failed_runtime_case_ids)
        except KeyError:
            raise LiveSyntheticBenchmarkError(
                "SYNTHETIC_SOURCE_CASE_MAPPING_INVALID"
            ) from None
        _SAFE_FAILURE_TELEMETRY.update(
            evaluation_failed_case_ids=failed_case_ids,
            evaluation_failure_code=final.failure_code,
            evaluation_metrics=dict(final.metrics),
            evaluation_status=final.status,
            evaluation_tier=suffix,
        )
        raise LiveSyntheticBenchmarkError(f"{suffix.upper()}_EVALUATION_FAILED")
    return final.id, dict(final.metrics)


def _execute(
    *,
    settings: object,
    api_key: object,
    vector_store: QdrantVectorAdapter,
    review: dict[str, object],
    corpus: dict[str, object],
) -> dict[str, object]:
    engine = create_migration_engine(
        smoke.parse_database_url(settings.database_url.get_secret_value())
    )
    adapter = None
    bounded = None
    try:
        smoke._verify_database(engine)
        factory = create_session_factory(engine)
        smoke._seed_actor(factory)
        smoke._seed_knowledge_subjects(factory)
        quarantine = MemoryQuarantineStorage()
        intake = FileIntakeService(
            factory,
            cast(MinioQuarantineAdapter, quarantine),
            cast(
                object,
                type(
                    "UploadSettings",
                    (),
                    {"max_upload_size_mb": 1, "max_batch_file_count": 20},
                )(),
            ),
        )
        file_executor = _executor(factory, _RuntimeStorage(quarantine), _CleanDocumentScanner())
        policies = PolicyManagementService(factory)

        policy_ids_mutable: dict[str, list[UUID]] = {}
        chunk_ids: dict[str, UUID] = {}
        ordinal = 0
        for family_value in cast(list[object], corpus["policy_families"]):
            family = cast(dict[str, object], family_value)
            for policy_value in cast(list[object], family["policy_versions"]):
                policy = cast(dict[str, object], policy_value)
                policy_ref = str(policy["policy_ref"])
                policy_ids_mutable[policy_ref] = []
                for clause_value in cast(list[object], policy["clauses"]):
                    clause = cast(dict[str, object], clause_value)
                    ordinal += 1
                    policy_id, chunk_id = _approved_clause_policy(
                        factory=factory,
                        intake=intake,
                        file_executor=file_executor,
                        policies=policies,
                        ordinal=ordinal,
                        family=family,
                        policy=policy,
                        clause=clause,
                    )
                    policy_ids_mutable[policy_ref].append(policy_id)
                    chunk_ids[str(clause["clause_ref"])] = chunk_id
        if ordinal != 36 or len(chunk_ids) != 36:
            raise LiveSyntheticBenchmarkError("SYNTHETIC_CORPUS_PROJECTION_INVALID")
        policy_ids = {key: tuple(value) for key, value in policy_ids_mutable.items()}

        formal_section = cast(dict[str, object], review["formal_candidate_100"])
        formal_raw = cast(list[object], formal_section["cases"])
        formal_cases = tuple(
            _runtime_case(
                cast(dict[str, object], case),
                policy_ids=policy_ids,
                chunk_ids=chunk_ids,
            )
            for case in formal_raw
        )
        formal_by_id = {
            str(cast(dict[str, object], raw)["case_id"]): case
            for raw, case in zip(formal_raw, formal_cases, strict=True)
        }
        mvp_ids = cast(dict[str, object], review["mvp_uat_subset_50"])["case_ids"]
        formal_source_case_ids = tuple(
            str(cast(dict[str, object], raw)["case_id"]) for raw in formal_raw
        )
        mvp_source_case_ids = tuple(str(case_id) for case_id in cast(list[object], mvp_ids))
        mvp_cases = tuple(formal_by_id[str(case_id)] for case_id in cast(list[object], mvp_ids))
        if len(mvp_cases) != 50 or len(formal_cases) != 100:
            raise LiveSyntheticBenchmarkError("SYNTHETIC_RUNTIME_CASE_COUNT_INVALID")

        target = ModelTarget(
            adapter_id=OPENAI_EMBEDDINGS_ADAPTER_ID,
            model_id=smoke.LIVE_EMBEDDING_POLICY.model_id,
        )
        management = KnowledgeIndexManagementService(
            factory,
            settings,
            embedding_target=target,
        )
        index = management.build_index(
            smoke._publisher(),
            KNOWLEDGE_BASE_ID,
            "synthetic-benchmark-index-build-001",
            uuid4(),
        )
        with factory() as session:
            items = RetrievalRuntimeRepository(session).materialization_items(index.data.id)
        if len(items) != 36:
            raise LiveSyntheticBenchmarkError("SYNTHETIC_INDEX_MEMBER_PLAN_DRIFT")
        index_calls = tuple(
            tuple(item.content_text for item in items[offset : offset + _EMBEDDING_BATCH_SIZE])
            for offset in range(0, len(items), _EMBEDDING_BATCH_SIZE)
        )
        mvp_calls = _batched_texts(
            tuple(case.query_text for case in mvp_cases),
            _EVALUATION_EMBEDDING_BATCH_SIZE,
        )
        formal_calls = _batched_texts(
            tuple(case.query_text for case in formal_cases),
            _EVALUATION_EMBEDDING_BATCH_SIZE,
        )
        planned_calls = (
            *index_calls,
            *mvp_calls,
            *formal_calls,
        )
        if len(planned_calls) != _EXPECTED_PROVIDER_REQUESTS:
            raise LiveSyntheticBenchmarkError("PROVIDER_REQUEST_PLAN_INVALID")

        audit = AiCallAuditService(factory)
        adapter = smoke._adapter(api_key)
        bounded = smoke._BoundedEmbeddingRuntime(
            smoke._runtime(adapter, audit),
            planned_calls,
            max_provider_requests=_MAX_PROVIDER_REQUESTS,
            max_input_tokens=_MAX_INPUT_TOKENS,
            max_cost_microunits=_MAX_COST_MICROCNY,
        )
        executor = KnowledgeJobExecutor(
            factory,
            vector_store,
            cast(EmbeddingRuntime, bounded),
            embedding_batch_size=_EMBEDDING_BATCH_SIZE,
            evaluation_embedding_batch_size=_EVALUATION_EMBEDDING_BATCH_SIZE,
        )
        build_outbox = _dispatch_pending(factory, cast(UUID, index.data.job_id))
        built = executor.execute(
            job_id=cast(UUID, index.data.job_id),
            event_id=build_outbox.event_id,
            event_schema_version=build_outbox.event_version,
            worker_id="synthetic-benchmark-index-worker",
        )
        ready = management.get_index(smoke._publisher(), KNOWLEDGE_BASE_ID, index.data.id)
        if (
            built.outcome != "succeeded"
            or ready.status.value != "ready"
            or ready.member_count != 36
        ):
            raise LiveSyntheticBenchmarkError("SYNTHETIC_INDEX_BUILD_FAILED")

        mvp_dataset_id, mvp_case_source_ids = _create_approved_dataset(
            management,
            tier=EvaluationTier.MVP_UAT,
            cases=mvp_cases,
            source_case_ids=mvp_source_case_ids,
            suffix="mvp-uat-050",
        )
        _, mvp_metrics = _execute_run(
            management=management,
            executor=executor,
            index_id=ready.id,
            dataset_id=mvp_dataset_id,
            case_source_ids=mvp_case_source_ids,
            suffix="mvp-uat-050",
            expected_count=50,
        )
        formal_dataset_id, formal_case_source_ids_by_runtime_id = _create_approved_dataset(
            management,
            tier=EvaluationTier.FORMAL_RELEASE,
            cases=formal_cases,
            source_case_ids=formal_source_case_ids,
            suffix="formal-release-100",
        )
        _, formal_metrics = _execute_run(
            management=management,
            executor=executor,
            index_id=ready.id,
            dataset_id=formal_dataset_id,
            case_source_ids=formal_case_source_ids_by_runtime_id,
            suffix="formal-release-100",
            expected_count=100,
        )

        activated = management.activate_index(
            smoke._publisher(),
            KNOWLEDGE_BASE_ID,
            ready.id,
            VersionedTransitionRequest(
                row_version=ready.row_version,
                reason="BOSS 委托的 local/test 100 条 formal_release 技术门禁通过",
            ),
            "synthetic-benchmark-index-activate-001",
            uuid4(),
        )
        if activated.data.status.value != "active":
            raise LiveSyntheticBenchmarkError("FORMAL_RELEASE_ACTIVATION_FAILED")

        bounded.assert_consumed()
        projected_event_count = smoke._project_audit(audit, bounded.provider_request_count)
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
            result_count = session.scalar(select(func.count()).select_from(RetrievalEvalResult))
            dataset_rows = tuple(session.scalars(select(RetrievalEvalDataset)).all())
            run_rows = tuple(session.scalars(select(RetrievalEvalRun)).all())
            stored_index = session.get(DocumentIndexVersion, ready.id)
        if (
            len(logs) != _EXPECTED_PROVIDER_REQUESTS
            or result_count != 150
            or len(dataset_rows) != 2
            or any(
                row.status != "approved" or row.approved_by == row.submitted_by
                for row in dataset_rows
            )
            or len(run_rows) != 2
            or any(row.status != "passed" for row in run_rows)
            or stored_index is None
            or stored_index.status != "active"
            or any(
                log.event_version != 2
                or log.event_sequence != 2
                or log.status != "succeeded"
                or log.cost_currency != "CNY"
                or log.input_tokens is None
                or log.actual_cost_microunits is None
                for log in logs
            )
            or sum(cast(int, log.input_tokens) for log in logs) != bounded.actual_input_tokens
            or sum(cast(int, log.actual_cost_microunits) for log in logs)
            != bounded.actual_cost_microunits
        ):
            raise LiveSyntheticBenchmarkError("SYNTHETIC_BENCHMARK_AUDIT_INVALID")

        return {
            "actual_cost_microunits": bounded.actual_cost_microunits,
            "actual_input_tokens": bounded.actual_input_tokens,
            "answer_score_threshold": _ANSWER_SCORE_THRESHOLD,
            "audit_attempt_count": len(logs),
            "audit_projected_event_count": projected_event_count,
            "cost_currency": "CNY",
            "dataset_approval_mode": "owner_delegated_local_test_independent_actor",
            "formal_release_case_count": 100,
            "formal_release_metrics": formal_metrics,
            "human_review_claimed": False,
            "index_member_count": ready.member_count,
            "index_status": "active",
            "input_token_upper_bound": bounded.input_token_upper_bound,
            "is_formal_ac_acceptance": False,
            "mvp_uat_case_count": 50,
            "mvp_uat_metrics": mvp_metrics,
            "provider_request_cap": _MAX_PROVIDER_REQUESTS,
            "provider_request_count": bounded.provider_request_count,
            "qdrant_collection_verified": True,
            "status": "passed",
            "vector_dimension": settings.qdrant_vector_size,
            "worker_index_outcome": built.outcome,
        }
    except Exception:
        if bounded is not None:
            _SAFE_FAILURE_TELEMETRY.update(
                actual_cost_microunits=bounded.actual_cost_microunits,
                actual_input_tokens=bounded.actual_input_tokens,
                cost_currency="CNY",
                input_token_upper_bound=bounded.input_token_upper_bound,
                provider_request_count=bounded.provider_request_count,
            )
        raise
    finally:
        if adapter is not None:
            adapter.close()
        engine.dispose()


def _run() -> dict[str, object]:
    if sys.argv != [sys.argv[0]]:
        raise LiveSyntheticBenchmarkError("ARGUMENTS_NOT_SUPPORTED")
    if os.environ.get("FINAUDIT_LIVE_BAILIAN_SYNTHETIC_BENCHMARK") != _CONFIRMATION:
        raise LiveSyntheticBenchmarkError("LIVE_SYNTHETIC_BENCHMARK_CONFIRMATION_REQUIRED")
    review, corpus = _load_assets()
    api_key = smoke._api_key()
    database_url = smoke._database_url()
    qdrant_url = smoke._qdrant_url()
    collection_name = f"finaudit_live_benchmark_{uuid4().hex}"
    settings = smoke._settings(
        api_key=api_key,
        database_url=database_url,
        qdrant_url=qdrant_url,
        collection_name=collection_name,
    )
    admin_client = httpx.Client(base_url=qdrant_url, timeout=10.0, trust_env=False)
    vector_store = None
    collection_created = False
    summary = None
    try:
        smoke._create_collection(admin_client, collection_name)
        collection_created = True
        vector_store = QdrantVectorAdapter(settings)
        vector_store.verify_collection()
        summary = _execute(
            settings=settings,
            api_key=api_key,
            vector_store=vector_store,
            review=review,
            corpus=corpus,
        )
    finally:
        if vector_store is not None:
            vector_store.close()
        if collection_created:
            smoke._delete_collection(admin_client, collection_name)
        admin_client.close()
    if summary is None:
        raise LiveSyntheticBenchmarkError("LIVE_SYNTHETIC_BENCHMARK_FAILED")
    summary["qdrant_collection_deleted"] = True
    return summary


def main() -> int:
    _SAFE_FAILURE_TELEMETRY.clear()
    try:
        summary = _run()
    except LiveSyntheticBenchmarkError as error:
        result = {"code": str(error), "status": "failed"}
    except smoke.LiveBailianKnowledgeE2EError as error:
        result = {"code": str(error), "status": "failed"}
    except EmbeddingInvocationError as error:
        result = {"code": error.code, "status": "failed"}
    except AppError as error:
        result = {"code": error.code, "status": "failed"}
    except Exception:
        result = {"code": "LIVE_SYNTHETIC_BENCHMARK_UNEXPECTED", "status": "failed"}
    else:
        result = summary
    if result.get("status") == "failed":
        result.update(_SAFE_FAILURE_TELEMETRY)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
