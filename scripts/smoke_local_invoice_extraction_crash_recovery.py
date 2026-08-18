from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
from smoke_local_file_upload import (
    SmokeError,
    _login,
    _read_password,
    _require_envelope,
)
from smoke_local_worker_crash_recovery import (
    _DOCX_MIME,
    _POLL_INTERVAL_SECONDS,
    CrashRecoveryError,
    _canonical_uuid,
    _required_environment,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.models.documents import FilePrimaryBusinessObject, FileRecord
from app.models.financial import Invoice, InvoiceItem
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, AsyncJobStep
from app.services.invoice_facts import parse_field_evidence, parse_item_evidence

_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_STATE_PATH = Path("/state/status.json")
_STATE_SCHEMA_VERSION = "finaudit-local-invoice-extract-crash-v1"
_FILE_TIMEOUT_SECONDS = 180
_RUNNING_TIMEOUT_SECONDS = 90
_RECOVERY_TIMEOUT_SECONDS = 180
_INVOICE_FIELD_CODES = frozenset(
    {
        "invoice_code",
        "invoice_number",
        "invoice_type",
        "is_red_invoice",
        "invoice_date",
        "buyer_name",
        "buyer_tax_no",
        "seller_name",
        "seller_tax_no",
        "amount_excluding_tax",
        "tax_amount",
        "total_amount",
        "currency",
    }
)
_ITEM_NAME = "崩溃恢复咨询服务"


class InvoiceCrashRecoveryError(RuntimeError):
    pass


def _validate_run_id(run_id: str) -> None:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise InvoiceCrashRecoveryError("RUN_ID_INVALID")


def _lock_application_name(run_id: str) -> str:
    _validate_run_id(run_id)
    identity = f"finaudit-invoice-crash-{run_id}"
    if len(identity.encode("ascii")) > 63:
        raise InvoiceCrashRecoveryError("LOCK_IDENTITY_INVALID")
    return identity


def _invoice_identity(run_id: str) -> tuple[str, str]:
    _validate_run_id(run_id)
    return f"CRASH{run_id[:12].upper()}", run_id[12:24].upper()


def _expected_field_quotes(run_id: str) -> dict[str, str]:
    invoice_code, invoice_number = _invoice_identity(run_id)
    return {
        "invoice_code": f"发票代码: {invoice_code}",
        "invoice_number": f"发票号码: {invoice_number}",
        "invoice_type": "发票类型: 增值税专用发票",
        "is_red_invoice": "是否红字: 否",
        "invoice_date": "开票日期: 2026-08-16",
        "buyer_name": "购买方名称: 恢复测试采购方",
        "buyer_tax_no": "购买方税号: 91310000CRASHBUY02",
        "seller_name": "销售方名称: 恢复测试供应商",
        "seller_tax_no": "销售方税号: 91310000CRASHSELL2",
        "amount_excluding_tax": "不含税金额: 100.00",
        "tax_amount": "税额: 13.00",
        "total_amount": "价税合计: 113.00",
        "currency": "币种: CNY",
    }


def _invoice_docx(run_id: str) -> bytes:
    lines = tuple(_expected_field_quotes(run_id).values()) + (f"明细: {_ITEM_NAME}",)
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


def _state_payload(
    *,
    run_id: str,
    file_id: UUID,
    file_job_id: UUID,
    file_sha256: str,
) -> str:
    _validate_run_id(run_id)
    if _SHA256_PATTERN.fullmatch(file_sha256) is None:
        raise InvoiceCrashRecoveryError("FILE_SHA256_INVALID")
    return json.dumps(
        {
            "schema_version": _STATE_SCHEMA_VERSION,
            "phase": "file_ready",
            "run_id": run_id,
            "file_id": str(file_id),
            "file_job_id": str(file_job_id),
            "file_sha256": file_sha256,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _state_path() -> Path:
    raw_path = _required_environment("FINAUDIT_CRASH_STATE_PATH")
    path = Path(raw_path)
    if path != _STATE_PATH or not path.is_absolute() or path.is_symlink():
        raise InvoiceCrashRecoveryError("STATE_PATH_INVALID")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise InvoiceCrashRecoveryError("STATE_DIRECTORY_INVALID")
    return path


def _write_file_ready_state(
    *,
    run_id: str,
    file_id: UUID,
    file_job_id: UUID,
    file_sha256: str,
) -> None:
    path = _state_path()
    temporary = path.with_suffix(".tmp")
    if temporary.exists() or temporary.is_symlink():
        raise InvoiceCrashRecoveryError("STATE_TEMPORARY_PATH_OCCUPIED")
    temporary.write_text(
        _state_payload(
            run_id=run_id,
            file_id=file_id,
            file_job_id=file_job_id,
            file_sha256=file_sha256,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _client_profile() -> tuple[str, str, str, str]:
    base_url = _required_environment("FINAUDIT_SMOKE_BASE_URL")
    origin = _required_environment("AUTH_PUBLIC_ORIGIN")
    username = _required_environment("BOOTSTRAP_ADMIN_USERNAME")
    run_id = _required_environment("FINAUDIT_CRASH_RUN_ID")
    _validate_run_id(run_id)
    if base_url != "http://frontend:8443" or not origin.startswith("http://localhost:"):
        raise InvoiceCrashRecoveryError("CLIENT_PROFILE_INVALID")
    return base_url, origin, username, run_id


def _uploader_credentials(admin_password: str, run_id: str) -> tuple[str, str]:
    _validate_run_id(run_id)
    suffix = run_id[:12]
    return f"invoice-crash-{suffix}", f"{admin_password}-invoice-crash-{suffix}"


def _client(base_url: str, origin: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        verify=False,
        timeout=httpx.Timeout(15),
        headers={"Origin": origin, "Host": origin.removeprefix("http://")},
    )


def _wait_for_file(
    client: httpx.Client,
    *,
    access_token: str,
    file_id: UUID,
    file_job_id: UUID,
) -> dict[str, object]:
    deadline = time.monotonic() + _FILE_TIMEOUT_SECONDS
    authorization = {"Authorization": f"Bearer {access_token}"}
    while time.monotonic() < deadline:
        data = _require_envelope(
            client.get(f"/api/v1/files/{file_id}", headers=authorization),
            200,
        )
        if data.get("job_id") != str(file_job_id):
            raise InvoiceCrashRecoveryError("FILE_JOB_ID_DRIFT")
        if data.get("job_status") in {"succeeded", "failed", "cancelled"}:
            return data
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise InvoiceCrashRecoveryError("FILE_PROCESS_TIMEOUT")


def run_prepare_client() -> None:
    base_url, origin, admin_username, run_id = _client_profile()
    admin_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    uploader_username, uploader_password = _uploader_credentials(admin_password, run_id)
    payload = _invoice_docx(run_id)

    with _client(base_url, origin) as client:
        admin_token = _login(client, admin_username, admin_password)
        created_user = client.post(
            "/api/v1/users",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Idempotency-Key": f"local-invoice-crash-user.{run_id}",
            },
            json={
                "username": uploader_username,
                "display_name": "本地发票提取强杀恢复账号",
                "initial_password": uploader_password,
                "fixed_roles": ["finance_reviewer"],
            },
        )
        _require_envelope(created_user, 201)
        access_token = _login(client, uploader_username, uploader_password)
        authorization = {"Authorization": f"Bearer {access_token}"}
        accepted = client.post(
            "/api/v1/files",
            headers={
                **authorization,
                "Idempotency-Key": f"local-invoice-crash-file.{run_id}",
            },
            data={
                "intended_business_type": "invoice",
                "auto_process_requested": "true",
            },
            files={
                "file": (
                    f"local-invoice-crash-{run_id[:12]}.docx",
                    payload,
                    _DOCX_MIME,
                )
            },
        )
        accepted_data = _require_envelope(accepted, 202)
        file_id = _canonical_uuid(accepted_data.get("file_id"), "FILE_ID_INVALID")
        file_job_id = _canonical_uuid(
            accepted_data.get("job_id"), "FILE_JOB_ID_INVALID"
        )
        final = _wait_for_file(
            client,
            access_token=access_token,
            file_id=file_id,
            file_job_id=file_job_id,
        )
        if (
            final.get("job_status") != "succeeded"
            or final.get("status") != "stored"
            or final.get("security_scan_status") != "clean"
        ):
            raise InvoiceCrashRecoveryError("FILE_PROCESS_RESULT_INVALID")
        _write_file_ready_state(
            run_id=run_id,
            file_id=file_id,
            file_job_id=file_job_id,
            file_sha256=hashlib.sha256(payload).hexdigest(),
        )


def _database_profile() -> tuple[str, UUID, UUID | None]:
    run_id = _required_environment("FINAUDIT_CRASH_RUN_ID")
    _validate_run_id(run_id)
    file_id = _canonical_uuid(
        _required_environment("FINAUDIT_CRASH_FILE_ID"),
        "DATABASE_FILE_ID_INVALID",
    )
    raw_extraction_job_id = os.environ.get("FINAUDIT_CRASH_EXTRACTION_JOB_ID")
    extraction_job_id = (
        None
        if raw_extraction_job_id is None
        else _canonical_uuid(
            raw_extraction_job_id, "DATABASE_EXTRACTION_JOB_ID_INVALID"
        )
    )
    return run_id, file_id, extraction_job_id


def run_wait_for_extraction() -> None:
    _run_id, file_id, _extraction_job_id = _database_profile()
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        deadline = time.monotonic() + _RUNNING_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with factory() as session:
                jobs = tuple(
                    session.scalars(
                        select(AsyncJob).where(
                            AsyncJob.resource_type == "file",
                            AsyncJob.resource_id == file_id,
                            AsyncJob.job_type == "invoice_extract",
                        )
                    ).all()
                )
                if len(jobs) > 1:
                    raise InvoiceCrashRecoveryError("EXTRACTION_JOB_DUPLICATED")
                if jobs:
                    job = jobs[0]
                    steps = tuple(
                        session.scalars(
                            select(AsyncJobStep)
                            .where(AsyncJobStep.job_id == job.id)
                            .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                        ).all()
                    )
                    binding_count = session.scalar(
                        select(func.count())
                        .select_from(FilePrimaryBusinessObject)
                        .where(FilePrimaryBusinessObject.file_id == file_id)
                    )
                    log_count = session.scalar(
                        select(func.count())
                        .select_from(OperationLog)
                        .where(
                            OperationLog.trace_id == job.trace_id,
                            OperationLog.action_code == "invoices.extraction_created",
                        )
                    )
                    if job.status in {"succeeded", "failed", "cancelled"}:
                        raise InvoiceCrashRecoveryError(
                            "EXTRACTION_FINISHED_BEFORE_CRASH"
                        )
                    if (
                        job.status == "running"
                        and job.attempt_no == 1
                        and [
                            (step.attempt_no, step.step_code, step.status)
                            for step in steps
                        ]
                        == [(1, "extract", "running")]
                        and binding_count == 0
                        and log_count == 0
                    ):
                        print(f"LOCAL_INVOICE_EXTRACT_RUNNING_JOB_ID={job.id}")
                        return
            time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        engine.dispose()
    raise InvoiceCrashRecoveryError("EXTRACTION_RUNNING_TIMEOUT")


def _load_job_cluster(
    session: Session,
    file_id: UUID,
) -> tuple[FileRecord | None, tuple[AsyncJob, ...]]:
    file_record = session.get(FileRecord, file_id)
    jobs = tuple(
        session.scalars(
            select(AsyncJob)
            .where(AsyncJob.resource_type == "file", AsyncJob.resource_id == file_id)
            .order_by(AsyncJob.created_at, AsyncJob.id)
        ).all()
    )
    return file_record, jobs


def run_before_recovery_verification() -> None:
    run_id, file_id, extraction_job_id = _database_profile()
    if extraction_job_id is None:
        raise InvoiceCrashRecoveryError("DATABASE_EXTRACTION_JOB_ID_REQUIRED")
    invoice_code, invoice_number = _invoice_identity(run_id)
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            file_record, jobs = _load_job_cluster(session, file_id)
            file_jobs = tuple(job for job in jobs if job.job_type == "file_process")
            extraction_jobs = tuple(
                job for job in jobs if job.job_type == "invoice_extract"
            )
            extraction_job = extraction_jobs[0] if len(extraction_jobs) == 1 else None
            extraction_steps = (
                ()
                if extraction_job is None
                else tuple(
                    session.scalars(
                        select(AsyncJobStep).where(
                            AsyncJobStep.job_id == extraction_job.id
                        )
                    ).all()
                )
            )
            invoice_count = (
                None
                if file_record is None
                else session.scalar(
                    select(func.count())
                    .select_from(Invoice)
                    .where(
                        Invoice.organization_id == file_record.organization_id,
                        Invoice.invoice_code == invoice_code,
                        Invoice.invoice_number == invoice_number,
                    )
                )
            )
            item_count = (
                None
                if file_record is None
                else session.scalar(
                    select(func.count())
                    .select_from(InvoiceItem)
                    .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                    .where(
                        Invoice.organization_id == file_record.organization_id,
                        Invoice.invoice_code == invoice_code,
                        Invoice.invoice_number == invoice_number,
                    )
                )
            )
            binding_count = session.scalar(
                select(func.count())
                .select_from(FilePrimaryBusinessObject)
                .where(FilePrimaryBusinessObject.file_id == file_id)
            )
            log_count = (
                None
                if extraction_job is None
                else session.scalar(
                    select(func.count())
                    .select_from(OperationLog)
                    .where(
                        OperationLog.trace_id == extraction_job.trace_id,
                        OperationLog.action_code == "invoices.extraction_created",
                    )
                )
            )
    finally:
        engine.dispose()
    if (
        file_record is None
        or file_record.status != "stored"
        or file_record.security_scan_status != "clean"
        or file_record.intended_business_type != "invoice"
        or not file_record.auto_process_requested
        or len(file_jobs) != 1
        or file_jobs[0].status != "succeeded"
        or file_jobs[0].attempt_no != 1
        or extraction_job is None
        or extraction_job.id != extraction_job_id
        or extraction_job.status != "running"
        or extraction_job.attempt_no != 1
        or [(step.attempt_no, step.step_code, step.status) for step in extraction_steps]
        != [(1, "extract", "running")]
        or invoice_count != 0
        or item_count != 0
        or binding_count != 0
        or log_count != 0
    ):
        raise InvoiceCrashRecoveryError("BEFORE_RECOVERY_DATABASE_STATE_INVALID")
    print("LOCAL_INVOICE_EXTRACT_ZERO_FACTS_BEFORE_RECOVERY_GATE=PASS")


def _expected_invoice_detail(
    invoice_id: UUID,
    item_id: UUID,
    run_id: str,
) -> dict[str, object]:
    invoice_code, invoice_number = _invoice_identity(run_id)
    return {
        "id": str(invoice_id),
        "invoice_code": invoice_code,
        "invoice_number": invoice_number,
        "invoice_type": "增值税专用发票",
        "is_red_invoice": False,
        "invoice_date": "2026-08-16",
        "buyer_name": "恢复测试采购方",
        "buyer_tax_no": "91310000CRASHBUY02",
        "seller_name": "恢复测试供应商",
        "seller_tax_no": "91310000CRASHSELL2",
        "amount_excluding_tax": "100.00",
        "tax_amount": "13.00",
        "total_amount": "113.00",
        "currency": "CNY",
        "confirmation_status": "unconfirmed",
        "duplicate_status": "unique",
        "status": "draft",
        "row_version": "1",
        "items": [
            {
                "id": str(item_id),
                "line_no": 1,
                "item_name": _ITEM_NAME,
                "specification": None,
                "unit": None,
                "quantity": None,
                "unit_price": None,
                "amount_excluding_tax": None,
                "tax_rate": None,
                "tax_amount": None,
                "total_amount": None,
                "row_version": "1",
            }
        ],
    }


def run_verify_client() -> None:
    base_url, origin, _admin_username, run_id = _client_profile()
    file_id = _canonical_uuid(
        _required_environment("FINAUDIT_CRASH_FILE_ID"),
        "CLIENT_FILE_ID_INVALID",
    )
    expected_sha256 = _required_environment("FINAUDIT_CRASH_FILE_SHA256")
    if _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise InvoiceCrashRecoveryError("CLIENT_FILE_SHA256_INVALID")
    admin_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    uploader_username, uploader_password = _uploader_credentials(admin_password, run_id)
    invoice_code, invoice_number = _invoice_identity(run_id)
    with _client(base_url, origin) as client:
        access_token = _login(client, uploader_username, uploader_password)
        authorization = {"Authorization": f"Bearer {access_token}"}
        deadline = time.monotonic() + _RECOVERY_TIMEOUT_SECONDS
        invoice: dict[str, object] | None = None
        while time.monotonic() < deadline:
            page = _require_envelope(
                client.get("/api/v1/invoices?page_size=100", headers=authorization),
                200,
            )
            items = page.get("items")
            if not isinstance(items, list):
                raise InvoiceCrashRecoveryError("INVOICE_LIST_INVALID")
            matches = [
                item
                for item in items
                if isinstance(item, dict)
                and item.get("invoice_code") == invoice_code
                and item.get("invoice_number") == invoice_number
            ]
            if len(matches) > 1:
                raise InvoiceCrashRecoveryError("INVOICE_EXTRACTION_DUPLICATED")
            if matches:
                invoice = matches[0]
                break
            time.sleep(_POLL_INTERVAL_SECONDS)
        if invoice is None:
            raise InvoiceCrashRecoveryError("INVOICE_EXTRACTION_RECOVERY_TIMEOUT")
        invoice_id = _canonical_uuid(invoice.get("id"), "INVOICE_ID_INVALID")
        detail = _require_envelope(
            client.get(f"/api/v1/invoices/{invoice_id}", headers=authorization),
            200,
        )
        detail_items = detail.get("items")
        if not isinstance(detail_items, list) or len(detail_items) != 1:
            raise InvoiceCrashRecoveryError("INVOICE_ITEMS_INVALID")
        item = detail_items[0]
        if not isinstance(item, dict):
            raise InvoiceCrashRecoveryError("INVOICE_ITEMS_INVALID")
        item_id = _canonical_uuid(item.get("id"), "INVOICE_ITEM_ID_INVALID")
        if detail != _expected_invoice_detail(invoice_id, item_id, run_id):
            raise InvoiceCrashRecoveryError("INVOICE_EXTRACTION_RESULT_INVALID")

        evidence = _require_envelope(
            client.get(
                f"/api/v1/invoices/{invoice_id}/evidence", headers=authorization
            ),
            200,
        )
        field_evidence = evidence.get("field_evidence")
        item_evidence = evidence.get("item_evidence")
        if not isinstance(field_evidence, list) or not isinstance(item_evidence, dict):
            raise InvoiceCrashRecoveryError("INVOICE_EVIDENCE_INVALID")
        field_quotes: dict[str, object] = {}
        for field in field_evidence:
            if not isinstance(field, dict) or not isinstance(
                field.get("evidence"), dict
            ):
                raise InvoiceCrashRecoveryError("INVOICE_EVIDENCE_INVALID")
            field_code = field.get("field_code")
            if not isinstance(field_code, str) or field_code in field_quotes:
                raise InvoiceCrashRecoveryError("INVOICE_EVIDENCE_INVALID")
            field_quotes[field_code] = field["evidence"].get("quote_text")
        line_evidence = item_evidence.get("1")
        if (
            evidence.get("invoice_id") != str(invoice_id)
            or evidence.get("row_version") != "1"
            or field_quotes != _expected_field_quotes(run_id)
            or set(item_evidence) != {"1"}
            or not isinstance(line_evidence, list)
            or len(line_evidence) != 1
            or not isinstance(line_evidence[0], dict)
            or line_evidence[0].get("quote_text") != f"明细: {_ITEM_NAME}"
        ):
            raise InvoiceCrashRecoveryError("INVOICE_EVIDENCE_INVALID")

        preview = client.get(f"/api/v1/files/{file_id}/preview", headers=authorization)
        if (
            preview.status_code != 200
            or hashlib.sha256(preview.content).hexdigest() != expected_sha256
            or preview.headers.get("etag") != f'"{expected_sha256}"'
            or preview.headers.get("x-file-status") != "stored"
        ):
            raise InvoiceCrashRecoveryError("FILE_PREVIEW_INVALID")


def run_final_database_verification() -> None:
    run_id, file_id, extraction_job_id = _database_profile()
    if extraction_job_id is None:
        raise InvoiceCrashRecoveryError("DATABASE_EXTRACTION_JOB_ID_REQUIRED")
    invoice_code, invoice_number = _invoice_identity(run_id)
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            file_record, jobs = _load_job_cluster(session, file_id)
            file_jobs = tuple(job for job in jobs if job.job_type == "file_process")
            extraction_jobs = tuple(
                job for job in jobs if job.job_type == "invoice_extract"
            )
            file_job = file_jobs[0] if len(file_jobs) == 1 else None
            extraction_job = extraction_jobs[0] if len(extraction_jobs) == 1 else None
            file_steps = (
                ()
                if file_job is None
                else tuple(
                    session.scalars(
                        select(AsyncJobStep)
                        .where(AsyncJobStep.job_id == file_job.id)
                        .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                    ).all()
                )
            )
            extraction_steps = (
                ()
                if extraction_job is None
                else tuple(
                    session.scalars(
                        select(AsyncJobStep)
                        .where(AsyncJobStep.job_id == extraction_job.id)
                        .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                    ).all()
                )
            )
            invoices = (
                ()
                if file_record is None
                else tuple(
                    session.scalars(
                        select(Invoice).where(
                            Invoice.organization_id == file_record.organization_id,
                            Invoice.invoice_code == invoice_code,
                            Invoice.invoice_number == invoice_number,
                        )
                    ).all()
                )
            )
            invoice = invoices[0] if len(invoices) == 1 else None
            bindings = tuple(
                session.scalars(
                    select(FilePrimaryBusinessObject).where(
                        FilePrimaryBusinessObject.file_id == file_id,
                        FilePrimaryBusinessObject.business_type == "invoice",
                    )
                ).all()
            )
            items = (
                ()
                if invoice is None
                else tuple(
                    session.scalars(
                        select(InvoiceItem)
                        .where(InvoiceItem.invoice_id == invoice.id)
                        .order_by(InvoiceItem.line_no, InvoiceItem.id)
                    ).all()
                )
            )
            extraction_logs = (
                ()
                if invoice is None
                else tuple(
                    session.scalars(
                        select(OperationLog).where(
                            OperationLog.resource_type == "invoice",
                            OperationLog.resource_id == invoice.id,
                            OperationLog.action_code == "invoices.extraction_created",
                        )
                    ).all()
                )
            )
            field_evidence = (
                ()
                if invoice is None
                else parse_field_evidence(invoice.field_evidence_json)
            )
            item_evidence = (
                () if len(items) != 1 else parse_item_evidence(items[0].evidence_json)
            )
            parse_version_id = (
                None
                if extraction_job is None
                else _canonical_uuid(
                    extraction_job.input_json.get("parse_version_id"),
                    "FINAL_PARSE_VERSION_ID_INVALID",
                )
            )
    finally:
        engine.dispose()
    if (
        file_record is None
        or file_record.status != "stored"
        or file_record.security_scan_status != "clean"
        or file_record.intended_business_type != "invoice"
        or not file_record.auto_process_requested
        or len(jobs) != 2
        or file_job is None
        or file_job.status != "succeeded"
        or file_job.attempt_no != 1
        or extraction_job is None
        or extraction_job.id != extraction_job_id
        or extraction_job.status != "succeeded"
        or extraction_job.attempt_no != 2
    ):
        raise InvoiceCrashRecoveryError("FINAL_DATABASE_JOB_STATE_INVALID")
    if [
        (step.attempt_no, step.step_code, step.status, step.error_code)
        for step in file_steps
    ] != [
        (1, "scan", "succeeded", None),
        (1, "parse", "succeeded", None),
        (1, "markdown", "succeeded", None),
    ]:
        raise InvoiceCrashRecoveryError("FINAL_FILE_STEP_HISTORY_INVALID")
    if [
        (step.attempt_no, step.step_code, step.status, step.error_code)
        for step in extraction_steps
    ] != [
        (1, "extract", "failed", "LEASE_EXPIRED"),
        (2, "extract", "succeeded", None),
    ]:
        raise InvoiceCrashRecoveryError("FINAL_EXTRACTION_STEP_HISTORY_INVALID")
    binding = bindings[0] if len(bindings) == 1 else None
    item = items[0] if len(items) == 1 else None
    expected_quotes = _expected_field_quotes(run_id)
    actual_quotes = {
        evidence.field_code: evidence.evidence.quote_text for evidence in field_evidence
    }
    if (
        invoice is None
        or binding is None
        or binding.invoice_id != invoice.id
        or binding.contract_id is not None
        or invoice.invoice_code != invoice_code
        or invoice.invoice_number != invoice_number
        or invoice.invoice_type != "增值税专用发票"
        or invoice.is_red_invoice is not False
        or invoice.invoice_date != date(2026, 8, 16)
        or invoice.buyer_name != "恢复测试采购方"
        or invoice.buyer_tax_no != "91310000CRASHBUY02"
        or invoice.seller_name != "恢复测试供应商"
        or invoice.seller_tax_no != "91310000CRASHSELL2"
        or invoice.amount_excluding_tax != Decimal("100.00")
        or invoice.tax_amount != Decimal("13.00")
        or invoice.total_amount != Decimal("113.00")
        or invoice.currency != "CNY"
        or invoice.confirmation_status != "unconfirmed"
        or invoice.duplicate_status != "unique"
        or invoice.status != "draft"
        or invoice.row_version != 1
        or _SHA256_PATTERN.fullmatch(invoice.critical_fact_hash) is None
        or item is None
        or item.line_no != 1
        or item.item_name != _ITEM_NAME
        or any(
            value is not None
            for value in (
                item.specification,
                item.unit,
                item.quantity,
                item.unit_price,
                item.amount_excluding_tax,
                item.tax_rate,
                item.tax_amount,
                item.total_amount,
            )
        )
        or item.row_version != 1
        or len(field_evidence) != len(_INVOICE_FIELD_CODES)
        or {evidence.field_code for evidence in field_evidence} != _INVOICE_FIELD_CODES
        or actual_quotes != expected_quotes
        or parse_version_id is None
        or any(
            evidence.evidence.parse_version_id != parse_version_id
            for evidence in field_evidence
        )
        or len({evidence.evidence.block_id for evidence in field_evidence})
        != len(field_evidence)
        or len(item_evidence) != 1
        or item_evidence[0].parse_version_id != parse_version_id
        or item_evidence[0].quote_text != f"明细: {_ITEM_NAME}"
        or len(extraction_logs) != 1
        or extraction_logs[0].trace_id != extraction_job.trace_id
    ):
        raise InvoiceCrashRecoveryError("FINAL_INVOICE_FACTS_INVALID")
    print("LOCAL_INVOICE_EXTRACT_ATTEMPT_HISTORY_DATABASE_GATE=PASS")
    print("LOCAL_INVOICE_EXTRACT_UNIQUE_FACTS_DATABASE_GATE=PASS")


def main() -> int:
    try:
        if sys.argv == [sys.argv[0], "prepare"]:
            run_prepare_client()
            print("LOCAL_INVOICE_EXTRACT_CRASH_PREPARE_GATE=PASS")
        elif sys.argv == [sys.argv[0], "wait-running"]:
            run_wait_for_extraction()
            print("LOCAL_INVOICE_EXTRACT_RUNNING_GATE=PASS")
        elif sys.argv == [sys.argv[0], "before-recovery"]:
            run_before_recovery_verification()
        elif sys.argv == [sys.argv[0], "verify-client"]:
            run_verify_client()
            print("LOCAL_INVOICE_EXTRACT_CRASH_CLIENT_GATE=PASS")
        elif sys.argv == [sys.argv[0], "database"]:
            run_final_database_verification()
            print("LOCAL_INVOICE_EXTRACT_CRASH_DATABASE_GATE=PASS")
        else:
            raise InvoiceCrashRecoveryError("ARGUMENTS_INVALID")
    except (InvoiceCrashRecoveryError, CrashRecoveryError, SmokeError) as error:
        print("LOCAL_INVOICE_EXTRACT_CRASH_RECOVERY=FAIL")
        print(f"LOCAL_INVOICE_EXTRACT_CRASH_REASON={error}")
        return 1
    except Exception as error:
        print("LOCAL_INVOICE_EXTRACT_CRASH_RECOVERY=FAIL")
        print(
            f"LOCAL_INVOICE_EXTRACT_CRASH_REASON=UNEXPECTED_{type(error).__name__.upper()}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
