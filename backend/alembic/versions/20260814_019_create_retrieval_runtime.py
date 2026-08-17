"""创建知识索引、检索评测与 RAG 查询事实。

Revision ID: 20260814_019
Revises: 20260814_018
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260814_019"
down_revision: str | None = "20260814_018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATED_TABLES = (
    "document_index_versions",
    "document_index_items",
    "retrieval_eval_datasets",
    "retrieval_eval_cases",
    "retrieval_eval_runs",
    "retrieval_eval_results",
    "qa_queries",
    "qa_feedback",
)


def upgrade() -> None:
    op.create_table(
        "document_index_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("collection_name", sa.String(length=200), nullable=False),
        sa.Column("embedding_adapter_id", sa.String(length=100), nullable=False),
        sa.Column("embedding_model_id", sa.String(length=200), nullable=False),
        sa.Column("vector_dimension", sa.Integer(), nullable=False),
        sa.Column("distance", sa.String(length=20), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("manifest_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "consistency_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("activated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("version_no > 0", name="version_no_positive"),
        sa.CheckConstraint(
            "status IN ('building','ready','active','failed','superseded','archived')",
            name="status_allowed",
        ),
        sa.CheckConstraint("vector_dimension > 0", name="vector_dimension_positive"),
        sa.CheckConstraint(
            "distance IN ('Cosine','Dot','Euclid','Manhattan')", name="distance_allowed"
        ),
        sa.CheckConstraint("member_count >= 0", name="member_count_nonnegative"),
        sa.CheckConstraint("row_version > 0", name="row_version_positive"),
        sa.CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="manifest_hash_format"),
        sa.CheckConstraint("jsonb_typeof(consistency_json) = 'object'", name="consistency_object"),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["public.knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["public.users.id"]),
        sa.ForeignKeyConstraint(["activated_by"], ["public.users.id"]),
        sa.UniqueConstraint("knowledge_base_id", "version_no", name="uq_index_kb_version"),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "manifest_sha256",
            "embedding_adapter_id",
            "embedding_model_id",
            "vector_dimension",
            name="uq_index_input_identity",
        ),
        schema="public",
    )
    op.create_index(
        "uq_document_index_versions_kb_active",
        "document_index_versions",
        ["knowledge_base_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        schema="public",
    )
    op.create_index(
        "idx_document_index_versions_kb_created",
        "document_index_versions",
        ["knowledge_base_id", "created_at"],
        schema="public",
    )

    op.create_table(
        "document_index_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("markdown_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("vector_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("payload_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("vector_dimension", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_hash_format"),
        sa.CheckConstraint(
            "vector_sha256 IS NULL OR vector_sha256 ~ '^[0-9a-f]{64}$'",
            name="vector_hash_format",
        ),
        sa.CheckConstraint(
            "payload_sha256 IS NULL OR payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="payload_hash_format",
        ),
        sa.CheckConstraint("vector_dimension > 0", name="vector_dimension_positive"),
        sa.CheckConstraint(
            "(vector_sha256 IS NULL) = (payload_sha256 IS NULL)", name="materialization_matrix"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["public.knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["index_version_id"], ["public.document_index_versions.id"]),
        sa.ForeignKeyConstraint(["policy_document_id"], ["public.policy_documents.id"]),
        sa.ForeignKeyConstraint(["markdown_version_id"], ["public.document_markdown_versions.id"]),
        sa.ForeignKeyConstraint(["chunk_set_id"], ["public.document_chunk_sets.id"]),
        sa.ForeignKeyConstraint(["chunk_id"], ["public.document_chunks.id"]),
        sa.UniqueConstraint("index_version_id", "chunk_id", name="uq_index_item_chunk"),
        sa.UniqueConstraint("index_version_id", "qdrant_point_id", name="uq_index_item_point"),
        schema="public",
    )
    op.create_index(
        "idx_document_index_items_policy",
        "document_index_items",
        ["index_version_id", "policy_document_id"],
        schema="public",
    )

    op.create_table(
        "retrieval_eval_datasets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tier", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("answer_score_threshold", sa.Numeric(8, 6), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("manifest_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submission_reason", sa.Text(), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_reason", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("version_no > 0", name="version_no_positive"),
        sa.CheckConstraint("tier IN ('smoke','mvp_uat','formal_release')", name="tier_allowed"),
        sa.CheckConstraint(
            "status IN ('draft','submitted','approved','superseded')", name="status_allowed"
        ),
        sa.CheckConstraint("case_count >= 0", name="case_count_nonnegative"),
        sa.CheckConstraint("row_version > 0", name="row_version_positive"),
        sa.CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$'", name="manifest_hash_format"),
        sa.CheckConstraint(
            "answer_score_threshold >= 0 AND answer_score_threshold <= 1",
            name="answer_threshold_range",
        ),
        sa.CheckConstraint(
            "(submitted_by IS NULL) = (submitted_at IS NULL) "
            "AND (submitted_by IS NULL) = (submission_reason IS NULL) "
            "AND (approved_by IS NULL) = (approved_at IS NULL) "
            "AND (approved_by IS NULL) = (approval_reason IS NULL)",
            name="decision_metadata_pairs",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND submitted_by IS NULL AND approved_by IS NULL) OR "
            "(status = 'submitted' AND submitted_by IS NOT NULL AND approved_by IS NULL) OR "
            "(status IN ('approved','superseded') AND submitted_by IS NOT NULL "
            "AND approved_by IS NOT NULL AND submitted_by <> approved_by)",
            name="lifecycle_matrix",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["public.knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["submitted_by"], ["public.users.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["public.users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["public.users.id"]),
        sa.UniqueConstraint(
            "knowledge_base_id", "tier", "version_no", name="uq_eval_dataset_version"
        ),
        sa.UniqueConstraint(
            "knowledge_base_id", "tier", "manifest_sha256", name="uq_eval_dataset_manifest"
        ),
        schema="public",
    )

    op.create_table(
        "retrieval_eval_cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_no", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=30), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("baseline_date", sa.Date(), nullable=False),
        sa.Column(
            "allowed_policy_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "expected_chunk_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "forbidden_chunk_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.CheckConstraint("case_no > 0", name="case_no_positive"),
        sa.CheckConstraint(
            "label IN ('answerable','no_answer','unauthorized')", name="label_allowed"
        ),
        sa.CheckConstraint("btrim(query_text) <> ''", name="query_nonempty"),
        sa.CheckConstraint("query_sha256 ~ '^[0-9a-f]{64}$'", name="query_hash_format"),
        sa.CheckConstraint(
            "(label = 'answerable' AND cardinality(expected_chunk_ids) > 0 "
            "AND cardinality(forbidden_chunk_ids) = 0) OR "
            "(label = 'no_answer' AND cardinality(expected_chunk_ids) = 0 "
            "AND cardinality(forbidden_chunk_ids) = 0) OR "
            "(label = 'unauthorized' AND cardinality(expected_chunk_ids) = 0 "
            "AND cardinality(forbidden_chunk_ids) > 0)",
            name="label_ground_truth_matrix",
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["public.retrieval_eval_datasets.id"]),
        sa.UniqueConstraint("dataset_id", "case_no", name="uq_eval_case_number"),
        sa.UniqueConstraint("dataset_id", "query_sha256", name="uq_eval_case_query"),
        schema="public",
    )

    op.create_table(
        "retrieval_eval_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tier", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("embedding_adapter_id", sa.String(length=100), nullable=False),
        sa.Column("embedding_model_id", sa.String(length=200), nullable=False),
        sa.Column("generator_id", sa.String(length=100), nullable=False),
        sa.Column("parameters_json", postgresql.JSONB(), nullable=False),
        sa.Column("parameters_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("completed_case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metrics_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("tier IN ('smoke','mvp_uat','formal_release')", name="tier_allowed"),
        sa.CheckConstraint("status IN ('running','passed','failed')", name="status_allowed"),
        sa.CheckConstraint("case_count > 0", name="case_count_positive"),
        sa.CheckConstraint("completed_case_count >= 0", name="completed_count_nonnegative"),
        sa.CheckConstraint("completed_case_count <= case_count", name="completed_count_bounded"),
        sa.CheckConstraint("parameters_sha256 ~ '^[0-9a-f]{64}$'", name="parameters_hash_format"),
        sa.CheckConstraint("jsonb_typeof(parameters_json) = 'object'", name="parameters_object"),
        sa.CheckConstraint("jsonb_typeof(metrics_json) = 'object'", name="metrics_object"),
        sa.CheckConstraint(
            "(status = 'running' AND finished_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'passed' AND finished_at IS NOT NULL AND failure_code IS NULL "
            "AND completed_case_count = case_count) OR "
            "(status = 'failed' AND finished_at IS NOT NULL AND failure_code IS NOT NULL)",
            name="lifecycle_matrix",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["public.knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["index_version_id"], ["public.document_index_versions.id"]),
        sa.ForeignKeyConstraint(["dataset_id"], ["public.retrieval_eval_datasets.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["public.users.id"]),
        schema="public",
    )
    op.create_index(
        "idx_retrieval_eval_runs_index_status",
        "retrieval_eval_runs",
        ["index_version_id", "tier", "status"],
        schema="public",
    )

    op.create_table(
        "retrieval_eval_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("authorization_leak", sa.Boolean(), nullable=False),
        sa.Column("ranked_hits_json", postgresql.JSONB(), nullable=False),
        sa.Column("miss_reason", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("jsonb_typeof(ranked_hits_json) = 'array'", name="ranked_hits_array"),
        sa.CheckConstraint(
            "miss_reason IS NULL OR miss_reason IN "
            "('expected_evidence_missing','false_positive','authorization_leak',"
            "'member_drift','dependency_unavailable')",
            name="miss_reason_allowed",
        ),
        sa.CheckConstraint(
            "(passed AND miss_reason IS NULL AND NOT authorization_leak) OR "
            "(NOT passed AND miss_reason IS NOT NULL)",
            name="result_matrix",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["public.retrieval_eval_runs.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["public.retrieval_eval_cases.id"]),
        sa.UniqueConstraint("run_id", "case_id", name="uq_eval_result_case"),
        schema="public",
    )

    op.create_table(
        "qa_queries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("baseline_date", sa.Date(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("question_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("citations_json", postgresql.JSONB(), nullable=False),
        sa.Column("retrieved_count", sa.Integer(), nullable=False),
        sa.Column("embedding_adapter_id", sa.String(length=100), nullable=False),
        sa.Column("embedding_model_id", sa.String(length=200), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('answered','refused','service_degraded')", name="status_allowed"
        ),
        sa.CheckConstraint("btrim(question_text) <> ''", name="question_nonempty"),
        sa.CheckConstraint("question_sha256 ~ '^[0-9a-f]{64}$'", name="question_hash_format"),
        sa.CheckConstraint("retrieved_count >= 0", name="retrieved_count_nonnegative"),
        sa.CheckConstraint("jsonb_typeof(citations_json) = 'array'", name="citations_array"),
        sa.CheckConstraint(
            "(status = 'answered' AND answer_text IS NOT NULL AND btrim(answer_text) <> '' "
            "AND reason_code IS NULL AND jsonb_array_length(citations_json) > 0) OR "
            "(status IN ('refused','service_degraded') AND answer_text IS NULL "
            "AND reason_code IS NOT NULL AND jsonb_array_length(citations_json) = 0)",
            name="outcome_matrix",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["public.knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["index_version_id"], ["public.document_index_versions.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["public.users.id"]),
        schema="public",
    )
    op.create_index(
        "idx_qa_queries_actor_created",
        "qa_queries",
        ["organization_id", "created_by", "created_at"],
        schema="public",
    )

    op.create_table(
        "qa_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("qa_query_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.String(length=20), nullable=False),
        sa.Column("correction_text", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("rating IN ('helpful','unhelpful')", name="rating_allowed"),
        sa.CheckConstraint(
            "correction_text IS NULL OR btrim(correction_text) <> ''", name="correction_nonempty"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["qa_query_id"], ["public.qa_queries.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["public.users.id"]),
        sa.UniqueConstraint("qa_query_id", "created_by", name="uq_qa_feedback_actor"),
        schema="public",
    )

    op.execute(
        sa.text(
            r"""
            CREATE FUNCTION public.enforce_retrieval_runtime_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                parent_status text;
                parent_org uuid;
                parent_kb uuid;
                parent_dataset uuid;
                actual_count bigint;
                minimum_count integer;
            BEGIN
                IF TG_OP = 'TRUNCATE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='retrieval runtime facts cannot be truncated';
                END IF;

                IF TG_TABLE_NAME = 'document_index_versions' THEN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='document index versions are append-only';
                    END IF;
                    SELECT organization_id, status INTO parent_org, parent_status
                      FROM public.knowledge_bases WHERE id=NEW.knowledge_base_id FOR KEY SHARE;
                    IF parent_org IS DISTINCT FROM NEW.organization_id
                       OR parent_status <> 'active' THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='document index knowledge base is invalid';
                    END IF;
                    IF TG_OP = 'UPDATE' THEN
                        IF NEW.row_version <> OLD.row_version + 1 THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='document index row version is invalid';
                        END IF;
                        IF ROW(NEW.id,NEW.organization_id,NEW.knowledge_base_id,NEW.version_no,
                               NEW.collection_name,NEW.embedding_adapter_id,NEW.embedding_model_id,
                               NEW.vector_dimension,NEW.distance,NEW.member_count,
                               NEW.manifest_sha256,NEW.created_by,NEW.created_at,NEW.trace_id)
                           IS DISTINCT FROM
                           ROW(OLD.id,OLD.organization_id,OLD.knowledge_base_id,OLD.version_no,
                               OLD.collection_name,OLD.embedding_adapter_id,OLD.embedding_model_id,
                               OLD.vector_dimension,OLD.distance,OLD.member_count,
                               OLD.manifest_sha256,OLD.created_by,OLD.created_at,OLD.trace_id) THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='document index identity is immutable';
                        END IF;
                        IF NOT ((OLD.status='building' AND NEW.status IN ('ready','failed'))
                             OR (OLD.status='ready'
                                 AND NEW.status IN ('active','failed','archived'))
                             OR (OLD.status='active' AND NEW.status='superseded')
                             OR (OLD.status='superseded' AND NEW.status='archived')) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='document index status transition is invalid';
                        END IF;
                        IF NEW.status IN ('ready','active') THEN
                            SELECT count(*) INTO actual_count
                              FROM public.document_index_items
                             WHERE index_version_id=NEW.id
                               AND vector_sha256 IS NOT NULL AND payload_sha256 IS NOT NULL;
                            IF actual_count <> NEW.member_count THEN
                                RAISE EXCEPTION USING ERRCODE='23514',
                                    MESSAGE='document index membership is incomplete';
                            END IF;
                        END IF;
                        IF NEW.status='active' AND NOT EXISTS (
                            SELECT 1 FROM public.retrieval_eval_runs
                             WHERE index_version_id=NEW.id AND tier='formal_release'
                               AND status='passed'
                        ) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='formal retrieval evaluation is required';
                        END IF;
                    ELSIF NEW.row_version <> 1 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='document index initial row version is invalid';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME = 'document_index_items' THEN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='document index members are append-only';
                    END IF;
                    SELECT organization_id, knowledge_base_id, status
                      INTO parent_org, parent_kb, parent_status
                      FROM public.document_index_versions
                     WHERE id=NEW.index_version_id FOR KEY SHARE;
                    IF parent_status <> 'building'
                       OR parent_org IS DISTINCT FROM NEW.organization_id
                       OR parent_kb IS DISTINCT FROM NEW.knowledge_base_id THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='document index member parent is invalid';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1
                          FROM public.policy_documents p
                          JOIN public.document_chunk_sets s
                            ON s.policy_document_id=p.id
                           AND s.id=NEW.chunk_set_id
                           AND s.markdown_version_id=NEW.markdown_version_id
                           AND s.status='active'
                          JOIN public.document_chunks c
                            ON c.chunk_set_id=s.id AND c.id=NEW.chunk_id
                         WHERE p.id=NEW.policy_document_id
                           AND p.organization_id=NEW.organization_id
                           AND p.knowledge_base_id=NEW.knowledge_base_id
                           AND p.status IN ('business_approved','published')
                           AND p.deleted_at IS NULL
                           AND c.content_sha256=NEW.content_sha256
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='document index member source is invalid';
                    END IF;
                    IF TG_OP = 'UPDATE' AND ROW(
                        NEW.id,NEW.organization_id,NEW.knowledge_base_id,NEW.index_version_id,
                        NEW.policy_document_id,NEW.markdown_version_id,NEW.chunk_set_id,
                        NEW.chunk_id,NEW.qdrant_point_id,NEW.content_sha256,
                        NEW.vector_dimension,NEW.created_at
                    ) IS DISTINCT FROM ROW(
                        OLD.id,OLD.organization_id,OLD.knowledge_base_id,OLD.index_version_id,
                        OLD.policy_document_id,OLD.markdown_version_id,OLD.chunk_set_id,
                        OLD.chunk_id,OLD.qdrant_point_id,OLD.content_sha256,
                        OLD.vector_dimension,OLD.created_at
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='document index member identity is immutable';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME = 'retrieval_eval_datasets' THEN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='retrieval evaluation datasets are append-only';
                    END IF;
                    SELECT organization_id, status INTO parent_org, parent_status
                      FROM public.knowledge_bases WHERE id=NEW.knowledge_base_id FOR KEY SHARE;
                    IF parent_org IS DISTINCT FROM NEW.organization_id
                       OR parent_status <> 'active' THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='evaluation knowledge base is invalid';
                    END IF;
                    IF TG_OP = 'UPDATE' THEN
                        IF NEW.row_version <> OLD.row_version + 1 THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='evaluation dataset row version is invalid';
                        END IF;
                        IF ROW(NEW.id,NEW.organization_id,NEW.knowledge_base_id,NEW.version_no,
                               NEW.name,NEW.tier,NEW.answer_score_threshold,NEW.case_count,
                               NEW.manifest_sha256,NEW.created_by,NEW.created_at,NEW.trace_id)
                           IS DISTINCT FROM
                           ROW(OLD.id,OLD.organization_id,OLD.knowledge_base_id,OLD.version_no,
                               OLD.name,OLD.tier,OLD.answer_score_threshold,OLD.case_count,
                               OLD.manifest_sha256,OLD.created_by,OLD.created_at,OLD.trace_id) THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='evaluation dataset identity is immutable';
                        END IF;
                        IF NOT ((OLD.status='draft' AND NEW.status='submitted')
                             OR (OLD.status='submitted' AND NEW.status='approved')
                             OR (OLD.status='approved' AND NEW.status='superseded')) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='evaluation dataset transition is invalid';
                        END IF;
                        IF NEW.status IN ('submitted','approved') THEN
                            SELECT count(*) INTO actual_count FROM public.retrieval_eval_cases
                             WHERE dataset_id=NEW.id;
                            minimum_count := CASE NEW.tier
                                WHEN 'smoke' THEN 5 WHEN 'mvp_uat' THEN 50 ELSE 100 END;
                            IF actual_count <> NEW.case_count OR actual_count < minimum_count THEN
                                RAISE EXCEPTION USING ERRCODE='23514',
                                    MESSAGE='evaluation dataset case gate failed';
                            END IF;
                        END IF;
                    ELSIF NEW.row_version <> 1 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='evaluation dataset initial row version is invalid';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME = 'retrieval_eval_cases' THEN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='retrieval evaluation cases are append-only';
                    END IF;
                    SELECT status INTO parent_status FROM public.retrieval_eval_datasets
                     WHERE id=NEW.dataset_id FOR KEY SHARE;
                    IF parent_status <> 'draft' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='approved evaluation cases are immutable';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME = 'retrieval_eval_runs' THEN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='retrieval evaluation runs are append-only';
                    END IF;
                    IF TG_OP = 'INSERT' THEN
                        IF NOT EXISTS (
                            SELECT 1 FROM public.retrieval_eval_datasets d
                            JOIN public.document_index_versions i
                              ON i.id=NEW.index_version_id
                             AND i.organization_id=d.organization_id
                             AND i.knowledge_base_id=d.knowledge_base_id
                             AND i.status IN ('ready','active')
                             AND i.embedding_adapter_id=NEW.embedding_adapter_id
                             AND i.embedding_model_id=NEW.embedding_model_id
                           WHERE d.id=NEW.dataset_id AND d.status='approved'
                             AND d.organization_id=NEW.organization_id
                             AND d.knowledge_base_id=NEW.knowledge_base_id
                             AND d.tier=NEW.tier AND d.case_count=NEW.case_count
                        ) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='evaluation run inputs are invalid';
                        END IF;
                    ELSE
                        IF ROW(NEW.id,NEW.organization_id,NEW.knowledge_base_id,
                               NEW.index_version_id,NEW.dataset_id,NEW.tier,
                               NEW.embedding_adapter_id,NEW.embedding_model_id,NEW.generator_id,
                               NEW.parameters_json,NEW.parameters_sha256,NEW.case_count,
                               NEW.created_by,NEW.started_at,NEW.trace_id)
                           IS DISTINCT FROM
                           ROW(OLD.id,OLD.organization_id,OLD.knowledge_base_id,
                               OLD.index_version_id,OLD.dataset_id,OLD.tier,
                               OLD.embedding_adapter_id,OLD.embedding_model_id,OLD.generator_id,
                               OLD.parameters_json,OLD.parameters_sha256,OLD.case_count,
                               OLD.created_by,OLD.started_at,OLD.trace_id)
                           OR OLD.status <> 'running' OR NEW.status NOT IN ('passed','failed') THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='evaluation run update is invalid';
                        END IF;
                        SELECT count(*) INTO actual_count FROM public.retrieval_eval_results
                         WHERE run_id=NEW.id;
                        IF NEW.completed_case_count <> actual_count THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='evaluation run result count mismatch';
                        END IF;
                        IF NEW.status='passed' AND EXISTS (
                            SELECT 1 FROM public.retrieval_eval_results
                             WHERE run_id=NEW.id AND (NOT passed OR authorization_leak)
                        ) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='evaluation run contains failed cases';
                        END IF;
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME = 'retrieval_eval_results' THEN
                    IF TG_OP <> 'INSERT' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='retrieval evaluation results are append-only';
                    END IF;
                    SELECT dataset_id, status INTO parent_dataset, parent_status
                      FROM public.retrieval_eval_runs WHERE id=NEW.run_id FOR KEY SHARE;
                    IF parent_status <> 'running' OR NOT EXISTS (
                        SELECT 1 FROM public.retrieval_eval_cases
                         WHERE id=NEW.case_id AND dataset_id=parent_dataset
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='evaluation result parent is invalid';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME = 'qa_queries' THEN
                    IF TG_OP <> 'INSERT' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='qa query history is append-only';
                    END IF;
                    SELECT organization_id, status INTO parent_org, parent_status
                      FROM public.knowledge_bases WHERE id=NEW.knowledge_base_id FOR KEY SHARE;
                    IF parent_org IS DISTINCT FROM NEW.organization_id
                       OR parent_status <> 'active' THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='qa knowledge base is invalid';
                    END IF;
                    IF NEW.index_version_id IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM public.document_index_versions
                         WHERE id=NEW.index_version_id AND organization_id=NEW.organization_id
                           AND knowledge_base_id=NEW.knowledge_base_id AND status='active'
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='qa active index is invalid';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME = 'qa_feedback' THEN
                    IF TG_OP <> 'INSERT' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='qa feedback is append-only';
                    END IF;
                    SELECT organization_id INTO parent_org FROM public.qa_queries
                     WHERE id=NEW.qa_query_id FOR KEY SHARE;
                    IF parent_org IS DISTINCT FROM NEW.organization_id THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='qa feedback parent is invalid';
                    END IF;
                    RETURN NEW;
                END IF;

                RAISE EXCEPTION USING ERRCODE='55000', MESSAGE='unsupported retrieval fact table';
            END;
            $$;
            REVOKE ALL ON FUNCTION public.enforce_retrieval_runtime_v1() FROM PUBLIC;
            """
        )
    )
    for table_name in _CREATED_TABLES:
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table_name}_state_v1
                BEFORE INSERT OR UPDATE OR DELETE ON public.{table_name}
                FOR EACH ROW EXECUTE FUNCTION public.enforce_retrieval_runtime_v1();
                CREATE TRIGGER trg_{table_name}_no_truncate_v1
                BEFORE TRUNCATE ON public.{table_name}
                FOR EACH STATEMENT EXECUTE FUNCTION public.enforce_retrieval_runtime_v1();
                """
            )
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM public.document_index_versions LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.retrieval_eval_datasets LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.qa_queries LIMIT 1)
                   OR EXISTS (
                       SELECT 1 FROM public.async_jobs
                        WHERE job_type IN ('knowledge_index_build','retrieval_eval') LIMIT 1
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='refusing to drop non-empty retrieval runtime';
                END IF;
            END;
            $$;
            """
        )
    )
    for table_name in reversed(_CREATED_TABLES):
        op.execute(sa.text(f"DROP TRIGGER trg_{table_name}_no_truncate_v1 ON public.{table_name}"))
        op.execute(sa.text(f"DROP TRIGGER trg_{table_name}_state_v1 ON public.{table_name}"))
    op.drop_table("qa_feedback", schema="public")
    op.drop_table("qa_queries", schema="public")
    op.drop_table("retrieval_eval_results", schema="public")
    op.drop_table("retrieval_eval_runs", schema="public")
    op.drop_table("retrieval_eval_cases", schema="public")
    op.drop_table("retrieval_eval_datasets", schema="public")
    op.drop_table("document_index_items", schema="public")
    op.drop_table("document_index_versions", schema="public")
    op.execute(sa.text("DROP FUNCTION public.enforce_retrieval_runtime_v1()"))
