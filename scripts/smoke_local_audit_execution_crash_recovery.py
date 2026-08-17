from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
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

from app.audit.offline_preview import RiskLevel
from app.audit.rule_catalog import publish_builtin_catalog
from app.audit.snapshot import (
    AuditSnapshotFacts,
    build_aggregate_audit_preview,
    snapshot_sha256,
)
from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.models.audit import (
    AuditRisk,
    AuditRule,
    AuditTask,
    AuditTaskExecution,
    AuditTaskItem,
    AuditTaskSnapshot,
    RuleExecution,
)
from app.models.auth import Organization, User
from app.models.financial import Contract, Invoice, InvoiceItem
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, AsyncJobStep

_SCHEMA_VERSION = "finaudit-local-audit-execute-crash-v1"
_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_RUNNING_TIMEOUT_SECONDS = 90
_RECOVERY_TIMEOUT_SECONDS = 180
_BASELINE_DATE = date(2027, 1, 15)
_EXPECTED_RULE_CODES = tuple(f"RULE-{number:03d}" for number in range(1, 16))
_EXPECTED_RULE_STATUSES = {
    **{rule_code: "passed" for rule_code in _EXPECTED_RULE_CODES},
    "RULE-002": "failed",
    "RULE-004": "failed",
    "RULE-013": "not_applicable",
}
_EXPECTED_RISK_LEVELS = {"RULE-002": "high", "RULE-004": "medium"}


class AuditCrashRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _AuditCluster:
    task: AuditTask | None
    execution: AuditTaskExecution | None
    snapshot: AuditTaskSnapshot | None
    jobs: tuple[AsyncJob, ...]
    steps: tuple[AsyncJobStep, ...]
    items: tuple[AuditTaskItem, ...]
    rules: tuple[RuleExecution, ...]
    risks: tuple[AuditRisk, ...]
    evaluated_logs: tuple[OperationLog, ...]


def _validate_run_id(run_id: str) -> None:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise AuditCrashRecoveryError("RUN_ID_INVALID")


def _lock_application_name(run_id: str) -> str:
    _validate_run_id(run_id)
    identity = f"finaudit-audit-crash-{run_id}"
    if len(identity.encode("ascii")) > 63:
        raise AuditCrashRecoveryError("LOCK_IDENTITY_INVALID")
    return identity


def _seed_identities(run_id: str) -> tuple[UUID, UUID, UUID]:
    _validate_run_id(run_id)
    return (
        uuid5(NAMESPACE_URL, f"{_SCHEMA_VERSION}:{run_id}:contract"),
        uuid5(NAMESPACE_URL, f"{_SCHEMA_VERSION}:{run_id}:invoice"),
        uuid5(NAMESPACE_URL, f"{_SCHEMA_VERSION}:{run_id}:invoice-item"),
    )


def _task_no(run_id: str) -> str:
    _validate_run_id(run_id)
    return f"CRASH-AUDIT-{run_id[:12].upper()}"


def _task_payload(
    run_id: str, contract_id: UUID, invoice_id: UUID
) -> dict[str, object]:
    _validate_run_id(run_id)
    return {
        "task_no": _task_no(run_id),
        "name": f"Worker 强杀恢复审核 {run_id[:8].upper()}",
        "description": "本地 audit_execute 事务回滚与租约恢复门禁",
        "baseline_date": _BASELINE_DATE.isoformat(),
        "contract_id": str(contract_id),
        "invoice_ids": [str(invoice_id)],
    }


def _reviewer_credentials(admin_password: str, run_id: str) -> tuple[str, str]:
    _validate_run_id(run_id)
    digest = hashlib.sha256(
        f"{admin_password}\0{run_id}\0audit-crash".encode("utf-8")
    ).hexdigest()
    return f"audit-crash-{run_id[:12]}", f"Ac9!{digest[:24]}"


def _client(base_url: str, origin: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        verify=False,
        timeout=httpx.Timeout(15),
        headers={"Origin": origin, "Host": origin.removeprefix("https://")},
    )


def _client_profile() -> tuple[str, str, str, str]:
    base_url = _required_environment("FINAUDIT_SMOKE_BASE_URL")
    origin = _required_environment("AUTH_PUBLIC_ORIGIN")
    username = _required_environment("BOOTSTRAP_ADMIN_USERNAME")
    run_id = _required_environment("FINAUDIT_CRASH_RUN_ID")
    _validate_run_id(run_id)
    if base_url != "https://frontend:8443" or not origin.startswith(
        "https://localhost:"
    ):
        raise AuditCrashRecoveryError("CLIENT_PROFILE_INVALID")
    return base_url, origin, username, run_id


def _database_profile() -> tuple[str, UUID, UUID, UUID]:
    run_id = _required_environment("FINAUDIT_CRASH_RUN_ID")
    _validate_run_id(run_id)
    return (
        run_id,
        _canonical_uuid(
            _required_environment("FINAUDIT_CRASH_TASK_ID"),
            "DATABASE_TASK_ID_INVALID",
        ),
        _canonical_uuid(
            _required_environment("FINAUDIT_CRASH_EXECUTION_ID"),
            "DATABASE_EXECUTION_ID_INVALID",
        ),
        _canonical_uuid(
            _required_environment("FINAUDIT_CRASH_JOB_ID"),
            "DATABASE_JOB_ID_INVALID",
        ),
    )


def run_seed_database() -> None:
    run_id = _required_environment("FINAUDIT_CRASH_RUN_ID")
    _validate_run_id(run_id)
    admin_username = _required_environment("BOOTSTRAP_ADMIN_USERNAME")
    contract_id, invoice_id, item_id = _seed_identities(run_id)
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory.begin() as session:
            users = tuple(
                session.scalars(
                    select(User).where(
                        User.username == admin_username,
                        User.deleted_at.is_(None),
                    )
                ).all()
            )
            if len(users) != 1 or users[0].status != "active":
                raise AuditCrashRecoveryError("ADMIN_SUBJECT_INVALID")
            actor = users[0]
            organization = session.get(Organization, actor.organization_id)
            if (
                organization is None
                or organization.status != "active"
                or organization.deleted_at is not None
            ):
                raise AuditCrashRecoveryError("ORGANIZATION_SUBJECT_INVALID")
            if (
                session.get(Contract, contract_id) is not None
                or session.get(Invoice, invoice_id) is not None
                or session.get(InvoiceItem, item_id) is not None
            ):
                raise AuditCrashRecoveryError("AUDIT_SEED_COLLISION")
            now = session.scalar(select(func.clock_timestamp()))
            if now is None:
                raise AuditCrashRecoveryError("DATABASE_CLOCK_UNAVAILABLE")
            seller_tax_number = f"CRASHSELL{run_id[:20].upper()}"
            session.add(
                Contract(
                    id=contract_id,
                    organization_id=organization.id,
                    contract_no=f"CRASH-{run_id[:12].upper()}",
                    name="Worker 强杀恢复审核合同",
                    party_a_name=organization.name,
                    party_a_tax_no=organization.tax_number,
                    party_b_name="Worker 强杀恢复供应商",
                    party_b_tax_no=seller_tax_number,
                    supplier_id=None,
                    amount=Decimal("1000.00"),
                    currency="CNY",
                    signed_date=date(2026, 1, 1),
                    effective_date=date(2026, 1, 1),
                    expiry_date=date(2026, 12, 31),
                    payment_method=None,
                    payment_terms=None,
                    confirmation_status="confirmed",
                    status="active",
                    confirmed_by=actor.id,
                    confirmed_at=now,
                    critical_fact_hash=hashlib.sha256(
                        f"{run_id}:audit-contract".encode("ascii")
                    ).hexdigest(),
                    row_version=1,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )
            session.flush()
            invoice = Invoice(
                id=invoice_id,
                organization_id=organization.id,
                invoice_code=f"AC{run_id[:12].upper()}",
                invoice_number=run_id[12:24].upper(),
                invoice_type="vat_special",
                is_red_invoice=False,
                invoice_date=date(2027, 1, 10),
                buyer_name="Worker 强杀恢复不匹配购买方",
                buyer_tax_no=f"MISMATCH{run_id[:20].upper()}",
                seller_name="Worker 强杀恢复供应商",
                seller_tax_no=seller_tax_number,
                supplier_id=None,
                amount_excluding_tax=Decimal("100.00"),
                tax_amount=Decimal("6.00"),
                total_amount=Decimal("106.00"),
                currency="CNY",
                confirmation_status="unconfirmed",
                duplicate_status="unique",
                status="draft",
                field_evidence_json={},
                confirmed_by=None,
                confirmed_at=None,
                critical_fact_hash=hashlib.sha256(
                    f"{run_id}:audit-invoice".encode("ascii")
                ).hexdigest(),
                row_version=1,
                created_by=actor.id,
                updated_by=actor.id,
            )
            session.add(invoice)
            session.flush()
            session.add(
                InvoiceItem(
                    id=item_id,
                    invoice_id=invoice_id,
                    line_no=1,
                    item_name="Worker 强杀恢复审计服务费",
                    specification=None,
                    unit=None,
                    quantity=Decimal("1.000000"),
                    unit_price=Decimal("100.000000"),
                    amount_excluding_tax=Decimal("100.00"),
                    tax_rate=Decimal("0.060000"),
                    tax_amount=Decimal("6.00"),
                    total_amount=Decimal("106.00"),
                    evidence_json={},
                    row_version=1,
                )
            )
            session.flush()
            invoice.confirmation_status = "confirmed"
            invoice.status = "confirmed"
            invoice.confirmed_by = actor.id
            invoice.confirmed_at = now
            invoice.row_version = 2
            session.flush()
            publish_builtin_catalog(
                session,
                application_release="local-audit-crash-v1",
                change_reason="publish local audit execution crash recovery catalog",
            )
    finally:
        engine.dispose()


def run_prepare_client() -> None:
    base_url, origin, admin_username, run_id = _client_profile()
    admin_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    reviewer_username, reviewer_password = _reviewer_credentials(admin_password, run_id)
    contract_id, invoice_id, _item_id = _seed_identities(run_id)
    payload = _task_payload(run_id, contract_id, invoice_id)
    with _client(base_url, origin) as client:
        admin_token = _login(client, admin_username, admin_password)
        _require_envelope(
            client.post(
                "/api/v1/users",
                headers={
                    "Authorization": f"Bearer {admin_token}",
                    "Idempotency-Key": f"local-audit-crash-user.{run_id}",
                },
                json={
                    "username": reviewer_username,
                    "display_name": "本地审核执行强杀恢复账号",
                    "initial_password": reviewer_password,
                    "fixed_roles": ["finance_reviewer"],
                },
            ),
            201,
        )
        reviewer_token = _login(client, reviewer_username, reviewer_password)
        accepted = _require_envelope(
            client.post(
                "/api/v1/audit-tasks",
                headers={
                    "Authorization": f"Bearer {reviewer_token}",
                    "Idempotency-Key": f"local-audit-crash-task.{run_id}",
                },
                json=payload,
            ),
            202,
        )
    task = accepted.get("task")
    execution = accepted.get("execution")
    if not isinstance(task, dict) or not isinstance(execution, dict):
        raise AuditCrashRecoveryError("AUDIT_CREATE_CONTRACT_INVALID")
    task_id = _canonical_uuid(task.get("id"), "AUDIT_TASK_ID_INVALID")
    execution_id = _canonical_uuid(execution.get("id"), "AUDIT_EXECUTION_ID_INVALID")
    job_id = _canonical_uuid(execution.get("job_id"), "AUDIT_JOB_ID_INVALID")
    if (
        task.get("task_no") != payload["task_no"]
        or task.get("current_execution_id") != str(execution_id)
        or task.get("status") != "open"
        or execution.get("audit_task_id") != str(task_id)
        or execution.get("status") != "queued"
        or execution.get("baseline_date") != _BASELINE_DATE.isoformat()
    ):
        raise AuditCrashRecoveryError("AUDIT_CREATE_RESULT_INVALID")
    print(f"LOCAL_AUDIT_EXECUTE_TASK_ID={task_id}")
    print(f"LOCAL_AUDIT_EXECUTE_EXECUTION_ID={execution_id}")
    print(f"LOCAL_AUDIT_EXECUTE_JOB_ID={job_id}")


def _load_cluster(
    session: Session,
    *,
    task_id: UUID,
    execution_id: UUID,
    job_id: UUID,
) -> _AuditCluster:
    task = session.get(AuditTask, task_id)
    execution = session.get(AuditTaskExecution, execution_id)
    snapshot = session.scalar(
        select(AuditTaskSnapshot).where(AuditTaskSnapshot.execution_id == execution_id)
    )
    jobs = tuple(
        session.scalars(
            select(AsyncJob)
            .where(
                AsyncJob.resource_type == "audit_task_execution",
                AsyncJob.resource_id == execution_id,
            )
            .order_by(AsyncJob.created_at, AsyncJob.id)
        ).all()
    )
    steps = tuple(
        session.scalars(
            select(AsyncJobStep)
            .where(AsyncJobStep.job_id == job_id)
            .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
        ).all()
    )
    items = tuple(
        session.scalars(
            select(AuditTaskItem)
            .where(AuditTaskItem.audit_task_id == task_id)
            .order_by(AuditTaskItem.item_type, AuditTaskItem.id)
        ).all()
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
    evaluated_logs = tuple(
        session.scalars(
            select(OperationLog)
            .where(
                OperationLog.resource_type == "audit_task_execution",
                OperationLog.resource_id == execution_id,
                OperationLog.action_code == "audits.execution_evaluated",
            )
            .order_by(OperationLog.created_at, OperationLog.id)
        ).all()
    )
    if jobs and jobs[0].id != job_id:
        raise AuditCrashRecoveryError("AUDIT_JOB_ID_DRIFT")
    return _AuditCluster(
        task,
        execution,
        snapshot,
        jobs,
        steps,
        items,
        rules,
        risks,
        evaluated_logs,
    )


def run_wait_for_execution() -> None:
    _run_id, task_id, execution_id, job_id = _database_profile()
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        deadline = time.monotonic() + _RUNNING_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with factory() as session:
                task = session.get(AuditTask, task_id)
                execution = session.get(AuditTaskExecution, execution_id)
                snapshot = session.scalar(
                    select(AuditTaskSnapshot).where(
                        AuditTaskSnapshot.execution_id == execution_id
                    )
                )
                jobs = tuple(
                    session.scalars(
                        select(AsyncJob).where(
                            AsyncJob.resource_type == "audit_task_execution",
                            AsyncJob.resource_id == execution_id,
                        )
                    ).all()
                )
                job = jobs[0] if len(jobs) == 1 else None
                steps = tuple(
                    session.scalars(
                        select(AsyncJobStep)
                        .where(AsyncJobStep.job_id == job_id)
                        .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                    ).all()
                )
                evaluated_log_count = session.scalar(
                    select(func.count())
                    .select_from(OperationLog)
                    .where(
                        OperationLog.resource_type == "audit_task_execution",
                        OperationLog.resource_id == execution_id,
                        OperationLog.action_code == "audits.execution_evaluated",
                    )
                )
                if job is not None and job.status in {
                    "succeeded",
                    "failed",
                    "cancelled",
                }:
                    raise AuditCrashRecoveryError("AUDIT_FINISHED_BEFORE_CRASH")
                if (
                    task is not None
                    and task.current_execution_id == execution_id
                    and task.status == "open"
                    and execution is not None
                    and execution.status == "running"
                    and execution.job_id == job_id
                    and snapshot is not None
                    and job is not None
                    and job.id == job_id
                    and job.status == "running"
                    and job.attempt_no == 1
                    and [
                        (step.attempt_no, step.step_code, step.status) for step in steps
                    ]
                    == [(1, "evaluate", "running")]
                    and evaluated_log_count == 0
                ):
                    print(f"LOCAL_AUDIT_EXECUTE_RUNNING_JOB_ID={job.id}")
                    return
            time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        engine.dispose()
    raise AuditCrashRecoveryError("AUDIT_RUNNING_TIMEOUT")


def run_before_recovery_verification() -> None:
    _run_id, task_id, execution_id, job_id = _database_profile()
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            cluster = _load_cluster(
                session,
                task_id=task_id,
                execution_id=execution_id,
                job_id=job_id,
            )
    finally:
        engine.dispose()
    job = cluster.jobs[0] if len(cluster.jobs) == 1 else None
    if (
        cluster.task is None
        or cluster.task.current_execution_id != execution_id
        or cluster.task.status != "open"
        or cluster.execution is None
        or cluster.execution.audit_task_id != task_id
        or cluster.execution.status != "running"
        or cluster.execution.job_id != job_id
        or cluster.snapshot is None
        or cluster.snapshot.audit_task_id != task_id
        or cluster.snapshot.execution_id != execution_id
        or len(cluster.items) != 2
        or job is None
        or job.status != "running"
        or job.attempt_no != 1
        or [(step.attempt_no, step.step_code, step.status) for step in cluster.steps]
        != [(1, "evaluate", "running")]
        or cluster.rules
        or cluster.risks
        or cluster.evaluated_logs
    ):
        raise AuditCrashRecoveryError("BEFORE_RECOVERY_DATABASE_STATE_INVALID")
    print("LOCAL_AUDIT_EXECUTE_ZERO_FACTS_BEFORE_RECOVERY_GATE=PASS")


def _positive_integer_string(value: object) -> bool:
    return type(value) is str and value.isascii() and value.isdigit() and int(value) > 0


def run_verify_client() -> None:
    base_url, origin, _admin_username, run_id = _client_profile()
    _database_run_id, task_id, execution_id, job_id = _database_profile()
    if _database_run_id != run_id:
        raise AuditCrashRecoveryError("RUN_ID_DRIFT")
    admin_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    reviewer_username, reviewer_password = _reviewer_credentials(admin_password, run_id)
    contract_id, invoice_id, _item_id = _seed_identities(run_id)
    expected_payload = _task_payload(run_id, contract_id, invoice_id)
    with _client(base_url, origin) as client:
        token = _login(client, reviewer_username, reviewer_password)
        authorization = {"Authorization": f"Bearer {token}"}
        deadline = time.monotonic() + _RECOVERY_TIMEOUT_SECONDS
        detail: dict[str, object] | None = None
        while time.monotonic() < deadline:
            current = _require_envelope(
                client.get(f"/api/v1/audit-tasks/{task_id}", headers=authorization),
                200,
            )
            execution = current.get("execution")
            if isinstance(execution, dict):
                status = execution.get("status")
                if status in {"failed", "cancelled", "outdated"}:
                    raise AuditCrashRecoveryError("AUDIT_RECOVERY_FAILED")
                if status == "pending_finance_review":
                    detail = current
                    break
            time.sleep(_POLL_INTERVAL_SECONDS)
        if detail is None:
            raise AuditCrashRecoveryError("AUDIT_RECOVERY_TIMEOUT")
        task = detail.get("task")
        execution = detail.get("execution")
        rules = detail.get("rules")
        risks = detail.get("risks")
        if (
            not isinstance(task, dict)
            or not isinstance(execution, dict)
            or not isinstance(rules, list)
            or not isinstance(risks, list)
        ):
            raise AuditCrashRecoveryError("AUDIT_DETAIL_CONTRACT_INVALID")
        if (
            task.get("id") != str(task_id)
            or task.get("task_no") != expected_payload["task_no"]
            or task.get("name") != expected_payload["name"]
            or task.get("description") != expected_payload["description"]
            or task.get("current_execution_id") != str(execution_id)
            or task.get("status") != "open"
            or not _positive_integer_string(task.get("row_version"))
            or execution.get("id") != str(execution_id)
            or execution.get("audit_task_id") != str(task_id)
            or execution.get("version_no") != 1
            or execution.get("baseline_date") != _BASELINE_DATE.isoformat()
            or execution.get("status") != "pending_finance_review"
            or execution.get("job_id") != str(job_id)
            or not isinstance(execution.get("snapshot_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", execution["snapshot_sha256"]) is None
            or execution.get("finance_reviewer_id") is not None
            or execution.get("finance_reviewed_at") is not None
            or execution.get("audit_reviewer_id") is not None
            or execution.get("audit_reviewed_at") is not None
            or execution.get("retryable") is not False
            or execution.get("failure_code") is not None
            or execution.get("cancel_reason") is not None
            or execution.get("return_reason") is not None
            or not _positive_integer_string(execution.get("row_version"))
            or not isinstance(execution.get("started_at"), str)
            or execution.get("finished_at") is not None
            or execution.get("outdated_at") is not None
        ):
            raise AuditCrashRecoveryError("AUDIT_DETAIL_IDENTITY_INVALID")
        rule_codes = [rule.get("rule_code") for rule in rules if isinstance(rule, dict)]
        if len(rules) != 15 or rule_codes != list(_EXPECTED_RULE_CODES):
            raise AuditCrashRecoveryError("AUDIT_RULE_SET_INVALID")
        for rule in rules:
            if not isinstance(rule, dict):
                raise AuditCrashRecoveryError("AUDIT_RULE_RESULT_INVALID")
            rule_code = rule.get("rule_code")
            if (
                rule_code not in _EXPECTED_RULE_STATUSES
                or rule.get("status") != _EXPECTED_RULE_STATUSES[rule_code]
                or not isinstance(rule.get("id"), str)
                or not isinstance(rule.get("included_item_ids"), list)
                or not isinstance(rule.get("excluded_item_ids"), list)
                or rule.get("excluded_item_ids") != []
            ):
                raise AuditCrashRecoveryError("AUDIT_RULE_RESULT_INVALID")
            _canonical_uuid(rule["id"], "AUDIT_RULE_RESULT_INVALID")
        risk_by_code = {
            risk.get("rule_code"): risk for risk in risks if isinstance(risk, dict)
        }
        if len(risks) != 2 or set(risk_by_code) != set(_EXPECTED_RISK_LEVELS):
            raise AuditCrashRecoveryError("AUDIT_RISK_SET_INVALID")
        for rule_code, level in _EXPECTED_RISK_LEVELS.items():
            risk = risk_by_code[rule_code]
            if (
                risk.get("id") != str(uuid5(execution_id, rule_code))
                or risk.get("original_level") != level
                or risk.get("effective_level") != level
                or risk.get("review_status") != "pending"
                or risk.get("review_reason") is not None
                or risk.get("reviewed_by") is not None
                or risk.get("reviewed_at") is not None
                or risk.get("row_version") != "1"
                or not isinstance(risk.get("actual_value"), str)
                or not isinstance(risk.get("expected_value"), str)
            ):
                raise AuditCrashRecoveryError("AUDIT_RISK_RESULT_INVALID")
        execution_detail = _require_envelope(
            client.get(
                f"/api/v1/audit-executions/{execution_id}", headers=authorization
            ),
            200,
        )
        if execution_detail != {"execution": execution}:
            raise AuditCrashRecoveryError("AUDIT_EXECUTION_DETAIL_DRIFT")
        page = _require_envelope(
            client.get("/api/v1/audit-tasks?page_size=100", headers=authorization),
            200,
        )
        items = page.get("items")
        if (
            not isinstance(items, list)
            or len(
                [
                    item
                    for item in items
                    if isinstance(item, dict) and item.get("id") == str(task_id)
                ]
            )
            != 1
        ):
            raise AuditCrashRecoveryError("AUDIT_LIST_RESULT_INVALID")


def _expected_scalar(value: str | None) -> dict[str, str] | None:
    return None if value is None else {"value": value}


def run_final_database_verification() -> None:
    run_id, task_id, execution_id, job_id = _database_profile()
    contract_id, invoice_id, item_id = _seed_identities(run_id)
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            cluster = _load_cluster(
                session,
                task_id=task_id,
                execution_id=execution_id,
                job_id=job_id,
            )
            contract = session.get(Contract, contract_id)
            invoice = session.get(Invoice, invoice_id)
            invoice_item = session.get(InvoiceItem, item_id)
            rule_versions = (
                ()
                if cluster.snapshot is None
                else tuple(
                    session.scalars(
                        select(AuditRule)
                        .where(AuditRule.id.in_(cluster.snapshot.rule_version_ids))
                        .order_by(AuditRule.rule_code)
                    ).all()
                )
            )
            creation_logs = tuple(
                session.scalars(
                    select(OperationLog).where(
                        OperationLog.resource_type == "audit_task",
                        OperationLog.resource_id == task_id,
                        OperationLog.action_code == "audits.task_created",
                    )
                ).all()
            )
    finally:
        engine.dispose()
    job = cluster.jobs[0] if len(cluster.jobs) == 1 else None
    if (
        contract is None
        or invoice is None
        or invoice_item is None
        or cluster.task is None
        or cluster.execution is None
        or cluster.snapshot is None
        or job is None
        or len(cluster.items) != 2
        or len(cluster.rules) != 15
        or len(cluster.risks) != 2
        or len(cluster.evaluated_logs) != 1
        or len(creation_logs) != 1
        or len(rule_versions) != 15
    ):
        raise AuditCrashRecoveryError("FINAL_AUDIT_CLUSTER_CARDINALITY_INVALID")
    if (
        contract.contract_no != f"CRASH-{run_id[:12].upper()}"
        or contract.confirmation_status != "confirmed"
        or contract.status != "active"
        or contract.amount != Decimal("1000.00")
        or contract.currency != "CNY"
        or contract.effective_date != date(2026, 1, 1)
        or contract.expiry_date != date(2026, 12, 31)
        or invoice.invoice_code != f"AC{run_id[:12].upper()}"
        or invoice.invoice_number != run_id[12:24].upper()
        or invoice.confirmation_status != "confirmed"
        or invoice.status != "confirmed"
        or invoice.total_amount != Decimal("106.00")
        or invoice.invoice_date != date(2027, 1, 10)
        or invoice.is_red_invoice is not False
        or invoice_item.invoice_id != invoice_id
        or invoice_item.amount_excluding_tax != Decimal("100.00")
        or invoice_item.tax_amount != Decimal("6.00")
        or invoice_item.total_amount != Decimal("106.00")
    ):
        raise AuditCrashRecoveryError("FINAL_AUDIT_SEED_FACTS_INVALID")
    item_identities = {
        (item.item_type, item.contract_id, item.invoice_id) for item in cluster.items
    }
    if item_identities != {
        ("contract", contract_id, None),
        ("invoice", None, invoice_id),
    }:
        raise AuditCrashRecoveryError("FINAL_AUDIT_TASK_ITEMS_INVALID")
    if (
        cluster.task.task_no != _task_no(run_id)
        or cluster.task.current_execution_id != execution_id
        or cluster.task.status != "open"
        or cluster.execution.audit_task_id != task_id
        or cluster.execution.version_no != 1
        or cluster.execution.baseline_date != _BASELINE_DATE
        or cluster.execution.status != "pending_finance_review"
        or cluster.execution.job_id != job_id
        or cluster.execution.snapshot_sha256 != cluster.snapshot.facts_sha256
        or cluster.execution.retryable
        or cluster.execution.failure_code is not None
        or cluster.execution.finished_at is not None
        or cluster.snapshot.audit_task_id != task_id
        or cluster.snapshot.execution_id != execution_id
        or cluster.snapshot.schema_version != 1
        or cluster.snapshot.baseline_date != _BASELINE_DATE
        or cluster.snapshot.rule_version_ids != [rule.id for rule in rule_versions]
    ):
        raise AuditCrashRecoveryError("FINAL_AUDIT_TASK_STATE_INVALID")
    frozen = AuditSnapshotFacts.model_validate(cluster.snapshot.facts_json)
    if (
        frozen.task_id != task_id
        or frozen.execution_id != execution_id
        or frozen.contract_id != contract_id
        or tuple(item.invoice_id for item in frozen.invoices) != (invoice_id,)
        or frozen.retrieval_completed_successfully
        or frozen.has_applicable_policy_citation
        or snapshot_sha256(frozen) != cluster.snapshot.facts_sha256
    ):
        raise AuditCrashRecoveryError("FINAL_AUDIT_SNAPSHOT_INVALID")
    preview = build_aggregate_audit_preview(
        frozen,
        {rule.rule_code: RiskLevel(rule.default_risk_level) for rule in rule_versions},
    )
    if (
        tuple(result.rule_id for result in preview.rules) != _EXPECTED_RULE_CODES
        or {result.rule_id: result.status.value for result in preview.rules}
        != _EXPECTED_RULE_STATUSES
        or {result.rule_id for result in preview.rules if result.risk_id is not None}
        != set(_EXPECTED_RISK_LEVELS)
        or preview.summary.overall_level.value != "high"
    ):
        raise AuditCrashRecoveryError("FINAL_AUDIT_PREVIEW_INVALID")
    rule_version_by_code = {rule.rule_code: rule for rule in rule_versions}
    preview_by_code = {result.rule_id: result for result in preview.rules}
    persisted_rule_by_code = {rule.rule_code: rule for rule in cluster.rules}
    if set(persisted_rule_by_code) != set(_EXPECTED_RULE_CODES):
        raise AuditCrashRecoveryError("FINAL_AUDIT_RULE_IDENTITIES_INVALID")
    for rule_code in _EXPECTED_RULE_CODES:
        persisted = persisted_rule_by_code[rule_code]
        expected = preview_by_code[rule_code]
        if (
            persisted.organization_id != cluster.task.organization_id
            or persisted.audit_task_id != task_id
            or persisted.execution_id != execution_id
            or persisted.snapshot_id != cluster.snapshot.id
            or persisted.audit_rule_id != rule_version_by_code[rule_code].id
            or persisted.status != expected.status.value
            or persisted.input_json
            != {
                "disposition": expected.disposition.value,
                "snapshot_sha256": cluster.snapshot.facts_sha256,
            }
            or persisted.actual_value_json != _expected_scalar(expected.actual_value)
            or persisted.expected_value_json
            != _expected_scalar(expected.expected_value)
            or persisted.included_item_ids != list(expected.reference_ids)
            or persisted.excluded_item_ids != []
            or persisted.error_code is not None
        ):
            raise AuditCrashRecoveryError("FINAL_AUDIT_RULE_FACTS_INVALID")
    risk_by_code = {risk.rule_code: risk for risk in cluster.risks}
    if set(risk_by_code) != set(_EXPECTED_RISK_LEVELS):
        raise AuditCrashRecoveryError("FINAL_AUDIT_RISK_IDENTITIES_INVALID")
    for rule_code, level in _EXPECTED_RISK_LEVELS.items():
        risk = risk_by_code[rule_code]
        expected = preview_by_code[rule_code]
        persisted_rule = persisted_rule_by_code[rule_code]
        if (
            risk.id != expected.risk_id
            or risk.organization_id != cluster.task.organization_id
            or risk.audit_task_id != task_id
            or risk.execution_id != execution_id
            or risk.snapshot_id != cluster.snapshot.id
            or risk.rule_execution_id != persisted_rule.id
            or risk.original_level != level
            or risk.effective_level != level
            or risk.review_status != "pending"
            or risk.actual_value != expected.actual_value
            or risk.expected_value != expected.expected_value
            or risk.review_reason is not None
            or risk.reviewed_by is not None
            or risk.reviewed_at is not None
            or risk.row_version != 1
            or risk.trace_id != job.trace_id
        ):
            raise AuditCrashRecoveryError("FINAL_AUDIT_RISK_FACTS_INVALID")
    if (
        job.job_type != "audit_execute"
        or job.resource_type != "audit_task_execution"
        or job.resource_id != execution_id
        or job.status != "succeeded"
        or job.attempt_no != 2
        or job.error_code is not None
        or job.finished_at is None
        or job.worker_id is not None
        or job.lease_owner is not None
        or job.lease_expires_at is not None
        or job.heartbeat_at is not None
    ):
        raise AuditCrashRecoveryError("FINAL_AUDIT_JOB_STATE_INVALID")
    expected_summary = {
        "execution_id": str(execution_id),
        "rule_count": 15,
        "risk_count": 2,
        "overall_level": "high",
        "retrieval_status": "degraded",
    }
    if [
        (
            step.attempt_no,
            step.step_code,
            step.status,
            step.error_code,
            step.summary_json,
        )
        for step in cluster.steps
    ] != [
        (1, "evaluate", "failed", "LEASE_EXPIRED", {}),
        (2, "evaluate", "succeeded", None, expected_summary),
    ]:
        raise AuditCrashRecoveryError("FINAL_AUDIT_ATTEMPT_HISTORY_INVALID")
    evaluated_log = cluster.evaluated_logs[0]
    if (
        evaluated_log.trace_id != job.trace_id
        or evaluated_log.outcome != "succeeded"
        or evaluated_log.change_summary_json
        != {
            "retrieval_status": "degraded",
            "risk_count": 2,
            "rule_count": 15,
            "status": "pending_finance_review",
        }
    ):
        raise AuditCrashRecoveryError("FINAL_AUDIT_LOG_INVALID")
    print("LOCAL_AUDIT_EXECUTE_ATTEMPT_HISTORY_DATABASE_GATE=PASS")
    print("LOCAL_AUDIT_EXECUTE_UNIQUE_FACTS_DATABASE_GATE=PASS")


def main() -> int:
    try:
        if sys.argv == [sys.argv[0], "seed"]:
            run_seed_database()
            print("LOCAL_AUDIT_EXECUTE_CRASH_SEED_GATE=PASS")
        elif sys.argv == [sys.argv[0], "prepare"]:
            run_prepare_client()
            print("LOCAL_AUDIT_EXECUTE_CRASH_PREPARE_GATE=PASS")
        elif sys.argv == [sys.argv[0], "wait-running"]:
            run_wait_for_execution()
            print("LOCAL_AUDIT_EXECUTE_RUNNING_GATE=PASS")
        elif sys.argv == [sys.argv[0], "before-recovery"]:
            run_before_recovery_verification()
        elif sys.argv == [sys.argv[0], "verify-client"]:
            run_verify_client()
            print("LOCAL_AUDIT_EXECUTE_CRASH_CLIENT_GATE=PASS")
        elif sys.argv == [sys.argv[0], "database"]:
            run_final_database_verification()
            print("LOCAL_AUDIT_EXECUTE_CRASH_DATABASE_GATE=PASS")
        else:
            raise AuditCrashRecoveryError("ARGUMENTS_INVALID")
    except (AuditCrashRecoveryError, CrashRecoveryError, SmokeError) as error:
        print("LOCAL_AUDIT_EXECUTE_CRASH_RECOVERY=FAIL")
        print(f"LOCAL_AUDIT_EXECUTE_CRASH_REASON={error}")
        return 1
    except Exception as error:
        print("LOCAL_AUDIT_EXECUTE_CRASH_RECOVERY=FAIL")
        print(
            f"LOCAL_AUDIT_EXECUTE_CRASH_REASON=UNEXPECTED_{type(error).__name__.upper()}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
