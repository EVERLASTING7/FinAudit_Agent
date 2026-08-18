"""审核任务、不可变执行版本、风险、报告与 AI 调用摘要。"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

RISK_LEVELS = ("none", "notice", "low", "medium", "high")
AUDIT_TASK_STATUSES = ("open", "completed", "archived")
AUDIT_EXECUTION_STATUSES = (
    "draft",
    "validating",
    "queued",
    "running",
    "pending_finance_review",
    "pending_audit_review",
    "returned_for_correction",
    "completed",
    "failed",
    "cancelled",
    "outdated",
)
RULE_EXECUTION_STATUSES = ("passed", "failed", "not_applicable", "error")
RISK_REVIEW_STATUSES = ("pending", "confirmed", "dismissed", "adjusted", "returned")
AUDIT_REPORT_STATUSES = ("queued", "generating", "ready", "failed", "outdated", "archived")
AI_CALL_STATUSES = ("pending", "succeeded", "failed", "degraded", "rejected", "outcome_unknown")


class AuditTask(Base):
    """稳定审核案件；执行结果由后续执行版本表保存。"""

    __tablename__ = "audit_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'completed', 'archived')",
            name="status_allowed",
        ),
        CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        UniqueConstraint(
            "organization_id",
            "task_no",
            name="uq_audit_tasks_organization_id_task_no",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_audit_tasks_organization_id_organizations"),
        nullable=False,
    )
    task_no: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_audit_tasks_owner_id_users"),
        nullable=False,
    )
    current_execution_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "audit_task_executions.id",
            name="fk_audit_tasks_current_execution_id_audit_task_executions",
        ),
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_audit_tasks_created_by_users"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_audit_tasks_updated_by_users"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_audit_tasks_deleted_by_users"),
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)


class AuditRule(Base):
    """由 AUD-003 发布、创建后不可修改的规则版本。"""

    __tablename__ = "audit_rules"
    __table_args__ = (
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "default_risk_level IN ('none', 'notice', 'low', 'medium', 'high')",
            name="default_risk_level_allowed",
        ),
        CheckConstraint("btrim(application_release) <> ''", name="application_release_nonempty"),
        CheckConstraint(
            "catalog_manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name="catalog_manifest_hash_format",
        ),
        UniqueConstraint("rule_code", "version", name="uq_audit_rules_code_version"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    rule_code: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    input_schema_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    implementation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    implementation_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    application_release: Mapped[str] = mapped_column(String(100), nullable=False)
    catalog_manifest_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    default_risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    explanation_template: Mapped[str] = mapped_column(Text, nullable=False)
    requires_policy_citation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AuditTaskItem(Base):
    __tablename__ = "audit_task_items"
    __table_args__ = (
        CheckConstraint("item_type IN ('contract','invoice')", name="item_type_allowed"),
        CheckConstraint(
            "(item_type='contract' AND contract_id IS NOT NULL AND invoice_id IS NULL) OR "
            "(item_type='invoice' AND invoice_id IS NOT NULL AND contract_id IS NULL)",
            name="item_reference_matrix",
        ),
        UniqueConstraint("audit_task_id", "contract_id", name="uq_audit_task_contract"),
        UniqueConstraint("audit_task_id", "invoice_id", name="uq_audit_task_invoice"),
        Index(
            "uq_audit_task_single_contract",
            "audit_task_id",
            unique=True,
            postgresql_where=text("contract_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    audit_task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_tasks.id"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    contract_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("contracts.id")
    )
    invoice_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("invoices.id")
    )
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AuditTaskExecution(Base):
    __tablename__ = "audit_task_executions"
    __table_args__ = (
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint(
            "status IN ('draft','validating','queued','running','pending_finance_review',"
            "'pending_audit_review','returned_for_correction','completed','failed','cancelled',"
            "'outdated')",
            name="status_allowed",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        CheckConstraint(
            "snapshot_sha256 IS NULL OR snapshot_sha256 ~ '^[0-9a-f]{64}$'",
            name="snapshot_hash_format",
        ),
        CheckConstraint(
            "(finance_reviewer_id IS NULL) = (finance_reviewed_at IS NULL)",
            name="finance_review_pair",
        ),
        CheckConstraint(
            "(audit_reviewer_id IS NULL) = (audit_reviewed_at IS NULL)",
            name="audit_review_pair",
        ),
        CheckConstraint(
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
        UniqueConstraint("audit_task_id", "version_no", name="uq_audit_execution_version"),
        UniqueConstraint("job_id", name="uq_audit_execution_job"),
        Index("idx_audit_executions_task_created", "audit_task_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    audit_task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_tasks.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    snapshot_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("async_jobs.id"))
    finance_reviewer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    finance_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audit_reviewer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    audit_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    return_reason: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outdated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class AuditTaskSnapshot(Base):
    __tablename__ = "audit_task_snapshots"
    __table_args__ = (
        CheckConstraint("schema_version > 0", name="schema_version_positive"),
        CheckConstraint("facts_sha256 ~ '^[0-9a-f]{64}$'", name="facts_hash_format"),
        CheckConstraint("jsonb_typeof(facts_json)='object'", name="facts_object"),
        CheckConstraint("cardinality(rule_version_ids)=15", name="fifteen_rule_versions"),
        UniqueConstraint("execution_id", name="uq_audit_snapshot_execution"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    audit_task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_tasks.id"), nullable=False
    )
    execution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_task_executions.id"), nullable=False
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_date: Mapped[date] = mapped_column(Date, nullable=False)
    facts_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    facts_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    rule_version_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False
    )
    index_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_index_versions.id")
    )
    application_release: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class RuleExecution(Base):
    __tablename__ = "rule_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('passed','failed','not_applicable','error')", name="status_allowed"
        ),
        CheckConstraint("jsonb_typeof(input_json)='object'", name="input_object"),
        CheckConstraint(
            "actual_value_json IS NULL OR jsonb_typeof(actual_value_json)='object'",
            name="actual_value_object",
        ),
        CheckConstraint(
            "expected_value_json IS NULL OR jsonb_typeof(expected_value_json)='object'",
            name="expected_value_object",
        ),
        CheckConstraint(
            "(status='error' AND error_code IS NOT NULL) OR "
            "(status<>'error' AND error_code IS NULL)",
            name="error_matrix",
        ),
        UniqueConstraint("execution_id", "audit_rule_id", name="uq_rule_execution_rule"),
        Index("idx_rule_executions_execution", "execution_id", "rule_code"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    audit_task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_tasks.id"), nullable=False
    )
    execution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_task_executions.id"), nullable=False
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_task_snapshots.id"), nullable=False
    )
    audit_rule_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_rules.id"), nullable=False
    )
    rule_code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    actual_value_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    expected_value_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    applicability_reason: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(80))
    included_item_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    excluded_item_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AuditRisk(Base):
    __tablename__ = "audit_risks"
    __table_args__ = (
        CheckConstraint(
            "original_level IN ('none','notice','low','medium','high')",
            name="original_level_allowed",
        ),
        CheckConstraint(
            "effective_level IN ('none','notice','low','medium','high')",
            name="effective_level_allowed",
        ),
        CheckConstraint(
            "review_status IN ('pending','confirmed','dismissed','adjusted','returned')",
            name="review_status_allowed",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        CheckConstraint(
            "(review_status='pending' AND reviewed_by IS NULL AND reviewed_at IS NULL "
            "AND review_reason IS NULL) OR "
            "(review_status<>'pending' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND review_reason IS NOT NULL AND btrim(review_reason)<>'')",
            name="review_metadata_matrix",
        ),
        CheckConstraint(
            "review_status<>'adjusted' OR effective_level<>original_level",
            name="adjusted_level_changes",
        ),
        CheckConstraint(
            "ai_explanation_status IN ('disabled','succeeded','degraded')",
            name="ai_explanation_status_allowed",
        ),
        CheckConstraint(
            "ai_explanation_json IS NULL OR jsonb_typeof(ai_explanation_json)='object'",
            name="ai_explanation_object",
        ),
        CheckConstraint(
            "ai_explanation_sha256 IS NULL OR ai_explanation_sha256 ~ '^[0-9a-f]{64}$'",
            name="ai_explanation_hash_format",
        ),
        CheckConstraint(
            "(ai_explanation_status='succeeded' AND ai_explanation_json IS NOT NULL "
            "AND ai_explanation_sha256 IS NOT NULL) OR "
            "(ai_explanation_status IN ('disabled','degraded') "
            "AND ai_explanation_json IS NULL AND ai_explanation_sha256 IS NULL)",
            name="ai_explanation_matrix",
        ),
        UniqueConstraint("rule_execution_id", name="uq_audit_risk_rule_execution"),
        Index("idx_audit_risks_execution_review", "execution_id", "review_status"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    audit_task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_tasks.id"), nullable=False
    )
    execution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_task_executions.id"), nullable=False
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_task_snapshots.id"), nullable=False
    )
    rule_execution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("rule_executions.id"), nullable=False
    )
    rule_code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    original_level: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_level: Mapped[str] = mapped_column(String(20), nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False)
    actual_value: Mapped[str | None] = mapped_column(Text)
    expected_value: Mapped[str | None] = mapped_column(Text)
    ai_explanation_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="disabled"
    )
    ai_explanation_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    ai_explanation_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    review_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class RiskCitation(Base):
    __tablename__ = "risk_citations"
    __table_args__ = (
        CheckConstraint("start_page_no > 0", name="start_page_positive"),
        CheckConstraint("end_page_no >= start_page_no", name="page_range_valid"),
        CheckConstraint("btrim(quote)<>''", name="quote_nonempty"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_hash_format"),
        CheckConstraint("cardinality(block_ids)>0", name="block_ids_nonempty"),
        UniqueConstraint("risk_id", "chunk_id", name="uq_risk_citation_chunk"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    audit_task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_tasks.id"), nullable=False
    )
    execution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_task_executions.id"), nullable=False
    )
    risk_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_risks.id"), nullable=False
    )
    policy_document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("policy_documents.id"), nullable=False
    )
    markdown_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_markdown_versions.id"), nullable=False
    )
    chunk_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_chunks.id"), nullable=False
    )
    index_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_index_versions.id"), nullable=False
    )
    block_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False)
    start_page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AuditReport(Base):
    __tablename__ = "audit_reports"
    __table_args__ = (
        CheckConstraint("report_version > 0", name="report_version_positive"),
        CheckConstraint(
            "status IN ('queued','generating','ready','failed','outdated','archived')",
            name="status_allowed",
        ),
        CheckConstraint("payload_sha256 ~ '^[0-9a-f]{64}$'", name="payload_hash_format"),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        CheckConstraint(
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
        CheckConstraint(
            "(status='failed' AND failure_code IS NOT NULL) OR "
            "(status<>'failed' AND failure_code IS NULL)",
            name="failure_matrix",
        ),
        CheckConstraint(
            "ai_draft_status IN ('disabled','succeeded','degraded')",
            name="ai_draft_status_allowed",
        ),
        CheckConstraint(
            "ai_draft_json IS NULL OR jsonb_typeof(ai_draft_json)='object'",
            name="ai_draft_object",
        ),
        CheckConstraint(
            "ai_draft_sha256 IS NULL OR ai_draft_sha256 ~ '^[0-9a-f]{64}$'",
            name="ai_draft_hash_format",
        ),
        CheckConstraint(
            "(ai_draft_status='succeeded' AND ai_draft_json IS NOT NULL "
            "AND ai_draft_sha256 IS NOT NULL) OR "
            "(ai_draft_status IN ('disabled','degraded') "
            "AND ai_draft_json IS NULL AND ai_draft_sha256 IS NULL)",
            name="ai_draft_matrix",
        ),
        UniqueConstraint("execution_id", "report_version", name="uq_audit_report_version"),
        UniqueConstraint("job_id", name="uq_audit_report_job"),
        Index("idx_audit_reports_execution_created", "execution_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    audit_task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_tasks.id"), nullable=False
    )
    execution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("audit_task_executions.id"), nullable=False
    )
    report_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    ai_draft_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="disabled"
    )
    ai_draft_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    ai_draft_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    pdf_bucket: Mapped[str | None] = mapped_column(String(100))
    pdf_object_key: Mapped[str | None] = mapped_column(String(500))
    pdf_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    pdf_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    pdf_mime_type: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="application/pdf"
    )
    xlsx_bucket: Mapped[str | None] = mapped_column(String(100))
    xlsx_object_key: Mapped[str | None] = mapped_column(String(500))
    xlsx_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    xlsx_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    xlsx_mime_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        server_default="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("async_jobs.id"))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outdated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class AiCallLog(Base):
    __tablename__ = "ai_call_logs"
    __table_args__ = (
        CheckConstraint("event_version IN (1,2)", name="event_version_allowed"),
        CheckConstraint("event_sequence IN (1,2)", name="event_sequence_allowed"),
        CheckConstraint("logical_generation_no>0", name="generation_positive"),
        CheckConstraint("provider_attempt_no>0", name="provider_attempt_positive"),
        CheckConstraint("attempt_count>0", name="attempt_count_positive"),
        CheckConstraint(
            "reserved_input_tokens>=0 AND reserved_output_tokens>=0 "
            "AND (reserved_cost_micro_usd IS NULL OR reserved_cost_micro_usd>=0) "
            "AND (reserved_cost_microunits IS NULL OR reserved_cost_microunits>=0) "
            "AND (actual_cost_microunits IS NULL OR actual_cost_microunits>=0)",
            name="reservation_nonnegative",
        ),
        CheckConstraint(
            "(event_version=1 AND reserved_cost_micro_usd IS NOT NULL "
            "AND cost_currency IS NULL AND reserved_cost_microunits IS NULL "
            "AND actual_cost_microunits IS NULL) OR "
            "(event_version=2 AND reserved_cost_micro_usd IS NULL "
            "AND reserved_cost_microunits IS NOT NULL "
            "AND (cost_currency IN ('USD','CNY') OR "
            "(cost_currency IS NULL AND reserved_cost_microunits=0 "
            "AND (actual_cost_microunits IS NULL OR actual_cost_microunits=0))))",
            name="cost_version_matrix",
        ),
        CheckConstraint(
            "event_version=1 OR "
            "(status IN ('pending','outcome_unknown') AND actual_cost_microunits IS NULL) OR "
            "(status='succeeded' AND actual_cost_microunits IS NOT NULL) OR "
            "status IN ('failed','degraded','rejected')",
            name="actual_cost_matrix",
        ),
        CheckConstraint(
            "status IN ('pending','succeeded','failed','degraded','rejected','outcome_unknown')",
            name="status_allowed",
        ),
        CheckConstraint(
            "policy_hash ~ '^[0-9a-f]{64}$' AND input_hash ~ '^[0-9a-f]{64}$' "
            "AND (prompt_hash IS NULL OR prompt_hash ~ '^[0-9a-f]{64}$') "
            "AND (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$')",
            name="hashes_lower_hex",
        ),
        CheckConstraint(
            "(status='pending' AND event_sequence=1 AND completed_at IS NULL) OR "
            "(status<>'pending' AND event_sequence=2 AND completed_at IS NOT NULL)",
            name="lifecycle_matrix",
        ),
        Index("idx_ai_call_logs_operation", "business_operation_id", "provider_attempt_no"),
        Index("idx_ai_call_logs_status_started", "status", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    business_operation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("async_jobs.id"))
    request_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    resource_type: Mapped[str | None] = mapped_column(String(60))
    resource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    call_type: Mapped[str] = mapped_column(String(50), nullable=False)
    logical_generation_no: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(100), nullable=False)
    endpoint_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(100))
    prompt_id: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    prompt_hash: Mapped[str | None] = mapped_column(CHAR(64))
    schema_version: Mapped[str | None] = mapped_column(String(100))
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    pricing_version: Mapped[str] = mapped_column(String(80), nullable=False)
    input_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(CHAR(64))
    reserved_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_cost_micro_usd: Mapped[int | None] = mapped_column(BigInteger)
    cost_currency: Mapped[str | None] = mapped_column(String(3))
    reserved_cost_microunits: Mapped[int | None] = mapped_column(BigInteger)
    actual_cost_microunits: Mapped[int | None] = mapped_column(BigInteger)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    vector_count: Mapped[int | None] = mapped_column(Integer)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    breaker_state: Mapped[str | None] = mapped_column(String(30))
    citation_validation_status: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(80))
    safe_error_code: Mapped[str | None] = mapped_column(String(80))
    http_status: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
