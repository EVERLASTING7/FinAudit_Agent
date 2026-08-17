"""`audit_execute` Job 的快照校验、规则持久化和 PostgreSQL fencing。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.ai.output_validation import FrozenRuleResult
from app.ai.policy import canonicalize_jcs
from app.ai.risk_explanation_prompts import RiskExplanationPromptInput
from app.audit.offline_preview import OfflineAuditPreview
from app.audit.risk_summary import RiskLevel
from app.audit.snapshot import AuditSnapshotFacts, build_aggregate_audit_preview, snapshot_sha256
from app.models.audit import AuditRisk, RuleExecution
from app.repositories.audit_runtime import (
    AuditRuleVersion,
    AuditRuntimeRepository,
    LockedAuditCluster,
)
from app.repositories.job_runtime import ClaimedJob, JobRuntimeRepository, JobSnapshot
from app.repositories.operation_log import OperationLogRepository
from app.services.ai_risk_explanation import (
    AiRiskExplanationService,
    AiRiskExplanationServiceError,
    AuditedRiskExplanation,
)
from app.services.audited_llm import AuditedLlmInvocationError
from app.workers.audit_handler_registry import AuditHandlerRuntime, load_audit_handler
from app.workers.handler_registry import HandlerRegistryError


class AuditJobExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _AuditDeterministicFailure(RuntimeError):
    pass


class _AuditCancelled(RuntimeError):
    pass


class _AuditStale(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuditJobExecutionResult:
    outcome: Literal["succeeded", "failed", "duplicate_or_stale", "cancelled"]
    job_id: UUID


@dataclass(frozen=True, slots=True)
class _EvaluationPlan:
    snapshot_id: UUID
    snapshot_sha256: str
    preview: OfflineAuditPreview
    rule_versions: tuple[AuditRuleVersion, ...]


class AuditJobExecutor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        ai_explanation: AiRiskExplanationService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._ai_explanation = ai_explanation

    def execute(
        self,
        *,
        job_id: UUID,
        event_id: UUID,
        event_schema_version: int,
        worker_id: str,
    ) -> AuditJobExecutionResult:
        if not worker_id or len(worker_id) > 100:
            raise AuditJobExecutionError("WORKER_ID_INVALID")
        with self._session_factory.begin() as session:
            repository = JobRuntimeRepository(session)
            snapshot = repository.peek_job(job_id)
            if snapshot is None:
                raise AuditJobExecutionError("JOB_NOT_FOUND")
            handler = self._validated_handler(snapshot.input_json)
            if not self._job_matches(snapshot, handler):
                raise AuditJobExecutionError("HANDLER_REGISTRY_INVALID")
            claim = repository.claim_job(
                job_id=job_id,
                event_id=event_id,
                event_schema_version=event_schema_version,
                worker_id=worker_id,
                start_step_seq=1,
            )
            if claim is None:
                return AuditJobExecutionResult("duplicate_or_stale", job_id)
        return self._execute_claimed(claim, handler)

    def execute_claimed(self, claim: ClaimedJob) -> AuditJobExecutionResult:
        handler = self._validated_handler(claim.job.input_json)
        if not self._job_matches(claim.job, handler) or claim.step_code != "evaluate":
            raise AuditJobExecutionError("HANDLER_REGISTRY_INVALID")
        return self._execute_claimed(claim, handler)

    def _execute_claimed(
        self,
        claim: ClaimedJob,
        handler: AuditHandlerRuntime,
    ) -> AuditJobExecutionResult:
        try:
            plan = self._preflight(claim)
            explanations, ai_attempted = self._generate_explanations(claim, plan)
            return self._complete(claim, handler, plan, explanations, ai_attempted)
        except _AuditCancelled:
            return self._cancel(claim)
        except _AuditStale:
            return AuditJobExecutionResult("duplicate_or_stale", claim.job.id)
        except _AuditDeterministicFailure as error:
            return self._fail(claim, str(error), retryable=False)
        except AuditJobExecutionError:
            raise
        except Exception:
            return self._fail(claim, "AUDIT_EXECUTION_FAILED", retryable=False)

    def _preflight(self, claim: ClaimedJob) -> _EvaluationPlan:
        with self._session_factory.begin() as session:
            repository = AuditRuntimeRepository(session)
            cluster = repository.lock_cluster(
                claim.job.organization_id,
                claim.job.resource_id,
            )
            return self._build_plan(claim, repository, cluster)

    @staticmethod
    def _build_plan(
        claim: ClaimedJob,
        repository: AuditRuntimeRepository,
        cluster: LockedAuditCluster | None,
    ) -> _EvaluationPlan:
        if cluster is None or cluster.snapshot is None:
            raise _AuditDeterministicFailure("AUDIT_SNAPSHOT_INVALID")
        if cluster.execution.status in {"cancelled", "outdated"}:
            raise _AuditCancelled
        if (
            cluster.execution.status != "running"
            or cluster.execution.job_id != claim.job.id
            or cluster.rules
            or cluster.risks
            or claim.job.input_json
            != {
                "execution_id": str(cluster.execution.id),
                "snapshot_id": str(cluster.snapshot.id),
                "snapshot_sha256": cluster.snapshot.facts_sha256,
            }
        ):
            raise _AuditStale
        try:
            frozen = AuditSnapshotFacts.model_validate(cluster.snapshot.facts_json)
        except Exception:
            raise _AuditDeterministicFailure("AUDIT_SNAPSHOT_INVALID") from None
        if (
            frozen.execution_id != cluster.execution.id
            or frozen.task_id != cluster.task.id
            or snapshot_sha256(frozen) != cluster.snapshot.facts_sha256
            or cluster.execution.snapshot_sha256 != cluster.snapshot.facts_sha256
        ):
            raise _AuditDeterministicFailure("AUDIT_SNAPSHOT_INVALID")
        rule_versions = repository.rule_versions_by_ids(tuple(cluster.snapshot.rule_version_ids))
        if len(rule_versions) != 15:
            raise _AuditDeterministicFailure("AUDIT_RULE_CATALOG_INVALID")
        try:
            levels = {rule.rule_code: RiskLevel(rule.default_risk_level) for rule in rule_versions}
            preview = build_aggregate_audit_preview(frozen, levels)
        except (TypeError, ValueError):
            raise _AuditDeterministicFailure("AUDIT_RULE_EXECUTION_INVALID") from None
        return _EvaluationPlan(
            snapshot_id=cluster.snapshot.id,
            snapshot_sha256=cluster.snapshot.facts_sha256,
            preview=preview,
            rule_versions=rule_versions,
        )

    def _generate_explanations(
        self,
        claim: ClaimedJob,
        plan: _EvaluationPlan,
    ) -> tuple[dict[UUID, AuditedRiskExplanation], bool]:
        if self._ai_explanation is None:
            return {}, False
        rule_by_code = {rule.rule_code: rule for rule in plan.rule_versions}
        explanations: dict[UUID, AuditedRiskExplanation] = {}
        for result in plan.preview.rules:
            if result.risk_id is None or result.risk_level is None:
                continue
            rule = rule_by_code[result.rule_id]
            prompt_input = RiskExplanationPromptInput(
                frozen_rule=FrozenRuleResult(
                    rule_code=result.rule_id,
                    rule_version=str(rule.version),
                    rule_status=result.status.value,
                    original_risk_level=result.risk_level.value,
                ),
                title=rule.name,
                actual_value=result.actual_value,
                expected_value=result.expected_value,
                explanation_template=rule.explanation_template,
                requires_policy_citation=rule.requires_policy_citation,
                candidates=(),
            )
            try:
                explanation = self._ai_explanation.explain(
                    organization_id=claim.job.organization_id,
                    job_id=claim.job.id,
                    risk_id=result.risk_id,
                    trace_id=claim.job.trace_id,
                    prompt_input=prompt_input,
                )
            except AiRiskExplanationServiceError:
                continue
            explanations[result.risk_id] = explanation
        return explanations, True

    def _complete(
        self,
        claim: ClaimedJob,
        handler: AuditHandlerRuntime,
        plan: _EvaluationPlan,
        explanations: dict[UUID, AuditedRiskExplanation],
        ai_attempted: bool,
    ) -> AuditJobExecutionResult:
        with self._session_factory.begin() as session:
            repository = AuditRuntimeRepository(session)
            cluster = repository.lock_cluster(
                claim.job.organization_id,
                claim.job.resource_id,
            )
            if cluster is not None and cluster.execution.status in {"cancelled", "outdated"}:
                self._reject_explanations(session, explanations, "AI_RESULT_NOT_ADOPTED")
                if not JobRuntimeRepository(session).finish_cancel_requested(claim):
                    raise AuditJobExecutionError("JOB_FENCING_REJECTED")
                return AuditJobExecutionResult("cancelled", claim.job.id)
            try:
                current = self._build_plan(claim, repository, cluster)
            except _AuditStale:
                self._reject_explanations(session, explanations, "AI_RESULT_NOT_ADOPTED")
                return AuditJobExecutionResult("duplicate_or_stale", claim.job.id)
            if current != plan:
                self._reject_explanations(session, explanations, "AI_RISK_SOURCE_DRIFT")
                return AuditJobExecutionResult("duplicate_or_stale", claim.job.id)
            assert cluster is not None and cluster.snapshot is not None
            frozen = AuditSnapshotFacts.model_validate(cluster.snapshot.facts_json)
            rule_by_code = {rule.rule_code: rule for rule in plan.rule_versions}
            result_models: list[RuleExecution] = []
            risk_models: list[AuditRisk] = []
            for result in plan.preview.rules:
                rule_version = rule_by_code[result.rule_id]
                result_model = RuleExecution(
                    id=uuid4(),
                    organization_id=claim.job.organization_id,
                    audit_task_id=cluster.task.id,
                    execution_id=cluster.execution.id,
                    snapshot_id=cluster.snapshot.id,
                    audit_rule_id=rule_version.id,
                    rule_code=result.rule_id,
                    status=result.status.value,
                    input_json={
                        "disposition": result.disposition.value,
                        "snapshot_sha256": plan.snapshot_sha256,
                    },
                    actual_value_json=(
                        None if result.actual_value is None else {"value": result.actual_value}
                    ),
                    expected_value_json=(
                        None if result.expected_value is None else {"value": result.expected_value}
                    ),
                    applicability_reason=(
                        None
                        if result.disposition.value in {"hit", "not_hit"}
                        else result.disposition.value
                    ),
                    error_code=None,
                    included_item_ids=list(result.reference_ids),
                    excluded_item_ids=[],
                )
                result_models.append(result_model)
                if result.risk_id is None or result.risk_level is None:
                    continue
                explanation_status = "degraded" if ai_attempted else "disabled"
                explanation_json: dict[str, object] | None = None
                explanation_sha256: str | None = None
                explanation = explanations.get(result.risk_id)
                if explanation is not None:
                    try:
                        explanation.adoption.adopt_in_transaction(session)
                    except AuditedLlmInvocationError:
                        explanation_status = "degraded"
                    else:
                        explanation_json = explanation.output.model_dump(mode="json")
                        explanation_sha256 = hashlib.sha256(
                            canonicalize_jcs(explanation_json)
                        ).hexdigest()
                        explanation_status = "succeeded"
                risk_models.append(
                    AuditRisk(
                        id=result.risk_id,
                        organization_id=claim.job.organization_id,
                        audit_task_id=cluster.task.id,
                        execution_id=cluster.execution.id,
                        snapshot_id=cluster.snapshot.id,
                        rule_execution_id=result_model.id,
                        rule_code=result.rule_id,
                        title=rule_version.name,
                        original_level=result.risk_level.value,
                        effective_level=result.risk_level.value,
                        review_status="pending",
                        actual_value=result.actual_value,
                        expected_value=result.expected_value,
                        ai_explanation_status=explanation_status,
                        ai_explanation_json=explanation_json,
                        ai_explanation_sha256=explanation_sha256,
                        review_reason=None,
                        reviewed_by=None,
                        reviewed_at=None,
                        row_version=1,
                        trace_id=claim.job.trace_id,
                    )
                )
            repository.add_all(tuple(result_models))
            repository.flush()
            repository.add_all(tuple(risk_models))
            repository.flush()
            cluster.execution.status = "pending_finance_review"
            cluster.execution.retryable = False
            cluster.execution.failure_code = None
            cluster.execution.row_version += 1
            repository.flush()
            retrieval_status = (
                "not_required"
                if not frozen.requires_policy_citation
                else "succeeded"
                if frozen.retrieval_completed_successfully
                else "degraded"
            )
            summary = {
                "execution_id": str(cluster.execution.id),
                "rule_count": len(result_models),
                "risk_count": len(risk_models),
                "overall_level": plan.preview.summary.overall_level.value,
                "retrieval_status": retrieval_status,
            }
            handler.validate_summary(summary)
            OperationLogRepository(session).append(
                organization_id=claim.job.organization_id,
                actor_kind="system",
                actor_id=None,
                action_code="audits.execution_evaluated",
                outcome="succeeded",
                resource_type="audit_task_execution",
                resource_id=cluster.execution.id,
                trace_id=claim.job.trace_id,
                change_summary={
                    "retrieval_status": retrieval_status,
                    "risk_count": len(risk_models),
                    "rule_count": len(result_models),
                    "status": cluster.execution.status,
                },
            )
            if not JobRuntimeRepository(session).finish_job(
                claim,
                status="succeeded",
                summary=summary,
            ):
                raise AuditJobExecutionError("JOB_FENCING_REJECTED")
        return AuditJobExecutionResult("succeeded", claim.job.id)

    @staticmethod
    def _reject_explanations(
        session: Session,
        explanations: dict[UUID, AuditedRiskExplanation],
        safe_error_code: str,
    ) -> None:
        for explanation in explanations.values():
            explanation.adoption.reject_in_transaction(
                session,
                safe_error_code=safe_error_code,
            )

    def _fail(
        self,
        claim: ClaimedJob,
        error_code: str,
        *,
        retryable: bool,
    ) -> AuditJobExecutionResult:
        with self._session_factory.begin() as session:
            repository = AuditRuntimeRepository(session)
            cluster = repository.lock_cluster(
                claim.job.organization_id,
                claim.job.resource_id,
            )
            if cluster is None:
                raise AuditJobExecutionError("JOB_FENCING_REJECTED")
            if cluster.execution.status in {"cancelled", "outdated"}:
                if not JobRuntimeRepository(session).finish_cancel_requested(claim):
                    raise AuditJobExecutionError("JOB_FENCING_REJECTED")
                return AuditJobExecutionResult("cancelled", claim.job.id)
            if cluster.execution.status != "running":
                return AuditJobExecutionResult("duplicate_or_stale", claim.job.id)
            now = repository.database_now()
            cluster.execution.status = "failed"
            cluster.execution.failure_code = error_code
            cluster.execution.retryable = retryable
            cluster.execution.finished_at = now
            cluster.execution.row_version += 1
            repository.flush()
            job_error = "DATABASE_TRANSIENT" if retryable else error_code
            if not JobRuntimeRepository(session).finish_job(
                claim,
                status="failed",
                summary={},
                error_code=job_error,
                error_message="audit execution failed",
            ):
                raise AuditJobExecutionError("JOB_FENCING_REJECTED")
            return AuditJobExecutionResult("failed", claim.job.id)

    def _cancel(self, claim: ClaimedJob) -> AuditJobExecutionResult:
        with self._session_factory.begin() as session:
            if not JobRuntimeRepository(session).finish_cancel_requested(claim):
                raise AuditJobExecutionError("JOB_FENCING_REJECTED")
        return AuditJobExecutionResult("cancelled", claim.job.id)

    @staticmethod
    def _validated_handler(input_json: dict[str, object]) -> AuditHandlerRuntime:
        try:
            handler = load_audit_handler()
            handler.validate_input(input_json)
        except (HandlerRegistryError, ValueError):
            raise AuditJobExecutionError("HANDLER_REGISTRY_INVALID") from None
        return handler

    @staticmethod
    def _job_matches(job: JobSnapshot, handler: AuditHandlerRuntime) -> bool:
        return bool(
            job.job_type == "audit_execute"
            and job.resource_type == "audit_task_execution"
            and job.handler_registry_version == handler.registry_version
            and job.handler_registry_hash == handler.registry_hash
            and job.input_json.get("execution_id") == str(job.resource_id)
            and job.current_attempt_start_step_code == "evaluate"
        )


__all__ = [
    "AuditJobExecutionError",
    "AuditJobExecutionResult",
    "AuditJobExecutor",
]
