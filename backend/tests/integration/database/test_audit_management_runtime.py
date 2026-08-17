from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.minio_report_storage import MemoryReportStorageAdapter
from app.ai.output_validation import RiskExplanationOutput
from app.ai.report_draft import ReportDraftOutput, ReportDraftPromptInput
from app.ai.risk_explanation_prompts import RiskExplanationPromptInput
from app.audit.rule_catalog import publish_builtin_catalog
from app.core.config import Settings
from app.core.errors import AppError
from app.core.permissions import RoleCode
from app.db.migration import create_migration_engine
from app.db.session import create_session_factory
from app.models.audit import AuditReport, AuditRisk, AuditTaskExecution, RuleExecution
from app.models.auth import Organization, User
from app.models.corrections import UserCorrection
from app.models.financial import Contract, Invoice, InvoiceItem
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, AsyncJobStep, OutboxEvent
from app.repositories.job_runtime import JobRuntimeRepository
from app.schemas.audits import (
    AuditCancelRequest,
    AuditExecutionCreateRequest,
    AuditFinanceReviewRequest,
    AuditReviewDecisionRequest,
    AuditRiskReviewRequest,
    AuditTaskCreateRequest,
)
from app.schemas.invoices import InvoiceDuplicateCheckRequest, InvoiceDuplicateDecisionRequest
from app.services.ai_report_draft import AiReportDraftService, AuditedReportDraft
from app.services.ai_risk_explanation import (
    AiRiskExplanationService,
    AuditedRiskExplanation,
)
from app.services.audit_job_executor import AuditJobExecutor
from app.services.audit_management import AuditManagementService
from app.services.audited_llm import AuditedLlmAdoption
from app.services.auth import AuthenticatedActor
from app.services.invoice_management import InvoiceManagementService
from app.services.job_recovery import AuditJobRecovery
from app.services.report_job_executor import ReportJobExecutor
from app.services.report_management import ReportManagementService
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
    safe_database_error_signature,
)

pytestmark = pytest.mark.integration

ORGANIZATION_ID = UUID("a4000000-0000-4000-8000-000000000001")
FINANCE_REVIEWER_ID = UUID("a4000000-0000-4000-8000-000000000002")
AUDIT_REVIEWER_ID = UUID("a4000000-0000-4000-8000-000000000003")
CONTRACT_ID = UUID("a4000000-0000-4000-8000-000000000004")
INVOICE_ID = UUID("a4000000-0000-4000-8000-000000000005")
INVOICE_ITEM_ID = UUID("a4000000-0000-4000-8000-000000000006")
DUPLICATE_INVOICE_ID = UUID("a4000000-0000-4000-8000-000000000007")


class _RecordingAdoption:
    def __init__(self, adopted: list[str], label: str) -> None:
        self._adopted = adopted
        self._label = label

    def adopt_in_transaction(self, session: Session) -> None:
        assert session.in_transaction()
        self._adopted.append(self._label)

    def reject_in_transaction(self, session: Session, *, safe_error_code: str) -> None:
        assert session.in_transaction()
        self._adopted.append(f"rejected:{self._label}:{safe_error_code}")


class _StaticRiskExplanationService:
    def __init__(self, adopted: list[str]) -> None:
        self._adopted = adopted

    def explain(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
        risk_id: UUID,
        trace_id: UUID,
        prompt_input: RiskExplanationPromptInput,
    ) -> AuditedRiskExplanation:
        del organization_id, job_id, trace_id
        frozen = prompt_input.frozen_rule
        return AuditedRiskExplanation(
            risk_id=risk_id,
            output=RiskExplanationOutput(
                rule_code=frozen.rule_code,
                rule_version=frozen.rule_version,
                rule_status=frozen.rule_status,
                original_risk_level=frozen.original_risk_level,
                summary="AI 仅解释冻结规则命中事实。",
                reasoning_summary="实际值与预期值的差异触发了确定性规则。",
                business_impact=None,
                recommended_action="由授权审核人复核原始凭证。",
                citations=prompt_input.candidates,
                evidence_sufficient=bool(prompt_input.candidates),
                warnings=("AI 解释不替代规则结果或人工复核。",),
            ),
            adoption=cast(
                AuditedLlmAdoption,
                _RecordingAdoption(self._adopted, f"risk:{risk_id}"),
            ),
        )


class _StaticReportDraftService:
    def __init__(self, adopted: list[str]) -> None:
        self._adopted = adopted

    def draft(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
        report_id: UUID,
        trace_id: UUID,
        prompt_input: ReportDraftPromptInput,
    ) -> AuditedReportDraft:
        del organization_id, job_id, report_id, trace_id
        frozen = prompt_input.frozen
        return AuditedReportDraft(
            output=ReportDraftOutput(
                **frozen.model_dump(mode="python"),
                executive_summary="AI 仅对冻结审核事实生成文字草稿。",
                scope_summary="覆盖当前已完成的审核执行版本。",
                risk_summary=f"当前活动风险共 {frozen.active_risk_count} 项。",
                recommendations=("由授权审核人确认正式发布文字。",),
                warnings=("AI 草稿未审批，不替代规则结果和人工复核。",),
            ),
            adoption=cast(
                AuditedLlmAdoption,
                _RecordingAdoption(self._adopted, "report"),
            ),
        )


def _actor(user_id: UUID, role: RoleCode) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=user_id,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=(role,),
        permissions=(),
    )


def _seed_subjects(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        now = session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        session.add(
            Organization(
                id=ORGANIZATION_ID,
                name="Synthetic audit organization",
                unified_social_credit_code="SYNTH-AUDIT-USCC",
                tax_number="SYNTH-AUDIT-TAX",
                status="active",
            )
        )
        session.flush()
        session.add_all(
            [
                User(
                    id=FINANCE_REVIEWER_ID,
                    organization_id=ORGANIZATION_ID,
                    username="audit.finance.reviewer",
                    display_name="财务复核员",
                    password_hash="synthetic-password-hash",
                    status="active",
                    password_changed_at=now,
                ),
                User(
                    id=AUDIT_REVIEWER_ID,
                    organization_id=ORGANIZATION_ID,
                    username="audit.independent.reviewer",
                    display_name="独立审计复核员",
                    password_hash="synthetic-password-hash",
                    status="active",
                    password_changed_at=now,
                ),
            ]
        )
        session.flush()
        session.add(
            Contract(
                id=CONTRACT_ID,
                organization_id=ORGANIZATION_ID,
                contract_no="SYNTH-AUDIT-001",
                name="审计闭环测试合同",
                party_a_name="采购方",
                party_a_tax_no="SYNTH-AUDIT-TAX",
                party_b_name="销售方",
                party_b_tax_no="SYNTH-SELLER-TAX",
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
                confirmed_by=AUDIT_REVIEWER_ID,
                confirmed_at=now,
                critical_fact_hash="a" * 64,
                created_by=AUDIT_REVIEWER_ID,
                updated_by=AUDIT_REVIEWER_ID,
            )
        )
        invoice = Invoice(
            id=INVOICE_ID,
            organization_id=ORGANIZATION_ID,
            invoice_code="SYNTH-AUDIT-INV",
            invoice_number="000001",
            invoice_type="vat_special",
            is_red_invoice=False,
            invoice_date=date(2027, 1, 10),
            buyer_name="其他购买方",
            buyer_tax_no="MISMATCHED-BUYER-TAX",
            seller_name="销售方",
            seller_tax_no="SYNTH-SELLER-TAX",
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
            critical_fact_hash="b" * 64,
            created_by=FINANCE_REVIEWER_ID,
            updated_by=FINANCE_REVIEWER_ID,
        )
        session.add(invoice)
        session.flush()
        session.add(
            InvoiceItem(
                id=INVOICE_ITEM_ID,
                invoice_id=INVOICE_ID,
                line_no=1,
                item_name="审计服务费",
                specification=None,
                unit=None,
                quantity=Decimal("1.000000"),
                unit_price=Decimal("100.000000"),
                amount_excluding_tax=Decimal("100.00"),
                tax_rate=Decimal("0.060000"),
                tax_amount=Decimal("6.00"),
                total_amount=Decimal("106.00"),
                evidence_json={},
            )
        )
        session.flush()
        invoice.confirmation_status = "confirmed"
        invoice.status = "confirmed"
        invoice.confirmed_by = FINANCE_REVIEWER_ID
        invoice.confirmed_at = now
        invoice.row_version = 2
        session.flush()
        publish_builtin_catalog(
            session,
            application_release="audit-runtime-test-v1",
            change_reason="publish audit runtime integration catalog",
        )


def _publish_next_job(factory: sessionmaker[Session], job_id: UUID) -> UUID:
    with factory.begin() as session:
        repository = JobRuntimeRepository(session)
        claim = repository.claim_next_outbox()
        assert claim is not None
        assert claim.job.id == job_id
        assert repository.mark_outbox_published(claim)
        return claim.event_id


def _seed_duplicate_candidate(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        session.add(
            Invoice(
                id=DUPLICATE_INVOICE_ID,
                organization_id=ORGANIZATION_ID,
                invoice_code="SYNTH-AUDIT-INV",
                invoice_number="000001",
                invoice_type="vat_special",
                is_red_invoice=False,
                invoice_date=date(2027, 1, 10),
                buyer_name="其他购买方",
                buyer_tax_no="MISMATCHED-BUYER-TAX",
                seller_name="销售方",
                seller_tax_no="SYNTH-SELLER-TAX",
                supplier_id=None,
                amount_excluding_tax=Decimal("100.00"),
                tax_amount=Decimal("6.00"),
                total_amount=Decimal("106.00"),
                currency="CNY",
                confirmation_status="unconfirmed",
                duplicate_status="not_checked",
                status="draft",
                field_evidence_json={},
                confirmed_by=None,
                confirmed_at=None,
                critical_fact_hash="c" * 64,
                created_by=FINANCE_REVIEWER_ID,
                updated_by=FINANCE_REVIEWER_ID,
            )
        )


def _expire_active_job(engine: Engine, job_id: UUID) -> None:
    with engine.begin() as connection:
        for table_name in ("async_jobs", "async_job_steps"):
            connection.exec_driver_sql(f"ALTER TABLE {table_name} DISABLE TRIGGER USER")
        try:
            connection.execute(
                text(
                    "WITH clock AS MATERIALIZED (SELECT clock_timestamp() AS t), "
                    "expired AS (UPDATE async_jobs SET "
                    "started_at=clock.t-interval '120 seconds', "
                    "heartbeat_at=clock.t-interval '90 seconds', "
                    "lease_expires_at=clock.t-interval '30 seconds' FROM clock "
                    "WHERE id=:job_id RETURNING id, attempt_no) "
                    "UPDATE async_job_steps SET started_at=clock.t-interval '120 seconds' "
                    "FROM clock, expired WHERE job_id=expired.id "
                    "AND async_job_steps.attempt_no=expired.attempt_no "
                    "AND async_job_steps.status='running'"
                ),
                {"job_id": job_id},
            )
        finally:
            for table_name in reversed(("async_jobs", "async_job_steps")):
                connection.exec_driver_sql(f"ALTER TABLE {table_name} ENABLE TRIGGER USER")


def _clear_subjects(engine: Engine) -> None:
    table_names = (
        "operation_logs",
        "user_corrections",
        "risk_citations",
        "audit_reports",
        "audit_risks",
        "rule_executions",
        "async_job_steps",
        "outbox_events",
        "audit_task_snapshots",
        "audit_task_executions",
        "audit_task_items",
        "audit_tasks",
        "async_jobs",
        "idempotency_records",
        "audit_rules",
        "invoice_items",
        "contract_invoices",
        "invoices",
        "supplementary_agreement_changes",
        "supplementary_agreements",
        "contract_fields",
        "contracts",
        "users",
        "organizations",
    )
    with engine.begin() as connection:
        for table_name in table_names:
            connection.exec_driver_sql(f"ALTER TABLE {table_name} DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql("UPDATE audit_tasks SET current_execution_id = NULL")
            for table_name in table_names:
                connection.exec_driver_sql(f"DELETE FROM {table_name}")
        finally:
            for table_name in reversed(table_names):
                connection.exec_driver_sql(f"ALTER TABLE {table_name} ENABLE TRIGGER USER")


def test_audit_create_execute_review_complete_reaudit_and_cancel_close_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    factory = create_session_factory(engine)
    finance_actor = _actor(FINANCE_REVIEWER_ID, "finance_reviewer")
    audit_actor = _actor(AUDIT_REVIEWER_ID, "audit_reviewer")
    service = AuditManagementService(
        factory,
        cast(Settings, SimpleNamespace(app_version="audit-runtime-test-v1")),
    )
    adopted_ai_facts: list[str] = []
    executor = AuditJobExecutor(
        factory,
        cast(AiRiskExplanationService, _StaticRiskExplanationService(adopted_ai_facts)),
    )
    invoice_service = InvoiceManagementService(factory)
    report_storage = MemoryReportStorageAdapter()
    report_executor = ReportJobExecutor(
        factory,
        report_storage,
        cast(AiReportDraftService, _StaticReportDraftService(adopted_ai_facts)),
    )
    report_service = ReportManagementService(factory, report_storage)
    try:
        _seed_subjects(factory)
        with pytest.raises(DBAPIError) as red_invoice_error:
            with factory.begin() as session:
                invoice = session.get(Invoice, INVOICE_ID)
                assert invoice is not None
                invoice.is_red_invoice = True
                invoice.row_version += 1
                session.flush()
        assert safe_database_error_signature(red_invoice_error.value) == ("55000", None)
        create_payload = AuditTaskCreateRequest.model_validate(
            {
                "task_no": "AUDIT-RUNTIME-001",
                "name": "审核闭环集成验证",
                "description": "验证不可变快照、风险门禁和重审",
                "baseline_date": date(2027, 1, 15),
                "contract_id": CONTRACT_ID,
                "invoice_ids": [INVOICE_ID],
            }
        )
        created = service.create_task(
            audit_actor,
            create_payload,
            "audit-create-001",
            uuid4(),
        )
        replay = service.create_task(
            audit_actor,
            create_payload,
            "audit-create-001",
            uuid4(),
        )
        assert created.replayed is False
        assert replay.replayed is True
        assert replay.data == created.data
        assert created.data.execution.status == "queued"
        assert created.data.execution.job_id is not None
        assert created.data.execution.snapshot_sha256 is not None

        event_id = _publish_next_job(factory, created.data.execution.job_id)
        with factory.begin() as session:
            claim = JobRuntimeRepository(session).claim_job(
                job_id=created.data.execution.job_id,
                event_id=event_id,
                event_schema_version=1,
                worker_id="audit-runtime-lost-worker",
                start_step_seq=1,
            )
            assert claim is not None
        _expire_active_job(engine, created.data.execution.job_id)
        executed = AuditJobRecovery(factory, executor).recover_expired_once(
            worker_id="audit-runtime-recovery-worker"
        )
        if executed.outcome != "claimed_and_succeeded":
            with factory() as session:
                failed_execution = session.get(
                    AuditTaskExecution,
                    created.data.execution.id,
                )
                failed_job = session.get(AsyncJob, created.data.execution.job_id)
                assert failed_execution is not None and failed_job is not None
                pytest.fail(
                    "unexpected recovered audit outcome: "
                    f"{executed.outcome}; execution={failed_execution.status}/"
                    f"{failed_execution.failure_code}; job={failed_job.status}/"
                    f"{failed_job.error_code}",
                    pytrace=False,
                )

        detail = service.get_task(ORGANIZATION_ID, created.data.task.id)
        assert detail.execution.status == "pending_finance_review"
        assert len(detail.rules) == 15
        assert {rule.rule_code for rule in detail.rules} == {
            f"RULE-{number:03d}" for number in range(1, 16)
        }
        high_risks = tuple(risk for risk in detail.risks if risk.effective_level == "high")
        non_high_risks = tuple(risk for risk in detail.risks if risk.effective_level != "high")
        assert high_risks
        assert non_high_risks
        assert all(risk.ai_explanation_status == "succeeded" for risk in detail.risks)
        assert all(risk.ai_explanation is not None for risk in detail.risks)

        with pytest.raises(DBAPIError) as elevation_error:
            with factory.begin() as session:
                database_risk = session.get(AuditRisk, non_high_risks[0].id)
                assert database_risk is not None
                now = session.scalar(select(func.clock_timestamp()))
                assert isinstance(now, datetime)
                database_risk.effective_level = "high"
                database_risk.review_status = "adjusted"
                database_risk.review_reason = "数据库防线必须拒绝财务提升为高风险"
                database_risk.reviewed_by = FINANCE_REVIEWER_ID
                database_risk.reviewed_at = now
                database_risk.row_version += 1
                session.flush()
        assert safe_database_error_signature(elevation_error.value) == ("23514", None)

        with pytest.raises(AppError) as pending_error:
            service.finance_review(
                finance_actor,
                detail.execution.id,
                AuditFinanceReviewRequest(
                    row_version=detail.execution.row_version,
                    decision="submit",
                    reason="非高风险尚未复核",
                ),
                "audit-finance-too-early-001",
                uuid4(),
            )
        assert pending_error.value.code == "NON_HIGH_RISKS_PENDING"

        for index, risk in enumerate(non_high_risks, start=1):
            reviewed = service.review_risk(
                finance_actor,
                risk.id,
                AuditRiskReviewRequest(
                    row_version=risk.row_version,
                    decision="confirmed",
                    reason="财务核对确认风险事实",
                ),
                f"audit-risk-finance-{index:03d}",
                uuid4(),
                high_risk=False,
            )
            assert reviewed.data.risk.review_status == "confirmed"

        finance_reviewed = service.finance_review(
            finance_actor,
            detail.execution.id,
            AuditFinanceReviewRequest(
                row_version=detail.execution.row_version,
                decision="submit",
                reason="财务初审完成并提交高风险复核",
            ),
            "audit-finance-submit-001",
            uuid4(),
        )
        assert finance_reviewed.data.execution.status == "pending_audit_review"

        with pytest.raises(AppError) as separation_error:
            service.review_risk(
                finance_actor,
                high_risks[0].id,
                AuditRiskReviewRequest(
                    row_version=high_risks[0].row_version,
                    decision="confirmed",
                    reason="同一人员不得复核高风险",
                ),
                "audit-risk-separation-001",
                uuid4(),
                high_risk=True,
            )
        assert separation_error.value.code == "REVIEWER_SEPARATION_REQUIRED"

        for index, risk in enumerate(high_risks, start=1):
            reviewed = service.review_risk(
                audit_actor,
                risk.id,
                AuditRiskReviewRequest(
                    row_version=risk.row_version,
                    decision="confirmed",
                    reason="独立审计确认高风险事实",
                ),
                f"audit-risk-high-{index:03d}",
                uuid4(),
                high_risk=True,
            )
            assert reviewed.data.risk.review_status == "confirmed"

        completed = service.audit_review(
            audit_actor,
            detail.execution.id,
            AuditReviewDecisionRequest(
                row_version=finance_reviewed.data.execution.row_version,
                decision="complete",
                reason="全部风险复核完成",
            ),
            "audit-complete-001",
            uuid4(),
        )
        assert completed.data.execution.status == "completed"

        completed_detail = service.get_task(ORGANIZATION_ID, created.data.task.id)
        assert completed_detail.task.status == "completed"
        assert completed_detail.execution.status == "completed"

        with factory() as session:
            report = session.scalar(
                select(AuditReport).where(AuditReport.execution_id == completed_detail.execution.id)
            )
            assert report is not None
            assert report.status == "queued"
            assert report.job_id is not None
            report_id = report.id
            report_job_id = report.job_id
        report_event_id = _publish_next_job(factory, report_job_id)
        generated = report_executor.execute(
            job_id=report_job_id,
            event_id=report_event_id,
            event_schema_version=1,
            worker_id="report-runtime-worker",
        )
        if generated.outcome != "succeeded":
            with factory() as session:
                failed_report = session.get(AuditReport, report_id)
                failed_job = session.get(AsyncJob, report_job_id)
                assert failed_report is not None and failed_job is not None
                pytest.fail(
                    "unexpected report outcome: "
                    f"{generated.outcome}; report={failed_report.status}/"
                    f"{failed_report.failure_code}; job={failed_job.status}/"
                    f"{failed_job.error_code}",
                    pytrace=False,
                )
        report_data = report_service.get_report(ORGANIZATION_ID, report_id)
        assert report_data.status == "ready"
        assert report_data.pdf_sha256 is not None
        assert report_data.xlsx_sha256 is not None
        assert report_data.ai_draft_status == "succeeded"
        assert report_data.ai_draft_sha256 is not None
        assert report_data.ai_draft is not None
        assert len(adopted_ai_facts) == len(detail.risks) + 1
        assert all(not value.startswith("rejected:") for value in adopted_ai_facts)
        preview = report_service.preview_pdf(finance_actor, report_id, uuid4())
        export = report_service.download_xlsx(finance_actor, report_id, uuid4())
        assert preview.content.startswith(b"%PDF-")
        assert preview.is_outdated is False
        assert export.content.startswith(b"PK\x03\x04")
        assert export.is_outdated is False

        _seed_duplicate_candidate(factory)
        duplicate_checked = invoice_service.check_duplicate(
            finance_actor,
            INVOICE_ID,
            InvoiceDuplicateCheckRequest(
                row_version="2",
                reason="新增精确重复候选后重检",
            ),
            "audit-invoice-duplicate-check-001",
            uuid4(),
        )
        assert duplicate_checked.data.invoice.duplicate_status == "suspected"
        outdated_detail = service.get_task(ORGANIZATION_ID, created.data.task.id)
        assert outdated_detail.task.status == "open"
        assert outdated_detail.execution.status == "outdated"
        outdated_report = report_service.get_report(ORGANIZATION_ID, report_id)
        assert outdated_report.status == "outdated"
        assert outdated_report.is_outdated is True
        outdated_preview = report_service.preview_pdf(finance_actor, report_id, uuid4())
        assert outdated_preview.is_outdated is True
        with factory() as session:
            correction = session.scalar(
                select(UserCorrection)
                .where(UserCorrection.object_id == INVOICE_ID)
                .order_by(UserCorrection.created_at.desc(), UserCorrection.id.desc())
            )
            assert correction is not None
            assert correction.caused_outdated is True

        reaudit = service.create_execution(
            audit_actor,
            created.data.task.id,
            AuditExecutionCreateRequest(
                task_row_version=outdated_detail.task.row_version,
                baseline_date=date(2027, 1, 20),
                reason="关键事实复核后发起新版本",
            ),
            "audit-reaudit-001",
            uuid4(),
        )
        assert reaudit.data.execution.version_no == 2
        assert reaudit.data.execution.status == "queued"

        duplicate_decided = invoice_service.decide_duplicate(
            finance_actor,
            INVOICE_ID,
            InvoiceDuplicateDecisionRequest(
                row_version=duplicate_checked.data.invoice.row_version,
                candidate_id=DUPLICATE_INVOICE_ID,
                decision="confirmed_duplicate",
                reason="人工确认精确重复发票",
            ),
            "audit-invoice-duplicate-decision-001",
            uuid4(),
        )
        assert duplicate_decided.data.invoice.duplicate_status == "confirmed_duplicate"
        second_outdated = service.get_task(ORGANIZATION_ID, created.data.task.id)
        assert second_outdated.execution.version_no == 2
        assert second_outdated.execution.status == "outdated"

        final_execution = service.create_execution(
            audit_actor,
            created.data.task.id,
            AuditExecutionCreateRequest(
                task_row_version=second_outdated.task.row_version,
                baseline_date=date(2027, 1, 21),
                reason="重复处置后再次冻结新版本",
            ),
            "audit-reaudit-002",
            uuid4(),
        )
        assert final_execution.data.execution.version_no == 3
        cancelled = service.cancel_execution(
            audit_actor,
            final_execution.data.execution.id,
            AuditCancelRequest(
                row_version=final_execution.data.execution.row_version,
                reason="验证排队任务可审计取消",
            ),
            "audit-cancel-001",
            uuid4(),
        )
        assert cancelled.data.execution.status == "cancelled"

        with factory() as session:
            executions = tuple(
                session.scalars(
                    select(AuditTaskExecution).order_by(AuditTaskExecution.version_no)
                ).all()
            )
            assert [item.status for item in executions] == [
                "outdated",
                "outdated",
                "cancelled",
            ]
            assert session.scalar(select(func.count()).select_from(RuleExecution)) == 15
            risk_count = session.scalar(select(func.count()).select_from(AuditRisk))
            assert isinstance(risk_count, int) and risk_count >= 2
            assert session.scalar(select(func.count()).select_from(UserCorrection)) == (
                risk_count + 2
            )
            jobs = tuple(session.scalars(select(AsyncJob).order_by(AsyncJob.created_at)).all())
            assert [job.status for job in jobs] == [
                "succeeded",
                "succeeded",
                "cancelled",
                "cancelled",
            ]
            assert jobs[0].attempt_no == 2
            steps = tuple(
                session.scalars(
                    select(AsyncJobStep)
                    .where(AsyncJobStep.job_id == jobs[0].id)
                    .order_by(AsyncJobStep.attempt_no)
                ).all()
            )
            assert [(step.attempt_no, step.status, step.error_code) for step in steps] == [
                (1, "failed", "LEASE_EXPIRED"),
                (2, "succeeded", None),
            ]
            assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 4
            reports = tuple(session.scalars(select(AuditReport)).all())
            assert len(reports) == 1
            assert reports[0].status == "outdated"
            assert reports[0].pdf_object_key is not None
            assert reports[0].xlsx_object_key is not None
            actions = tuple(
                session.scalars(
                    select(OperationLog.action_code).order_by(
                        OperationLog.created_at,
                        OperationLog.id,
                    )
                ).all()
            )
            assert actions[0:2] == (
                "audits.task_created",
                "audits.execution_evaluated",
            )
            assert actions[-2:] == (
                "audits.execution_reaudit_queued",
                "audits.execution_cancelled",
            )
    finally:
        _clear_subjects(engine)
        engine.dispose()
