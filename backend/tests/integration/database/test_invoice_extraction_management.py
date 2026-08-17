from __future__ import annotations

import io
import zipfile
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.malware_scanner import ScanResult
from app.adapters.ocr import NotConfiguredOcrEngine
from app.models.corrections import UserCorrection
from app.models.documents import FilePrimaryBusinessObject
from app.models.financial import Invoice, InvoiceItem
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, AsyncJobStep, IdempotencyRecord
from app.repositories.job_runtime import JobRuntimeRepository
from app.schemas.files import FileUploadIntent, IntendedBusinessType
from app.schemas.invoices import (
    InvoiceDecisionRequest,
    InvoiceDuplicateCheckRequest,
    InvoiceDuplicateDecisionRequest,
    InvoiceFactsReplaceRequest,
    InvoiceFactsWriteData,
    InvoiceItemWriteData,
)
from app.services.auth import AuthenticatedActor
from app.services.document_parser import DocumentParser
from app.services.file_intake import FileIntakeService
from app.services.file_job_executor import FileJobExecutor
from app.services.invoice_extraction_executor import InvoiceExtractionExecutor
from app.services.invoice_management import InvoiceManagementService
from app.services.job_recovery import FileJobRecovery
from tests.integration.database.test_file_intake_service import (
    ACTOR_ID,
    ORGANIZATION_ID,
    MemoryQuarantineStorage,
    _clear_subjects,
    _setup,
)
from tests.integration.database.test_file_job_executor import (
    _clear_document_subjects,
    _dispatch_pending,
    _RuntimeStorage,
)

pytestmark = pytest.mark.integration

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_DUPLICATE_ID = UUID("6e000000-0000-4000-8000-0000000000d0")


class _CleanDocumentScanner:
    def scan(self, payload: bytes) -> ScanResult:
        assert payload.startswith(b"PK\x03\x04")
        return ScanResult(
            outcome="clean",
            scanner_invoked=True,
            adapter_code="synthetic-clean-v1",
            scanner_version="synthetic-1",
            definition_version="definitions-1",
        )


def _invoice_actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=("finance_reviewer",),
        permissions=("files.read", "files.upload", "financial.read", "invoices.manage"),
    )


def _invoice_docx() -> bytes:
    lines = (
        "发票代码: SYNTHINV001",
        "发票号码: 000001",
        "发票类型: 增值税专用发票",
        "开票日期: 2026-05-01",
        "购买方名称: 测试采购方",
        "购买方税号: 91310000BUYER0001X",
        "销售方名称: 测试供应商",
        "销售方税号: 91310000SELLER001X",
        "不含税金额: 100.00",
        "税额: 13.00",
        "价税合计: 113.00",
        "币种: CNY",
        "明细: 咨询服务",
    )
    paragraphs = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in lines)
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>'
        f"{paragraphs}<w:sectPr/></w:body></w:document>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def _file_executor(
    factory: sessionmaker[Session],
    storage: _RuntimeStorage,
) -> FileJobExecutor:
    return FileJobExecutor(
        factory,
        storage,
        _CleanDocumentScanner(),
        DocumentParser(ocr_engine=NotConfiguredOcrEngine(), pdf_renderer=None),
        max_file_bytes=1024 * 1024,
    )


def _upload_and_parse(
    factory: sessionmaker[Session],
    intake: FileIntakeService,
    quarantine: MemoryQuarantineStorage,
) -> tuple[UUID, UUID, FileJobExecutor]:
    uploaded = intake.upload(
        _invoice_actor(),
        FileUploadIntent(intended_business_type=IntendedBusinessType.INVOICE),
        file_name="invoice.docx",
        declared_mime=_DOCX_MIME,
        stream=io.BytesIO(_invoice_docx()),
        idempotency_key="invoice-upload-e2e-001",
        trace_id=uuid4(),
    )
    file_event = _dispatch_pending(factory, uploaded.data.job_id)
    runtime_storage = _RuntimeStorage(quarantine)
    file_executor = _file_executor(factory, runtime_storage)
    parsed = file_executor.execute(
        job_id=uploaded.data.job_id,
        event_id=file_event.event_id,
        event_schema_version=file_event.event_version,
        worker_id="invoice-file-worker",
    )
    assert parsed.outcome == "succeeded"
    with factory() as session:
        extraction_job = session.scalars(
            select(AsyncJob).where(
                AsyncJob.resource_id == uploaded.data.file_id,
                AsyncJob.job_type == "invoice_extract",
            )
        ).one()
        assert extraction_job.input_json["file_id"] == str(uploaded.data.file_id)
        assert extraction_job.input_json["parse_version_id"]
        return uploaded.data.file_id, extraction_job.id, file_executor


def _seed_exact_duplicate(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        now = session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        session.add(
            Invoice(
                id=_DUPLICATE_ID,
                organization_id=ORGANIZATION_ID,
                invoice_code="SYNTHINV001",
                invoice_number="000001",
                invoice_type="vat_special",
                invoice_date=None,
                buyer_name="其他采购方",
                buyer_tax_no="91310000OTHER0001X",
                seller_name="测试供应商",
                seller_tax_no="91310000SELLER001X",
                supplier_id=None,
                amount_excluding_tax=Decimal("100.00"),
                tax_amount=Decimal("13.00"),
                total_amount=Decimal("113.00"),
                currency="CNY",
                confirmation_status="confirmed",
                duplicate_status="unique",
                status="confirmed",
                field_evidence_json={},
                confirmed_by=ACTOR_ID,
                confirmed_at=now,
                critical_fact_hash="d" * 64,
                row_version=1,
                created_by=ACTOR_ID,
                updated_by=ACTOR_ID,
            )
        )


def _clear_invoice_subjects(engine: Engine, file_id: UUID) -> None:
    tables = (
        "user_corrections",
        "file_primary_business_objects",
        "invoice_items",
        "invoices",
    )
    with engine.begin() as connection:
        for table_name in tables:
            connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
        try:
            connection.execute(
                text("DELETE FROM user_corrections WHERE organization_id=:organization_id"),
                {"organization_id": ORGANIZATION_ID},
            )
            connection.execute(
                text("DELETE FROM file_primary_business_objects WHERE file_id=:file_id"),
                {"file_id": file_id},
            )
            connection.execute(
                text(
                    "DELETE FROM invoice_items WHERE invoice_id IN "
                    "(SELECT id FROM invoices WHERE organization_id=:organization_id)"
                ),
                {"organization_id": ORGANIZATION_ID},
            )
            connection.execute(
                text("DELETE FROM invoices WHERE organization_id=:organization_id"),
                {"organization_id": ORGANIZATION_ID},
            )
        finally:
            for table_name in reversed(tables):
                connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))


def test_upload_parse_extract_correct_confirm_and_duplicate_decision_close_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    file_id: UUID | None = None
    try:
        file_id, extraction_job_id, _ = _upload_and_parse(factory, intake, quarantine)
        event = _dispatch_pending(factory, extraction_job_id)
        executor = InvoiceExtractionExecutor(factory)
        extracted = executor.execute(
            job_id=extraction_job_id,
            event_id=event.event_id,
            event_schema_version=event.event_version,
            worker_id="invoice-extraction-worker",
        )
        duplicate_delivery = executor.execute(
            job_id=extraction_job_id,
            event_id=event.event_id,
            event_schema_version=event.event_version,
            worker_id="invoice-extraction-worker-duplicate",
        )
        assert extracted.outcome == "succeeded"
        assert duplicate_delivery.outcome == "duplicate_or_stale"

        with factory() as session:
            binding = session.scalars(
                select(FilePrimaryBusinessObject).where(
                    FilePrimaryBusinessObject.file_id == file_id
                )
            ).one()
            assert binding.business_type == "invoice"
            assert binding.invoice_id is not None
            invoice_id = binding.invoice_id
            extracted_invoice = session.get(Invoice, invoice_id)
            assert extracted_invoice is not None
            assert extracted_invoice.invoice_code == "SYNTHINV001"
            assert extracted_invoice.invoice_number == "000001"
            assert extracted_invoice.total_amount == Decimal("113.00")
            assert extracted_invoice.confirmation_status == "unconfirmed"
            assert extracted_invoice.duplicate_status == "unique"
            assert extracted_invoice.status == "draft"
            assert extracted_invoice.row_version == 1
            extracted_items = tuple(
                session.scalars(
                    select(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id)
                ).all()
            )
            assert [(item.line_no, item.item_name) for item in extracted_items] == [(1, "咨询服务")]

        actor = _invoice_actor()
        service = InvoiceManagementService(factory)
        evidence = service.get_evidence(ORGANIZATION_ID, invoice_id)
        assert evidence.row_version == "1"
        assert {item.field_code for item in evidence.field_evidence} >= {
            "invoice_code",
            "invoice_number",
            "invoice_date",
            "buyer_tax_no",
            "seller_tax_no",
            "amount_excluding_tax",
            "tax_amount",
            "total_amount",
        }
        assert tuple(evidence.item_evidence) == ("1",)

        replacement = InvoiceFactsReplaceRequest(
            row_version="1",
            reason="人工复核并补充明细字段",
            facts=InvoiceFactsWriteData(
                invoice_code="SYNTHINV001",
                invoice_number="000001",
                invoice_type="增值税专用发票",
                invoice_date=datetime(2026, 5, 1).date(),
                buyer_name="测试采购方",
                buyer_tax_no="91310000BUYER0001X",
                seller_name="测试供应商",
                seller_tax_no="91310000SELLER001X",
                amount_excluding_tax="100.00",
                tax_amount="13.00",
                total_amount="113.00",
                currency="CNY",
            ),
            field_evidence=evidence.field_evidence,
            items=(
                InvoiceItemWriteData(
                    line_no=1,
                    item_name="咨询服务",
                    specification="人工复核",
                    amount_excluding_tax="100.00",
                    tax_amount="13.00",
                    total_amount="113.00",
                    evidence=evidence.item_evidence["1"],
                ),
            ),
        )
        corrected = service.replace_facts(
            actor,
            invoice_id,
            replacement,
            "invoice-facts-e2e-001",
            uuid4(),
        )
        replay = service.replace_facts(
            actor,
            invoice_id,
            replacement,
            "invoice-facts-e2e-001",
            uuid4(),
        )
        assert corrected.replayed is False
        assert replay.replayed is True
        assert replay.data == corrected.data
        assert corrected.data.invoice.row_version == "2"
        assert corrected.data.invoice.items[0].specification == "人工复核"

        confirmed = service.decide(
            actor,
            invoice_id,
            InvoiceDecisionRequest(
                row_version="2",
                decision="confirmed",
                reason="字段、金额与来源证据复核通过",
            ),
            "invoice-confirm-e2e-001",
            uuid4(),
        )
        assert confirmed.data.invoice.confirmation_status == "confirmed"
        assert confirmed.data.invoice.status == "confirmed"
        assert confirmed.data.invoice.row_version == "3"

        _seed_exact_duplicate(factory)
        checked = service.check_duplicate(
            actor,
            invoice_id,
            InvoiceDuplicateCheckRequest(
                row_version="3",
                reason="确认后重新执行精确重复检测",
            ),
            "invoice-duplicate-check-e2e-001",
            uuid4(),
        )
        assert checked.data.invoice.duplicate_status == "suspected"
        assert checked.data.invoice.row_version == "4"
        assert checked.data.duplicate_candidate_id == _DUPLICATE_ID

        decided = service.decide_duplicate(
            actor,
            invoice_id,
            InvoiceDuplicateDecisionRequest(
                row_version="4",
                candidate_id=_DUPLICATE_ID,
                decision="confirmed_duplicate",
                reason="财务复核确认与候选发票重复",
            ),
            "invoice-duplicate-decision-e2e-001",
            uuid4(),
        )
        assert decided.data.invoice.duplicate_status == "confirmed_duplicate"
        assert decided.data.invoice.confirmation_status == "confirmed"
        assert decided.data.invoice.row_version == "5"

        history = service.get_history(ORGANIZATION_ID, invoice_id)
        assert [item.field_path for item in history.items] == [
            "facts",
            "decision",
            "duplicate_status",
            "duplicate_status",
        ]
        assert service.get_evidence(ORGANIZATION_ID, invoice_id).row_version == "5"

        with factory() as session:
            job = session.get(AsyncJob, extraction_job_id)
            assert job is not None
            assert job.status == "succeeded"
            assert job.stage == "extract"
            assert job.attempt_no == 1
            assert session.scalar(select(func.count()).select_from(UserCorrection)) == 4
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecord)
                    .where(IdempotencyRecord.organization_id == ORGANIZATION_ID)
                )
                == 5
            )
            actions = tuple(
                session.scalars(
                    select(OperationLog.action_code)
                    .where(OperationLog.organization_id == ORGANIZATION_ID)
                    .order_by(OperationLog.created_at, OperationLog.id)
                ).all()
            )
            assert actions == (
                "files.uploaded",
                "invoices.extraction_created",
                "invoices.facts_replaced",
                "invoices.confirmed",
                "invoices.duplicate_checked",
                "invoices.duplicate_confirmed",
            )
    finally:
        if file_id is not None:
            _clear_invoice_subjects(engine, file_id)
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()


def test_expired_invoice_extraction_lease_is_fenced_and_recovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    file_id: UUID | None = None
    try:
        file_id, extraction_job_id, file_executor = _upload_and_parse(
            factory,
            intake,
            quarantine,
        )
        event = _dispatch_pending(factory, extraction_job_id)
        with factory.begin() as session:
            claim = JobRuntimeRepository(session).claim_job(
                job_id=extraction_job_id,
                event_id=event.event_id,
                event_schema_version=event.event_version,
                worker_id="crashed-invoice-worker",
                start_step_seq=1,
            )
            assert claim is not None

        with engine.begin() as connection:
            for table_name in ("async_jobs", "async_job_steps"):
                connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
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
                    {"job_id": extraction_job_id},
                )
            finally:
                for table_name in reversed(("async_jobs", "async_job_steps")):
                    connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))

        invoice_executor = InvoiceExtractionExecutor(factory)
        recovery = FileJobRecovery(factory, file_executor, invoice_executor)
        recovered = recovery.recover_expired_once(worker_id="invoice-recovery-worker")
        assert recovered.outcome == "claimed_and_succeeded"
        assert recovered.job_id == str(extraction_job_id)

        with factory() as session:
            job = session.get(AsyncJob, extraction_job_id)
            steps = tuple(
                session.scalars(
                    select(AsyncJobStep)
                    .where(AsyncJobStep.job_id == extraction_job_id)
                    .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                ).all()
            )
            assert job is not None
            assert job.status == "succeeded"
            assert job.attempt_no == 2
            assert [
                (step.attempt_no, step.step_code, step.status, step.error_code) for step in steps
            ] == [
                (1, "extract", "failed", "LEASE_EXPIRED"),
                (2, "extract", "succeeded", None),
            ]
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(FilePrimaryBusinessObject)
                    .where(FilePrimaryBusinessObject.file_id == file_id)
                )
                == 1
            )
    finally:
        if file_id is not None:
            _clear_invoice_subjects(engine, file_id)
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()
