"""已完成审核执行到正式报告 Job/Outbox 的同事务编排。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from app.audit.offline_preview import RulePreviewDisposition
from app.audit.risk_summary import RiskLevel, RiskReviewStatus
from app.audit.rule_predicates import RuleExecutionStatus
from app.audit.snapshot import AuditSnapshotFacts, snapshot_sha256
from app.models.audit import AuditReport
from app.models.reliability import (
    JOB_LEASE_POLICY_HASH,
    JOB_LEASE_POLICY_VERSION,
    JOB_RETRY_POLICY_HASH,
    JOB_RETRY_POLICY_VERSION,
    AsyncJob,
    OutboxEvent,
)
from app.reports.formal_payload import (
    FormalCitation,
    FormalReportContext,
    FormalRiskFact,
    FormalRuleFact,
    build_formal_report_payload,
    formal_report_payload_json_bytes,
)
from app.reports.report_payload import ReportMetadata, ReportPayload
from app.repositories.audit_runtime import AuditRuntimeRepository, LockedAuditCluster
from app.workers.report_handler_registry import REPORT_INPUT_SCHEMA_VERSION, load_report_handler

FORMAL_REPORT_GENERATOR_VERSION = "formal-report-generator-v2"


class FormalReportProjectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FormalReportProjection:
    payload: ReportPayload
    context: FormalReportContext
    payload_sha256: str


def _json_text(value: dict[str, object] | None) -> str | None:
    if value is None:
        return None
    projected = value.get("value")
    return projected if type(projected) is str else None


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _degraded_reasons(snapshot: AuditSnapshotFacts) -> tuple[str, ...]:
    reasons = ["AI_DECISION_DISABLED"]
    if snapshot.requires_policy_citation and not snapshot.retrieval_completed_successfully:
        reasons.append("POLICY_RETRIEVAL_UNAVAILABLE")
    elif snapshot.requires_policy_citation and not snapshot.has_applicable_policy_citation:
        reasons.append("POLICY_CITATION_UNAVAILABLE")
    return tuple(reasons)


def build_formal_report_projection(
    cluster: LockedAuditCluster,
    *,
    report_id: UUID,
    created_at: datetime,
) -> FormalReportProjection:
    """从同一锁定审核簇重建正式载荷和不可变摘要。"""

    execution = cluster.execution
    snapshot_model = cluster.snapshot
    if (
        execution.status != "completed"
        or snapshot_model is None
        or execution.finance_reviewer_id is None
        or execution.finance_reviewed_at is None
        or len(cluster.rules) != 15
        or any(
            risk.review_status == "pending"
            or risk.actual_value is None
            or risk.expected_value is None
            or risk.reviewed_by is None
            or risk.reviewed_at is None
            or risk.review_reason is None
            for risk in cluster.risks
        )
    ):
        raise FormalReportProjectionError("completed audit facts are required")
    try:
        snapshot = AuditSnapshotFacts.model_validate(snapshot_model.facts_json)
        if (
            snapshot.execution_id != execution.id
            or snapshot.task_id != cluster.task.id
            or snapshot_model.facts_sha256 != execution.snapshot_sha256
            or snapshot_sha256(snapshot) != snapshot_model.facts_sha256
        ):
            raise ValueError
        rules = tuple(
            FormalRuleFact(
                rule_code=rule.rule_code,
                status=RuleExecutionStatus(rule.status),
                disposition=RulePreviewDisposition(str(rule.input_json.get("disposition"))),
                actual_value=_json_text(rule.actual_value_json),
                expected_value=_json_text(rule.expected_value_json),
                included_item_ids=tuple(rule.included_item_ids),
            )
            for rule in cluster.rules
        )
        risks = tuple(
            FormalRiskFact(
                risk_id=risk.id,
                rule_code=risk.rule_code,
                original_level=RiskLevel(risk.original_level),
                effective_level=RiskLevel(risk.effective_level),
                review_status=RiskReviewStatus(risk.review_status),
                actual_value=cast(str, risk.actual_value),
                expected_value=cast(str, risk.expected_value),
                reviewed_by=cast(UUID, risk.reviewed_by),
                reviewed_at=cast(datetime, risk.reviewed_at),
                review_reason=cast(str, risk.review_reason),
            )
            for risk in cluster.risks
        )
        citations = tuple(
            FormalCitation(
                risk_id=citation.risk_id,
                policy_document_id=citation.policy_document_id,
                markdown_version_id=citation.markdown_version_id,
                chunk_id=citation.chunk_id,
                index_version_id=citation.index_version_id,
                start_page_no=citation.start_page_no,
                end_page_no=citation.end_page_no,
                title_path=tuple(citation.title_path),
                quote=citation.quote,
                content_sha256=citation.content_sha256,
            )
            for citation in cluster.citations
        )
        context = FormalReportContext(
            task_id=cluster.task.id,
            task_no=cluster.task.task_no,
            task_name=cluster.task.name,
            execution_id=execution.id,
            execution_version=execution.version_no,
            baseline_date=execution.baseline_date,
            finance_reviewer_id=execution.finance_reviewer_id,
            finance_reviewed_at=execution.finance_reviewed_at,
            audit_reviewer_id=execution.audit_reviewer_id,
            audit_reviewed_at=execution.audit_reviewed_at,
            risks=risks,
            citations=citations,
        )
        reasons = _degraded_reasons(snapshot)
        payload = build_formal_report_payload(
            ReportMetadata(
                report_version_id=report_id,
                audit_version_id=execution.id,
                generated_at=created_at,
                is_outdated=False,
                is_degraded=bool(reasons),
                degraded_reasons=reasons,
            ),
            context,
            rules,
        )
        payload_hash = hashlib.sha256(
            formal_report_payload_json_bytes(payload, context)
        ).hexdigest()
    except (TypeError, ValueError):
        raise FormalReportProjectionError("formal report facts are invalid") from None
    return FormalReportProjection(payload, context, payload_hash)


def queue_formal_report(
    repository: AuditRuntimeRepository,
    cluster: LockedAuditCluster,
    *,
    actor_id: UUID,
    idempotency_record_id: UUID,
    trace_id: UUID,
    now: datetime,
) -> AuditReport:
    """在调用方事务内创建唯一报告版本、Job 与首次 Outbox。"""

    if cluster.execution.status != "completed":
        raise FormalReportProjectionError("audit execution is not completed")
    if any(report.status in {"queued", "generating", "ready"} for report in cluster.reports):
        raise FormalReportProjectionError("active report already exists")
    report_id = uuid4()
    report_version = max((report.report_version for report in cluster.reports), default=0) + 1
    projection = build_formal_report_projection(
        cluster,
        report_id=report_id,
        created_at=now,
    )
    handler = load_report_handler()
    input_json: dict[str, object] = {
        "report_id": str(report_id),
        "execution_id": str(cluster.execution.id),
        "payload_sha256": projection.payload_sha256,
    }
    handler.validate_input(input_json)
    job = AsyncJob(
        id=uuid4(),
        organization_id=cluster.execution.organization_id,
        job_type="report_generate",
        resource_type="audit_report",
        resource_id=report_id,
        status="queued",
        stage=None,
        attempt_no=0,
        max_attempts=handler.handler.max_attempts,
        current_attempt_start_step_code=handler.handler.steps[0].step_code,
        input_hash=hashlib.sha256(_canonical_json(input_json)).hexdigest(),
        input_json=input_json,
        input_schema_version=REPORT_INPUT_SCHEMA_VERSION,
        idempotency_record_id=idempotency_record_id,
        handler_registry_version=handler.registry_version,
        handler_registry_hash=handler.registry_hash,
        retry_policy_version=JOB_RETRY_POLICY_VERSION,
        retry_policy_hash=JOB_RETRY_POLICY_HASH,
        lease_policy_version=JOB_LEASE_POLICY_VERSION,
        lease_policy_hash=JOB_LEASE_POLICY_HASH,
        row_version=1,
        trace_id=trace_id,
        created_by=actor_id,
        created_at=now,
    )
    report = AuditReport(
        id=report_id,
        organization_id=cluster.execution.organization_id,
        audit_task_id=cluster.task.id,
        execution_id=cluster.execution.id,
        report_version=report_version,
        status="queued",
        payload_sha256=projection.payload_sha256,
        generator_version=FORMAL_REPORT_GENERATOR_VERSION,
        job_id=job.id,
        failure_code=None,
        row_version=1,
        created_by=actor_id,
        created_at=now,
        trace_id=trace_id,
    )
    outbox = OutboxEvent(
        id=uuid4(),
        aggregate_type="async_job",
        aggregate_id=job.id,
        event_id=uuid4(),
        event_type="job.dispatch.requested",
        event_version=1,
        event_sequence=1,
        payload_json={"job_id": str(job.id)},
        status="pending",
        attempt_count=0,
        trace_id=trace_id,
        created_at=now,
    )
    repository.add(job)
    # 两个模型未声明 ORM relationship，需先落库以满足 audit_reports.job_id 外键。
    repository.flush()
    repository.add(report)
    repository.add(outbox)
    repository.flush()
    return report


__all__ = [
    "FORMAL_REPORT_GENERATOR_VERSION",
    "FormalReportProjection",
    "FormalReportProjectionError",
    "build_formal_report_projection",
    "queue_formal_report",
]
