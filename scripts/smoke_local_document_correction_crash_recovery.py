from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

import httpx
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]
from smoke_local_file_upload import SmokeError, _login, _read_password, _require_envelope
from smoke_local_worker_crash_recovery import (
    _POLL_INTERVAL_SECONDS,
    CrashRecoveryError,
    _canonical_uuid,
    _required_environment,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.models.document_processing import DocumentBlock, DocumentPage, DocumentParseVersion
from app.models.documents import FileRecord
from app.models.knowledge import DocumentBlockCorrection, DocumentMarkdownVersion
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, AsyncJobStep, OutboxEvent

_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_STATE_PATH = Path("/state/status.json")
_STATE_SCHEMA_VERSION = "finaudit-local-document-correction-crash-v1"
_FILE_TIMEOUT_SECONDS = 180
_RUNNING_TIMEOUT_SECONDS = 90
_RECOVERY_TIMEOUT_SECONDS = 180
_SOURCE_TEXT_PREFIX = "Supplementary agreement correction source"
_CORRECTED_TEXT_PREFIX = "Supplementary agreement corrected after crash test"


class DocumentCorrectionCrashError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _DatabaseProfile:
    run_id: str
    file_id: UUID
    file_job_id: UUID
    file_sha256: str
    source_parse_version_id: UUID
    source_block_id: UUID
    source_text_sha256: str
    source_block_count: int
    correction_id: UUID
    result_parse_version_id: UUID
    correction_job_id: UUID
    correction_trace_id: UUID


def _validate_run_id(run_id: str) -> None:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise DocumentCorrectionCrashError("RUN_ID_INVALID")


def _state_path() -> Path:
    path = Path(_required_environment("FINAUDIT_CRASH_STATE_PATH"))
    if path != _STATE_PATH or not path.is_absolute() or path.is_symlink():
        raise DocumentCorrectionCrashError("STATE_PATH_INVALID")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise DocumentCorrectionCrashError("STATE_DIRECTORY_INVALID")
    return path


def _write_state(payload: dict[str, object]) -> None:
    path = _state_path()
    temporary = path.with_suffix(".tmp")
    if temporary.exists() or temporary.is_symlink():
        raise DocumentCorrectionCrashError("STATE_TEMPORARY_PATH_OCCUPIED")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _state_uuid(payload: dict[str, object], key: str) -> UUID:
    return _canonical_uuid(payload.get(key), f"STATE_{key.upper()}_INVALID")


def _state_sha256(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise DocumentCorrectionCrashError(f"STATE_{key.upper()}_INVALID")
    return value


def _read_state(expected_phase: str) -> dict[str, object]:
    path = _state_path()
    if not path.is_file():
        raise DocumentCorrectionCrashError("STATE_FILE_MISSING")
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DocumentCorrectionCrashError("STATE_FILE_INVALID") from None
    if type(loaded) is not dict:
        raise DocumentCorrectionCrashError("STATE_FILE_INVALID")
    payload = cast(dict[str, object], loaded)
    file_ready_keys = {
        "schema_version",
        "phase",
        "run_id",
        "file_id",
        "file_job_id",
        "file_sha256",
        "source_parse_version_id",
        "source_block_id",
        "source_text_sha256",
        "source_block_count",
    }
    expected_keys = (
        file_ready_keys
        if expected_phase == "file_ready"
        else file_ready_keys
        | {
            "correction_id",
            "result_parse_version_id",
            "correction_job_id",
            "correction_trace_id",
        }
    )
    run_id = payload.get("run_id")
    source_block_count = payload.get("source_block_count")
    if (
        expected_phase not in {"file_ready", "correction_requested"}
        or set(payload) != expected_keys
        or payload.get("schema_version") != _STATE_SCHEMA_VERSION
        or payload.get("phase") != expected_phase
        or type(run_id) is not str
        or _RUN_ID_PATTERN.fullmatch(run_id) is None
        or type(source_block_count) is not int
        or source_block_count <= 0
    ):
        raise DocumentCorrectionCrashError("STATE_FILE_INVALID")
    for key in ("file_id", "file_job_id", "source_parse_version_id", "source_block_id"):
        _state_uuid(payload, key)
    for key in ("file_sha256", "source_text_sha256"):
        _state_sha256(payload, key)
    if expected_phase == "correction_requested":
        for key in (
            "correction_id",
            "result_parse_version_id",
            "correction_job_id",
            "correction_trace_id",
        ):
            _state_uuid(payload, key)
    return payload


def _source_pdf(run_id: str) -> bytes:
    _validate_run_id(run_id)
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=(700, 300), invariant=1)
    document.drawString(20, 250, f"{_SOURCE_TEXT_PREFIX} {run_id[:12]}")
    document.drawString(
        20, 230, "The original agreement text remains active until explicit activation."
    )
    document.drawString(20, 210, "A failed correction candidate must never replace this source.")
    document.save()
    payload = output.getvalue()
    if not payload.startswith(b"%PDF") or not payload.rstrip().endswith(b"%%EOF"):
        raise DocumentCorrectionCrashError("SOURCE_PDF_INVALID")
    return payload


def _client_profile() -> tuple[str, str, str, str]:
    base_url = _required_environment("FINAUDIT_SMOKE_BASE_URL")
    origin = _required_environment("AUTH_PUBLIC_ORIGIN")
    admin_username = _required_environment("BOOTSTRAP_ADMIN_USERNAME")
    run_id = _required_environment("FINAUDIT_CRASH_RUN_ID")
    _validate_run_id(run_id)
    if base_url != "http://frontend:8443" or not origin.startswith("http://localhost:"):
        raise DocumentCorrectionCrashError("CLIENT_PROFILE_INVALID")
    return base_url, origin, admin_username, run_id


def _client(base_url: str, origin: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        verify=False,
        timeout=httpx.Timeout(15),
        headers={"Origin": origin, "Host": origin.removeprefix("http://")},
    )


def _reviewer_credentials(admin_password: str, run_id: str) -> tuple[str, str]:
    _validate_run_id(run_id)
    digest = hashlib.sha256(
        f"{admin_password}\0{run_id}\0document-correction-crash".encode()
    ).hexdigest()
    return f"correction-crash-{run_id[:12]}", f"Dc9!{digest[:24]}"


def _wait_for_file(
    client: httpx.Client,
    *,
    access_token: str,
    file_id: UUID,
    file_job_id: UUID,
) -> dict[str, object]:
    authorization = {"Authorization": f"Bearer {access_token}"}
    deadline = time.monotonic() + _FILE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        data = _require_envelope(
            client.get(f"/api/v1/files/{file_id}", headers=authorization),
            200,
        )
        if data.get("job_id") != str(file_job_id):
            raise DocumentCorrectionCrashError("FILE_JOB_ID_DRIFT")
        if data.get("job_status") in {"succeeded", "failed", "cancelled"}:
            return data
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise DocumentCorrectionCrashError("FILE_PROCESS_TIMEOUT")


def run_prepare_client() -> None:
    base_url, origin, admin_username, run_id = _client_profile()
    admin_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    reviewer_username, reviewer_password = _reviewer_credentials(admin_password, run_id)
    payload = _source_pdf(run_id)
    with _client(base_url, origin) as client:
        admin_token = _login(client, admin_username, admin_password)
        created = client.post(
            "/api/v1/users",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Idempotency-Key": f"local-correction-crash-user.{run_id}",
            },
            json={
                "username": reviewer_username,
                "display_name": "本地文档纠错强杀恢复账号",
                "initial_password": reviewer_password,
                "fixed_roles": ["contract_admin"],
            },
        )
        _require_envelope(created, 201)
        reviewer_token = _login(client, reviewer_username, reviewer_password)
        authorization = {"Authorization": f"Bearer {reviewer_token}"}
        accepted = client.post(
            "/api/v1/files",
            headers={
                **authorization,
                "Idempotency-Key": f"local-correction-crash-file.{run_id}",
            },
            data={
                "intended_business_type": "supplementary_agreement",
                "auto_process_requested": "true",
            },
            files={
                "file": (
                    f"local-correction-crash-{run_id[:12]}.pdf",
                    payload,
                    "application/pdf",
                )
            },
        )
        accepted_data = _require_envelope(accepted, 202)
        file_id = _canonical_uuid(accepted_data.get("file_id"), "FILE_ID_INVALID")
        file_job_id = _canonical_uuid(accepted_data.get("job_id"), "FILE_JOB_ID_INVALID")
        final = _wait_for_file(
            client,
            access_token=reviewer_token,
            file_id=file_id,
            file_job_id=file_job_id,
        )
        if (
            final.get("job_status") != "succeeded"
            or final.get("status") != "stored"
            or final.get("security_scan_status") != "clean"
        ):
            raise DocumentCorrectionCrashError("FILE_PROCESS_RESULT_INVALID")
        block_page = _require_envelope(
            client.get(
                f"/api/v1/files/{file_id}/document-correction-blocks?page_size=100",
                headers=authorization,
            ),
            200,
        )
        items = block_page.get("items")
        if (
            block_page.get("file_id") != str(file_id)
            or block_page.get("business_type") != "supplementary_agreement"
            or type(block_page.get("parse_version_id")) is not str
            or type(items) is not list
            or not items
            or block_page.get("next_cursor") is not None
        ):
            raise DocumentCorrectionCrashError("CORRECTION_SOURCE_LIST_INVALID")
        source_parse_version_id = _canonical_uuid(
            block_page.get("parse_version_id"), "SOURCE_PARSE_VERSION_ID_INVALID"
        )
        first = items[0]
        if type(first) is not dict or type(first.get("text_content")) is not str:
            raise DocumentCorrectionCrashError("CORRECTION_SOURCE_BLOCK_INVALID")
        source_block_id = _canonical_uuid(first.get("block_id"), "SOURCE_BLOCK_ID_INVALID")
        source_text = first["text_content"]
        if not source_text or _SOURCE_TEXT_PREFIX not in source_text:
            raise DocumentCorrectionCrashError("CORRECTION_SOURCE_TEXT_INVALID")
        _write_state(
            {
                "schema_version": _STATE_SCHEMA_VERSION,
                "phase": "file_ready",
                "run_id": run_id,
                "file_id": str(file_id),
                "file_job_id": str(file_job_id),
                "file_sha256": hashlib.sha256(payload).hexdigest(),
                "source_parse_version_id": str(source_parse_version_id),
                "source_block_id": str(source_block_id),
                "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                "source_block_count": len(items),
            }
        )


def run_request_client() -> None:
    base_url, origin, _admin_username, run_id = _client_profile()
    state = _read_state("file_ready")
    if state.get("run_id") != run_id:
        raise DocumentCorrectionCrashError("STATE_RUN_ID_MISMATCH")
    admin_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    reviewer_username, reviewer_password = _reviewer_credentials(admin_password, run_id)
    source_parse_version_id = _state_uuid(state, "source_parse_version_id")
    source_block_id = _state_uuid(state, "source_block_id")
    with _client(base_url, origin) as client:
        reviewer_token = _login(client, reviewer_username, reviewer_password)
        response = client.post(
            f"/api/v1/document-blocks/{source_block_id}/correct",
            headers={
                "Authorization": f"Bearer {reviewer_token}",
                "Idempotency-Key": f"local-correction-crash-request.{run_id}",
            },
            json={
                "field_name": "text_content",
                "after_value": f"{_CORRECTED_TEXT_PREFIX} {run_id[:12]}",
                "reason": "验证 Worker 强杀后旧活动解析保持不变",
                "source_parse_version_id": str(source_parse_version_id),
            },
        )
        accepted = _require_envelope(response, 202)
        correction_id = _canonical_uuid(accepted.get("correction_id"), "CORRECTION_ID_INVALID")
        result_parse_version_id = _canonical_uuid(
            accepted.get("result_parse_version_id"), "RESULT_PARSE_VERSION_ID_INVALID"
        )
        correction_job_id = _canonical_uuid(accepted.get("job_id"), "CORRECTION_JOB_ID_INVALID")
        correction_trace_id = _canonical_uuid(
            response.headers.get("x-trace-id"), "CORRECTION_TRACE_ID_INVALID"
        )
        if (
            accepted.get("status") != "queued"
            or response.headers.get("idempotency-replayed") != "false"
            or response.headers.get("cache-control") != "private, no-store"
        ):
            raise DocumentCorrectionCrashError("CORRECTION_REQUEST_CONTRACT_INVALID")
        _write_state(
            {
                **state,
                "phase": "correction_requested",
                "correction_id": str(correction_id),
                "result_parse_version_id": str(result_parse_version_id),
                "correction_job_id": str(correction_job_id),
                "correction_trace_id": str(correction_trace_id),
            }
        )


def _required_uuid(name: str) -> UUID:
    return _canonical_uuid(_required_environment(name), f"{name}_INVALID")


def _required_sha256(name: str) -> str:
    value = _required_environment(name)
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise DocumentCorrectionCrashError(f"{name}_INVALID")
    return value


def _required_positive_int(name: str) -> int:
    value = _required_environment(name)
    if not value.isascii() or not value.isdigit() or int(value) <= 0:
        raise DocumentCorrectionCrashError(f"{name}_INVALID")
    return int(value)


def _database_profile() -> _DatabaseProfile:
    run_id = _required_environment("FINAUDIT_CRASH_RUN_ID")
    _validate_run_id(run_id)
    return _DatabaseProfile(
        run_id=run_id,
        file_id=_required_uuid("FINAUDIT_CRASH_FILE_ID"),
        file_job_id=_required_uuid("FINAUDIT_CRASH_FILE_JOB_ID"),
        file_sha256=_required_sha256("FINAUDIT_CRASH_FILE_SHA256"),
        source_parse_version_id=_required_uuid("FINAUDIT_CRASH_SOURCE_PARSE_ID"),
        source_block_id=_required_uuid("FINAUDIT_CRASH_SOURCE_BLOCK_ID"),
        source_text_sha256=_required_sha256("FINAUDIT_CRASH_SOURCE_TEXT_SHA256"),
        source_block_count=_required_positive_int("FINAUDIT_CRASH_SOURCE_BLOCK_COUNT"),
        correction_id=_required_uuid("FINAUDIT_CRASH_CORRECTION_ID"),
        result_parse_version_id=_required_uuid("FINAUDIT_CRASH_RESULT_PARSE_ID"),
        correction_job_id=_required_uuid("FINAUDIT_CRASH_CORRECTION_JOB_ID"),
        correction_trace_id=_required_uuid("FINAUDIT_CRASH_CORRECTION_TRACE_ID"),
    )


def _result_fact_counts(session: Session, result_parse_version_id: UUID) -> tuple[int, int, int]:
    page_count = session.scalar(
        select(func.count())
        .select_from(DocumentPage)
        .where(DocumentPage.parse_version_id == result_parse_version_id)
    )
    block_count = session.scalar(
        select(func.count())
        .select_from(DocumentBlock)
        .where(DocumentBlock.parse_version_id == result_parse_version_id)
    )
    markdown_count = session.scalar(
        select(func.count())
        .select_from(DocumentMarkdownVersion)
        .where(DocumentMarkdownVersion.parse_version_id == result_parse_version_id)
    )
    return int(page_count or 0), int(block_count or 0), int(markdown_count or 0)


def run_wait_for_correction() -> None:
    profile = _database_profile()
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        deadline = time.monotonic() + _RUNNING_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with factory() as session:
                job = session.get(AsyncJob, profile.correction_job_id)
                result = session.get(DocumentParseVersion, profile.result_parse_version_id)
                source = session.get(DocumentParseVersion, profile.source_parse_version_id)
                correction = session.get(DocumentBlockCorrection, profile.correction_id)
                steps = tuple(
                    session.scalars(
                        select(AsyncJobStep)
                        .where(AsyncJobStep.job_id == profile.correction_job_id)
                        .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                    ).all()
                )
                result_counts = _result_fact_counts(session, profile.result_parse_version_id)
                if job is not None and job.status in {"succeeded", "failed", "cancelled"}:
                    raise DocumentCorrectionCrashError("CORRECTION_FINISHED_BEFORE_CRASH")
                if (
                    job is not None
                    and job.job_type == "manual_correction_snapshot"
                    and job.resource_type == "document_parse_version"
                    and job.resource_id == profile.result_parse_version_id
                    and job.status == "running"
                    and job.stage == "snapshot_rebuild"
                    and job.attempt_no == 1
                    and job.max_attempts == 1
                    and [(step.attempt_no, step.step_code, step.status) for step in steps]
                    == [(1, "snapshot_rebuild", "running")]
                    and result is not None
                    and result.status == "running"
                    and source is not None
                    and source.status == "active"
                    and correction is not None
                    and correction.result_parse_version_id == result.id
                    and result_counts == (0, 0, 0)
                ):
                    print(f"LOCAL_DOCUMENT_CORRECTION_RUNNING_JOB_ID={job.id}")
                    return
            time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        engine.dispose()
    raise DocumentCorrectionCrashError("CORRECTION_RUNNING_TIMEOUT")


def run_before_recovery_verification() -> None:
    profile = _database_profile()
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            file_record = session.get(FileRecord, profile.file_id)
            source = session.get(DocumentParseVersion, profile.source_parse_version_id)
            result = session.get(DocumentParseVersion, profile.result_parse_version_id)
            correction = session.get(DocumentBlockCorrection, profile.correction_id)
            job = session.get(AsyncJob, profile.correction_job_id)
            steps = tuple(
                session.scalars(
                    select(AsyncJobStep).where(AsyncJobStep.job_id == profile.correction_job_id)
                ).all()
            )
            result_counts = _result_fact_counts(session, profile.result_parse_version_id)
            source_block_count = session.scalar(
                select(func.count())
                .select_from(DocumentBlock)
                .where(DocumentBlock.parse_version_id == profile.source_parse_version_id)
            )
            request_log_count = session.scalar(
                select(func.count())
                .select_from(OperationLog)
                .where(
                    OperationLog.trace_id == profile.correction_trace_id,
                    OperationLog.action_code == "document_block.correction_requested",
                )
            )
    finally:
        engine.dispose()
    if (
        file_record is None
        or file_record.status != "stored"
        or file_record.security_scan_status != "clean"
        or source is None
        or source.status != "active"
        or result is None
        or result.status != "running"
        or correction is None
        or correction.source_parse_version_id != source.id
        or correction.result_parse_version_id != result.id
        or job is None
        or job.status != "running"
        or job.attempt_no != 1
        or [(step.attempt_no, step.step_code, step.status) for step in steps]
        != [(1, "snapshot_rebuild", "running")]
        or result_counts != (0, 0, 0)
        or source_block_count != profile.source_block_count
        or request_log_count != 1
    ):
        raise DocumentCorrectionCrashError("BEFORE_RECOVERY_DATABASE_STATE_INVALID")
    print("LOCAL_DOCUMENT_CORRECTION_ZERO_CANDIDATE_FACTS_GATE=PASS")


def _wait_for_terminal_failure(profile: _DatabaseProfile) -> None:
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        deadline = time.monotonic() + _RECOVERY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with factory() as session:
                job = session.get(AsyncJob, profile.correction_job_id)
                result = session.get(DocumentParseVersion, profile.result_parse_version_id)
                if (
                    job is not None
                    and result is not None
                    and job.status == "failed"
                    and result.status == "failed"
                ):
                    return
            time.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        engine.dispose()
    raise DocumentCorrectionCrashError("CORRECTION_FAILURE_TIMEOUT")


def run_verify_client() -> None:
    base_url, origin, _admin_username, run_id = _client_profile()
    profile = _database_profile()
    if profile.run_id != run_id:
        raise DocumentCorrectionCrashError("CLIENT_RUN_ID_MISMATCH")
    admin_password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    reviewer_username, reviewer_password = _reviewer_credentials(admin_password, run_id)
    with _client(base_url, origin) as client:
        reviewer_token = _login(client, reviewer_username, reviewer_password)
        authorization = {"Authorization": f"Bearer {reviewer_token}"}
        block_page = _require_envelope(
            client.get(
                f"/api/v1/files/{profile.file_id}/document-correction-blocks?page_size=100",
                headers=authorization,
            ),
            200,
        )
        items = block_page.get("items")
        if (
            block_page.get("parse_version_id") != str(profile.source_parse_version_id)
            or type(items) is not list
            or len(items) != profile.source_block_count
        ):
            raise DocumentCorrectionCrashError("CLIENT_SOURCE_VERSION_DRIFT")
        source_matches = [
            item
            for item in items
            if type(item) is dict and item.get("block_id") == str(profile.source_block_id)
        ]
        if len(source_matches) != 1 or type(source_matches[0].get("text_content")) is not str:
            raise DocumentCorrectionCrashError("CLIENT_SOURCE_BLOCK_INVALID")
        source_text = source_matches[0]["text_content"]
        if hashlib.sha256(source_text.encode("utf-8")).hexdigest() != profile.source_text_sha256:
            raise DocumentCorrectionCrashError("CLIENT_SOURCE_TEXT_DRIFT")
        activation = client.post(
            f"/api/v1/document-parse-versions/{profile.result_parse_version_id}/activate",
            headers={
                **authorization,
                "Idempotency-Key": f"local-correction-crash-activate.{run_id}",
            },
            json={"reason": "失败候选不得激活"},
        )
        try:
            activation_payload: object = activation.json()
        except ValueError:
            raise DocumentCorrectionCrashError("CLIENT_ACTIVATION_ERROR_INVALID") from None
        if (
            activation.status_code != 409
            or type(activation_payload) is not dict
            or activation_payload.get("code") != "PARSE_STATE_CONFLICT"
            or activation_payload.get("data") is not None
        ):
            raise DocumentCorrectionCrashError("CLIENT_FAILED_CANDIDATE_ACTIVATABLE")
        preview = client.get(f"/api/v1/files/{profile.file_id}/preview", headers=authorization)
        if (
            preview.status_code != 200
            or hashlib.sha256(preview.content).hexdigest() != profile.file_sha256
            or preview.headers.get("etag") != f'"{profile.file_sha256}"'
        ):
            raise DocumentCorrectionCrashError("CLIENT_SOURCE_PREVIEW_INVALID")


def run_final_database_verification() -> None:
    profile = _database_profile()
    _wait_for_terminal_failure(profile)
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            file_record = session.get(FileRecord, profile.file_id)
            source = session.get(DocumentParseVersion, profile.source_parse_version_id)
            result = session.get(DocumentParseVersion, profile.result_parse_version_id)
            correction = session.get(DocumentBlockCorrection, profile.correction_id)
            file_job = session.get(AsyncJob, profile.file_job_id)
            correction_job = session.get(AsyncJob, profile.correction_job_id)
            file_steps = tuple(
                session.scalars(
                    select(AsyncJobStep)
                    .where(AsyncJobStep.job_id == profile.file_job_id)
                    .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                ).all()
            )
            correction_steps = tuple(
                session.scalars(
                    select(AsyncJobStep)
                    .where(AsyncJobStep.job_id == profile.correction_job_id)
                    .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
                ).all()
            )
            result_counts = _result_fact_counts(session, profile.result_parse_version_id)
            source_blocks = tuple(
                session.scalars(
                    select(DocumentBlock)
                    .where(DocumentBlock.parse_version_id == profile.source_parse_version_id)
                    .order_by(DocumentBlock.block_index)
                ).all()
            )
            source_block = session.get(DocumentBlock, profile.source_block_id)
            outboxes = tuple(
                session.scalars(
                    select(OutboxEvent).where(OutboxEvent.aggregate_id == profile.correction_job_id)
                ).all()
            )
            request_logs = tuple(
                session.scalars(
                    select(OperationLog).where(
                        OperationLog.trace_id == profile.correction_trace_id,
                        OperationLog.action_code == "document_block.correction_requested",
                    )
                ).all()
            )
            activation_log_count = session.scalar(
                select(func.count())
                .select_from(OperationLog)
                .where(
                    OperationLog.resource_type == "document_parse_version",
                    OperationLog.resource_id == profile.result_parse_version_id,
                    OperationLog.action_code == "document_parse.activated",
                )
            )
    finally:
        engine.dispose()
    if (
        file_record is None
        or file_record.status != "stored"
        or file_record.security_scan_status != "clean"
        or source is None
        or source.status != "active"
        or source.superseded_at is not None
        or result is None
        or result.status != "failed"
        or result.error_code != "WORKER_LOST"
        or result.page_count != 0
        or result.activated_at is not None
        or correction is None
        or correction.source_parse_version_id != source.id
        or correction.source_block_id != profile.source_block_id
        or correction.result_parse_version_id != result.id
        or correction.trace_id != profile.correction_trace_id
        or file_job is None
        or file_job.status != "succeeded"
        or file_job.attempt_no != 1
        or correction_job is None
        or correction_job.status != "failed"
        or correction_job.error_code != "WORKER_LOST"
        or correction_job.attempt_no != 1
        or correction_job.max_attempts != 1
        or correction_job.resource_id != result.id
        or correction_job.trace_id != profile.correction_trace_id
        or result_counts != (0, 0, 0)
        or len(source_blocks) != profile.source_block_count
        or source_block is None
        or source_block.text_content is None
        or hashlib.sha256(source_block.text_content.encode("utf-8")).hexdigest()
        != profile.source_text_sha256
        or len(outboxes) != 1
        or outboxes[0].status != "published"
        or len(request_logs) != 1
        or activation_log_count != 0
    ):
        raise DocumentCorrectionCrashError("FINAL_DATABASE_FACTS_INVALID")
    if [(step.attempt_no, step.step_code, step.status, step.error_code) for step in file_steps] != [
        (1, "scan", "succeeded", None),
        (1, "parse", "succeeded", None),
        (1, "markdown", "succeeded", None),
    ]:
        raise DocumentCorrectionCrashError("FINAL_FILE_STEP_HISTORY_INVALID")
    if [
        (step.attempt_no, step.step_code, step.status, step.error_code) for step in correction_steps
    ] != [(1, "snapshot_rebuild", "failed", "WORKER_LOST")]:
        raise DocumentCorrectionCrashError("FINAL_CORRECTION_STEP_HISTORY_INVALID")
    print("LOCAL_DOCUMENT_CORRECTION_TERMINAL_FAILURE_DATABASE_GATE=PASS")
    print("LOCAL_DOCUMENT_CORRECTION_OLD_ACTIVE_DATABASE_GATE=PASS")


def main() -> int:
    try:
        if sys.argv == [sys.argv[0], "prepare"]:
            run_prepare_client()
            print("LOCAL_DOCUMENT_CORRECTION_CRASH_PREPARE_GATE=PASS")
        elif sys.argv == [sys.argv[0], "request"]:
            run_request_client()
            print("LOCAL_DOCUMENT_CORRECTION_CRASH_REQUEST_GATE=PASS")
        elif sys.argv == [sys.argv[0], "wait-running"]:
            run_wait_for_correction()
            print("LOCAL_DOCUMENT_CORRECTION_RUNNING_GATE=PASS")
        elif sys.argv == [sys.argv[0], "before-recovery"]:
            run_before_recovery_verification()
        elif sys.argv == [sys.argv[0], "verify-client"]:
            run_verify_client()
            print("LOCAL_DOCUMENT_CORRECTION_CRASH_CLIENT_GATE=PASS")
        elif sys.argv == [sys.argv[0], "database"]:
            run_final_database_verification()
            print("LOCAL_DOCUMENT_CORRECTION_CRASH_DATABASE_GATE=PASS")
        else:
            raise DocumentCorrectionCrashError("ARGUMENTS_INVALID")
    except (DocumentCorrectionCrashError, CrashRecoveryError, SmokeError) as error:
        print("LOCAL_DOCUMENT_CORRECTION_CRASH_RECOVERY=FAIL")
        print(f"LOCAL_DOCUMENT_CORRECTION_CRASH_REASON={error}")
        return 1
    except Exception as error:
        print("LOCAL_DOCUMENT_CORRECTION_CRASH_RECOVERY=FAIL")
        print(f"LOCAL_DOCUMENT_CORRECTION_CRASH_REASON=UNEXPECTED_{type(error).__name__.upper()}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
