from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
from smoke_local_file_upload import SmokeError, _login, _read_password, _require_envelope
from smoke_local_worker_crash_recovery import (
    _CONTRACT_FIELD_CODES,
    _CONTRACT_NAME,
    _DOCX_MIME,
    _POLL_INTERVAL_SECONDS,
    CrashRecoveryError,
    _canonical_uuid,
    _contract_no,
    _crash_contract_docx,
    _required_environment,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.models.documents import FilePrimaryBusinessObject, FileRecord
from app.models.financial import Contract, ContractField
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, AsyncJobStep

_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_STATE_PATH = Path("/state/status.json")
_STATE_SCHEMA_VERSION = "finaudit-local-contract-extract-crash-v1"
_FILE_TIMEOUT_SECONDS = 180
_RUNNING_TIMEOUT_SECONDS = 90
_RECOVERY_TIMEOUT_SECONDS = 180


class ContractCrashRecoveryError(RuntimeError):
    pass


def _validate_run_id(run_id: str) -> None:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ContractCrashRecoveryError("RUN_ID_INVALID")


def _lock_application_name(run_id: str) -> str:
    _validate_run_id(run_id)
    identity = f"finaudit-contract-crash-{run_id}"
    if len(identity.encode("ascii")) > 63:
        raise ContractCrashRecoveryError("LOCK_IDENTITY_INVALID")
    return identity


def _state_payload(
    *,
    run_id: str,
    file_id: UUID,
    file_job_id: UUID,
    file_sha256: str,
) -> str:
    _validate_run_id(run_id)
    if _SHA256_PATTERN.fullmatch(file_sha256) is None:
        raise ContractCrashRecoveryError("FILE_SHA256_INVALID")
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
        raise ContractCrashRecoveryError("STATE_PATH_INVALID")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ContractCrashRecoveryError("STATE_DIRECTORY_INVALID")
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
        raise ContractCrashRecoveryError("STATE_TEMPORARY_PATH_OCCUPIED")
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
    if base_url != "https://frontend:8443" or not origin.startswith("https://localhost:"):
        raise ContractCrashRecoveryError("CLIENT_PROFILE_INVALID")
    return base_url, origin, username, run_id


def _uploader_credentials(admin_password: str, run_id: str) -> tuple[str, str]:
    _validate_run_id(run_id)
    suffix = run_id[:12]
    return f"contract-crash-{suffix}", f"{admin_password}-contract-crash-{suffix}"


def _client(base_url: str, origin: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        verify=False,
        timeout=httpx.Timeout(15),
        headers={"Origin": origin, "Host": origin.removeprefix("https://")},
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
            raise ContractCrashRecoveryError("FILE_JOB_ID_DRIFT")
        if data.get("job_status") in {"succeeded", "failed", "cancelled"}:
            return data
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise ContractCrashRecoveryError("FILE_PROCESS_TIMEOUT")


def run_prepare_client() -> None:
    base_url, origin, admin_username, run_id = _client_profile()
    admin_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    uploader_username, uploader_password = _uploader_credentials(admin_password, run_id)
    payload = _crash_contract_docx(run_id)

    with _client(base_url, origin) as client:
        admin_token = _login(client, admin_username, admin_password)
        created_user = client.post(
            "/api/v1/users",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Idempotency-Key": f"local-contract-crash-user.{run_id}",
            },
            json={
                "username": uploader_username,
                "display_name": "本地合同提取强杀恢复账号",
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
                "Idempotency-Key": f"local-contract-crash-file.{run_id}",
            },
            data={
                "intended_business_type": "contract",
                "auto_process_requested": "true",
            },
            files={
                "file": (
                    f"local-contract-crash-{run_id[:12]}.docx",
                    payload,
                    _DOCX_MIME,
                )
            },
        )
        accepted_data = _require_envelope(accepted, 202)
        file_id = _canonical_uuid(accepted_data.get("file_id"), "FILE_ID_INVALID")
        file_job_id = _canonical_uuid(accepted_data.get("job_id"), "FILE_JOB_ID_INVALID")
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
            raise ContractCrashRecoveryError("FILE_PROCESS_RESULT_INVALID")
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
        else _canonical_uuid(raw_extraction_job_id, "DATABASE_EXTRACTION_JOB_ID_INVALID")
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
                            AsyncJob.job_type == "contract_extract",
                        )
                    ).all()
                )
                if len(jobs) > 1:
                    raise ContractCrashRecoveryError("EXTRACTION_JOB_DUPLICATED")
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
                            OperationLog.action_code == "contracts.extraction_created",
                        )
                    )
                    if job.status in {"succeeded", "failed", "cancelled"}:
                        raise ContractCrashRecoveryError("EXTRACTION_FINISHED_BEFORE_CRASH")
                    if (
                        job.status == "running"
                        and job.attempt_no == 1
                        and [(step.attempt_no, step.step_code, step.status) for step in steps]
                        == [(1, "extract", "running")]
                        and binding_count == 0
                        and log_count == 0
                    ):
                        print(f"LOCAL_CONTRACT_EXTRACT_RUNNING_JOB_ID={job.id}")
                        return
            time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        engine.dispose()
    raise ContractCrashRecoveryError("EXTRACTION_RUNNING_TIMEOUT")


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
        raise ContractCrashRecoveryError("DATABASE_EXTRACTION_JOB_ID_REQUIRED")
    contract_no = _contract_no(run_id)
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            file_record, jobs = _load_job_cluster(session, file_id)
            file_jobs = tuple(job for job in jobs if job.job_type == "file_process")
            extraction_jobs = tuple(job for job in jobs if job.job_type == "contract_extract")
            extraction_job = extraction_jobs[0] if len(extraction_jobs) == 1 else None
            extraction_steps = (
                ()
                if extraction_job is None
                else tuple(
                    session.scalars(
                        select(AsyncJobStep).where(AsyncJobStep.job_id == extraction_job.id)
                    ).all()
                )
            )
            contract_count = session.scalar(
                select(func.count())
                .select_from(Contract)
                .where(Contract.contract_no == contract_no)
            )
            field_count = session.scalar(
                select(func.count())
                .select_from(ContractField)
                .where(ContractField.evidence_file_id == file_id)
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
                        OperationLog.action_code == "contracts.extraction_created",
                    )
                )
            )
    finally:
        engine.dispose()
    if (
        file_record is None
        or file_record.status != "stored"
        or file_record.security_scan_status != "clean"
        or len(file_jobs) != 1
        or file_jobs[0].status != "succeeded"
        or file_jobs[0].attempt_no != 1
        or extraction_job is None
        or extraction_job.id != extraction_job_id
        or extraction_job.status != "running"
        or extraction_job.attempt_no != 1
        or [(step.attempt_no, step.step_code, step.status) for step in extraction_steps]
        != [(1, "extract", "running")]
        or contract_count != 0
        or field_count != 0
        or binding_count != 0
        or log_count != 0
    ):
        raise ContractCrashRecoveryError("BEFORE_RECOVERY_DATABASE_STATE_INVALID")
    print("LOCAL_CONTRACT_EXTRACT_ZERO_FACTS_BEFORE_RECOVERY_GATE=PASS")


def _expected_contract_detail(contract_id: UUID, contract_no: str) -> dict[str, object]:
    return {
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
    }


def run_verify_client() -> None:
    base_url, origin, _admin_username, run_id = _client_profile()
    file_id = _canonical_uuid(
        _required_environment("FINAUDIT_CRASH_FILE_ID"),
        "CLIENT_FILE_ID_INVALID",
    )
    expected_sha256 = _required_environment("FINAUDIT_CRASH_FILE_SHA256")
    if _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise ContractCrashRecoveryError("CLIENT_FILE_SHA256_INVALID")
    admin_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    uploader_username, uploader_password = _uploader_credentials(admin_password, run_id)
    contract_no = _contract_no(run_id)
    with _client(base_url, origin) as client:
        access_token = _login(client, uploader_username, uploader_password)
        authorization = {"Authorization": f"Bearer {access_token}"}
        deadline = time.monotonic() + _RECOVERY_TIMEOUT_SECONDS
        contract: dict[str, object] | None = None
        while time.monotonic() < deadline:
            page = _require_envelope(
                client.get("/api/v1/contracts?page_size=100", headers=authorization),
                200,
            )
            items = page.get("items")
            if not isinstance(items, list):
                raise ContractCrashRecoveryError("CONTRACT_LIST_INVALID")
            matches = [
                item
                for item in items
                if isinstance(item, dict) and item.get("contract_no") == contract_no
            ]
            if len(matches) > 1:
                raise ContractCrashRecoveryError("CONTRACT_EXTRACTION_DUPLICATED")
            if matches:
                contract = matches[0]
                break
            time.sleep(_POLL_INTERVAL_SECONDS)
        if contract is None:
            raise ContractCrashRecoveryError("CONTRACT_EXTRACTION_RECOVERY_TIMEOUT")
        contract_id = _canonical_uuid(contract.get("id"), "CONTRACT_ID_INVALID")
        detail = _require_envelope(
            client.get(f"/api/v1/contracts/{contract_id}", headers=authorization),
            200,
        )
        if detail != _expected_contract_detail(contract_id, contract_no):
            raise ContractCrashRecoveryError("CONTRACT_EXTRACTION_RESULT_INVALID")
        preview = client.get(f"/api/v1/files/{file_id}/preview", headers=authorization)
        if (
            preview.status_code != 200
            or hashlib.sha256(preview.content).hexdigest() != expected_sha256
            or preview.headers.get("etag") != f'"{expected_sha256}"'
            or preview.headers.get("x-file-status") != "stored"
        ):
            raise ContractCrashRecoveryError("FILE_PREVIEW_INVALID")


def run_final_database_verification() -> None:
    run_id, file_id, extraction_job_id = _database_profile()
    if extraction_job_id is None:
        raise ContractCrashRecoveryError("DATABASE_EXTRACTION_JOB_ID_REQUIRED")
    contract_no = _contract_no(run_id)
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            file_record, jobs = _load_job_cluster(session, file_id)
            file_jobs = tuple(job for job in jobs if job.job_type == "file_process")
            extraction_jobs = tuple(job for job in jobs if job.job_type == "contract_extract")
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
            contracts = tuple(
                session.scalars(select(Contract).where(Contract.contract_no == contract_no)).all()
            )
            contract = contracts[0] if len(contracts) == 1 else None
            bindings = tuple(
                session.scalars(
                    select(FilePrimaryBusinessObject).where(
                        FilePrimaryBusinessObject.file_id == file_id,
                        FilePrimaryBusinessObject.business_type == "contract",
                    )
                ).all()
            )
            fields = (
                ()
                if contract is None
                else tuple(
                    session.scalars(
                        select(ContractField).where(ContractField.contract_id == contract.id)
                    ).all()
                )
            )
            extraction_logs = (
                ()
                if contract is None
                else tuple(
                    session.scalars(
                        select(OperationLog).where(
                            OperationLog.resource_type == "contract",
                            OperationLog.resource_id == contract.id,
                            OperationLog.action_code == "contracts.extraction_created",
                        )
                    ).all()
                )
            )
    finally:
        engine.dispose()
    if (
        file_record is None
        or file_record.status != "stored"
        or file_record.security_scan_status != "clean"
        or len(jobs) != 2
        or file_job is None
        or file_job.status != "succeeded"
        or file_job.attempt_no != 1
        or extraction_job is None
        or extraction_job.id != extraction_job_id
        or extraction_job.status != "succeeded"
        or extraction_job.attempt_no != 2
    ):
        raise ContractCrashRecoveryError("FINAL_DATABASE_JOB_STATE_INVALID")
    if [(step.attempt_no, step.step_code, step.status, step.error_code) for step in file_steps] != [
        (1, "scan", "succeeded", None),
        (1, "parse", "succeeded", None),
        (1, "markdown", "succeeded", None),
    ]:
        raise ContractCrashRecoveryError("FINAL_FILE_STEP_HISTORY_INVALID")
    if [
        (step.attempt_no, step.step_code, step.status, step.error_code) for step in extraction_steps
    ] != [
        (1, "extract", "failed", "LEASE_EXPIRED"),
        (2, "extract", "succeeded", None),
    ]:
        raise ContractCrashRecoveryError("FINAL_EXTRACTION_STEP_HISTORY_INVALID")
    binding = bindings[0] if len(bindings) == 1 else None
    if (
        contract is None
        or binding is None
        or binding.contract_id != contract.id
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
        or len(fields) != len(_CONTRACT_FIELD_CODES)
        or {field.field_code for field in fields} != _CONTRACT_FIELD_CODES
        or any(field.evidence_file_id != file_id for field in fields)
        or len(extraction_logs) != 1
        or extraction_job is None
        or extraction_logs[0].trace_id != extraction_job.trace_id
    ):
        raise ContractCrashRecoveryError("FINAL_CONTRACT_FACTS_INVALID")
    print("LOCAL_CONTRACT_EXTRACT_ATTEMPT_HISTORY_DATABASE_GATE=PASS")
    print("LOCAL_CONTRACT_EXTRACT_UNIQUE_FACTS_DATABASE_GATE=PASS")


def main() -> int:
    try:
        if sys.argv == [sys.argv[0], "prepare"]:
            run_prepare_client()
            print("LOCAL_CONTRACT_EXTRACT_CRASH_PREPARE_GATE=PASS")
        elif sys.argv == [sys.argv[0], "wait-running"]:
            run_wait_for_extraction()
            print("LOCAL_CONTRACT_EXTRACT_RUNNING_GATE=PASS")
        elif sys.argv == [sys.argv[0], "before-recovery"]:
            run_before_recovery_verification()
        elif sys.argv == [sys.argv[0], "verify-client"]:
            run_verify_client()
            print("LOCAL_CONTRACT_EXTRACT_CRASH_CLIENT_GATE=PASS")
        elif sys.argv == [sys.argv[0], "database"]:
            run_final_database_verification()
            print("LOCAL_CONTRACT_EXTRACT_CRASH_DATABASE_GATE=PASS")
        else:
            raise ContractCrashRecoveryError("ARGUMENTS_INVALID")
    except (ContractCrashRecoveryError, CrashRecoveryError, SmokeError) as error:
        print("LOCAL_CONTRACT_EXTRACT_CRASH_RECOVERY=FAIL")
        print(f"LOCAL_CONTRACT_EXTRACT_CRASH_REASON={error}")
        return 1
    except Exception as error:
        print("LOCAL_CONTRACT_EXTRACT_CRASH_RECOVERY=FAIL")
        print(f"LOCAL_CONTRACT_EXTRACT_CRASH_REASON=UNEXPECTED_{type(error).__name__.upper()}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
