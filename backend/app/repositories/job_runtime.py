"""Job/Step/Outbox 运行时的 PostgreSQL fencing 与原子转换。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Row, func, select, text
from sqlalchemy.orm import Session

from app.models.audit import AuditReport, AuditTask, AuditTaskExecution, AuditTaskSnapshot
from app.models.document_processing import DocumentParseVersion
from app.models.documents import FileRecord
from app.models.reliability import AsyncJob, AsyncJobStep, OutboxEvent
from app.models.retrieval import (
    DocumentIndexVersion,
    RetrievalEvalResult,
    RetrievalEvalRun,
)
from app.repositories.audit_runtime import AuditRuntimeRepository, LockedAuditCluster

OutboxFailureCode = Literal[
    "BROKER_UNAVAILABLE",
    "BROKER_TIMEOUT",
    "PUBLISH_CONFIRM_UNKNOWN",
    "PROCESSING_LEASE_EXPIRED",
    "UNSUPPORTED_EVENT_VERSION",
    "SERIALIZATION_FAILED",
    "UNKNOWN_DELIVERY_ERROR",
]

_LEASE_RECOVERY_GRACE = timedelta(seconds=15)


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    id: UUID
    organization_id: UUID
    job_type: str
    resource_type: str
    resource_id: UUID
    status: str
    attempt_no: int
    max_attempts: int
    current_attempt_start_step_code: str
    input_json: dict[str, object]
    input_schema_version: int
    handler_registry_version: str
    handler_registry_hash: str
    trace_id: UUID


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    outbox_id: UUID
    event_id: UUID
    job: JobSnapshot
    event_type: str
    event_version: int
    event_sequence: int
    payload_json: dict[str, object]
    attempt_count: int
    trace_id: UUID


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job: JobSnapshot
    step_id: UUID
    step_seq: int
    step_code: str
    worker_id: str
    lease_owner: str
    started_at: datetime
    heartbeat_at: datetime
    lease_expires_at: datetime
    row_version: int


@dataclass(frozen=True, slots=True)
class FileRuntimeSource:
    id: UUID
    organization_id: UUID
    mime_type: str
    size_bytes: int
    sha256: str
    quarantine_bucket: str
    quarantine_object_key: str
    original_bucket: str | None
    original_object_key: str | None
    status: str
    security_scan_status: str
    intended_business_type: str
    auto_process_requested: bool
    uploaded_by: UUID


@dataclass(frozen=True, slots=True)
class FileRecoveryCandidate:
    job: JobSnapshot
    stage: str


@dataclass(frozen=True, slots=True)
class KnowledgeRecoveryCandidate:
    job: JobSnapshot
    stage: str


@dataclass(frozen=True, slots=True)
class AuditRecoveryCandidate:
    job: JobSnapshot
    stage: str


@dataclass(frozen=True, slots=True)
class ReportRecoveryCandidate:
    job: JobSnapshot
    stage: str


@dataclass(frozen=True, slots=True)
class LeaseRecoveryResult:
    outcome: Literal["claimed", "exhausted", "stale"]
    job_id: UUID
    claim: ClaimedJob | None = None


def _job_snapshot(row: Row[tuple[object, ...]] | AsyncJob) -> JobSnapshot:
    return JobSnapshot(
        id=cast(UUID, row.id),
        organization_id=cast(UUID, row.organization_id),
        job_type=cast(str, row.job_type),
        resource_type=cast(str, row.resource_type),
        resource_id=cast(UUID, row.resource_id),
        status=cast(str, row.status),
        attempt_no=cast(int, row.attempt_no),
        max_attempts=cast(int, row.max_attempts),
        current_attempt_start_step_code=cast(str, row.current_attempt_start_step_code),
        input_json=cast(dict[str, object], row.input_json),
        input_schema_version=cast(int, row.input_schema_version),
        handler_registry_version=cast(str, row.handler_registry_version),
        handler_registry_hash=cast(str, row.handler_registry_hash),
        trace_id=cast(UUID, row.trace_id),
    )


class JobRuntimeRepository:
    """调用方持有事务；外部 I/O 绝不能在本仓储方法内执行。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def peek_job(self, job_id: UUID) -> JobSnapshot | None:
        job = self._session.get(AsyncJob, job_id)
        return None if job is None else _job_snapshot(job)

    def file_runtime_source(self, claim: ClaimedJob) -> FileRuntimeSource | None:
        if claim.job.resource_type != "file":
            return None
        row = self._session.execute(
            select(FileRecord).where(
                FileRecord.id == claim.job.resource_id,
                FileRecord.organization_id == claim.job.organization_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return FileRuntimeSource(
            id=row.id,
            organization_id=row.organization_id,
            mime_type=row.detected_mime_type,
            size_bytes=row.size_bytes,
            sha256=row.sha256,
            quarantine_bucket=row.minio_bucket,
            quarantine_object_key=row.minio_object_key,
            original_bucket=row.original_minio_bucket,
            original_object_key=row.original_minio_object_key,
            status=row.status,
            security_scan_status=row.security_scan_status,
            intended_business_type=row.intended_business_type,
            auto_process_requested=row.auto_process_requested,
            uploaded_by=row.uploaded_by,
        )

    def claim_next_outbox(self) -> OutboxClaim | None:
        row = self._session.execute(
            text(
                """
                WITH candidate AS MATERIALIZED (
                    SELECT id
                    FROM public.outbox_events
                    WHERE event_type = 'job.dispatch.requested'
                      AND (
                        status = 'pending'
                        OR (status = 'failed' AND next_attempt_at <= clock_timestamp())
                      )
                    ORDER BY created_at ASC, id ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                ), claimed AS (
                    UPDATE public.outbox_events AS event
                       SET status = 'processing'
                      FROM candidate
                     WHERE event.id = candidate.id
                    RETURNING event.*
                )
                SELECT
                    claimed.id AS outbox_id,
                    claimed.event_id,
                    claimed.event_type,
                    claimed.event_version,
                    claimed.event_sequence,
                    claimed.payload_json,
                    claimed.attempt_count,
                    claimed.trace_id AS outbox_trace_id,
                    job.id,
                    job.organization_id,
                    job.job_type,
                    job.resource_type,
                    job.resource_id,
                    job.status,
                    job.attempt_no,
                    job.max_attempts,
                    job.current_attempt_start_step_code,
                    job.input_json,
                    job.input_schema_version,
                    job.handler_registry_version,
                    job.handler_registry_hash,
                    job.trace_id
                FROM claimed
                JOIN public.async_jobs AS job ON job.id = claimed.aggregate_id
                """
            )
        ).one_or_none()
        if row is None:
            return None
        return OutboxClaim(
            outbox_id=cast(UUID, row.outbox_id),
            event_id=cast(UUID, row.event_id),
            job=_job_snapshot(row),
            event_type=cast(str, row.event_type),
            event_version=cast(int, row.event_version),
            event_sequence=cast(int, row.event_sequence),
            payload_json=cast(dict[str, object], row.payload_json),
            attempt_count=cast(int, row.attempt_count),
            trace_id=cast(UUID, row.outbox_trace_id),
        )

    def next_expired_processing_outbox(self) -> OutboxClaim | None:
        row = self._session.execute(
            text(
                """
                SELECT
                    event.id AS outbox_id,
                    event.event_id,
                    event.event_type,
                    event.event_version,
                    event.event_sequence,
                    event.payload_json,
                    event.attempt_count,
                    event.trace_id AS outbox_trace_id,
                    job.id,
                    job.organization_id,
                    job.job_type,
                    job.resource_type,
                    job.resource_id,
                    job.status,
                    job.attempt_no,
                    job.max_attempts,
                    job.current_attempt_start_step_code,
                    job.input_json,
                    job.input_schema_version,
                    job.handler_registry_version,
                    job.handler_registry_hash,
                    job.trace_id
                FROM public.outbox_events AS event
                JOIN public.async_jobs AS job ON job.id = event.aggregate_id
                WHERE event.event_type = 'job.dispatch.requested'
                  AND event.status = 'processing'
                  AND event.next_attempt_at <= clock_timestamp()
                ORDER BY event.next_attempt_at ASC, event.id ASC
                LIMIT 1
                """
            )
        ).one_or_none()
        if row is None:
            return None
        return OutboxClaim(
            outbox_id=cast(UUID, row.outbox_id),
            event_id=cast(UUID, row.event_id),
            job=_job_snapshot(row),
            event_type=cast(str, row.event_type),
            event_version=cast(int, row.event_version),
            event_sequence=cast(int, row.event_sequence),
            payload_json=cast(dict[str, object], row.payload_json),
            attempt_count=cast(int, row.attempt_count),
            trace_id=cast(UUID, row.outbox_trace_id),
        )

    def mark_outbox_published(self, claim: OutboxClaim) -> bool:
        event_id = self._session.execute(
            text(
                """
                UPDATE public.outbox_events
                   SET status = 'published'
                 WHERE id = :outbox_id
                   AND status = 'processing'
                   AND attempt_count = :attempt_count
                RETURNING id
                """
            ),
            {
                "outbox_id": claim.outbox_id,
                "attempt_count": claim.attempt_count,
            },
        ).scalar_one_or_none()
        return event_id is not None

    def mark_outbox_failure(
        self,
        claim: OutboxClaim,
        *,
        error_code: OutboxFailureCode,
        broker_called: bool,
    ) -> bool:
        """按 attempt fencing 记录发送失败，并在最终失败时原子终结 queued Job。"""

        job = self._session.execute(
            select(AsyncJob).where(AsyncJob.id == claim.job.id).with_for_update(of=AsyncJob)
        ).scalar_one_or_none()
        event = self._session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.id == claim.outbox_id)
            .with_for_update(of=OutboxEvent)
        ).scalar_one_or_none()
        if (
            job is None
            or event is None
            or event.status != "processing"
            or event.attempt_count != claim.attempt_count
        ):
            return False

        deterministic_failure = not broker_called and error_code in {
            "UNSUPPORTED_EVENT_VERSION",
            "SERIALIZATION_FAILED",
        }
        recoverable_failure = error_code in {
            "BROKER_UNAVAILABLE",
            "BROKER_TIMEOUT",
            "PUBLISH_CONFIRM_UNKNOWN",
            "PROCESSING_LEASE_EXPIRED",
        }
        if claim.attempt_count < 8 and recoverable_failure:
            event.status = "failed"
            event.last_error = error_code
            self._session.flush()
            return True

        event.status = "dead_letter"
        event.last_error = error_code
        self._session.flush()
        if job.status != "queued":
            return True

        outcome_unknown = error_code in {
            "BROKER_TIMEOUT",
            "PUBLISH_CONFIRM_UNKNOWN",
            "PROCESSING_LEASE_EXPIRED",
            "UNKNOWN_DELIVERY_ERROR",
        }
        terminal_code = "JOB_DISPATCH_OUTCOME_UNKNOWN" if outcome_unknown else "JOB_DISPATCH_FAILED"
        terminal_message = (
            "dispatch outcome is unknown"
            if outcome_unknown
            else (
                "dispatch contract validation failed"
                if deterministic_failure
                else "dispatch attempts were exhausted"
            )
        )
        updated = self._session.execute(
            text(
                """
                WITH transition_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                )
                UPDATE public.async_jobs AS job
                   SET status = 'failed',
                       finished_at = transition_clock.t,
                       error_code = :error_code,
                       error_message = :error_message,
                       row_version = row_version + 1
                  FROM transition_clock
                 WHERE job.id = :job_id
                   AND job.status = 'queued'
                   AND job.row_version = :row_version
                RETURNING job.id
                """
            ),
            {
                "error_code": terminal_code,
                "error_message": terminal_message,
                "job_id": job.id,
                "row_version": job.row_version,
            },
        ).scalar_one_or_none()
        return updated is not None

    def claim_job(
        self,
        *,
        job_id: UUID,
        event_id: UUID,
        event_schema_version: int,
        worker_id: str,
        start_step_seq: int,
    ) -> ClaimedJob | None:
        """锁业务资源→Job→Outbox，并以一个 writable CTE 创建首次 Step。"""

        classification = self._session.execute(
            select(AsyncJob.resource_type, AsyncJob.resource_id).where(AsyncJob.id == job_id)
        ).one_or_none()
        if classification is None:
            return None
        locked_audit_execution: AuditTaskExecution | None = None
        locked_audit_snapshot: AuditTaskSnapshot | None = None
        locked_report: AuditReport | None = None
        locked_report_execution: AuditTaskExecution | None = None
        if classification.resource_type == "audit_task_execution":
            audit_identity = self._session.execute(
                select(
                    AuditTaskExecution.audit_task_id,
                    AuditTaskExecution.organization_id,
                ).where(AuditTaskExecution.id == classification.resource_id)
            ).one_or_none()
            if audit_identity is None:
                return None
            locked_task = self._session.execute(
                select(AuditTask)
                .where(
                    AuditTask.id == audit_identity.audit_task_id,
                    AuditTask.organization_id == audit_identity.organization_id,
                    AuditTask.deleted_at.is_(None),
                )
                .with_for_update(of=AuditTask)
            ).scalar_one_or_none()
            if locked_task is None:
                return None
            locked_audit_execution = self._session.execute(
                select(AuditTaskExecution)
                .where(
                    AuditTaskExecution.id == classification.resource_id,
                    AuditTaskExecution.audit_task_id == locked_task.id,
                    AuditTaskExecution.organization_id == locked_task.organization_id,
                )
                .with_for_update(of=AuditTaskExecution)
            ).scalar_one_or_none()
            if locked_audit_execution is None:
                return None
            locked_audit_snapshot = self._session.execute(
                select(AuditTaskSnapshot)
                .where(AuditTaskSnapshot.execution_id == locked_audit_execution.id)
                .with_for_update(of=AuditTaskSnapshot)
            ).scalar_one_or_none()
            if locked_audit_snapshot is None:
                return None
            locked_file = None
        elif classification.resource_type == "audit_report":
            report_identity = self._session.execute(
                select(AuditReport.organization_id, AuditReport.execution_id).where(
                    AuditReport.id == classification.resource_id
                )
            ).one_or_none()
            if report_identity is None:
                return None
            report_cluster = AuditRuntimeRepository(self._session).lock_cluster(
                report_identity.organization_id,
                report_identity.execution_id,
            )
            if report_cluster is None:
                return None
            locked_report = next(
                (
                    report
                    for report in report_cluster.reports
                    if report.id == classification.resource_id
                ),
                None,
            )
            if locked_report is None:
                return None
            locked_report_execution = report_cluster.execution
            locked_file = None
        elif classification.resource_type == "file":
            locked_file = self._session.execute(
                select(FileRecord)
                .where(FileRecord.id == classification.resource_id)
                .with_for_update(of=FileRecord)
            ).scalar_one_or_none()
            if locked_file is None:
                return None
        else:
            locked_file = None

        job = self._session.execute(
            select(AsyncJob).where(AsyncJob.id == job_id).with_for_update(of=AsyncJob)
        ).scalar_one_or_none()
        if job is None or job.status != "queued":
            return None
        event = self._session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.event_id == event_id)
            .with_for_update(of=OutboxEvent)
        ).scalar_one_or_none()
        if event is None or not self._claim_identity_matches(job, event, event_schema_version):
            return None
        existing_step = self._session.execute(
            select(AsyncJobStep.id).where(
                AsyncJobStep.job_id == job.id,
                AsyncJobStep.attempt_no == job.attempt_no + 1,
            )
        ).scalar_one_or_none()
        if existing_step is not None:
            return None

        if job.resource_type == "audit_task_execution":
            if (
                locked_audit_execution is None
                or locked_audit_snapshot is None
                or job.job_type != "audit_execute"
                or job.current_attempt_start_step_code != "evaluate"
                or locked_audit_execution.status != "queued"
                or locked_audit_execution.job_id != job.id
                or locked_audit_execution.snapshot_sha256 != locked_audit_snapshot.facts_sha256
                or job.input_json
                != {
                    "execution_id": str(locked_audit_execution.id),
                    "snapshot_id": str(locked_audit_snapshot.id),
                    "snapshot_sha256": locked_audit_snapshot.facts_sha256,
                }
            ):
                return None
        elif job.resource_type == "audit_report":
            if (
                locked_report is None
                or locked_report_execution is None
                or job.job_type != "report_generate"
                or job.current_attempt_start_step_code != "generate"
                or locked_report.status != "queued"
                or locked_report.job_id != job.id
                or locked_report_execution.status != "completed"
                or job.organization_id != locked_report.organization_id
                or job.resource_id != locked_report.id
                or job.input_json
                != {
                    "report_id": str(locked_report.id),
                    "execution_id": str(locked_report.execution_id),
                    "payload_sha256": locked_report.payload_sha256,
                }
            ):
                return None
        elif job.resource_type == "file" and job.current_attempt_start_step_code == "scan":
            updated_file = self._session.execute(
                text(
                    """
                    UPDATE public.files
                       SET status = 'validating',
                           row_version = row_version + 1,
                           updated_at = clock_timestamp(),
                           updated_by = NULL
                     WHERE id = :resource_id
                       AND organization_id = :organization_id
                       AND status IN ('uploaded', 'validating')
                       AND security_scan_status = 'pending'
                    RETURNING id
                    """
                ),
                {
                    "resource_id": job.resource_id,
                    "organization_id": job.organization_id,
                },
            ).scalar_one_or_none()
            if updated_file is None:
                return None
        elif job.resource_type == "file" and job.current_attempt_start_step_code == "parse":
            if (
                locked_file is None
                or locked_file.status != "stored"
                or locked_file.security_scan_status != "clean"
                or locked_file.original_minio_bucket is None
                or locked_file.original_minio_object_key is None
            ):
                return None
        elif job.resource_type == "file" and job.current_attempt_start_step_code == "extract":
            if locked_file is None or not self._financial_extract_source_available(
                job,
                locked_file,
            ):
                return None
        elif job.resource_type == "file":
            return None

        step_id = uuid4()
        row = self._session.execute(
            text(
                """
                WITH claimed AS (
                    UPDATE public.async_jobs
                       SET status = 'running',
                           stage = current_attempt_start_step_code,
                           attempt_no = attempt_no + 1,
                           worker_id = :worker_id,
                           row_version = row_version + 1
                     WHERE id = :job_id
                       AND status = 'queued'
                       AND row_version = :row_version
                    RETURNING id, organization_id, job_type, resource_type, resource_id,
                              status, attempt_no, max_attempts,
                              current_attempt_start_step_code, input_json,
                              input_schema_version, handler_registry_version,
                              handler_registry_hash, trace_id, stage, worker_id,
                              lease_owner, started_at, heartbeat_at, lease_expires_at,
                              row_version
                ), created_step AS (
                    INSERT INTO public.async_job_steps (
                        id, job_id, step_seq, step_code, status, attempt_no,
                        started_at, trace_id
                    )
                    SELECT :step_id, id, :step_seq, stage, 'running', attempt_no,
                           started_at, trace_id
                      FROM claimed
                    RETURNING id
                )
                SELECT claimed.*, created_step.id AS step_id
                  FROM claimed CROSS JOIN created_step
                """
            ),
            {
                "job_id": job.id,
                "row_version": job.row_version,
                "worker_id": worker_id,
                "step_id": step_id,
                "step_seq": start_step_seq,
            },
        ).one_or_none()
        if row is None:
            return None
        if locked_audit_execution is not None:
            locked_audit_execution.status = "running"
            locked_audit_execution.started_at = cast(datetime, row.started_at)
            locked_audit_execution.row_version += 1
            self._session.flush()
        if locked_report is not None:
            locked_report.status = "generating"
            locked_report.failure_code = None
            locked_report.row_version += 1
            self._session.flush()
        return self._claimed_job(row, start_step_seq)

    @staticmethod
    def _claim_identity_matches(
        job: AsyncJob,
        event: OutboxEvent,
        event_schema_version: int,
    ) -> bool:
        return bool(
            event.aggregate_type == "async_job"
            and event.aggregate_id == job.id
            and event.event_type == "job.dispatch.requested"
            and event.event_version == event_schema_version == 1
            and event.event_sequence == job.attempt_no + 1
            and event.payload_json == {"job_id": str(job.id)}
            and event.status in {"processing", "failed", "published"}
        )

    @staticmethod
    def _claimed_job(row: Row[tuple[object, ...]], step_seq: int) -> ClaimedJob:
        return ClaimedJob(
            job=_job_snapshot(row),
            step_id=cast(UUID, row.step_id),
            step_seq=step_seq,
            step_code=cast(str, row.stage),
            worker_id=cast(str, row.worker_id),
            lease_owner=cast(str, row.lease_owner),
            started_at=cast(datetime, row.started_at),
            heartbeat_at=cast(datetime, row.heartbeat_at),
            lease_expires_at=cast(datetime, row.lease_expires_at),
            row_version=cast(int, row.row_version),
        )

    def heartbeat(self, claim: ClaimedJob) -> ClaimedJob | None:
        row = self._session.execute(
            text(
                """
                WITH heartbeat_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                )
                UPDATE public.async_jobs AS job
                   SET heartbeat_at = heartbeat_clock.t,
                       lease_expires_at = heartbeat_clock.t + interval '60 seconds',
                       row_version = job.row_version + 1
                  FROM heartbeat_clock
                 WHERE job.id = :job_id
                   AND job.status IN ('running', 'cancel_requested')
                   AND job.attempt_no = :attempt_no
                   AND job.worker_id = :worker_id
                   AND job.lease_owner = :lease_owner
                   AND job.row_version = :row_version
                   AND heartbeat_clock.t < job.lease_expires_at
                RETURNING job.id, job.organization_id, job.job_type,
                          job.resource_type, job.resource_id, job.status,
                          job.attempt_no, job.max_attempts,
                          job.current_attempt_start_step_code, job.input_json,
                          job.input_schema_version, job.handler_registry_version,
                          job.handler_registry_hash, job.trace_id, job.stage,
                          job.worker_id, job.lease_owner, job.started_at,
                          job.heartbeat_at, job.lease_expires_at, job.row_version,
                          CAST(:step_id AS uuid) AS step_id
                """
            ),
            {
                "job_id": claim.job.id,
                "attempt_no": claim.job.attempt_no,
                "worker_id": claim.worker_id,
                "lease_owner": claim.lease_owner,
                "row_version": claim.row_version,
                "step_id": claim.step_id,
            },
        ).one_or_none()
        return None if row is None else self._claimed_job(row, claim.step_seq)

    def advance_step(
        self,
        claim: ClaimedJob,
        *,
        summary: dict[str, object],
        next_step_code: str,
        next_step_seq: int,
    ) -> ClaimedJob | None:
        next_step_id = uuid4()
        row = self._session.execute(
            text(
                """
                WITH transition_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                ), finished AS (
                    UPDATE public.async_job_steps AS step
                       SET status = 'succeeded',
                           finished_at = transition_clock.t,
                           summary_json = CAST(:summary_json AS jsonb)
                      FROM transition_clock, public.async_jobs AS job
                     WHERE step.id = :step_id
                       AND step.job_id = job.id
                       AND job.id = :job_id
                       AND step.status = 'running'
                       AND step.attempt_no = :attempt_no
                       AND job.status = 'running'
                       AND job.worker_id = :worker_id
                       AND job.lease_owner = :lease_owner
                       AND job.row_version = :row_version
                       AND transition_clock.t < job.lease_expires_at
                    RETURNING step.job_id
                ), advanced AS (
                    UPDATE public.async_jobs AS job
                       SET stage = :next_step_code,
                           heartbeat_at = transition_clock.t,
                           lease_expires_at = transition_clock.t + interval '60 seconds',
                           row_version = row_version + 1
                      FROM transition_clock, finished
                     WHERE job.id = finished.job_id
                    RETURNING job.id, job.organization_id, job.job_type,
                              job.resource_type, job.resource_id, job.status,
                              job.attempt_no, job.max_attempts,
                              job.current_attempt_start_step_code, job.input_json,
                              job.input_schema_version, job.handler_registry_version,
                              job.handler_registry_hash, job.trace_id, job.stage,
                              job.worker_id, job.lease_owner, job.started_at,
                              job.heartbeat_at, job.lease_expires_at, job.row_version
                ), created_step AS (
                    INSERT INTO public.async_job_steps (
                        id, job_id, step_seq, step_code, status, attempt_no,
                        started_at, trace_id
                    )
                    SELECT :next_step_id, id, :next_step_seq, stage, 'running',
                           attempt_no, heartbeat_at, trace_id
                      FROM advanced
                    RETURNING id
                )
                SELECT advanced.*, created_step.id AS step_id
                  FROM advanced CROSS JOIN created_step
                """
            ),
            {
                "summary_json": json.dumps(summary, separators=(",", ":"), sort_keys=True),
                "step_id": claim.step_id,
                "job_id": claim.job.id,
                "attempt_no": claim.job.attempt_no,
                "worker_id": claim.worker_id,
                "lease_owner": claim.lease_owner,
                "row_version": claim.row_version,
                "next_step_code": next_step_code,
                "next_step_seq": next_step_seq,
                "next_step_id": next_step_id,
            },
        ).one_or_none()
        return None if row is None else self._claimed_job(row, next_step_seq)

    def complete_file_scan_clean(
        self,
        claim: ClaimedJob,
        *,
        summary: dict[str, object],
        original_bucket: str,
        original_object_key: str,
        next_step_code: str | None,
        next_step_seq: int | None,
    ) -> ClaimedJob | bool | None:
        if claim.job.resource_type != "file":
            return None
        if (next_step_code is None) != (next_step_seq is None):
            raise ValueError("next step code and sequence must be provided together")
        if next_step_code is None:
            updated = self._session.execute(
                text(
                    """
                    WITH transition_clock AS MATERIALIZED (
                        SELECT clock_timestamp() AS t
                    ), finished_step AS (
                        UPDATE public.async_job_steps AS step
                           SET status = 'succeeded',
                               finished_at = transition_clock.t,
                               summary_json = CAST(:summary_json AS jsonb)
                          FROM transition_clock, public.async_jobs AS current_job
                         WHERE step.id = :step_id
                           AND step.job_id = current_job.id
                           AND current_job.id = :job_id
                           AND step.status = 'running'
                           AND step.step_code = 'scan'
                           AND current_job.status = 'running'
                           AND current_job.attempt_no = :attempt_no
                           AND current_job.worker_id = :worker_id
                           AND current_job.lease_owner = :lease_owner
                           AND current_job.row_version = :row_version
                           AND transition_clock.t < current_job.lease_expires_at
                        RETURNING step.job_id, transition_clock.t
                    ), stored_file AS (
                        UPDATE public.files AS file
                           SET status = 'stored',
                               security_scan_status = 'clean',
                               original_minio_bucket = :original_bucket,
                               original_minio_object_key = :original_object_key,
                               stored_at = finished_step.t,
                               row_version = file.row_version + 1,
                               updated_at = finished_step.t,
                               updated_by = NULL
                          FROM finished_step, public.async_jobs AS current_job
                         WHERE current_job.id = finished_step.job_id
                           AND file.id = current_job.resource_id
                           AND file.organization_id = current_job.organization_id
                           AND file.status = 'validating'
                           AND file.security_scan_status = 'pending'
                        RETURNING current_job.id, finished_step.t
                    )
                    UPDATE public.async_jobs AS job
                       SET status = 'succeeded',
                           finished_at = stored_file.t,
                           worker_id = NULL,
                           lease_owner = NULL,
                           lease_expires_at = NULL,
                           heartbeat_at = NULL,
                           row_version = job.row_version + 1
                      FROM stored_file
                     WHERE job.id = stored_file.id
                    RETURNING job.id
                    """
                ),
                {
                    "summary_json": json.dumps(summary, separators=(",", ":"), sort_keys=True),
                    "step_id": claim.step_id,
                    "job_id": claim.job.id,
                    "attempt_no": claim.job.attempt_no,
                    "worker_id": claim.worker_id,
                    "lease_owner": claim.lease_owner,
                    "row_version": claim.row_version,
                    "original_bucket": original_bucket,
                    "original_object_key": original_object_key,
                },
            ).scalar_one_or_none()
            return updated is not None

        next_step_id = uuid4()
        row = self._session.execute(
            text(
                """
                WITH transition_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                ), finished_step AS (
                    UPDATE public.async_job_steps AS step
                       SET status = 'succeeded',
                           finished_at = transition_clock.t,
                           summary_json = CAST(:summary_json AS jsonb)
                      FROM transition_clock, public.async_jobs AS current_job
                     WHERE step.id = :step_id
                       AND step.job_id = current_job.id
                       AND current_job.id = :job_id
                       AND step.status = 'running'
                       AND step.step_code = 'scan'
                       AND current_job.status = 'running'
                       AND current_job.attempt_no = :attempt_no
                       AND current_job.worker_id = :worker_id
                       AND current_job.lease_owner = :lease_owner
                       AND current_job.row_version = :row_version
                       AND transition_clock.t < current_job.lease_expires_at
                    RETURNING step.job_id, transition_clock.t
                ), stored_file AS (
                    UPDATE public.files AS file
                       SET status = 'stored',
                           security_scan_status = 'clean',
                           original_minio_bucket = :original_bucket,
                           original_minio_object_key = :original_object_key,
                           stored_at = finished_step.t,
                           row_version = file.row_version + 1,
                           updated_at = finished_step.t,
                           updated_by = NULL
                      FROM finished_step, public.async_jobs AS current_job
                     WHERE current_job.id = finished_step.job_id
                       AND file.id = current_job.resource_id
                       AND file.organization_id = current_job.organization_id
                       AND file.status = 'validating'
                       AND file.security_scan_status = 'pending'
                    RETURNING current_job.id, finished_step.t
                ), advanced AS (
                    UPDATE public.async_jobs AS job
                       SET stage = :next_step_code,
                           heartbeat_at = stored_file.t,
                           lease_expires_at = stored_file.t + interval '60 seconds',
                           row_version = job.row_version + 1
                      FROM stored_file
                     WHERE job.id = stored_file.id
                    RETURNING job.id, job.organization_id, job.job_type,
                              job.resource_type, job.resource_id, job.status,
                              job.attempt_no, job.max_attempts,
                              job.current_attempt_start_step_code, job.input_json,
                              job.input_schema_version, job.handler_registry_version,
                              job.handler_registry_hash, job.trace_id, job.stage,
                              job.worker_id, job.lease_owner, job.started_at,
                              job.heartbeat_at, job.lease_expires_at, job.row_version
                ), created_step AS (
                    INSERT INTO public.async_job_steps (
                        id, job_id, step_seq, step_code, status, attempt_no,
                        started_at, trace_id
                    )
                    SELECT :next_step_id, id, :next_step_seq, stage, 'running',
                           attempt_no, heartbeat_at, trace_id
                      FROM advanced
                    RETURNING id
                )
                SELECT advanced.*, created_step.id AS step_id
                  FROM advanced CROSS JOIN created_step
                """
            ),
            {
                "summary_json": json.dumps(summary, separators=(",", ":"), sort_keys=True),
                "step_id": claim.step_id,
                "job_id": claim.job.id,
                "attempt_no": claim.job.attempt_no,
                "worker_id": claim.worker_id,
                "lease_owner": claim.lease_owner,
                "row_version": claim.row_version,
                "original_bucket": original_bucket,
                "original_object_key": original_object_key,
                "next_step_code": next_step_code,
                "next_step_seq": next_step_seq,
                "next_step_id": next_step_id,
            },
        ).one_or_none()
        return None if row is None else self._claimed_job(row, cast(int, next_step_seq))

    def fail_file_scan(
        self,
        claim: ClaimedJob,
        *,
        summary: dict[str, object],
        scan_status: Literal["infected", "scan_failed", "unsupported", "not_configured"],
        job_error_code: str,
        rejection_code: str | None,
    ) -> bool:
        if claim.job.resource_type != "file":
            return False
        file_status = "rejected" if scan_status in {"infected", "unsupported"} else "validating"
        retryable = (
            job_error_code
            in {
                "DATABASE_TRANSIENT",
                "DEPENDENCY_TIMEOUT",
                "DEPENDENCY_UNAVAILABLE",
                "RATE_LIMITED",
                "STORAGE_TRANSIENT",
                "WORKER_LOST",
            }
            and claim.job.attempt_no < claim.job.max_attempts
        )
        updated = self._session.execute(
            text(
                """
                WITH transition_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                ), finished_step AS (
                    UPDATE public.async_job_steps AS step
                       SET status = 'failed',
                           finished_at = transition_clock.t,
                           summary_json = CAST(:summary_json AS jsonb),
                           error_code = :job_error_code
                      FROM transition_clock, public.async_jobs AS current_job
                     WHERE step.id = :step_id
                       AND step.job_id = current_job.id
                       AND current_job.id = :job_id
                       AND step.status = 'running'
                       AND step.step_code = 'scan'
                       AND current_job.status = 'running'
                       AND current_job.attempt_no = :attempt_no
                       AND current_job.worker_id = :worker_id
                       AND current_job.lease_owner = :lease_owner
                       AND current_job.row_version = :row_version
                       AND transition_clock.t < current_job.lease_expires_at
                    RETURNING step.job_id, transition_clock.t
                ), failed_file AS (
                    UPDATE public.files AS file
                       SET status = :file_status,
                           security_scan_status = :scan_status,
                           rejection_code = :rejection_code,
                           rejection_message = NULL,
                           row_version = file.row_version + 1,
                           updated_at = finished_step.t,
                           updated_by = NULL
                      FROM finished_step, public.async_jobs AS current_job
                     WHERE current_job.id = finished_step.job_id
                       AND file.id = current_job.resource_id
                       AND file.organization_id = current_job.organization_id
                       AND file.status = 'validating'
                       AND file.security_scan_status = 'pending'
                    RETURNING current_job.id, finished_step.t
                )
                UPDATE public.async_jobs AS job
                   SET status = 'failed',
                       finished_at = failed_file.t,
                       error_code = :job_error_code,
                       error_message = :error_message,
                       next_retry_at = CASE WHEN :retryable THEN failed_file.t ELSE NULL END,
                       worker_id = NULL,
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       heartbeat_at = NULL,
                       row_version = job.row_version + 1
                  FROM failed_file
                 WHERE job.id = failed_file.id
                RETURNING job.id
                """
            ),
            {
                "summary_json": json.dumps(summary, separators=(",", ":"), sort_keys=True),
                "job_error_code": job_error_code,
                "step_id": claim.step_id,
                "job_id": claim.job.id,
                "attempt_no": claim.job.attempt_no,
                "worker_id": claim.worker_id,
                "lease_owner": claim.lease_owner,
                "row_version": claim.row_version,
                "file_status": file_status,
                "scan_status": scan_status,
                "rejection_code": rejection_code,
                "retryable": retryable,
                "error_message": (
                    "scanner dependency unavailable"
                    if retryable
                    else "file was rejected by the security gate"
                ),
            },
        ).scalar_one_or_none()
        return updated is not None

    def finish_job(
        self,
        claim: ClaimedJob,
        *,
        status: Literal["succeeded", "failed", "cancelled"],
        summary: dict[str, object],
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        if status == "succeeded":
            step_status = "succeeded"
            next_retry = False
        elif status == "cancelled":
            step_status = "cancelled"
            error_code = "JOB_CANCELLED"
            error_message = None
            next_retry = False
        else:
            step_status = "failed"
            next_retry = (
                error_code
                in {
                    "DATABASE_TRANSIENT",
                    "DEPENDENCY_TIMEOUT",
                    "DEPENDENCY_UNAVAILABLE",
                    "RATE_LIMITED",
                    "STORAGE_TRANSIENT",
                    "WORKER_LOST",
                }
                and claim.job.attempt_no < claim.job.max_attempts
            )
        updated = self._session.execute(
            text(
                """
                WITH transition_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                ), finished_step AS (
                    UPDATE public.async_job_steps AS step
                       SET status = :step_status,
                           finished_at = transition_clock.t,
                           summary_json = CAST(:summary_json AS jsonb),
                           error_code = :error_code
                      FROM transition_clock, public.async_jobs AS current_job
                     WHERE step.id = :step_id
                       AND step.job_id = current_job.id
                       AND current_job.id = :job_id
                       AND step.status = 'running'
                       AND step.attempt_no = :attempt_no
                       AND current_job.status = :required_status
                       AND current_job.worker_id = :worker_id
                       AND current_job.lease_owner = :lease_owner
                       AND current_job.row_version = :row_version
                       AND transition_clock.t < current_job.lease_expires_at
                    RETURNING step.job_id, transition_clock.t
                )
                UPDATE public.async_jobs AS job
                   SET status = :status,
                       finished_at = finished_step.t,
                       error_code = :error_code,
                       error_message = :error_message,
                       next_retry_at = CASE WHEN :next_retry THEN finished_step.t ELSE NULL END,
                       worker_id = NULL,
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       heartbeat_at = NULL,
                       row_version = job.row_version + 1
                  FROM finished_step
                 WHERE job.id = finished_step.job_id
                RETURNING job.id
                """
            ),
            {
                "step_status": step_status,
                "summary_json": json.dumps(summary, separators=(",", ":"), sort_keys=True),
                "error_code": error_code,
                "step_id": claim.step_id,
                "job_id": claim.job.id,
                "attempt_no": claim.job.attempt_no,
                "required_status": "cancel_requested" if status == "cancelled" else "running",
                "worker_id": claim.worker_id,
                "lease_owner": claim.lease_owner,
                "row_version": claim.row_version,
                "status": status,
                "error_message": error_message,
                "next_retry": next_retry,
            },
        ).scalar_one_or_none()
        return updated is not None

    def finish_cancel_requested(self, claim: ClaimedJob) -> bool:
        """以 attempt/worker/lease fencing 采用已请求取消，不依赖旧 row_version。"""

        updated = self._session.execute(
            text(
                """
                WITH transition_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                ), finished_step AS (
                    UPDATE public.async_job_steps AS step
                       SET status = 'cancelled',
                           finished_at = transition_clock.t,
                           summary_json = '{}'::jsonb,
                           error_code = 'JOB_CANCELLED'
                      FROM transition_clock, public.async_jobs AS current_job
                     WHERE step.id = :step_id
                       AND step.job_id = current_job.id
                       AND current_job.id = :job_id
                       AND step.status = 'running'
                       AND step.attempt_no = :attempt_no
                       AND current_job.status = 'cancel_requested'
                       AND current_job.worker_id = :worker_id
                       AND current_job.lease_owner = :lease_owner
                    RETURNING step.job_id, transition_clock.t
                )
                UPDATE public.async_jobs AS job
                   SET status = 'cancelled',
                       finished_at = finished_step.t,
                       error_code = 'JOB_CANCELLED',
                       error_message = NULL,
                       next_retry_at = NULL,
                       worker_id = NULL,
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       heartbeat_at = NULL,
                       row_version = job.row_version + 1
                  FROM finished_step
                 WHERE job.id = finished_step.job_id
                RETURNING job.id
                """
            ),
            {
                "step_id": claim.step_id,
                "job_id": claim.job.id,
                "attempt_no": claim.job.attempt_no,
                "worker_id": claim.worker_id,
                "lease_owner": claim.lease_owner,
            },
        ).scalar_one_or_none()
        return updated is not None

    def retryable_file_candidates(self, *, limit: int = 32) -> tuple[FileRecoveryCandidate, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid recovery candidate limit")
        jobs = self._session.scalars(
            select(AsyncJob)
            .where(
                AsyncJob.resource_type == "file",
                AsyncJob.job_type.in_(
                    ("file_process", "file_scan", "invoice_extract", "contract_extract")
                ),
                AsyncJob.status == "failed",
                AsyncJob.next_retry_at.is_not(None),
                AsyncJob.next_retry_at <= func.clock_timestamp(),
                AsyncJob.attempt_no < AsyncJob.max_attempts,
            )
            .order_by(AsyncJob.next_retry_at, AsyncJob.id)
            .limit(limit)
        ).all()
        return tuple(
            FileRecoveryCandidate(_job_snapshot(job), job.stage)
            for job in jobs
            if job.stage is not None
        )

    def expired_file_candidates(self, *, limit: int = 32) -> tuple[FileRecoveryCandidate, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid recovery candidate limit")
        jobs = self._session.scalars(
            select(AsyncJob)
            .where(
                AsyncJob.resource_type == "file",
                AsyncJob.job_type.in_(
                    ("file_process", "file_scan", "invoice_extract", "contract_extract")
                ),
                AsyncJob.status == "running",
                AsyncJob.lease_expires_at.is_not(None),
                AsyncJob.lease_expires_at <= func.clock_timestamp() - text("interval '15 seconds'"),
            )
            .order_by(AsyncJob.lease_expires_at, AsyncJob.id)
            .limit(limit)
        ).all()
        return tuple(
            FileRecoveryCandidate(_job_snapshot(job), job.stage)
            for job in jobs
            if job.stage is not None
        )

    def retryable_knowledge_candidates(
        self, *, limit: int = 32
    ) -> tuple[KnowledgeRecoveryCandidate, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid recovery candidate limit")
        jobs = self._session.scalars(
            select(AsyncJob)
            .where(
                AsyncJob.job_type.in_(("knowledge_index_build", "retrieval_eval")),
                AsyncJob.resource_type.in_(("document_index_version", "retrieval_eval_run")),
                AsyncJob.status == "failed",
                AsyncJob.next_retry_at.is_not(None),
                AsyncJob.next_retry_at <= func.clock_timestamp(),
                AsyncJob.attempt_no < AsyncJob.max_attempts,
            )
            .order_by(AsyncJob.next_retry_at, AsyncJob.id)
            .limit(limit)
        ).all()
        return tuple(
            KnowledgeRecoveryCandidate(_job_snapshot(job), job.stage)
            for job in jobs
            if job.stage is not None
        )

    def expired_knowledge_candidates(
        self, *, limit: int = 32
    ) -> tuple[KnowledgeRecoveryCandidate, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid recovery candidate limit")
        jobs = self._session.scalars(
            select(AsyncJob)
            .where(
                AsyncJob.job_type.in_(("knowledge_index_build", "retrieval_eval")),
                AsyncJob.resource_type.in_(("document_index_version", "retrieval_eval_run")),
                AsyncJob.status == "running",
                AsyncJob.lease_expires_at.is_not(None),
                AsyncJob.lease_expires_at <= func.clock_timestamp() - text("interval '15 seconds'"),
            )
            .order_by(AsyncJob.lease_expires_at, AsyncJob.id)
            .limit(limit)
        ).all()
        return tuple(
            KnowledgeRecoveryCandidate(_job_snapshot(job), job.stage)
            for job in jobs
            if job.stage is not None
        )

    def retryable_audit_candidates(self, *, limit: int = 32) -> tuple[AuditRecoveryCandidate, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid recovery candidate limit")
        jobs = self._session.scalars(
            select(AsyncJob)
            .where(
                AsyncJob.job_type == "audit_execute",
                AsyncJob.resource_type == "audit_task_execution",
                AsyncJob.status == "failed",
                AsyncJob.next_retry_at.is_not(None),
                AsyncJob.next_retry_at <= func.clock_timestamp(),
                AsyncJob.attempt_no < AsyncJob.max_attempts,
            )
            .order_by(AsyncJob.next_retry_at, AsyncJob.id)
            .limit(limit)
        ).all()
        return tuple(
            AuditRecoveryCandidate(_job_snapshot(job), job.stage)
            for job in jobs
            if job.stage is not None
        )

    def retryable_report_candidates(
        self, *, limit: int = 32
    ) -> tuple[ReportRecoveryCandidate, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid recovery candidate limit")
        jobs = self._session.scalars(
            select(AsyncJob)
            .where(
                AsyncJob.job_type == "report_generate",
                AsyncJob.resource_type == "audit_report",
                AsyncJob.status == "failed",
                AsyncJob.next_retry_at.is_not(None),
                AsyncJob.next_retry_at <= func.clock_timestamp(),
                AsyncJob.attempt_no < AsyncJob.max_attempts,
            )
            .order_by(AsyncJob.next_retry_at, AsyncJob.id)
            .limit(limit)
        ).all()
        return tuple(
            ReportRecoveryCandidate(_job_snapshot(job), job.stage)
            for job in jobs
            if job.stage is not None
        )

    def expired_report_candidates(self, *, limit: int = 32) -> tuple[ReportRecoveryCandidate, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid recovery candidate limit")
        jobs = self._session.scalars(
            select(AsyncJob)
            .where(
                AsyncJob.job_type == "report_generate",
                AsyncJob.resource_type == "audit_report",
                AsyncJob.status == "running",
                AsyncJob.lease_expires_at.is_not(None),
                AsyncJob.lease_expires_at <= func.clock_timestamp() - text("interval '15 seconds'"),
            )
            .order_by(AsyncJob.lease_expires_at, AsyncJob.id)
            .limit(limit)
        ).all()
        return tuple(
            ReportRecoveryCandidate(_job_snapshot(job), job.stage)
            for job in jobs
            if job.stage is not None
        )

    def requeue_failed_report_job(self, *, job_id: UUID, start_step_code: str) -> bool:
        """按审核簇→Report→Job 锁序重排可重试报告。"""

        classification = self._session.execute(
            select(AsyncJob.resource_type, AsyncJob.resource_id).where(AsyncJob.id == job_id)
        ).one_or_none()
        if classification is None or classification.resource_type != "audit_report":
            return False
        resource = self._lock_report_resource(classification.resource_id)
        if resource is None:
            return False
        cluster, report = resource
        job = self._session.execute(
            select(AsyncJob).where(AsyncJob.id == job_id).with_for_update(of=AsyncJob)
        ).scalar_one_or_none()
        if (
            job is None
            or job.status != "failed"
            or job.next_retry_at is None
            or job.attempt_no >= job.max_attempts
            or start_step_code != "generate"
            or job.current_attempt_start_step_code != start_step_code
            or report.status != "failed"
            or report.failure_code == "STORAGE_OUTCOME_UNKNOWN"
            or cluster.execution.status != "completed"
            or not self._report_resource_matches(job, cluster, report)
        ):
            return False
        database_now = self._session.scalar(select(func.clock_timestamp()))
        if database_now is None or job.next_retry_at > database_now:
            return False

        report.status = "queued"
        report.failure_code = None
        report.row_version += 1
        self._session.flush()
        job.status = "queued"
        job.stage = None
        job.next_retry_at = None
        job.worker_id = None
        job.started_at = None
        job.finished_at = None
        job.error_code = None
        job.error_message = None
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.row_version += 1
        self._session.flush()
        self._session.add(
            OutboxEvent(
                id=uuid4(),
                aggregate_type="async_job",
                aggregate_id=job.id,
                event_id=uuid4(),
                event_type="job.dispatch.requested",
                event_version=1,
                event_sequence=job.attempt_no + 1,
                payload_json={"job_id": str(job.id)},
                status="pending",
                attempt_count=0,
                next_attempt_at=None,
                published_at=None,
                last_error=None,
                trace_id=job.trace_id,
            )
        )
        self._session.flush()
        return True

    def recover_expired_report_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        start_step_code: str,
        start_step_seq: int,
    ) -> LeaseRecoveryResult:
        """重领生成中的报告；耗尽或执行过期时同步失败关闭。"""

        if not worker_id or len(worker_id) > 100 or start_step_seq <= 0:
            raise ValueError("invalid lease recovery identity")
        classification = self._session.execute(
            select(AsyncJob.resource_type, AsyncJob.resource_id).where(AsyncJob.id == job_id)
        ).one_or_none()
        if classification is None or classification.resource_type != "audit_report":
            return LeaseRecoveryResult("stale", job_id)
        resource = self._lock_report_resource(classification.resource_id)
        if resource is None:
            return LeaseRecoveryResult("stale", job_id)
        cluster, report = resource
        job = self._session.execute(
            select(AsyncJob).where(AsyncJob.id == job_id).with_for_update(of=AsyncJob)
        ).scalar_one_or_none()
        if (
            job is None
            or job.status != "running"
            or job.lease_expires_at is None
            or start_step_code != "generate"
            or job.current_attempt_start_step_code != start_step_code
            or report.status != "generating"
            or not self._report_resource_matches(job, cluster, report)
        ):
            return LeaseRecoveryResult("stale", job_id)
        database_now = self._session.scalar(select(func.clock_timestamp()))
        if database_now is None or database_now < job.lease_expires_at + _LEASE_RECOVERY_GRACE:
            return LeaseRecoveryResult("stale", job_id)
        current_step = self._session.execute(
            select(AsyncJobStep)
            .where(
                AsyncJobStep.job_id == job.id,
                AsyncJobStep.attempt_no == job.attempt_no,
                AsyncJobStep.status == "running",
            )
            .with_for_update(of=AsyncJobStep)
        ).scalar_one_or_none()
        if current_step is None or current_step.step_code != job.stage:
            return LeaseRecoveryResult("stale", job_id)

        if job.attempt_no >= job.max_attempts or cluster.execution.status != "completed":
            failure_code = (
                "WORKER_LOST"
                if cluster.execution.status == "completed"
                else "AUDIT_EXECUTION_OUTDATED"
            )
            report.status = "failed"
            report.failure_code = failure_code
            report.row_version += 1
            self._session.flush()
            updated = self._session.execute(
                text(
                    """
                    WITH recovery_clock AS MATERIALIZED (
                        SELECT clock_timestamp() AS t
                    ), finished_step AS (
                        UPDATE public.async_job_steps AS step
                           SET status = 'failed', finished_at = recovery_clock.t,
                               summary_json = '{}'::jsonb, error_code = :failure_code
                          FROM recovery_clock
                         WHERE step.id = :step_id AND step.status = 'running'
                        RETURNING step.job_id, recovery_clock.t
                    )
                    UPDATE public.async_jobs AS job
                       SET status = 'failed', finished_at = finished_step.t,
                           error_code = :failure_code,
                           error_message = 'report worker lease expired', next_retry_at = NULL,
                           worker_id = NULL, lease_owner = NULL,
                           lease_expires_at = NULL, heartbeat_at = NULL,
                           row_version = job.row_version + 1
                      FROM finished_step
                     WHERE job.id = :job_id AND job.status = 'running'
                       AND job.row_version = :row_version
                    RETURNING job.id
                    """
                ),
                {
                    "failure_code": failure_code,
                    "step_id": current_step.id,
                    "job_id": job.id,
                    "row_version": job.row_version,
                },
            ).scalar_one_or_none()
            return LeaseRecoveryResult(
                "exhausted" if updated is not None else "stale",
                job_id,
            )

        new_step_id = uuid4()
        row = self._session.execute(
            text(
                """
                WITH recovery_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                ), finished_previous AS (
                    UPDATE public.async_job_steps AS step
                       SET status = 'failed', finished_at = recovery_clock.t,
                           summary_json = '{}'::jsonb, error_code = 'LEASE_EXPIRED'
                      FROM recovery_clock
                     WHERE step.id = :old_step_id AND step.status = 'running'
                    RETURNING step.job_id, recovery_clock.t
                ), reclaimed AS (
                    UPDATE public.async_jobs AS job
                       SET attempt_no = job.attempt_no + 1,
                           stage = job.current_attempt_start_step_code,
                           worker_id = :worker_id, started_at = recovery_clock.t,
                           heartbeat_at = recovery_clock.t,
                           lease_expires_at = recovery_clock.t + interval '60 seconds',
                           row_version = job.row_version + 1
                      FROM recovery_clock, finished_previous
                     WHERE job.id = :job_id AND finished_previous.job_id = job.id
                       AND job.status = 'running' AND job.attempt_no < job.max_attempts
                       AND job.current_attempt_start_step_code = :start_step_code
                       AND job.row_version = :row_version
                    RETURNING job.id, job.organization_id, job.job_type,
                              job.resource_type, job.resource_id, job.status,
                              job.attempt_no, job.max_attempts,
                              job.current_attempt_start_step_code, job.input_json,
                              job.input_schema_version, job.handler_registry_version,
                              job.handler_registry_hash, job.trace_id, job.stage,
                              job.worker_id, job.lease_owner, job.started_at,
                              job.heartbeat_at, job.lease_expires_at, job.row_version
                ), created_step AS (
                    INSERT INTO public.async_job_steps (
                        id, job_id, step_seq, step_code, status, attempt_no,
                        started_at, trace_id
                    )
                    SELECT :new_step_id, id, :start_step_seq, stage, 'running',
                           attempt_no, started_at, trace_id
                      FROM reclaimed
                    RETURNING id
                )
                SELECT reclaimed.*, created_step.id AS step_id
                  FROM reclaimed CROSS JOIN created_step
                """
            ),
            {
                "old_step_id": current_step.id,
                "job_id": job.id,
                "worker_id": worker_id,
                "start_step_code": start_step_code,
                "start_step_seq": start_step_seq,
                "new_step_id": new_step_id,
                "row_version": job.row_version,
            },
        ).one_or_none()
        if row is None:
            return LeaseRecoveryResult("stale", job_id)
        return LeaseRecoveryResult("claimed", job_id, self._claimed_job(row, start_step_seq))

    def expired_audit_candidates(self, *, limit: int = 32) -> tuple[AuditRecoveryCandidate, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid recovery candidate limit")
        jobs = self._session.scalars(
            select(AsyncJob)
            .where(
                AsyncJob.job_type == "audit_execute",
                AsyncJob.resource_type == "audit_task_execution",
                AsyncJob.status == "running",
                AsyncJob.lease_expires_at.is_not(None),
                AsyncJob.lease_expires_at <= func.clock_timestamp() - text("interval '15 seconds'"),
            )
            .order_by(AsyncJob.lease_expires_at, AsyncJob.id)
            .limit(limit)
        ).all()
        return tuple(
            AuditRecoveryCandidate(_job_snapshot(job), job.stage)
            for job in jobs
            if job.stage is not None
        )

    def requeue_failed_audit_job(self, *, job_id: UUID, start_step_code: str) -> bool:
        """按审核 Task→Execution→Snapshot→Job 锁序重排可重试失败。"""

        classification = self._session.execute(
            select(AsyncJob.resource_type, AsyncJob.resource_id).where(AsyncJob.id == job_id)
        ).one_or_none()
        if classification is None or classification.resource_type != "audit_task_execution":
            return False
        resource = self._lock_audit_resource(classification.resource_id)
        if resource is None:
            return False
        _task, execution, snapshot = resource
        job = self._session.execute(
            select(AsyncJob).where(AsyncJob.id == job_id).with_for_update(of=AsyncJob)
        ).scalar_one_or_none()
        if (
            job is None
            or job.status != "failed"
            or job.next_retry_at is None
            or job.attempt_no >= job.max_attempts
            or job.current_attempt_start_step_code != start_step_code
            or start_step_code != "evaluate"
            or execution.status != "failed"
            or not execution.retryable
            or not self._audit_resource_matches(job, execution, snapshot)
        ):
            return False
        database_now = self._session.scalar(select(func.clock_timestamp()))
        if database_now is None or job.next_retry_at > database_now:
            return False

        execution.status = "queued"
        execution.failure_code = None
        execution.retryable = False
        execution.started_at = None
        execution.finished_at = None
        execution.row_version += 1
        self._session.flush()
        job.status = "queued"
        job.stage = None
        job.next_retry_at = None
        job.worker_id = None
        job.started_at = None
        job.finished_at = None
        job.error_code = None
        job.error_message = None
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.row_version += 1
        self._session.flush()
        self._session.add(
            OutboxEvent(
                id=uuid4(),
                aggregate_type="async_job",
                aggregate_id=job.id,
                event_id=uuid4(),
                event_type="job.dispatch.requested",
                event_version=1,
                event_sequence=job.attempt_no + 1,
                payload_json={"job_id": str(job.id)},
                status="pending",
                attempt_count=0,
                next_attempt_at=None,
                published_at=None,
                last_error=None,
                trace_id=job.trace_id,
            )
        )
        self._session.flush()
        return True

    def recover_expired_audit_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        start_step_code: str,
        start_step_seq: int,
    ) -> LeaseRecoveryResult:
        """审核执行过期租约在宽限期后重领，耗尽时同步终结执行。"""

        if not worker_id or len(worker_id) > 100 or start_step_seq <= 0:
            raise ValueError("invalid lease recovery identity")
        classification = self._session.execute(
            select(AsyncJob.resource_type, AsyncJob.resource_id).where(AsyncJob.id == job_id)
        ).one_or_none()
        if classification is None or classification.resource_type != "audit_task_execution":
            return LeaseRecoveryResult("stale", job_id)
        resource = self._lock_audit_resource(classification.resource_id)
        if resource is None:
            return LeaseRecoveryResult("stale", job_id)
        _task, execution, snapshot = resource
        job = self._session.execute(
            select(AsyncJob).where(AsyncJob.id == job_id).with_for_update(of=AsyncJob)
        ).scalar_one_or_none()
        if (
            job is None
            or job.status != "running"
            or job.lease_expires_at is None
            or job.current_attempt_start_step_code != start_step_code
            or start_step_code != "evaluate"
            or execution.status != "running"
            or not self._audit_resource_matches(job, execution, snapshot)
        ):
            return LeaseRecoveryResult("stale", job_id)
        database_now = self._session.scalar(select(func.clock_timestamp()))
        if database_now is None or database_now < job.lease_expires_at + _LEASE_RECOVERY_GRACE:
            return LeaseRecoveryResult("stale", job_id)
        current_step = self._session.execute(
            select(AsyncJobStep)
            .where(
                AsyncJobStep.job_id == job.id,
                AsyncJobStep.attempt_no == job.attempt_no,
                AsyncJobStep.status == "running",
            )
            .with_for_update(of=AsyncJobStep)
        ).scalar_one_or_none()
        if current_step is None or current_step.step_code != job.stage:
            return LeaseRecoveryResult("stale", job_id)

        if job.attempt_no >= job.max_attempts:
            execution.status = "failed"
            execution.failure_code = "WORKER_LOST"
            execution.retryable = False
            execution.finished_at = database_now
            execution.row_version += 1
            self._session.flush()
            updated = self._session.execute(
                text(
                    """
                    WITH recovery_clock AS MATERIALIZED (
                        SELECT clock_timestamp() AS t
                    ), finished_step AS (
                        UPDATE public.async_job_steps AS step
                           SET status = 'failed', finished_at = recovery_clock.t,
                               summary_json = '{}'::jsonb, error_code = 'WORKER_LOST'
                          FROM recovery_clock
                         WHERE step.id = :step_id AND step.status = 'running'
                        RETURNING step.job_id, recovery_clock.t
                    )
                    UPDATE public.async_jobs AS job
                       SET status = 'failed', finished_at = finished_step.t,
                           error_code = 'WORKER_LOST',
                           error_message = 'worker lease expired', next_retry_at = NULL,
                           worker_id = NULL, lease_owner = NULL,
                           lease_expires_at = NULL, heartbeat_at = NULL,
                           row_version = job.row_version + 1
                      FROM finished_step
                     WHERE job.id = :job_id AND job.status = 'running'
                       AND job.attempt_no = job.max_attempts
                       AND job.row_version = :row_version
                    RETURNING job.id
                    """
                ),
                {
                    "step_id": current_step.id,
                    "job_id": job.id,
                    "row_version": job.row_version,
                },
            ).scalar_one_or_none()
            return LeaseRecoveryResult(
                "exhausted" if updated is not None else "stale",
                job_id,
            )

        new_step_id = uuid4()
        row = self._session.execute(
            text(
                """
                WITH recovery_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                ), finished_previous AS (
                    UPDATE public.async_job_steps AS step
                       SET status = 'failed', finished_at = recovery_clock.t,
                           summary_json = '{}'::jsonb, error_code = 'LEASE_EXPIRED'
                      FROM recovery_clock
                     WHERE step.id = :old_step_id AND step.status = 'running'
                    RETURNING step.job_id, recovery_clock.t
                ), reclaimed AS (
                    UPDATE public.async_jobs AS job
                       SET attempt_no = job.attempt_no + 1,
                           stage = job.current_attempt_start_step_code,
                           worker_id = :worker_id, started_at = recovery_clock.t,
                           heartbeat_at = recovery_clock.t,
                           lease_expires_at = recovery_clock.t + interval '60 seconds',
                           row_version = job.row_version + 1
                      FROM recovery_clock, finished_previous
                     WHERE job.id = :job_id AND finished_previous.job_id = job.id
                       AND job.status = 'running' AND job.attempt_no < job.max_attempts
                       AND job.current_attempt_start_step_code = :start_step_code
                       AND job.row_version = :row_version
                    RETURNING job.id, job.organization_id, job.job_type,
                              job.resource_type, job.resource_id, job.status,
                              job.attempt_no, job.max_attempts,
                              job.current_attempt_start_step_code, job.input_json,
                              job.input_schema_version, job.handler_registry_version,
                              job.handler_registry_hash, job.trace_id, job.stage,
                              job.worker_id, job.lease_owner, job.started_at,
                              job.heartbeat_at, job.lease_expires_at, job.row_version
                ), created_step AS (
                    INSERT INTO public.async_job_steps (
                        id, job_id, step_seq, step_code, status, attempt_no,
                        started_at, trace_id
                    )
                    SELECT :new_step_id, id, :start_step_seq, stage, 'running',
                           attempt_no, started_at, trace_id
                      FROM reclaimed
                    RETURNING id
                )
                SELECT reclaimed.*, created_step.id AS step_id
                  FROM reclaimed CROSS JOIN created_step
                """
            ),
            {
                "old_step_id": current_step.id,
                "job_id": job.id,
                "worker_id": worker_id,
                "start_step_code": start_step_code,
                "start_step_seq": start_step_seq,
                "new_step_id": new_step_id,
                "row_version": job.row_version,
            },
        ).one_or_none()
        if row is None:
            return LeaseRecoveryResult("stale", job_id)
        return LeaseRecoveryResult("claimed", job_id, self._claimed_job(row, start_step_seq))

    def requeue_failed_knowledge_job(self, *, job_id: UUID, start_step_code: str) -> bool:
        """按知识资源→Job 锁序重排队，并追加下一 attempt 的 Outbox。"""

        classification = self._session.execute(
            select(AsyncJob.job_type, AsyncJob.resource_type, AsyncJob.resource_id).where(
                AsyncJob.id == job_id
            )
        ).one_or_none()
        if classification is None:
            return False
        resource = self._lock_knowledge_resource(
            classification.job_type,
            classification.resource_type,
            classification.resource_id,
        )
        if resource is None:
            return False
        job = self._session.execute(
            select(AsyncJob).where(AsyncJob.id == job_id).with_for_update(of=AsyncJob)
        ).scalar_one_or_none()
        if (
            job is None
            or job.status != "failed"
            or job.next_retry_at is None
            or job.attempt_no >= job.max_attempts
            or job.current_attempt_start_step_code != start_step_code
            or not self._knowledge_resource_matches(job, resource)
        ):
            return False
        database_now = self._session.scalar(select(func.clock_timestamp()))
        if database_now is None or job.next_retry_at > database_now:
            return False

        job.status = "queued"
        job.stage = None
        job.next_retry_at = None
        job.worker_id = None
        job.started_at = None
        job.finished_at = None
        job.error_code = None
        job.error_message = None
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.row_version += 1
        self._session.flush()
        self._session.add(
            OutboxEvent(
                id=uuid4(),
                aggregate_type="async_job",
                aggregate_id=job.id,
                event_id=uuid4(),
                event_type="job.dispatch.requested",
                event_version=1,
                event_sequence=job.attempt_no + 1,
                payload_json={"job_id": str(job.id)},
                status="pending",
                attempt_count=0,
                next_attempt_at=None,
                published_at=None,
                last_error=None,
                trace_id=job.trace_id,
            )
        )
        self._session.flush()
        return True

    def recover_expired_knowledge_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        start_step_code: str,
        start_step_seq: int,
    ) -> LeaseRecoveryResult:
        """知识 Job 过期租约在宽限期后重领，耗尽时同步终结业务资源。"""

        if not worker_id or len(worker_id) > 100 or start_step_seq <= 0:
            raise ValueError("invalid lease recovery identity")
        classification = self._session.execute(
            select(AsyncJob.job_type, AsyncJob.resource_type, AsyncJob.resource_id).where(
                AsyncJob.id == job_id
            )
        ).one_or_none()
        if classification is None:
            return LeaseRecoveryResult("stale", job_id)
        resource = self._lock_knowledge_resource(
            classification.job_type,
            classification.resource_type,
            classification.resource_id,
        )
        if resource is None:
            return LeaseRecoveryResult("stale", job_id)
        job = self._session.execute(
            select(AsyncJob).where(AsyncJob.id == job_id).with_for_update(of=AsyncJob)
        ).scalar_one_or_none()
        if (
            job is None
            or job.status != "running"
            or job.lease_expires_at is None
            or job.current_attempt_start_step_code != start_step_code
            or not self._knowledge_resource_matches(job, resource)
        ):
            return LeaseRecoveryResult("stale", job_id)
        database_now = self._session.scalar(select(func.clock_timestamp()))
        if database_now is None or database_now < job.lease_expires_at + _LEASE_RECOVERY_GRACE:
            return LeaseRecoveryResult("stale", job_id)
        current_step = self._session.execute(
            select(AsyncJobStep)
            .where(
                AsyncJobStep.job_id == job.id,
                AsyncJobStep.attempt_no == job.attempt_no,
                AsyncJobStep.status == "running",
            )
            .with_for_update(of=AsyncJobStep)
        ).scalar_one_or_none()
        if current_step is None or current_step.step_code != job.stage:
            return LeaseRecoveryResult("stale", job_id)

        if job.attempt_no >= job.max_attempts:
            if isinstance(resource, DocumentIndexVersion):
                resource.status = "failed"
                resource.failure_code = "WORKER_LOST"
                resource.row_version += 1
            else:
                completed_count = self._session.scalar(
                    select(func.count(RetrievalEvalResult.id)).where(
                        RetrievalEvalResult.run_id == resource.id
                    )
                )
                resource.status = "failed"
                resource.failure_code = "WORKER_LOST"
                resource.completed_case_count = int(completed_count or 0)
                resource.finished_at = database_now
            self._session.flush()
            updated = self._session.execute(
                text(
                    """
                    WITH recovery_clock AS MATERIALIZED (
                        SELECT clock_timestamp() AS t
                    ), finished_step AS (
                        UPDATE public.async_job_steps AS step
                           SET status = 'failed', finished_at = recovery_clock.t,
                               summary_json = '{}'::jsonb, error_code = 'WORKER_LOST'
                          FROM recovery_clock
                         WHERE step.id = :step_id AND step.status = 'running'
                        RETURNING step.job_id, recovery_clock.t
                    )
                    UPDATE public.async_jobs AS job
                       SET status = 'failed', finished_at = finished_step.t,
                           error_code = 'WORKER_LOST',
                           error_message = 'worker lease expired', next_retry_at = NULL,
                           worker_id = NULL, lease_owner = NULL,
                           lease_expires_at = NULL, heartbeat_at = NULL,
                           row_version = job.row_version + 1
                      FROM finished_step
                     WHERE job.id = :job_id AND job.status = 'running'
                       AND job.attempt_no = job.max_attempts
                       AND job.row_version = :row_version
                    RETURNING job.id
                    """
                ),
                {
                    "step_id": current_step.id,
                    "job_id": job.id,
                    "row_version": job.row_version,
                },
            ).scalar_one_or_none()
            return LeaseRecoveryResult("exhausted" if updated is not None else "stale", job_id)

        new_step_id = uuid4()
        row = self._session.execute(
            text(
                """
                WITH recovery_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                ), finished_previous AS (
                    UPDATE public.async_job_steps AS step
                       SET status = 'failed', finished_at = recovery_clock.t,
                           summary_json = '{}'::jsonb, error_code = 'LEASE_EXPIRED'
                      FROM recovery_clock
                     WHERE step.id = :old_step_id AND step.status = 'running'
                    RETURNING step.job_id, recovery_clock.t
                ), reclaimed AS (
                    UPDATE public.async_jobs AS job
                       SET attempt_no = job.attempt_no + 1,
                           stage = job.current_attempt_start_step_code,
                           worker_id = :worker_id, started_at = recovery_clock.t,
                           heartbeat_at = recovery_clock.t,
                           lease_expires_at = recovery_clock.t + interval '60 seconds',
                           row_version = job.row_version + 1
                      FROM recovery_clock, finished_previous
                     WHERE job.id = :job_id AND finished_previous.job_id = job.id
                       AND job.status = 'running' AND job.attempt_no < job.max_attempts
                       AND job.current_attempt_start_step_code = :start_step_code
                       AND job.row_version = :row_version
                    RETURNING job.id, job.organization_id, job.job_type,
                              job.resource_type, job.resource_id, job.status,
                              job.attempt_no, job.max_attempts,
                              job.current_attempt_start_step_code, job.input_json,
                              job.input_schema_version, job.handler_registry_version,
                              job.handler_registry_hash, job.trace_id, job.stage,
                              job.worker_id, job.lease_owner, job.started_at,
                              job.heartbeat_at, job.lease_expires_at, job.row_version
                ), created_step AS (
                    INSERT INTO public.async_job_steps (
                        id, job_id, step_seq, step_code, status, attempt_no,
                        started_at, trace_id
                    )
                    SELECT :new_step_id, id, :start_step_seq, stage, 'running',
                           attempt_no, started_at, trace_id
                      FROM reclaimed
                    RETURNING id
                )
                SELECT reclaimed.*, created_step.id AS step_id
                  FROM reclaimed CROSS JOIN created_step
                """
            ),
            {
                "old_step_id": current_step.id,
                "job_id": job.id,
                "worker_id": worker_id,
                "start_step_code": start_step_code,
                "start_step_seq": start_step_seq,
                "new_step_id": new_step_id,
                "row_version": job.row_version,
            },
        ).one_or_none()
        if row is None:
            return LeaseRecoveryResult("stale", job_id)
        return LeaseRecoveryResult("claimed", job_id, self._claimed_job(row, start_step_seq))

    def _lock_audit_resource(
        self,
        execution_id: UUID,
    ) -> tuple[AuditTask, AuditTaskExecution, AuditTaskSnapshot] | None:
        identity = self._session.execute(
            select(
                AuditTaskExecution.audit_task_id,
                AuditTaskExecution.organization_id,
            ).where(AuditTaskExecution.id == execution_id)
        ).one_or_none()
        if identity is None:
            return None
        task = self._session.execute(
            select(AuditTask)
            .where(
                AuditTask.id == identity.audit_task_id,
                AuditTask.organization_id == identity.organization_id,
                AuditTask.deleted_at.is_(None),
            )
            .with_for_update(of=AuditTask)
        ).scalar_one_or_none()
        if task is None:
            return None
        execution = self._session.execute(
            select(AuditTaskExecution)
            .where(
                AuditTaskExecution.id == execution_id,
                AuditTaskExecution.audit_task_id == task.id,
                AuditTaskExecution.organization_id == task.organization_id,
            )
            .with_for_update(of=AuditTaskExecution)
        ).scalar_one_or_none()
        if execution is None:
            return None
        snapshot = self._session.execute(
            select(AuditTaskSnapshot)
            .where(AuditTaskSnapshot.execution_id == execution.id)
            .with_for_update(of=AuditTaskSnapshot)
        ).scalar_one_or_none()
        if snapshot is None:
            return None
        return task, execution, snapshot

    def _lock_report_resource(
        self,
        report_id: UUID,
    ) -> tuple[LockedAuditCluster, AuditReport] | None:
        identity = self._session.execute(
            select(AuditReport.organization_id, AuditReport.execution_id).where(
                AuditReport.id == report_id
            )
        ).one_or_none()
        if identity is None:
            return None
        cluster = AuditRuntimeRepository(self._session).lock_cluster(
            identity.organization_id,
            identity.execution_id,
        )
        if cluster is None:
            return None
        report = next((item for item in cluster.reports if item.id == report_id), None)
        return None if report is None else (cluster, report)

    @staticmethod
    def _report_resource_matches(
        job: AsyncJob,
        cluster: LockedAuditCluster,
        report: AuditReport,
    ) -> bool:
        return bool(
            job.job_type == "report_generate"
            and job.resource_type == "audit_report"
            and job.organization_id == report.organization_id == cluster.execution.organization_id
            and job.resource_id == report.id
            and report.execution_id == cluster.execution.id
            and report.audit_task_id == cluster.task.id
            and report.job_id == job.id
            and job.input_json
            == {
                "report_id": str(report.id),
                "execution_id": str(report.execution_id),
                "payload_sha256": report.payload_sha256,
            }
        )

    @staticmethod
    def _audit_resource_matches(
        job: AsyncJob,
        execution: AuditTaskExecution,
        snapshot: AuditTaskSnapshot,
    ) -> bool:
        return bool(
            job.job_type == "audit_execute"
            and job.resource_type == "audit_task_execution"
            and job.organization_id == execution.organization_id == snapshot.organization_id
            and job.resource_id == execution.id == snapshot.execution_id
            and execution.audit_task_id == snapshot.audit_task_id
            and execution.job_id == job.id
            and execution.snapshot_sha256 == snapshot.facts_sha256
            and job.input_json
            == {
                "execution_id": str(execution.id),
                "snapshot_id": str(snapshot.id),
                "snapshot_sha256": snapshot.facts_sha256,
            }
        )

    def _lock_knowledge_resource(
        self, job_type: str, resource_type: str, resource_id: UUID
    ) -> DocumentIndexVersion | RetrievalEvalRun | None:
        if job_type == "knowledge_index_build" and resource_type == "document_index_version":
            return self._session.execute(
                select(DocumentIndexVersion)
                .where(DocumentIndexVersion.id == resource_id)
                .with_for_update(of=DocumentIndexVersion)
            ).scalar_one_or_none()
        if job_type == "retrieval_eval" and resource_type == "retrieval_eval_run":
            return self._session.execute(
                select(RetrievalEvalRun)
                .where(RetrievalEvalRun.id == resource_id)
                .with_for_update(of=RetrievalEvalRun)
            ).scalar_one_or_none()
        return None

    @staticmethod
    def _knowledge_resource_matches(
        job: AsyncJob, resource: DocumentIndexVersion | RetrievalEvalRun
    ) -> bool:
        if job.organization_id != resource.organization_id or job.resource_id != resource.id:
            return False
        if isinstance(resource, DocumentIndexVersion):
            return bool(
                job.job_type == "knowledge_index_build"
                and job.resource_type == "document_index_version"
                and job.input_json.get("index_version_id") == str(resource.id)
                and resource.status == "building"
            )
        return bool(
            job.job_type == "retrieval_eval"
            and job.resource_type == "retrieval_eval_run"
            and job.input_json.get("run_id") == str(resource.id)
            and resource.status == "running"
        )

    def requeue_failed_file_job(
        self,
        *,
        job_id: UUID,
        start_step_code: str,
        allow_before_next_retry: bool = False,
    ) -> bool:
        """按 File→Job 锁序重排队，并为下一 attempt 追加唯一 Outbox 事实。"""

        if type(allow_before_next_retry) is not bool:
            raise TypeError("allow_before_next_retry must be bool")

        classification = self._session.execute(
            select(AsyncJob.resource_type, AsyncJob.resource_id).where(AsyncJob.id == job_id)
        ).one_or_none()
        if classification is None or classification.resource_type != "file":
            return False
        file_record = self._session.execute(
            select(FileRecord)
            .where(FileRecord.id == classification.resource_id)
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        job = self._session.execute(
            select(AsyncJob).where(AsyncJob.id == job_id).with_for_update(of=AsyncJob)
        ).scalar_one_or_none()
        if (
            file_record is None
            or job is None
            or job.status != "failed"
            or job.next_retry_at is None
            or job.attempt_no >= job.max_attempts
            or job.resource_id != file_record.id
            or job.organization_id != file_record.organization_id
        ):
            return False
        database_now = self._session.scalar(select(func.clock_timestamp()))
        if database_now is None or (
            not allow_before_next_retry and job.next_retry_at > database_now
        ):
            return False

        if start_step_code == "scan":
            if (
                file_record.status != "validating"
                or file_record.security_scan_status
                not in {
                    "scan_failed",
                    "not_configured",
                }
                or job.job_type not in {"file_process", "file_scan"}
            ):
                return False
            file_record.security_scan_status = "pending"
            file_record.row_version += 1
            file_record.updated_at = database_now
            file_record.updated_by = None
            self._session.flush()
        elif start_step_code == "parse":
            if (
                job.job_type != "file_process"
                or job.input_json.get("file_id") != str(file_record.id)
                or file_record.status != "stored"
                or file_record.security_scan_status != "clean"
                or file_record.original_minio_bucket is None
                or file_record.original_minio_object_key is None
            ):
                return False
        elif start_step_code == "extract":
            if not self._financial_extract_source_available(job, file_record):
                return False
        else:
            return False

        job.status = "queued"
        job.stage = None
        job.current_attempt_start_step_code = start_step_code
        job.next_retry_at = None
        job.worker_id = None
        job.started_at = None
        job.finished_at = None
        job.error_code = None
        job.error_message = None
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.row_version += 1
        self._session.flush()

        self._session.add(
            OutboxEvent(
                id=uuid4(),
                aggregate_type="async_job",
                aggregate_id=job.id,
                event_id=uuid4(),
                event_type="job.dispatch.requested",
                event_version=1,
                event_sequence=job.attempt_no + 1,
                payload_json={"job_id": str(job.id)},
                status="pending",
                attempt_count=0,
                next_attempt_at=None,
                published_at=None,
                last_error=None,
                trace_id=job.trace_id,
            )
        )
        self._session.flush()
        return True

    def recover_expired_file_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        start_step_code: str,
        start_step_seq: int,
    ) -> LeaseRecoveryResult:
        """过期租约在宽限期后原子重领；最后一次则终结为 WORKER_LOST。"""

        if not worker_id or len(worker_id) > 100 or start_step_seq <= 0:
            raise ValueError("invalid lease recovery identity")
        classification = self._session.execute(
            select(AsyncJob.resource_type, AsyncJob.resource_id).where(AsyncJob.id == job_id)
        ).one_or_none()
        if classification is None or classification.resource_type != "file":
            return LeaseRecoveryResult("stale", job_id)
        file_record = self._session.execute(
            select(FileRecord)
            .where(FileRecord.id == classification.resource_id)
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        job = self._session.execute(
            select(AsyncJob).where(AsyncJob.id == job_id).with_for_update(of=AsyncJob)
        ).scalar_one_or_none()
        if (
            file_record is None
            or job is None
            or job.status != "running"
            or job.lease_expires_at is None
            or job.current_attempt_start_step_code != start_step_code
            or job.organization_id != file_record.organization_id
            or job.resource_id != file_record.id
        ):
            return LeaseRecoveryResult("stale", job_id)
        database_now = self._session.scalar(select(func.clock_timestamp()))
        if database_now is None or database_now < job.lease_expires_at + _LEASE_RECOVERY_GRACE:
            return LeaseRecoveryResult("stale", job_id)
        if start_step_code == "scan":
            scan_source_available = (
                file_record.status == "validating" and file_record.security_scan_status == "pending"
            ) or (
                job.job_type == "file_process"
                and file_record.status == "stored"
                and file_record.security_scan_status == "clean"
                and file_record.original_minio_bucket is not None
                and file_record.original_minio_object_key is not None
            )
            if job.job_type not in {"file_process", "file_scan"} or not scan_source_available:
                return LeaseRecoveryResult("stale", job_id)
        elif start_step_code == "parse":
            if (
                job.job_type != "file_process"
                or job.input_json.get("file_id") != str(file_record.id)
                or file_record.status != "stored"
                or file_record.security_scan_status != "clean"
                or file_record.original_minio_bucket is None
                or file_record.original_minio_object_key is None
            ):
                return LeaseRecoveryResult("stale", job_id)
        elif start_step_code == "extract":
            if not self._financial_extract_source_available(job, file_record):
                return LeaseRecoveryResult("stale", job_id)
        else:
            return LeaseRecoveryResult("stale", job_id)

        current_step = self._session.execute(
            select(AsyncJobStep)
            .where(
                AsyncJobStep.job_id == job.id,
                AsyncJobStep.attempt_no == job.attempt_no,
                AsyncJobStep.status == "running",
            )
            .with_for_update(of=AsyncJobStep)
        ).scalar_one_or_none()
        if current_step is None or current_step.step_code != job.stage:
            return LeaseRecoveryResult("stale", job_id)

        if job.attempt_no >= job.max_attempts:
            if (
                job.stage == "scan"
                and file_record.status == "validating"
                and file_record.security_scan_status == "pending"
            ):
                file_record.security_scan_status = "scan_failed"
                file_record.row_version += 1
                file_record.updated_at = database_now
                file_record.updated_by = None
                self._session.flush()
            updated = self._session.execute(
                text(
                    """
                    WITH recovery_clock AS MATERIALIZED (
                        SELECT clock_timestamp() AS t
                    ), finished_step AS (
                        UPDATE public.async_job_steps AS step
                           SET status = 'failed',
                               finished_at = recovery_clock.t,
                               summary_json = '{}'::jsonb,
                               error_code = 'WORKER_LOST'
                          FROM recovery_clock
                         WHERE step.id = :step_id
                           AND step.status = 'running'
                        RETURNING step.job_id, recovery_clock.t
                    )
                    UPDATE public.async_jobs AS job
                       SET status = 'failed',
                           finished_at = finished_step.t,
                           error_code = 'WORKER_LOST',
                           error_message = 'worker lease expired',
                           next_retry_at = NULL,
                           worker_id = NULL,
                           lease_owner = NULL,
                           lease_expires_at = NULL,
                           heartbeat_at = NULL,
                           row_version = job.row_version + 1
                      FROM finished_step
                     WHERE job.id = :job_id
                       AND job.status = 'running'
                       AND job.attempt_no = job.max_attempts
                       AND job.row_version = :row_version
                    RETURNING job.id
                    """
                ),
                {
                    "step_id": current_step.id,
                    "job_id": job.id,
                    "row_version": job.row_version,
                },
            ).scalar_one_or_none()
            return LeaseRecoveryResult("exhausted" if updated is not None else "stale", job_id)

        new_step_id = uuid4()
        row = self._session.execute(
            text(
                """
                WITH recovery_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                ), finished_previous AS (
                    UPDATE public.async_job_steps AS step
                       SET status = 'failed',
                           finished_at = recovery_clock.t,
                           summary_json = '{}'::jsonb,
                           error_code = 'LEASE_EXPIRED'
                      FROM recovery_clock
                     WHERE step.id = :old_step_id
                       AND step.status = 'running'
                    RETURNING step.job_id, recovery_clock.t
                ), reclaimed AS (
                    UPDATE public.async_jobs AS job
                       SET attempt_no = job.attempt_no + 1,
                           stage = job.current_attempt_start_step_code,
                           worker_id = :worker_id,
                           started_at = recovery_clock.t,
                           heartbeat_at = recovery_clock.t,
                           lease_expires_at = recovery_clock.t + interval '60 seconds',
                           row_version = job.row_version + 1
                      FROM recovery_clock, finished_previous
                     WHERE job.id = :job_id
                       AND finished_previous.job_id = job.id
                       AND job.status = 'running'
                       AND job.attempt_no < job.max_attempts
                       AND job.current_attempt_start_step_code = :start_step_code
                       AND job.row_version = :row_version
                    RETURNING job.id, job.organization_id, job.job_type,
                              job.resource_type, job.resource_id, job.status,
                              job.attempt_no, job.max_attempts,
                              job.current_attempt_start_step_code, job.input_json,
                              job.input_schema_version, job.handler_registry_version,
                              job.handler_registry_hash, job.trace_id, job.stage,
                              job.worker_id, job.lease_owner, job.started_at,
                              job.heartbeat_at, job.lease_expires_at, job.row_version
                ), created_step AS (
                    INSERT INTO public.async_job_steps (
                        id, job_id, step_seq, step_code, status, attempt_no,
                        started_at, trace_id
                    )
                    SELECT :new_step_id, id, :start_step_seq, stage, 'running',
                           attempt_no, started_at, trace_id
                      FROM reclaimed
                    RETURNING id
                )
                SELECT reclaimed.*, created_step.id AS step_id
                  FROM reclaimed CROSS JOIN created_step
                """
            ),
            {
                "old_step_id": current_step.id,
                "job_id": job.id,
                "worker_id": worker_id,
                "start_step_code": start_step_code,
                "start_step_seq": start_step_seq,
                "new_step_id": new_step_id,
                "row_version": job.row_version,
            },
        ).one_or_none()
        if row is None:
            return LeaseRecoveryResult("stale", job_id)
        return LeaseRecoveryResult(
            "claimed",
            job_id,
            self._claimed_job(row, start_step_seq),
        )

    def _financial_extract_source_available(
        self,
        job: AsyncJob,
        file_record: FileRecord,
    ) -> bool:
        raw_parse_version_id = job.input_json.get("parse_version_id")
        try:
            parse_version_id = UUID(cast(str, raw_parse_version_id))
        except (TypeError, ValueError):
            return False
        expected_business_type = {
            "invoice_extract": "invoice",
            "contract_extract": "contract",
        }.get(job.job_type)
        if (
            expected_business_type is None
            or job.input_json.get("file_id") != str(file_record.id)
            or str(parse_version_id) != raw_parse_version_id
            or file_record.status != "stored"
            or file_record.security_scan_status != "clean"
            or file_record.intended_business_type != expected_business_type
            or not file_record.auto_process_requested
        ):
            return False
        return (
            self._session.scalar(
                select(DocumentParseVersion.id).where(
                    DocumentParseVersion.id == parse_version_id,
                    DocumentParseVersion.file_id == file_record.id,
                    DocumentParseVersion.status.in_(
                        ("succeeded", "manual_review_required", "active")
                    ),
                    DocumentParseVersion.archived_at.is_(None),
                )
            )
            is not None
        )

    def skip_recovered_clean_scan(
        self,
        claim: ClaimedJob,
        *,
        next_step_code: str,
        next_step_seq: int,
    ) -> ClaimedJob | None:
        """恢复 attempt 从固定 scan 起步时，复用已提交的 clean 原件事实。"""

        if (
            claim.job.job_type != "file_process"
            or claim.step_code != "scan"
            or claim.job.attempt_no <= 1
            or next_step_code != "parse"
        ):
            return None
        file_record = self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == claim.job.resource_id,
                FileRecord.organization_id == claim.job.organization_id,
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        if (
            file_record is None
            or file_record.status != "stored"
            or file_record.security_scan_status != "clean"
            or file_record.original_minio_bucket is None
            or file_record.original_minio_object_key is None
        ):
            return None
        next_step_id = uuid4()
        row = self._session.execute(
            text(
                """
                WITH transition_clock AS MATERIALIZED (
                    SELECT clock_timestamp() AS t
                ), finished AS (
                    UPDATE public.async_job_steps AS step
                       SET status = 'skipped',
                           finished_at = transition_clock.t,
                           summary_json = '{}'::jsonb,
                           error_code = 'STEP_SKIPPED'
                      FROM transition_clock, public.async_jobs AS job
                     WHERE step.id = :step_id
                       AND step.job_id = job.id
                       AND job.id = :job_id
                       AND step.status = 'running'
                       AND step.step_code = 'scan'
                       AND step.attempt_no = :attempt_no
                       AND job.status = 'running'
                       AND job.worker_id = :worker_id
                       AND job.lease_owner = :lease_owner
                       AND job.row_version = :row_version
                       AND transition_clock.t < job.lease_expires_at
                       AND EXISTS (
                           SELECT 1 FROM public.async_job_steps AS prior
                            WHERE prior.job_id = job.id
                              AND prior.attempt_no < job.attempt_no
                              AND prior.step_code = 'scan'
                              AND prior.status = 'succeeded'
                       )
                    RETURNING step.job_id
                ), advanced AS (
                    UPDATE public.async_jobs AS job
                       SET stage = :next_step_code,
                           heartbeat_at = transition_clock.t,
                           lease_expires_at = transition_clock.t + interval '60 seconds',
                           row_version = job.row_version + 1
                      FROM transition_clock, finished
                     WHERE job.id = finished.job_id
                    RETURNING job.id, job.organization_id, job.job_type,
                              job.resource_type, job.resource_id, job.status,
                              job.attempt_no, job.max_attempts,
                              job.current_attempt_start_step_code, job.input_json,
                              job.input_schema_version, job.handler_registry_version,
                              job.handler_registry_hash, job.trace_id, job.stage,
                              job.worker_id, job.lease_owner, job.started_at,
                              job.heartbeat_at, job.lease_expires_at, job.row_version
                ), created_step AS (
                    INSERT INTO public.async_job_steps (
                        id, job_id, step_seq, step_code, status, attempt_no,
                        started_at, trace_id
                    )
                    SELECT :next_step_id, id, :next_step_seq, stage, 'running',
                           attempt_no, heartbeat_at, trace_id
                      FROM advanced
                    RETURNING id
                )
                SELECT advanced.*, created_step.id AS step_id
                  FROM advanced CROSS JOIN created_step
                """
            ),
            {
                "step_id": claim.step_id,
                "job_id": claim.job.id,
                "attempt_no": claim.job.attempt_no,
                "worker_id": claim.worker_id,
                "lease_owner": claim.lease_owner,
                "row_version": claim.row_version,
                "next_step_code": next_step_code,
                "next_step_seq": next_step_seq,
                "next_step_id": next_step_id,
            },
        ).one_or_none()
        return None if row is None else self._claimed_job(row, next_step_seq)


__all__ = [
    "AuditRecoveryCandidate",
    "ClaimedJob",
    "FileRecoveryCandidate",
    "FileRuntimeSource",
    "JobRuntimeRepository",
    "JobSnapshot",
    "LeaseRecoveryResult",
    "OutboxClaim",
    "OutboxFailureCode",
    "ReportRecoveryCandidate",
]
