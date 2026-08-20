"""文件 Job 的失败重试与过期租约恢复协调。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy.orm import Session, sessionmaker

from app.repositories.job_runtime import (
    AuditRecoveryCandidate,
    FileRecoveryCandidate,
    JobRuntimeRepository,
    KnowledgeRecoveryCandidate,
    ReportRecoveryCandidate,
)
from app.services.audit_job_executor import AuditJobExecutionError, AuditJobExecutor
from app.services.contract_extraction_executor import (
    ContractExtractionExecutionError,
    ContractExtractionExecutor,
)
from app.services.file_job_executor import FileJobExecutionError, FileJobExecutor
from app.services.invoice_extraction_executor import (
    InvoiceExtractionExecutionError,
    InvoiceExtractionExecutor,
)
from app.services.knowledge_job_executor import (
    KnowledgeJobExecutionError,
    KnowledgeJobExecutor,
)
from app.services.report_job_executor import ReportJobExecutionError, ReportJobExecutor
from app.workers.audit_handler_registry import AuditHandlerRuntime, load_audit_handler
from app.workers.contract_handler_registry import ContractHandlerRuntime, load_contract_handler
from app.workers.file_handler_registry import FileHandlerRuntime, FileJobType, load_file_handler
from app.workers.handler_registry import HandlerRegistryError
from app.workers.invoice_handler_registry import InvoiceHandlerRuntime, load_invoice_handler
from app.workers.knowledge_handler_registry import (
    KnowledgeHandlerRuntime,
    KnowledgeJobType,
    load_knowledge_handler,
)
from app.workers.report_handler_registry import ReportHandlerRuntime, load_report_handler


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    outcome: Literal[
        "idle",
        "requeued",
        "claimed_and_succeeded",
        "claimed_and_failed",
        "exhausted",
        "stale",
        "registry_invalid",
    ]
    job_id: str | None = None


class FileJobRecovery:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        executor: FileJobExecutor,
        invoice_executor: InvoiceExtractionExecutor | None = None,
        contract_executor: ContractExtractionExecutor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor
        self._invoice_executor = invoice_executor
        self._contract_executor = contract_executor

    def requeue_failed_once(self) -> RecoveryResult:
        with self._session_factory() as session:
            candidates = JobRuntimeRepository(session).retryable_file_candidates(limit=1)
        if not candidates:
            return RecoveryResult("idle")
        candidate = candidates[0]
        handler = _validated_handler(candidate)
        if handler is None or not _can_start_at(handler, candidate.stage):
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        with self._session_factory.begin() as session:
            requeued = JobRuntimeRepository(session).requeue_failed_file_job(
                job_id=candidate.job.id,
                start_step_code=candidate.stage,
            )
        return RecoveryResult(
            "requeued" if requeued else "stale",
            str(candidate.job.id),
        )

    def recover_expired_once(self, *, worker_id: str) -> RecoveryResult:
        with self._session_factory() as session:
            candidates = JobRuntimeRepository(session).expired_file_candidates(limit=1)
        if not candidates:
            return RecoveryResult("idle")
        candidate = candidates[0]
        handler = _validated_handler(candidate)
        start_step = candidate.job.current_attempt_start_step_code
        can_recover = handler is not None and (
            _can_start_at(handler, start_step)
            or (
                candidate.job.job_type
                in {"manual_correction_snapshot", "asset_security_revalidation"}
                and any(step.step_code == start_step for step in handler.handler.steps)
            )
        )
        if not can_recover:
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        assert handler is not None
        if candidate.job.job_type == "invoice_extract" and self._invoice_executor is None:
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        if candidate.job.job_type == "contract_extract" and self._contract_executor is None:
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        step_seq = next(
            (
                index
                for index, step in enumerate(handler.handler.steps, start=1)
                if step.step_code == start_step
            ),
            0,
        )
        if step_seq == 0:
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        with self._session_factory.begin() as session:
            recovered = JobRuntimeRepository(session).recover_expired_file_job(
                job_id=candidate.job.id,
                worker_id=worker_id,
                start_step_code=start_step,
                start_step_seq=step_seq,
            )
        if recovered.outcome == "exhausted":
            return RecoveryResult("exhausted", str(candidate.job.id))
        if recovered.claim is None:
            return RecoveryResult("stale", str(candidate.job.id))
        try:
            if candidate.job.job_type == "invoice_extract":
                assert self._invoice_executor is not None
                outcome = self._invoice_executor.execute_claimed(recovered.claim).outcome
            elif candidate.job.job_type == "contract_extract":
                assert self._contract_executor is not None
                outcome = self._contract_executor.execute_claimed(recovered.claim).outcome
            else:
                outcome = self._executor.execute_claimed(recovered.claim).outcome
        except (
            FileJobExecutionError,
            InvoiceExtractionExecutionError,
            ContractExtractionExecutionError,
        ):
            # 已重领的 Job 保持运行，由同一租约恢复协议再次收敛；异常原文不得外泄。
            return RecoveryResult("claimed_and_failed", str(candidate.job.id))
        if outcome == "succeeded":
            return RecoveryResult("claimed_and_succeeded", str(candidate.job.id))
        return RecoveryResult("claimed_and_failed", str(candidate.job.id))


class KnowledgeJobRecovery:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        executor: KnowledgeJobExecutor,
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor

    def requeue_failed_once(self) -> RecoveryResult:
        with self._session_factory() as session:
            candidates = JobRuntimeRepository(session).retryable_knowledge_candidates(limit=1)
        if not candidates:
            return RecoveryResult("idle")
        candidate = candidates[0]
        handler = _validated_knowledge_handler(candidate)
        if handler is None or not _can_start_at(handler, candidate.stage):
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        with self._session_factory.begin() as session:
            requeued = JobRuntimeRepository(session).requeue_failed_knowledge_job(
                job_id=candidate.job.id,
                start_step_code=candidate.stage,
            )
        return RecoveryResult(
            "requeued" if requeued else "stale",
            str(candidate.job.id),
        )

    def recover_expired_once(self, *, worker_id: str) -> RecoveryResult:
        with self._session_factory() as session:
            candidates = JobRuntimeRepository(session).expired_knowledge_candidates(limit=1)
        if not candidates:
            return RecoveryResult("idle")
        candidate = candidates[0]
        handler = _validated_knowledge_handler(candidate)
        start_step = candidate.job.current_attempt_start_step_code
        if handler is None or not _can_start_at(handler, start_step):
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        step_seq = next(
            (
                index
                for index, step in enumerate(handler.handler.steps, start=1)
                if step.step_code == start_step
            ),
            0,
        )
        if step_seq == 0:
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        with self._session_factory.begin() as session:
            recovered = JobRuntimeRepository(session).recover_expired_knowledge_job(
                job_id=candidate.job.id,
                worker_id=worker_id,
                start_step_code=start_step,
                start_step_seq=step_seq,
            )
        if recovered.outcome == "exhausted":
            return RecoveryResult("exhausted", str(candidate.job.id))
        if recovered.claim is None:
            return RecoveryResult("stale", str(candidate.job.id))
        try:
            outcome = self._executor.execute_claimed(recovered.claim).outcome
        except KnowledgeJobExecutionError:
            return RecoveryResult("claimed_and_failed", str(candidate.job.id))
        if outcome == "succeeded":
            return RecoveryResult("claimed_and_succeeded", str(candidate.job.id))
        return RecoveryResult("claimed_and_failed", str(candidate.job.id))


class AuditJobRecovery:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        executor: AuditJobExecutor,
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor

    def requeue_failed_once(self) -> RecoveryResult:
        with self._session_factory() as session:
            candidates = JobRuntimeRepository(session).retryable_audit_candidates(limit=1)
        if not candidates:
            return RecoveryResult("idle")
        candidate = candidates[0]
        handler = _validated_audit_handler(candidate)
        if handler is None or not _can_start_at(handler, candidate.stage):
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        with self._session_factory.begin() as session:
            requeued = JobRuntimeRepository(session).requeue_failed_audit_job(
                job_id=candidate.job.id,
                start_step_code=candidate.stage,
            )
        return RecoveryResult(
            "requeued" if requeued else "stale",
            str(candidate.job.id),
        )

    def recover_expired_once(self, *, worker_id: str) -> RecoveryResult:
        with self._session_factory() as session:
            candidates = JobRuntimeRepository(session).expired_audit_candidates(limit=1)
        if not candidates:
            return RecoveryResult("idle")
        candidate = candidates[0]
        handler = _validated_audit_handler(candidate)
        start_step = candidate.job.current_attempt_start_step_code
        if handler is None or not _can_start_at(handler, start_step):
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        step_seq = next(
            (
                index
                for index, step in enumerate(handler.handler.steps, start=1)
                if step.step_code == start_step
            ),
            0,
        )
        if step_seq == 0:
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        with self._session_factory.begin() as session:
            recovered = JobRuntimeRepository(session).recover_expired_audit_job(
                job_id=candidate.job.id,
                worker_id=worker_id,
                start_step_code=start_step,
                start_step_seq=step_seq,
            )
        if recovered.outcome == "exhausted":
            return RecoveryResult("exhausted", str(candidate.job.id))
        if recovered.claim is None:
            return RecoveryResult("stale", str(candidate.job.id))
        try:
            outcome = self._executor.execute_claimed(recovered.claim).outcome
        except AuditJobExecutionError:
            return RecoveryResult("claimed_and_failed", str(candidate.job.id))
        if outcome == "succeeded":
            return RecoveryResult("claimed_and_succeeded", str(candidate.job.id))
        return RecoveryResult("claimed_and_failed", str(candidate.job.id))


class ReportJobRecovery:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        executor: ReportJobExecutor,
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor

    def requeue_failed_once(self) -> RecoveryResult:
        with self._session_factory() as session:
            candidates = JobRuntimeRepository(session).retryable_report_candidates(limit=1)
        if not candidates:
            return RecoveryResult("idle")
        candidate = candidates[0]
        handler = _validated_report_handler(candidate)
        if handler is None or not _can_start_at(handler, candidate.stage):
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        with self._session_factory.begin() as session:
            requeued = JobRuntimeRepository(session).requeue_failed_report_job(
                job_id=candidate.job.id,
                start_step_code=candidate.stage,
            )
        return RecoveryResult(
            "requeued" if requeued else "stale",
            str(candidate.job.id),
        )

    def recover_expired_once(self, *, worker_id: str) -> RecoveryResult:
        with self._session_factory() as session:
            candidates = JobRuntimeRepository(session).expired_report_candidates(limit=1)
        if not candidates:
            return RecoveryResult("idle")
        candidate = candidates[0]
        handler = _validated_report_handler(candidate)
        start_step = candidate.job.current_attempt_start_step_code
        if handler is None or not _can_start_at(handler, start_step):
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        step_seq = next(
            (
                index
                for index, step in enumerate(handler.handler.steps, start=1)
                if step.step_code == start_step
            ),
            0,
        )
        if step_seq == 0:
            return RecoveryResult("registry_invalid", str(candidate.job.id))
        with self._session_factory.begin() as session:
            recovered = JobRuntimeRepository(session).recover_expired_report_job(
                job_id=candidate.job.id,
                worker_id=worker_id,
                start_step_code=start_step,
                start_step_seq=step_seq,
            )
        if recovered.outcome == "exhausted":
            return RecoveryResult("exhausted", str(candidate.job.id))
        if recovered.claim is None:
            return RecoveryResult("stale", str(candidate.job.id))
        try:
            outcome = self._executor.execute_claimed(recovered.claim).outcome
        except ReportJobExecutionError:
            return RecoveryResult("claimed_and_failed", str(candidate.job.id))
        if outcome == "succeeded":
            return RecoveryResult("claimed_and_succeeded", str(candidate.job.id))
        return RecoveryResult("claimed_and_failed", str(candidate.job.id))


RecoveryHandlerRuntime = FileHandlerRuntime | InvoiceHandlerRuntime | ContractHandlerRuntime


def _validated_handler(candidate: FileRecoveryCandidate) -> RecoveryHandlerRuntime | None:
    try:
        handler: RecoveryHandlerRuntime
        if candidate.job.job_type == "invoice_extract":
            handler = load_invoice_handler(candidate.job.handler_registry_version)
        elif candidate.job.job_type == "contract_extract":
            handler = load_contract_handler(candidate.job.handler_registry_version)
        else:
            handler = load_file_handler(cast(FileJobType, candidate.job.job_type))
        handler.validate_input(candidate.job.input_json)
    except (HandlerRegistryError, ValueError):
        return None
    is_document_rebuild = candidate.job.job_type in {
        "manual_correction_snapshot",
        "asset_security_revalidation",
    }
    if (
        candidate.job.handler_registry_version != handler.registry_version
        or candidate.job.handler_registry_hash != handler.registry_hash
        or (
            candidate.job.resource_type != "document_parse_version"
            or candidate.job.input_json.get("result_parse_version_id")
            != str(candidate.job.resource_id)
            if is_document_rebuild
            else candidate.job.job_type
            not in {"file_process", "file_scan", "invoice_extract", "contract_extract"}
            or candidate.job.resource_type != "file"
            or candidate.job.input_json.get("file_id") != str(candidate.job.resource_id)
        )
    ):
        return None
    return handler


def _validated_knowledge_handler(
    candidate: KnowledgeRecoveryCandidate,
) -> KnowledgeHandlerRuntime | None:
    try:
        handler = load_knowledge_handler(cast(KnowledgeJobType, candidate.job.job_type))
        handler.validate_input(candidate.job.input_json)
    except (HandlerRegistryError, ValueError):
        return None
    expected_resource_type = (
        "document_index_version"
        if candidate.job.job_type == "knowledge_index_build"
        else "retrieval_eval_run"
    )
    identity_field = (
        "index_version_id" if candidate.job.job_type == "knowledge_index_build" else "run_id"
    )
    if (
        candidate.job.job_type not in {"knowledge_index_build", "retrieval_eval"}
        or candidate.job.resource_type != expected_resource_type
        or candidate.job.handler_registry_version != handler.registry_version
        or candidate.job.handler_registry_hash != handler.registry_hash
        or candidate.job.input_schema_version != 1
        or candidate.job.input_json.get(identity_field) != str(candidate.job.resource_id)
    ):
        return None
    return handler


def _validated_audit_handler(
    candidate: AuditRecoveryCandidate,
) -> AuditHandlerRuntime | None:
    try:
        handler = load_audit_handler()
        handler.validate_input(candidate.job.input_json)
    except (HandlerRegistryError, ValueError):
        return None
    if (
        candidate.job.job_type != "audit_execute"
        or candidate.job.resource_type != "audit_task_execution"
        or candidate.job.handler_registry_version != handler.registry_version
        or candidate.job.handler_registry_hash != handler.registry_hash
        or candidate.job.input_schema_version != 1
        or candidate.job.input_json.get("execution_id") != str(candidate.job.resource_id)
    ):
        return None
    return handler


def _validated_report_handler(
    candidate: ReportRecoveryCandidate,
) -> ReportHandlerRuntime | None:
    try:
        handler = load_report_handler()
        handler.validate_input(candidate.job.input_json)
    except (HandlerRegistryError, ValueError):
        return None
    if (
        candidate.job.job_type != "report_generate"
        or candidate.job.resource_type != "audit_report"
        or candidate.job.handler_registry_version != handler.registry_version
        or candidate.job.handler_registry_hash != handler.registry_hash
        or candidate.job.input_schema_version != 1
        or candidate.job.input_json.get("report_id") != str(candidate.job.resource_id)
    ):
        return None
    return handler


def _can_start_at(
    handler: (
        RecoveryHandlerRuntime
        | KnowledgeHandlerRuntime
        | AuditHandlerRuntime
        | ReportHandlerRuntime
    ),
    step_code: str,
) -> bool:
    return any(scope.start_step_code == step_code for scope in handler.handler.retry_scopes)


__all__ = [
    "AuditJobRecovery",
    "FileJobRecovery",
    "KnowledgeJobRecovery",
    "RecoveryResult",
    "ReportJobRecovery",
]
