"""知识索引、检索评测与 RAG 查询的 PostgreSQL 权威事实。"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

INDEX_VERSION_STATUSES = ("building", "ready", "active", "failed", "superseded", "archived")
RETRIEVAL_EVAL_TIERS = ("smoke", "mvp_uat", "formal_release")
RETRIEVAL_EVAL_DATASET_STATUSES = ("draft", "submitted", "approved", "superseded")
RETRIEVAL_EVAL_RUN_STATUSES = ("running", "passed", "failed")
QA_QUERY_STATUSES = ("answered", "refused", "service_degraded")


class DocumentIndexVersion(Base):
    __tablename__ = "document_index_versions"
    __table_args__ = (
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint(
            "status IN ('building','ready','active','failed','superseded','archived')",
            name="status_allowed",
        ),
        CheckConstraint("vector_dimension > 0", name="vector_dimension_positive"),
        CheckConstraint(
            "distance IN ('Cosine','Dot','Euclid','Manhattan')", name="distance_allowed"
        ),
        CheckConstraint("member_count >= 0", name="member_count_nonnegative"),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="manifest_hash_format"),
        CheckConstraint("jsonb_typeof(consistency_json) = 'object'", name="consistency_object"),
        CheckConstraint(
            "(status = 'active' AND activated_by IS NOT NULL AND activated_at IS NOT NULL "
            "AND superseded_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'superseded' AND activated_by IS NOT NULL AND activated_at IS NOT NULL "
            "AND superseded_at IS NOT NULL AND superseded_at >= activated_at "
            "AND failure_code IS NULL) OR "
            "(status = 'failed' AND activated_by IS NULL AND activated_at IS NULL "
            "AND superseded_at IS NULL AND failure_code IS NOT NULL) OR "
            "(status IN ('building','ready') AND activated_by IS NULL "
            "AND activated_at IS NULL AND superseded_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'archived' AND failure_code IS NULL AND ((activated_by IS NULL "
            "AND activated_at IS NULL AND superseded_at IS NULL) OR "
            "(activated_by IS NOT NULL AND activated_at IS NOT NULL "
            "AND superseded_at IS NOT NULL AND superseded_at >= activated_at)))",
            name="lifecycle_matrix",
        ),
        UniqueConstraint("knowledge_base_id", "version_no", name="uq_index_kb_version"),
        UniqueConstraint(
            "knowledge_base_id",
            "manifest_sha256",
            "embedding_adapter_id",
            "embedding_model_id",
            "vector_dimension",
            name="uq_index_input_identity",
        ),
        Index(
            "uq_document_index_versions_kb_active",
            "knowledge_base_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("idx_document_index_versions_kb_created", "knowledge_base_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    collection_name: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_adapter_id: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    vector_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    distance: Mapped[str] = mapped_column(String(20), nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    consistency_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    failure_code: Mapped[str | None] = mapped_column(String(80))
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    activated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class DocumentIndexItem(Base):
    __tablename__ = "document_index_items"
    __table_args__ = (
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_hash_format"),
        CheckConstraint(
            "vector_sha256 IS NULL OR vector_sha256 ~ '^[0-9a-f]{64}$'",
            name="vector_hash_format",
        ),
        CheckConstraint(
            "payload_sha256 IS NULL OR payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="payload_hash_format",
        ),
        CheckConstraint("vector_dimension > 0", name="vector_dimension_positive"),
        CheckConstraint(
            "(vector_sha256 IS NULL) = (payload_sha256 IS NULL)", name="materialization_matrix"
        ),
        UniqueConstraint("index_version_id", "chunk_id", name="uq_index_item_chunk"),
        UniqueConstraint("index_version_id", "qdrant_point_id", name="uq_index_item_point"),
        Index("idx_document_index_items_policy", "index_version_id", "policy_document_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False
    )
    index_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_index_versions.id"), nullable=False
    )
    policy_document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("policy_documents.id"), nullable=False
    )
    markdown_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_markdown_versions.id"), nullable=False
    )
    chunk_set_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_chunk_sets.id"), nullable=False
    )
    chunk_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_chunks.id"), nullable=False
    )
    qdrant_point_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    vector_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    payload_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    vector_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RetrievalEvalDataset(Base):
    __tablename__ = "retrieval_eval_datasets"
    __table_args__ = (
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint("tier IN ('smoke','mvp_uat','formal_release')", name="tier_allowed"),
        CheckConstraint(
            "status IN ('draft','submitted','approved','superseded')", name="status_allowed"
        ),
        CheckConstraint("case_count >= 0", name="case_count_nonnegative"),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="manifest_hash_format"),
        CheckConstraint(
            "answer_score_threshold >= 0 AND answer_score_threshold <= 1",
            name="answer_threshold_range",
        ),
        CheckConstraint(
            "(submitted_by IS NULL) = (submitted_at IS NULL) "
            "AND (submitted_by IS NULL) = (submission_reason IS NULL) "
            "AND (approved_by IS NULL) = (approved_at IS NULL) "
            "AND (approved_by IS NULL) = (approval_reason IS NULL)",
            name="decision_metadata_pairs",
        ),
        CheckConstraint(
            "(status = 'draft' AND submitted_by IS NULL AND approved_by IS NULL) OR "
            "(status = 'submitted' AND submitted_by IS NOT NULL AND approved_by IS NULL) OR "
            "(status IN ('approved','superseded') AND submitted_by IS NOT NULL "
            "AND approved_by IS NOT NULL AND submitted_by <> approved_by)",
            name="lifecycle_matrix",
        ),
        UniqueConstraint("knowledge_base_id", "tier", "version_no", name="uq_eval_dataset_version"),
        UniqueConstraint(
            "knowledge_base_id", "tier", "manifest_sha256", name="uq_eval_dataset_manifest"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tier: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    answer_score_threshold: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    submitted_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_reason: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class RetrievalEvalCase(Base):
    __tablename__ = "retrieval_eval_cases"
    __table_args__ = (
        CheckConstraint("case_no > 0", name="case_no_positive"),
        CheckConstraint("label IN ('answerable','no_answer','unauthorized')", name="label_allowed"),
        CheckConstraint("btrim(query_text) <> ''", name="query_nonempty"),
        CheckConstraint("query_sha256 ~ '^[0-9a-f]{64}$'", name="query_hash_format"),
        CheckConstraint(
            "(label = 'answerable' AND cardinality(expected_chunk_ids) > 0 "
            "AND cardinality(forbidden_chunk_ids) = 0) OR "
            "(label = 'no_answer' AND cardinality(expected_chunk_ids) = 0 "
            "AND cardinality(forbidden_chunk_ids) = 0) OR "
            "(label = 'unauthorized' AND cardinality(expected_chunk_ids) = 0 "
            "AND cardinality(forbidden_chunk_ids) > 0)",
            name="label_ground_truth_matrix",
        ),
        UniqueConstraint("dataset_id", "case_no", name="uq_eval_case_number"),
        UniqueConstraint("dataset_id", "query_sha256", name="uq_eval_case_query"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    dataset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("retrieval_eval_datasets.id"), nullable=False
    )
    case_no: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(30), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    baseline_date: Mapped[date] = mapped_column(Date, nullable=False)
    allowed_policy_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    expected_chunk_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    forbidden_chunk_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )


class RetrievalEvalRun(Base):
    __tablename__ = "retrieval_eval_runs"
    __table_args__ = (
        CheckConstraint("tier IN ('smoke','mvp_uat','formal_release')", name="tier_allowed"),
        CheckConstraint("status IN ('running','passed','failed')", name="status_allowed"),
        CheckConstraint("case_count > 0", name="case_count_positive"),
        CheckConstraint("completed_case_count >= 0", name="completed_count_nonnegative"),
        CheckConstraint("completed_case_count <= case_count", name="completed_count_bounded"),
        CheckConstraint("parameters_sha256 ~ '^[0-9a-f]{64}$'", name="parameters_hash_format"),
        CheckConstraint("jsonb_typeof(parameters_json) = 'object'", name="parameters_object"),
        CheckConstraint("jsonb_typeof(metrics_json) = 'object'", name="metrics_object"),
        CheckConstraint(
            "(status = 'running' AND finished_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'passed' AND finished_at IS NOT NULL AND failure_code IS NULL "
            "AND completed_case_count = case_count) OR "
            "(status = 'failed' AND finished_at IS NOT NULL AND failure_code IS NOT NULL)",
            name="lifecycle_matrix",
        ),
        Index("idx_retrieval_eval_runs_index_status", "index_version_id", "tier", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False
    )
    index_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_index_versions.id"), nullable=False
    )
    dataset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("retrieval_eval_datasets.id"), nullable=False
    )
    tier: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    embedding_adapter_id: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    generator_id: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    parameters_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_case_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metrics_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    failure_code: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class RetrievalEvalResult(Base):
    __tablename__ = "retrieval_eval_results"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(ranked_hits_json) = 'array'", name="ranked_hits_array"),
        CheckConstraint(
            "miss_reason IS NULL OR miss_reason IN "
            "('expected_evidence_missing','false_positive','authorization_leak',"
            "'member_drift','dependency_unavailable')",
            name="miss_reason_allowed",
        ),
        CheckConstraint(
            "(passed AND miss_reason IS NULL AND NOT authorization_leak) OR "
            "(NOT passed AND miss_reason IS NOT NULL)",
            name="result_matrix",
        ),
        UniqueConstraint("run_id", "case_id", name="uq_eval_result_case"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("retrieval_eval_runs.id"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("retrieval_eval_cases.id"), nullable=False
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    authorization_leak: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ranked_hits_json: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    miss_reason: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class QaQuery(Base):
    __tablename__ = "qa_queries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('answered','refused','service_degraded')", name="status_allowed"
        ),
        CheckConstraint("btrim(question_text) <> ''", name="question_nonempty"),
        CheckConstraint("question_sha256 ~ '^[0-9a-f]{64}$'", name="question_hash_format"),
        CheckConstraint("retrieved_count >= 0", name="retrieved_count_nonnegative"),
        CheckConstraint("jsonb_typeof(citations_json) = 'array'", name="citations_array"),
        CheckConstraint(
            "(status = 'answered' AND answer_text IS NOT NULL AND btrim(answer_text) <> '' "
            "AND reason_code IS NULL AND jsonb_array_length(citations_json) > 0) OR "
            "(status IN ('refused','service_degraded') AND answer_text IS NULL "
            "AND reason_code IS NOT NULL AND jsonb_array_length(citations_json) = 0)",
            name="outcome_matrix",
        ),
        Index("idx_qa_queries_actor_created", "organization_id", "created_by", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False
    )
    index_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_index_versions.id")
    )
    baseline_date: Mapped[date] = mapped_column(Date, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(String(80))
    citations_json: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    retrieved_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_adapter_id: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class QaFeedback(Base):
    __tablename__ = "qa_feedback"
    __table_args__ = (
        CheckConstraint("rating IN ('helpful','unhelpful')", name="rating_allowed"),
        CheckConstraint(
            "correction_text IS NULL OR btrim(correction_text) <> ''", name="correction_nonempty"
        ),
        UniqueConstraint("qa_query_id", "created_by", name="uq_qa_feedback_actor"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    qa_query_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("qa_queries.id"), nullable=False
    )
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    correction_text: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


__all__ = [
    "INDEX_VERSION_STATUSES",
    "QA_QUERY_STATUSES",
    "RETRIEVAL_EVAL_DATASET_STATUSES",
    "RETRIEVAL_EVAL_RUN_STATUSES",
    "RETRIEVAL_EVAL_TIERS",
    "DocumentIndexItem",
    "DocumentIndexVersion",
    "QaFeedback",
    "QaQuery",
    "RetrievalEvalCase",
    "RetrievalEvalDataset",
    "RetrievalEvalResult",
    "RetrievalEvalRun",
]
