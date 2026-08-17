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
from sqlalchemy import select

from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.models.documents import FilePrimaryBusinessObject, FileRecord
from app.models.financial import Contract, ContractField
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, AsyncJobStep

_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_STATE_PATH = Path("/state/status.json")
_POLL_INTERVAL_SECONDS = 0.5
_RUNNING_TIMEOUT_SECONDS = 60
_RECOVERY_TIMEOUT_SECONDS = 180
_CONTRACT_TIMEOUT_SECONDS = 180
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_CONTRACT_NAME = "Worker 崩溃恢复合同"
_CONTRACT_FIELD_CODES = frozenset(
    {
        "contract_no",
        "name",
        "party_a_name",
        "party_a_tax_no",
        "party_b_name",
        "party_b_tax_no",
        "amount",
        "currency",
        "signed_date",
        "effective_date",
        "expiry_date",
        "payment_method",
        "payment_terms",
    }
)


class CrashRecoveryError(RuntimeError):
    pass


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise CrashRecoveryError(f"{name}_REQUIRED")
    return value


def _canonical_uuid(value: object, reason: str) -> UUID:
    if type(value) is not str:
        raise CrashRecoveryError(reason)
    try:
        parsed = UUID(value)
    except ValueError:
        raise CrashRecoveryError(reason) from None
    if str(parsed) != value:
        raise CrashRecoveryError(reason)
    return parsed


def _state_path() -> Path:
    raw_path = _required_environment("FINAUDIT_CRASH_STATE_PATH")
    path = Path(raw_path)
    if path != _STATE_PATH or not path.is_absolute() or path.is_symlink():
        raise CrashRecoveryError("STATE_PATH_INVALID")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise CrashRecoveryError("STATE_DIRECTORY_INVALID")
    return path


def _write_state(
    path: Path,
    *,
    phase: str,
    file_id: UUID,
    job_id: UUID,
) -> None:
    if phase not in {"running", "complete"}:
        raise CrashRecoveryError("STATE_PHASE_INVALID")
    temporary = path.with_suffix(".tmp")
    if temporary.exists() or temporary.is_symlink():
        raise CrashRecoveryError("STATE_TEMPORARY_PATH_OCCUPIED")
    temporary.write_text(
        json.dumps(
            {
                "schema_version": "finaudit-local-worker-crash-v1",
                "phase": phase,
                "file_id": str(file_id),
                "job_id": str(job_id),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _contract_no(run_id: str) -> str:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise CrashRecoveryError("RUN_ID_INVALID")
    return f"CRASH-{run_id[:12].upper()}"


def _crash_contract_docx(run_id: str) -> bytes:
    contract_no = _contract_no(run_id)
    lines = (
        f"合同编号: {contract_no}",
        f"合同名称: {_CONTRACT_NAME}",
        "甲方名称: 恢复测试采购方",
        "甲方税号: 91310000CRASHBUY01",
        "乙方名称: 恢复测试供应商",
        "乙方税号: 91310000CRASHSELL1",
        "合同金额: 100000.00 CNY",
        "签订日期: 2026-08-15",
        "生效日期: 2026-08-15",
        "到期日期: 2027-08-14",
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
    payload = output.getvalue()
    if not payload.startswith(b"PK\x03\x04"):
        raise CrashRecoveryError("DOCX_FIXTURE_INVALID")
    return payload


def _client_profile() -> tuple[str, str, str, str, Path]:
    base_url = _required_environment("FINAUDIT_SMOKE_BASE_URL")
    origin = _required_environment("AUTH_PUBLIC_ORIGIN")
    username = _required_environment("BOOTSTRAP_ADMIN_USERNAME")
    run_id = _required_environment("FINAUDIT_CRASH_RUN_ID")
    if (
        base_url != "https://frontend:8443"
        or not origin.startswith("https://localhost:")
        or _RUN_ID_PATTERN.fullmatch(run_id) is None
    ):
        raise CrashRecoveryError("CLIENT_PROFILE_INVALID")
    return base_url, origin, username, run_id, _state_path()


def run_client() -> None:
    base_url, origin, username, run_id, state_path = _client_profile()
    password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    payload = _crash_contract_docx(run_id)
    contract_no = _contract_no(run_id)
    host = origin.removeprefix("https://")

    with httpx.Client(
        base_url=base_url,
        verify=False,
        timeout=httpx.Timeout(15),
        headers={"Origin": origin, "Host": host},
    ) as client:
        admin_token = _login(client, username, password)
        uploader_username = f"crash-{run_id[:12]}"
        uploader_password = f"{password}-crash-{run_id[:12]}"
        created_user = client.post(
            "/api/v1/users",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Idempotency-Key": f"local-worker-crash-user.{run_id}",
            },
            json={
                "username": uploader_username,
                "display_name": "本地 Worker 强杀恢复账号",
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
                "Idempotency-Key": f"local-worker-crash-file.{run_id}",
            },
            data={
                "intended_business_type": "contract",
                "auto_process_requested": "true",
            },
            files={
                "file": (
                    f"local-worker-crash-{run_id[:12]}.docx",
                    payload,
                    _DOCX_MIME,
                ),
            },
        )
        accepted_data = _require_envelope(accepted, 202)
        file_id = _canonical_uuid(accepted_data.get("file_id"), "FILE_ID_INVALID")
        job_id = _canonical_uuid(accepted_data.get("job_id"), "JOB_ID_INVALID")

        running_deadline = time.monotonic() + _RUNNING_TIMEOUT_SECONDS
        running_observed = False
        recovery_deadline: float | None = None
        final: dict[str, object] | None = None
        while True:
            response = client.get(f"/api/v1/files/{file_id}", headers=authorization)
            data = _require_envelope(response, 200)
            if data.get("job_id") != str(job_id):
                raise CrashRecoveryError("JOB_ID_DRIFT")
            status = data.get("job_status")
            if status == "running" and not running_observed:
                _write_state(state_path, phase="running", file_id=file_id, job_id=job_id)
                running_observed = True
                recovery_deadline = time.monotonic() + _RECOVERY_TIMEOUT_SECONDS
            if status in {"succeeded", "failed", "cancelled"}:
                final = data
                break
            now = time.monotonic()
            if not running_observed and now >= running_deadline:
                raise CrashRecoveryError("RUNNING_STATE_TIMEOUT")
            if recovery_deadline is not None and now >= recovery_deadline:
                raise CrashRecoveryError("RECOVERY_STATE_TIMEOUT")
            time.sleep(_POLL_INTERVAL_SECONDS)

        if not running_observed or final is None:
            raise CrashRecoveryError("RUNNING_STATE_NOT_OBSERVED")
        if (
            final.get("job_status") != "succeeded"
            or final.get("status") != "stored"
            or final.get("security_scan_status") != "clean"
        ):
            raise CrashRecoveryError("RECOVERY_RESULT_INVALID")

        preview = client.get(f"/api/v1/files/{file_id}/preview", headers=authorization)
        if (
            preview.status_code != 200
            or preview.content != payload
            or preview.headers.get("etag") != f'"{hashlib.sha256(payload).hexdigest()}"'
            or preview.headers.get("x-file-status") != "stored"
        ):
            raise CrashRecoveryError("RECOVERY_PREVIEW_INVALID")

        contract_deadline = time.monotonic() + _CONTRACT_TIMEOUT_SECONDS
        contract: dict[str, object] | None = None
        while time.monotonic() < contract_deadline:
            page = _require_envelope(
                client.get("/api/v1/contracts?page_size=100", headers=authorization),
                200,
            )
            items = page.get("items")
            if not isinstance(items, list):
                raise CrashRecoveryError("CONTRACT_LIST_INVALID")
            matches = [
                item
                for item in items
                if isinstance(item, dict) and item.get("contract_no") == contract_no
            ]
            if len(matches) > 1:
                raise CrashRecoveryError("CONTRACT_EXTRACTION_DUPLICATED")
            if matches:
                contract = matches[0]
                break
            time.sleep(_POLL_INTERVAL_SECONDS)
        if contract is None:
            raise CrashRecoveryError("CONTRACT_EXTRACTION_TIMEOUT")
        contract_id = _canonical_uuid(contract.get("id"), "CONTRACT_ID_INVALID")
        detail = _require_envelope(
            client.get(f"/api/v1/contracts/{contract_id}", headers=authorization),
            200,
        )
        if detail != {
            "id": str(contract_id),
            "contract_no": contract_no,
            "name": _CONTRACT_NAME,
            "party_a_name": "恢复测试采购方",
            "party_a_tax_no": "91310000CRASHBUY01",
            "party_b_name": "恢复测试供应商",
            "party_b_tax_no": "91310000CRASHSELL1",
            "amount": "100000.00",
            "currency": "CNY",
            "signed_date": "2026-08-15",
            "effective_date": "2026-08-15",
            "expiry_date": "2027-08-14",
            "payment_method": "银行转账",
            "payment_terms": "验收后十个工作日内付款",
            "confirmation_status": "unconfirmed",
            "status": "draft",
            "row_version": "1",
        }:
            raise CrashRecoveryError("CONTRACT_EXTRACTION_RESULT_INVALID")
        _write_state(state_path, phase="complete", file_id=file_id, job_id=job_id)


def run_database_verification() -> None:
    run_id = _required_environment("FINAUDIT_CRASH_RUN_ID")
    contract_no = _contract_no(run_id)
    file_id = _canonical_uuid(
        _required_environment("FINAUDIT_CRASH_FILE_ID"),
        "DATABASE_FILE_ID_INVALID",
    )
    job_id = _canonical_uuid(
        _required_environment("FINAUDIT_CRASH_JOB_ID"),
        "DATABASE_JOB_ID_INVALID",
    )
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            file_record = session.get(FileRecord, file_id)
            jobs = session.scalars(
                select(AsyncJob).where(
                    AsyncJob.resource_type == "file",
                    AsyncJob.resource_id == file_id,
                )
            ).all()
            job = session.get(AsyncJob, job_id)
            file_steps = session.scalars(
                select(AsyncJobStep)
                .where(AsyncJobStep.job_id == job_id)
                .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
            ).all()
            extraction_jobs = tuple(
                candidate for candidate in jobs if candidate.job_type == "contract_extract"
            )
            extraction_job = extraction_jobs[0] if len(extraction_jobs) == 1 else None
            extraction_steps = (
                []
                if extraction_job is None
                else session.scalars(
                    select(AsyncJobStep)
                    .where(AsyncJobStep.job_id == extraction_job.id)
                    .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                ).all()
            )
            binding = session.scalar(
                select(FilePrimaryBusinessObject).where(
                    FilePrimaryBusinessObject.file_id == file_id,
                    FilePrimaryBusinessObject.business_type == "contract",
                )
            )
            contract = (
                None
                if binding is None or binding.contract_id is None
                else session.get(Contract, binding.contract_id)
            )
            fields = (
                []
                if contract is None
                else session.scalars(
                    select(ContractField).where(ContractField.contract_id == contract.id)
                ).all()
            )
            extraction_logs = (
                []
                if contract is None
                else session.scalars(
                    select(OperationLog).where(
                        OperationLog.resource_type == "contract",
                        OperationLog.resource_id == contract.id,
                        OperationLog.action_code == "contracts.extraction_created",
                    )
                ).all()
            )
    finally:
        engine.dispose()

    if (
        file_record is None
        or file_record.status != "stored"
        or file_record.security_scan_status != "clean"
        or len(jobs) != 2
        or job is None
        or job.job_type != "file_process"
        or job.resource_id != file_id
        or job.status != "succeeded"
        or job.attempt_no != 2
        or extraction_job is None
        or extraction_job.resource_id != file_id
        or extraction_job.status != "succeeded"
        or extraction_job.attempt_no != 1
    ):
        raise CrashRecoveryError("DATABASE_JOB_STATE_INVALID")
    observed_file_steps = [
        (step.attempt_no, step.step_code, step.status, step.error_code) for step in file_steps
    ]
    if observed_file_steps != [
        (1, "scan", "failed", "LEASE_EXPIRED"),
        (2, "scan", "succeeded", None),
        (2, "parse", "succeeded", None),
        (2, "markdown", "succeeded", None),
    ]:
        raise CrashRecoveryError("DATABASE_STEP_HISTORY_INVALID")
    observed_extraction_steps = [
        (step.attempt_no, step.step_code, step.status, step.error_code) for step in extraction_steps
    ]
    if observed_extraction_steps != [(1, "extract", "succeeded", None)]:
        raise CrashRecoveryError("DATABASE_EXTRACTION_STEP_HISTORY_INVALID")
    if (
        binding is None
        or contract is None
        or contract.contract_no != contract_no
        or contract.name != _CONTRACT_NAME
        or contract.party_a_name != "恢复测试采购方"
        or contract.party_a_tax_no != "91310000CRASHBUY01"
        or contract.party_b_name != "恢复测试供应商"
        or contract.party_b_tax_no != "91310000CRASHSELL1"
        or contract.amount != Decimal("100000.00")
        or contract.currency != "CNY"
        or contract.signed_date != date(2026, 8, 15)
        or contract.effective_date != date(2026, 8, 15)
        or contract.expiry_date != date(2027, 8, 14)
        or contract.payment_method != "银行转账"
        or contract.payment_terms != "验收后十个工作日内付款"
        or contract.confirmation_status != "unconfirmed"
        or contract.status != "draft"
        or contract.row_version != 1
        or {field.field_code for field in fields} != _CONTRACT_FIELD_CODES
        or any(field.evidence_file_id != file_id for field in fields)
        or len(extraction_logs) != 1
    ):
        raise CrashRecoveryError("DATABASE_CONTRACT_EXTRACTION_INVALID")
    print("LOCAL_WORKER_FILE_PROCESS_DATABASE_GATE=PASS")
    print("LOCAL_WORKER_CONTRACT_EXTRACTION_DATABASE_GATE=PASS")


def main() -> int:
    try:
        if sys.argv == [sys.argv[0], "client"]:
            run_client()
            print("LOCAL_WORKER_CRASH_CLIENT_GATE=PASS")
        elif sys.argv == [sys.argv[0], "database"]:
            run_database_verification()
            print("LOCAL_WORKER_CRASH_DATABASE_GATE=PASS")
        else:
            raise CrashRecoveryError("ARGUMENTS_INVALID")
    except (CrashRecoveryError, SmokeError) as error:
        print("LOCAL_WORKER_CRASH_RECOVERY=FAIL")
        print(f"LOCAL_WORKER_CRASH_REASON={error}")
        return 1
    except Exception:
        print("LOCAL_WORKER_CRASH_RECOVERY=FAIL")
        print("LOCAL_WORKER_CRASH_REASON=UNEXPECTED_FAILURE")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
