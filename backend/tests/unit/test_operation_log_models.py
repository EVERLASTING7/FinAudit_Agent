import re

from sqlalchemy import CheckConstraint, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models import (
    OPERATION_LOG_ACTION_CODES,
    OPERATION_LOG_ACTOR_KINDS,
    OPERATION_LOG_OUTCOMES,
    Base,
)


def test_operation_log_constants_are_exact() -> None:
    assert OPERATION_LOG_ACTOR_KINDS == ("anonymous", "user", "system")
    assert OPERATION_LOG_OUTCOMES == ("succeeded", "denied", "failed")
    assert OPERATION_LOG_ACTION_CODES == (
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
    action_pattern = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    assert all(action_pattern.fullmatch(action) for action in OPERATION_LOG_ACTION_CODES)


def test_operation_log_model_is_exact_append_only_storage_projection() -> None:
    table = Base.metadata.tables["operation_logs"]

    assert list(table.c.keys()) == [
        "id",
        "organization_id",
        "actor_kind",
        "actor_id",
        "action_code",
        "outcome",
        "resource_type",
        "resource_id",
        "trace_id",
        "change_summary_json",
        "created_at",
    ]
    assert isinstance(table.c.change_summary_json.type, JSONB)
    assert str(table.c.id.server_default.arg) == "gen_random_uuid()"
    assert str(table.c.change_summary_json.server_default.arg) == "'{}'::jsonb"
    assert str(table.c.created_at.server_default.arg) == "now()"

    checks = {
        str(constraint.name): " ".join(str(constraint.sqltext).split())
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert set(checks) == {
        "ck_operation_logs_action_code_format",
        "ck_operation_logs_actor_matrix",
        "ck_operation_logs_change_summary_object",
        "ck_operation_logs_outcome_allowed",
        "ck_operation_logs_resource_matrix",
        "ck_operation_logs_resource_type_format",
    }
    assert (
        "jsonb_typeof(change_summary_json) = 'object'"
        in checks["ck_operation_logs_change_summary_object"]
    )

    foreign_keys = {
        str(constraint.name): tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert foreign_keys == {
        "fk_operation_logs_actor_id_users": ("users.id",),
        "fk_operation_logs_organization_id_organizations": ("organizations.id",),
    }
    assert {str(index.name) for index in table.indexes} == {
        "idx_operation_logs_actor_created",
        "idx_operation_logs_organization_created",
        "idx_operation_logs_resource_created",
        "idx_operation_logs_trace",
    }
