"""`report_generate` Job 的正式制品生成、MinIO 持久化与 fencing。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.minio_report_storage import (
    ReportObjectLocator,
    ReportStorageError,
    ReportStorageOutcomeUnknownError,
    report_object_locators,
)
from app.ai.policy import canonicalize_jcs
from app.ai.report_draft import (
    FrozenReportFacts,
    ReportDraftOutput,
    ReportDraftPromptInput,
    validate_report_draft,
)
from app.models.audit import AuditReport
from app.reports.formal_payload import formal_report_payload_json_bytes
from app.reports.pdf_writer import MAX_PDF_BYTES, formal_report_pdf_bytes
from app.reports.xlsx_writer import MAX_XLSX_BYTES, formal_report_xlsx_bytes
from app.repositories.audit_runtime import AuditRuntimeRepository, LockedAuditCluster
from app.repositories.job_runtime import ClaimedJob, JobRuntimeRepository, JobSnapshot
from app.repositories.operation_log import OperationLogRepository
from app.services.ai_report_draft import (
    AiReportDraftService,
    AiReportDraftServiceError,
    AuditedReportDraft,
)
from app.services.report_queue import (
    FormalReportProjection,
    FormalReportProjectionError,
    build_formal_report_projection,
)
from app.workers.handler_registry import HandlerRegistryError
from app.workers.report_handler_registry import ReportHandlerRuntime, load_report_handler

_PDF_MIME_TYPE = "application/pdf"
_XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ReportArtifactStorage(Protocol):
    @property
    def reports_bucket(self) -> str: ...

    @property
    def exports_bucket(self) -> str: ...

    def put_verified(
        self,
        locator: ReportObjectLocator,
        payload: bytes,
        *,
        expected_sha256: str,
        content_type: str,
        max_bytes: int,
    ) -> None: ...

    def delete_compensation(self, locator: ReportObjectLocator) -> None: ...


class ReportJobExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _ReportDeterministicFailure(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReportJobExecutionResult:
    outcome: Literal["succeeded", "failed", "duplicate_or_stale"]
    job_id: UUID


@dataclass(frozen=True, slots=True)
class _Preflight:
    report_version: int
    projection: FormalReportProjection
    ai_draft_status: str
    ai_draft_sha256: str | None
    ai_draft: ReportDraftOutput | None


def _canonical_uuid(value: object) -> UUID:
    if type(value) is not str:
        raise ValueError
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError
    return parsed


def _report(cluster: LockedAuditCluster, report_id: UUID) -> AuditReport | None:
    return next((report for report in cluster.reports if report.id == report_id), None)


class ReportJobExecutor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        storage: ReportArtifactStorage,
        ai_report_draft: AiReportDraftService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._ai_report_draft = ai_report_draft

    def execute(
        self,
        *,
        job_id: UUID,
        event_id: UUID,
        event_schema_version: int,
        worker_id: str,
    ) -> ReportJobExecutionResult:
        if not worker_id or len(worker_id) > 100:
            raise ReportJobExecutionError("WORKER_ID_INVALID")
        with self._session_factory.begin() as session:
            repository = JobRuntimeRepository(session)
            snapshot = repository.peek_job(job_id)
            if snapshot is None:
                raise ReportJobExecutionError("JOB_NOT_FOUND")
            handler = self._validated_handler(snapshot.input_json)
            if not self._job_matches(snapshot, handler):
                raise ReportJobExecutionError("HANDLER_REGISTRY_INVALID")
            claim = repository.claim_job(
                job_id=job_id,
                event_id=event_id,
                event_schema_version=event_schema_version,
                worker_id=worker_id,
                start_step_seq=1,
            )
            if claim is None:
                return ReportJobExecutionResult("duplicate_or_stale", job_id)
        return self._execute_claimed(claim, handler)

    def execute_claimed(self, claim: ClaimedJob) -> ReportJobExecutionResult:
        handler = self._validated_handler(claim.job.input_json)
        if not self._job_matches(claim.job, handler) or claim.step_code != "generate":
            raise ReportJobExecutionError("HANDLER_REGISTRY_INVALID")
        return self._execute_claimed(claim, handler)

    def _execute_claimed(
        self,
        claim: ClaimedJob,
        handler: ReportHandlerRuntime,
    ) -> ReportJobExecutionResult:
        uploaded: list[ReportObjectLocator] = []
        try:
            report_id, execution_id = self._input_identity(claim)
            preflight = self._preflight(claim, report_id, execution_id)
            if self._ai_report_draft is not None and preflight.ai_draft_status == "disabled":
                prompt_input = self._draft_prompt_input(report_id, preflight.projection)
                try:
                    audited_draft = self._ai_report_draft.draft(
                        organization_id=claim.job.organization_id,
                        job_id=claim.job.id,
                        report_id=report_id,
                        trace_id=claim.job.trace_id,
                        prompt_input=prompt_input,
                    )
                except AiReportDraftServiceError:
                    self._mark_draft_degraded(
                        claim,
                        report_id=report_id,
                        execution_id=execution_id,
                        projection_hash=preflight.projection.payload_sha256,
                    )
                else:
                    if not self._adopt_draft(
                        claim,
                        report_id=report_id,
                        execution_id=execution_id,
                        projection_hash=preflight.projection.payload_sha256,
                        audited_draft=audited_draft,
                    ):
                        raise _ReportDeterministicFailure
                preflight = self._preflight(claim, report_id, execution_id)
            pdf = formal_report_pdf_bytes(
                preflight.projection.payload,
                preflight.projection.context,
                preflight.ai_draft,
            )
            xlsx = formal_report_xlsx_bytes(
                preflight.projection.payload,
                preflight.ai_draft,
            )
            pdf_sha256 = hashlib.sha256(pdf).hexdigest()
            xlsx_sha256 = hashlib.sha256(xlsx).hexdigest()
            pdf_locator, xlsx_locator = report_object_locators(
                organization_id=claim.job.organization_id,
                report_id=report_id,
                report_version=preflight.report_version,
                reports_bucket=self._storage.reports_bucket,
                exports_bucket=self._storage.exports_bucket,
            )
            self._storage.put_verified(
                pdf_locator,
                pdf,
                expected_sha256=pdf_sha256,
                content_type=_PDF_MIME_TYPE,
                max_bytes=MAX_PDF_BYTES,
            )
            uploaded.append(pdf_locator)
            self._storage.put_verified(
                xlsx_locator,
                xlsx,
                expected_sha256=xlsx_sha256,
                content_type=_XLSX_MIME_TYPE,
                max_bytes=MAX_XLSX_BYTES,
            )
            uploaded.append(xlsx_locator)
            summary: dict[str, object] = {
                "report_id": str(report_id),
                "pdf_sha256": pdf_sha256,
                "pdf_size_bytes": len(pdf),
                "xlsx_sha256": xlsx_sha256,
                "xlsx_size_bytes": len(xlsx),
            }
            handler.validate_summary(summary)
            self._complete(
                claim,
                report_id=report_id,
                execution_id=execution_id,
                projection_hash=preflight.projection.payload_sha256,
                ai_draft_status=preflight.ai_draft_status,
                ai_draft_sha256=preflight.ai_draft_sha256,
                ai_draft=preflight.ai_draft,
                pdf_locator=pdf_locator,
                pdf_sha256=pdf_sha256,
                pdf_size=len(pdf),
                xlsx_locator=xlsx_locator,
                xlsx_sha256=xlsx_sha256,
                xlsx_size=len(xlsx),
                summary=summary,
            )
            return ReportJobExecutionResult("succeeded", claim.job.id)
        except ReportStorageOutcomeUnknownError as error:
            unknown = not self._compensate([*uploaded, error.locator])
            return self._fail(
                claim,
                "STORAGE_OUTCOME_UNKNOWN" if unknown else "REPORT_STORAGE_FAILED",
                job_error_code=("STORAGE_OUTCOME_UNKNOWN" if unknown else "STORAGE_TRANSIENT"),
            )
        except ReportStorageError:
            unknown = not self._compensate(uploaded)
            return self._fail(
                claim,
                "STORAGE_OUTCOME_UNKNOWN" if unknown else "REPORT_STORAGE_FAILED",
                job_error_code=("STORAGE_OUTCOME_UNKNOWN" if unknown else "STORAGE_TRANSIENT"),
            )
        except (_ReportDeterministicFailure, FormalReportProjectionError, ValueError):
            unknown = not self._compensate(uploaded)
            return self._fail(
                claim,
                "STORAGE_OUTCOME_UNKNOWN" if unknown else "REPORT_GENERATION_INVALID",
                job_error_code=(
                    "STORAGE_OUTCOME_UNKNOWN" if unknown else "REPORT_GENERATION_INVALID"
                ),
            )
        except ReportJobExecutionError:
            self._compensate(uploaded)
            raise
        except Exception:
            unknown = not self._compensate(uploaded)
            return self._fail(
                claim,
                "STORAGE_OUTCOME_UNKNOWN" if unknown else "REPORT_GENERATION_FAILED",
                job_error_code=("STORAGE_OUTCOME_UNKNOWN" if unknown else "DATABASE_TRANSIENT"),
            )

    def _preflight(
        self,
        claim: ClaimedJob,
        report_id: UUID,
        execution_id: UUID,
    ) -> _Preflight:
        with self._session_factory.begin() as session:
            cluster = AuditRuntimeRepository(session).lock_cluster(
                claim.job.organization_id,
                execution_id,
            )
            report = None if cluster is None else _report(cluster, report_id)
            if (
                cluster is None
                or report is None
                or report.status != "generating"
                or report.job_id != claim.job.id
                or report.payload_sha256 != claim.job.input_json.get("payload_sha256")
            ):
                raise _ReportDeterministicFailure
            projection = build_formal_report_projection(
                cluster,
                report_id=report.id,
                created_at=report.created_at,
            )
            if projection.payload_sha256 != report.payload_sha256:
                raise _ReportDeterministicFailure
            draft = self._validated_stored_draft(report, projection)
            return _Preflight(
                report.report_version,
                projection,
                report.ai_draft_status,
                report.ai_draft_sha256,
                draft,
            )

    @staticmethod
    def _draft_frozen_facts(
        report_id: UUID,
        projection: FormalReportProjection,
    ) -> FrozenReportFacts:
        summary = projection.payload.summary
        return FrozenReportFacts(
            report_id=str(report_id),
            execution_id=str(projection.payload.preview_id),
            overall_level=summary.overall_level,
            active_risk_count=summary.active_risk_count,
            dismissed_risk_count=summary.dismissed_risk_count,
            has_effective_high=summary.has_effective_high,
            has_unreviewed_high=summary.has_unreviewed_high,
        )

    @classmethod
    def _draft_prompt_input(
        cls,
        report_id: UUID,
        projection: FormalReportProjection,
    ) -> ReportDraftPromptInput:
        facts = json.loads(
            formal_report_payload_json_bytes(
                projection.payload,
                projection.context,
            )
        )
        if type(facts) is not dict:
            raise _ReportDeterministicFailure
        return ReportDraftPromptInput(
            frozen=cls._draft_frozen_facts(report_id, projection),
            facts=facts,
        )

    @classmethod
    def _validated_stored_draft(
        cls,
        report: AuditReport,
        projection: FormalReportProjection,
    ) -> ReportDraftOutput | None:
        if report.ai_draft_status in {"disabled", "degraded"}:
            if report.ai_draft_json is not None or report.ai_draft_sha256 is not None:
                raise _ReportDeterministicFailure
            return None
        if (
            report.ai_draft_status != "succeeded"
            or report.ai_draft_json is None
            or report.ai_draft_sha256 is None
        ):
            raise _ReportDeterministicFailure
        try:
            encoded = canonicalize_jcs(report.ai_draft_json)
            if hashlib.sha256(encoded).hexdigest() != report.ai_draft_sha256:
                raise ValueError
            draft = ReportDraftOutput.model_validate_json(encoded)
            return validate_report_draft(
                draft,
                frozen=cls._draft_frozen_facts(report.id, projection),
            )
        except (TypeError, ValueError):
            raise _ReportDeterministicFailure from None

    def _adopt_draft(
        self,
        claim: ClaimedJob,
        *,
        report_id: UUID,
        execution_id: UUID,
        projection_hash: str,
        audited_draft: AuditedReportDraft,
    ) -> bool:
        draft_json = audited_draft.output.model_dump(mode="json")
        draft_sha256 = hashlib.sha256(canonicalize_jcs(draft_json)).hexdigest()
        adopted = False
        with self._session_factory.begin() as session:
            repository = AuditRuntimeRepository(session)
            cluster = repository.lock_cluster(claim.job.organization_id, execution_id)
            report = None if cluster is None else _report(cluster, report_id)
            current = (
                None
                if cluster is None or report is None
                else build_formal_report_projection(
                    cluster,
                    report_id=report.id,
                    created_at=report.created_at,
                )
            )
            if (
                cluster is None
                or report is None
                or current is None
                or report.status != "generating"
                or report.job_id != claim.job.id
                or current.payload_sha256 != projection_hash
                or report.payload_sha256 != projection_hash
                or report.ai_draft_status != "disabled"
            ):
                audited_draft.adoption.reject_in_transaction(
                    session,
                    safe_error_code="AI_REPORT_SOURCE_DRIFT",
                )
                return False
            audited_draft.adoption.adopt_in_transaction(session)
            report.ai_draft_status = "succeeded"
            report.ai_draft_json = draft_json
            report.ai_draft_sha256 = draft_sha256
            report.row_version += 1
            repository.flush()
            adopted = True
        return adopted

    def _mark_draft_degraded(
        self,
        claim: ClaimedJob,
        *,
        report_id: UUID,
        execution_id: UUID,
        projection_hash: str,
    ) -> None:
        with self._session_factory.begin() as session:
            repository = AuditRuntimeRepository(session)
            cluster = repository.lock_cluster(claim.job.organization_id, execution_id)
            report = None if cluster is None else _report(cluster, report_id)
            if cluster is None or report is None:
                raise _ReportDeterministicFailure
            current = build_formal_report_projection(
                cluster,
                report_id=report.id,
                created_at=report.created_at,
            )
            if (
                report.status != "generating"
                or report.job_id != claim.job.id
                or current.payload_sha256 != projection_hash
                or report.payload_sha256 != projection_hash
                or report.ai_draft_status != "disabled"
            ):
                raise _ReportDeterministicFailure
            report.ai_draft_status = "degraded"
            report.ai_draft_json = None
            report.ai_draft_sha256 = None
            report.row_version += 1
            repository.flush()

    def _complete(
        self,
        claim: ClaimedJob,
        *,
        report_id: UUID,
        execution_id: UUID,
        projection_hash: str,
        ai_draft_status: str,
        ai_draft_sha256: str | None,
        ai_draft: ReportDraftOutput | None,
        pdf_locator: ReportObjectLocator,
        pdf_sha256: str,
        pdf_size: int,
        xlsx_locator: ReportObjectLocator,
        xlsx_sha256: str,
        xlsx_size: int,
        summary: dict[str, object],
    ) -> None:
        with self._session_factory.begin() as session:
            repository = AuditRuntimeRepository(session)
            cluster = repository.lock_cluster(claim.job.organization_id, execution_id)
            report = None if cluster is None else _report(cluster, report_id)
            if (
                cluster is None
                or report is None
                or cluster.execution.status != "completed"
                or report.status != "generating"
                or report.job_id != claim.job.id
                or report.ai_draft_status != ai_draft_status
                or report.ai_draft_sha256 != ai_draft_sha256
            ):
                raise _ReportDeterministicFailure
            current = build_formal_report_projection(
                cluster,
                report_id=report.id,
                created_at=report.created_at,
            )
            if not (current.payload_sha256 == projection_hash == report.payload_sha256):
                raise _ReportDeterministicFailure
            if self._validated_stored_draft(report, current) != ai_draft:
                raise _ReportDeterministicFailure
            report.status = "ready"
            report.pdf_bucket = pdf_locator.bucket_name
            report.pdf_object_key = pdf_locator.object_key
            report.pdf_sha256 = pdf_sha256
            report.pdf_size_bytes = pdf_size
            report.pdf_mime_type = _PDF_MIME_TYPE
            report.xlsx_bucket = xlsx_locator.bucket_name
            report.xlsx_object_key = xlsx_locator.object_key
            report.xlsx_sha256 = xlsx_sha256
            report.xlsx_size_bytes = xlsx_size
            report.xlsx_mime_type = _XLSX_MIME_TYPE
            report.generated_at = repository.database_now()
            report.failure_code = None
            report.row_version += 1
            repository.flush()
            OperationLogRepository(session).append(
                organization_id=claim.job.organization_id,
                actor_kind="system",
                actor_id=None,
                action_code="reports.generated",
                outcome="succeeded",
                resource_type="audit_report",
                resource_id=report.id,
                trace_id=claim.job.trace_id,
                change_summary={
                    "pdf_sha256": pdf_sha256,
                    "pdf_size_bytes": pdf_size,
                    "status": "ready",
                    "xlsx_sha256": xlsx_sha256,
                    "xlsx_size_bytes": xlsx_size,
                },
            )
            if not JobRuntimeRepository(session).finish_job(
                claim,
                status="succeeded",
                summary=summary,
            ):
                raise ReportJobExecutionError("JOB_FENCING_REJECTED")

    def _fail(
        self,
        claim: ClaimedJob,
        failure_code: str,
        *,
        job_error_code: str,
    ) -> ReportJobExecutionResult:
        try:
            report_id, execution_id = self._input_identity(claim)
        except ValueError:
            raise ReportJobExecutionError("HANDLER_REGISTRY_INVALID") from None
        with self._session_factory.begin() as session:
            repository = AuditRuntimeRepository(session)
            cluster = repository.lock_cluster(claim.job.organization_id, execution_id)
            report = None if cluster is None else _report(cluster, report_id)
            if report is None:
                raise ReportJobExecutionError("JOB_FENCING_REJECTED")
            if report.status != "generating":
                if report.status == "failed" and JobRuntimeRepository(
                    session
                ).finish_cancel_requested(claim):
                    return ReportJobExecutionResult("failed", claim.job.id)
                return ReportJobExecutionResult("duplicate_or_stale", claim.job.id)
            report.status = "failed"
            report.failure_code = failure_code
            report.row_version += 1
            repository.flush()
            OperationLogRepository(session).append(
                organization_id=claim.job.organization_id,
                actor_kind="system",
                actor_id=None,
                action_code="reports.generation_failed",
                outcome="failed",
                resource_type="audit_report",
                resource_id=report.id,
                trace_id=claim.job.trace_id,
                change_summary={"failure_code": failure_code, "status": "failed"},
            )
            if not JobRuntimeRepository(session).finish_job(
                claim,
                status="failed",
                summary={},
                error_code=job_error_code,
                error_message="formal report generation failed",
            ):
                raise ReportJobExecutionError("JOB_FENCING_REJECTED")
        return ReportJobExecutionResult("failed", claim.job.id)

    def _compensate(self, locators: list[ReportObjectLocator]) -> bool:
        clean = True
        for locator in reversed(tuple(dict.fromkeys(locators))):
            try:
                self._storage.delete_compensation(locator)
            except ReportStorageError:
                clean = False
        return clean

    @staticmethod
    def _input_identity(claim: ClaimedJob) -> tuple[UUID, UUID]:
        report_id = _canonical_uuid(claim.job.input_json.get("report_id"))
        execution_id = _canonical_uuid(claim.job.input_json.get("execution_id"))
        if report_id != claim.job.resource_id:
            raise ValueError
        return report_id, execution_id

    @staticmethod
    def _validated_handler(input_json: dict[str, object]) -> ReportHandlerRuntime:
        try:
            handler = load_report_handler()
            handler.validate_input(input_json)
        except (HandlerRegistryError, ValueError):
            raise ReportJobExecutionError("HANDLER_REGISTRY_INVALID") from None
        return handler

    @staticmethod
    def _job_matches(job: JobSnapshot, handler: ReportHandlerRuntime) -> bool:
        return bool(
            job.job_type == "report_generate"
            and job.resource_type == "audit_report"
            and job.handler_registry_version == handler.registry_version
            and job.handler_registry_hash == handler.registry_hash
            and job.input_schema_version == 1
            and job.input_json.get("report_id") == str(job.resource_id)
            and job.current_attempt_start_step_code == "generate"
        )


__all__ = [
    "ReportArtifactStorage",
    "ReportJobExecutionError",
    "ReportJobExecutionResult",
    "ReportJobExecutor",
]
