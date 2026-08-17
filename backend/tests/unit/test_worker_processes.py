from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import cast

import pytest

from app.core.config import Settings
from app.repositories.ai_call_audit import (
    AiCallProjectionResult,
    AiCallProjectionStatus,
    AiCallReconcileResult,
    AiCallReconcileStatus,
)
from app.services.ai_call_audit import AiCallAuditService
from app.services.job_dispatcher import DispatchResult, OutboxDispatcher
from app.services.job_recovery import (
    AuditJobRecovery,
    FileJobRecovery,
    KnowledgeJobRecovery,
    RecoveryResult,
)
from app.workers.dispatcher_process import (
    DispatcherProcessRuntime,
    create_dispatcher_runtime,
    run_dispatcher_iteration,
)
from app.workers.maintenance_process import (
    MaintenanceProcessRuntime,
    run_maintenance_iteration,
)
from app.workers.runtime import FileWorkerRuntime, create_file_worker_runtime


class _DisposableEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _Dispatcher:
    def __init__(self, reap: DispatchResult, dispatch: DispatchResult) -> None:
        self.reap = reap
        self.dispatch = dispatch
        self.dispatch_calls = 0

    def reap_expired_once(self) -> DispatchResult:
        return self.reap

    def dispatch_once(self) -> DispatchResult:
        self.dispatch_calls += 1
        return self.dispatch


class _Recovery:
    def __init__(self, requeue: RecoveryResult, recover: RecoveryResult) -> None:
        self.requeue = requeue
        self.recover = recover
        self.recover_calls = 0
        self.worker_id: str | None = None

    def requeue_failed_once(self) -> RecoveryResult:
        return self.requeue

    def recover_expired_once(self, *, worker_id: str) -> RecoveryResult:
        self.recover_calls += 1
        self.worker_id = worker_id
        return self.recover


class _AiCallAudit:
    def __init__(
        self,
        projection: AiCallProjectionResult,
        reconciliation: AiCallReconcileResult,
    ) -> None:
        self.projection = projection
        self.reconciliation = reconciliation
        self.reconcile_calls = 0

    def project_once(self) -> AiCallProjectionResult:
        return self.projection

    def reconcile_once(self, deadlines: object) -> AiCallReconcileResult:
        assert deadlines == {"contract_field_extraction": 120}
        self.reconcile_calls += 1
        return self.reconciliation


def _worker_runtime(engine: _DisposableEngine | None = None) -> FileWorkerRuntime:
    active_engine = engine or _DisposableEngine()
    return FileWorkerRuntime(
        executor=cast(object, SimpleNamespace()),
        engine=cast(object, active_engine),
    )


def test_dispatcher_iteration_reaps_before_publishing() -> None:
    dispatcher = _Dispatcher(
        DispatchResult("retry_scheduled", "outbox-1", "job-1"),
        DispatchResult("published", "outbox-2", "job-2"),
    )
    runtime = DispatcherProcessRuntime(
        engine=cast(object, _DisposableEngine()),
        dispatcher=cast(OutboxDispatcher, dispatcher),
    )

    result = run_dispatcher_iteration(runtime)

    assert result.outcome == "retry_scheduled"
    assert dispatcher.dispatch_calls == 0


def test_dispatcher_iteration_publishes_when_no_expired_claim_exists() -> None:
    dispatcher = _Dispatcher(
        DispatchResult("idle"),
        DispatchResult("published", "outbox-1", "job-1"),
    )
    runtime = DispatcherProcessRuntime(
        engine=cast(object, _DisposableEngine()),
        dispatcher=cast(OutboxDispatcher, dispatcher),
    )

    result = run_dispatcher_iteration(runtime)

    assert result.outcome == "published"
    assert dispatcher.dispatch_calls == 1


def test_maintenance_iteration_requeues_before_reclaiming_expired_lease() -> None:
    recovery = _Recovery(RecoveryResult("requeued", "job-1"), RecoveryResult("idle"))
    runtime = MaintenanceProcessRuntime(
        worker=_worker_runtime(),
        recovery=cast(FileJobRecovery, recovery),
    )

    result = run_maintenance_iteration(runtime)

    assert result.outcome == "requeued"
    assert recovery.recover_calls == 0


def test_maintenance_iteration_reclaims_after_retry_queue_is_empty() -> None:
    recovery = _Recovery(
        RecoveryResult("idle"),
        RecoveryResult("claimed_and_succeeded", "job-1"),
    )
    runtime = MaintenanceProcessRuntime(
        worker=_worker_runtime(),
        recovery=cast(FileJobRecovery, recovery),
    )

    result = run_maintenance_iteration(runtime)

    assert result.outcome == "claimed_and_succeeded"
    assert recovery.recover_calls == 1
    assert recovery.worker_id == "maintenance-recovery"


def test_maintenance_iteration_checks_knowledge_retry_before_any_lease_reclaim() -> None:
    file_recovery = _Recovery(RecoveryResult("idle"), RecoveryResult("idle"))
    knowledge_recovery = _Recovery(
        RecoveryResult("requeued", "knowledge-job-1"), RecoveryResult("idle")
    )
    runtime = MaintenanceProcessRuntime(
        worker=_worker_runtime(),
        recovery=cast(FileJobRecovery, file_recovery),
        knowledge_recovery=cast(KnowledgeJobRecovery, knowledge_recovery),
    )

    result = run_maintenance_iteration(runtime)

    assert result == RecoveryResult("requeued", "knowledge-job-1")
    assert file_recovery.recover_calls == 0
    assert knowledge_recovery.recover_calls == 0


def test_maintenance_iteration_reclaims_knowledge_after_file_work_is_idle() -> None:
    file_recovery = _Recovery(RecoveryResult("idle"), RecoveryResult("idle"))
    knowledge_recovery = _Recovery(
        RecoveryResult("idle"),
        RecoveryResult("claimed_and_succeeded", "knowledge-job-1"),
    )
    runtime = MaintenanceProcessRuntime(
        worker=_worker_runtime(),
        recovery=cast(FileJobRecovery, file_recovery),
        knowledge_recovery=cast(KnowledgeJobRecovery, knowledge_recovery),
    )

    result = run_maintenance_iteration(runtime)

    assert result == RecoveryResult("claimed_and_succeeded", "knowledge-job-1")
    assert file_recovery.recover_calls == 1
    assert knowledge_recovery.recover_calls == 1
    assert knowledge_recovery.worker_id == "maintenance-recovery"


def test_maintenance_iteration_checks_audit_retry_after_other_retry_queues() -> None:
    file_recovery = _Recovery(RecoveryResult("idle"), RecoveryResult("idle"))
    knowledge_recovery = _Recovery(RecoveryResult("idle"), RecoveryResult("idle"))
    audit_recovery = _Recovery(
        RecoveryResult("requeued", "audit-job-1"),
        RecoveryResult("idle"),
    )
    runtime = MaintenanceProcessRuntime(
        worker=_worker_runtime(),
        recovery=cast(FileJobRecovery, file_recovery),
        knowledge_recovery=cast(KnowledgeJobRecovery, knowledge_recovery),
        audit_recovery=cast(AuditJobRecovery, audit_recovery),
    )

    result = run_maintenance_iteration(runtime)

    assert result == RecoveryResult("requeued", "audit-job-1")
    assert file_recovery.recover_calls == 0
    assert knowledge_recovery.recover_calls == 0
    assert audit_recovery.recover_calls == 0


def test_maintenance_iteration_reclaims_audit_after_other_work_is_idle() -> None:
    file_recovery = _Recovery(RecoveryResult("idle"), RecoveryResult("idle"))
    knowledge_recovery = _Recovery(RecoveryResult("idle"), RecoveryResult("idle"))
    audit_recovery = _Recovery(
        RecoveryResult("idle"),
        RecoveryResult("claimed_and_succeeded", "audit-job-1"),
    )
    runtime = MaintenanceProcessRuntime(
        worker=_worker_runtime(),
        recovery=cast(FileJobRecovery, file_recovery),
        knowledge_recovery=cast(KnowledgeJobRecovery, knowledge_recovery),
        audit_recovery=cast(AuditJobRecovery, audit_recovery),
    )

    result = run_maintenance_iteration(runtime)

    assert result == RecoveryResult("claimed_and_succeeded", "audit-job-1")
    assert file_recovery.recover_calls == 1
    assert knowledge_recovery.recover_calls == 1
    assert audit_recovery.recover_calls == 1
    assert audit_recovery.worker_id == "maintenance-recovery"


def test_maintenance_iteration_projects_ai_audit_before_reconciliation() -> None:
    recovery = _Recovery(RecoveryResult("idle"), RecoveryResult("idle"))
    ai_audit = _AiCallAudit(
        AiCallProjectionResult(
            AiCallProjectionStatus.PROJECTED,
            event_type="ai.call.started",
        ),
        AiCallReconcileResult(AiCallReconcileStatus.OUTCOME_UNKNOWN),
    )
    runtime = MaintenanceProcessRuntime(
        worker=_worker_runtime(),
        recovery=cast(FileJobRecovery, recovery),
        ai_call_audit=cast(AiCallAuditService, ai_audit),
        ai_call_deadlines={"contract_field_extraction": 120},
    )

    assert run_maintenance_iteration(runtime) == RecoveryResult("idle")
    assert ai_audit.reconcile_calls == 0


def test_maintenance_iteration_reconciles_ai_audit_after_projection_is_idle() -> None:
    recovery = _Recovery(RecoveryResult("idle"), RecoveryResult("idle"))
    ai_audit = _AiCallAudit(
        AiCallProjectionResult(AiCallProjectionStatus.IDLE),
        AiCallReconcileResult(AiCallReconcileStatus.OUTCOME_UNKNOWN),
    )
    runtime = MaintenanceProcessRuntime(
        worker=_worker_runtime(),
        recovery=cast(FileJobRecovery, recovery),
        ai_call_audit=cast(AiCallAuditService, ai_audit),
        ai_call_deadlines={"contract_field_extraction": 120},
    )

    assert run_maintenance_iteration(runtime) == RecoveryResult("idle")
    assert ai_audit.reconcile_calls == 1


@pytest.mark.parametrize(
    "projection_status",
    [AiCallProjectionStatus.DEAD_LETTER, AiCallProjectionStatus.LATE_RECORDED],
)
def test_maintenance_iteration_warns_for_ai_audit_projection_anomalies(
    caplog: pytest.LogCaptureFixture,
    projection_status: AiCallProjectionStatus,
) -> None:
    recovery = _Recovery(RecoveryResult("idle"), RecoveryResult("idle"))
    ai_audit = _AiCallAudit(
        AiCallProjectionResult(projection_status),
        AiCallReconcileResult(AiCallReconcileStatus.IDLE),
    )
    runtime = MaintenanceProcessRuntime(
        worker=_worker_runtime(),
        recovery=cast(FileJobRecovery, recovery),
        ai_call_audit=cast(AiCallAuditService, ai_audit),
        ai_call_deadlines={"contract_field_extraction": 120},
    )

    with caplog.at_level(logging.WARNING, logger="finaudit.maintenance"):
        assert run_maintenance_iteration(runtime) == RecoveryResult("idle")

    assert caplog.messages == [f"AI_AUDIT_PROJECTION outcome={projection_status.value}"]


def test_maintenance_iteration_warns_for_ai_audit_outcome_unknown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recovery = _Recovery(RecoveryResult("idle"), RecoveryResult("idle"))
    ai_audit = _AiCallAudit(
        AiCallProjectionResult(AiCallProjectionStatus.IDLE),
        AiCallReconcileResult(AiCallReconcileStatus.OUTCOME_UNKNOWN),
    )
    runtime = MaintenanceProcessRuntime(
        worker=_worker_runtime(),
        recovery=cast(FileJobRecovery, recovery),
        ai_call_audit=cast(AiCallAuditService, ai_audit),
        ai_call_deadlines={"contract_field_extraction": 120},
    )

    with caplog.at_level(logging.WARNING, logger="finaudit.maintenance"):
        assert run_maintenance_iteration(runtime) == RecoveryResult("idle")

    assert caplog.messages == ["AI_AUDIT_RECONCILE outcome=outcome_unknown"]


def test_worker_runtime_disposes_engine_when_dependency_construction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _DisposableEngine()
    monkeypatch.setattr("app.workers.runtime.create_application_engine", lambda settings: engine)
    monkeypatch.setattr(
        "app.workers.runtime.create_session_factory",
        lambda active_engine: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.workers.runtime.create_ocr_engine",
        lambda settings: (_ for _ in ()).throw(RuntimeError("synthetic failure")),
    )

    with pytest.raises(RuntimeError, match="synthetic failure"):
        create_file_worker_runtime(cast(Settings, SimpleNamespace()))

    assert engine.disposed is True


def test_worker_runtime_disposes_engine_when_qdrant_construction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _DisposableEngine()
    monkeypatch.setattr("app.workers.runtime.create_application_engine", lambda settings: engine)
    monkeypatch.setattr(
        "app.workers.runtime.create_session_factory",
        lambda active_engine: SimpleNamespace(),
    )
    monkeypatch.setattr("app.workers.runtime.create_ocr_engine", lambda settings: SimpleNamespace())
    monkeypatch.setattr(
        "app.workers.runtime.create_pdf_renderer", lambda settings: SimpleNamespace()
    )
    monkeypatch.setattr(
        "app.workers.runtime.MinioFileRuntimeAdapter",
        lambda settings: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.workers.runtime.create_malware_scanner", lambda settings: SimpleNamespace()
    )
    monkeypatch.setattr(
        "app.workers.runtime.QdrantVectorAdapter",
        lambda settings: (_ for _ in ()).throw(RuntimeError("synthetic qdrant failure")),
    )

    with pytest.raises(RuntimeError, match="synthetic qdrant failure"):
        create_file_worker_runtime(cast(Settings, SimpleNamespace(max_upload_size_mb=10)))

    assert engine.disposed is True


def test_dispatcher_runtime_disposes_engine_when_construction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _DisposableEngine()
    monkeypatch.setattr(
        "app.workers.dispatcher_process.create_celery_app",
        lambda settings: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.workers.dispatcher_process.create_application_engine",
        lambda settings: engine,
    )
    monkeypatch.setattr(
        "app.workers.dispatcher_process.create_session_factory",
        lambda active_engine: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.workers.dispatcher_process.OutboxDispatcher",
        lambda *args: (_ for _ in ()).throw(RuntimeError("synthetic failure")),
    )

    with pytest.raises(RuntimeError, match="synthetic failure"):
        create_dispatcher_runtime(cast(Settings, SimpleNamespace()))

    assert engine.disposed is True
