"""安全操作日志的追加式 PostgreSQL 投影。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

OPERATION_LOG_ACTOR_KINDS = ("anonymous", "user", "system")
OPERATION_LOG_OUTCOMES = ("succeeded", "denied", "failed")
OPERATION_LOG_ACTION_CODES = (
    "system.bootstrap.completed",
    "auth.login.succeeded",
    "auth.login.failed",
    "auth.logout",
    "authorization.denied",
    "users.created",
    "users.status_changed",
    "users.password_reset",
    "users.roles_replaced",
    "break_glass.requested",
    "break_glass.approved",
    "break_glass.rejected",
    "break_glass.revoked",
    "files.uploaded",
    "files.previewed",
    "files.archived",
    "files.retry_queued",
    "document_block.correction_requested",
    "document_parse.security_revalidation.requested",
    "document_parse.activated",
    "supplementary_agreements.changes_replaced",
    "supplementary_agreements.confirmed",
    "supplementary_agreements.rejected",
    "contract_invoices.suggested",
    "contract_invoices.primary_confirmed",
    "contract_invoices.primary_replaced",
    "contract_invoices.primary_cancelled",
    "contracts.extraction_created",
    "contracts.facts_replaced",
    "contracts.confirmed",
    "contracts.rejected",
    "invoices.extraction_created",
    "invoices.facts_replaced",
    "invoices.confirmed",
    "invoices.rejected",
    "invoices.duplicate_checked",
    "invoices.duplicate_confirmed",
    "invoices.duplicate_exception_approved",
    "supplier.resolve",
    "supplier.update",
    "policy.created",
    "policy.submitted",
    "policy.business_approved",
    "policy.published",
    "policy.revocation_requested",
    "policy.revoked",
    "knowledge.index_build_queued",
    "knowledge.index_ready",
    "knowledge.index_activated",
    "knowledge.eval_dataset_created",
    "knowledge.eval_dataset_submitted",
    "knowledge.eval_dataset_approved",
    "knowledge.eval_queued",
    "knowledge.eval_completed",
    "knowledge.qa_queried",
    "knowledge.qa_feedback",
    "audits.task_created",
    "audits.execution_reaudit_queued",
    "audits.execution_retry_queued",
    "audits.execution_evaluated",
    "audits.risk_reviewed",
    "audits.high_risk_reviewed",
    "audits.execution_cancelled",
    "audits.finance_review_submit",
    "audits.finance_review_return",
    "audits.audit_review_complete",
    "audits.audit_review_return",
    "reports.generation_queued",
    "reports.generated",
    "reports.generation_failed",
    "reports.pdf_previewed",
    "reports.xlsx_downloaded",
)


class OperationLog(Base):
    """认证、授权与身份写操作的脱敏追加式审计记录。"""

    __tablename__ = "operation_logs"
    __table_args__ = (
        CheckConstraint(
            "(action_code COLLATE \"C\") ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$'",
            name="action_code_format",
        ),
        CheckConstraint(
            "(actor_kind = 'user' AND organization_id IS NOT NULL "
            "AND actor_id IS NOT NULL) OR "
            "(actor_kind IN ('anonymous', 'system') AND actor_id IS NULL)",
            name="actor_matrix",
        ),
        CheckConstraint(
            "jsonb_typeof(change_summary_json) = 'object' "
            "AND octet_length(change_summary_json::text) <= 16384",
            name="change_summary_object",
        ),
        CheckConstraint(
            "outcome IN ('succeeded', 'denied', 'failed')",
            name="outcome_allowed",
        ),
        CheckConstraint(
            "(resource_type IS NULL AND resource_id IS NULL) OR "
            "(resource_type IS NOT NULL AND resource_id IS NOT NULL)",
            name="resource_matrix",
        ),
        CheckConstraint(
            "resource_type IS NULL OR (resource_type COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'",
            name="resource_type_format",
        ),
        Index(
            "idx_operation_logs_actor_created",
            "actor_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index(
            "idx_operation_logs_organization_created",
            "organization_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index(
            "idx_operation_logs_resource_created",
            "resource_type",
            "resource_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index("idx_operation_logs_trace", "trace_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            name="fk_operation_logs_organization_id_organizations",
        ),
    )
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_operation_logs_actor_id_users"),
    )
    action_code: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    change_summary_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
