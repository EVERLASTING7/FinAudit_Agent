from __future__ import annotations

import hashlib
import io
import json
import os
import socketserver
import struct
import tempfile
import threading
from contextlib import ExitStack, asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import uvicorn
from celery.contrib.testing.worker import start_worker  # type: ignore[import-untyped]
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from reportlab.pdfgen import canvas
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.minio_file_runtime import MinioFileRuntimeAdapter
from app.adapters.minio_quarantine import MinioQuarantineAdapter, QuarantineObject
from app.adapters.minio_report_storage import (
    MinioReportStorageAdapter,
    ReportObjectLocator,
    report_object_locators,
)
from app.audit.rule_catalog import publish_builtin_catalog
from app.core.auth_security import hash_password
from app.core.config import Settings, canonicalize_http_origin
from app.db.session import create_application_engine, create_session_factory
from app.models.audit import AuditReport, AuditTask, AuditTaskExecution, AuditTaskItem
from app.models.auth import Organization, Role, User, UserRole
from app.models.corrections import UserCorrection
from app.models.document_processing import DocumentBlock, DocumentParseVersion
from app.models.documents import FilePrimaryBusinessObject, FileRecord
from app.models.financial import (
    Contract,
    ContractInvoice,
    Invoice,
    SupplementaryAgreement,
    SupplementaryAgreementChange,
    Supplier,
)
from app.models.knowledge import DocumentBlockCorrection, DocumentMarkdownVersion
from app.models.operations import OperationLog
from app.models.reliability import (
    JOB_LEASE_POLICY_HASH,
    JOB_LEASE_POLICY_VERSION,
    JOB_RETRY_POLICY_HASH,
    JOB_RETRY_POLICY_VERSION,
    AsyncJob,
    AsyncJobStep,
    IdempotencyRecord,
    OutboxEvent,
)
from app.repositories.auth import AuthRepository
from app.repositories.document_processing import (
    DocumentProcessingRepository,
    ParseBlockWrite,
    ParsePageWrite,
    ParseVersionWrite,
)
from app.repositories.job_runtime import JobRuntimeRepository
from app.repositories.markdown_write import MarkdownWriteRepository
from app.schemas.audits import (
    AuditFinanceReviewRequest,
    AuditRiskReviewRequest,
    AuditTaskCreateRequest,
)
from app.services.audit_job_executor import AuditJobExecutor
from app.services.audit_management import AuditManagementService
from app.services.auth import AuthenticatedActor, AuthService
from app.services.contract_primary_invoice_query import (
    ContractPrimaryInvoiceQueryService,
)
from app.services.contract_query import ContractQueryService
from app.services.document_correction import DocumentCorrectionService
from app.services.file_intake import FileIntakeService, FileQueryService
from app.services.file_management import FileManagementService
from app.services.invoice_primary_contract_query import (
    InvoicePrimaryContractQueryService,
)
from app.services.invoice_query import InvoiceQueryService
from app.services.report_job_executor import ReportJobExecutor
from app.services.report_management import ReportManagementService
from app.services.supplementary_agreement_management import (
    SupplementaryAgreementManagementService,
)
from app.services.supplementary_agreement_query import (
    SupplementaryAgreementQueryService,
)
from app.services.supplier_management import SupplierManagementService
from app.services.user_query import UserQueryService
from app.workers.bootstrap import create_celery_app
from app.workers.dispatcher_process import (
    DispatcherProcessRuntime,
    create_dispatcher_runtime,
    run_dispatcher_iteration,
)
from app.workers.file_handler_registry import FILE_INPUT_SCHEMA_VERSION, load_file_handler
from tests.integration.database.test_authenticated_financial_read_api import (
    ADMIN_USER_ID,
    AGREEMENT_ID,
    CONTRACT_ID,
    DUPLICATE_INVOICE_ID,
    FILE_ID,
    INVOICE_ID,
    ORGANIZATION_ID,
    USER_ID,
    _bound_transaction_waits,
    _clear_owned_test_facts,
    _runtime_settings,
    _seed_subject_and_financial_facts,
)
from tests.integration.database.test_contract_extraction_management import (
    _contract_docx as _financial_loop_contract_docx,
)
from tests.integration.database.test_invoice_extraction_management import (
    _invoice_docx as _financial_loop_invoice_docx,
)
from tests.integration.database.test_migrations import (
    assert_disposable_database_marker,
    read_safe_test_database_url,
)

_GATE_TOKEN = "RUN_DISPOSABLE_FINANCIAL_READ_BROWSER_V1"
_REPORT_GATE_TOKEN = "RUN_DISPOSABLE_REPORT_BROWSER_V1"
_FILE_UPLOAD_GATE_TOKEN = "RUN_DISPOSABLE_FILE_UPLOAD_BROWSER_V1"
_FINANCIAL_LOOP_GATE_TOKEN = "RUN_DISPOSABLE_FINANCIAL_LOOP_BROWSER_V1"
_SUPPLEMENTARY_GATE_TOKEN = "RUN_DISPOSABLE_SUPPLEMENTARY_AGREEMENT_BROWSER_V1"
_INVOICE_DUPLICATE_GATE_TOKEN = "RUN_DISPOSABLE_INVOICE_DUPLICATE_BROWSER_V1"
_DOCUMENT_CORRECTION_GATE_TOKEN = "RUN_DISPOSABLE_DOCUMENT_CORRECTION_BROWSER_V1"
_AUTH_KID = "browser-gate-auth-v1"
_SHUTDOWN_TOKEN = "STOP_DISPOSABLE_BROWSER_GATE_V1"
_FILE_CAPABILITIES_COMPLETE_TOKEN = "COMPLETE_DISPOSABLE_FILE_CAPABILITIES_BROWSER_V1"
_FINANCIAL_LOOP_COMPLETE_TOKEN = "COMPLETE_DISPOSABLE_FINANCIAL_LOOP_BROWSER_V1"
_SUPPLEMENTARY_COMPLETE_TOKEN = "COMPLETE_DISPOSABLE_SUPPLEMENTARY_AGREEMENT_BROWSER_V1"
_INVOICE_DUPLICATE_COMPLETE_TOKEN = "COMPLETE_DISPOSABLE_INVOICE_DUPLICATE_BROWSER_V1"
_DOCUMENT_CORRECTION_COMPLETE_TOKEN = "COMPLETE_DISPOSABLE_DOCUMENT_CORRECTION_BROWSER_V1"
_SUPPLEMENTARY_FILE_ID = UUID("7c000000-0000-4000-8000-000000000001")
_SUPPLEMENTARY_BINDING_ID = UUID("7c000000-0000-4000-8000-000000000002")
_SUPPLEMENTARY_CONTRACT_FILE_ID = UUID("7c000000-0000-4000-8000-000000000003")
_SUPPLEMENTARY_CONTRACT_BINDING_ID = UUID("7c000000-0000-4000-8000-000000000004")
_SUPPLEMENTARY_QUOTE = "合同金额调整为 120.50 元"
_SUPPLEMENTARY_REPLACE_REASON = "浏览器补充协议字段替换"
_SUPPLEMENTARY_CONFIRM_REASON = "浏览器逐项复核确认"
_SUPPLEMENTARY_REJECT_AGREEMENT_ID = UUID("7c000000-0000-4000-8000-000000000005")
_SUPPLEMENTARY_REJECT_CHANGE_ID = UUID("7c000000-0000-4000-8000-000000000006")
_SUPPLEMENTARY_REJECT_REASON = "浏览器复核后拒绝补充协议"
_DOCUMENT_CORRECTION_TEXT = "浏览器纠错后的补充协议证据文本"
_DOCUMENT_CORRECTION_REASON = "浏览器人工复核纠错"
_SUPPLEMENTARY_CONTRACT_ACTOR_ID = UUID("7b000000-0000-4000-8000-000000000005")
_ROLE_MATRIX_PASSWORD = "Synthetic-Role-Matrix-2026!"
_ROLE_MATRIX_USERS = (
    (
        UUID("7b000000-0000-4000-8000-000000000001"),
        UUID("7b000000-0000-4000-8000-000000000002"),
        "browser.finance.matrix",
        "Synthetic finance matrix user",
        "finance_reviewer",
    ),
    (
        UUID("7b000000-0000-4000-8000-000000000003"),
        UUID("7b000000-0000-4000-8000-000000000004"),
        "browser.audit.matrix",
        "Synthetic audit matrix user",
        "audit_reviewer",
    ),
    (
        UUID("7b000000-0000-4000-8000-000000000005"),
        UUID("7b000000-0000-4000-8000-000000000006"),
        "browser.contract.matrix",
        "Synthetic contract matrix user",
        "contract_admin",
    ),
    (
        UUID("7b000000-0000-4000-8000-000000000007"),
        UUID("7b000000-0000-4000-8000-000000000008"),
        "browser.readonly.matrix",
        "Synthetic read-only matrix user",
        "read_only",
    ),
)
_ROLE_MATRIX_USER_IDS = frozenset(
    (ADMIN_USER_ID, *(user_id for user_id, _, _, _, _ in _ROLE_MATRIX_USERS))
)
_CLAMD_COMMAND = b"zINSTREAM\0"
_SYNTHETIC_SCAN_FAIL_ONCE_MARKER = b"FINAUDIT_SCAN_FAIL_ONCE"
_MAX_SYNTHETIC_SCAN_BYTES = 50 * 1024 * 1024


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        raise RuntimeError(f"BROWSER_GATE_{name}_MISSING")
    return value


def _minio_settings() -> dict[str, object]:
    return {
        "minio_endpoint": _required_environment("MINIO_ENDPOINT"),
        "minio_secure": _required_environment("MINIO_SECURE").lower() == "true",
        "minio_access_key": _required_environment("MINIO_ACCESS_KEY"),
        "minio_secret_key": _required_environment("MINIO_SECRET_KEY"),
        "minio_worker_access_key": _required_environment("MINIO_WORKER_ACCESS_KEY"),
        "minio_worker_secret_key": _required_environment("MINIO_WORKER_SECRET_KEY"),
        "minio_bucket_quarantine": _required_environment("MINIO_BUCKET_QUARANTINE"),
        "minio_bucket_originals": _required_environment("MINIO_BUCKET_ORIGINALS"),
        "minio_bucket_assets": _required_environment("MINIO_BUCKET_ASSETS"),
        "minio_bucket_previews": _required_environment("MINIO_BUCKET_PREVIEWS"),
        "minio_bucket_reports": _required_environment("MINIO_BUCKET_REPORTS"),
        "minio_bucket_exports": _required_environment("MINIO_BUCKET_EXPORTS"),
        "minio_bucket_temp": _required_environment("MINIO_BUCKET_TEMP"),
    }


def _file_worker_settings() -> dict[str, object]:
    raw_port = _required_environment("FINAUDIT_BROWSER_SCANNER_PORT")
    if not raw_port.isascii() or not raw_port.isdigit():
        raise RuntimeError("BROWSER_GATE_SCANNER_PORT_INVALID")
    scanner_port = int(raw_port)
    if scanner_port < 1024 or scanner_port > 65535:
        raise RuntimeError("BROWSER_GATE_SCANNER_PORT_INVALID")
    queue_suffix = uuid4().hex
    return {
        "redis_url": _required_environment("FINAUDIT_BROWSER_REDIS_URL"),
        "celery_broker_url": _required_environment("FINAUDIT_BROWSER_REDIS_URL"),
        "celery_result_backend": _required_environment("FINAUDIT_BROWSER_REDIS_RESULT_URL"),
        "celery_queue_document": f"document-browser-{queue_suffix}",
        "celery_queue_extraction": f"extraction-browser-{queue_suffix}",
        "celery_queue_knowledge": f"knowledge-browser-{queue_suffix}",
        "celery_queue_evaluation": f"evaluation-browser-{queue_suffix}",
        "celery_queue_audit": f"audit-browser-{queue_suffix}",
        "celery_queue_report": f"report-browser-{queue_suffix}",
        "celery_queue_maintenance": f"maintenance-browser-{queue_suffix}",
        "scanner_provider": "clamav_instream",
        "scanner_host": "127.0.0.1",
        "scanner_port": scanner_port,
        "scanner_connect_timeout_seconds": 2,
        "scanner_read_timeout_seconds": 10,
    }


def _receive_exact(connection: object, length: int) -> bytes:
    receiver = getattr(connection, "recv", None)
    if not callable(receiver):
        raise OSError
    payload = bytearray()
    while len(payload) < length:
        chunk = receiver(length - len(payload))
        if type(chunk) is not bytes or not chunk:
            raise OSError
        payload.extend(chunk)
    return bytes(payload)


class _SyntheticClamdHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        connection = self.request
        if _receive_exact(connection, len(_CLAMD_COMMAND)) != _CLAMD_COMMAND:
            return
        payload = bytearray()
        while True:
            chunk_size = struct.unpack("!I", _receive_exact(connection, 4))[0]
            if chunk_size == 0:
                break
            if len(payload) + chunk_size > _MAX_SYNTHETIC_SCAN_BYTES:
                return
            payload.extend(_receive_exact(connection, chunk_size))
        if payload:
            server = self.server
            if isinstance(server, _SyntheticClamdServer) and server.should_fail_once(
                bytes(payload)
            ):
                connection.sendall(b"stream: synthetic ERROR\0")
            else:
                connection.sendall(b"stream: OK\0")


class _SyntheticClamdServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[socketserver.BaseRequestHandler],
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self._failure_lock = threading.Lock()
        self._failed_payloads: set[str] = set()

    def should_fail_once(self, payload: bytes) -> bool:
        if _SYNTHETIC_SCAN_FAIL_ONCE_MARKER not in payload:
            return False
        digest = hashlib.sha256(payload).hexdigest()
        with self._failure_lock:
            if digest in self._failed_payloads:
                return False
            self._failed_payloads.add(digest)
            return True


def _file_capability_pdf(label: str, *, fail_once: bool = False) -> bytes:
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=(300, 300), invariant=1)
    document.drawString(20, 250, label)
    document.drawString(20, 230, "Browser multipart capability gate")
    document.save()
    payload = output.getvalue()
    if fail_once:
        payload += b"\n% " + _SYNTHETIC_SCAN_FAIL_ONCE_MARKER + b"\n"
    return payload


class _DispatcherLoop:
    def __init__(self, runtime: DispatcherProcessRuntime) -> None:
        self._runtime = runtime
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="finaudit-browser-dispatcher",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                result = run_dispatcher_iteration(self._runtime)
                if result.outcome == "idle":
                    self._stop.wait(0.05)
        except BaseException as error:
            self._error = error
            self._stop.set()

    def assert_healthy(self) -> None:
        if self._error is not None or not self._thread.is_alive():
            raise RuntimeError("BROWSER_GATE_DISPATCHER_FAILED")

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        self._runtime.close()
        if self._thread.is_alive() or self._error is not None:
            raise RuntimeError("BROWSER_GATE_DISPATCHER_FAILED")


def _publish_next_job(factory: sessionmaker[Session], job_id: UUID) -> UUID:
    with factory.begin() as session:
        repository = JobRuntimeRepository(session)
        claim = repository.claim_next_outbox()
        if claim is None or claim.job.id != job_id or not repository.mark_outbox_published(claim):
            raise RuntimeError("BROWSER_GATE_OUTBOX_INVALID")
        return claim.event_id


def _prepare_report_financial_facts(engine: Engine) -> None:
    """Remove the deliberate duplicate and align the synthetic buyer for a no-risk report."""

    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE invoices DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM invoices WHERE id = %s",
                (DUPLICATE_INVOICE_ID,),
            )
        finally:
            connection.exec_driver_sql("ALTER TABLE invoices ENABLE TRIGGER USER")
    factory = create_session_factory(engine)
    with factory.begin() as session:
        organization = session.get(Organization, ORGANIZATION_ID)
        invoice = session.get(Invoice, INVOICE_ID)
        if organization is None or invoice is None or invoice.buyer_tax_no is None:
            raise RuntimeError("BROWSER_GATE_REPORT_FACTS_MISSING")
        organization.tax_number = invoice.buyer_tax_no


def _grant_financial_loop_permissions(factory: sessionmaker[Session]) -> None:
    """Allow the synthetic finance user to perform the contract-admin lane in this gate."""

    with factory.begin() as session:
        role = session.scalar(select(Role).where(Role.code == "contract_admin"))
        if role is None:
            raise RuntimeError("BROWSER_GATE_CONTRACT_ADMIN_ROLE_MISSING")
        existing = session.scalar(
            select(UserRole).where(UserRole.user_id == USER_ID, UserRole.role_id == role.id)
        )
        if existing is None:
            session.add(
                UserRole(
                    id=uuid4(),
                    user_id=USER_ID,
                    role_id=role.id,
                    assigned_by=None,
                    assignment_source="bootstrap",
                    assignment_reason="system_bootstrap",
                )
            )
        organization = session.get(Organization, ORGANIZATION_ID)
        if organization is None:
            raise RuntimeError("BROWSER_GATE_ORGANIZATION_MISSING")
        organization.tax_number = "91310000BUYER0001X"


def _add_stored_browser_file(
    session: Session,
    *,
    file_id: UUID,
    original_name: str,
    intended_business_type: str,
    sha256: str,
) -> None:
    file_record = FileRecord(
        id=file_id,
        organization_id=ORGANIZATION_ID,
        original_name=original_name,
        extension=".pdf",
        mime_type="application/pdf",
        detected_mime_type="application/pdf",
        size_bytes=128,
        sha256=sha256,
        minio_bucket="quarantine",
        minio_object_key=f"{ORGANIZATION_ID}/{file_id}/quarantine",
        original_minio_bucket=None,
        original_minio_object_key=None,
        status="uploaded",
        intended_business_type=intended_business_type,
        target_knowledge_base_id=None,
        auto_process_requested=True,
        security_scan_status="pending",
        rejection_code=None,
        rejection_message=None,
        uploaded_by=USER_ID,
        stored_at=None,
        archived_at=None,
        created_by=USER_ID,
        updated_by=USER_ID,
    )
    session.add(file_record)
    session.flush()
    file_record.status = "validating"
    file_record.row_version += 1
    session.flush()
    file_record.status = "stored"
    file_record.security_scan_status = "clean"
    file_record.original_minio_bucket = "originals"
    file_record.original_minio_object_key = f"{ORGANIZATION_ID}/{file_id}/original"
    now = AuthRepository(session).database_now()
    file_record.stored_at = now
    file_record.row_version += 1
    session.flush()
    input_json: dict[str, object] = {
        "auto_process_requested": True,
        "file_id": str(file_id),
        "intended_business_type": intended_business_type,
        "processing_scope": "full",
        "target_knowledge_base_id": None,
    }
    handler = load_file_handler("file_process")
    handler.validate_input(input_json)
    session.add(
        AsyncJob(
            id=uuid4(),
            organization_id=ORGANIZATION_ID,
            job_type="file_process",
            resource_type="file",
            resource_id=file_id,
            status="queued",
            stage=None,
            attempt_no=0,
            max_attempts=handler.handler.max_attempts,
            current_attempt_start_step_code="scan",
            input_hash=hashlib.sha256(
                json.dumps(
                    input_json,
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            input_json=input_json,
            input_schema_version=FILE_INPUT_SCHEMA_VERSION,
            handler_registry_version=handler.registry_version,
            handler_registry_hash=handler.registry_hash,
            retry_policy_version=JOB_RETRY_POLICY_VERSION,
            retry_policy_hash=JOB_RETRY_POLICY_HASH,
            lease_policy_version=JOB_LEASE_POLICY_VERSION,
            lease_policy_hash=JOB_LEASE_POLICY_HASH,
            row_version=1,
            trace_id=uuid4(),
            created_by=USER_ID,
            created_at=now,
        )
    )
    session.flush()


def _prepare_supplementary_browser_facts(
    factory: sessionmaker[Session],
    *,
    activate_parse: bool = False,
) -> UUID:
    """Prepare confirm/conflict/reject agreements and one scoped evidence block."""

    with factory.begin() as session:
        agreement = session.get(SupplementaryAgreement, AGREEMENT_ID)
        if agreement is None:
            raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_SUBJECT_MISSING")

        agreement.status = "draft"
        agreement.confirmation_status = "unconfirmed"
        agreement.confirmed_by = None
        agreement.confirmed_at = None
        agreement.confirmation_reason = None
        agreement.updated_by = USER_ID

        session.add(
            SupplementaryAgreement(
                id=_SUPPLEMENTARY_REJECT_AGREEMENT_ID,
                organization_id=ORGANIZATION_ID,
                contract_id=CONTRACT_ID,
                agreement_no="AGREEMENT-INTEGRATION-REJECT-001",
                name="Synthetic rejected supplementary agreement",
                signed_date=date(2026, 2, 15),
                effective_date=date(2026, 4, 1),
                status="pending_confirmation",
                confirmation_status="unconfirmed",
                confirmed_by=None,
                confirmed_at=None,
                confirmation_reason=None,
                critical_fact_hash="c" * 64,
                row_version=1,
                created_by=USER_ID,
                updated_by=USER_ID,
            )
        )
        session.flush()
        session.add(
            SupplementaryAgreementChange(
                id=_SUPPLEMENTARY_REJECT_CHANGE_ID,
                supplementary_agreement_id=_SUPPLEMENTARY_REJECT_AGREEMENT_ID,
                field_code="payment_terms",
                value_type="string",
                old_value_json="30 days",
                new_value_json="45 days",
                evidence_block_id=None,
                page_no=None,
                quote_text=None,
                bbox_json=None,
                confirmation_status="unconfirmed",
                confirmed_by=None,
                confirmed_at=None,
            )
        )

        _add_stored_browser_file(
            session,
            file_id=_SUPPLEMENTARY_CONTRACT_FILE_ID,
            original_name="contract-browser.pdf",
            intended_business_type="contract",
            sha256="1" * 64,
        )
        session.add(
            FilePrimaryBusinessObject(
                id=_SUPPLEMENTARY_CONTRACT_BINDING_ID,
                file_id=_SUPPLEMENTARY_CONTRACT_FILE_ID,
                business_type="contract",
                contract_id=CONTRACT_ID,
                invoice_id=None,
                supplementary_agreement_id=None,
                policy_document_id=None,
                bound_by=USER_ID,
            )
        )
        _add_stored_browser_file(
            session,
            file_id=_SUPPLEMENTARY_FILE_ID,
            original_name="supplementary-browser.pdf",
            sha256="f" * 64,
            intended_business_type="supplementary_agreement",
        )
        session.add(
            FilePrimaryBusinessObject(
                id=_SUPPLEMENTARY_BINDING_ID,
                file_id=_SUPPLEMENTARY_FILE_ID,
                business_type="supplementary_agreement",
                contract_id=None,
                invoice_id=None,
                supplementary_agreement_id=AGREEMENT_ID,
                policy_document_id=None,
                bound_by=USER_ID,
            )
        )
        parse_version_id = DocumentProcessingRepository(session).append_result(
            organization_id=ORGANIZATION_ID,
            file_id=_SUPPLEMENTARY_FILE_ID,
            trace_id=uuid4(),
            result=ParseVersionWrite(
                source_type="parser",
                parser_name="synthetic-browser-parser",
                parser_version="1",
                ocr_name=None,
                ocr_version=None,
                average_confidence=Decimal("0.99"),
                pages=(
                    ParsePageWrite(
                        page_no=1,
                        width=Decimal("595"),
                        height=Decimal("842"),
                        unit="point",
                        text=_SUPPLEMENTARY_QUOTE,
                        confidence=Decimal("0.99"),
                        blocks=(
                            ParseBlockWrite(
                                block_index=0,
                                block_type="paragraph",
                                text=_SUPPLEMENTARY_QUOTE,
                                bbox=None,
                                confidence=Decimal("0.99"),
                            ),
                        ),
                    ),
                ),
            ),
        )
        if activate_parse:
            activation = MarkdownWriteRepository(session).generate_and_activate(
                organization_id=ORGANIZATION_ID,
                file_id=_SUPPLEMENTARY_FILE_ID,
                parse_version_id=parse_version_id,
                trace_id=uuid4(),
                actor_id=USER_ID,
            )
            if activation.outcome != "active":
                raise RuntimeError("BROWSER_GATE_DOCUMENT_CORRECTION_SOURCE_NOT_ACTIVE")
        evidence_block_id = session.scalar(
            select(DocumentBlock.id).where(DocumentBlock.parse_version_id == parse_version_id)
        )
        if not isinstance(evidence_block_id, UUID):
            raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_EVIDENCE_MISSING")
        return evidence_block_id


def _seed_role_matrix_users(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        now = AuthRepository(session).database_now()
        role_codes = tuple(item[4] for item in _ROLE_MATRIX_USERS)
        roles = {
            role.code: role
            for role in session.scalars(select(Role).where(Role.code.in_(role_codes)))
        }
        if set(roles) != set(role_codes):
            raise RuntimeError("BROWSER_GATE_ROLE_MATRIX_ROLES_MISSING")
        for user_id, user_role_id, username, display_name, role_code in _ROLE_MATRIX_USERS:
            session.add(
                User(
                    id=user_id,
                    organization_id=ORGANIZATION_ID,
                    username=username,
                    display_name=display_name,
                    password_hash=hash_password(_ROLE_MATRIX_PASSWORD),
                    status="active",
                    password_changed_at=now,
                )
            )
            session.add(
                UserRole(
                    id=user_role_id,
                    user_id=user_id,
                    role_id=roles[role_code].id,
                    assigned_by=None,
                    assignment_source="bootstrap",
                    assignment_reason="system_bootstrap",
                )
            )


def _seed_ready_report(
    factory: sessionmaker[Session],
    settings: Settings,
) -> tuple[UUID, MinioReportStorageAdapter, tuple[ReportObjectLocator, ReportObjectLocator]]:
    with factory.begin() as session:
        publish_builtin_catalog(
            session,
            application_release=settings.app_version,
            change_reason="publish disposable report browser catalog",
        )

    actor = AuthenticatedActor(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=("finance_reviewer",),
        permissions=(),
    )
    audit_service = AuditManagementService(factory, settings)
    created = audit_service.create_task(
        actor,
        AuditTaskCreateRequest(
            task_no="AUDIT-BROWSER-REPORT-001",
            name="正式报告浏览器验收",
            description="验证授权 PDF 预览与 XLSX 下载",
            baseline_date=date(2026, 6, 30),
            contract_id=CONTRACT_ID,
            invoice_ids=[INVOICE_ID],
        ),
        "browser-report-create-v1",
        uuid4(),
    )
    job_id = created.data.execution.job_id
    if job_id is None:
        raise RuntimeError("BROWSER_GATE_AUDIT_JOB_MISSING")
    audit_result = AuditJobExecutor(factory).execute(
        job_id=job_id,
        event_id=_publish_next_job(factory, job_id),
        event_schema_version=1,
        worker_id="browser-audit-worker",
    )
    if audit_result.outcome != "succeeded":
        raise RuntimeError("BROWSER_GATE_AUDIT_EXECUTION_FAILED")

    detail = audit_service.get_task(ORGANIZATION_ID, created.data.task.id)
    if any(risk.effective_level == "high" for risk in detail.risks):
        raise RuntimeError("BROWSER_GATE_UNEXPECTED_HIGH_RISK")
    for index, risk in enumerate(detail.risks, start=1):
        audit_service.review_risk(
            actor,
            risk.id,
            AuditRiskReviewRequest(
                row_version=risk.row_version,
                decision="confirmed",
                reason="浏览器验收合成事实已核对",
            ),
            f"browser-report-risk-{index:03d}",
            uuid4(),
            high_risk=False,
        )
    completed = audit_service.finance_review(
        actor,
        detail.execution.id,
        AuditFinanceReviewRequest(
            row_version=detail.execution.row_version,
            decision="submit",
            reason="浏览器验收合成审核已完成",
        ),
        "browser-report-finance-review-v1",
        uuid4(),
    )
    if completed.data.execution.status != "completed":
        raise RuntimeError("BROWSER_GATE_AUDIT_NOT_COMPLETED")

    with factory() as session:
        report = session.scalar(
            select(AuditReport).where(AuditReport.execution_id == detail.execution.id)
        )
        if report is None or report.status != "queued" or report.job_id is None:
            raise RuntimeError("BROWSER_GATE_REPORT_NOT_QUEUED")
        report_id = report.id
        report_job_id = report.job_id
        report_version = report.report_version

    storage = MinioReportStorageAdapter(settings, credential_scope="worker")
    generated = ReportJobExecutor(factory, storage).execute(
        job_id=report_job_id,
        event_id=_publish_next_job(factory, report_job_id),
        event_schema_version=1,
        worker_id="browser-report-worker",
    )
    if generated.outcome != "succeeded":
        raise RuntimeError("BROWSER_GATE_REPORT_GENERATION_FAILED")
    locators = report_object_locators(
        organization_id=ORGANIZATION_ID,
        report_id=report_id,
        report_version=report_version,
        reports_bucket=storage.reports_bucket,
        exports_bucket=storage.exports_bucket,
    )
    return report_id, storage, locators


def _clear_report_facts(engine: Engine) -> None:
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


def _file_gate_manifest(
    factory: sessionmaker[Session],
    dispatcher: _DispatcherLoop,
) -> dict[str, object]:
    dispatcher.assert_healthy()
    with factory() as session:
        files = tuple(
            session.scalars(
                select(FileRecord)
                .where(FileRecord.uploaded_by == USER_ID, FileRecord.id != FILE_ID)
                .order_by(FileRecord.created_at.asc(), FileRecord.id.asc())
            )
        )
        items: list[dict[str, object]] = []
        for file_record in files:
            jobs = tuple(
                session.scalars(
                    select(AsyncJob)
                    .where(
                        AsyncJob.organization_id == ORGANIZATION_ID,
                        AsyncJob.resource_type == "file",
                        AsyncJob.resource_id == file_record.id,
                        AsyncJob.job_type.in_(("file_process", "file_scan")),
                    )
                    .order_by(AsyncJob.created_at.asc(), AsyncJob.id.asc())
                )
            )
            if len(jobs) != 1:
                raise RuntimeError("BROWSER_GATE_FILE_JOB_CARDINALITY_INVALID")
            job = jobs[0]
            action_codes = tuple(
                session.scalars(
                    select(OperationLog.action_code)
                    .where(
                        OperationLog.organization_id == ORGANIZATION_ID,
                        OperationLog.resource_type == "file",
                        OperationLog.resource_id == file_record.id,
                    )
                    .order_by(OperationLog.created_at, OperationLog.id)
                )
            )
            upload_keys = tuple(
                session.scalars(
                    select(IdempotencyRecord.idempotency_key).where(
                        IdempotencyRecord.organization_id == ORGANIZATION_ID,
                        IdempotencyRecord.resource_type == "file",
                        IdempotencyRecord.resource_id == file_record.id,
                    )
                )
            )
            items.append(
                {
                    "file_id": str(file_record.id),
                    "original_name": file_record.original_name,
                    "file_status": file_record.status,
                    "security_scan_status": file_record.security_scan_status,
                    "file_row_version": file_record.row_version,
                    "job_id": str(job.id),
                    "job_status": job.status,
                    "job_type": job.job_type,
                    "job_attempt_no": job.attempt_no,
                    "job_row_version": job.row_version,
                    "trace_id": str(job.trace_id),
                    "original_stored": file_record.original_minio_object_key is not None,
                    "action_codes": list(action_codes),
                    "batch_upload_claimed": any(key.startswith("batch.") for key in upload_keys),
                }
            )
    return {"items": items, "scanner_profile": "synthetic-clamd-clean-v1"}


def _assert_file_capabilities_complete(manifest: dict[str, object]) -> None:
    if manifest.get("scanner_profile") != "synthetic-clamd-clean-v1":
        raise RuntimeError("BROWSER_GATE_FILE_SCANNER_INVALID")
    raw_items = manifest.get("items")
    if type(raw_items) is not list or any(type(item) is not dict for item in raw_items):
        raise RuntimeError("BROWSER_GATE_FILE_MANIFEST_INVALID")
    items = cast(list[dict[str, object]], raw_items)
    if len(items) != 2 or any(item.get("batch_upload_claimed") is not True for item in items):
        raise RuntimeError("BROWSER_GATE_FILE_BATCH_UPLOAD_INVALID")
    if any(
        item.get("security_scan_status") != "clean"
        or item.get("job_status") != "succeeded"
        or item.get("original_stored") is not True
        for item in items
    ):
        raise RuntimeError("BROWSER_GATE_FILE_RUNTIME_INCOMPLETE")

    archived = next(
        (item for item in items if item.get("original_name") == "browser-clean.pdf"),
        None,
    )
    retried = next(
        (item for item in items if item.get("original_name") == "browser-retry.pdf"),
        None,
    )
    if archived is None or retried is None:
        raise RuntimeError("BROWSER_GATE_FILE_FIXTURES_INVALID")
    archived_actions = archived.get("action_codes")
    retried_actions = retried.get("action_codes")
    if (
        archived.get("file_status") != "archived"
        or type(archived_actions) is not list
        or "files.previewed" not in archived_actions
        or "files.archived" not in archived_actions
    ):
        raise RuntimeError("BROWSER_GATE_FILE_ARCHIVE_INVALID")
    if (
        retried.get("file_status") != "stored"
        or type(retried.get("job_attempt_no")) is not int
        or cast(int, retried.get("job_attempt_no")) < 2
        or type(retried_actions) is not list
        or "files.retry_queued" not in retried_actions
        or "files.previewed" not in retried_actions
    ):
        raise RuntimeError("BROWSER_GATE_FILE_RETRY_INVALID")


def _supplementary_manifest(
    factory: sessionmaker[Session],
    evidence_block_id: UUID,
    write_http_results: tuple[dict[str, object], ...],
) -> dict[str, object]:
    with factory() as session:
        agreement = session.get(SupplementaryAgreement, AGREEMENT_ID)
        rejected_agreement = session.get(
            SupplementaryAgreement,
            _SUPPLEMENTARY_REJECT_AGREEMENT_ID,
        )
        changes = tuple(
            session.scalars(
                select(SupplementaryAgreementChange)
                .where(SupplementaryAgreementChange.supplementary_agreement_id == AGREEMENT_ID)
                .order_by(SupplementaryAgreementChange.field_code, SupplementaryAgreementChange.id)
            )
        )
        rejected_changes = tuple(
            session.scalars(
                select(SupplementaryAgreementChange)
                .where(
                    SupplementaryAgreementChange.supplementary_agreement_id
                    == _SUPPLEMENTARY_REJECT_AGREEMENT_ID
                )
                .order_by(SupplementaryAgreementChange.field_code, SupplementaryAgreementChange.id)
            )
        )
        corrections = tuple(
            session.scalars(
                select(UserCorrection)
                .where(
                    UserCorrection.organization_id == ORGANIZATION_ID,
                    UserCorrection.correction_type == "supplementary_agreement_changes",
                    UserCorrection.object_id == AGREEMENT_ID,
                )
                .order_by(UserCorrection.created_at, UserCorrection.id)
            )
        )
        action_codes = tuple(
            session.scalars(
                select(OperationLog.action_code)
                .where(
                    OperationLog.organization_id == ORGANIZATION_ID,
                    OperationLog.resource_type == "supplementary_agreement",
                    OperationLog.resource_id == AGREEMENT_ID,
                )
                .order_by(OperationLog.created_at, OperationLog.id)
            )
        )
        rejected_action_codes = tuple(
            session.scalars(
                select(OperationLog.action_code)
                .where(
                    OperationLog.organization_id == ORGANIZATION_ID,
                    OperationLog.resource_type == "supplementary_agreement",
                    OperationLog.resource_id == _SUPPLEMENTARY_REJECT_AGREEMENT_ID,
                )
                .order_by(OperationLog.created_at, OperationLog.id)
            )
        )
        idempotency_records = tuple(
            session.scalars(
                select(IdempotencyRecord)
                .where(
                    IdempotencyRecord.organization_id == ORGANIZATION_ID,
                    IdempotencyRecord.user_id == _SUPPLEMENTARY_CONTRACT_ACTOR_ID,
                    IdempotencyRecord.resource_type == "supplementary_agreement",
                    IdempotencyRecord.resource_id.in_(
                        (AGREEMENT_ID, _SUPPLEMENTARY_REJECT_AGREEMENT_ID)
                    ),
                )
                .order_by(IdempotencyRecord.created_at, IdempotencyRecord.id)
            )
        )
        role_matrix_login_actor_ids = frozenset(
            actor_id
            for actor_id in session.scalars(
                select(OperationLog.actor_id).where(
                    OperationLog.organization_id == ORGANIZATION_ID,
                    OperationLog.action_code == "auth.login.succeeded",
                    OperationLog.actor_id.in_(_ROLE_MATRIX_USER_IDS),
                )
            )
            if actor_id is not None
        )
    return {
        "expected_evidence_block_id": str(evidence_block_id),
        "agreement": (
            None
            if agreement is None
            else {
                "id": str(agreement.id),
                "status": agreement.status,
                "confirmation_status": agreement.confirmation_status,
                "confirmation_reason": agreement.confirmation_reason,
                "confirmed_by": (
                    None if agreement.confirmed_by is None else str(agreement.confirmed_by)
                ),
                "row_version": agreement.row_version,
            }
        ),
        "rejected_agreement": (
            None
            if rejected_agreement is None
            else {
                "id": str(rejected_agreement.id),
                "status": rejected_agreement.status,
                "confirmation_status": rejected_agreement.confirmation_status,
                "confirmation_reason": rejected_agreement.confirmation_reason,
                "confirmed_by": (
                    None
                    if rejected_agreement.confirmed_by is None
                    else str(rejected_agreement.confirmed_by)
                ),
                "row_version": rejected_agreement.row_version,
            }
        ),
        "changes": [
            {
                "field_code": item.field_code,
                "value_type": item.value_type,
                "old_value": item.old_value_json,
                "new_value": item.new_value_json,
                "evidence_block_id": (
                    None if item.evidence_block_id is None else str(item.evidence_block_id)
                ),
                "page_no": item.page_no,
                "quote_text": item.quote_text,
                "confirmation_status": item.confirmation_status,
                "confirmed_by": None if item.confirmed_by is None else str(item.confirmed_by),
            }
            for item in changes
        ],
        "rejected_changes": [
            {
                "field_code": item.field_code,
                "value_type": item.value_type,
                "old_value": item.old_value_json,
                "new_value": item.new_value_json,
                "evidence_block_id": (
                    None if item.evidence_block_id is None else str(item.evidence_block_id)
                ),
                "page_no": item.page_no,
                "quote_text": item.quote_text,
                "confirmation_status": item.confirmation_status,
                "confirmed_by": None if item.confirmed_by is None else str(item.confirmed_by),
            }
            for item in rejected_changes
        ],
        "corrections": [
            {
                "reason": item.reason,
                "field_path": item.field_path,
                "caused_outdated": item.caused_outdated,
            }
            for item in corrections
        ],
        "action_codes": list(action_codes),
        "rejected_action_codes": list(rejected_action_codes),
        "idempotency": [
            {
                "key_has_expected_prefix": item.idempotency_key.startswith("supplementary-write."),
                "request_method": item.request_method,
                "response_status": item.response_status,
                "resource_id": None if item.resource_id is None else str(item.resource_id),
            }
            for item in idempotency_records
        ],
        "write_http_results": [dict(item) for item in write_http_results],
        "role_matrix_login_actor_ids": sorted(str(item) for item in role_matrix_login_actor_ids),
    }


def _assert_supplementary_complete(manifest: dict[str, object]) -> None:
    evidence_block_id = manifest.get("expected_evidence_block_id")
    agreement = manifest.get("agreement")
    if type(evidence_block_id) is not str or agreement != {
        "id": str(AGREEMENT_ID),
        "status": "confirmed",
        "confirmation_status": "confirmed",
        "confirmation_reason": _SUPPLEMENTARY_CONFIRM_REASON,
        "confirmed_by": str(_SUPPLEMENTARY_CONTRACT_ACTOR_ID),
        "row_version": 3,
    }:
        raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_AGREEMENT_INVALID")

    rejected_agreement = manifest.get("rejected_agreement")
    if rejected_agreement != {
        "id": str(_SUPPLEMENTARY_REJECT_AGREEMENT_ID),
        "status": "rejected",
        "confirmation_status": "rejected",
        "confirmation_reason": _SUPPLEMENTARY_REJECT_REASON,
        "confirmed_by": str(_SUPPLEMENTARY_CONTRACT_ACTOR_ID),
        "row_version": 2,
    }:
        raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_REJECTION_INVALID")

    changes = _manifest_rows(manifest, "changes", scope="SUPPLEMENTARY")
    if len(changes) != 1 or changes[0] != {
        "field_code": "amount",
        "value_type": "number",
        "old_value": "100.25",
        "new_value": "120.50",
        "evidence_block_id": evidence_block_id,
        "page_no": 1,
        "quote_text": _SUPPLEMENTARY_QUOTE,
        "confirmation_status": "confirmed",
        "confirmed_by": str(_SUPPLEMENTARY_CONTRACT_ACTOR_ID),
    }:
        raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_CHANGE_INVALID")

    rejected_changes = _manifest_rows(manifest, "rejected_changes", scope="SUPPLEMENTARY")
    if len(rejected_changes) != 1 or rejected_changes[0] != {
        "field_code": "payment_terms",
        "value_type": "string",
        "old_value": "30 days",
        "new_value": "45 days",
        "evidence_block_id": None,
        "page_no": None,
        "quote_text": None,
        "confirmation_status": "rejected",
        "confirmed_by": str(_SUPPLEMENTARY_CONTRACT_ACTOR_ID),
    }:
        raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_REJECTION_INVALID")

    corrections = _manifest_rows(manifest, "corrections", scope="SUPPLEMENTARY")
    if len(corrections) != 1 or corrections[0] != {
        "reason": _SUPPLEMENTARY_REPLACE_REASON,
        "field_path": "changes",
        "caused_outdated": False,
    }:
        raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_CORRECTION_INVALID")

    action_codes = manifest.get("action_codes")
    if type(action_codes) is not list or sorted(action_codes) != [
        "supplementary_agreements.changes_replaced",
        "supplementary_agreements.confirmed",
    ]:
        raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_AUDIT_INVALID")
    if manifest.get("rejected_action_codes") != ["supplementary_agreements.rejected"]:
        raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_REJECTION_INVALID")

    idempotency = _manifest_rows(manifest, "idempotency", scope="SUPPLEMENTARY")
    if len(idempotency) != 3 or sorted(
        (
            item.get("resource_id"),
            item.get("key_has_expected_prefix"),
            item.get("request_method"),
            item.get("response_status"),
        )
        for item in idempotency
    ) != [
        (str(AGREEMENT_ID), True, "POST", 200),
        (str(AGREEMENT_ID), True, "PUT", 200),
        (str(_SUPPLEMENTARY_REJECT_AGREEMENT_ID), True, "POST", 200),
    ]:
        raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_IDEMPOTENCY_INVALID")

    changes_path = (
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/{AGREEMENT_ID}/changes"
    )
    decision_path = (
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/{AGREEMENT_ID}/decision"
    )
    reject_path = (
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/"
        f"{_SUPPLEMENTARY_REJECT_AGREEMENT_ID}/decision"
    )
    http_results = _manifest_rows(manifest, "write_http_results", scope="SUPPLEMENTARY")
    if sorted(
        (item.get("method"), item.get("path"), item.get("status")) for item in http_results
    ) != [
        ("POST", decision_path, 200),
        ("POST", reject_path, 200),
        ("PUT", changes_path, 200),
        ("PUT", changes_path, 409),
    ]:
        raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_HTTP_MATRIX_INVALID")

    role_actor_ids = manifest.get("role_matrix_login_actor_ids")
    if type(role_actor_ids) is not list or set(role_actor_ids) != {
        str(item) for item in _ROLE_MATRIX_USER_IDS
    }:
        raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_ROLE_MATRIX_INCOMPLETE")


def _financial_loop_manifest(
    factory: sessionmaker[Session],
    dispatcher: _DispatcherLoop,
) -> dict[str, object]:
    dispatcher.assert_healthy()
    with factory() as session:
        files = tuple(
            session.scalars(
                select(FileRecord)
                .where(FileRecord.uploaded_by == USER_ID, FileRecord.id != FILE_ID)
                .order_by(FileRecord.created_at, FileRecord.id)
            )
        )
        bindings = (
            tuple(
                session.scalars(
                    select(FilePrimaryBusinessObject)
                    .where(FilePrimaryBusinessObject.file_id.in_(item.id for item in files))
                    .order_by(FilePrimaryBusinessObject.bound_at, FilePrimaryBusinessObject.id)
                )
            )
            if files
            else ()
        )
        contracts = tuple(
            session.scalars(
                select(Contract)
                .where(
                    Contract.organization_id == ORGANIZATION_ID,
                    Contract.id != CONTRACT_ID,
                    Contract.deleted_at.is_(None),
                )
                .order_by(Contract.created_at, Contract.id)
            )
        )
        invoices = tuple(
            session.scalars(
                select(Invoice)
                .where(
                    Invoice.organization_id == ORGANIZATION_ID,
                    Invoice.id.not_in((INVOICE_ID, DUPLICATE_INVOICE_ID)),
                    Invoice.deleted_at.is_(None),
                )
                .order_by(Invoice.created_at, Invoice.id)
            )
        )
        invoice_ids = tuple(item.id for item in invoices)
        relations = (
            tuple(
                session.scalars(
                    select(ContractInvoice)
                    .where(ContractInvoice.invoice_id.in_(invoice_ids))
                    .order_by(ContractInvoice.created_at, ContractInvoice.id)
                )
            )
            if invoice_ids
            else ()
        )
        suppliers = tuple(
            session.scalars(
                select(Supplier)
                .where(
                    Supplier.organization_id == ORGANIZATION_ID,
                    Supplier.deleted_at.is_(None),
                )
                .order_by(Supplier.created_at, Supplier.id)
            )
        )
        supplier_corrections = tuple(
            session.scalars(
                select(UserCorrection)
                .where(
                    UserCorrection.organization_id == ORGANIZATION_ID,
                    UserCorrection.correction_type == "supplier_field",
                )
                .order_by(UserCorrection.created_at, UserCorrection.id)
            )
        )
        supplier_action_codes = tuple(
            session.scalars(
                select(OperationLog.action_code)
                .where(
                    OperationLog.organization_id == ORGANIZATION_ID,
                    OperationLog.action_code.in_(("supplier.resolve", "supplier.update")),
                )
                .order_by(OperationLog.created_at, OperationLog.id)
            )
        )
        role_matrix_login_actor_ids = frozenset(
            actor_id
            for actor_id in session.scalars(
                select(OperationLog.actor_id).where(
                    OperationLog.organization_id == ORGANIZATION_ID,
                    OperationLog.action_code == "auth.login.succeeded",
                    OperationLog.actor_id.in_(_ROLE_MATRIX_USER_IDS),
                )
            )
            if actor_id is not None
        )
        tasks = tuple(
            session.scalars(
                select(AuditTask)
                .where(AuditTask.organization_id == ORGANIZATION_ID)
                .order_by(AuditTask.created_at, AuditTask.id)
            )
        )
        task_ids = tuple(item.id for item in tasks)
        task_items = (
            tuple(
                session.scalars(
                    select(AuditTaskItem)
                    .where(AuditTaskItem.audit_task_id.in_(task_ids))
                    .order_by(
                        AuditTaskItem.audit_task_id, AuditTaskItem.item_type, AuditTaskItem.id
                    )
                )
            )
            if task_ids
            else ()
        )
        executions = (
            tuple(
                session.scalars(
                    select(AuditTaskExecution)
                    .where(AuditTaskExecution.audit_task_id.in_(task_ids))
                    .order_by(AuditTaskExecution.created_at, AuditTaskExecution.id)
                )
            )
            if task_ids
            else ()
        )
        execution_ids = tuple(item.id for item in executions)
        reports = (
            tuple(
                session.scalars(
                    select(AuditReport)
                    .where(AuditReport.execution_id.in_(execution_ids))
                    .order_by(AuditReport.created_at, AuditReport.id)
                )
            )
            if execution_ids
            else ()
        )
    return {
        "scanner_profile": "synthetic-clamd-clean-v1",
        "files": [
            {
                "id": str(item.id),
                "business_type": item.intended_business_type,
                "status": item.status,
                "security_scan_status": item.security_scan_status,
            }
            for item in files
        ],
        "bindings": [
            {
                "file_id": str(item.file_id),
                "business_type": item.business_type,
                "contract_id": None if item.contract_id is None else str(item.contract_id),
                "invoice_id": None if item.invoice_id is None else str(item.invoice_id),
            }
            for item in bindings
        ],
        "contracts": [
            {
                "id": str(item.id),
                "contract_no": item.contract_no,
                "confirmation_status": item.confirmation_status,
                "status": item.status,
                "supplier_id": None if item.supplier_id is None else str(item.supplier_id),
            }
            for item in contracts
        ],
        "invoices": [
            {
                "id": str(item.id),
                "invoice_number": item.invoice_number,
                "confirmation_status": item.confirmation_status,
                "duplicate_status": item.duplicate_status,
                "status": item.status,
                "supplier_id": None if item.supplier_id is None else str(item.supplier_id),
            }
            for item in invoices
        ],
        "relations": [
            {
                "id": str(item.id),
                "contract_id": str(item.contract_id),
                "invoice_id": str(item.invoice_id),
                "status": item.status,
            }
            for item in relations
        ],
        "suppliers": [
            {
                "id": str(item.id),
                "standard_name": item.standard_name,
                "source_type": item.source_type,
                "source_contract_id": (
                    None if item.source_contract_id is None else str(item.source_contract_id)
                ),
                "source_invoice_id": (
                    None if item.source_invoice_id is None else str(item.source_invoice_id)
                ),
                "confirmation_status": item.confirmation_status,
                "status": item.status,
            }
            for item in suppliers
        ],
        "supplier_corrections": [
            {
                "object_id": str(item.object_id),
                "field_path": item.field_path,
                "before_keys": sorted((item.before_value_json or {}).keys()),
                "after_keys": sorted((item.after_value_json or {}).keys()),
            }
            for item in supplier_corrections
        ],
        "supplier_action_codes": list(supplier_action_codes),
        "role_matrix_login_actor_ids": sorted(str(item) for item in role_matrix_login_actor_ids),
        "tasks": [
            {
                "id": str(item.id),
                "task_no": item.task_no,
                "status": item.status,
                "current_execution_id": (
                    None if item.current_execution_id is None else str(item.current_execution_id)
                ),
                "items": [
                    {
                        "item_type": task_item.item_type,
                        "contract_id": (
                            None if task_item.contract_id is None else str(task_item.contract_id)
                        ),
                        "invoice_id": (
                            None if task_item.invoice_id is None else str(task_item.invoice_id)
                        ),
                    }
                    for task_item in task_items
                    if task_item.audit_task_id == item.id
                ],
            }
            for item in tasks
        ],
        "executions": [
            {
                "id": str(item.id),
                "task_id": str(item.audit_task_id),
                "status": item.status,
                "row_version": item.row_version,
            }
            for item in executions
        ],
        "reports": [
            {
                "id": str(item.id),
                "execution_id": str(item.execution_id),
                "status": item.status,
                "pdf_stored": item.pdf_object_key is not None,
                "xlsx_stored": item.xlsx_object_key is not None,
                "pdf_size_bytes": item.pdf_size_bytes,
                "xlsx_size_bytes": item.xlsx_size_bytes,
            }
            for item in reports
        ],
    }


def _manifest_rows(
    manifest: dict[str, object],
    key: str,
    *,
    scope: str = "FINANCIAL_LOOP",
) -> list[dict[str, object]]:
    value = manifest.get(key)
    if type(value) is not list or any(type(item) is not dict for item in value):
        raise RuntimeError(f"BROWSER_GATE_{scope}_{key.upper()}_INVALID")
    return cast(list[dict[str, object]], value)


def _assert_financial_loop_complete(manifest: dict[str, object]) -> None:
    if manifest.get("scanner_profile") != "synthetic-clamd-clean-v1":
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_SCANNER_INVALID")

    files = _manifest_rows(manifest, "files")
    if len(files) != 2 or {item.get("business_type") for item in files} != {
        "contract",
        "invoice",
    }:
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_FILES_INCOMPLETE")
    if any(
        item.get("status") != "stored" or item.get("security_scan_status") != "clean"
        for item in files
    ):
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_FILES_NOT_READY")

    contracts = _manifest_rows(manifest, "contracts")
    invoices = _manifest_rows(manifest, "invoices")
    if len(contracts) != 1 or contracts[0].get("contract_no") != "SYNTH-CONTRACT-001":
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_CONTRACT_INVALID")
    if (
        contracts[0].get("confirmation_status") != "confirmed"
        or contracts[0].get("status") != "active"
    ):
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_CONTRACT_NOT_CONFIRMED")
    if len(invoices) != 1 or invoices[0].get("invoice_number") != "000001":
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_INVOICE_INVALID")
    if (
        invoices[0].get("confirmation_status") != "confirmed"
        or invoices[0].get("duplicate_status") != "unique"
        or invoices[0].get("status") != "confirmed"
    ):
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_INVOICE_NOT_CONFIRMED")

    contract_id = contracts[0].get("id")
    invoice_id = invoices[0].get("id")
    if type(contract_id) is not str or type(invoice_id) is not str:
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_BUSINESS_IDS_INVALID")

    suppliers = _manifest_rows(manifest, "suppliers")
    if len(suppliers) != 1:
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_SUPPLIER_INVALID")
    supplier_id = suppliers[0].get("id")
    if type(supplier_id) is not str or (
        suppliers[0].get("standard_name"),
        suppliers[0].get("source_type"),
        suppliers[0].get("source_contract_id"),
        suppliers[0].get("source_invoice_id"),
        suppliers[0].get("confirmation_status"),
        suppliers[0].get("status"),
    ) != (
        "测试供应商（浏览器已确认）",
        "contract",
        contract_id,
        None,
        "confirmed",
        "active",
    ):
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_SUPPLIER_INVALID")
    if (
        contracts[0].get("supplier_id") != supplier_id
        or invoices[0].get("supplier_id") != supplier_id
    ):
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_SUPPLIER_BINDINGS_INVALID")

    supplier_corrections = _manifest_rows(manifest, "supplier_corrections")
    expected_correction_keys = [
        "confirmation_status",
        "source_supplier_id",
        "standard_name",
        "status",
    ]
    if len(supplier_corrections) != 1 or (
        supplier_corrections[0].get("object_id"),
        supplier_corrections[0].get("field_path"),
        supplier_corrections[0].get("before_keys"),
        supplier_corrections[0].get("after_keys"),
    ) != (supplier_id, "supplier", expected_correction_keys, expected_correction_keys):
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_SUPPLIER_AUDIT_INVALID")
    supplier_action_codes = manifest.get("supplier_action_codes")
    if (
        type(supplier_action_codes) is not list
        or supplier_action_codes.count("supplier.resolve") != 2
        or supplier_action_codes.count("supplier.update") != 1
    ):
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_SUPPLIER_AUDIT_INVALID")
    role_matrix_login_actor_ids = manifest.get("role_matrix_login_actor_ids")
    if type(role_matrix_login_actor_ids) is not list or set(role_matrix_login_actor_ids) != {
        str(item) for item in _ROLE_MATRIX_USER_IDS
    }:
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_ROLE_MATRIX_INCOMPLETE")

    bindings = _manifest_rows(manifest, "bindings")
    binding_targets = {
        (item.get("business_type"), item.get("contract_id"), item.get("invoice_id"))
        for item in bindings
    }
    if len(bindings) != 2 or binding_targets != {
        ("contract", contract_id, None),
        ("invoice", None, invoice_id),
    }:
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_BINDINGS_INVALID")

    relations = _manifest_rows(manifest, "relations")
    if len(relations) != 1 or (
        relations[0].get("contract_id"),
        relations[0].get("invoice_id"),
        relations[0].get("status"),
    ) != (contract_id, invoice_id, "confirmed_primary"):
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_RELATION_INVALID")

    tasks = _manifest_rows(manifest, "tasks")
    executions = _manifest_rows(manifest, "executions")
    reports = _manifest_rows(manifest, "reports")
    if len(tasks) != 1 or tasks[0].get("status") != "completed":
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_TASK_NOT_COMPLETED")
    task_id = tasks[0].get("id")
    task_items = tasks[0].get("items")
    if type(task_id) is not str or type(task_items) is not list:
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_TASK_INVALID")
    task_targets = {
        (item.get("item_type"), item.get("contract_id"), item.get("invoice_id"))
        for item in task_items
        if type(item) is dict
    }
    if len(task_items) != 2 or task_targets != {
        ("contract", contract_id, None),
        ("invoice", None, invoice_id),
    }:
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_TASK_ITEMS_INVALID")
    if len(executions) != 1 or (
        executions[0].get("task_id"),
        executions[0].get("status"),
    ) != (task_id, "completed"):
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_EXECUTION_NOT_COMPLETED")
    execution_id = executions[0].get("id")
    if type(execution_id) is not str or tasks[0].get("current_execution_id") != execution_id:
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_CURRENT_EXECUTION_INVALID")
    if len(reports) != 1 or (
        reports[0].get("execution_id"),
        reports[0].get("status"),
    ) != (execution_id, "ready"):
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_REPORT_NOT_READY")
    if (
        reports[0].get("pdf_stored") is not True
        or reports[0].get("xlsx_stored") is not True
        or type(reports[0].get("pdf_size_bytes")) is not int
        or cast(int, reports[0].get("pdf_size_bytes")) <= 0
        or type(reports[0].get("xlsx_size_bytes")) is not int
        or cast(int, reports[0].get("xlsx_size_bytes")) <= 0
    ):
        raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_ARTIFACTS_INVALID")


def _cleanup_file_gate_objects(
    factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    with factory() as session:
        files = tuple(
            session.scalars(
                select(FileRecord).where(
                    FileRecord.uploaded_by == USER_ID,
                    FileRecord.id != FILE_ID,
                )
            )
        )
    quarantine = MinioQuarantineAdapter(settings)
    runtime = MinioFileRuntimeAdapter(settings)
    cleanup_failed = False
    for file_record in files:
        try:
            quarantine.delete_quarantine(
                QuarantineObject(file_record.minio_bucket, file_record.minio_object_key)
            )
        except Exception:
            cleanup_failed = True
        if file_record.original_minio_object_key is not None:
            try:
                runtime.delete_original_compensation(file_record.original_minio_object_key)
            except Exception:
                cleanup_failed = True
    if cleanup_failed:
        raise RuntimeError("BROWSER_GATE_FILE_OBJECT_CLEANUP_FAILED")


def _cleanup_financial_loop_report_objects(
    factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    with factory() as session:
        reports = tuple(
            session.scalars(
                select(AuditReport).where(AuditReport.organization_id == ORGANIZATION_ID)
            )
        )
    storage = MinioReportStorageAdapter(settings, credential_scope="worker")
    cleanup_failed = False
    for report in reports:
        for locator in report_object_locators(
            organization_id=ORGANIZATION_ID,
            report_id=report.id,
            report_version=report.report_version,
            reports_bucket=storage.reports_bucket,
            exports_bucket=storage.exports_bucket,
        ):
            try:
                storage.delete_compensation(locator)
            except Exception:
                cleanup_failed = True
    if cleanup_failed:
        raise RuntimeError("BROWSER_GATE_REPORT_OBJECT_CLEANUP_FAILED")


def _clear_supplementary_browser_facts(engine: Engine) -> None:
    table_names = (
        "operation_logs",
        "idempotency_records",
        "async_job_steps",
        "outbox_events",
        "async_jobs",
        "user_corrections",
        "supplementary_agreement_changes",
        "document_content_exclusions",
        "document_blocks",
        "document_assets",
        "document_pages",
        "document_parse_versions",
        "file_primary_business_objects",
        "files",
        "supplementary_agreements",
        "token_sessions",
        "user_roles",
        "users",
    )
    role_matrix_actor_ids = tuple(sorted(_ROLE_MATRIX_USER_IDS, key=str))
    matrix_user_ids = tuple(item[0] for item in _ROLE_MATRIX_USERS)
    role_matrix_placeholders = ", ".join("%s" for _ in role_matrix_actor_ids)
    matrix_user_placeholders = ", ".join("%s" for _ in matrix_user_ids)
    with engine.begin() as connection:
        for table_name in table_names:
            connection.exec_driver_sql(f"ALTER TABLE {table_name} DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM idempotency_records WHERE resource_type = %s "
                "AND resource_id IN (%s, %s)",
                (
                    "supplementary_agreement",
                    AGREEMENT_ID,
                    _SUPPLEMENTARY_REJECT_AGREEMENT_ID,
                ),
            )
            connection.exec_driver_sql(
                "DELETE FROM user_corrections WHERE object_type = %s AND object_id IN (%s, %s)",
                (
                    "supplementary_agreement",
                    AGREEMENT_ID,
                    _SUPPLEMENTARY_REJECT_AGREEMENT_ID,
                ),
            )
            connection.exec_driver_sql(
                "DELETE FROM supplementary_agreement_changes "
                "WHERE supplementary_agreement_id IN (%s, %s)",
                (AGREEMENT_ID, _SUPPLEMENTARY_REJECT_AGREEMENT_ID),
            )
            connection.exec_driver_sql(
                "DELETE FROM operation_logs WHERE "
                "(resource_type = %s AND resource_id IN (%s, %s)) OR actor_id IN ("
                + role_matrix_placeholders
                + ")",
                (
                    "supplementary_agreement",
                    AGREEMENT_ID,
                    _SUPPLEMENTARY_REJECT_AGREEMENT_ID,
                    *role_matrix_actor_ids,
                ),
            )
            file_job_subquery = (
                "SELECT id FROM async_jobs WHERE resource_type = 'file' AND resource_id IN (%s, %s)"
            )
            connection.exec_driver_sql(
                "DELETE FROM async_job_steps WHERE job_id IN (" + file_job_subquery + ")",
                (_SUPPLEMENTARY_FILE_ID, _SUPPLEMENTARY_CONTRACT_FILE_ID),
            )
            connection.exec_driver_sql(
                "DELETE FROM outbox_events WHERE aggregate_type = 'async_job' "
                "AND aggregate_id IN (" + file_job_subquery + ")",
                (_SUPPLEMENTARY_FILE_ID, _SUPPLEMENTARY_CONTRACT_FILE_ID),
            )
            connection.exec_driver_sql(
                "DELETE FROM async_jobs WHERE resource_type = 'file' AND resource_id IN (%s, %s)",
                (_SUPPLEMENTARY_FILE_ID, _SUPPLEMENTARY_CONTRACT_FILE_ID),
            )
            parse_subquery = "SELECT id FROM document_parse_versions WHERE file_id = %s"
            connection.exec_driver_sql(
                "DELETE FROM document_content_exclusions WHERE parse_version_id IN ("
                + parse_subquery
                + ")",
                (_SUPPLEMENTARY_FILE_ID,),
            )
            connection.exec_driver_sql(
                "DELETE FROM document_blocks WHERE parse_version_id IN (" + parse_subquery + ")",
                (_SUPPLEMENTARY_FILE_ID,),
            )
            connection.exec_driver_sql(
                "DELETE FROM document_assets WHERE file_id = %s",
                (_SUPPLEMENTARY_FILE_ID,),
            )
            connection.exec_driver_sql(
                "DELETE FROM document_pages WHERE parse_version_id IN (" + parse_subquery + ")",
                (_SUPPLEMENTARY_FILE_ID,),
            )
            connection.exec_driver_sql(
                "DELETE FROM document_parse_versions WHERE file_id = %s",
                (_SUPPLEMENTARY_FILE_ID,),
            )
            connection.exec_driver_sql(
                "DELETE FROM file_primary_business_objects WHERE id IN (%s, %s)",
                (_SUPPLEMENTARY_BINDING_ID, _SUPPLEMENTARY_CONTRACT_BINDING_ID),
            )
            connection.exec_driver_sql(
                "DELETE FROM files WHERE id IN (%s, %s)",
                (_SUPPLEMENTARY_FILE_ID, _SUPPLEMENTARY_CONTRACT_FILE_ID),
            )
            connection.exec_driver_sql(
                "DELETE FROM supplementary_agreements WHERE id IN (%s, %s)",
                (AGREEMENT_ID, _SUPPLEMENTARY_REJECT_AGREEMENT_ID),
            )
            connection.exec_driver_sql(
                "DELETE FROM token_sessions WHERE user_id IN (" + role_matrix_placeholders + ")",
                role_matrix_actor_ids,
            )
            connection.exec_driver_sql(
                "DELETE FROM user_roles WHERE user_id IN (" + matrix_user_placeholders + ")",
                matrix_user_ids,
            )
            connection.exec_driver_sql(
                "DELETE FROM users WHERE id IN (" + matrix_user_placeholders + ")",
                matrix_user_ids,
            )
        finally:
            for table_name in reversed(table_names):
                connection.exec_driver_sql(f"ALTER TABLE {table_name} ENABLE TRIGGER USER")


def _stop_synthetic_clamd(
    server: _SyntheticClamdServer,
    thread: threading.Thread,
) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)
    if thread.is_alive():
        raise RuntimeError("BROWSER_GATE_SCANNER_SHUTDOWN_FAILED")


def _invoice_duplicate_manifest(
    factory: sessionmaker[Session],
    http_results: tuple[dict[str, object], ...],
) -> dict[str, object]:
    with factory() as session:
        source = session.get(Invoice, INVOICE_ID)
        candidate = session.get(Invoice, DUPLICATE_INVOICE_ID)
    if source is None or candidate is None:
        raise RuntimeError("BROWSER_GATE_INVOICE_DUPLICATE_SUBJECT_MISSING")
    return {
        "source": {
            "id": str(source.id),
            "invoice_code": source.invoice_code,
            "invoice_number": source.invoice_number,
            "seller_tax_no": source.seller_tax_no,
            "duplicate_status": source.duplicate_status,
            "status": source.status,
        },
        "candidate": {
            "id": str(candidate.id),
            "invoice_code": candidate.invoice_code,
            "invoice_number": candidate.invoice_number,
            "seller_tax_no": candidate.seller_tax_no,
            "duplicate_status": candidate.duplicate_status,
            "status": candidate.status,
        },
        "http_results": list(http_results),
    }


def _assert_invoice_duplicate_complete(manifest: dict[str, object]) -> None:
    source = manifest.get("source")
    candidate = manifest.get("candidate")
    http_results = manifest.get("http_results")
    if (
        type(source) is not dict
        or type(candidate) is not dict
        or type(http_results) is not list
        or any(type(item) is not dict for item in http_results)
    ):
        raise RuntimeError("BROWSER_GATE_INVOICE_DUPLICATE_MANIFEST_INVALID")
    if (
        source.get("id") != str(INVOICE_ID)
        or candidate.get("id") != str(DUPLICATE_INVOICE_ID)
        or source.get("status") == "voided"
        or candidate.get("status") == "voided"
        or source.get("duplicate_status") != "unique"
        or candidate.get("duplicate_status") != "suspected"
        or source.get("invoice_code") != candidate.get("invoice_code")
        or source.get("invoice_number") != candidate.get("invoice_number")
        or source.get("seller_tax_no") != candidate.get("seller_tax_no")
    ):
        raise RuntimeError("BROWSER_GATE_INVOICE_DUPLICATE_FACTS_INVALID")
    observed = {
        (item.get("method"), item.get("path"), item.get("status"))
        for item in http_results
        if type(item) is dict
    }
    expected = {
        (
            "GET",
            f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates",
            200,
        ),
        (
            "GET",
            f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates/{DUPLICATE_INVOICE_ID}",
            200,
        ),
    }
    if not expected.issubset(observed):
        raise RuntimeError("BROWSER_GATE_INVOICE_DUPLICATE_HTTP_INCOMPLETE")


def _document_correction_manifest(
    factory: sessionmaker[Session],
    evidence_block_id: UUID,
    http_results: tuple[dict[str, object], ...],
) -> dict[str, object]:
    with factory() as session:
        source_block = session.get(DocumentBlock, evidence_block_id)
        if source_block is None:
            raise RuntimeError("BROWSER_GATE_DOCUMENT_CORRECTION_SOURCE_MISSING")
        source = session.get(DocumentParseVersion, source_block.parse_version_id)
        corrections = tuple(
            session.scalars(
                select(DocumentBlockCorrection).where(
                    DocumentBlockCorrection.source_block_id == evidence_block_id
                )
            ).all()
        )
        correction = corrections[0] if len(corrections) == 1 else None
        result = (
            None
            if correction is None
            else session.get(DocumentParseVersion, correction.result_parse_version_id)
        )
        job = (
            None
            if result is None
            else session.scalar(
                select(AsyncJob).where(
                    AsyncJob.job_type == "manual_correction_snapshot",
                    AsyncJob.resource_id == result.id,
                )
            )
        )
        steps = (
            ()
            if job is None
            else tuple(
                session.scalars(
                    select(AsyncJobStep)
                    .where(AsyncJobStep.job_id == job.id)
                    .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                ).all()
            )
        )
        result_blocks = (
            ()
            if result is None
            else tuple(
                session.scalars(
                    select(DocumentBlock)
                    .where(DocumentBlock.parse_version_id == result.id)
                    .order_by(DocumentBlock.block_index)
                ).all()
            )
        )
        active_markdown_count = (
            0
            if result is None
            else session.scalar(
                select(func.count())
                .select_from(DocumentMarkdownVersion)
                .where(
                    DocumentMarkdownVersion.parse_version_id == result.id,
                    DocumentMarkdownVersion.status == "active",
                )
            )
        )
        outbox_count = (
            0
            if job is None
            else session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.aggregate_id == job.id,
                    OutboxEvent.status == "published",
                )
            )
        )
        action_codes = (
            []
            if result is None
            else list(
                session.scalars(
                    select(OperationLog.action_code)
                    .where(
                        OperationLog.resource_type == "document_parse_version",
                        OperationLog.resource_id == result.id,
                    )
                    .order_by(OperationLog.created_at, OperationLog.id)
                ).all()
            )
        )
    return {
        "evidence_block_id": str(evidence_block_id),
        "source": None
        if source is None
        else {
            "id": str(source.id),
            "status": source.status,
            "superseded_at_present": source.superseded_at is not None,
        },
        "correction": None
        if correction is None
        else {
            "id": str(correction.id),
            "source_block_id": str(correction.source_block_id),
            "result_parse_version_id": str(correction.result_parse_version_id),
            "field_name": correction.field_name,
            "after_value": correction.after_value_json,
            "reason": correction.reason,
        },
        "result": None
        if result is None
        else {
            "id": str(result.id),
            "status": result.status,
            "parent_version_id": str(result.parent_version_id),
            "activated_at_present": result.activated_at is not None,
            "block_texts": [block.text_content for block in result_blocks],
            "active_markdown_count": active_markdown_count,
        },
        "job": None
        if job is None
        else {
            "id": str(job.id),
            "status": job.status,
            "attempt_no": job.attempt_no,
            "max_attempts": job.max_attempts,
            "steps": [
                {
                    "attempt_no": step.attempt_no,
                    "step_code": step.step_code,
                    "status": step.status,
                    "error_code": step.error_code,
                }
                for step in steps
            ],
            "published_outbox_count": outbox_count,
        },
        "action_codes": action_codes,
        "http_results": list(http_results),
    }


def _assert_document_correction_complete(manifest: dict[str, object]) -> None:
    source = manifest.get("source")
    evidence_block_id = manifest.get("evidence_block_id")
    correction = manifest.get("correction")
    result = manifest.get("result")
    job = manifest.get("job")
    action_codes = manifest.get("action_codes")
    http_results = manifest.get("http_results")
    if any(type(item) is not dict for item in (source, correction, result, job)) or any(
        type(item) is not list for item in (action_codes, http_results)
    ):
        raise RuntimeError("BROWSER_GATE_DOCUMENT_CORRECTION_MANIFEST_INVALID")
    source = cast(dict[str, object], source)
    correction = cast(dict[str, object], correction)
    result = cast(dict[str, object], result)
    job = cast(dict[str, object], job)
    action_codes = cast(list[object], action_codes)
    http_results = cast(list[object], http_results)
    if (
        type(evidence_block_id) is not str
        or source.get("status") != "superseded"
        or source.get("superseded_at_present") is not True
        or correction.get("source_block_id") != evidence_block_id
        or correction.get("field_name") != "text_content"
        or correction.get("after_value") != _DOCUMENT_CORRECTION_TEXT
        or correction.get("reason") != _DOCUMENT_CORRECTION_REASON
        or result.get("status") != "active"
        or result.get("parent_version_id") != source.get("id")
        or result.get("activated_at_present") is not True
        or _DOCUMENT_CORRECTION_TEXT not in result.get("block_texts", [])
        or result.get("active_markdown_count") != 1
        or job.get("status") != "succeeded"
        or job.get("attempt_no") != 1
        or job.get("max_attempts") != 1
        or job.get("steps")
        != [
            {
                "attempt_no": 1,
                "step_code": "snapshot_rebuild",
                "status": "succeeded",
                "error_code": None,
            }
        ]
        or job.get("published_outbox_count") != 1
        or action_codes != ["document_block.correction_requested", "document_parse.activated"]
    ):
        raise RuntimeError("BROWSER_GATE_DOCUMENT_CORRECTION_FACTS_INVALID")
    observed = {
        (item.get("method"), item.get("path"), item.get("status"))
        for item in http_results
        if type(item) is dict
    }
    result_id = result.get("id")
    expected = {
        (
            "GET",
            f"/api/v1/files/{_SUPPLEMENTARY_FILE_ID}/document-correction-blocks",
            200,
        ),
        (
            "POST",
            f"/api/v1/document-blocks/{evidence_block_id}/correct",
            202,
        ),
        (
            "POST",
            f"/api/v1/document-parse-versions/{result_id}/activate",
            200,
        ),
    }
    if not expected.issubset(observed):
        raise RuntimeError("BROWSER_GATE_DOCUMENT_CORRECTION_HTTP_INCOMPLETE")


def _write_auth_key_files(
    private_key_file: Path,
    public_keyring_file: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    private_key_file.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_keyring_file.write_text(
        json.dumps({_AUTH_KID: public_pem.decode("ascii")}, separators=(",", ":")),
        encoding="utf-8",
    )


def _cleanup_gate_key_files(application: FastAPI) -> None:
    private_key_file: Path = application.state.browser_gate_private_key_file
    public_keyring_file: Path = application.state.browser_gate_public_keyring_file
    temporary_directory: tempfile.TemporaryDirectory[str] = (
        application.state.browser_gate_temporary_directory
    )
    try:
        private_key_file.unlink(missing_ok=True)
    finally:
        try:
            public_keyring_file.unlink(missing_ok=True)
        finally:
            temporary_directory.cleanup()


def build_browser_application() -> FastAPI:
    """Build the explicit local-only browser gate over disposable synthetic facts."""

    gate_token = os.environ.get("FINAUDIT_BROWSER_GATE")
    if gate_token not in {
        _GATE_TOKEN,
        _REPORT_GATE_TOKEN,
        _FILE_UPLOAD_GATE_TOKEN,
        _FINANCIAL_LOOP_GATE_TOKEN,
        _SUPPLEMENTARY_GATE_TOKEN,
        _INVOICE_DUPLICATE_GATE_TOKEN,
        _DOCUMENT_CORRECTION_GATE_TOKEN,
    }:
        raise RuntimeError("BROWSER_GATE_NOT_AUTHORIZED")
    report_gate = gate_token == _REPORT_GATE_TOKEN
    file_upload_gate = gate_token == _FILE_UPLOAD_GATE_TOKEN
    financial_loop_gate = gate_token == _FINANCIAL_LOOP_GATE_TOKEN
    supplementary_gate = gate_token == _SUPPLEMENTARY_GATE_TOKEN
    invoice_duplicate_gate = gate_token == _INVOICE_DUPLICATE_GATE_TOKEN
    document_correction_gate = gate_token == _DOCUMENT_CORRECTION_GATE_TOKEN
    worker_gate = file_upload_gate or financial_loop_gate or document_correction_gate

    raw_port = os.environ.get("FINAUDIT_BROWSER_PORT", "")
    if not raw_port.isascii() or not raw_port.isdigit():
        raise RuntimeError("BROWSER_GATE_PORT_INVALID")
    port = int(raw_port)
    if port < 1024 or port > 65535:
        raise RuntimeError("BROWSER_GATE_PORT_INVALID")

    expected_origin = f"http://127.0.0.1:{port}"
    configured_origin = canonicalize_http_origin(
        os.environ.get("FINAUDIT_BROWSER_PUBLIC_ORIGIN", "")
    )
    if configured_origin != expected_origin:
        raise RuntimeError("BROWSER_GATE_ORIGIN_INVALID")

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    index_file = frontend_dist / "index.html"
    assets_directory = frontend_dist / "assets"
    if not index_file.is_file() or not assets_directory.is_dir():
        raise RuntimeError("BROWSER_GATE_FRONTEND_BUILD_MISSING")

    database_url = read_safe_test_database_url()
    assert_disposable_database_marker(database_url)
    temporary_directory = tempfile.TemporaryDirectory(prefix="finaudit-browser-gate-")
    private_key_file = Path(temporary_directory.name) / "auth-private.pem"
    public_keyring_file = Path(temporary_directory.name) / "auth-public-keyring.json"
    contract_fixture_file = Path(temporary_directory.name) / "financial-loop-contract.docx"
    invoice_fixture_file = Path(temporary_directory.name) / "financial-loop-invoice.docx"
    clean_file_fixture = Path(temporary_directory.name) / "browser-clean.pdf"
    retry_file_fixture = Path(temporary_directory.name) / "browser-retry.pdf"
    if financial_loop_gate:
        contract_fixture_file.write_bytes(_financial_loop_contract_docx())
        invoice_fixture_file.write_bytes(_financial_loop_invoice_docx())
    if file_upload_gate:
        clean_file_fixture.write_bytes(_file_capability_pdf("Clean browser file"))
        retry_file_fixture.write_bytes(_file_capability_pdf("Retry browser file", fail_once=True))
    application: FastAPI | None = None
    try:
        settings_values = _runtime_settings(database_url).model_dump()
        settings_values.update(
            {
                "app_env": "local",
                "auth_jwt_active_kid": _AUTH_KID,
                "auth_jwt_private_key_file": str(private_key_file),
                "auth_jwt_public_keyring_file": str(public_keyring_file),
                "auth_public_origin": configured_origin,
            }
        )
        if report_gate or worker_gate:
            settings_values.update(_minio_settings())
        if worker_gate:
            settings_values.update(_file_worker_settings())
        settings = Settings.model_validate(settings_values)
        from app.bootstrap import create_app

        application = create_app(settings)
        application.state.browser_gate_private_key_file = private_key_file
        application.state.browser_gate_public_keyring_file = public_keyring_file
        application.state.browser_gate_temporary_directory = temporary_directory
        application.state.browser_gate_file_capabilities_accepted = False
        application.state.browser_gate_financial_loop_accepted = False
        application.state.browser_gate_supplementary_accepted = False
        application.state.browser_gate_supplementary_http_results = []
        application.state.browser_gate_invoice_duplicate_accepted = False
        application.state.browser_gate_invoice_duplicate_http_results = []
        application.state.browser_gate_document_correction_accepted = False
        application.state.browser_gate_document_correction_http_results = []
        if supplementary_gate:
            supplementary_path_prefix = f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/"

            @application.middleware("http")
            async def record_supplementary_writes(request: Request, call_next):  # type: ignore[no-untyped-def]
                response = await call_next(request)
                if (
                    request.method in {"PUT", "POST"}
                    and request.url.path.startswith(supplementary_path_prefix)
                    and request.url.path.endswith(("/changes", "/decision"))
                ):
                    results = application.state.browser_gate_supplementary_http_results
                    if not isinstance(results, list):
                        raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_HTTP_RESULTS_INVALID")
                    results.append(
                        {
                            "method": request.method,
                            "path": request.url.path,
                            "status": response.status_code,
                        }
                    )
                return response

        if invoice_duplicate_gate:
            duplicate_paths = {
                f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates",
                (f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates/{DUPLICATE_INVOICE_ID}"),
            }

            @application.middleware("http")
            async def record_invoice_duplicate_reads(  # type: ignore[no-untyped-def]
                request: Request,
                call_next,
            ):
                response = await call_next(request)
                if request.method == "GET" and request.url.path in duplicate_paths:
                    results = application.state.browser_gate_invoice_duplicate_http_results
                    if not isinstance(results, list):
                        raise RuntimeError("BROWSER_GATE_INVOICE_DUPLICATE_HTTP_RESULTS_INVALID")
                    results.append(
                        {
                            "method": request.method,
                            "path": request.url.path,
                            "status": response.status_code,
                        }
                    )
                return response

        if document_correction_gate:
            correction_prefixes = (
                f"/api/v1/files/{_SUPPLEMENTARY_FILE_ID}/document-correction-blocks",
                "/api/v1/document-blocks/",
                "/api/v1/document-parse-versions/",
            )

            @application.middleware("http")
            async def record_document_correction_requests(  # type: ignore[no-untyped-def]
                request: Request,
                call_next,
            ):
                response = await call_next(request)
                path = request.url.path
                if (
                    (request.method == "GET" and path == correction_prefixes[0])
                    or (
                        request.method == "POST"
                        and path.startswith(correction_prefixes[1])
                        and path.endswith("/correct")
                    )
                    or (
                        request.method == "POST"
                        and path.startswith(correction_prefixes[2])
                        and path.endswith("/activate")
                    )
                ):
                    results = application.state.browser_gate_document_correction_http_results
                    if not isinstance(results, list):
                        raise RuntimeError("BROWSER_GATE_DOCUMENT_CORRECTION_HTTP_RESULTS_INVALID")
                    results.append(
                        {
                            "method": request.method,
                            "path": path,
                            "status": response.status_code,
                        }
                    )
                return response

        original_lifespan = application.router.lifespan_context

        @asynccontextmanager
        async def browser_lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
            seed_engine: Engine | None = None
            seeded = False
            report_storage: MinioReportStorageAdapter | None = None
            report_locators: tuple[ReportObjectLocator, ReportObjectLocator] | None = None
            file_factory: sessionmaker[Session] | None = None
            try:
                _write_auth_key_files(private_key_file, public_keyring_file)
                seed_engine = create_application_engine(settings)
                factory = create_session_factory(seed_engine)
                file_factory = factory
                event.listen(factory, "after_begin", _bound_transaction_waits)
                _seed_subject_and_financial_facts(factory)
                seeded = True
                if invoice_duplicate_gate:
                    app.state.browser_gate_invoice_duplicate_factory = factory
                    print(f"BROWSER_GATE_INVOICE_ID={INVOICE_ID}", flush=True)
                    print(
                        f"BROWSER_GATE_DUPLICATE_INVOICE_ID={DUPLICATE_INVOICE_ID}",
                        flush=True,
                    )
                    print("BROWSER_GATE_INVOICE_DUPLICATE_RUNTIME=READY", flush=True)
                if supplementary_gate or document_correction_gate:
                    _seed_role_matrix_users(factory)
                    evidence_block_id = _prepare_supplementary_browser_facts(
                        factory,
                        activate_parse=document_correction_gate,
                    )
                    if supplementary_gate:
                        app.state.browser_gate_supplementary_factory = factory
                        app.state.browser_gate_supplementary_evidence_block_id = evidence_block_id
                        print(f"BROWSER_GATE_CONTRACT_ID={CONTRACT_ID}", flush=True)
                        print(f"BROWSER_GATE_AGREEMENT_ID={AGREEMENT_ID}", flush=True)
                        print(
                            f"BROWSER_GATE_REJECT_AGREEMENT_ID={_SUPPLEMENTARY_REJECT_AGREEMENT_ID}",
                            flush=True,
                        )
                        print(
                            f"BROWSER_GATE_SUPPLEMENTARY_EVIDENCE_BLOCK_ID={evidence_block_id}",
                            flush=True,
                        )
                    else:
                        app.state.browser_gate_document_correction_factory = factory
                        app.state.browser_gate_document_correction_evidence_block_id = (
                            evidence_block_id
                        )
                        print(
                            f"BROWSER_GATE_DOCUMENT_CORRECTION_FILE_ID={_SUPPLEMENTARY_FILE_ID}",
                            flush=True,
                        )
                        print(
                            f"BROWSER_GATE_DOCUMENT_CORRECTION_BLOCK_ID={evidence_block_id}",
                            flush=True,
                        )
                if report_gate:
                    _prepare_report_financial_facts(seed_engine)
                    report_id, report_storage, report_locators = _seed_ready_report(
                        factory,
                        settings,
                    )
                    app.state.browser_gate_report_id = report_id
                    print(f"BROWSER_GATE_REPORT_ID={report_id}", flush=True)
                if financial_loop_gate:
                    _prepare_report_financial_facts(seed_engine)
                    _grant_financial_loop_permissions(factory)
                    _seed_role_matrix_users(factory)
                    with factory.begin() as session:
                        publish_builtin_catalog(
                            session,
                            application_release=settings.app_version,
                            change_reason="publish disposable financial loop browser catalog",
                        )
                if app.dependency_overrides or any(
                    hasattr(app.state, name)
                    for name in (
                        "auth_service",
                        "contract_query_service",
                        "contract_primary_invoice_query_service",
                        "invoice_query_service",
                        "invoice_primary_contract_query_service",
                        "supplementary_agreement_query_service",
                        "supplementary_agreement_management_service",
                        "user_query_service",
                        "report_management_service",
                        "file_intake_service",
                        "file_query_service",
                        "supplier_management_service",
                    )
                ):
                    raise RuntimeError("BROWSER_GATE_BOOTSTRAP_STATE_PREPOPULATED")
                async with original_lifespan(app):
                    expected_services: list[tuple[str, type[object]]] = [
                        ("auth_service", AuthService),
                        ("contract_query_service", ContractQueryService),
                        (
                            "contract_primary_invoice_query_service",
                            ContractPrimaryInvoiceQueryService,
                        ),
                        ("invoice_query_service", InvoiceQueryService),
                        (
                            "invoice_primary_contract_query_service",
                            InvoicePrimaryContractQueryService,
                        ),
                        (
                            "supplementary_agreement_query_service",
                            SupplementaryAgreementQueryService,
                        ),
                        ("user_query_service", UserQueryService),
                    ]
                    if supplementary_gate:
                        expected_services.append(
                            (
                                "supplementary_agreement_management_service",
                                SupplementaryAgreementManagementService,
                            )
                        )
                    if document_correction_gate:
                        expected_services.append(
                            ("document_correction_service", DocumentCorrectionService)
                        )
                    if report_gate or financial_loop_gate:
                        expected_services.append(
                            ("report_management_service", ReportManagementService)
                        )
                    if financial_loop_gate:
                        expected_services.append(
                            ("supplier_management_service", SupplierManagementService)
                        )
                    if worker_gate:
                        expected_services.extend(
                            [
                                ("file_intake_service", FileIntakeService),
                                ("file_query_service", FileQueryService),
                                ("file_management_service", FileManagementService),
                            ]
                        )
                    if app.dependency_overrides or any(
                        not isinstance(getattr(app.state, name, None), service_type)
                        for name, service_type in expected_services
                    ):
                        raise RuntimeError("BROWSER_GATE_BOOTSTRAP_WIRING_INVALID")
                    with ExitStack() as runtime_stack:
                        if worker_gate:
                            scanner = _SyntheticClamdServer(
                                ("127.0.0.1", settings.scanner_port),
                                _SyntheticClamdHandler,
                            )
                            scanner_thread = threading.Thread(
                                target=scanner.serve_forever,
                                name="finaudit-browser-synthetic-clamd",
                                daemon=True,
                            )
                            scanner_thread.start()
                            runtime_stack.callback(
                                _stop_synthetic_clamd,
                                scanner,
                                scanner_thread,
                            )
                            worker_application = create_celery_app(settings)
                            worker_application.conf.worker_hijack_root_logger = False
                            runtime_stack.enter_context(
                                start_worker(
                                    worker_application,
                                    pool="solo",
                                    concurrency=1,
                                    perform_ping_check=False,
                                    queues=(
                                        [settings.celery_queue_document]
                                        if file_upload_gate
                                        else [
                                            settings.celery_queue_document,
                                            settings.celery_queue_extraction,
                                            settings.celery_queue_audit,
                                            settings.celery_queue_report,
                                        ]
                                    ),
                                    hostname=(
                                        "browser-file-worker@localhost"
                                        if file_upload_gate
                                        else "browser-financial-loop-worker@localhost"
                                    ),
                                    shutdown_timeout=20,
                                )
                            )
                            dispatcher = _DispatcherLoop(create_dispatcher_runtime(settings))
                            dispatcher.start()
                            runtime_stack.callback(dispatcher.close)
                            app.state.browser_gate_file_factory = factory
                            app.state.browser_gate_dispatcher = dispatcher
                            runtime_ready = (
                                "BROWSER_GATE_FINANCIAL_LOOP_RUNTIME=READY"
                                if financial_loop_gate
                                else (
                                    "BROWSER_GATE_DOCUMENT_CORRECTION_RUNTIME=READY"
                                    if document_correction_gate
                                    else "BROWSER_GATE_FILE_RUNTIME=READY"
                                )
                            )
                            print(runtime_ready, flush=True)
                            if file_upload_gate:
                                print(
                                    f"BROWSER_GATE_FILE_CLEAN_FIXTURE={clean_file_fixture}",
                                    flush=True,
                                )
                                print(
                                    f"BROWSER_GATE_FILE_RETRY_FIXTURE={retry_file_fixture}",
                                    flush=True,
                                )
                            if financial_loop_gate:
                                print(
                                    f"BROWSER_GATE_CONTRACT_FIXTURE={contract_fixture_file}",
                                    flush=True,
                                )
                                print(
                                    f"BROWSER_GATE_INVOICE_FIXTURE={invoice_fixture_file}",
                                    flush=True,
                                )
                        yield
            finally:
                try:
                    if seed_engine is not None:
                        try:
                            if seeded:
                                if (
                                    file_upload_gate or financial_loop_gate
                                ) and file_factory is not None:
                                    _cleanup_file_gate_objects(file_factory, settings)
                                if financial_loop_gate and file_factory is not None:
                                    _cleanup_financial_loop_report_objects(file_factory, settings)
                                if report_storage is not None and report_locators is not None:
                                    for locator in report_locators:
                                        report_storage.delete_compensation(locator)
                                if report_gate:
                                    _clear_report_facts(seed_engine)
                                if supplementary_gate:
                                    _clear_supplementary_browser_facts(seed_engine)
                                if not worker_gate:
                                    _clear_owned_test_facts(seed_engine)
                        finally:
                            seed_engine.dispose()
                finally:
                    _cleanup_gate_key_files(app)

        application.router.lifespan_context = browser_lifespan

        application.mount(
            "/assets",
            StaticFiles(directory=assets_directory),
            name="browser-gate-assets",
        )

        @application.get("/__finaudit_test__/report-manifest", include_in_schema=False)
        async def report_manifest() -> dict[str, str]:
            report_id = getattr(application.state, "browser_gate_report_id", None)
            if not report_gate or not isinstance(report_id, UUID):
                raise HTTPException(status_code=404, detail="Not Found")
            return {"report_id": str(report_id)}

        @application.get("/__finaudit_test__/file-manifest", include_in_schema=False)
        async def file_manifest() -> dict[str, object]:
            factory = getattr(application.state, "browser_gate_file_factory", None)
            dispatcher = getattr(application.state, "browser_gate_dispatcher", None)
            if (
                not file_upload_gate
                or not isinstance(factory, sessionmaker)
                or not isinstance(dispatcher, _DispatcherLoop)
            ):
                raise HTTPException(status_code=404, detail="Not Found")
            return _file_gate_manifest(factory, dispatcher)

        @application.get("/__finaudit_test__/financial-loop-manifest", include_in_schema=False)
        async def financial_loop_manifest() -> dict[str, object]:
            factory = getattr(application.state, "browser_gate_file_factory", None)
            dispatcher = getattr(application.state, "browser_gate_dispatcher", None)
            if (
                not financial_loop_gate
                or not isinstance(factory, sessionmaker)
                or not isinstance(dispatcher, _DispatcherLoop)
            ):
                raise HTTPException(status_code=404, detail="Not Found")
            return _financial_loop_manifest(factory, dispatcher)

        @application.get("/__finaudit_test__/supplementary-manifest", include_in_schema=False)
        async def supplementary_manifest() -> dict[str, object]:
            factory = getattr(
                application.state,
                "browser_gate_supplementary_factory",
                None,
            )
            evidence_block_id = getattr(
                application.state,
                "browser_gate_supplementary_evidence_block_id",
                None,
            )
            write_http_results = getattr(
                application.state,
                "browser_gate_supplementary_http_results",
                None,
            )
            if (
                not supplementary_gate
                or not isinstance(factory, sessionmaker)
                or not isinstance(evidence_block_id, UUID)
                or not isinstance(write_http_results, list)
                or not all(type(item) is dict for item in write_http_results)
            ):
                raise HTTPException(status_code=404, detail="Not Found")
            return _supplementary_manifest(
                factory,
                evidence_block_id,
                tuple(cast(dict[str, object], item) for item in write_http_results),
            )

        @application.get("/__finaudit_test__/invoice-duplicate-manifest", include_in_schema=False)
        async def invoice_duplicate_manifest() -> dict[str, object]:
            factory = getattr(
                application.state,
                "browser_gate_invoice_duplicate_factory",
                None,
            )
            http_results = getattr(
                application.state,
                "browser_gate_invoice_duplicate_http_results",
                None,
            )
            if (
                not invoice_duplicate_gate
                or not isinstance(factory, sessionmaker)
                or not isinstance(http_results, list)
                or not all(type(item) is dict for item in http_results)
            ):
                raise HTTPException(status_code=404, detail="Not Found")
            return _invoice_duplicate_manifest(
                factory,
                tuple(cast(dict[str, object], item) for item in http_results),
            )

        @application.get("/__finaudit_test__/document-correction-manifest", include_in_schema=False)
        async def document_correction_manifest() -> dict[str, object]:
            factory = getattr(
                application.state,
                "browser_gate_document_correction_factory",
                None,
            )
            evidence_block_id = getattr(
                application.state,
                "browser_gate_document_correction_evidence_block_id",
                None,
            )
            http_results = getattr(
                application.state,
                "browser_gate_document_correction_http_results",
                None,
            )
            if (
                not document_correction_gate
                or not isinstance(factory, sessionmaker)
                or not isinstance(evidence_block_id, UUID)
                or not isinstance(http_results, list)
                or not all(type(item) is dict for item in http_results)
            ):
                raise HTTPException(status_code=404, detail="Not Found")
            return _document_correction_manifest(
                factory,
                evidence_block_id,
                tuple(cast(dict[str, object], item) for item in http_results),
            )

        @application.post("/__finaudit_test__/shutdown", include_in_schema=False)
        async def shutdown_gate(request: Request) -> dict[str, str]:
            if request.headers.get("X-FinAudit-Browser-Gate") != _SHUTDOWN_TOKEN:
                raise HTTPException(status_code=404, detail="Not Found")
            server = getattr(application.state, "browser_gate_server", None)
            if not isinstance(server, uvicorn.Server):
                raise HTTPException(status_code=503, detail="Not Ready")
            server.should_exit = True
            return {"status": "stopping"}

        @application.post(
            "/__finaudit_test__/file-capabilities-complete",
            include_in_schema=False,
        )
        async def complete_file_capabilities(request: Request) -> dict[str, str]:
            if (
                not file_upload_gate
                or request.headers.get("X-FinAudit-Browser-Gate")
                != _FILE_CAPABILITIES_COMPLETE_TOKEN
            ):
                raise HTTPException(status_code=404, detail="Not Found")
            factory = getattr(application.state, "browser_gate_file_factory", None)
            dispatcher = getattr(application.state, "browser_gate_dispatcher", None)
            server = getattr(application.state, "browser_gate_server", None)
            if (
                not isinstance(factory, sessionmaker)
                or not isinstance(dispatcher, _DispatcherLoop)
                or not isinstance(server, uvicorn.Server)
            ):
                raise HTTPException(status_code=503, detail="Not Ready")
            try:
                _assert_file_capabilities_complete(_file_gate_manifest(factory, dispatcher))
            except RuntimeError as error:
                raise HTTPException(status_code=409, detail=str(error)) from None
            application.state.browser_gate_file_capabilities_accepted = True
            server.should_exit = True
            return {"status": "accepted"}

        @application.post(
            "/__finaudit_test__/financial-loop-complete",
            include_in_schema=False,
        )
        async def complete_financial_loop(request: Request) -> dict[str, str]:
            if (
                not financial_loop_gate
                or request.headers.get("X-FinAudit-Browser-Gate") != _FINANCIAL_LOOP_COMPLETE_TOKEN
            ):
                raise HTTPException(status_code=404, detail="Not Found")
            factory = getattr(application.state, "browser_gate_file_factory", None)
            dispatcher = getattr(application.state, "browser_gate_dispatcher", None)
            server = getattr(application.state, "browser_gate_server", None)
            if (
                not isinstance(factory, sessionmaker)
                or not isinstance(dispatcher, _DispatcherLoop)
                or not isinstance(server, uvicorn.Server)
            ):
                raise HTTPException(status_code=503, detail="Not Ready")
            try:
                _assert_financial_loop_complete(_financial_loop_manifest(factory, dispatcher))
            except RuntimeError as error:
                raise HTTPException(status_code=409, detail=str(error)) from None
            application.state.browser_gate_financial_loop_accepted = True
            server.should_exit = True
            return {"status": "accepted"}

        @application.post(
            "/__finaudit_test__/supplementary-complete",
            include_in_schema=False,
        )
        async def complete_supplementary(request: Request) -> dict[str, str]:
            factory = getattr(
                application.state,
                "browser_gate_supplementary_factory",
                None,
            )
            evidence_block_id = getattr(
                application.state,
                "browser_gate_supplementary_evidence_block_id",
                None,
            )
            write_http_results = getattr(
                application.state,
                "browser_gate_supplementary_http_results",
                None,
            )
            server = getattr(application.state, "browser_gate_server", None)
            if (
                not supplementary_gate
                or request.headers.get("X-FinAudit-Browser-Gate") != _SUPPLEMENTARY_COMPLETE_TOKEN
            ):
                raise HTTPException(status_code=404, detail="Not Found")
            if (
                not isinstance(factory, sessionmaker)
                or not isinstance(evidence_block_id, UUID)
                or not isinstance(server, uvicorn.Server)
                or not isinstance(write_http_results, list)
                or not all(type(item) is dict for item in write_http_results)
            ):
                raise HTTPException(status_code=503, detail="Not Ready")
            try:
                _assert_supplementary_complete(
                    _supplementary_manifest(
                        factory,
                        evidence_block_id,
                        tuple(cast(dict[str, object], item) for item in write_http_results),
                    )
                )
            except RuntimeError as error:
                raise HTTPException(status_code=409, detail=str(error)) from None
            application.state.browser_gate_supplementary_accepted = True
            server.should_exit = True
            return {"status": "accepted"}

        @application.post(
            "/__finaudit_test__/invoice-duplicate-complete",
            include_in_schema=False,
        )
        async def complete_invoice_duplicate(request: Request) -> dict[str, str]:
            factory = getattr(
                application.state,
                "browser_gate_invoice_duplicate_factory",
                None,
            )
            http_results = getattr(
                application.state,
                "browser_gate_invoice_duplicate_http_results",
                None,
            )
            server = getattr(application.state, "browser_gate_server", None)
            if (
                not invoice_duplicate_gate
                or request.headers.get("X-FinAudit-Browser-Gate")
                != _INVOICE_DUPLICATE_COMPLETE_TOKEN
            ):
                raise HTTPException(status_code=404, detail="Not Found")
            if (
                not isinstance(factory, sessionmaker)
                or not isinstance(http_results, list)
                or not all(type(item) is dict for item in http_results)
                or not isinstance(server, uvicorn.Server)
            ):
                raise HTTPException(status_code=503, detail="Not Ready")
            try:
                _assert_invoice_duplicate_complete(
                    _invoice_duplicate_manifest(
                        factory,
                        tuple(cast(dict[str, object], item) for item in http_results),
                    )
                )
            except RuntimeError as error:
                raise HTTPException(status_code=409, detail=str(error)) from None
            application.state.browser_gate_invoice_duplicate_accepted = True
            server.should_exit = True
            return {"status": "accepted"}

        @application.post(
            "/__finaudit_test__/document-correction-complete",
            include_in_schema=False,
        )
        async def complete_document_correction(request: Request) -> dict[str, str]:
            factory = getattr(
                application.state,
                "browser_gate_document_correction_factory",
                None,
            )
            evidence_block_id = getattr(
                application.state,
                "browser_gate_document_correction_evidence_block_id",
                None,
            )
            http_results = getattr(
                application.state,
                "browser_gate_document_correction_http_results",
                None,
            )
            server = getattr(application.state, "browser_gate_server", None)
            if (
                not document_correction_gate
                or request.headers.get("X-FinAudit-Browser-Gate")
                != _DOCUMENT_CORRECTION_COMPLETE_TOKEN
            ):
                raise HTTPException(status_code=404, detail="Not Found")
            if (
                not isinstance(factory, sessionmaker)
                or not isinstance(evidence_block_id, UUID)
                or not isinstance(http_results, list)
                or not all(type(item) is dict for item in http_results)
                or not isinstance(server, uvicorn.Server)
            ):
                raise HTTPException(status_code=503, detail="Not Ready")
            try:
                _assert_document_correction_complete(
                    _document_correction_manifest(
                        factory,
                        evidence_block_id,
                        tuple(cast(dict[str, object], item) for item in http_results),
                    )
                )
            except RuntimeError as error:
                raise HTTPException(status_code=409, detail=str(error)) from None
            application.state.browser_gate_document_correction_accepted = True
            server.should_exit = True
            return {"status": "accepted"}

        @application.get("/{spa_path:path}", include_in_schema=False)
        async def serve_spa(spa_path: str) -> FileResponse:
            if spa_path == "api" or spa_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(index_file)

        return application
    except BaseException:
        if application is None:
            try:
                private_key_file.unlink(missing_ok=True)
            finally:
                try:
                    public_keyring_file.unlink(missing_ok=True)
                finally:
                    temporary_directory.cleanup()
        else:
            _cleanup_gate_key_files(application)
        raise


def run_browser_gate() -> None:
    application = build_browser_application()
    try:
        server = uvicorn.Server(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=int(os.environ["FINAUDIT_BROWSER_PORT"]),
                log_level="warning",
                access_log=False,
            )
        )
        application.state.browser_gate_server = server
        server.run()
        if (
            os.environ.get("FINAUDIT_BROWSER_GATE") == _FINANCIAL_LOOP_GATE_TOKEN
            and application.state.browser_gate_financial_loop_accepted is not True
        ):
            raise RuntimeError("BROWSER_GATE_FINANCIAL_LOOP_NOT_ACCEPTED")
        if (
            os.environ.get("FINAUDIT_BROWSER_GATE") == _FILE_UPLOAD_GATE_TOKEN
            and application.state.browser_gate_file_capabilities_accepted is not True
        ):
            raise RuntimeError("BROWSER_GATE_FILE_CAPABILITIES_NOT_ACCEPTED")
        if (
            os.environ.get("FINAUDIT_BROWSER_GATE") == _SUPPLEMENTARY_GATE_TOKEN
            and application.state.browser_gate_supplementary_accepted is not True
        ):
            raise RuntimeError("BROWSER_GATE_SUPPLEMENTARY_NOT_ACCEPTED")
        if (
            os.environ.get("FINAUDIT_BROWSER_GATE") == _INVOICE_DUPLICATE_GATE_TOKEN
            and application.state.browser_gate_invoice_duplicate_accepted is not True
        ):
            raise RuntimeError("BROWSER_GATE_INVOICE_DUPLICATE_NOT_ACCEPTED")
        if (
            os.environ.get("FINAUDIT_BROWSER_GATE") == _DOCUMENT_CORRECTION_GATE_TOKEN
            and application.state.browser_gate_document_correction_accepted is not True
        ):
            raise RuntimeError("BROWSER_GATE_DOCUMENT_CORRECTION_NOT_ACCEPTED")
    finally:
        _cleanup_gate_key_files(application)


if __name__ == "__main__":
    run_browser_gate()
