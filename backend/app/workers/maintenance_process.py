"""文件 Job 重排队与租约恢复常驻进程入口。"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Mapping
from dataclasses import dataclass

from app.ai.policy_loader import load_validated_policy
from app.core.config import Settings
from app.db.session import create_session_factory
from app.repositories.ai_call_audit import (
    AiCallProjectionStatus,
    AiCallReconcileStatus,
)
from app.services.ai_call_audit import AiCallAuditService, ai_call_deadlines_from_settings
from app.services.job_recovery import (
    AuditJobRecovery,
    FileJobRecovery,
    KnowledgeJobRecovery,
    RecoveryResult,
    ReportJobRecovery,
)
from app.workers.runtime import FileWorkerRuntime, create_file_worker_runtime

_IDLE_WAIT_SECONDS = 0.5
_ERROR_WAIT_SECONDS = 1.0
_WORKER_ID = "maintenance-recovery"
_LOG = logging.getLogger("finaudit.maintenance")


@dataclass(slots=True)
class MaintenanceProcessRuntime:
    worker: FileWorkerRuntime
    recovery: FileJobRecovery
    knowledge_recovery: KnowledgeJobRecovery | None = None
    audit_recovery: AuditJobRecovery | None = None
    report_recovery: ReportJobRecovery | None = None
    ai_call_audit: AiCallAuditService | None = None
    ai_call_deadlines: Mapping[str, int] | None = None

    def close(self) -> None:
        self.worker.close()


def create_maintenance_runtime(settings: Settings | None = None) -> MaintenanceProcessRuntime:
    active_settings = settings or Settings()
    load_validated_policy(active_settings)
    worker = create_file_worker_runtime(active_settings)
    try:
        recovery = FileJobRecovery(
            create_session_factory(worker.engine),
            worker.executor,
            worker.invoice_executor,
            worker.contract_executor,
        )
        if worker.knowledge_executor is None:
            raise RuntimeError("knowledge job executor is unavailable")
        knowledge_recovery = KnowledgeJobRecovery(
            create_session_factory(worker.engine), worker.knowledge_executor
        )
        if worker.audit_executor is None:
            raise RuntimeError("audit job executor is unavailable")
        audit_recovery = AuditJobRecovery(
            create_session_factory(worker.engine), worker.audit_executor
        )
        if worker.report_executor is None:
            raise RuntimeError("report job executor is unavailable")
        report_recovery = ReportJobRecovery(
            create_session_factory(worker.engine), worker.report_executor
        )
        ai_call_audit = AiCallAuditService(create_session_factory(worker.engine))
        ai_call_deadlines = ai_call_deadlines_from_settings(active_settings)
    except Exception:
        worker.close()
        raise
    return MaintenanceProcessRuntime(
        worker=worker,
        recovery=recovery,
        knowledge_recovery=knowledge_recovery,
        audit_recovery=audit_recovery,
        report_recovery=report_recovery,
        ai_call_audit=ai_call_audit,
        ai_call_deadlines=ai_call_deadlines,
    )


def run_maintenance_iteration(runtime: MaintenanceProcessRuntime) -> RecoveryResult:
    requeued = runtime.recovery.requeue_failed_once()
    if requeued.outcome != "idle":
        return requeued
    if runtime.knowledge_recovery is not None:
        knowledge_requeued = runtime.knowledge_recovery.requeue_failed_once()
        if knowledge_requeued.outcome != "idle":
            return knowledge_requeued
    if runtime.audit_recovery is not None:
        audit_requeued = runtime.audit_recovery.requeue_failed_once()
        if audit_requeued.outcome != "idle":
            return audit_requeued
    if runtime.report_recovery is not None:
        report_requeued = runtime.report_recovery.requeue_failed_once()
        if report_requeued.outcome != "idle":
            return report_requeued
    recovered = runtime.recovery.recover_expired_once(worker_id=_WORKER_ID)
    if recovered.outcome != "idle":
        return recovered
    if runtime.knowledge_recovery is not None:
        knowledge_recovered = runtime.knowledge_recovery.recover_expired_once(worker_id=_WORKER_ID)
        if knowledge_recovered.outcome != "idle":
            return knowledge_recovered
    if runtime.audit_recovery is not None:
        audit_recovered = runtime.audit_recovery.recover_expired_once(worker_id=_WORKER_ID)
        if audit_recovered.outcome != "idle":
            return audit_recovered
    if runtime.report_recovery is not None:
        report_recovered = runtime.report_recovery.recover_expired_once(worker_id=_WORKER_ID)
        if report_recovered.outcome != "idle":
            return report_recovered
    if runtime.ai_call_audit is not None:
        projected = runtime.ai_call_audit.project_once()
        if projected.status is not AiCallProjectionStatus.IDLE:
            log_projection = (
                _LOG.warning
                if projected.status
                in {
                    AiCallProjectionStatus.DEAD_LETTER,
                    AiCallProjectionStatus.LATE_RECORDED,
                }
                else _LOG.info
            )
            log_projection("AI_AUDIT_PROJECTION outcome=%s", projected.status.value)
            return RecoveryResult("idle")
        if runtime.ai_call_deadlines is None:
            raise RuntimeError("AI audit deadlines are unavailable")
        reconciled = runtime.ai_call_audit.reconcile_once(runtime.ai_call_deadlines)
        if reconciled.status is not AiCallReconcileStatus.IDLE:
            log_reconciliation = (
                _LOG.warning
                if reconciled.status
                in {
                    AiCallReconcileStatus.BLOCKED,
                    AiCallReconcileStatus.OUTCOME_UNKNOWN,
                }
                else _LOG.info
            )
            log_reconciliation("AI_AUDIT_RECONCILE outcome=%s", reconciled.status.value)
    return RecoveryResult("idle")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    stop = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    try:
        runtime = create_maintenance_runtime()
    except Exception:
        _LOG.error("MAINTENANCE_STARTUP_FAILED")
        return 1
    try:
        while not stop.is_set():
            try:
                result = run_maintenance_iteration(runtime)
            except Exception:
                _LOG.error("MAINTENANCE_ITERATION_FAILED")
                stop.wait(_ERROR_WAIT_SECONDS)
                continue
            if result.outcome == "idle":
                stop.wait(_IDLE_WAIT_SECONDS)
            else:
                _LOG.info(
                    "MAINTENANCE_OUTCOME outcome=%s job_id=%s",
                    result.outcome,
                    result.job_id,
                )
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MaintenanceProcessRuntime",
    "create_maintenance_runtime",
    "main",
    "run_maintenance_iteration",
]
