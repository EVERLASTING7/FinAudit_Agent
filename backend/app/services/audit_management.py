"""审核任务创建、冻结执行、人工复核、取消和重审用例。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID, uuid4

from pydantic import BaseModel, JsonValue
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.output_validation import RiskExplanationOutput
from app.ai.policy import canonicalize_jcs
from app.audit.snapshot import (
    AuditSnapshotFacts,
    SnapshotInvoiceFacts,
    snapshot_json_document,
    snapshot_sha256,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.models.audit import (
    AuditRisk,
    AuditTask,
    AuditTaskExecution,
    AuditTaskItem,
    AuditTaskSnapshot,
    RuleExecution,
)
from app.models.auth import Organization
from app.models.corrections import UserCorrection
from app.models.reliability import (
    JOB_LEASE_POLICY_HASH,
    JOB_LEASE_POLICY_VERSION,
    JOB_RETRY_POLICY_HASH,
    JOB_RETRY_POLICY_VERSION,
    AsyncJob,
    OutboxEvent,
)
from app.repositories.audit_runtime import (
    AuditRuleVersion,
    AuditRuntimeRepository,
    LockedAuditCluster,
)
from app.repositories.financial_read import FinancialReadRepository, InvoiceReadView
from app.repositories.operation_log import OperationLogRepository
from app.repositories.user_write import IdempotencyClaim
from app.schemas.audits import (
    AiArtifactStatus,
    AuditCancelRequest,
    AuditExecutionCreateRequest,
    AuditExecutionData,
    AuditExecutionMutationData,
    AuditExecutionStatus,
    AuditFinanceReviewRequest,
    AuditReviewDecisionRequest,
    AuditRiskData,
    AuditRiskExplanationCitationData,
    AuditRiskExplanationData,
    AuditRiskMutationData,
    AuditRiskReviewRequest,
    AuditRuleExecutionData,
    AuditTaskCreateRequest,
    AuditTaskData,
    AuditTaskDetailData,
    AuditTaskListData,
    AuditTaskMutationData,
    AuditTaskStatus,
    RiskLevel,
    RiskReviewStatus,
    RuleExecutionStatus,
)
from app.services.auth import AuthenticatedActor
from app.services.effective_contract_query import project_effective_contract
from app.services.report_queue import queue_formal_report
from app.workers.audit_handler_registry import AUDIT_INPUT_SCHEMA_VERSION, load_audit_handler

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_IDEMPOTENCY_TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class AuditTaskMutationResult:
    data: AuditTaskMutationData
    replayed: bool
    status_code: int


@dataclass(frozen=True, slots=True)
class AuditExecutionMutationResult:
    data: AuditExecutionMutationData
    replayed: bool


@dataclass(frozen=True, slots=True)
class AuditRiskMutationResult:
    data: AuditRiskMutationData
    replayed: bool


def _not_found() -> AppError:
    return AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )


def _conflict(code: str, message: str) -> AppError:
    return AppError(status_code=409, code=code, message=message)


def _validate_idempotency_key(value: str) -> None:
    if type(value) is not str or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": "header.Idempotency-Key", "reason": "invalid"}],
        )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _request_hash(method: str, path: str, body: dict[str, object]) -> str:
    return hashlib.sha256(
        _canonical_json({"body": body, "method": method, "path": path})
    ).hexdigest()


def _project_task(task: AuditTask) -> AuditTaskData:
    return AuditTaskData(
        id=task.id,
        task_no=task.task_no,
        name=task.name,
        description=task.description,
        owner_id=task.owner_id,
        current_execution_id=task.current_execution_id,
        status=cast(AuditTaskStatus, task.status),
        row_version=str(task.row_version),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _project_execution(execution: AuditTaskExecution) -> AuditExecutionData:
    return AuditExecutionData(
        id=execution.id,
        audit_task_id=execution.audit_task_id,
        version_no=execution.version_no,
        baseline_date=execution.baseline_date,
        status=cast(AuditExecutionStatus, execution.status),
        snapshot_sha256=execution.snapshot_sha256,
        job_id=execution.job_id,
        finance_reviewer_id=execution.finance_reviewer_id,
        finance_reviewed_at=execution.finance_reviewed_at,
        audit_reviewer_id=execution.audit_reviewer_id,
        audit_reviewed_at=execution.audit_reviewed_at,
        retryable=execution.retryable,
        failure_code=execution.failure_code,
        cancel_reason=execution.cancel_reason,
        return_reason=execution.return_reason,
        row_version=str(execution.row_version),
        created_at=execution.created_at,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        outdated_at=execution.outdated_at,
    )


def _json_text(value: dict[str, object] | None) -> str | None:
    if value is None:
        return None
    projected = value.get("value")
    return projected if type(projected) is str else None


def _project_rule(rule: RuleExecution) -> AuditRuleExecutionData:
    return AuditRuleExecutionData(
        id=rule.id,
        rule_code=rule.rule_code,
        status=cast(RuleExecutionStatus, rule.status),
        actual_value=_json_text(rule.actual_value_json),
        expected_value=_json_text(rule.expected_value_json),
        applicability_reason=rule.applicability_reason,
        included_item_ids=tuple(rule.included_item_ids),
        excluded_item_ids=tuple(rule.excluded_item_ids),
    )


def _project_risk(risk: AuditRisk) -> AuditRiskData:
    explanation = None
    if risk.ai_explanation_status == "succeeded":
        if risk.ai_explanation_json is None:
            raise RuntimeError("succeeded AI explanation is missing")
        parsed = RiskExplanationOutput.model_validate_json(
            canonicalize_jcs(risk.ai_explanation_json)
        )
        explanation = AuditRiskExplanationData(
            summary=parsed.summary,
            reasoning_summary=parsed.reasoning_summary,
            business_impact=parsed.business_impact,
            recommended_action=parsed.recommended_action,
            citations=tuple(
                AuditRiskExplanationCitationData(
                    candidate_id=UUID(citation.candidate_id),
                    policy_document_id=UUID(citation.policy_document_id),
                    chunk_id=UUID(citation.chunk_id),
                    quote=citation.quote,
                )
                for citation in parsed.citations
            ),
            evidence_sufficient=parsed.evidence_sufficient,
            warnings=parsed.warnings,
        )
    return AuditRiskData(
        id=risk.id,
        rule_code=risk.rule_code,
        title=risk.title,
        original_level=cast(RiskLevel, risk.original_level),
        effective_level=cast(RiskLevel, risk.effective_level),
        review_status=cast(RiskReviewStatus, risk.review_status),
        actual_value=risk.actual_value,
        expected_value=risk.expected_value,
        review_reason=risk.review_reason,
        reviewed_by=risk.reviewed_by,
        reviewed_at=risk.reviewed_at,
        row_version=str(risk.row_version),
        ai_explanation_status=cast(AiArtifactStatus, risk.ai_explanation_status),
        ai_explanation=explanation,
    )


def _effective_value(fields: dict[str, JsonValue], name: str) -> JsonValue:
    try:
        return fields[name]
    except KeyError:
        raise RuntimeError(f"effective contract field is missing: {name}") from None


def _optional_string(value: JsonValue) -> str | None:
    if value is None or type(value) is str:
        return value
    raise RuntimeError("effective contract string has an invalid type")


def _optional_decimal(value: JsonValue) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not str:
        raise RuntimeError("effective contract number has an invalid type")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise RuntimeError("effective contract number is invalid") from None
    if not parsed.is_finite():
        raise RuntimeError("effective contract number is invalid")
    return parsed


def _optional_date(value: JsonValue) -> date | None:
    if value is None:
        return None
    if type(value) is not str:
        raise RuntimeError("effective contract date has an invalid type")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise RuntimeError("effective contract date is invalid") from None
    if parsed.isoformat() != value:
        raise RuntimeError("effective contract date is invalid")
    return parsed


def _line_net_amount(invoice: InvoiceReadView) -> Decimal | None:
    if not invoice.items or any(item.amount_excluding_tax is None for item in invoice.items):
        return None
    return sum(
        (item.amount_excluding_tax for item in invoice.items if item.amount_excluding_tax),
        Decimal("0"),
    )


def _new_audit_job(
    *,
    organization_id: UUID,
    actor_id: UUID,
    trace_id: UUID,
    execution_id: UUID,
    snapshot_id: UUID,
    snapshot_hash: str,
    idempotency_record_id: UUID,
    now: datetime,
) -> tuple[AsyncJob, OutboxEvent]:
    handler = load_audit_handler()
    input_json: dict[str, object] = {
        "execution_id": str(execution_id),
        "snapshot_id": str(snapshot_id),
        "snapshot_sha256": snapshot_hash,
    }
    handler.validate_input(input_json)
    job = AsyncJob(
        id=uuid4(),
        organization_id=organization_id,
        job_type="audit_execute",
        resource_type="audit_task_execution",
        resource_id=execution_id,
        status="queued",
        stage=None,
        attempt_no=0,
        max_attempts=handler.handler.max_attempts,
        current_attempt_start_step_code=handler.handler.steps[0].step_code,
        input_hash=hashlib.sha256(_canonical_json(input_json)).hexdigest(),
        input_json=input_json,
        input_schema_version=AUDIT_INPUT_SCHEMA_VERSION,
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
    return job, outbox


class AuditManagementService:
    def __init__(self, session_factory: sessionmaker[Session], settings: Settings) -> None:
        self._session_factory = session_factory
        self._application_release = settings.app_version

    def list_tasks(
        self,
        organization_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> AuditTaskListData:
        cursor_id: UUID | None = None
        if cursor is not None:
            try:
                cursor_id = UUID(cursor)
            except ValueError:
                raise AppError(
                    status_code=422,
                    code="VALIDATION_ERROR",
                    message="请求参数不符合约束",
                    details=[{"field": "query.cursor", "reason": "invalid"}],
                ) from None
            if str(cursor_id) != cursor:
                raise AppError(
                    status_code=422,
                    code="VALIDATION_ERROR",
                    message="请求参数不符合约束",
                    details=[{"field": "query.cursor", "reason": "invalid"}],
                )
        with self._session_factory() as session:
            rows, has_more = AuditRuntimeRepository(session).list_tasks(
                organization_id,
                page_size=page_size,
                cursor_id=cursor_id,
            )
        return AuditTaskListData(
            items=tuple(_project_task(row) for row in rows),
            page_size=page_size,
            next_cursor=str(rows[-1].id) if has_more and rows else None,
        )

    def get_task(self, organization_id: UUID, task_id: UUID) -> AuditTaskDetailData:
        with self._session_factory() as session:
            repository = AuditRuntimeRepository(session)
            task = repository.get_task(organization_id, task_id)
            if task is None or task.current_execution_id is None:
                raise _not_found()
            execution = repository.get_execution(organization_id, task.current_execution_id)
            if execution is None:
                raise RuntimeError("audit task current execution is missing")
            rules = repository.execution_rules(execution.id)
            risks = repository.execution_risks(execution.id)
            return AuditTaskDetailData(
                task=_project_task(task),
                execution=_project_execution(execution),
                rules=tuple(_project_rule(rule) for rule in rules),
                risks=tuple(_project_risk(risk) for risk in risks),
            )

    def get_execution(
        self, organization_id: UUID, execution_id: UUID
    ) -> AuditExecutionMutationData:
        with self._session_factory() as session:
            execution = AuditRuntimeRepository(session).get_execution(organization_id, execution_id)
            if execution is None:
                raise _not_found()
            return AuditExecutionMutationData(execution=_project_execution(execution))

    def create_task(
        self,
        actor: AuthenticatedActor,
        payload: AuditTaskCreateRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> AuditTaskMutationResult:
        path = "/api/v1/audit-tasks"
        digest = self._write_digest("POST", path, payload, idempotency_key)
        try:
            with self._session_factory.begin() as session:
                repository, claim, now, organization = self._claim(
                    session, actor, idempotency_key, "POST", path, digest
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._replay_task(claim)
                task = AuditTask(
                    id=uuid4(),
                    organization_id=actor.organization_id,
                    task_no=payload.task_no,
                    name=payload.name,
                    owner_id=actor.user_id,
                    current_execution_id=None,
                    status="open",
                    description=payload.description,
                    row_version=1,
                    created_at=now,
                    created_by=actor.user_id,
                    updated_at=now,
                    updated_by=actor.user_id,
                    deleted_at=None,
                    deleted_by=None,
                    delete_reason=None,
                )
                repository.add(task)
                repository.flush()
                item_models: list[object] = []
                if payload.contract_id is not None:
                    item_models.append(
                        AuditTaskItem(
                            id=uuid4(),
                            organization_id=actor.organization_id,
                            audit_task_id=task.id,
                            item_type="contract",
                            contract_id=payload.contract_id,
                            invoice_id=None,
                            created_by=actor.user_id,
                            created_at=now,
                        )
                    )
                item_models.extend(
                    AuditTaskItem(
                        id=uuid4(),
                        organization_id=actor.organization_id,
                        audit_task_id=task.id,
                        item_type="invoice",
                        contract_id=None,
                        invoice_id=invoice_id,
                        created_by=actor.user_id,
                        created_at=now,
                    )
                    for invoice_id in payload.invoice_ids
                )
                repository.add_all(tuple(item_models))
                repository.flush()
                execution = self._create_execution_model(
                    task,
                    version_no=1,
                    baseline_date=payload.baseline_date,
                    actor=actor,
                    trace_id=trace_id,
                    now=now,
                )
                repository.add(execution)
                repository.flush()
                self._freeze_and_queue(
                    session,
                    repository,
                    organization.tax_number,
                    task,
                    execution,
                    payload.contract_id,
                    payload.invoice_ids,
                    actor,
                    claim,
                    trace_id,
                    now,
                )
                data = AuditTaskMutationData(
                    task=_project_task(task), execution=_project_execution(execution)
                )
                self._append_log(
                    session,
                    actor,
                    "audits.task_created",
                    "audit_task",
                    task.id,
                    trace_id,
                    {
                        "execution_id": str(execution.id),
                        "invoice_count": len(payload.invoice_ids),
                        "status": execution.status,
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_status=202,
                    response_body=data.model_dump(mode="json"),
                    resource_type="audit_task",
                    resource_id=task.id,
                )
                return AuditTaskMutationResult(data, False, 202)
        except IntegrityError as error:
            raise self._integrity_error(error) from None

    def create_execution(
        self,
        actor: AuthenticatedActor,
        task_id: UUID,
        payload: AuditExecutionCreateRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> AuditTaskMutationResult:
        path = f"/api/v1/audit-tasks/{task_id}/executions"
        digest = self._write_digest("POST", path, payload, idempotency_key)
        try:
            with self._session_factory.begin() as session:
                repository, claim, now, organization = self._claim(
                    session, actor, idempotency_key, "POST", path, digest
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._replay_task(claim)
                task = repository.lock_task(actor.organization_id, task_id)
                if task is None:
                    raise _not_found()
                if task.row_version != int(payload.task_row_version):
                    raise _conflict("ROW_VERSION_CONFLICT", "审核任务版本已变化")
                if task.status == "archived":
                    raise _conflict("AUDIT_TASK_STATE_CONFLICT", "归档审核任务不能重审")
                items = repository.task_items(task.id)
                contract_ids = tuple(item.contract_id for item in items if item.contract_id)
                invoice_ids = tuple(
                    sorted(
                        (item.invoice_id for item in items if item.invoice_id),
                        key=lambda value: value.bytes,
                    )
                )
                if len(contract_ids) > 1 or not invoice_ids:
                    raise RuntimeError("audit task items violate the frozen contract")
                if task.current_execution_id is not None:
                    current = repository.get_execution(
                        actor.organization_id, task.current_execution_id
                    )
                    if current is None:
                        raise RuntimeError("audit task current execution is missing")
                    if current.status not in {
                        "completed",
                        "failed",
                        "returned_for_correction",
                        "cancelled",
                        "outdated",
                    }:
                        raise _conflict(
                            "AUDIT_EXECUTION_ACTIVE",
                            "当前审核执行尚未进入可重审状态",
                        )
                    if current.status in {"completed", "failed"}:
                        current.status = "outdated"
                        current.outdated_at = now
                        current.finished_at = now
                        current.row_version += 1
                        repository.flush()
                execution = self._create_execution_model(
                    task,
                    version_no=repository.next_execution_version(task.id),
                    baseline_date=payload.baseline_date,
                    actor=actor,
                    trace_id=trace_id,
                    now=now,
                )
                repository.add(execution)
                repository.flush()
                self._freeze_and_queue(
                    session,
                    repository,
                    organization.tax_number,
                    task,
                    execution,
                    contract_ids[0] if contract_ids else None,
                    invoice_ids,
                    actor,
                    claim,
                    trace_id,
                    now,
                )
                data = AuditTaskMutationData(
                    task=_project_task(task), execution=_project_execution(execution)
                )
                self._append_log(
                    session,
                    actor,
                    "audits.execution_reaudit_queued",
                    "audit_task_execution",
                    execution.id,
                    trace_id,
                    {
                        "version_no": execution.version_no,
                        "status": execution.status,
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_status=202,
                    response_body=data.model_dump(mode="json"),
                    resource_type="audit_task_execution",
                    resource_id=execution.id,
                )
                return AuditTaskMutationResult(data, False, 202)
        except IntegrityError as error:
            raise self._integrity_error(error) from None

    def review_risk(
        self,
        actor: AuthenticatedActor,
        risk_id: UUID,
        payload: AuditRiskReviewRequest,
        idempotency_key: str,
        trace_id: UUID,
        *,
        high_risk: bool,
    ) -> AuditRiskMutationResult:
        lane = "high" if high_risk else "non-high"
        path = f"/api/v1/audit-risks/{risk_id}/reviews/{lane}"
        digest = self._write_digest("POST", path, payload, idempotency_key)
        with self._session_factory.begin() as session:
            repository, claim, now, _organization = self._claim(
                session, actor, idempotency_key, "POST", path, digest
            )
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return self._replay_risk(claim)
            execution_id = session.scalar(
                select(AuditRisk.execution_id).where(
                    AuditRisk.id == risk_id,
                    AuditRisk.organization_id == actor.organization_id,
                )
            )
            if type(execution_id) is not UUID:
                raise _not_found()
            cluster = repository.lock_cluster(actor.organization_id, execution_id)
            if cluster is None:
                raise _not_found()
            risk = next((item for item in cluster.risks if item.id == risk_id), None)
            if risk is None:
                raise _not_found()
            self._validate_risk_review_lane(cluster, risk, actor, high_risk)
            if risk.row_version != int(payload.row_version):
                raise _conflict("ROW_VERSION_CONFLICT", "风险版本已变化")
            before = self._risk_review_snapshot(risk)
            effective_level = (
                risk.effective_level if payload.effective_level is None else payload.effective_level
            )
            if not high_risk and effective_level == "high":
                raise _conflict("HIGH_RISK_REVIEW_REQUIRED", "财务复核不能产生或处理高风险")
            if payload.decision == "adjusted" and effective_level == risk.original_level:
                raise _conflict("RISK_LEVEL_UNCHANGED", "调整后的等级必须不同于原始等级")
            risk.effective_level = effective_level
            risk.review_status = payload.decision
            risk.review_reason = payload.reason
            risk.reviewed_by = actor.user_id
            risk.reviewed_at = now
            risk.row_version += 1
            correction = UserCorrection(
                id=uuid4(),
                organization_id=actor.organization_id,
                correction_type="audit_risk",
                object_type="audit_risk",
                object_id=risk.id,
                field_path="review",
                before_value_json=before,
                after_value_json=self._risk_review_snapshot(risk),
                reason=payload.reason,
                actor_id=actor.user_id,
                actor_role_code="audit_reviewer" if high_risk else "finance_reviewer",
                related_execution_id=cluster.execution.id,
                caused_outdated=False,
                created_at=now,
                trace_id=trace_id,
            )
            repository.add(correction)
            repository.flush()
            data = AuditRiskMutationData(risk=_project_risk(risk))
            self._append_log(
                session,
                actor,
                "audits.high_risk_reviewed" if high_risk else "audits.risk_reviewed",
                "audit_risk",
                risk.id,
                trace_id,
                {
                    "effective_level": risk.effective_level,
                    "review_status": risk.review_status,
                    "row_version": str(risk.row_version),
                },
            )
            repository.complete_idempotency(
                claim,
                response_status=200,
                response_body=data.model_dump(mode="json"),
                resource_type="audit_risk",
                resource_id=risk.id,
            )
            return AuditRiskMutationResult(data, False)

    def finance_review(
        self,
        actor: AuthenticatedActor,
        execution_id: UUID,
        payload: AuditFinanceReviewRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> AuditExecutionMutationResult:
        return self._execution_decision(
            actor,
            execution_id,
            payload,
            idempotency_key,
            trace_id,
            lane="finance",
        )

    def audit_review(
        self,
        actor: AuthenticatedActor,
        execution_id: UUID,
        payload: AuditReviewDecisionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> AuditExecutionMutationResult:
        return self._execution_decision(
            actor,
            execution_id,
            payload,
            idempotency_key,
            trace_id,
            lane="audit",
        )

    def cancel_execution(
        self,
        actor: AuthenticatedActor,
        execution_id: UUID,
        payload: AuditCancelRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> AuditExecutionMutationResult:
        path = f"/api/v1/audit-executions/{execution_id}/cancel"
        digest = self._write_digest("POST", path, payload, idempotency_key)
        with self._session_factory.begin() as session:
            repository, claim, now, _organization = self._claim(
                session, actor, idempotency_key, "POST", path, digest
            )
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return self._replay_execution(claim)
            cluster = repository.lock_cluster(actor.organization_id, execution_id)
            if cluster is None:
                raise _not_found()
            execution = cluster.execution
            if execution.row_version != int(payload.row_version):
                raise _conflict("ROW_VERSION_CONFLICT", "审核执行版本已变化")
            if execution.status not in {
                "draft",
                "validating",
                "queued",
                "running",
                "pending_finance_review",
                "pending_audit_review",
            }:
                raise _conflict("AUDIT_EXECUTION_STATE_CONFLICT", "当前审核执行不可取消")
            execution.status = "cancelled"
            execution.cancel_reason = payload.reason
            execution.finished_at = now
            execution.retryable = False
            execution.row_version += 1
            job = repository.job_for_execution(execution.id)
            if job is not None and job.status == "queued":
                job.status = "cancelled"
                job.finished_at = now
                job.error_code = "JOB_CANCELLED"
                job.error_message = None
                job.row_version += 1
            elif job is not None and job.status == "running":
                job.status = "cancel_requested"
                job.row_version += 1
            repository.flush()
            data = AuditExecutionMutationData(execution=_project_execution(execution))
            self._append_log(
                session,
                actor,
                "audits.execution_cancelled",
                "audit_task_execution",
                execution.id,
                trace_id,
                {"status": execution.status},
            )
            repository.complete_idempotency(
                claim,
                response_status=200,
                response_body=data.model_dump(mode="json"),
                resource_type="audit_task_execution",
                resource_id=execution.id,
            )
            return AuditExecutionMutationResult(data, False)

    def _execution_decision(
        self,
        actor: AuthenticatedActor,
        execution_id: UUID,
        payload: AuditFinanceReviewRequest | AuditReviewDecisionRequest,
        idempotency_key: str,
        trace_id: UUID,
        *,
        lane: str,
    ) -> AuditExecutionMutationResult:
        path = f"/api/v1/audit-executions/{execution_id}/{lane}-review"
        digest = self._write_digest("POST", path, payload, idempotency_key)
        with self._session_factory.begin() as session:
            repository, claim, now, _organization = self._claim(
                session, actor, idempotency_key, "POST", path, digest
            )
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return self._replay_execution(claim)
            cluster = repository.lock_cluster(actor.organization_id, execution_id)
            if cluster is None:
                raise _not_found()
            execution = cluster.execution
            if execution.row_version != int(payload.row_version):
                raise _conflict("ROW_VERSION_CONFLICT", "审核执行版本已变化")
            expected_status = (
                "pending_finance_review" if lane == "finance" else "pending_audit_review"
            )
            if execution.status != expected_status:
                raise _conflict("AUDIT_EXECUTION_STATE_CONFLICT", "当前审核执行不在该复核阶段")
            pending_non_high = tuple(
                risk
                for risk in cluster.risks
                if risk.effective_level != "high" and risk.review_status == "pending"
            )
            pending_high = tuple(
                risk
                for risk in cluster.risks
                if risk.effective_level == "high" and risk.review_status == "pending"
            )
            if lane == "finance":
                if pending_non_high:
                    raise _conflict("NON_HIGH_RISKS_PENDING", "仍有非高风险未完成财务复核")
                execution.finance_reviewer_id = actor.user_id
                execution.finance_reviewed_at = now
                if payload.decision == "return":
                    execution.status = "returned_for_correction"
                    execution.return_reason = payload.reason
                    execution.finished_at = now
                elif pending_high:
                    execution.status = "pending_audit_review"
                else:
                    execution.status = "completed"
                    execution.finished_at = now
            else:
                if execution.finance_reviewer_id == actor.user_id:
                    raise _conflict(
                        "REVIEWER_SEPARATION_REQUIRED",
                        "财务初审人员不能复核同一执行的高风险",
                    )
                execution.audit_reviewer_id = actor.user_id
                execution.audit_reviewed_at = now
                if payload.decision == "return":
                    execution.status = "returned_for_correction"
                    execution.return_reason = payload.reason
                    execution.finished_at = now
                else:
                    if pending_high or any(
                        risk.review_status == "pending" for risk in cluster.risks
                    ):
                        raise _conflict("RISKS_PENDING", "仍有风险未完成复核")
                    execution.status = "completed"
                    execution.finished_at = now
            execution.row_version += 1
            repository.flush()
            if (
                execution.status == "completed"
                and cluster.task.current_execution_id == execution.id
            ):
                cluster.task.status = "completed"
                cluster.task.updated_by = actor.user_id
                cluster.task.updated_at = now
                cluster.task.row_version += 1
                repository.flush()
                report = queue_formal_report(
                    repository,
                    cluster,
                    actor_id=actor.user_id,
                    idempotency_record_id=claim.record.id,
                    trace_id=trace_id,
                    now=now,
                )
                self._append_log(
                    session,
                    actor,
                    "reports.generation_queued",
                    "audit_report",
                    report.id,
                    trace_id,
                    {
                        "payload_sha256": report.payload_sha256,
                        "report_version": report.report_version,
                        "status": report.status,
                    },
                )
            data = AuditExecutionMutationData(execution=_project_execution(execution))
            self._append_log(
                session,
                actor,
                f"audits.{lane}_review_{payload.decision}",
                "audit_task_execution",
                execution.id,
                trace_id,
                {"status": execution.status},
            )
            repository.complete_idempotency(
                claim,
                response_status=200,
                response_body=data.model_dump(mode="json"),
                resource_type="audit_task_execution",
                resource_id=execution.id,
            )
            return AuditExecutionMutationResult(data, False)

    def _freeze_and_queue(
        self,
        session: Session,
        repository: AuditRuntimeRepository,
        organization_tax_number: str,
        task: AuditTask,
        execution: AuditTaskExecution,
        contract_id: UUID | None,
        invoice_ids: tuple[UUID, ...],
        actor: AuthenticatedActor,
        claim: IdempotencyClaim,
        trace_id: UUID,
        now: datetime,
    ) -> None:
        execution.status = "validating"
        execution.row_version += 1
        repository.flush()
        if not repository.lock_financial_inputs(
            actor.organization_id,
            contract_id=contract_id,
            invoice_ids=invoice_ids,
        ):
            raise _not_found()
        financial = FinancialReadRepository(session)
        invoices = tuple(
            financial.read_invoice(actor.organization_id, invoice_id) for invoice_id in invoice_ids
        )
        if any(invoice is None for invoice in invoices):
            raise _not_found()
        invoice_views = cast(tuple[InvoiceReadView, ...], invoices)
        if any(
            invoice.confirmation_status != "confirmed"
            or invoice.status not in {"confirmed", "archived"}
            for invoice in invoice_views
        ):
            raise _conflict(
                "AUDIT_FACTS_UNCONFIRMED",
                "发票核心事实未确认或已失效，不能开始审核",
            )
        rule_versions = repository.current_rule_versions()
        if len(rule_versions) != 15:
            raise _conflict("AUDIT_RULE_CATALOG_UNAVAILABLE", "完整审核规则目录尚未发布")
        snapshot = self._build_snapshot(
            repository,
            financial,
            organization_tax_number,
            task,
            execution,
            contract_id,
            invoice_views,
            rule_versions,
        )
        snapshot_hash = snapshot_sha256(snapshot)
        snapshot_model = AuditTaskSnapshot(
            id=uuid4(),
            organization_id=actor.organization_id,
            audit_task_id=task.id,
            execution_id=execution.id,
            schema_version=1,
            baseline_date=execution.baseline_date,
            facts_json=snapshot_json_document(snapshot),
            facts_sha256=snapshot_hash,
            rule_version_ids=[rule.id for rule in rule_versions],
            index_version_id=None,
            application_release=rule_versions[0].application_release,
            created_by=actor.user_id,
            created_at=now,
            trace_id=trace_id,
        )
        repository.add(snapshot_model)
        repository.flush()
        job, outbox = _new_audit_job(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            trace_id=trace_id,
            execution_id=execution.id,
            snapshot_id=snapshot_model.id,
            snapshot_hash=snapshot_hash,
            idempotency_record_id=claim.record.id,
            now=now,
        )
        repository.add(job)
        repository.add(outbox)
        repository.flush()
        execution.snapshot_sha256 = snapshot_hash
        execution.job_id = job.id
        execution.status = "queued"
        execution.row_version += 1
        repository.flush()
        task.current_execution_id = execution.id
        task.status = "open"
        task.updated_by = actor.user_id
        task.updated_at = now
        task.row_version += 1
        repository.flush()

    def _build_snapshot(
        self,
        repository: AuditRuntimeRepository,
        financial: FinancialReadRepository,
        organization_tax_number: str,
        task: AuditTask,
        execution: AuditTaskExecution,
        contract_id: UUID | None,
        invoices: tuple[InvoiceReadView, ...],
        rules: tuple[AuditRuleVersion, ...],
    ) -> AuditSnapshotFacts:
        contract_hash: str | None = None
        contract_fields: dict[str, JsonValue] = {}
        has_unconfirmed_agreement = False
        if contract_id is not None:
            view = financial.read_effective_contract(task.organization_id, contract_id)
            if view is None:
                raise _not_found()
            if view.contract.confirmation_status != "confirmed":
                raise _conflict(
                    "AUDIT_FACTS_UNCONFIRMED",
                    "合同核心事实未确认，不能开始审核",
                )
            projected = project_effective_contract(view, execution.baseline_date)
            contract_fields = {
                field.field_code: field.effective_value for field in projected.fields
            }
            contract_hash = hashlib.sha256(
                canonicalize_jcs(
                    [
                        "effective-contract-snapshot-v1",
                        view.contract.critical_fact_hash,
                        execution.baseline_date.isoformat(),
                        projected.model_dump(mode="json"),
                    ]
                )
            ).hexdigest()
            has_unconfirmed_agreement = any(
                change.effective_date <= execution.baseline_date
                and (
                    change.agreement_status != "confirmed"
                    or change.agreement_confirmation_status != "confirmed"
                    or change.change_confirmation_status != "confirmed"
                )
                for change in view.changes
            )
        invoice_facts: list[SnapshotInvoiceFacts] = []
        cumulative_total = Decimal("0")
        for invoice in invoices:
            included = invoice.duplicate_status != "confirmed_duplicate"
            exclusion_reason = None if included else "confirmed_duplicate"
            if invoice.total_amount is None or invoice.currency is None:
                raise _conflict(
                    "AUDIT_FACTS_UNCONFIRMED",
                    "已确认发票缺少总额或币种，不能开始审核",
                )
            if included:
                cumulative_total += invoice.total_amount
            invoice_facts.append(
                SnapshotInvoiceFacts(
                    invoice_id=invoice.id,
                    critical_fact_hash=invoice.critical_fact_hash,
                    invoice_code=invoice.invoice_code,
                    invoice_number=invoice.invoice_number,
                    invoice_type=invoice.invoice_type,
                    invoice_date=invoice.invoice_date,
                    buyer_name=invoice.buyer_name,
                    buyer_tax_no=invoice.buyer_tax_no,
                    seller_name=invoice.seller_name,
                    seller_tax_no=invoice.seller_tax_no,
                    amount_excluding_tax=invoice.amount_excluding_tax,
                    tax_amount=invoice.tax_amount,
                    total_amount=invoice.total_amount,
                    line_net_amount=_line_net_amount(invoice),
                    currency=invoice.currency,
                    duplicate_status=invoice.duplicate_status,
                    has_existing_exact_invoice_identity=repository.has_exact_duplicate(
                        organization_id=invoice.organization_id,
                        invoice_id=invoice.id,
                        invoice_code=invoice.invoice_code,
                        invoice_number=invoice.invoice_number,
                        seller_tax_no=invoice.seller_tax_no,
                    ),
                    is_red_invoice=invoice.is_red_invoice,
                    included_in_cumulative_total=included,
                    cumulative_exclusion_reason=exclusion_reason,
                    row_version=invoice.row_version,
                )
            )
        requires_citation = any(rule.requires_policy_citation for rule in rules)
        party_a_name = _optional_string(contract_fields.get("party_a_name"))
        party_b_name = _optional_string(contract_fields.get("party_b_name"))
        return AuditSnapshotFacts(
            schema_version=1,
            organization_id=task.organization_id,
            task_id=task.id,
            execution_id=execution.id,
            baseline_date=execution.baseline_date,
            organization_tax_number=organization_tax_number,
            contract_id=contract_id,
            contract_critical_fact_hash=contract_hash,
            contract_no=_optional_string(contract_fields.get("contract_no")),
            contract_party_a_name=party_a_name,
            contract_party_a_tax_no=_optional_string(contract_fields.get("party_a_tax_no")),
            contract_party_b_name=party_b_name,
            contract_party_b_tax_no=_optional_string(contract_fields.get("party_b_tax_no")),
            effective_contract_amount=_optional_decimal(contract_fields.get("amount")),
            contract_currency=_optional_string(contract_fields.get("currency")),
            contract_effective_date=_optional_date(contract_fields.get("effective_date")),
            contract_expiry_date=_optional_date(contract_fields.get("expiry_date")),
            contract_subjects_present=bool(party_a_name and party_b_name),
            has_effective_unconfirmed_supplementary_agreement=has_unconfirmed_agreement,
            cumulative_invoice_total=cumulative_total,
            requires_policy_citation=requires_citation,
            retrieval_completed_successfully=False,
            has_applicable_policy_citation=False,
            invoices=tuple(invoice_facts),
        )

    @staticmethod
    def _create_execution_model(
        task: AuditTask,
        *,
        version_no: int,
        baseline_date: date,
        actor: AuthenticatedActor,
        trace_id: UUID,
        now: datetime,
    ) -> AuditTaskExecution:
        return AuditTaskExecution(
            id=uuid4(),
            organization_id=actor.organization_id,
            audit_task_id=task.id,
            version_no=version_no,
            baseline_date=baseline_date,
            status="draft",
            snapshot_sha256=None,
            job_id=None,
            finance_reviewer_id=None,
            finance_reviewed_at=None,
            audit_reviewer_id=None,
            audit_reviewed_at=None,
            retryable=False,
            failure_code=None,
            cancel_reason=None,
            return_reason=None,
            row_version=1,
            created_by=actor.user_id,
            created_at=now,
            started_at=None,
            finished_at=None,
            outdated_at=None,
            trace_id=trace_id,
        )

    @staticmethod
    def _validate_risk_review_lane(
        cluster: LockedAuditCluster,
        risk: AuditRisk,
        actor: AuthenticatedActor,
        high_risk: bool,
    ) -> None:
        if risk.review_status != "pending":
            raise _conflict("RISK_ALREADY_REVIEWED", "风险已经完成复核")
        if high_risk:
            if risk.effective_level != "high" or cluster.execution.status != "pending_audit_review":
                raise _conflict("HIGH_RISK_REVIEW_REQUIRED", "当前风险不在高风险审计复核阶段")
            if cluster.execution.finance_reviewer_id == actor.user_id:
                raise _conflict(
                    "REVIEWER_SEPARATION_REQUIRED",
                    "财务初审人员不能复核同一执行的高风险",
                )
        elif risk.effective_level == "high" or cluster.execution.status != "pending_finance_review":
            raise _conflict("HIGH_RISK_REVIEW_REQUIRED", "高风险只能由独立审计复核")

    @staticmethod
    def _risk_review_snapshot(risk: AuditRisk) -> dict[str, object]:
        return {
            "effective_level": risk.effective_level,
            "review_reason": risk.review_reason,
            "review_status": risk.review_status,
            "reviewed_by": None if risk.reviewed_by is None else str(risk.reviewed_by),
            "row_version": str(risk.row_version),
        }

    @staticmethod
    def _append_log(
        session: Session,
        actor: AuthenticatedActor,
        action_code: str,
        resource_type: str,
        resource_id: UUID,
        trace_id: UUID,
        change_summary: dict[str, object],
    ) -> None:
        OperationLogRepository(session).append(
            organization_id=actor.organization_id,
            actor_kind="user",
            actor_id=actor.user_id,
            action_code=action_code,
            outcome="succeeded",
            resource_type=resource_type,
            resource_id=resource_id,
            trace_id=trace_id,
            change_summary=change_summary,
        )

    @staticmethod
    def _write_digest(
        method: str,
        path: str,
        payload: BaseModel,
        idempotency_key: str,
    ) -> str:
        _validate_idempotency_key(idempotency_key)
        body = cast(dict[str, object], payload.model_dump(mode="json"))
        return _request_hash(method, path, body)

    @staticmethod
    def _claim(
        session: Session,
        actor: AuthenticatedActor,
        idempotency_key: str,
        method: str,
        path: str,
        digest: str,
    ) -> tuple[AuditRuntimeRepository, IdempotencyClaim, datetime, Organization]:
        repository = AuditRuntimeRepository(session)
        repository.acquire_api_locks(actor.organization_id, actor.user_id, idempotency_key)
        organization = repository.lock_active_organization(actor.organization_id)
        if organization is None:
            raise _not_found()
        now = repository.database_now()
        claim = repository.claim_idempotency(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            idempotency_key=idempotency_key,
            request_method=method,
            request_path=path,
            request_hash=digest,
            now=now,
            expires_at=now + _IDEMPOTENCY_TTL,
        )
        return repository, claim, now, organization

    @staticmethod
    def _replay_task(claim: IdempotencyClaim) -> AuditTaskMutationResult:
        if claim.replay_status != 202 or claim.replay_body is None:
            raise RuntimeError("audit task replay does not match the contract")
        data = AuditTaskMutationData.model_validate_json(_canonical_json(claim.replay_body))
        return AuditTaskMutationResult(data, True, 202)

    @staticmethod
    def _replay_execution(claim: IdempotencyClaim) -> AuditExecutionMutationResult:
        if claim.replay_status != 200 or claim.replay_body is None:
            raise RuntimeError("audit execution replay does not match the contract")
        data = AuditExecutionMutationData.model_validate_json(_canonical_json(claim.replay_body))
        return AuditExecutionMutationResult(data, True)

    @staticmethod
    def _replay_risk(claim: IdempotencyClaim) -> AuditRiskMutationResult:
        if claim.replay_status != 200 or claim.replay_body is None:
            raise RuntimeError("audit risk replay does not match the contract")
        data = AuditRiskMutationData.model_validate_json(_canonical_json(claim.replay_body))
        return AuditRiskMutationResult(data, True)

    @staticmethod
    def _integrity_error(error: IntegrityError) -> AppError:
        diagnostic = getattr(error.orig, "diag", None)
        constraint = getattr(diagnostic, "constraint_name", None)
        if constraint == "uq_audit_tasks_organization_id_task_no":
            return _conflict("AUDIT_TASK_NO_EXISTS", "审核任务编号已存在")
        return _conflict("WRITE_CONFLICT", "并发写入冲突")


__all__ = [
    "AuditExecutionMutationResult",
    "AuditManagementService",
    "AuditRiskMutationResult",
    "AuditTaskMutationResult",
]
