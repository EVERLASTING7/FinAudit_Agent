from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass
from uuid import UUID

from smoke_local_audit_execution_crash_recovery import (
    AuditCrashRecoveryError,
    _client,
    _client_profile,
    _database_profile,
    _reviewer_credentials,
)
from smoke_local_file_upload import (
    SmokeError,
    _login,
    _read_password,
    _require_envelope,
)
from smoke_local_worker_crash_recovery import (
    _POLL_INTERVAL_SECONDS,
    CrashRecoveryError,
    _canonical_uuid,
    _required_environment,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.minio_report_storage import (
    MinioReportStorageAdapter,
    ReportObjectLocator,
    report_object_locators,
)
from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.models.audit import (
    AuditReport,
    AuditRisk,
    AuditTask,
    AuditTaskExecution,
    AuditTaskSnapshot,
    RiskCitation,
    RuleExecution,
)
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, AsyncJobStep, OutboxEvent
from app.reports.pdf_writer import MAX_PDF_BYTES, formal_report_pdf_bytes
from app.reports.xlsx_writer import MAX_XLSX_BYTES, formal_report_xlsx_bytes
from app.repositories.audit_runtime import LockedAuditCluster
from app.services.report_queue import build_formal_report_projection

_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_AUDIT_READY_TIMEOUT_SECONDS = 180
_REPORT_RUNNING_TIMEOUT_SECONDS = 90
_REPORT_RECOVERY_TIMEOUT_SECONDS = 180
_PDF_MIME_TYPE = "application/pdf"
_XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ReportCrashRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ReportProfile:
    run_id: str
    task_id: UUID
    execution_id: UUID
    audit_job_id: UUID
    report_id: UUID
    report_job_id: UUID
    report_version: int


@dataclass(frozen=True, slots=True)
class _ExpectedArtifacts:
    pdf_locator: ReportObjectLocator
    pdf: bytes
    pdf_sha256: str
    xlsx_locator: ReportObjectLocator
    xlsx: bytes
    xlsx_sha256: str
    payload_sha256: str


def _validate_run_id(run_id: str) -> None:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ReportCrashRecoveryError("RUN_ID_INVALID")


def _lock_application_name(run_id: str) -> str:
    _validate_run_id(run_id)
    identity = f"finaudit-report-crash-{run_id}"
    if len(identity.encode("ascii")) > 63:
        raise ReportCrashRecoveryError("LOCK_IDENTITY_INVALID")
    return identity


def _audit_reviewer_credentials(admin_password: str, run_id: str) -> tuple[str, str]:
    _validate_run_id(run_id)
    digest = hashlib.sha256(
        f"{admin_password}\0{run_id}\0report-crash-audit".encode()
    ).hexdigest()
    return f"report-crash-audit-{run_id[:12]}", f"Ar9!{digest[:24]}"


def _positive_integer_string(value: object) -> bool:
    return type(value) is str and value.isascii() and value.isdigit() and int(value) > 0


def _required_sha256(name: str) -> str:
    value = _required_environment(name)
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ReportCrashRecoveryError(f"{name}_INVALID")
    return value


def _required_positive_integer(name: str) -> int:
    value = _required_environment(name)
    if not value.isascii() or not value.isdigit() or int(value) <= 0:
        raise ReportCrashRecoveryError(f"{name}_INVALID")
    return int(value)


def _report_profile() -> _ReportProfile:
    run_id, task_id, execution_id, audit_job_id = _database_profile()
    report_version_raw = _required_environment("FINAUDIT_REPORT_VERSION")
    if not report_version_raw.isascii() or not report_version_raw.isdigit():
        raise ReportCrashRecoveryError("REPORT_VERSION_INVALID")
    report_version = int(report_version_raw)
    if report_version <= 0:
        raise ReportCrashRecoveryError("REPORT_VERSION_INVALID")
    return _ReportProfile(
        run_id=run_id,
        task_id=task_id,
        execution_id=execution_id,
        audit_job_id=audit_job_id,
        report_id=_canonical_uuid(
            _required_environment("FINAUDIT_REPORT_ID"), "REPORT_ID_INVALID"
        ),
        report_job_id=_canonical_uuid(
            _required_environment("FINAUDIT_REPORT_JOB_ID"), "REPORT_JOB_ID_INVALID"
        ),
        report_version=report_version,
    )


def _load_report_cluster(
    session: Session,
    *,
    task_id: UUID,
    execution_id: UUID,
    report_id: UUID,
) -> tuple[LockedAuditCluster, AuditReport]:
    task = session.get(AuditTask, task_id)
    execution = session.get(AuditTaskExecution, execution_id)
    snapshot = session.scalar(
        select(AuditTaskSnapshot).where(AuditTaskSnapshot.execution_id == execution_id)
    )
    rules = tuple(
        session.scalars(
            select(RuleExecution)
            .where(RuleExecution.execution_id == execution_id)
            .order_by(RuleExecution.rule_code)
        ).all()
    )
    risks = tuple(
        session.scalars(
            select(AuditRisk)
            .where(AuditRisk.execution_id == execution_id)
            .order_by(AuditRisk.rule_code)
        ).all()
    )
    citations = tuple(
        session.scalars(
            select(RiskCitation)
            .where(RiskCitation.execution_id == execution_id)
            .order_by(RiskCitation.risk_id, RiskCitation.chunk_id)
        ).all()
    )
    reports = tuple(
        session.scalars(
            select(AuditReport)
            .where(AuditReport.execution_id == execution_id)
            .order_by(AuditReport.report_version)
        ).all()
    )
    if task is None or execution is None:
        raise ReportCrashRecoveryError("REPORT_AUDIT_CLUSTER_MISSING")
    cluster = LockedAuditCluster(
        task, execution, snapshot, rules, risks, citations, reports
    )
    report = next((item for item in reports if item.id == report_id), None)
    if report is None:
        raise ReportCrashRecoveryError("REPORT_ROW_MISSING")
    return cluster, report


def _expected_artifacts(
    settings: Settings, profile: _ReportProfile
) -> _ExpectedArtifacts:
    engine = create_application_engine(settings)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            cluster, report = _load_report_cluster(
                session,
                task_id=profile.task_id,
                execution_id=profile.execution_id,
                report_id=profile.report_id,
            )
            if (
                report.report_version != profile.report_version
                or report.job_id != profile.report_job_id
            ):
                raise ReportCrashRecoveryError("REPORT_IDENTITY_DRIFT")
            projection = build_formal_report_projection(
                cluster,
                report_id=report.id,
                created_at=report.created_at,
            )
            if projection.payload_sha256 != report.payload_sha256:
                raise ReportCrashRecoveryError("REPORT_PROJECTION_HASH_DRIFT")
            pdf = formal_report_pdf_bytes(projection.payload, projection.context)
            xlsx = formal_report_xlsx_bytes(projection.payload)
    finally:
        engine.dispose()
    storage = MinioReportStorageAdapter(settings, credential_scope="worker")
    pdf_locator, xlsx_locator = report_object_locators(
        organization_id=cluster.execution.organization_id,
        report_id=profile.report_id,
        report_version=profile.report_version,
        reports_bucket=storage.reports_bucket,
        exports_bucket=storage.exports_bucket,
    )
    return _ExpectedArtifacts(
        pdf_locator=pdf_locator,
        pdf=pdf,
        pdf_sha256=hashlib.sha256(pdf).hexdigest(),
        xlsx_locator=xlsx_locator,
        xlsx=xlsx,
        xlsx_sha256=hashlib.sha256(xlsx).hexdigest(),
        payload_sha256=projection.payload_sha256,
    )


def _verify_stored_artifacts(settings: Settings, expected: _ExpectedArtifacts) -> None:
    storage = MinioReportStorageAdapter(settings, credential_scope="worker")
    pdf = storage.read_verified(
        expected.pdf_locator,
        expected_size=len(expected.pdf),
        expected_sha256=expected.pdf_sha256,
        max_bytes=MAX_PDF_BYTES,
    )
    xlsx = storage.read_verified(
        expected.xlsx_locator,
        expected_size=len(expected.xlsx),
        expected_sha256=expected.xlsx_sha256,
        max_bytes=MAX_XLSX_BYTES,
    )
    if pdf != expected.pdf or xlsx != expected.xlsx:
        raise ReportCrashRecoveryError("REPORT_OBJECT_BYTES_DRIFT")


def run_wait_for_audit_ready() -> None:
    _run_id, task_id, execution_id, audit_job_id = _database_profile()
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        deadline = time.monotonic() + _AUDIT_READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with factory() as session:
                task = session.get(AuditTask, task_id)
                execution = session.get(AuditTaskExecution, execution_id)
                job = session.get(AsyncJob, audit_job_id)
                rules = tuple(
                    session.scalars(
                        select(RuleExecution).where(
                            RuleExecution.execution_id == execution_id
                        )
                    ).all()
                )
                risks = tuple(
                    session.scalars(
                        select(AuditRisk).where(AuditRisk.execution_id == execution_id)
                    ).all()
                )
                reports = tuple(
                    session.scalars(
                        select(AuditReport).where(
                            AuditReport.execution_id == execution_id
                        )
                    ).all()
                )
                if job is not None and job.status in {"failed", "cancelled"}:
                    raise ReportCrashRecoveryError("AUDIT_EXECUTION_FAILED")
                if (
                    task is not None
                    and task.current_execution_id == execution_id
                    and task.status == "open"
                    and execution is not None
                    and execution.status == "pending_finance_review"
                    and execution.job_id == audit_job_id
                    and job is not None
                    and job.status == "succeeded"
                    and job.attempt_no == 1
                    and len(rules) == 15
                    and {risk.effective_level for risk in risks} == {"high", "medium"}
                    and all(risk.review_status == "pending" for risk in risks)
                    and not reports
                ):
                    print("LOCAL_REPORT_GENERATE_AUDIT_READY_GATE=PASS")
                    return
            time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        engine.dispose()
    raise ReportCrashRecoveryError("AUDIT_READY_TIMEOUT")


def run_queue_report_client() -> None:
    base_url, origin, admin_username, run_id = _client_profile()
    database_run_id, task_id, execution_id, _audit_job_id = _database_profile()
    if database_run_id != run_id:
        raise ReportCrashRecoveryError("RUN_ID_DRIFT")
    admin_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    finance_username, finance_password = _reviewer_credentials(admin_password, run_id)
    audit_username, audit_password = _audit_reviewer_credentials(admin_password, run_id)
    with _client(base_url, origin) as client:
        admin_token = _login(client, admin_username, admin_password)
        _require_envelope(
            client.post(
                "/api/v1/users",
                headers={
                    "Authorization": f"Bearer {admin_token}",
                    "Idempotency-Key": f"local-report-crash-auditor.{run_id}",
                },
                json={
                    "username": audit_username,
                    "display_name": "本地报告强杀恢复审计账号",
                    "initial_password": audit_password,
                    "fixed_roles": ["audit_reviewer"],
                },
            ),
            201,
        )
        finance_token = _login(client, finance_username, finance_password)
        finance_headers = {"Authorization": f"Bearer {finance_token}"}
        detail = _require_envelope(
            client.get(f"/api/v1/audit-tasks/{task_id}", headers=finance_headers),
            200,
        )
        execution = detail.get("execution")
        risks = detail.get("risks")
        if (
            not isinstance(execution, dict)
            or execution.get("id") != str(execution_id)
            or execution.get("status") != "pending_finance_review"
            or not _positive_integer_string(execution.get("row_version"))
            or not isinstance(risks, list)
        ):
            raise ReportCrashRecoveryError("AUDIT_REVIEW_INPUT_INVALID")
        high_risks = [
            risk
            for risk in risks
            if isinstance(risk, dict) and risk.get("effective_level") == "high"
        ]
        non_high_risks = [
            risk
            for risk in risks
            if isinstance(risk, dict) and risk.get("effective_level") != "high"
        ]
        if len(high_risks) != 1 or len(non_high_risks) != 1:
            raise ReportCrashRecoveryError("AUDIT_REVIEW_RISK_SET_INVALID")
        for index, risk in enumerate(non_high_risks, start=1):
            risk_id = _canonical_uuid(risk.get("id"), "AUDIT_RISK_ID_INVALID")
            if not _positive_integer_string(risk.get("row_version")):
                raise ReportCrashRecoveryError("AUDIT_RISK_VERSION_INVALID")
            reviewed = _require_envelope(
                client.post(
                    f"/api/v1/audit-risks/{risk_id}/reviews/non-high",
                    headers={
                        **finance_headers,
                        "Idempotency-Key": f"local-report-crash-finance-risk-{index}.{run_id}",
                    },
                    json={
                        "row_version": risk["row_version"],
                        "decision": "confirmed",
                        "reason": "报告强杀恢复门禁财务复核合成风险",
                    },
                ),
                200,
            )
            reviewed_risk = reviewed.get("risk")
            if (
                not isinstance(reviewed_risk, dict)
                or reviewed_risk.get("review_status") != "confirmed"
            ):
                raise ReportCrashRecoveryError("FINANCE_RISK_REVIEW_INVALID")
        finance_reviewed = _require_envelope(
            client.post(
                f"/api/v1/audit-executions/{execution_id}/finance-review",
                headers={
                    **finance_headers,
                    "Idempotency-Key": f"local-report-crash-finance-submit.{run_id}",
                },
                json={
                    "row_version": execution["row_version"],
                    "decision": "submit",
                    "reason": "报告强杀恢复门禁提交独立高风险复核",
                },
            ),
            200,
        )
        finance_execution = finance_reviewed.get("execution")
        if (
            not isinstance(finance_execution, dict)
            or finance_execution.get("status") != "pending_audit_review"
            or not _positive_integer_string(finance_execution.get("row_version"))
        ):
            raise ReportCrashRecoveryError("FINANCE_REVIEW_RESULT_INVALID")
        audit_token = _login(client, audit_username, audit_password)
        audit_headers = {"Authorization": f"Bearer {audit_token}"}
        for index, risk in enumerate(high_risks, start=1):
            risk_id = _canonical_uuid(risk.get("id"), "AUDIT_RISK_ID_INVALID")
            if not _positive_integer_string(risk.get("row_version")):
                raise ReportCrashRecoveryError("AUDIT_RISK_VERSION_INVALID")
            reviewed = _require_envelope(
                client.post(
                    f"/api/v1/audit-risks/{risk_id}/reviews/high",
                    headers={
                        **audit_headers,
                        "Idempotency-Key": f"local-report-crash-audit-risk-{index}.{run_id}",
                    },
                    json={
                        "row_version": risk["row_version"],
                        "decision": "confirmed",
                        "reason": "报告强杀恢复门禁独立审计复核合成高风险",
                    },
                ),
                200,
            )
            reviewed_risk = reviewed.get("risk")
            if (
                not isinstance(reviewed_risk, dict)
                or reviewed_risk.get("review_status") != "confirmed"
            ):
                raise ReportCrashRecoveryError("AUDIT_RISK_REVIEW_INVALID")
        completed = _require_envelope(
            client.post(
                f"/api/v1/audit-executions/{execution_id}/audit-review",
                headers={
                    **audit_headers,
                    "Idempotency-Key": f"local-report-crash-complete.{run_id}",
                },
                json={
                    "row_version": finance_execution["row_version"],
                    "decision": "complete",
                    "reason": "报告强杀恢复门禁完成审核并排队正式报告",
                },
            ),
            200,
        )
        completed_execution = completed.get("execution")
        if (
            not isinstance(completed_execution, dict)
            or completed_execution.get("id") != str(execution_id)
            or completed_execution.get("status") != "completed"
        ):
            raise ReportCrashRecoveryError("AUDIT_COMPLETION_INVALID")
        report_list = _require_envelope(
            client.get(
                f"/api/v1/audit-executions/{execution_id}/reports",
                headers=finance_headers,
            ),
            200,
        )
    items = report_list.get("items")
    if report_list.get("execution_id") != str(execution_id) or not isinstance(
        items, list
    ):
        raise ReportCrashRecoveryError("REPORT_LIST_CONTRACT_INVALID")
    matching = [item for item in items if isinstance(item, dict)]
    if len(matching) != 1:
        raise ReportCrashRecoveryError("REPORT_QUEUE_CARDINALITY_INVALID")
    report = matching[0]
    report_id = _canonical_uuid(report.get("id"), "REPORT_ID_INVALID")
    report_job_id = _canonical_uuid(report.get("job_id"), "REPORT_JOB_ID_INVALID")
    report_version = report.get("report_version")
    if (
        report.get("audit_task_id") != str(task_id)
        or report.get("execution_id") != str(execution_id)
        or report.get("status") != "queued"
        or type(report_version) is not int
        or report_version != 1
        or not isinstance(report.get("payload_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", report["payload_sha256"]) is None
        or report.get("pdf_sha256") is not None
        or report.get("xlsx_sha256") is not None
    ):
        raise ReportCrashRecoveryError("REPORT_QUEUE_RESULT_INVALID")
    print(f"LOCAL_REPORT_GENERATE_REPORT_ID={report_id}")
    print(f"LOCAL_REPORT_GENERATE_JOB_ID={report_job_id}")
    print(f"LOCAL_REPORT_GENERATE_VERSION={report_version}")
    print(f"LOCAL_REPORT_GENERATE_PAYLOAD_SHA256={report['payload_sha256']}")


def run_wait_for_report_running() -> None:
    profile = _report_profile()
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        deadline = time.monotonic() + _REPORT_RUNNING_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with factory() as session:
                execution = session.get(AuditTaskExecution, profile.execution_id)
                report = session.get(AuditReport, profile.report_id)
                job = session.get(AsyncJob, profile.report_job_id)
                steps = tuple(
                    session.scalars(
                        select(AsyncJobStep)
                        .where(AsyncJobStep.job_id == profile.report_job_id)
                        .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                    ).all()
                )
                if job is not None and job.status in {
                    "succeeded",
                    "failed",
                    "cancelled",
                }:
                    raise ReportCrashRecoveryError("REPORT_FINISHED_BEFORE_CRASH")
                if (
                    execution is not None
                    and execution.status == "completed"
                    and report is not None
                    and report.execution_id == profile.execution_id
                    and report.report_version == profile.report_version
                    and report.status == "generating"
                    and report.job_id == profile.report_job_id
                    and report.pdf_object_key is None
                    and report.xlsx_object_key is None
                    and job is not None
                    and job.status == "running"
                    and job.attempt_no == 1
                    and [
                        (step.attempt_no, step.step_code, step.status) for step in steps
                    ]
                    == [(1, "generate", "running")]
                ):
                    print(f"LOCAL_REPORT_GENERATE_RUNNING_JOB_ID={job.id}")
                    print("LOCAL_REPORT_GENERATE_RUNNING_GATE=PASS")
                    return
            time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        engine.dispose()
    raise ReportCrashRecoveryError("REPORT_RUNNING_TIMEOUT")


def run_verify_objects_before_crash() -> None:
    profile = _report_profile()
    settings = Settings()
    expected = _expected_artifacts(settings, profile)
    _verify_stored_artifacts(settings, expected)
    print(f"LOCAL_REPORT_GENERATE_PRECRASH_PDF_SHA256={expected.pdf_sha256}")
    print(f"LOCAL_REPORT_GENERATE_PRECRASH_PDF_SIZE={len(expected.pdf)}")
    print(f"LOCAL_REPORT_GENERATE_PRECRASH_XLSX_SHA256={expected.xlsx_sha256}")
    print(f"LOCAL_REPORT_GENERATE_PRECRASH_XLSX_SIZE={len(expected.xlsx)}")
    print("LOCAL_REPORT_GENERATE_OBJECTS_BEFORE_CRASH_GATE=PASS")


def run_before_recovery_verification() -> None:
    profile = _report_profile()
    settings = Settings()
    expected = _expected_artifacts(settings, profile)
    engine = create_application_engine(settings)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            execution = session.get(AuditTaskExecution, profile.execution_id)
            report = session.get(AuditReport, profile.report_id)
            job = session.get(AsyncJob, profile.report_job_id)
            steps = tuple(
                session.scalars(
                    select(AsyncJobStep)
                    .where(AsyncJobStep.job_id == profile.report_job_id)
                    .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                ).all()
            )
            generated_log_count = session.scalar(
                select(func.count())
                .select_from(OperationLog)
                .where(
                    OperationLog.resource_type == "audit_report",
                    OperationLog.resource_id == profile.report_id,
                    OperationLog.action_code == "reports.generated",
                )
            )
    finally:
        engine.dispose()
    if (
        execution is None
        or execution.status != "completed"
        or report is None
        or report.status != "generating"
        or report.payload_sha256 != expected.payload_sha256
        or report.pdf_bucket is not None
        or report.pdf_object_key is not None
        or report.pdf_sha256 is not None
        or report.pdf_size_bytes is not None
        or report.xlsx_bucket is not None
        or report.xlsx_object_key is not None
        or report.xlsx_sha256 is not None
        or report.xlsx_size_bytes is not None
        or report.generated_at is not None
        or job is None
        or job.status != "running"
        or job.attempt_no != 1
        or [(step.attempt_no, step.step_code, step.status) for step in steps]
        != [(1, "generate", "running")]
        or generated_log_count != 0
    ):
        raise ReportCrashRecoveryError("BEFORE_RECOVERY_DATABASE_STATE_INVALID")
    _verify_stored_artifacts(settings, expected)
    print("LOCAL_REPORT_GENERATE_ZERO_DATABASE_FACTS_BEFORE_RECOVERY_GATE=PASS")
    print("LOCAL_REPORT_GENERATE_ORPHAN_OBJECTS_PRESERVED_GATE=PASS")


def run_verify_client() -> None:
    base_url, origin, _admin_username, run_id = _client_profile()
    profile = _report_profile()
    if profile.run_id != run_id:
        raise ReportCrashRecoveryError("RUN_ID_DRIFT")
    expected_payload_sha256 = _required_sha256("FINAUDIT_REPORT_PAYLOAD_SHA256")
    expected_pdf_sha256 = _required_sha256("FINAUDIT_REPORT_PDF_SHA256")
    expected_pdf_size = _required_positive_integer("FINAUDIT_REPORT_PDF_SIZE")
    expected_xlsx_sha256 = _required_sha256("FINAUDIT_REPORT_XLSX_SHA256")
    expected_xlsx_size = _required_positive_integer("FINAUDIT_REPORT_XLSX_SIZE")
    admin_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    finance_username, finance_password = _reviewer_credentials(admin_password, run_id)
    with _client(base_url, origin) as client:
        token = _login(client, finance_username, finance_password)
        authorization = {"Authorization": f"Bearer {token}"}
        deadline = time.monotonic() + _REPORT_RECOVERY_TIMEOUT_SECONDS
        report: dict[str, object] | None = None
        while time.monotonic() < deadline:
            current = _require_envelope(
                client.get(
                    f"/api/v1/audit-reports/{profile.report_id}",
                    headers=authorization,
                ),
                200,
            )
            status = current.get("status")
            if status in {"failed", "outdated", "archived"}:
                raise ReportCrashRecoveryError("REPORT_RECOVERY_FAILED")
            if status == "ready":
                report = current
                break
            time.sleep(_POLL_INTERVAL_SECONDS)
        if report is None:
            raise ReportCrashRecoveryError("REPORT_RECOVERY_TIMEOUT")
        if (
            report.get("id") != str(profile.report_id)
            or report.get("audit_task_id") != str(profile.task_id)
            or report.get("execution_id") != str(profile.execution_id)
            or report.get("report_version") != profile.report_version
            or report.get("status") != "ready"
            or report.get("payload_sha256") != expected_payload_sha256
            or report.get("pdf_sha256") != expected_pdf_sha256
            or report.get("pdf_size_bytes") != expected_pdf_size
            or report.get("pdf_mime_type") != _PDF_MIME_TYPE
            or report.get("xlsx_sha256") != expected_xlsx_sha256
            or report.get("xlsx_size_bytes") != expected_xlsx_size
            or report.get("xlsx_mime_type") != _XLSX_MIME_TYPE
            or report.get("job_id") != str(profile.report_job_id)
            or report.get("failure_code") is not None
            or report.get("row_version") != "3"
            or not isinstance(report.get("generated_at"), str)
            or report.get("is_outdated") is not False
        ):
            raise ReportCrashRecoveryError("REPORT_DETAIL_INVALID")
        report_list = _require_envelope(
            client.get(
                f"/api/v1/audit-executions/{profile.execution_id}/reports",
                headers=authorization,
            ),
            200,
        )
        if report_list != {
            "execution_id": str(profile.execution_id),
            "items": [report],
        }:
            raise ReportCrashRecoveryError("REPORT_LIST_DRIFT")
        preview = client.get(
            f"/api/v1/audit-reports/{profile.report_id}/preview",
            headers=authorization,
        )
        if (
            preview.status_code != 200
            or len(preview.content) != expected_pdf_size
            or hashlib.sha256(preview.content).hexdigest() != expected_pdf_sha256
            or preview.headers.get("content-type") != _PDF_MIME_TYPE
            or preview.headers.get("etag") != f'"{expected_pdf_sha256}"'
            or preview.headers.get("x-report-status") != "ready"
            or preview.headers.get("x-report-outdated") != "false"
            or preview.headers.get("x-content-type-options") != "nosniff"
            or preview.headers.get("content-disposition")
            != f'inline; filename="audit-report-{profile.report_id}-v{profile.report_version}.pdf"'
        ):
            raise ReportCrashRecoveryError("REPORT_PREVIEW_INVALID")
        download = client.get(
            f"/api/v1/audit-reports/{profile.report_id}/download",
            headers=authorization,
        )
        if (
            download.status_code != 200
            or len(download.content) != expected_xlsx_size
            or hashlib.sha256(download.content).hexdigest() != expected_xlsx_sha256
            or download.headers.get("content-type") != _XLSX_MIME_TYPE
            or download.headers.get("etag") != f'"{expected_xlsx_sha256}"'
            or download.headers.get("x-report-status") != "ready"
            or download.headers.get("x-report-outdated") != "false"
            or download.headers.get("x-content-type-options") != "nosniff"
            or download.headers.get("content-disposition")
            != (
                f'attachment; filename="audit-report-{profile.report_id}-'
                f'v{profile.report_version}-risks.xlsx"'
            )
        ):
            raise ReportCrashRecoveryError("REPORT_DOWNLOAD_INVALID")
    print("LOCAL_REPORT_GENERATE_CRASH_CLIENT_GATE=PASS")


def run_final_database_verification() -> None:
    profile = _report_profile()
    settings = Settings()
    expected = _expected_artifacts(settings, profile)
    engine = create_application_engine(settings)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            execution = session.get(AuditTaskExecution, profile.execution_id)
            reports = tuple(
                session.scalars(
                    select(AuditReport).where(
                        AuditReport.execution_id == profile.execution_id
                    )
                ).all()
            )
            job = session.get(AsyncJob, profile.report_job_id)
            steps = tuple(
                session.scalars(
                    select(AsyncJobStep)
                    .where(AsyncJobStep.job_id == profile.report_job_id)
                    .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                ).all()
            )
            outbox = tuple(
                session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_type == "async_job",
                        OutboxEvent.aggregate_id == profile.report_job_id,
                    )
                ).all()
            )
            report_logs = tuple(
                session.scalars(
                    select(OperationLog)
                    .where(
                        OperationLog.resource_type == "audit_report",
                        OperationLog.resource_id == profile.report_id,
                    )
                    .order_by(OperationLog.created_at, OperationLog.id)
                ).all()
            )
    finally:
        engine.dispose()
    if (
        execution is None
        or execution.status != "completed"
        or len(reports) != 1
        or reports[0].id != profile.report_id
        or job is None
        or len(steps) != 2
        or len(outbox) != 1
        or outbox[0].status != "published"
    ):
        raise ReportCrashRecoveryError("FINAL_REPORT_CLUSTER_CARDINALITY_INVALID")
    report = reports[0]
    if (
        report.status != "ready"
        or report.report_version != profile.report_version
        or report.job_id != profile.report_job_id
        or report.payload_sha256 != expected.payload_sha256
        or report.pdf_bucket != expected.pdf_locator.bucket_name
        or report.pdf_object_key != expected.pdf_locator.object_key
        or report.pdf_sha256 != expected.pdf_sha256
        or report.pdf_size_bytes != len(expected.pdf)
        or report.pdf_mime_type != _PDF_MIME_TYPE
        or report.xlsx_bucket != expected.xlsx_locator.bucket_name
        or report.xlsx_object_key != expected.xlsx_locator.object_key
        or report.xlsx_sha256 != expected.xlsx_sha256
        or report.xlsx_size_bytes != len(expected.xlsx)
        or report.xlsx_mime_type != _XLSX_MIME_TYPE
        or report.generated_at is None
        or report.failure_code is not None
        or report.row_version != 3
    ):
        raise ReportCrashRecoveryError("FINAL_REPORT_ROW_INVALID")
    expected_summary: dict[str, object] = {
        "report_id": str(profile.report_id),
        "pdf_sha256": expected.pdf_sha256,
        "pdf_size_bytes": len(expected.pdf),
        "xlsx_sha256": expected.xlsx_sha256,
        "xlsx_size_bytes": len(expected.xlsx),
    }
    if (
        job.job_type != "report_generate"
        or job.resource_type != "audit_report"
        or job.resource_id != profile.report_id
        or job.status != "succeeded"
        or job.attempt_no != 2
        or job.stage != "generate"
        or job.current_attempt_start_step_code != "generate"
        or job.error_code is not None
        or job.error_message is not None
    ):
        raise ReportCrashRecoveryError("FINAL_REPORT_JOB_INVALID")
    if [
        (
            step.attempt_no,
            step.step_code,
            step.status,
            step.error_code,
            step.summary_json,
        )
        for step in steps
    ] != [
        (1, "generate", "failed", "LEASE_EXPIRED", {}),
        (2, "generate", "succeeded", None, expected_summary),
    ]:
        raise ReportCrashRecoveryError("FINAL_REPORT_ATTEMPT_HISTORY_INVALID")
    actions = [log.action_code for log in report_logs]
    if (
        actions.count("reports.generated") != 1
        or actions.count("reports.pdf_previewed") != 1
        or actions.count("reports.xlsx_downloaded") != 1
    ):
        raise ReportCrashRecoveryError("FINAL_REPORT_OPERATION_LOG_INVALID")
    generated_log = next(
        log for log in report_logs if log.action_code == "reports.generated"
    )
    if (
        generated_log.trace_id != job.trace_id
        or generated_log.outcome != "succeeded"
        or generated_log.change_summary_json
        != {
            "pdf_sha256": expected.pdf_sha256,
            "pdf_size_bytes": len(expected.pdf),
            "status": "ready",
            "xlsx_sha256": expected.xlsx_sha256,
            "xlsx_size_bytes": len(expected.xlsx),
        }
    ):
        raise ReportCrashRecoveryError("FINAL_REPORT_GENERATED_LOG_INVALID")
    _verify_stored_artifacts(settings, expected)
    print("LOCAL_REPORT_GENERATE_ATTEMPT_HISTORY_DATABASE_GATE=PASS")
    print("LOCAL_REPORT_GENERATE_UNIQUE_FACTS_DATABASE_GATE=PASS")
    print("LOCAL_REPORT_GENERATE_CRASH_DATABASE_GATE=PASS")


def main() -> int:
    try:
        if sys.argv == [sys.argv[0], "wait-audit-ready"]:
            run_wait_for_audit_ready()
        elif sys.argv == [sys.argv[0], "queue-report"]:
            run_queue_report_client()
            print("LOCAL_REPORT_GENERATE_QUEUE_GATE=PASS")
        elif sys.argv == [sys.argv[0], "wait-running"]:
            run_wait_for_report_running()
        elif sys.argv == [sys.argv[0], "verify-objects"]:
            run_verify_objects_before_crash()
        elif sys.argv == [sys.argv[0], "before-recovery"]:
            run_before_recovery_verification()
        elif sys.argv == [sys.argv[0], "verify-client"]:
            run_verify_client()
        elif sys.argv == [sys.argv[0], "database"]:
            run_final_database_verification()
        else:
            raise ReportCrashRecoveryError("ARGUMENTS_INVALID")
    except (
        AuditCrashRecoveryError,
        CrashRecoveryError,
        ReportCrashRecoveryError,
        SmokeError,
    ) as error:
        print("LOCAL_REPORT_GENERATE_CRASH_RECOVERY=FAIL")
        print(f"LOCAL_REPORT_GENERATE_CRASH_REASON={error}")
        return 1
    except Exception as error:
        print("LOCAL_REPORT_GENERATE_CRASH_RECOVERY=FAIL")
        print(
            f"LOCAL_REPORT_GENERATE_CRASH_REASON=UNEXPECTED_{type(error).__name__.upper()}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
