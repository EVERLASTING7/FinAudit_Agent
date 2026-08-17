"""创建审核执行、风险、正式报告与 AI 调用审计事实。

Revision ID: 20260814_020
Revises: 20260814_019
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260814_020"
down_revision: str | None = "20260814_019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATED_TABLES = (
    "audit_task_items",
    "audit_task_executions",
    "audit_task_snapshots",
    "rule_executions",
    "audit_risks",
    "risk_citations",
    "audit_reports",
    "ai_call_logs",
)


def _uuid(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def _replace_invoice_state_guard(*, include_red_invoice: bool) -> None:
    red_invoice_guard = (
        "\n                       OR NEW.is_red_invoice IS DISTINCT FROM OLD.is_red_invoice"
        if include_red_invoice
        else ""
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION public.enforce_invoices_state_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='invoice facts cannot be deleted';
                END IF;
                IF TG_OP = 'INSERT' THEN
                    IF NEW.row_version <> 1 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='invoice must start at row version one';
                    END IF;
                    RETURN NEW;
                END IF;

                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at
                   OR NEW.created_by IS DISTINCT FROM OLD.created_by
                   OR NEW.row_version <> OLD.row_version + 1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='invoice identity or row version is invalid';
                END IF;

                IF OLD.confirmation_status = 'unconfirmed' THEN
                    IF NOT (
                        (NEW.confirmation_status = 'unconfirmed' AND NEW.status = 'draft')
                        OR (NEW.confirmation_status = 'confirmed' AND NEW.status = 'confirmed')
                        OR (NEW.confirmation_status = 'rejected' AND NEW.status = 'draft')
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='invoice state transition is invalid';
                    END IF;
                ELSIF OLD.confirmation_status = 'rejected' THEN
                    IF NOT (
                        (NEW.confirmation_status = 'rejected' AND NEW.status = 'draft')
                        OR (NEW.confirmation_status = 'unconfirmed' AND NEW.status = 'draft')
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='invoice state transition is invalid';
                    END IF;
                ELSE
                    IF NEW.confirmation_status <> 'confirmed'
                       OR NOT (
                           (OLD.status = 'confirmed'
                            AND NEW.status IN ('confirmed','voided','archived'))
                           OR (OLD.status = 'voided'
                               AND NEW.status IN ('voided','archived'))
                           OR (OLD.status = 'archived' AND NEW.status = 'archived')
                       ) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='invoice confirmed state is immutable';
                    END IF;
                    IF NEW.invoice_code IS DISTINCT FROM OLD.invoice_code
                       OR NEW.invoice_number IS DISTINCT FROM OLD.invoice_number
                       OR NEW.invoice_type IS DISTINCT FROM OLD.invoice_type{red_invoice_guard}
                       OR NEW.invoice_date IS DISTINCT FROM OLD.invoice_date
                       OR NEW.buyer_name IS DISTINCT FROM OLD.buyer_name
                       OR NEW.buyer_tax_no IS DISTINCT FROM OLD.buyer_tax_no
                       OR NEW.seller_name IS DISTINCT FROM OLD.seller_name
                       OR NEW.seller_tax_no IS DISTINCT FROM OLD.seller_tax_no
                       OR (
                           NEW.supplier_id IS DISTINCT FROM OLD.supplier_id
                           AND NOT (
                               OLD.supplier_id IS NULL
                               AND NEW.supplier_id IS NOT NULL
                           )
                       )
                       OR NEW.amount_excluding_tax IS DISTINCT FROM OLD.amount_excluding_tax
                       OR NEW.tax_amount IS DISTINCT FROM OLD.tax_amount
                       OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
                       OR NEW.currency IS DISTINCT FROM OLD.currency
                       OR NEW.field_evidence_json IS DISTINCT FROM OLD.field_evidence_json
                       OR NEW.critical_fact_hash IS DISTINCT FROM OLD.critical_fact_hash
                       OR NEW.confirmed_by IS DISTINCT FROM OLD.confirmed_by
                       OR NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='confirmed invoice facts are immutable';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM public.audit_rules LIMIT 1) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='refusing to upgrade non-empty legacy audit rules';
                END IF;
            END; $$;
            """
        )
    )
    op.add_column(
        "audit_rules",
        sa.Column("application_release", sa.String(length=100), nullable=False),
        schema="public",
    )
    op.add_column(
        "audit_rules",
        sa.Column("catalog_manifest_sha256", sa.CHAR(length=64), nullable=False),
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_audit_rules_application_release_nonempty"),
        "audit_rules",
        "btrim(application_release) <> ''",
        schema="public",
    )
    op.add_column(
        "invoices",
        sa.Column("is_red_invoice", sa.Boolean(), nullable=True),
        schema="public",
    )
    _replace_invoice_state_guard(include_red_invoice=True)
    op.create_check_constraint(
        op.f("ck_audit_rules_catalog_manifest_hash_format"),
        "audit_rules",
        "catalog_manifest_sha256 ~ '^[0-9a-f]{64}$'",
        schema="public",
    )

    op.create_table(
        "audit_task_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        _uuid("organization_id"),
        _uuid("audit_task_id"),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        _uuid("contract_id", nullable=True),
        _uuid("invoice_id", nullable=True),
        _uuid("created_by"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("item_type IN ('contract','invoice')", name="item_type_allowed"),
        sa.CheckConstraint(
            "(item_type='contract' AND contract_id IS NOT NULL AND invoice_id IS NULL) OR "
            "(item_type='invoice' AND invoice_id IS NOT NULL AND contract_id IS NULL)",
            name="item_reference_matrix",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["audit_task_id"], ["public.audit_tasks.id"]),
        sa.ForeignKeyConstraint(["contract_id"], ["public.contracts.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["public.invoices.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["public.users.id"]),
        sa.UniqueConstraint("audit_task_id", "contract_id", name="uq_audit_task_contract"),
        sa.UniqueConstraint("audit_task_id", "invoice_id", name="uq_audit_task_invoice"),
        schema="public",
    )
    op.create_index(
        "uq_audit_task_single_contract",
        "audit_task_items",
        ["audit_task_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("contract_id IS NOT NULL"),
    )

    op.create_table(
        "audit_task_executions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        _uuid("organization_id"),
        _uuid("audit_task_id"),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("baseline_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("snapshot_sha256", sa.CHAR(length=64), nullable=True),
        _uuid("job_id", nullable=True),
        _uuid("finance_reviewer_id", nullable=True),
        sa.Column("finance_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        _uuid("audit_reviewer_id", nullable=True),
        sa.Column("audit_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("return_reason", sa.Text(), nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        _uuid("created_by"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outdated_at", sa.DateTime(timezone=True), nullable=True),
        _uuid("trace_id"),
        sa.CheckConstraint("version_no>0", name="version_no_positive"),
        sa.CheckConstraint(
            "status IN ('draft','validating','queued','running','pending_finance_review',"
            "'pending_audit_review','returned_for_correction','completed','failed','cancelled',"
            "'outdated')",
            name="status_allowed",
        ),
        sa.CheckConstraint("row_version>0", name="row_version_positive"),
        sa.CheckConstraint(
            "snapshot_sha256 IS NULL OR snapshot_sha256 ~ '^[0-9a-f]{64}$'",
            name="snapshot_hash_format",
        ),
        sa.CheckConstraint(
            "(finance_reviewer_id IS NULL)=(finance_reviewed_at IS NULL)",
            name="finance_review_pair",
        ),
        sa.CheckConstraint(
            "(audit_reviewer_id IS NULL)=(audit_reviewed_at IS NULL)",
            name="audit_review_pair",
        ),
        sa.CheckConstraint(
            "(status='failed' AND failure_code IS NOT NULL AND finished_at IS NOT NULL) OR "
            "(status='cancelled' AND cancel_reason IS NOT NULL AND finished_at IS NOT NULL) OR "
            "(status='returned_for_correction' AND return_reason IS NOT NULL "
            "AND finished_at IS NOT NULL) OR "
            "(status='completed' AND finished_at IS NOT NULL) OR "
            "(status='outdated' AND outdated_at IS NOT NULL AND finished_at IS NOT NULL) OR "
            "(status NOT IN "
            "('failed','cancelled','returned_for_correction','completed','outdated') "
            "AND finished_at IS NULL)",
            name="terminal_metadata_matrix",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["audit_task_id"], ["public.audit_tasks.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["public.async_jobs.id"]),
        sa.ForeignKeyConstraint(["finance_reviewer_id"], ["public.users.id"]),
        sa.ForeignKeyConstraint(["audit_reviewer_id"], ["public.users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["public.users.id"]),
        sa.UniqueConstraint("audit_task_id", "version_no", name="uq_audit_execution_version"),
        sa.UniqueConstraint("job_id", name="uq_audit_execution_job"),
        schema="public",
    )
    op.create_index(
        "idx_audit_executions_task_created",
        "audit_task_executions",
        ["audit_task_id", "created_at"],
        schema="public",
    )

    op.create_foreign_key(
        "fk_audit_tasks_current_execution_id_audit_task_executions",
        "audit_tasks",
        "audit_task_executions",
        ["current_execution_id"],
        ["id"],
        source_schema="public",
        referent_schema="public",
    )
    op.create_foreign_key(
        "fk_user_corrections_related_execution_id_audit_task_executions",
        "user_corrections",
        "audit_task_executions",
        ["related_execution_id"],
        ["id"],
        source_schema="public",
        referent_schema="public",
    )
    op.drop_constraint(
        op.f("ck_user_corrections_correction_type_allowed"),
        "user_corrections",
        schema="public",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_corrections_correction_type_allowed"),
        "user_corrections",
        "correction_type IN ('contract_field','supplementary_agreement_changes',"
        "'invoice_field','contract_invoice','supplier_field','audit_risk')",
        schema="public",
    )

    op.create_table(
        "audit_task_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        _uuid("organization_id"),
        _uuid("audit_task_id"),
        _uuid("execution_id"),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("baseline_date", sa.Date(), nullable=False),
        sa.Column("facts_json", postgresql.JSONB(), nullable=False),
        sa.Column("facts_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "rule_version_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        _uuid("index_version_id", nullable=True),
        sa.Column("application_release", sa.String(length=100), nullable=False),
        _uuid("created_by"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        _uuid("trace_id"),
        sa.CheckConstraint("schema_version>0", name="schema_version_positive"),
        sa.CheckConstraint("facts_sha256 ~ '^[0-9a-f]{64}$'", name="facts_hash_format"),
        sa.CheckConstraint("jsonb_typeof(facts_json)='object'", name="facts_object"),
        sa.CheckConstraint("cardinality(rule_version_ids)=15", name="fifteen_rule_versions"),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["audit_task_id"], ["public.audit_tasks.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["public.audit_task_executions.id"]),
        sa.ForeignKeyConstraint(["index_version_id"], ["public.document_index_versions.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["public.users.id"]),
        sa.UniqueConstraint("execution_id", name="uq_audit_snapshot_execution"),
        schema="public",
    )

    op.create_table(
        "rule_executions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        _uuid("organization_id"),
        _uuid("audit_task_id"),
        _uuid("execution_id"),
        _uuid("snapshot_id"),
        _uuid("audit_rule_id"),
        sa.Column("rule_code", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("input_json", postgresql.JSONB(), nullable=False),
        sa.Column("actual_value_json", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("expected_value_json", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("applicability_reason", sa.String(length=100), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "included_item_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "excluded_item_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('passed','failed','not_applicable','error')", name="status_allowed"
        ),
        sa.CheckConstraint("jsonb_typeof(input_json)='object'", name="input_object"),
        sa.CheckConstraint(
            "actual_value_json IS NULL OR jsonb_typeof(actual_value_json)='object'",
            name="actual_value_object",
        ),
        sa.CheckConstraint(
            "expected_value_json IS NULL OR jsonb_typeof(expected_value_json)='object'",
            name="expected_value_object",
        ),
        sa.CheckConstraint(
            "(status='error' AND error_code IS NOT NULL) OR "
            "(status<>'error' AND error_code IS NULL)",
            name="error_matrix",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["audit_task_id"], ["public.audit_tasks.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["public.audit_task_executions.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["public.audit_task_snapshots.id"]),
        sa.ForeignKeyConstraint(["audit_rule_id"], ["public.audit_rules.id"]),
        sa.UniqueConstraint("execution_id", "audit_rule_id", name="uq_rule_execution_rule"),
        schema="public",
    )
    op.create_index(
        "idx_rule_executions_execution",
        "rule_executions",
        ["execution_id", "rule_code"],
        schema="public",
    )

    op.create_table(
        "audit_risks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        _uuid("organization_id"),
        _uuid("audit_task_id"),
        _uuid("execution_id"),
        _uuid("snapshot_id"),
        _uuid("rule_execution_id"),
        sa.Column("rule_code", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("original_level", sa.String(length=20), nullable=False),
        sa.Column("effective_level", sa.String(length=20), nullable=False),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("actual_value", sa.Text(), nullable=True),
        sa.Column("expected_value", sa.Text(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        _uuid("reviewed_by", nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        _uuid("trace_id"),
        sa.CheckConstraint(
            "original_level IN ('none','notice','low','medium','high')",
            name="original_level_allowed",
        ),
        sa.CheckConstraint(
            "effective_level IN ('none','notice','low','medium','high')",
            name="effective_level_allowed",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending','confirmed','dismissed','adjusted','returned')",
            name="review_status_allowed",
        ),
        sa.CheckConstraint("row_version>0", name="row_version_positive"),
        sa.CheckConstraint(
            "(review_status='pending' AND reviewed_by IS NULL AND reviewed_at IS NULL "
            "AND review_reason IS NULL) OR "
            "(review_status<>'pending' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND review_reason IS NOT NULL AND btrim(review_reason)<>'')",
            name="review_metadata_matrix",
        ),
        sa.CheckConstraint(
            "review_status<>'adjusted' OR effective_level<>original_level",
            name="adjusted_level_changes",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["audit_task_id"], ["public.audit_tasks.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["public.audit_task_executions.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["public.audit_task_snapshots.id"]),
        sa.ForeignKeyConstraint(["rule_execution_id"], ["public.rule_executions.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["public.users.id"]),
        sa.UniqueConstraint("rule_execution_id", name="uq_audit_risk_rule_execution"),
        schema="public",
    )
    op.create_index(
        "idx_audit_risks_execution_review",
        "audit_risks",
        ["execution_id", "review_status"],
        schema="public",
    )

    op.create_table(
        "risk_citations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        _uuid("organization_id"),
        _uuid("audit_task_id"),
        _uuid("execution_id"),
        _uuid("risk_id"),
        _uuid("policy_document_id"),
        _uuid("markdown_version_id"),
        _uuid("chunk_id"),
        _uuid("index_version_id"),
        sa.Column(
            "block_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("start_page_no", sa.Integer(), nullable=False),
        sa.Column("end_page_no", sa.Integer(), nullable=False),
        sa.Column(
            "title_path",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("start_page_no>0", name="start_page_positive"),
        sa.CheckConstraint("end_page_no>=start_page_no", name="page_range_valid"),
        sa.CheckConstraint("btrim(quote)<>''", name="quote_nonempty"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_hash_format"),
        sa.CheckConstraint("cardinality(block_ids)>0", name="block_ids_nonempty"),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["audit_task_id"], ["public.audit_tasks.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["public.audit_task_executions.id"]),
        sa.ForeignKeyConstraint(["risk_id"], ["public.audit_risks.id"]),
        sa.ForeignKeyConstraint(["policy_document_id"], ["public.policy_documents.id"]),
        sa.ForeignKeyConstraint(["markdown_version_id"], ["public.document_markdown_versions.id"]),
        sa.ForeignKeyConstraint(["chunk_id"], ["public.document_chunks.id"]),
        sa.ForeignKeyConstraint(["index_version_id"], ["public.document_index_versions.id"]),
        sa.UniqueConstraint("risk_id", "chunk_id", name="uq_risk_citation_chunk"),
        schema="public",
    )

    op.create_table(
        "audit_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        _uuid("organization_id"),
        _uuid("audit_task_id"),
        _uuid("execution_id"),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payload_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("generator_version", sa.String(length=100), nullable=False),
        sa.Column("pdf_bucket", sa.String(length=100), nullable=True),
        sa.Column("pdf_object_key", sa.String(length=500), nullable=True),
        sa.Column("pdf_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("pdf_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "pdf_mime_type",
            sa.String(length=100),
            nullable=False,
            server_default="application/pdf",
        ),
        sa.Column("xlsx_bucket", sa.String(length=100), nullable=True),
        sa.Column("xlsx_object_key", sa.String(length=500), nullable=True),
        sa.Column("xlsx_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("xlsx_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "xlsx_mime_type",
            sa.String(length=100),
            nullable=False,
            server_default="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        _uuid("job_id", nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        _uuid("created_by"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outdated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        _uuid("trace_id"),
        sa.CheckConstraint("report_version>0", name="report_version_positive"),
        sa.CheckConstraint(
            "status IN ('queued','generating','ready','failed','outdated','archived')",
            name="status_allowed",
        ),
        sa.CheckConstraint("payload_sha256 ~ '^[0-9a-f]{64}$'", name="payload_hash_format"),
        sa.CheckConstraint("row_version>0", name="row_version_positive"),
        sa.CheckConstraint(
            "(status IN ('ready','outdated','archived') AND pdf_bucket IS NOT NULL "
            "AND pdf_object_key IS NOT NULL AND pdf_sha256 IS NOT NULL AND pdf_size_bytes>0 "
            "AND xlsx_bucket IS NOT NULL AND xlsx_object_key IS NOT NULL "
            "AND xlsx_sha256 IS NOT NULL AND xlsx_size_bytes>0 AND generated_at IS NOT NULL) OR "
            "(status IN ('queued','generating','failed') AND pdf_bucket IS NULL "
            "AND pdf_object_key IS NULL AND pdf_sha256 IS NULL AND pdf_size_bytes IS NULL "
            "AND xlsx_bucket IS NULL AND xlsx_object_key IS NULL AND xlsx_sha256 IS NULL "
            "AND xlsx_size_bytes IS NULL AND generated_at IS NULL)",
            name="artifact_matrix",
        ),
        sa.CheckConstraint(
            "(status='failed' AND failure_code IS NOT NULL) OR "
            "(status<>'failed' AND failure_code IS NULL)",
            name="failure_matrix",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["audit_task_id"], ["public.audit_tasks.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["public.audit_task_executions.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["public.async_jobs.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["public.users.id"]),
        sa.UniqueConstraint("execution_id", "report_version", name="uq_audit_report_version"),
        sa.UniqueConstraint("job_id", name="uq_audit_report_job"),
        schema="public",
    )
    op.create_index(
        "idx_audit_reports_execution_created",
        "audit_reports",
        ["execution_id", "created_at"],
        schema="public",
    )

    op.create_table(
        "ai_call_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        _uuid("organization_id"),
        _uuid("business_operation_id"),
        _uuid("job_id", nullable=True),
        _uuid("request_id", nullable=True),
        sa.Column("resource_type", sa.String(length=60), nullable=True),
        _uuid("resource_id", nullable=True),
        _uuid("trace_id"),
        sa.Column("call_type", sa.String(length=50), nullable=False),
        sa.Column("logical_generation_no", sa.Integer(), nullable=False),
        sa.Column("provider_attempt_no", sa.Integer(), nullable=False),
        sa.Column("adapter_id", sa.String(length=100), nullable=False),
        sa.Column("endpoint_id", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=True),
        sa.Column("prompt_id", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=100), nullable=True),
        sa.Column("prompt_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("schema_version", sa.String(length=100), nullable=True),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("policy_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("pricing_version", sa.String(length=80), nullable=False),
        sa.Column("input_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("output_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("reserved_input_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_output_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_cost_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("vector_count", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_fallback", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("breaker_state", sa.String(length=30), nullable=True),
        sa.Column("citation_validation_status", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error_category", sa.String(length=80), nullable=True),
        sa.Column("safe_error_code", sa.String(length=80), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("event_version=1", name="event_version_one"),
        sa.CheckConstraint("event_sequence IN (1,2)", name="event_sequence_allowed"),
        sa.CheckConstraint("logical_generation_no>0", name="generation_positive"),
        sa.CheckConstraint("provider_attempt_no>0", name="provider_attempt_positive"),
        sa.CheckConstraint("attempt_count>0", name="attempt_count_positive"),
        sa.CheckConstraint(
            "reserved_input_tokens>=0 AND reserved_output_tokens>=0 AND reserved_cost_micro_usd>=0",
            name="reservation_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('pending','succeeded','failed','degraded','rejected','outcome_unknown')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "policy_hash ~ '^[0-9a-f]{64}$' AND input_hash ~ '^[0-9a-f]{64}$' "
            "AND (prompt_hash IS NULL OR prompt_hash ~ '^[0-9a-f]{64}$') "
            "AND (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$')",
            name="hashes_lower_hex",
        ),
        sa.CheckConstraint(
            "(status='pending' AND event_sequence=1 AND completed_at IS NULL) OR "
            "(status<>'pending' AND event_sequence=2 AND completed_at IS NOT NULL)",
            name="lifecycle_matrix",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["public.organizations.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["public.async_jobs.id"]),
        schema="public",
    )
    op.create_index(
        "idx_ai_call_logs_operation",
        "ai_call_logs",
        ["business_operation_id", "provider_attempt_no"],
        schema="public",
    )
    op.create_index(
        "idx_ai_call_logs_status_started",
        "ai_call_logs",
        ["status", "started_at"],
        schema="public",
    )

    _create_runtime_function_and_triggers()


def _create_runtime_function_and_triggers() -> None:
    op.execute(
        sa.text(
            r"""
            CREATE FUNCTION public.enforce_audit_report_runtime_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,pg_temp
            AS $$
            DECLARE
                parent_org uuid;
                parent_task uuid;
                parent_execution uuid;
                parent_snapshot uuid;
                parent_status text;
                parent_finance uuid;
                rule_code_value text;
                rule_level text;
                rule_count integer;
                invoice_count integer;
            BEGIN
                IF TG_OP='TRUNCATE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='audit and report runtime facts cannot be truncated';
                END IF;

                IF TG_TABLE_NAME='audit_tasks' THEN
                    IF TG_OP<>'UPDATE' THEN RETURN NEW; END IF;
                    IF NEW.row_version<>OLD.row_version+1 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='audit task row version invalid';
                    END IF;
                    IF NEW.current_execution_id IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM public.audit_task_executions e
                         WHERE e.id=NEW.current_execution_id
                           AND e.audit_task_id=NEW.id AND e.organization_id=NEW.organization_id
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='audit task current execution invalid';
                    END IF;
                    IF NEW.status='completed' AND NOT EXISTS (
                        SELECT 1 FROM public.audit_task_executions e
                         WHERE e.id=NEW.current_execution_id AND e.status='completed'
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='audit task completion requires completed execution';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME='audit_task_items' THEN
                    IF TG_OP<>'INSERT' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='audit task items are immutable';
                    END IF;
                    SELECT organization_id INTO parent_org FROM public.audit_tasks
                     WHERE id=NEW.audit_task_id FOR KEY SHARE;
                    IF parent_org IS DISTINCT FROM NEW.organization_id OR EXISTS (
                        SELECT 1 FROM public.audit_tasks
                         WHERE id=NEW.audit_task_id AND current_execution_id IS NOT NULL
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='audit task item parent invalid';
                    END IF;
                    IF NEW.contract_id IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM public.contracts
                         WHERE id=NEW.contract_id AND organization_id=NEW.organization_id
                           AND deleted_at IS NULL
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='audit contract item invalid';
                    END IF;
                    IF NEW.invoice_id IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM public.invoices
                         WHERE id=NEW.invoice_id AND organization_id=NEW.organization_id
                           AND deleted_at IS NULL
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='audit invoice item invalid';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME='audit_task_executions' THEN
                    SELECT organization_id INTO parent_org FROM public.audit_tasks
                     WHERE id=COALESCE(NEW.audit_task_id,OLD.audit_task_id) FOR UPDATE;
                    IF parent_org IS DISTINCT FROM
                       COALESCE(NEW.organization_id,OLD.organization_id) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='audit execution parent invalid';
                    END IF;
                    IF TG_OP='DELETE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='audit executions are immutable';
                    ELSIF TG_OP='INSERT' THEN
                        IF NEW.status<>'draft' OR NEW.row_version<>1 THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='audit execution initial state invalid';
                        END IF;
                    ELSE
                        IF ROW(NEW.id,NEW.organization_id,NEW.audit_task_id,NEW.version_no,
                               NEW.baseline_date,NEW.created_by,NEW.created_at,NEW.trace_id)
                           IS DISTINCT FROM
                           ROW(OLD.id,OLD.organization_id,OLD.audit_task_id,OLD.version_no,
                               OLD.baseline_date,OLD.created_by,OLD.created_at,OLD.trace_id)
                           OR NEW.row_version<>OLD.row_version+1 THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='audit execution identity is immutable';
                        END IF;
                        IF NOT ((OLD.status='draft' AND NEW.status IN ('validating','cancelled'))
                             OR (OLD.status='validating' AND NEW.status IN
                                 ('queued','failed','cancelled','outdated'))
                             OR (OLD.status='queued' AND NEW.status IN
                                 ('running','failed','cancelled','outdated'))
                             OR (OLD.status='running' AND NEW.status IN
                                 ('pending_finance_review','failed','cancelled','outdated'))
                             OR (OLD.status='pending_finance_review' AND NEW.status IN
                                 ('completed','pending_audit_review','returned_for_correction',
                                  'cancelled','outdated'))
                             OR (OLD.status='pending_audit_review' AND NEW.status IN
                                 ('completed','returned_for_correction','cancelled','outdated'))
                             OR (OLD.status='failed' AND NEW.status IN ('queued','outdated'))
                             OR (OLD.status='completed' AND NEW.status='outdated')) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='audit execution status transition invalid';
                        END IF;
                        IF NEW.status='queued'
                           AND (NEW.snapshot_sha256 IS NULL OR NEW.job_id IS NULL) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='queued audit execution requires snapshot and job';
                        END IF;
                        IF NEW.status='pending_finance_review' THEN
                            SELECT count(*) INTO rule_count FROM public.rule_executions
                             WHERE execution_id=NEW.id AND status<>'error';
                            IF rule_count<>15 OR EXISTS (
                                SELECT 1 FROM public.rule_executions
                                 WHERE execution_id=NEW.id AND status='error'
                            ) THEN
                                RAISE EXCEPTION USING ERRCODE='23514',
                                    MESSAGE='audit execution requires complete rule results';
                            END IF;
                        END IF;
                        IF NEW.status='pending_audit_review' AND
                           (NEW.finance_reviewer_id IS NULL OR NOT EXISTS (
                                SELECT 1 FROM public.audit_risks
                                 WHERE execution_id=NEW.id AND effective_level='high'
                                   AND review_status='pending'
                           )) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='audit review requires pending high risk';
                        END IF;
                        IF NEW.status='completed' THEN
                            IF NEW.finance_reviewer_id IS NULL OR EXISTS (
                                SELECT 1 FROM public.audit_risks
                                 WHERE execution_id=NEW.id AND review_status='pending'
                            ) OR (EXISTS (
                                SELECT 1 FROM public.audit_risks
                                 WHERE execution_id=NEW.id AND original_level='high'
                            ) AND NEW.audit_reviewer_id IS NULL) THEN
                                RAISE EXCEPTION USING ERRCODE='23514',
                                    MESSAGE='audit execution review gate failed';
                            END IF;
                        END IF;
                        IF NEW.status='outdated' THEN
                            UPDATE public.audit_reports
                               SET status='outdated', outdated_at=clock_timestamp(),
                                   row_version=row_version+1
                             WHERE execution_id=NEW.id AND status='ready';
                        END IF;
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME='audit_task_snapshots' THEN
                    IF TG_OP<>'INSERT' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='audit snapshots are immutable';
                    END IF;
                    SELECT organization_id,audit_task_id,status
                      INTO parent_org,parent_task,parent_status
                      FROM public.audit_task_executions
                     WHERE id=NEW.execution_id FOR KEY SHARE;
                    SELECT count(*) INTO invoice_count FROM public.audit_task_items
                     WHERE audit_task_id=NEW.audit_task_id AND item_type='invoice';
                    SELECT count(DISTINCT rule_code) INTO rule_count FROM public.audit_rules
                     WHERE id=ANY(NEW.rule_version_ids);
                    IF parent_org IS DISTINCT FROM NEW.organization_id
                       OR parent_task IS DISTINCT FROM NEW.audit_task_id
                       OR parent_status<>'validating' OR invoice_count<1 OR rule_count<>15 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='audit snapshot parent invalid';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME='rule_executions' THEN
                    IF TG_OP<>'INSERT' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='rule executions are immutable';
                    END IF;
                    SELECT e.organization_id,e.audit_task_id,e.status,s.id
                      INTO parent_org,parent_task,parent_status,parent_snapshot
                      FROM public.audit_task_executions e
                      JOIN public.audit_task_snapshots s ON s.execution_id=e.id
                     WHERE e.id=NEW.execution_id FOR KEY SHARE OF e,s;
                    SELECT rule_code INTO rule_code_value FROM public.audit_rules
                     WHERE id=NEW.audit_rule_id;
                    IF parent_org IS DISTINCT FROM NEW.organization_id
                       OR parent_task IS DISTINCT FROM NEW.audit_task_id
                       OR parent_snapshot IS DISTINCT FROM NEW.snapshot_id
                       OR parent_status<>'running' OR rule_code_value IS DISTINCT FROM NEW.rule_code
                       OR NOT EXISTS (
                            SELECT 1 FROM public.audit_task_snapshots s
                             WHERE s.id=NEW.snapshot_id
                               AND NEW.audit_rule_id=ANY(s.rule_version_ids)
                       ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='rule execution parent invalid';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME='audit_risks' THEN
                    SELECT e.organization_id,e.audit_task_id,e.status,e.finance_reviewer_id,
                           r.snapshot_id,r.rule_code,a.default_risk_level
                      INTO parent_org,parent_task,parent_status,parent_finance,parent_snapshot,
                           rule_code_value,rule_level
                      FROM public.rule_executions r
                      JOIN public.audit_task_executions e ON e.id=r.execution_id
                      JOIN public.audit_rules a ON a.id=r.audit_rule_id
                     WHERE r.id=COALESCE(NEW.rule_execution_id,OLD.rule_execution_id)
                       AND r.status='failed' FOR KEY SHARE OF r,e,a;
                    IF TG_OP='DELETE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='audit risks cannot be deleted';
                    ELSIF TG_OP='INSERT' THEN
                        IF parent_org IS DISTINCT FROM NEW.organization_id
                           OR parent_task IS DISTINCT FROM NEW.audit_task_id
                           OR parent_snapshot IS DISTINCT FROM NEW.snapshot_id
                           OR parent_status<>'running'
                           OR rule_code_value IS DISTINCT FROM NEW.rule_code
                           OR rule_level IS DISTINCT FROM NEW.original_level
                           OR NEW.effective_level<>NEW.original_level
                           OR NEW.review_status<>'pending' OR NEW.row_version<>1 THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='audit risk parent invalid';
                        END IF;
                    ELSE
                        IF ROW(NEW.id,NEW.organization_id,NEW.audit_task_id,NEW.execution_id,
                               NEW.snapshot_id,NEW.rule_execution_id,NEW.rule_code,NEW.title,
                               NEW.original_level,NEW.actual_value,NEW.expected_value,
                               NEW.created_at,NEW.trace_id)
                           IS DISTINCT FROM
                           ROW(OLD.id,OLD.organization_id,OLD.audit_task_id,OLD.execution_id,
                               OLD.snapshot_id,OLD.rule_execution_id,OLD.rule_code,OLD.title,
                               OLD.original_level,OLD.actual_value,OLD.expected_value,
                               OLD.created_at,OLD.trace_id)
                           OR NEW.row_version<>OLD.row_version+1 OR OLD.review_status<>'pending'
                           OR NEW.review_status='pending' THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='audit risk review update invalid';
                        END IF;
                        IF OLD.effective_level='high' THEN
                            IF parent_status<>'pending_audit_review'
                               OR NEW.reviewed_by IS NOT DISTINCT FROM parent_finance THEN
                                RAISE EXCEPTION USING ERRCODE='23514',
                                    MESSAGE='high risk reviewer separation failed';
                            END IF;
                        ELSIF NEW.effective_level='high' THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='finance review cannot elevate risk to high';
                        ELSIF parent_status<>'pending_finance_review' THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='non-high risk finance review state invalid';
                        END IF;
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME='risk_citations' THEN
                    IF TG_OP<>'INSERT' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='risk citations are immutable';
                    END IF;
                    SELECT organization_id,audit_task_id,execution_id
                      INTO parent_org,parent_task,parent_execution
                      FROM public.audit_risks WHERE id=NEW.risk_id FOR KEY SHARE;
                    IF parent_org IS DISTINCT FROM NEW.organization_id
                       OR parent_task IS DISTINCT FROM NEW.audit_task_id
                       OR parent_execution IS DISTINCT FROM NEW.execution_id
                       OR NOT EXISTS (
                            SELECT 1 FROM public.document_index_items i
                            JOIN public.document_chunks c ON c.id=i.chunk_id
                             WHERE i.index_version_id=NEW.index_version_id
                               AND i.policy_document_id=NEW.policy_document_id
                               AND i.markdown_version_id=NEW.markdown_version_id
                               AND i.chunk_id=NEW.chunk_id
                               AND i.content_sha256=NEW.content_sha256
                               AND c.content_sha256=NEW.content_sha256
                       ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='risk citation chain invalid';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME='audit_reports' THEN
                    SELECT organization_id,audit_task_id,status
                      INTO parent_org,parent_task,parent_status
                      FROM public.audit_task_executions
                     WHERE id=COALESCE(NEW.execution_id,OLD.execution_id) FOR UPDATE;
                    IF TG_OP='DELETE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='audit reports cannot be deleted';
                    ELSIF TG_OP='INSERT' THEN
                        IF parent_org IS DISTINCT FROM NEW.organization_id
                           OR parent_task IS DISTINCT FROM NEW.audit_task_id
                           OR parent_status<>'completed' OR NEW.status<>'queued'
                           OR NEW.row_version<>1 THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='audit report parent invalid';
                        END IF;
                    ELSE
                        IF ROW(NEW.id,NEW.organization_id,NEW.audit_task_id,NEW.execution_id,
                               NEW.report_version,NEW.payload_sha256,NEW.generator_version,
                               NEW.job_id,NEW.created_by,NEW.created_at,NEW.trace_id)
                           IS DISTINCT FROM
                           ROW(OLD.id,OLD.organization_id,OLD.audit_task_id,OLD.execution_id,
                               OLD.report_version,OLD.payload_sha256,OLD.generator_version,
                               OLD.job_id,OLD.created_by,OLD.created_at,OLD.trace_id)
                           OR NEW.row_version<>OLD.row_version+1
                           OR NOT ((OLD.status='queued' AND NEW.status IN ('generating','failed'))
                                OR (OLD.status='generating' AND NEW.status IN ('ready','failed'))
                                OR (OLD.status='failed' AND NEW.status='queued')
                                OR (OLD.status='ready' AND NEW.status IN ('outdated','archived'))
                                OR (OLD.status='outdated' AND NEW.status='archived')) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='audit report transition invalid';
                        END IF;
                        IF OLD.status IN ('ready','outdated') AND ROW(
                            NEW.pdf_bucket,NEW.pdf_object_key,NEW.pdf_sha256,NEW.pdf_size_bytes,
                            NEW.xlsx_bucket,NEW.xlsx_object_key,NEW.xlsx_sha256,NEW.xlsx_size_bytes,
                            NEW.generated_at
                        ) IS DISTINCT FROM ROW(
                            OLD.pdf_bucket,OLD.pdf_object_key,OLD.pdf_sha256,OLD.pdf_size_bytes,
                            OLD.xlsx_bucket,OLD.xlsx_object_key,OLD.xlsx_sha256,OLD.xlsx_size_bytes,
                            OLD.generated_at
                        ) THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='ready report artifacts are immutable';
                        END IF;
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME='ai_call_logs' THEN
                    IF TG_OP='DELETE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='ai call logs are append-only';
                    ELSIF TG_OP='UPDATE' THEN
                        IF OLD.status<>'pending' OR NEW.status='pending' OR NEW.event_sequence<>2
                           OR ROW(NEW.id,NEW.event_version,NEW.organization_id,
                                  NEW.business_operation_id,NEW.job_id,NEW.request_id,
                                  NEW.resource_type,NEW.resource_id,NEW.trace_id,NEW.call_type,
                                  NEW.logical_generation_no,NEW.provider_attempt_no,NEW.adapter_id,
                                  NEW.endpoint_id,NEW.model_id,NEW.model_version,NEW.prompt_id,
                                  NEW.prompt_version,NEW.prompt_hash,NEW.schema_version,
                                  NEW.policy_version,NEW.policy_hash,NEW.pricing_version,
                                  NEW.input_hash,NEW.reserved_input_tokens,
                                  NEW.reserved_output_tokens,NEW.reserved_cost_micro_usd,
                                  NEW.attempt_count,NEW.is_fallback,NEW.breaker_state,NEW.started_at)
                              IS DISTINCT FROM
                              ROW(OLD.id,OLD.event_version,OLD.organization_id,
                                  OLD.business_operation_id,OLD.job_id,OLD.request_id,
                                  OLD.resource_type,OLD.resource_id,OLD.trace_id,OLD.call_type,
                                  OLD.logical_generation_no,OLD.provider_attempt_no,OLD.adapter_id,
                                  OLD.endpoint_id,OLD.model_id,OLD.model_version,OLD.prompt_id,
                                  OLD.prompt_version,OLD.prompt_hash,OLD.schema_version,
                                  OLD.policy_version,OLD.policy_hash,OLD.pricing_version,
                                  OLD.input_hash,OLD.reserved_input_tokens,
                                  OLD.reserved_output_tokens,OLD.reserved_cost_micro_usd,
                                  OLD.attempt_count,OLD.is_fallback,OLD.breaker_state,OLD.started_at)
                        THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='ai call terminal projection invalid';
                        END IF;
                    END IF;
                    RETURN NEW;
                END IF;

                RAISE EXCEPTION USING ERRCODE='55000', MESSAGE='unsupported audit runtime table';
            END;
            $$;
            REVOKE ALL ON FUNCTION public.enforce_audit_report_runtime_v1() FROM PUBLIC;
            """
        )
    )
    for table_name in _CREATED_TABLES:
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table_name}_state_v1 "
                f"BEFORE INSERT OR UPDATE OR DELETE ON public.{table_name} "
                "FOR EACH ROW EXECUTE FUNCTION public.enforce_audit_report_runtime_v1(); "
                f"CREATE TRIGGER trg_{table_name}_no_truncate_v1 "
                f"BEFORE TRUNCATE ON public.{table_name} FOR EACH STATEMENT "
                "EXECUTE FUNCTION public.enforce_audit_report_runtime_v1();"
            )
        )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_audit_tasks_runtime_v1 BEFORE UPDATE ON public.audit_tasks "
            "FOR EACH ROW EXECUTE FUNCTION public.enforce_audit_report_runtime_v1()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout='5s'"))
    op.execute(
        sa.text(
            "LOCK TABLE public.audit_tasks, public.audit_task_executions, "
            "public.audit_task_snapshots, public.rule_executions, public.audit_risks, "
            "public.audit_reports, public.audit_task_items, public.risk_citations, "
            "public.ai_call_logs, public.audit_rules, public.user_corrections, public.invoices "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM public.audit_task_items LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.audit_task_executions LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.audit_task_snapshots LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.rule_executions LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.audit_risks LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.risk_citations LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.audit_reports LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.ai_call_logs LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.audit_rules LIMIT 1)
                   OR EXISTS (
                        SELECT 1 FROM public.user_corrections
                         WHERE related_execution_id IS NOT NULL OR correction_type='audit_risk'
                        LIMIT 1
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='refusing to drop non-empty audit report runtime';
                END IF;
            END; $$;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER trg_audit_tasks_runtime_v1 ON public.audit_tasks"))
    for table_name in reversed(_CREATED_TABLES):
        op.execute(sa.text(f"DROP TRIGGER trg_{table_name}_no_truncate_v1 ON public.{table_name}"))
        op.execute(sa.text(f"DROP TRIGGER trg_{table_name}_state_v1 ON public.{table_name}"))
    op.execute(sa.text("DROP FUNCTION public.enforce_audit_report_runtime_v1()"))

    op.drop_constraint(
        "fk_user_corrections_related_execution_id_audit_task_executions",
        "user_corrections",
        schema="public",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_audit_tasks_current_execution_id_audit_task_executions",
        "audit_tasks",
        schema="public",
        type_="foreignkey",
    )
    for table_name in reversed(_CREATED_TABLES):
        op.drop_table(table_name, schema="public")

    op.drop_constraint(
        op.f("ck_user_corrections_correction_type_allowed"),
        "user_corrections",
        schema="public",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_corrections_correction_type_allowed"),
        "user_corrections",
        "correction_type IN ('contract_field','supplementary_agreement_changes',"
        "'invoice_field','contract_invoice','supplier_field')",
        schema="public",
    )
    op.drop_constraint(
        op.f("ck_audit_rules_catalog_manifest_hash_format"),
        "audit_rules",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_audit_rules_application_release_nonempty"),
        "audit_rules",
        schema="public",
        type_="check",
    )
    op.drop_column("audit_rules", "catalog_manifest_sha256", schema="public")
    op.drop_column("audit_rules", "application_release", schema="public")
    _replace_invoice_state_guard(include_red_invoice=False)
    op.drop_column("invoices", "is_red_invoice", schema="public")
