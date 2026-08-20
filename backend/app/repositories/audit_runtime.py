"""审核任务、执行、快照、规则结果和复核的 PostgreSQL 访问边界。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.rule_catalog import RULE_CATALOG_CODES
from app.models.audit import (
    AuditReport,
    AuditRisk,
    AuditRule,
    AuditTask,
    AuditTaskExecution,
    AuditTaskItem,
    AuditTaskSnapshot,
    RiskCitation,
    RuleExecution,
)
from app.models.auth import Organization
from app.models.financial import (
    Contract,
    ContractField,
    Invoice,
    InvoiceItem,
    SupplementaryAgreement,
    SupplementaryAgreementChange,
)
from app.models.reliability import AsyncJob
from app.repositories.user_write import IdempotencyClaim, UserWriteRepository


@dataclass(frozen=True, slots=True)
class AuditRuleVersion:
    id: UUID
    rule_code: str
    version: int
    name: str
    default_risk_level: str
    explanation_template: str
    requires_policy_citation: bool
    application_release: str
    catalog_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class LockedAuditCluster:
    task: AuditTask
    execution: AuditTaskExecution
    snapshot: AuditTaskSnapshot | None
    rules: tuple[RuleExecution, ...]
    risks: tuple[AuditRisk, ...]
    citations: tuple[RiskCitation, ...]
    reports: tuple[AuditReport, ...]


class AuditRuntimeRepository:
    """调用方持有事务；本仓储不执行外部 I/O。"""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._idempotency = UserWriteRepository(session)

    def database_now(self) -> datetime:
        return cast(datetime, self._session.scalar(select(func.clock_timestamp())))

    def acquire_api_locks(
        self,
        organization_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> None:
        organization_identity = f"finaudit:audit:{organization_id}"
        request_identity = f"{organization_id}:{actor_id}:{idempotency_key}"
        self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(organization_identity, 20)))
        ).one()
        self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(request_identity, 21)))
        ).one()

    def lock_active_organization(self, organization_id: UUID) -> Organization | None:
        return self._session.execute(
            select(Organization)
            .where(
                Organization.id == organization_id,
                Organization.status == "active",
                Organization.deleted_at.is_(None),
            )
            .with_for_update(of=Organization)
        ).scalar_one_or_none()

    def claim_idempotency(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
        request_method: str,
        request_path: str,
        request_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> IdempotencyClaim:
        return self._idempotency.claim_idempotency(
            organization_id=organization_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request_method=request_method,
            request_path=request_path,
            request_hash=request_hash,
            now=now,
            expires_at=expires_at,
        )

    @staticmethod
    def complete_idempotency(
        claim: IdempotencyClaim,
        *,
        response_status: int,
        response_body: dict[str, object],
        resource_type: str,
        resource_id: UUID,
    ) -> None:
        UserWriteRepository.complete_idempotency(
            claim,
            response_status=response_status,
            response_body=response_body,
            resource_type=resource_type,
            resource_id=resource_id,
        )

    def get_task(self, organization_id: UUID, task_id: UUID) -> AuditTask | None:
        return self._session.execute(
            select(AuditTask).where(
                AuditTask.id == task_id,
                AuditTask.organization_id == organization_id,
                AuditTask.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

    def lock_task(self, organization_id: UUID, task_id: UUID) -> AuditTask | None:
        return self._session.execute(
            select(AuditTask)
            .where(
                AuditTask.id == task_id,
                AuditTask.organization_id == organization_id,
                AuditTask.deleted_at.is_(None),
            )
            .with_for_update(of=AuditTask)
        ).scalar_one_or_none()

    def list_tasks(
        self,
        organization_id: UUID,
        *,
        page_size: int,
        cursor_id: UUID | None,
    ) -> tuple[tuple[AuditTask, ...], bool]:
        statement = select(AuditTask).where(
            AuditTask.organization_id == organization_id,
            AuditTask.deleted_at.is_(None),
        )
        if cursor_id is not None:
            statement = statement.where(AuditTask.id < cursor_id)
        rows = self._session.execute(
            statement.order_by(AuditTask.id.desc()).limit(page_size + 1)
        ).scalars()
        values = tuple(rows)
        return values[:page_size], len(values) > page_size

    def task_items(self, task_id: UUID) -> tuple[AuditTaskItem, ...]:
        return tuple(
            self._session.execute(
                select(AuditTaskItem)
                .where(AuditTaskItem.audit_task_id == task_id)
                .order_by(AuditTaskItem.item_type, AuditTaskItem.id)
            ).scalars()
        )

    def next_execution_version(self, task_id: UUID) -> int:
        current = self._session.scalar(
            select(func.max(AuditTaskExecution.version_no)).where(
                AuditTaskExecution.audit_task_id == task_id
            )
        )
        return 1 if current is None else int(current) + 1

    def current_rule_versions(self) -> tuple[AuditRuleVersion, ...]:
        version = self._session.scalar(select(func.max(AuditRule.version)))
        if version is None:
            return ()
        rows = tuple(
            self._session.execute(
                select(AuditRule)
                .where(AuditRule.version == version, AuditRule.is_enabled.is_(True))
                .order_by(AuditRule.rule_code)
                .with_for_update(read=True, of=AuditRule)
            ).scalars()
        )
        if tuple(row.rule_code for row in rows) != RULE_CATALOG_CODES:
            return ()
        releases = {row.application_release for row in rows}
        manifests = {row.catalog_manifest_sha256 for row in rows}
        if len(releases) != 1 or len(manifests) != 1:
            return ()
        return tuple(
            AuditRuleVersion(
                id=row.id,
                rule_code=row.rule_code,
                version=row.version,
                name=row.name,
                default_risk_level=row.default_risk_level,
                explanation_template=row.explanation_template,
                requires_policy_citation=row.requires_policy_citation,
                application_release=row.application_release,
                catalog_manifest_sha256=row.catalog_manifest_sha256,
            )
            for row in rows
        )

    def rule_versions_by_ids(
        self, rule_version_ids: tuple[UUID, ...]
    ) -> tuple[AuditRuleVersion, ...]:
        rows = tuple(
            self._session.execute(
                select(AuditRule)
                .where(AuditRule.id.in_(rule_version_ids))
                .order_by(AuditRule.rule_code)
                .with_for_update(read=True, of=AuditRule)
            ).scalars()
        )
        if (
            len(rows) != 15
            or {row.id for row in rows} != set(rule_version_ids)
            or tuple(row.rule_code for row in rows) != RULE_CATALOG_CODES
        ):
            return ()
        return tuple(
            AuditRuleVersion(
                id=row.id,
                rule_code=row.rule_code,
                version=row.version,
                name=row.name,
                default_risk_level=row.default_risk_level,
                explanation_template=row.explanation_template,
                requires_policy_citation=row.requires_policy_citation,
                application_release=row.application_release,
                catalog_manifest_sha256=row.catalog_manifest_sha256,
            )
            for row in rows
        )

    def lock_financial_inputs(
        self,
        organization_id: UUID,
        *,
        contract_id: UUID | None,
        invoice_ids: tuple[UUID, ...],
    ) -> bool:
        if contract_id is not None:
            contract = self._session.execute(
                select(Contract)
                .where(
                    Contract.id == contract_id,
                    Contract.organization_id == organization_id,
                    Contract.deleted_at.is_(None),
                )
                .with_for_update(read=True, of=Contract)
            ).scalar_one_or_none()
            if contract is None:
                return False
            tuple(
                self._session.execute(
                    select(ContractField)
                    .where(ContractField.contract_id == contract_id)
                    .order_by(ContractField.field_code)
                    .with_for_update(read=True, of=ContractField)
                ).scalars()
            )
            agreements = tuple(
                self._session.execute(
                    select(SupplementaryAgreement)
                    .where(
                        SupplementaryAgreement.organization_id == organization_id,
                        SupplementaryAgreement.contract_id == contract_id,
                        SupplementaryAgreement.deleted_at.is_(None),
                    )
                    .order_by(SupplementaryAgreement.id)
                    .with_for_update(read=True, of=SupplementaryAgreement)
                ).scalars()
            )
            agreement_ids = tuple(item.id for item in agreements)
            if agreement_ids:
                tuple(
                    self._session.execute(
                        select(SupplementaryAgreementChange)
                        .where(
                            SupplementaryAgreementChange.supplementary_agreement_id.in_(
                                agreement_ids
                            )
                        )
                        .order_by(
                            SupplementaryAgreementChange.supplementary_agreement_id,
                            SupplementaryAgreementChange.field_code,
                        )
                        .with_for_update(read=True, of=SupplementaryAgreementChange)
                    ).scalars()
                )
        invoices = tuple(
            self._session.execute(
                select(Invoice)
                .where(
                    Invoice.organization_id == organization_id,
                    Invoice.id.in_(invoice_ids),
                    Invoice.deleted_at.is_(None),
                )
                .order_by(Invoice.id)
                .with_for_update(read=True, of=Invoice)
            ).scalars()
        )
        if tuple(item.id for item in invoices) != invoice_ids:
            return False
        tuple(
            self._session.execute(
                select(InvoiceItem)
                .where(InvoiceItem.invoice_id.in_(invoice_ids))
                .order_by(InvoiceItem.invoice_id, InvoiceItem.line_no, InvoiceItem.id)
                .with_for_update(read=True, of=InvoiceItem)
            ).scalars()
        )
        return True

    def has_exact_duplicate(
        self,
        *,
        organization_id: UUID,
        invoice_id: UUID,
        invoice_code: str | None,
        invoice_number: str | None,
        seller_tax_no: str | None,
    ) -> bool | None:
        if not invoice_code or not invoice_number or not seller_tax_no:
            return None
        return bool(
            self._session.scalar(
                select(
                    select(Invoice.id)
                    .where(
                        Invoice.organization_id == organization_id,
                        Invoice.id != invoice_id,
                        Invoice.deleted_at.is_(None),
                        Invoice.status != "voided",
                        Invoice.invoice_code == invoice_code,
                        Invoice.invoice_number == invoice_number,
                        Invoice.seller_tax_no == seller_tax_no,
                    )
                    .exists()
                )
            )
        )

    def get_execution(self, organization_id: UUID, execution_id: UUID) -> AuditTaskExecution | None:
        return self._session.execute(
            select(AuditTaskExecution).where(
                AuditTaskExecution.id == execution_id,
                AuditTaskExecution.organization_id == organization_id,
            )
        ).scalar_one_or_none()

    def execution_snapshot(self, execution_id: UUID) -> AuditTaskSnapshot | None:
        return self._session.execute(
            select(AuditTaskSnapshot).where(AuditTaskSnapshot.execution_id == execution_id)
        ).scalar_one_or_none()

    def execution_rules(self, execution_id: UUID) -> tuple[RuleExecution, ...]:
        return tuple(
            self._session.execute(
                select(RuleExecution)
                .where(RuleExecution.execution_id == execution_id)
                .order_by(RuleExecution.rule_code)
            ).scalars()
        )

    def execution_risks(self, execution_id: UUID) -> tuple[AuditRisk, ...]:
        return tuple(
            self._session.execute(
                select(AuditRisk)
                .where(AuditRisk.execution_id == execution_id)
                .order_by(AuditRisk.rule_code)
            ).scalars()
        )

    def job_for_execution(self, execution_id: UUID, *, lock: bool = True) -> AsyncJob | None:
        statement = select(AsyncJob).where(
            AsyncJob.resource_type == "audit_task_execution",
            AsyncJob.resource_id == execution_id,
        )
        if lock:
            statement = statement.with_for_update(of=AsyncJob)
        return self._session.execute(statement).scalar_one_or_none()

    def outdate_current_executions_for_invoice(
        self,
        organization_id: UUID,
        invoice_id: UUID,
        *,
        actor_id: UUID,
        now: datetime,
    ) -> tuple[UUID, ...]:
        """使引用发票当前事实的可推进执行过期，并阻断其活动 Job。"""

        task_ids = tuple(
            self._session.scalars(
                select(AuditTaskItem.audit_task_id)
                .where(
                    AuditTaskItem.organization_id == organization_id,
                    AuditTaskItem.invoice_id == invoice_id,
                )
                .order_by(AuditTaskItem.audit_task_id)
            ).all()
        )
        return self._outdate_current_executions(
            organization_id,
            task_ids,
            actor_id=actor_id,
            now=now,
            effective_from=None,
        )

    def outdate_current_executions_for_contract(
        self,
        organization_id: UUID,
        contract_id: UUID,
        *,
        actor_id: UUID,
        now: datetime,
        effective_from: date | None = None,
    ) -> tuple[UUID, ...]:
        """使引用合同有效投影的可推进执行过期。"""

        task_ids = tuple(
            self._session.scalars(
                select(AuditTaskItem.audit_task_id)
                .where(
                    AuditTaskItem.organization_id == organization_id,
                    AuditTaskItem.contract_id == contract_id,
                )
                .order_by(AuditTaskItem.audit_task_id)
            ).all()
        )
        return self._outdate_current_executions(
            organization_id,
            task_ids,
            actor_id=actor_id,
            now=now,
            effective_from=effective_from,
        )

    def _outdate_current_executions(
        self,
        organization_id: UUID,
        task_ids: tuple[UUID, ...],
        *,
        actor_id: UUID,
        now: datetime,
        effective_from: date | None,
    ) -> tuple[UUID, ...]:
        if not task_ids:
            return ()
        tasks = tuple(
            self._session.scalars(
                select(AuditTask)
                .where(
                    AuditTask.id.in_(task_ids),
                    AuditTask.organization_id == organization_id,
                    AuditTask.current_execution_id.is_not(None),
                    AuditTask.deleted_at.is_(None),
                )
                .order_by(AuditTask.id)
                .with_for_update(of=AuditTask)
            ).all()
        )
        execution_ids = tuple(
            task.current_execution_id for task in tasks if task.current_execution_id is not None
        )
        if not execution_ids:
            return ()
        executions = tuple(
            self._session.scalars(
                select(AuditTaskExecution)
                .where(
                    AuditTaskExecution.id.in_(execution_ids),
                    AuditTaskExecution.organization_id == organization_id,
                )
                .order_by(AuditTaskExecution.audit_task_id)
                .with_for_update(of=AuditTaskExecution)
            ).all()
        )
        execution_by_id = {execution.id: execution for execution in executions}
        outdatable = {
            "validating",
            "queued",
            "running",
            "pending_finance_review",
            "pending_audit_review",
            "failed",
            "completed",
        }
        outdated_ids: list[UUID] = []
        for task in tasks:
            if task.current_execution_id is None:
                continue
            execution = execution_by_id.get(task.current_execution_id)
            if (
                execution is None
                or execution.status not in outdatable
                or (effective_from is not None and execution.baseline_date < effective_from)
            ):
                continue
            cluster = self.lock_cluster(organization_id, execution.id)
            if cluster is None:
                continue
            reports_by_id = {report.id: report for report in cluster.reports}
            jobs = tuple(
                self._session.scalars(
                    select(AsyncJob)
                    .where(
                        AsyncJob.organization_id == organization_id,
                        or_(
                            (
                                (AsyncJob.resource_type == "audit_task_execution")
                                & (AsyncJob.resource_id == execution.id)
                            ),
                            (
                                (AsyncJob.resource_type == "audit_report")
                                & (AsyncJob.resource_id.in_(tuple(reports_by_id)))
                            ),
                        ),
                    )
                    .order_by(AsyncJob.id)
                    .with_for_update(of=AsyncJob)
                ).all()
            )
            if task.status == "completed":
                task.status = "open"
                task.updated_by = actor_id
                task.updated_at = now
                task.row_version += 1
                self._session.flush((task,))
            for report in cluster.reports:
                if report.status in {"queued", "generating"}:
                    report.status = "failed"
                    report.failure_code = "AUDIT_EXECUTION_OUTDATED"
                    report.row_version += 1
            for job in jobs:
                if job.status == "queued":
                    job.status = "cancelled"
                    job.finished_at = now
                    job.error_code = "JOB_CANCELLED"
                    job.error_message = None
                    job.row_version += 1
                elif job.status == "running":
                    job.status = "cancel_requested"
                    job.row_version += 1
            execution.status = "outdated"
            execution.outdated_at = now
            execution.finished_at = execution.finished_at or now
            execution.retryable = False
            execution.row_version += 1
            self._session.flush((*cluster.reports, *jobs, execution))
            outdated_ids.append(execution.id)
        return tuple(outdated_ids)

    def lock_cluster(
        self,
        organization_id: UUID,
        execution_id: UUID,
    ) -> LockedAuditCluster | None:
        identity = self._session.execute(
            select(AuditTaskExecution.audit_task_id).where(
                AuditTaskExecution.id == execution_id,
                AuditTaskExecution.organization_id == organization_id,
            )
        ).scalar_one_or_none()
        if identity is None:
            return None
        task = self._session.execute(
            select(AuditTask)
            .where(
                AuditTask.id == identity,
                AuditTask.organization_id == organization_id,
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
                AuditTaskExecution.organization_id == organization_id,
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
        rules = tuple(
            self._session.execute(
                select(RuleExecution)
                .where(RuleExecution.execution_id == execution.id)
                .order_by(RuleExecution.rule_code)
                .with_for_update(of=RuleExecution)
            ).scalars()
        )
        risks = tuple(
            self._session.execute(
                select(AuditRisk)
                .where(AuditRisk.execution_id == execution.id)
                .order_by(AuditRisk.rule_code)
                .with_for_update(of=AuditRisk)
            ).scalars()
        )
        citations = tuple(
            self._session.execute(
                select(RiskCitation)
                .where(RiskCitation.execution_id == execution.id)
                .order_by(RiskCitation.risk_id, RiskCitation.chunk_id)
                .with_for_update(of=RiskCitation)
            ).scalars()
        )
        reports = tuple(
            self._session.execute(
                select(AuditReport)
                .where(AuditReport.execution_id == execution.id)
                .order_by(AuditReport.report_version)
                .with_for_update(of=AuditReport)
            ).scalars()
        )
        return LockedAuditCluster(task, execution, snapshot, rules, risks, citations, reports)

    def add(self, value: object) -> None:
        self._session.add(value)

    def add_all(self, values: tuple[object, ...]) -> None:
        self._session.add_all(values)

    def flush(self) -> None:
        self._session.flush()


__all__ = [
    "AuditRuleVersion",
    "AuditRuntimeRepository",
    "LockedAuditCluster",
]
