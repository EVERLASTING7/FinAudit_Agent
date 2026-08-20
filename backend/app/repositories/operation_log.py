"""操作日志追加写与 action 级脱敏摘要门禁。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.permissions import PERMISSION_CODES, ROLE_CODES
from app.models.operations import (
    OPERATION_LOG_ACTION_CODES,
    OPERATION_LOG_ACTOR_KINDS,
    OPERATION_LOG_OUTCOMES,
    OperationLog,
)

_RESOURCE_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9]\d*$")
_USER_STATUSES = frozenset({"active", "disabled", "locked"})
_BREAK_GLASS_ROLE_CODES = frozenset(set(ROLE_CODES) - {"read_only"})


def _require_exact_keys(summary: Mapping[str, object], expected: set[str]) -> None:
    if set(summary) != expected or any(type(key) is not str for key in summary):
        raise ValueError("operation summary keys do not match the action registry")


def _require_row_version(value: object) -> None:
    if type(value) is not str or _POSITIVE_INTEGER_PATTERN.fullmatch(value) is None:
        raise ValueError("operation summary row_version is invalid")


def _require_uuid_text(value: object) -> None:
    if type(value) is not str:
        raise ValueError("operation summary identifier is invalid")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("operation summary identifier is invalid") from None
    if str(parsed) != value:
        raise ValueError("operation summary identifier is invalid")


def _require_sha256(value: object) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("operation summary sha256 is invalid")


def _require_role_codes(value: object, *, allow_empty: bool = False) -> None:
    minimum_length = 0 if allow_empty else 1
    if type(value) is not list or not minimum_length <= len(value) <= len(ROLE_CODES):
        raise ValueError("operation summary roles are invalid")
    if any(type(role) is not str for role in value):
        raise ValueError("operation summary roles are invalid")
    roles = cast(list[str], value)
    if roles != sorted(set(roles)) or any(role not in ROLE_CODES for role in roles):
        raise ValueError("operation summary roles are invalid")


def _validate_change_summary(action_code: str, summary: Mapping[str, object]) -> None:
    if action_code == "system.bootstrap.completed":
        _require_exact_keys(summary, {"initial_admin_id", "role_code"})
        _require_uuid_text(summary["initial_admin_id"])
        if summary["role_code"] != "system_admin":
            raise ValueError("operation summary bootstrap role is invalid")
    elif action_code == "auth.login.succeeded":
        _require_exact_keys(summary, set())
    elif action_code == "auth.login.failed":
        _require_exact_keys(summary, {"failure_code"})
        if summary["failure_code"] != "invalid_credentials":
            raise ValueError("operation summary failure_code is invalid")
    elif action_code == "auth.logout":
        _require_exact_keys(summary, {"session_recognized"})
        if type(summary["session_recognized"]) is not bool:
            raise ValueError("operation summary session_recognized is invalid")
    elif action_code == "authorization.denied":
        _require_exact_keys(summary, {"permission_code"})
        if summary["permission_code"] not in PERMISSION_CODES:
            raise ValueError("operation summary permission_code is invalid")
    elif action_code == "document_block.correction_requested":
        _require_exact_keys(
            summary,
            {"field_name", "source_parse_version_id", "status"},
        )
        _require_uuid_text(summary["source_parse_version_id"])
        if (
            summary["field_name"] not in {"text_content", "block_type", "reading_order", "bbox"}
            or summary["status"] != "queued"
        ):
            raise ValueError("operation summary document correction is invalid")
    elif action_code == "document_parse.security_revalidation.requested":
        _require_exact_keys(summary, {"source_parse_version_id", "status"})
        if summary["status"] != "queued":
            raise ValueError("operation summary security revalidation is invalid")
        _require_uuid_text(summary["source_parse_version_id"])
    elif action_code == "document_parse.activated":
        _require_exact_keys(summary, {"source_parse_version_id", "status"})
        _require_uuid_text(summary["source_parse_version_id"])
        if summary["status"] != "active":
            raise ValueError("operation summary parse activation is invalid")
    elif action_code == "users.created":
        _require_exact_keys(summary, {"fixed_roles", "row_version"})
        _require_role_codes(summary["fixed_roles"])
        _require_row_version(summary["row_version"])
    elif action_code == "users.status_changed":
        _require_exact_keys(summary, {"from_status", "to_status", "row_version"})
        if (
            summary["from_status"] not in _USER_STATUSES
            or summary["to_status"] not in {"active", "disabled"}
            or summary["from_status"] == summary["to_status"]
        ):
            raise ValueError("operation summary status transition is invalid")
        _require_row_version(summary["row_version"])
    elif action_code == "users.password_reset":
        _require_exact_keys(summary, {"row_version"})
        _require_row_version(summary["row_version"])
    elif action_code == "users.roles_replaced":
        _require_exact_keys(summary, {"old_roles", "new_roles", "row_version"})
        _require_role_codes(summary["old_roles"], allow_empty=True)
        _require_role_codes(summary["new_roles"])
        if summary["old_roles"] == summary["new_roles"]:
            raise ValueError("operation summary role transition is unchanged")
        _require_row_version(summary["row_version"])
    elif action_code == "break_glass.requested":
        _require_exact_keys(
            summary,
            {
                "target_role_code",
                "status",
                "row_version",
                "requested_duration_seconds",
            },
        )
        if (
            summary["target_role_code"] not in _BREAK_GLASS_ROLE_CODES
            or summary["status"] != "pending"
            or type(summary["requested_duration_seconds"]) is not int
            or not 1 <= summary["requested_duration_seconds"] <= 14_400
        ):
            raise ValueError("operation summary break-glass request is invalid")
        _require_row_version(summary["row_version"])
    elif action_code in {
        "break_glass.approved",
        "break_glass.rejected",
        "break_glass.revoked",
    }:
        _require_exact_keys(summary, {"target_role_code", "status", "row_version"})
        expected_status = action_code.rsplit(".", maxsplit=1)[1]
        if (
            summary["target_role_code"] not in _BREAK_GLASS_ROLE_CODES
            or summary["status"] != expected_status
        ):
            raise ValueError("operation summary break-glass transition is invalid")
        _require_row_version(summary["row_version"])
    elif action_code == "files.uploaded":
        _require_exact_keys(
            summary,
            {"intended_business_type", "job_scope", "row_version"},
        )
        if summary["intended_business_type"] not in {
            "contract",
            "supplementary_agreement",
            "invoice",
            "policy",
        } or summary["job_scope"] not in {"full", "scan_only"}:
            raise ValueError("operation summary file upload is invalid")
        _require_row_version(summary["row_version"])
    elif action_code == "files.previewed":
        _require_exact_keys(summary, {"format", "status", "row_version"})
        if summary["format"] not in {"original", "markdown"} or summary["status"] not in {
            "stored",
            "archived",
        }:
            raise ValueError("operation summary file preview is invalid")
        _require_row_version(summary["row_version"])
    elif action_code == "files.archived":
        _require_exact_keys(summary, {"reason_sha256", "status", "row_version"})
        if summary["status"] != "archived":
            raise ValueError("operation summary file archive is invalid")
        _require_sha256(summary["reason_sha256"])
        _require_row_version(summary["row_version"])
    elif action_code == "files.retry_queued":
        _require_exact_keys(
            summary,
            {"job_id", "reason_sha256", "stage", "row_version"},
        )
        _require_uuid_text(summary["job_id"])
        _require_sha256(summary["reason_sha256"])
        if summary["stage"] not in {"scan", "parse"}:
            raise ValueError("operation summary file retry is invalid")
        _require_row_version(summary["row_version"])
    elif action_code in {
        "supplementary_agreements.changes_replaced",
        "supplementary_agreements.confirmed",
        "supplementary_agreements.rejected",
    }:
        _require_exact_keys(summary, {"change_count", "row_version"})
        if type(summary["change_count"]) is not int or not 1 <= summary["change_count"] <= 100:
            raise ValueError("operation summary change_count is invalid")
        _require_row_version(summary["row_version"])
    elif action_code in {
        "contract_invoices.suggested",
        "contract_invoices.primary_confirmed",
        "contract_invoices.primary_replaced",
        "contract_invoices.primary_cancelled",
    }:
        _require_exact_keys(
            summary,
            {"invoice_row_version", "relation_row_version", "relation_status"},
        )
        expected_status = {
            "contract_invoices.suggested": "suggested",
            "contract_invoices.primary_confirmed": "confirmed_primary",
            "contract_invoices.primary_replaced": "confirmed_primary",
            "contract_invoices.primary_cancelled": "cancelled",
        }[action_code]
        if summary["relation_status"] != expected_status:
            raise ValueError("operation summary relation status is invalid")
        _require_row_version(summary["invoice_row_version"])
        _require_row_version(summary["relation_row_version"])
    elif action_code in {"contracts.extraction_created", "contracts.facts_replaced"}:
        _require_exact_keys(summary, {"field_count", "row_version"})
        if type(summary["field_count"]) is not int or not 0 <= summary["field_count"] <= 13:
            raise ValueError("operation summary contract facts are invalid")
        _require_row_version(summary["row_version"])
    elif action_code in {"contracts.confirmed", "contracts.rejected"}:
        _require_exact_keys(summary, {"confirmation_status", "row_version"})
        if summary["confirmation_status"] != action_code.rsplit(".", maxsplit=1)[1]:
            raise ValueError("operation summary contract decision is invalid")
        _require_row_version(summary["row_version"])
    elif action_code in {"invoices.extraction_created", "invoices.facts_replaced"}:
        _require_exact_keys(
            summary,
            {"field_count", "item_count", "duplicate_status", "row_version"},
        )
        if (
            type(summary["field_count"]) is not int
            or not 0 <= summary["field_count"] <= 13
            or type(summary["item_count"]) is not int
            or not 0 <= summary["item_count"] <= 1000
            or summary["duplicate_status"] not in {"not_checked", "unique", "suspected"}
        ):
            raise ValueError("operation summary invoice facts are invalid")
        _require_row_version(summary["row_version"])
    elif action_code in {"invoices.confirmed", "invoices.rejected"}:
        _require_exact_keys(summary, {"confirmation_status", "row_version"})
        if summary["confirmation_status"] != action_code.rsplit(".", maxsplit=1)[1]:
            raise ValueError("operation summary invoice decision is invalid")
        _require_row_version(summary["row_version"])
    elif action_code in {
        "invoices.duplicate_checked",
        "invoices.duplicate_confirmed",
        "invoices.duplicate_exception_approved",
    }:
        _require_exact_keys(summary, {"duplicate_status", "row_version"})
        expected_statuses = {
            "invoices.duplicate_checked": {"not_checked", "unique", "suspected"},
            "invoices.duplicate_confirmed": {"confirmed_duplicate"},
            "invoices.duplicate_exception_approved": {"exception_approved"},
        }[action_code]
        if summary["duplicate_status"] not in expected_statuses:
            raise ValueError("operation summary duplicate status is invalid")
        _require_row_version(summary["row_version"])
    elif action_code == "supplier.resolve":
        _require_exact_keys(
            summary,
            {"created", "reused", "source_type", "source_row_version", "supplier_status"},
        )
        if (
            type(summary["created"]) is not bool
            or type(summary["reused"]) is not bool
            or (summary["created"] and summary["reused"])
            or summary["source_type"] not in {"contract", "invoice"}
            or summary["supplier_status"] not in {"candidate", "active"}
        ):
            raise ValueError("operation summary supplier resolve is invalid")
        _require_row_version(summary["source_row_version"])
    elif action_code == "supplier.update":
        _require_exact_keys(summary, {"changed_fields", "reused", "row_version", "status"})
        allowed_fields = {
            "confirmation_status",
            "source_supplier_id",
            "standard_name",
            "status",
            "tax_number",
        }
        changed_fields = summary["changed_fields"]
        if (
            type(changed_fields) is not list
            or not changed_fields
            or any(type(field) is not str for field in changed_fields)
            or changed_fields != sorted(set(changed_fields))
            or any(field not in allowed_fields for field in changed_fields)
            or type(summary["reused"]) is not bool
            or summary["status"] not in {"candidate", "active", "inactive"}
        ):
            raise ValueError("operation summary supplier update is invalid")
        _require_row_version(summary["row_version"])
    elif action_code == "policy.created":
        _require_exact_keys(summary, {"status", "row_version"})
        if summary["status"] != "draft":
            raise ValueError("operation summary policy status is invalid")
        _require_row_version(summary["row_version"])
    elif action_code == "policy.submitted":
        _require_exact_keys(summary, {"from_status", "to_status", "row_version"})
        if summary["from_status"] != "draft" or summary["to_status"] != "submitted":
            raise ValueError("operation summary policy transition is invalid")
        _require_row_version(summary["row_version"])
    elif action_code == "policy.business_approved":
        _require_exact_keys(
            summary,
            {"chunk_count", "from_status", "profile_hash", "to_status", "row_version"},
        )
        if (
            summary["from_status"] != "submitted"
            or summary["to_status"] != "business_approved"
            or type(summary["chunk_count"]) is not int
            or summary["chunk_count"] <= 0
            or type(summary["profile_hash"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", summary["profile_hash"]) is None
        ):
            raise ValueError("operation summary policy approval is invalid")
        _require_row_version(summary["row_version"])
    elif action_code == "policy.published":
        _require_exact_keys(
            summary,
            {"from_status", "index_version_id", "row_version", "to_status"},
        )
        if summary["from_status"] != "business_approved" or summary["to_status"] != "published":
            raise ValueError("operation summary policy publication is invalid")
        _require_uuid_text(summary["index_version_id"])
        _require_row_version(summary["row_version"])
    elif action_code == "policy.revocation_requested":
        _require_exact_keys(summary, {"revocation_request_id", "status"})
        if summary["status"] != "pending_execution":
            raise ValueError("operation summary policy revocation request is invalid")
        _require_uuid_text(summary["revocation_request_id"])
    elif action_code == "policy.revoked":
        _require_exact_keys(
            summary,
            {"from_status", "revocation_request_id", "row_version", "to_status"},
        )
        if summary["from_status"] != "published" or summary["to_status"] != "revoked":
            raise ValueError("operation summary policy revocation is invalid")
        _require_uuid_text(summary["revocation_request_id"])
        _require_row_version(summary["row_version"])
    elif action_code in {"knowledge.index_build_queued", "knowledge.index_ready"}:
        _require_exact_keys(summary, {"manifest_sha256", "member_count", "status"})
        expected_status = "building" if action_code == "knowledge.index_build_queued" else "ready"
        if (
            summary["status"] != expected_status
            or type(summary["member_count"]) is not int
            or not 1 <= summary["member_count"] <= 10_000
            or type(summary["manifest_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", summary["manifest_sha256"]) is None
        ):
            raise ValueError("operation summary index lifecycle is invalid")
    elif action_code == "knowledge.index_activated":
        _require_exact_keys(summary, {"from_status", "row_version", "to_status"})
        if summary["from_status"] != "ready" or summary["to_status"] != "active":
            raise ValueError("operation summary index activation is invalid")
        _require_row_version(summary["row_version"])
    elif action_code in {
        "knowledge.eval_dataset_created",
        "knowledge.eval_dataset_submitted",
        "knowledge.eval_dataset_approved",
    }:
        expected = {"case_count", "row_version", "status", "tier"}
        _require_exact_keys(summary, expected)
        expected_status = {
            "knowledge.eval_dataset_created": "draft",
            "knowledge.eval_dataset_submitted": "submitted",
            "knowledge.eval_dataset_approved": "approved",
        }[action_code]
        if (
            summary["status"] != expected_status
            or summary["tier"] not in {"smoke", "mvp_uat", "formal_release"}
            or type(summary["case_count"]) is not int
            or not 1 <= summary["case_count"] <= 1000
        ):
            raise ValueError("operation summary evaluation dataset is invalid")
        _require_row_version(summary["row_version"])
    elif action_code in {"knowledge.eval_queued", "knowledge.eval_completed"}:
        expected = {"case_count", "passed", "tier"}
        _require_exact_keys(summary, expected)
        if (
            summary["tier"] not in {"smoke", "mvp_uat", "formal_release"}
            or type(summary["case_count"]) is not int
            or not 1 <= summary["case_count"] <= 1000
            or type(summary["passed"]) is not bool
            or (action_code == "knowledge.eval_queued" and summary["passed"])
        ):
            raise ValueError("operation summary evaluation run is invalid")
    elif action_code == "knowledge.qa_queried":
        _require_exact_keys(summary, {"retrieved_count", "status"})
        if (
            summary["status"] not in {"answered", "refused", "service_degraded"}
            or type(summary["retrieved_count"]) is not int
            or not 0 <= summary["retrieved_count"] <= 100
        ):
            raise ValueError("operation summary qa query is invalid")
    elif action_code == "knowledge.qa_feedback":
        _require_exact_keys(summary, {"rating"})
        if summary["rating"] not in {"helpful", "unhelpful"}:
            raise ValueError("operation summary qa feedback is invalid")
    elif action_code == "audits.task_created":
        _require_exact_keys(summary, {"execution_id", "invoice_count", "status"})
        _require_uuid_text(summary["execution_id"])
        if (
            type(summary["invoice_count"]) is not int
            or not 1 <= summary["invoice_count"] <= 100
            or summary["status"] != "queued"
        ):
            raise ValueError("operation summary audit task creation is invalid")
    elif action_code == "audits.execution_reaudit_queued":
        _require_exact_keys(summary, {"status", "version_no"})
        if (
            summary["status"] != "queued"
            or type(summary["version_no"]) is not int
            or summary["version_no"] < 2
        ):
            raise ValueError("operation summary audit re-execution is invalid")
    elif action_code == "audits.execution_retry_queued":
        _require_exact_keys(summary, {"attempt_no", "scheduled_attempt_no", "status"})
        if (
            summary["status"] != "queued"
            or type(summary["attempt_no"]) is not int
            or type(summary["scheduled_attempt_no"]) is not int
            or summary["attempt_no"] < 1
            or summary["scheduled_attempt_no"] != summary["attempt_no"] + 1
        ):
            raise ValueError("operation summary audit retry is invalid")
    elif action_code == "audits.execution_evaluated":
        _require_exact_keys(
            summary,
            {"retrieval_status", "risk_count", "rule_count", "status"},
        )
        if (
            summary["retrieval_status"] not in {"not_required", "succeeded", "degraded"}
            or type(summary["risk_count"]) is not int
            or not 0 <= summary["risk_count"] <= 15
            or summary["rule_count"] != 15
            or summary["status"] != "pending_finance_review"
        ):
            raise ValueError("operation summary audit evaluation is invalid")
    elif action_code in {"audits.risk_reviewed", "audits.high_risk_reviewed"}:
        _require_exact_keys(summary, {"effective_level", "review_status", "row_version"})
        if summary["effective_level"] not in {"none", "notice", "low", "medium", "high"} or summary[
            "review_status"
        ] not in {"confirmed", "dismissed", "adjusted"}:
            raise ValueError("operation summary audit risk review is invalid")
        _require_row_version(summary["row_version"])
    elif action_code == "audits.execution_cancelled":
        _require_exact_keys(summary, {"status"})
        if summary["status"] != "cancelled":
            raise ValueError("operation summary audit cancellation is invalid")
    elif action_code in {
        "audits.finance_review_submit",
        "audits.finance_review_return",
        "audits.audit_review_complete",
        "audits.audit_review_return",
    }:
        _require_exact_keys(summary, {"status"})
        expected_statuses = {
            "audits.finance_review_submit": {"completed", "pending_audit_review"},
            "audits.finance_review_return": {"returned_for_correction"},
            "audits.audit_review_complete": {"completed"},
            "audits.audit_review_return": {"returned_for_correction"},
        }[action_code]
        if summary["status"] not in expected_statuses:
            raise ValueError("operation summary audit decision is invalid")
    elif action_code == "reports.generation_queued":
        _require_exact_keys(summary, {"payload_sha256", "report_version", "status"})
        if (
            summary["status"] != "queued"
            or type(summary["report_version"]) is not int
            or summary["report_version"] <= 0
            or type(summary["payload_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", summary["payload_sha256"]) is None
        ):
            raise ValueError("operation summary report queue is invalid")
    elif action_code == "reports.generated":
        _require_exact_keys(
            summary,
            {"pdf_sha256", "pdf_size_bytes", "status", "xlsx_sha256", "xlsx_size_bytes"},
        )
        if (
            summary["status"] != "ready"
            or type(summary["pdf_size_bytes"]) is not int
            or not 1 <= summary["pdf_size_bytes"] <= 8 * 1024 * 1024
            or type(summary["xlsx_size_bytes"]) is not int
            or not 1 <= summary["xlsx_size_bytes"] <= 2 * 1024 * 1024
            or any(
                type(summary[name]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", cast(str, summary[name])) is None
                for name in ("pdf_sha256", "xlsx_sha256")
            )
        ):
            raise ValueError("operation summary generated report is invalid")
    elif action_code == "reports.generation_failed":
        _require_exact_keys(summary, {"failure_code", "status"})
        if (
            summary["status"] != "failed"
            or type(summary["failure_code"]) is not str
            or re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", summary["failure_code"]) is None
        ):
            raise ValueError("operation summary report failure is invalid")
    elif action_code in {"reports.pdf_previewed", "reports.xlsx_downloaded"}:
        _require_exact_keys(summary, {"format", "is_outdated", "status"})
        expected_format = "pdf" if action_code == "reports.pdf_previewed" else "xlsx"
        if (
            summary["format"] != expected_format
            or type(summary["is_outdated"]) is not bool
            or summary["status"] not in {"ready", "outdated", "archived"}
            or (summary["status"] == "ready" and summary["is_outdated"])
            or (summary["status"] == "outdated" and not summary["is_outdated"])
        ):
            raise ValueError("operation summary report access is invalid")
    else:  # pragma: no cover - action registry membership is checked first
        raise ValueError("operation action is not registered")

    try:
        encoded = json.dumps(
            dict(summary),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("operation summary is not safe JSON") from exc
    if len(encoded) > 16_384:
        raise ValueError("operation summary exceeds 16 KiB")


class OperationLogRepository:
    """只接受注册 action 与严格脱敏摘要的追加写入口。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        organization_id: UUID | None,
        actor_kind: str,
        actor_id: UUID | None,
        action_code: str,
        outcome: str,
        resource_type: str | None,
        resource_id: UUID | None,
        trace_id: UUID,
        change_summary: Mapping[str, object],
    ) -> OperationLog:
        if actor_kind not in OPERATION_LOG_ACTOR_KINDS:
            raise ValueError("operation actor kind is invalid")
        if actor_kind == "user":
            if type(organization_id) is not UUID or type(actor_id) is not UUID:
                raise ValueError("user operation actor requires organization and actor ids")
        elif actor_id is not None:
            raise ValueError("anonymous and system operation actors cannot have actor ids")
        if organization_id is not None and type(organization_id) is not UUID:
            raise ValueError("operation organization id is invalid")
        if action_code not in OPERATION_LOG_ACTION_CODES:
            raise ValueError("operation action is not registered")
        if outcome not in OPERATION_LOG_OUTCOMES:
            raise ValueError("operation outcome is invalid")
        if (resource_type is None) != (resource_id is None):
            raise ValueError("operation resource type and id must be provided together")
        if resource_type is not None and (
            type(resource_type) is not str
            or _RESOURCE_TYPE_PATTERN.fullmatch(resource_type) is None
        ):
            raise ValueError("operation resource type is invalid")
        if resource_id is not None and type(resource_id) is not UUID:
            raise ValueError("operation resource id is invalid")
        if type(trace_id) is not UUID:
            raise ValueError("operation trace id is invalid")
        if type(change_summary) is not dict:
            raise ValueError("operation summary must be an exact dict")
        _validate_change_summary(action_code, change_summary)

        record = OperationLog(
            organization_id=organization_id,
            actor_kind=actor_kind,
            actor_id=actor_id,
            action_code=action_code,
            outcome=outcome,
            resource_type=resource_type,
            resource_id=resource_id,
            trace_id=trace_id,
            change_summary_json=dict(change_summary),
        )
        self._session.add(record)
        return record


__all__ = ["OperationLogRepository"]
