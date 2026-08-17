from __future__ import annotations

import io
import zipfile
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.malware_scanner import ScanResult
from app.adapters.ocr import NotConfiguredOcrEngine
from app.models.corrections import UserCorrection
from app.models.documents import FilePrimaryBusinessObject
from app.models.financial import Contract, ContractField
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, AsyncJobStep, IdempotencyRecord
from app.repositories.job_runtime import JobRuntimeRepository
from app.schemas.contracts import (
    ContractDecisionRequest,
    ContractFactsReplaceRequest,
    ContractFactsWriteData,
    ContractFieldEvidenceData,
)
from app.schemas.files import FileUploadIntent, IntendedBusinessType
from app.services.auth import AuthenticatedActor
from app.services.contract_extraction_executor import ContractExtractionExecutor
from app.services.contract_management import ContractManagementService
from app.services.document_parser import DocumentParser
from app.services.file_job_executor import FileJobExecutor
from app.services.job_recovery import FileJobRecovery
from tests.integration.database.test_file_intake_service import (
    ACTOR_ID,
    ORGANIZATION_ID,
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


def _contract_actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=("contract_admin",),
        permissions=("files.read", "files.upload", "financial.read", "contracts.manage"),
    )


def _contract_docx() -> bytes:
    lines = (
        "合同编号: SYNTH-CONTRACT-001",
        "合同名称: 年度咨询服务合同",
        "甲方名称: 测试采购方",
        "甲方税号: 91310000BUYER0001X",
        "乙方名称: 测试供应商",
        "乙方税号: 91310000SELLER001X",
        "合同金额: 100000.00 CNY",
        "签订日期: 2026-01-01",
        "生效日期: 2026-01-01",
        "到期日期: 2026-12-31",
        "付款方式: 银行转账",
        "付款条件: 验收后十个工作日内付款",
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


def _clear_contract_subjects(engine: Engine, file_id: UUID) -> None:
    tables = ("user_corrections", "file_primary_business_objects", "contract_fields")
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
                    "DELETE FROM contract_fields WHERE contract_id IN "
                    "(SELECT id FROM contracts WHERE organization_id=:organization_id)"
                ),
                {"organization_id": ORGANIZATION_ID},
            )
            connection.execute(
                text("DELETE FROM contracts WHERE organization_id=:organization_id"),
                {"organization_id": ORGANIZATION_ID},
            )
        finally:
            for table_name in reversed(tables):
                connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))


def test_upload_parse_extract_correct_and_confirm_contract_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    file_id: UUID | None = None
    try:
        uploaded = intake.upload(
            _contract_actor(),
            FileUploadIntent(intended_business_type=IntendedBusinessType.CONTRACT),
            file_name="contract.docx",
            declared_mime=_DOCX_MIME,
            stream=io.BytesIO(_contract_docx()),
            idempotency_key="contract-upload-e2e-001",
            trace_id=uuid4(),
        )
        file_id = uploaded.data.file_id
        file_event = _dispatch_pending(factory, uploaded.data.job_id)
        file_executor = _file_executor(factory, _RuntimeStorage(quarantine))
        parsed = file_executor.execute(
            job_id=uploaded.data.job_id,
            event_id=file_event.event_id,
            event_schema_version=file_event.event_version,
            worker_id="contract-file-worker",
        )
        assert parsed.outcome == "succeeded"

        with factory() as session:
            extraction_job = session.scalars(
                select(AsyncJob).where(
                    AsyncJob.resource_id == file_id,
                    AsyncJob.job_type == "contract_extract",
                )
            ).one()
            extraction_job_id = extraction_job.id
        event = _dispatch_pending(factory, extraction_job_id)
        executor = ContractExtractionExecutor(factory)
        extracted = executor.execute(
            job_id=extraction_job_id,
            event_id=event.event_id,
            event_schema_version=event.event_version,
            worker_id="contract-extraction-worker",
        )
        duplicate = executor.execute(
            job_id=extraction_job_id,
            event_id=event.event_id,
            event_schema_version=event.event_version,
            worker_id="contract-extraction-worker-duplicate",
        )
        assert extracted.outcome == "succeeded"
        assert duplicate.outcome == "duplicate_or_stale"

        with factory() as session:
            binding = session.scalars(
                select(FilePrimaryBusinessObject).where(
                    FilePrimaryBusinessObject.file_id == file_id
                )
            ).one()
            assert binding.contract_id is not None
            contract_id = binding.contract_id
            contract = session.get(Contract, contract_id)
            assert contract is not None
            assert contract.contract_no == "SYNTH-CONTRACT-001"
            assert contract.amount is not None and contract.amount == 100000
            assert contract.confirmation_status == "unconfirmed"
            assert contract.status == "draft"
            assert contract.row_version == 1
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ContractField)
                    .where(ContractField.contract_id == contract_id)
                )
                == 13
            )

        actor = _contract_actor()
        service = ContractManagementService(factory)
        evidence = service.get_evidence(ORGANIZATION_ID, contract_id)
        assert evidence.row_version == "1"
        assert all(item.evidence is not None for item in evidence.fields)
        replacement = ContractFactsReplaceRequest(
            row_version="1",
            reason="人工复核并修正付款条件",
            facts=ContractFactsWriteData(
                contract_no="SYNTH-CONTRACT-001",
                name="年度咨询服务合同",
                party_a_name="测试采购方",
                party_a_tax_no="91310000BUYER0001X",
                party_b_name="测试供应商",
                party_b_tax_no="91310000SELLER001X",
                amount="100000.00",
                currency="CNY",
                signed_date=date(2026, 1, 1),
                effective_date=date(2026, 1, 1),
                expiry_date=date(2026, 12, 31),
                payment_method="银行转账",
                payment_terms="验收后十五个工作日内付款",
            ),
            field_evidence=tuple(
                ContractFieldEvidenceData(
                    field_code=item.field_code,
                    evidence=item.evidence,
                )
                for item in evidence.fields
                if item.evidence is not None
            ),
        )
        corrected = service.replace_facts(
            actor,
            contract_id,
            replacement,
            "contract-facts-e2e-001",
            uuid4(),
        )
        replay = service.replace_facts(
            actor,
            contract_id,
            replacement,
            "contract-facts-e2e-001",
            uuid4(),
        )
        assert corrected.replayed is False
        assert replay.replayed is True
        assert corrected.data.contract.payment_terms == "验收后十五个工作日内付款"
        assert corrected.data.contract.row_version == "2"

        confirmed = service.decide(
            actor,
            contract_id,
            ContractDecisionRequest(
                row_version="2",
                decision="confirmed",
                reason="核心字段与原文证据复核通过",
            ),
            "contract-confirm-e2e-001",
            uuid4(),
        )
        assert confirmed.data.contract.confirmation_status == "confirmed"
        assert confirmed.data.contract.status == "active"
        assert confirmed.data.contract.row_version == "3"
        history = service.get_history(ORGANIZATION_ID, contract_id)
        assert [item.field_path for item in history.items] == ["facts", "decision"]
        assert service.get_evidence(ORGANIZATION_ID, contract_id).row_version == "3"

        with factory() as session:
            fields = tuple(
                session.scalars(
                    select(ContractField)
                    .where(ContractField.contract_id == contract_id)
                    .order_by(ContractField.field_code)
                ).all()
            )
            assert len(fields) == 13
            assert {field.confirmation_status for field in fields} == {"confirmed"}
            assert session.scalar(select(func.count()).select_from(UserCorrection)) == 2
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecord)
                    .where(IdempotencyRecord.organization_id == ORGANIZATION_ID)
                )
                == 3
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
                "contracts.extraction_created",
                "contracts.facts_replaced",
                "contracts.confirmed",
            )
    finally:
        if file_id is not None:
            _clear_contract_subjects(engine, file_id)
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()


def test_expired_contract_extraction_lease_is_fenced_and_recovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    file_id: UUID | None = None
    try:
        uploaded = intake.upload(
            _contract_actor(),
            FileUploadIntent(intended_business_type=IntendedBusinessType.CONTRACT),
            file_name="contract-recovery.docx",
            declared_mime=_DOCX_MIME,
            stream=io.BytesIO(_contract_docx()),
            idempotency_key="contract-upload-recovery-001",
            trace_id=uuid4(),
        )
        file_id = uploaded.data.file_id
        file_event = _dispatch_pending(factory, uploaded.data.job_id)
        file_executor = _file_executor(factory, _RuntimeStorage(quarantine))
        assert (
            file_executor.execute(
                job_id=uploaded.data.job_id,
                event_id=file_event.event_id,
                event_schema_version=file_event.event_version,
                worker_id="contract-recovery-file-worker",
            ).outcome
            == "succeeded"
        )
        with factory() as session:
            extraction_job_id = session.scalars(
                select(AsyncJob.id).where(
                    AsyncJob.resource_id == file_id,
                    AsyncJob.job_type == "contract_extract",
                )
            ).one()
        event = _dispatch_pending(factory, extraction_job_id)
        with factory.begin() as session:
            claim = JobRuntimeRepository(session).claim_job(
                job_id=extraction_job_id,
                event_id=event.event_id,
                event_schema_version=event.event_version,
                worker_id="crashed-contract-worker",
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

        contract_executor = ContractExtractionExecutor(factory)
        recovery = FileJobRecovery(
            factory,
            file_executor,
            invoice_executor=None,
            contract_executor=contract_executor,
        )
        recovered = recovery.recover_expired_once(worker_id="contract-recovery-worker")
        assert recovered.outcome == "claimed_and_succeeded"

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
            _clear_contract_subjects(engine, file_id)
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()
