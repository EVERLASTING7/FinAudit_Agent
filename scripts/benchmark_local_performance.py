from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from smoke_local_file_upload import (
    SmokeError,
    _login,
    _read_password,
    _require_envelope,
)
from smoke_local_file_upload import _synthetic_pdf as _base_pdf
from sqlalchemy import func, select

from app.audit.rule_catalog import publish_builtin_catalog
from app.core.config import Settings
from app.core.password_policy import validate_new_password
from app.db.session import create_application_engine, create_session_factory
from app.models.audit import (
    AuditTask,
    AuditTaskExecution,
    AuditTaskItem,
    AuditTaskSnapshot,
    RuleExecution,
)
from app.models.auth import Organization, User
from app.models.documents import FileRecord
from app.models.financial import Contract, Invoice, InvoiceItem
from app.models.reliability import AsyncJob, AsyncJobStep, OutboxEvent

_SCHEMA_VERSION = "finaudit-local-performance-v2"
_TRANSPORT_SCOPE = "http-nginx-backend"
_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_BASELINE_DATE = date(2026, 8, 15)
_ROUND_COUNT = 3
_LIST_SAMPLE_COUNT = 20
_UPLOAD_SAMPLE_COUNT = 20
_BATCH_FILE_COUNT = 20
_AUDIT_TASK_COUNT = 3
_LIST_P95_LIMIT_SECONDS = 0.8
_UPLOAD_ACCEPTANCE_P95_LIMIT_SECONDS = 3.0
_JOB_TIMEOUT_SECONDS = 180.0
_POLL_INTERVAL_SECONDS = 0.25


class PerformanceError(RuntimeError):
    pass


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise PerformanceError(f"{name}_REQUIRED")
    return value


def _run_id() -> str:
    value = _required_environment("FINAUDIT_PERFORMANCE_RUN_ID")
    if _RUN_ID_PATTERN.fullmatch(value) is None:
        raise PerformanceError("RUN_ID_INVALID")
    return value


def _task_prefix(run_id: str) -> str:
    return f"LP-{run_id[:12].upper()}-"


def _batch_file_name(run_id: str, round_no: int, item_no: int) -> str:
    return f"local-performance-batch-{run_id[:12]}-{round_no:02d}-{item_no:02d}.pdf"


def _stable_id(run_id: str, kind: str, index: int = 0) -> UUID:
    return uuid5(NAMESPACE_URL, f"{_SCHEMA_VERSION}:{run_id}:{kind}:{index}")


def _canonical_uuid(value: object, reason: str) -> UUID:
    if type(value) is not str:
        raise PerformanceError(reason)
    try:
        parsed = UUID(value)
    except ValueError:
        raise PerformanceError(reason) from None
    if str(parsed) != value:
        raise PerformanceError(reason)
    return parsed


def _p95(samples: list[float]) -> float:
    if not samples:
        raise PerformanceError("EMPTY_PERFORMANCE_SAMPLE")
    ordered = sorted(samples)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def _validate_batch_limit_response(response: httpx.Response) -> None:
    if response.status_code != 413:
        raise PerformanceError("BATCH_LIMIT_CONTRACT_INVALID")
    try:
        payload = response.json()
    except ValueError:
        raise PerformanceError("BATCH_LIMIT_CONTRACT_INVALID") from None
    if not isinstance(payload, dict) or payload.get("code") != "BATCH_LIMIT_EXCEEDED":
        raise PerformanceError("BATCH_LIMIT_CONTRACT_INVALID")
    _canonical_uuid(payload.get("trace_id"), "BATCH_LIMIT_CONTRACT_INVALID")


def _validate_batch_response(
    data: dict[str, object],
    *,
    expected_count: int,
    expected_replayed: bool,
    expected_rejections: dict[int, tuple[int, str]] | None = None,
    expected_names: tuple[str, ...] | None = None,
) -> tuple[tuple[UUID, UUID], ...]:
    rejections = expected_rejections or {}
    items = data.get("items")
    expected_accepted_count = expected_count - len(rejections)
    if (
        type(expected_count) is not int
        or expected_count < 1
        or any(
            type(index) is not int or not 0 <= index < expected_count
            for index in rejections
        )
        or (expected_names is not None and len(expected_names) != expected_count)
        or type(items) is not list
        or len(items) != expected_count
        or data.get("accepted_count") != expected_accepted_count
        or data.get("rejected_count") != len(rejections)
    ):
        raise PerformanceError("BATCH_CONTRACT_INVALID")

    identities: list[tuple[UUID, UUID]] = []
    for index, item in enumerate(items):
        if (
            not isinstance(item, dict)
            or item.get("index") != index
            or (
                expected_names is not None
                and item.get("original_name") != expected_names[index]
            )
        ):
            raise PerformanceError("BATCH_CONTRACT_INVALID")
        if index in rejections:
            expected_status, expected_code = rejections[index]
            error = item.get("error")
            if (
                item.get("outcome") != "rejected"
                or item.get("http_status") != expected_status
                or item.get("replayed") is not False
                or item.get("data") is not None
                or not isinstance(error, dict)
                or error.get("code") != expected_code
                or type(error.get("message")) is not str
                or not error["message"]
            ):
                raise PerformanceError("BATCH_REJECTION_CONTRACT_INVALID")
            continue

        item_data = item.get("data")
        if (
            item.get("outcome") != "accepted"
            or item.get("http_status") != 202
            or item.get("replayed") is not expected_replayed
            or not isinstance(item_data, dict)
            or item.get("error") is not None
            or (
                expected_names is not None
                and item_data.get("original_name") != expected_names[index]
            )
        ):
            raise PerformanceError("BATCH_ACCEPTANCE_CONTRACT_INVALID")
        identities.append(
            (
                _canonical_uuid(item_data.get("file_id"), "BATCH_FILE_ID_INVALID"),
                _canonical_uuid(item_data.get("job_id"), "BATCH_JOB_ID_INVALID"),
            )
        )

    file_ids = {file_id for file_id, _job_id in identities}
    job_ids = {job_id for _file_id, job_id in identities}
    if len(file_ids) != len(identities) or len(job_ids) != len(identities):
        raise PerformanceError("BATCH_IDENTITY_DUPLICATED")
    return tuple(identities)


def _performance_pdf(run_id: str, round_no: int, sample_no: int) -> bytes:
    base = _base_pdf()
    eof_offset = base.rfind(b"%%EOF")
    if eof_offset < 0:
        raise PerformanceError("PDF_FIXTURE_INVALID")
    marker = (f"% local-performance-{run_id}-{round_no:02d}-{sample_no:02d}\n").encode(
        "ascii"
    )
    payload = base[:eof_offset] + marker + base[eof_offset:]
    if not payload.startswith(b"%PDF") or not payload.rstrip().endswith(b"%%EOF"):
        raise PerformanceError("PDF_FIXTURE_INVALID")
    return payload


def _database_subject() -> tuple[Settings, str, str]:
    settings = Settings()
    run_id = _run_id()
    username = _required_environment("BOOTSTRAP_ADMIN_USERNAME")
    return settings, run_id, username


def seed_database() -> None:
    settings, run_id, username = _database_subject()
    contract_id = _stable_id(run_id, "contract")
    invoice_ids = tuple(
        _stable_id(run_id, "invoice", index)
        for index in range(1, _ROUND_COUNT * _AUDIT_TASK_COUNT + 1)
    )
    item_ids = tuple(
        _stable_id(run_id, "invoice-item", index)
        for index in range(1, _ROUND_COUNT * _AUDIT_TASK_COUNT + 1)
    )
    engine = create_application_engine(settings)
    try:
        factory = create_session_factory(engine)
        with factory.begin() as session:
            users = tuple(
                session.scalars(
                    select(User).where(
                        User.username == username,
                        User.deleted_at.is_(None),
                    )
                )
            )
            if len(users) != 1 or users[0].status != "active":
                raise PerformanceError("ADMIN_SUBJECT_INVALID")
            actor = users[0]
            organization = session.get(Organization, actor.organization_id)
            if (
                organization is None
                or organization.status != "active"
                or organization.deleted_at is not None
            ):
                raise PerformanceError("ORGANIZATION_SUBJECT_INVALID")
            existing_ids = tuple(
                session.scalars(select(Contract.id).where(Contract.id == contract_id))
            ) + tuple(
                session.scalars(select(Invoice.id).where(Invoice.id.in_(invoice_ids)))
            )
            if existing_ids:
                raise PerformanceError("PERFORMANCE_SEED_COLLISION")
            now = session.scalar(select(func.clock_timestamp()))
            if now is None:
                raise PerformanceError("DATABASE_CLOCK_UNAVAILABLE")
            seller_tax_number = f"LPSELLER{run_id[:20].upper()}"
            session.add(
                Contract(
                    id=contract_id,
                    organization_id=organization.id,
                    contract_no=f"LP-{run_id[:16].upper()}",
                    name="本地性能基线合成合同",
                    party_a_name=organization.name,
                    party_a_tax_no=organization.tax_number,
                    party_b_name="本地性能基线合成供应商",
                    party_b_tax_no=seller_tax_number,
                    supplier_id=None,
                    amount=Decimal("9000.00"),
                    currency="CNY",
                    signed_date=date(2026, 1, 1),
                    effective_date=date(2026, 1, 1),
                    expiry_date=date(2027, 12, 31),
                    payment_method=None,
                    payment_terms=None,
                    confirmation_status="confirmed",
                    status="active",
                    confirmed_by=actor.id,
                    confirmed_at=now,
                    critical_fact_hash=hashlib.sha256(
                        f"{run_id}:contract".encode("ascii")
                    ).hexdigest(),
                    row_version=1,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )
            session.flush()
            for index, (invoice_id, item_id) in enumerate(
                zip(invoice_ids, item_ids, strict=True), start=1
            ):
                amount = Decimal("100.00") + Decimal(index)
                tax = (amount * Decimal("0.06")).quantize(Decimal("0.01"))
                total = amount + tax
                invoice = Invoice(
                    id=invoice_id,
                    organization_id=organization.id,
                    invoice_code=f"LP{run_id[:12].upper()}",
                    invoice_number=f"{index:08d}",
                    invoice_type="vat_special",
                    is_red_invoice=False,
                    invoice_date=_BASELINE_DATE - timedelta(days=index),
                    buyer_name=organization.name,
                    buyer_tax_no=organization.tax_number,
                    seller_name="本地性能基线合成供应商",
                    seller_tax_no=seller_tax_number,
                    supplier_id=None,
                    amount_excluding_tax=amount,
                    tax_amount=tax,
                    total_amount=total,
                    currency="CNY",
                    confirmation_status="unconfirmed",
                    duplicate_status="unique",
                    status="draft",
                    field_evidence_json={},
                    confirmed_by=None,
                    confirmed_at=None,
                    critical_fact_hash=hashlib.sha256(
                        f"{run_id}:invoice:{index}".encode("ascii")
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
                        item_name="本地性能基线服务费",
                        specification=None,
                        unit=None,
                        quantity=Decimal("1.000000"),
                        unit_price=amount.quantize(Decimal("0.000001")),
                        amount_excluding_tax=amount,
                        tax_rate=Decimal("0.060000"),
                        tax_amount=tax,
                        total_amount=total,
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
                application_release="local-performance-v2",
                change_reason="publish local performance baseline catalog",
            )
    finally:
        engine.dispose()


def _client_profile() -> tuple[str, str, str, str, str]:
    base_url = _required_environment("FINAUDIT_SMOKE_BASE_URL")
    origin = _required_environment("AUTH_PUBLIC_ORIGIN")
    username = _required_environment("BOOTSTRAP_ADMIN_USERNAME")
    run_id = _run_id()
    if base_url != "http://frontend:8443" or not origin.startswith("http://localhost:"):
        raise PerformanceError("CLIENT_PROFILE_INVALID")
    return base_url, origin, origin.removeprefix("http://"), username, run_id


def _client(
    base_url: str,
    origin: str,
    host: str,
    *,
    timeout_seconds: float = 15.0,
) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        verify=False,
        timeout=httpx.Timeout(timeout_seconds),
        headers={"Origin": origin, "Host": host},
    )


def _measure_lists(client: httpx.Client, authorization: dict[str, str]) -> list[float]:
    samples: list[float] = []
    for _ in range(_LIST_SAMPLE_COUNT):
        started = time.perf_counter()
        response = client.get(
            "/api/v1/audit-tasks?page_size=100",
            headers=authorization,
        )
        data = _require_envelope(response, 200)
        elapsed = time.perf_counter() - started
        if type(data.get("items")) is not list or data.get("page_size") != 100:
            raise PerformanceError("AUDIT_LIST_CONTRACT_INVALID")
        samples.append(elapsed)
    return samples


def _wait_for_scan_only_files(
    client: httpx.Client,
    authorization: dict[str, str],
    accepted: tuple[tuple[UUID, float, bytes], ...],
) -> list[float]:
    if not accepted:
        raise PerformanceError("UPLOAD_IDENTITY_MISSING")
    pending = {file_id: (started, payload) for file_id, started, payload in accepted}
    if len(pending) != len(accepted):
        raise PerformanceError("UPLOAD_FILE_ID_DUPLICATED")
    processing_samples: list[float] = []
    deadline = time.monotonic() + _JOB_TIMEOUT_SECONDS
    while pending and time.monotonic() < deadline:
        for file_id in tuple(pending):
            response = client.get(f"/api/v1/files/{file_id}", headers=authorization)
            data = _require_envelope(response, 200)
            status = data.get("job_status")
            if status in {"failed", "cancelled"}:
                raise PerformanceError("UPLOAD_JOB_FAILED")
            if status == "succeeded":
                if (
                    data.get("status") != "stored"
                    or data.get("security_scan_status") != "clean"
                ):
                    raise PerformanceError("UPLOAD_JOB_RESULT_INVALID")
                started, _payload = pending.pop(file_id)
                processing_samples.append(time.perf_counter() - started)
        if pending:
            time.sleep(_POLL_INTERVAL_SECONDS)
    if pending or len(processing_samples) != len(accepted):
        raise PerformanceError("UPLOAD_JOB_TIMEOUT")

    preview_id, _started, preview_payload = accepted[-1]
    preview = client.get(f"/api/v1/files/{preview_id}/preview", headers=authorization)
    if (
        preview.status_code != 200
        or preview.content != preview_payload
        or preview.headers.get("etag")
        != f'"{hashlib.sha256(preview_payload).hexdigest()}"'
        or preview.headers.get("x-file-status") != "stored"
    ):
        raise PerformanceError("UPLOAD_PREVIEW_INVALID")
    return processing_samples


def _measure_uploads(
    client: httpx.Client,
    authorization: dict[str, str],
    run_id: str,
    round_no: int,
) -> tuple[list[float], list[float]]:
    accepted: list[tuple[UUID, float, bytes]] = []
    acceptance_samples: list[float] = []
    for sample_no in range(1, _UPLOAD_SAMPLE_COUNT + 1):
        payload = _performance_pdf(run_id, round_no, sample_no)
        started = time.perf_counter()
        response = client.post(
            "/api/v1/files",
            headers={
                **authorization,
                "Idempotency-Key": (
                    f"local-performance-file.{run_id}.{round_no}.{sample_no}"
                ),
            },
            data={
                "intended_business_type": "contract",
                "auto_process_requested": "false",
            },
            files={
                "file": (
                    f"local-performance-{round_no:02d}-{sample_no:02d}.pdf",
                    payload,
                    "application/pdf",
                )
            },
        )
        data = _require_envelope(response, 202)
        elapsed = time.perf_counter() - started
        file_id = _canonical_uuid(data.get("file_id"), "UPLOAD_FILE_ID_INVALID")
        _canonical_uuid(data.get("job_id"), "UPLOAD_JOB_ID_INVALID")
        acceptance_samples.append(elapsed)
        accepted.append((file_id, started, payload))

    processing_samples = _wait_for_scan_only_files(
        client,
        authorization,
        tuple(accepted),
    )
    return acceptance_samples, processing_samples


def _measure_batch(
    client: httpx.Client,
    authorization: dict[str, str],
    run_id: str,
    *,
    key_suffix: str,
    uploads: tuple[tuple[str, bytes, str], ...],
    expected_rejections: dict[int, tuple[int, str]] | None = None,
) -> tuple[float, float, list[float], tuple[tuple[UUID, UUID], ...]]:
    rejections = expected_rejections or {}
    expected_names = tuple(name for name, _payload, _mime in uploads)
    multipart = [("files", (name, payload, mime)) for name, payload, mime in uploads]
    headers = {
        **authorization,
        "Idempotency-Key": f"local-performance-batch.{run_id}.{key_suffix}",
    }
    form = {
        "intended_business_type": "contract",
        "auto_process_requested": "false",
    }

    started = time.perf_counter()
    response = client.post(
        "/api/v1/files/batch",
        headers=headers,
        data=form,
        files=multipart,
    )
    data = _require_envelope(response, 207)
    acceptance_seconds = time.perf_counter() - started
    identities = _validate_batch_response(
        data,
        expected_count=len(uploads),
        expected_replayed=False,
        expected_rejections=rejections,
        expected_names=expected_names,
    )

    replay_started = time.perf_counter()
    replay_response = client.post(
        "/api/v1/files/batch",
        headers=headers,
        data=form,
        files=multipart,
    )
    replay_data = _require_envelope(replay_response, 207)
    replay_seconds = time.perf_counter() - replay_started
    replay_identities = _validate_batch_response(
        replay_data,
        expected_count=len(uploads),
        expected_replayed=True,
        expected_rejections=rejections,
        expected_names=expected_names,
    )
    if replay_identities != identities:
        raise PerformanceError("BATCH_REPLAY_IDENTITY_CHANGED")
    if (
        acceptance_seconds > _UPLOAD_ACCEPTANCE_P95_LIMIT_SECONDS
        or replay_seconds > _UPLOAD_ACCEPTANCE_P95_LIMIT_SECONDS
    ):
        raise PerformanceError("BATCH_ACCEPTANCE_THRESHOLD_EXCEEDED")

    accepted_uploads = tuple(
        upload for index, upload in enumerate(uploads) if index not in rejections
    )
    accepted = tuple(
        (file_id, started, upload[1])
        for (file_id, _job_id), upload in zip(
            identities,
            accepted_uploads,
            strict=True,
        )
    )
    processing_samples = _wait_for_scan_only_files(client, authorization, accepted)
    return acceptance_seconds, replay_seconds, processing_samples, identities


def _measure_max_batch(
    client: httpx.Client,
    authorization: dict[str, str],
    run_id: str,
    round_no: int,
) -> tuple[float, float, list[float], tuple[tuple[UUID, UUID], ...]]:
    uploads = tuple(
        (
            _batch_file_name(run_id, round_no, item_no),
            _performance_pdf(run_id, round_no, _UPLOAD_SAMPLE_COUNT + item_no),
            "application/pdf",
        )
        for item_no in range(1, _BATCH_FILE_COUNT + 1)
    )
    return _measure_batch(
        client,
        authorization,
        run_id,
        key_suffix=f"max.{round_no}",
        uploads=uploads,
    )


def _measure_partial_failure_batch(
    client: httpx.Client,
    authorization: dict[str, str],
    run_id: str,
) -> tuple[float, float, list[float], tuple[tuple[UUID, UUID], ...]]:
    uploads = (
        (
            f"local-performance-partial-{run_id[:12]}-valid.pdf",
            _performance_pdf(run_id, 99, 1),
            "application/pdf",
        ),
        (
            f"local-performance-partial-{run_id[:12]}-invalid.txt",
            b"unsupported local performance fixture",
            "text/plain",
        ),
    )
    return _measure_batch(
        client,
        authorization,
        run_id,
        key_suffix="partial",
        uploads=uploads,
        expected_rejections={1: (400, "FILE_FORMAT_NOT_SUPPORTED")},
    )


def _measure_over_limit_batch(
    client: httpx.Client,
    authorization: dict[str, str],
    run_id: str,
) -> float:
    multipart = [
        (
            "files",
            (
                f"local-performance-over-limit-{run_id[:12]}-{item_no:02d}.pdf",
                _performance_pdf(run_id, 98, item_no),
                "application/pdf",
            ),
        )
        for item_no in range(1, _BATCH_FILE_COUNT + 2)
    ]
    started = time.perf_counter()
    response = client.post(
        "/api/v1/files/batch",
        headers={
            **authorization,
            "Idempotency-Key": f"local-performance-batch.{run_id}.over-limit",
        },
        data={
            "intended_business_type": "contract",
            "auto_process_requested": "false",
        },
        files=multipart,
    )
    elapsed = time.perf_counter() - started
    _validate_batch_limit_response(response)
    if elapsed > _UPLOAD_ACCEPTANCE_P95_LIMIT_SECONDS:
        raise PerformanceError("BATCH_LIMIT_REJECTION_THRESHOLD_EXCEEDED")
    return elapsed


def _post_audit_task(
    *,
    base_url: str,
    origin: str,
    host: str,
    authorization: dict[str, str],
    barrier: threading.Barrier,
    run_id: str,
    round_no: int,
    task_no: int,
) -> tuple[UUID, UUID, UUID, float, float]:
    invoice_index = (round_no - 1) * _AUDIT_TASK_COUNT + task_no
    contract_id = _stable_id(run_id, "contract")
    invoice_id = _stable_id(run_id, "invoice", invoice_index)
    with _client(base_url, origin, host) as client:
        try:
            barrier.wait(timeout=15)
        except threading.BrokenBarrierError:
            raise PerformanceError("AUDIT_CONCURRENCY_BARRIER_FAILED") from None
        started = time.perf_counter()
        response = client.post(
            "/api/v1/audit-tasks",
            headers={
                **authorization,
                "Idempotency-Key": (
                    f"local-performance-audit.{run_id}.{round_no}.{task_no}"
                ),
            },
            json={
                "task_no": f"{_task_prefix(run_id)}{round_no}-{task_no}",
                "name": f"本地性能基线审核 {round_no}-{task_no}",
                "description": "本地性能门禁专用合成任务",
                "baseline_date": _BASELINE_DATE.isoformat(),
                "contract_id": str(contract_id),
                "invoice_ids": [str(invoice_id)],
            },
        )
        data = _require_envelope(response, 202)
        accepted_at = time.perf_counter()
    task = data.get("task")
    execution = data.get("execution")
    if not isinstance(task, dict) or not isinstance(execution, dict):
        raise PerformanceError("AUDIT_CREATE_CONTRACT_INVALID")
    task_id = _canonical_uuid(task.get("id"), "AUDIT_TASK_ID_INVALID")
    execution_id = _canonical_uuid(execution.get("id"), "AUDIT_EXECUTION_ID_INVALID")
    job_id = _canonical_uuid(execution.get("job_id"), "AUDIT_JOB_ID_INVALID")
    if execution.get("status") != "queued":
        raise PerformanceError("AUDIT_INITIAL_STATUS_INVALID")
    return task_id, execution_id, job_id, started, accepted_at - started


def _measure_concurrent_audits(
    client: httpx.Client,
    *,
    base_url: str,
    origin: str,
    host: str,
    authorization: dict[str, str],
    run_id: str,
    round_no: int,
) -> tuple[list[float], list[float], tuple[tuple[UUID, UUID, UUID], ...]]:
    barrier = threading.Barrier(_AUDIT_TASK_COUNT + 1)
    with ThreadPoolExecutor(max_workers=_AUDIT_TASK_COUNT) as executor:
        futures = tuple(
            executor.submit(
                _post_audit_task,
                base_url=base_url,
                origin=origin,
                host=host,
                authorization=authorization,
                barrier=barrier,
                run_id=run_id,
                round_no=round_no,
                task_no=task_no,
            )
            for task_no in range(1, _AUDIT_TASK_COUNT + 1)
        )
        try:
            barrier.wait(timeout=15)
        except threading.BrokenBarrierError:
            raise PerformanceError("AUDIT_CONCURRENCY_BARRIER_FAILED") from None
        created = tuple(future.result() for future in futures)

    identities = tuple(
        (task_id, execution_id, job_id)
        for task_id, execution_id, job_id, _, _ in created
    )
    if (
        len({item[0] for item in identities}) != _AUDIT_TASK_COUNT
        or len({item[1] for item in identities}) != _AUDIT_TASK_COUNT
        or len({item[2] for item in identities}) != _AUDIT_TASK_COUNT
    ):
        raise PerformanceError("AUDIT_IDENTITY_DUPLICATED")
    pending = {
        execution_id: started
        for _task_id, execution_id, _job_id, started, _accepted in created
    }
    execution_samples: list[float] = []
    deadline = time.monotonic() + _JOB_TIMEOUT_SECONDS
    while pending and time.monotonic() < deadline:
        for execution_id in tuple(pending):
            response = client.get(
                f"/api/v1/audit-executions/{execution_id}",
                headers=authorization,
            )
            data = _require_envelope(response, 200)
            execution = data.get("execution")
            if not isinstance(execution, dict):
                raise PerformanceError("AUDIT_EXECUTION_CONTRACT_INVALID")
            status = execution.get("status")
            if status in {"failed", "cancelled", "outdated"}:
                raise PerformanceError("AUDIT_JOB_FAILED")
            if status == "pending_finance_review":
                started = pending.pop(execution_id)
                execution_samples.append(time.perf_counter() - started)
        if pending:
            time.sleep(_POLL_INTERVAL_SECONDS)
    if pending or len(execution_samples) != _AUDIT_TASK_COUNT:
        raise PerformanceError("AUDIT_JOB_TIMEOUT")
    return (
        [item[4] for item in created],
        execution_samples,
        identities,
    )


def run_client() -> dict[str, object]:
    base_url, origin, host, username, run_id = _client_profile()
    password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    rounds: list[dict[str, object]] = []
    all_audit_identities: set[UUID] = set()
    all_batch_identities: set[UUID] = set()
    with _client(base_url, origin, host) as client:
        admin_token = _login(client, username, password)
        reviewer_username = f"perf-{run_id[:12]}"
        reviewer_password = validate_new_password(
            f"{password}-performance-{run_id[:12]}"
        )
        created_user = client.post(
            "/api/v1/users",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Idempotency-Key": f"local-performance-user.{run_id}",
            },
            json={
                "username": reviewer_username,
                "display_name": "本地性能门禁财务复核员",
                "initial_password": reviewer_password,
                "fixed_roles": ["finance_reviewer"],
            },
        )
        _require_envelope(created_user, 201)
        access_token = _login(client, reviewer_username, reviewer_password)
        authorization = {"Authorization": f"Bearer {access_token}"}
        _require_envelope(
            client.get("/api/v1/audit-tasks?page_size=100", headers=authorization),
            200,
        )
        for round_no in range(1, _ROUND_COUNT + 1):
            list_samples = _measure_lists(client, authorization)
            upload_acceptance, upload_processing = _measure_uploads(
                client, authorization, run_id, round_no
            )
            (
                batch_acceptance,
                batch_replay_acceptance,
                batch_processing,
                batch_identities,
            ) = _measure_max_batch(client, authorization, run_id, round_no)
            audit_acceptance, audit_execution, identities = _measure_concurrent_audits(
                client,
                base_url=base_url,
                origin=origin,
                host=host,
                authorization=authorization,
                run_id=run_id,
                round_no=round_no,
            )
            for audit_identity_group in identities:
                for identity in audit_identity_group:
                    if identity in all_audit_identities:
                        raise PerformanceError("CROSS_ROUND_IDENTITY_DUPLICATED")
                    all_audit_identities.add(identity)
            for batch_identity_group in batch_identities:
                for identity in batch_identity_group:
                    if identity in all_batch_identities:
                        raise PerformanceError("CROSS_ROUND_BATCH_IDENTITY_DUPLICATED")
                    all_batch_identities.add(identity)
            list_p95 = _p95(list_samples)
            upload_acceptance_p95 = _p95(upload_acceptance)
            if list_p95 > _LIST_P95_LIMIT_SECONDS:
                raise PerformanceError("LIST_P95_THRESHOLD_EXCEEDED")
            if upload_acceptance_p95 > _UPLOAD_ACCEPTANCE_P95_LIMIT_SECONDS:
                raise PerformanceError("UPLOAD_ACCEPTANCE_P95_THRESHOLD_EXCEEDED")
            rounds.append(
                {
                    "round": round_no,
                    "list_samples": len(list_samples),
                    "list_p95_ms": round(list_p95 * 1000, 3),
                    "upload_acceptance_samples": len(upload_acceptance),
                    "upload_acceptance_p95_ms": round(upload_acceptance_p95 * 1000, 3),
                    "scan_only_processing_samples": len(upload_processing),
                    "scan_only_processing_p95_ms": round(
                        _p95(upload_processing) * 1000, 3
                    ),
                    "batch_file_count": len(batch_identities),
                    "batch_acceptance_ms": round(batch_acceptance * 1000, 3),
                    "batch_replay_acceptance_ms": round(
                        batch_replay_acceptance * 1000,
                        3,
                    ),
                    "batch_scan_only_processing_samples": len(batch_processing),
                    "batch_scan_only_processing_p95_ms": round(
                        _p95(batch_processing) * 1000,
                        3,
                    ),
                    "audit_tasks": len(audit_execution),
                    "audit_acceptance_p95_ms": round(_p95(audit_acceptance) * 1000, 3),
                    "audit_execution_p95_ms": round(_p95(audit_execution) * 1000, 3),
                }
            )
        (
            partial_acceptance,
            partial_replay_acceptance,
            partial_processing,
            partial_identities,
        ) = _measure_partial_failure_batch(client, authorization, run_id)
        for partial_identity_group in partial_identities:
            for identity in partial_identity_group:
                if identity in all_batch_identities:
                    raise PerformanceError("PARTIAL_BATCH_IDENTITY_DUPLICATED")
                all_batch_identities.add(identity)
        over_limit_rejection = _measure_over_limit_batch(client, authorization, run_id)
    return {
        "schema_version": _SCHEMA_VERSION,
        "round_count": _ROUND_COUNT,
        "list_p95_limit_ms": int(_LIST_P95_LIMIT_SECONDS * 1000),
        "upload_acceptance_p95_limit_ms": int(
            _UPLOAD_ACCEPTANCE_P95_LIMIT_SECONDS * 1000
        ),
        "rounds": rounds,
        "partial_batch": {
            "file_count": 2,
            "accepted_count": len(partial_identities),
            "rejected_count": 1,
            "acceptance_ms": round(partial_acceptance * 1000, 3),
            "replay_acceptance_ms": round(partial_replay_acceptance * 1000, 3),
            "scan_only_processing_ms": round(partial_processing[0] * 1000, 3),
        },
        "over_limit_batch": {
            "file_count": _BATCH_FILE_COUNT + 1,
            "http_status": 413,
            "rejection_ms": round(over_limit_rejection * 1000, 3),
        },
        "scope": {
            "transport": _TRANSPORT_SCOPE,
            "scanner": "local-clamav-scan-only",
            "batch_upload": (
                "default-max-20-idempotent-replay-partial-failure-and-limit-rejection"
            ),
            "audit": "database-seeded-facts-api-dispatcher-worker",
            "ocr": "not_run",
            "ai_provider": "disabled",
            "production": "not_run",
        },
    }


def verify_database() -> None:
    settings, run_id, username = _database_subject()
    reviewer_username = f"perf-{run_id[:12]}"
    expected_task_numbers = {
        f"{_task_prefix(run_id)}{round_no}-{task_no}"
        for round_no in range(1, _ROUND_COUNT + 1)
        for task_no in range(1, _AUDIT_TASK_COUNT + 1)
    }
    expected_batch_file_names = {
        _batch_file_name(run_id, round_no, item_no)
        for round_no in range(1, _ROUND_COUNT + 1)
        for item_no in range(1, _BATCH_FILE_COUNT + 1)
    }
    expected_file_names = expected_batch_file_names | {
        f"local-performance-partial-{run_id[:12]}-valid.pdf"
    }
    rejected_over_limit_names = {
        f"local-performance-over-limit-{run_id[:12]}-{item_no:02d}.pdf"
        for item_no in range(1, _BATCH_FILE_COUNT + 2)
    }
    engine = create_application_engine(settings)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            actor = session.scalar(
                select(User).where(
                    User.username == username,
                    User.deleted_at.is_(None),
                )
            )
            if actor is None:
                raise PerformanceError("ADMIN_SUBJECT_INVALID")
            reviewer = session.scalar(
                select(User).where(
                    User.organization_id == actor.organization_id,
                    User.username == reviewer_username,
                    User.deleted_at.is_(None),
                )
            )
            if reviewer is None or reviewer.status != "active":
                raise PerformanceError("REVIEWER_SUBJECT_INVALID")
            batch_files = tuple(
                session.scalars(
                    select(FileRecord).where(
                        FileRecord.organization_id == actor.organization_id,
                        FileRecord.original_name.in_(expected_file_names),
                        FileRecord.deleted_at.is_(None),
                    )
                )
            )
            batch_file_ids = tuple(file.id for file in batch_files)
            batch_jobs = tuple(
                session.scalars(
                    select(AsyncJob).where(
                        AsyncJob.organization_id == actor.organization_id,
                        AsyncJob.resource_type == "file",
                        AsyncJob.resource_id.in_(batch_file_ids),
                    )
                )
            )
            batch_job_ids = tuple(job.id for job in batch_jobs)
            batch_steps = tuple(
                session.scalars(
                    select(AsyncJobStep).where(AsyncJobStep.job_id.in_(batch_job_ids))
                )
            )
            batch_outbox = tuple(
                session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_type == "async_job",
                        OutboxEvent.aggregate_id.in_(batch_job_ids),
                    )
                )
            )
            rejected_over_limit_files = tuple(
                session.scalars(
                    select(FileRecord).where(
                        FileRecord.organization_id == actor.organization_id,
                        FileRecord.original_name.in_(rejected_over_limit_names),
                    )
                )
            )
            tasks = tuple(
                session.scalars(
                    select(AuditTask).where(
                        AuditTask.organization_id == actor.organization_id,
                        AuditTask.task_no.in_(expected_task_numbers),
                        AuditTask.deleted_at.is_(None),
                    )
                )
            )
            task_ids = tuple(task.id for task in tasks)
            executions = tuple(
                session.scalars(
                    select(AuditTaskExecution).where(
                        AuditTaskExecution.audit_task_id.in_(task_ids)
                    )
                )
            )
            execution_ids = tuple(execution.id for execution in executions)
            job_ids = tuple(
                execution.job_id for execution in executions if execution.job_id
            )
            items = tuple(
                session.scalars(
                    select(AuditTaskItem).where(
                        AuditTaskItem.audit_task_id.in_(task_ids)
                    )
                )
            )
            snapshots = tuple(
                session.scalars(
                    select(AuditTaskSnapshot).where(
                        AuditTaskSnapshot.execution_id.in_(execution_ids)
                    )
                )
            )
            rules = tuple(
                session.scalars(
                    select(RuleExecution).where(
                        RuleExecution.execution_id.in_(execution_ids)
                    )
                )
            )
            jobs = tuple(
                session.scalars(select(AsyncJob).where(AsyncJob.id.in_(job_ids)))
            )
            steps = tuple(
                session.scalars(
                    select(AsyncJobStep).where(AsyncJobStep.job_id.in_(job_ids))
                )
            )
            outbox = tuple(
                session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_type == "async_job",
                        OutboxEvent.aggregate_id.in_(job_ids),
                    )
                )
            )
    finally:
        engine.dispose()

    expected_batch_fact_count = _ROUND_COUNT * _BATCH_FILE_COUNT + 1
    if rejected_over_limit_files:
        raise PerformanceError("BATCH_LIMIT_DATABASE_SIDE_EFFECT")
    batch_step_counts = {
        job_id: sum(
            step.job_id == job_id
            and step.attempt_no == 1
            and step.step_code == "scan"
            and step.status == "succeeded"
            for step in batch_steps
        )
        for job_id in batch_job_ids
    }
    if (
        len(batch_files) != expected_batch_fact_count
        or {file.original_name for file in batch_files} != expected_file_names
        or len(batch_jobs) != expected_batch_fact_count
        or len({job.resource_id for job in batch_jobs}) != expected_batch_fact_count
        or len(batch_steps) != expected_batch_fact_count
        or len(batch_outbox) != expected_batch_fact_count
    ):
        raise PerformanceError("BATCH_DATABASE_CARDINALITY_INVALID")
    if any(
        file.uploaded_by != reviewer.id
        or file.status != "stored"
        or file.security_scan_status != "clean"
        or file.intended_business_type != "contract"
        or file.auto_process_requested is not False
        or file.original_minio_bucket is None
        or file.original_minio_object_key is None
        or file.archived_at is not None
        or file.rejection_code is not None
        for file in batch_files
    ):
        raise PerformanceError("BATCH_DATABASE_FILE_STATE_INVALID")
    if any(
        job.job_type != "file_scan"
        or job.resource_type != "file"
        or job.resource_id not in set(batch_file_ids)
        or job.status != "succeeded"
        or job.attempt_no != 1
        or job.error_code is not None
        or batch_step_counts.get(job.id) != 1
        for job in batch_jobs
    ):
        raise PerformanceError("BATCH_DATABASE_JOB_STATE_INVALID")
    if any(
        event.event_type != "job.dispatch.requested"
        or event.status != "published"
        or event.attempt_count < 1
        for event in batch_outbox
    ):
        raise PerformanceError("BATCH_DATABASE_OUTBOX_STATE_INVALID")

    expected_count = _ROUND_COUNT * _AUDIT_TASK_COUNT
    execution_by_task = {execution.audit_task_id: execution for execution in executions}
    item_counts = {
        task_id: sum(item.audit_task_id == task_id for item in items)
        for task_id in task_ids
    }
    invoice_ids = {
        item.invoice_id
        for item in items
        if item.item_type == "invoice" and item.invoice_id
    }
    rule_counts = {
        execution_id: sum(rule.execution_id == execution_id for rule in rules)
        for execution_id in execution_ids
    }
    step_counts = {
        job_id: sum(
            step.job_id == job_id
            and step.attempt_no == 1
            and step.step_code == "evaluate"
            and step.status == "succeeded"
            for step in steps
        )
        for job_id in job_ids
    }
    if (
        len(tasks) != expected_count
        or {task.task_no for task in tasks} != expected_task_numbers
        or len(executions) != expected_count
        or len(job_ids) != expected_count
        or len(set(job_ids)) != expected_count
        or len(snapshots) != expected_count
        or len(rules) != expected_count * 15
        or len(jobs) != expected_count
        or len(steps) != expected_count
        or len(outbox) != expected_count
        or len(items) != expected_count * 2
        or len(invoice_ids) != expected_count
    ):
        raise PerformanceError("DATABASE_CARDINALITY_INVALID")
    if any(
        task.status != "open"
        or task.current_execution_id is None
        or task.id not in execution_by_task
        or task.current_execution_id != execution_by_task[task.id].id
        or item_counts.get(task.id) != 2
        for task in tasks
    ):
        raise PerformanceError("DATABASE_TASK_STATE_INVALID")
    if any(
        execution.version_no != 1
        or execution.status != "pending_finance_review"
        or execution.job_id is None
        or execution.snapshot_sha256 is None
        or rule_counts.get(execution.id) != 15
        for execution in executions
    ):
        raise PerformanceError("DATABASE_EXECUTION_STATE_INVALID")
    if any(
        job.job_type != "audit_execute"
        or job.resource_type != "audit_task_execution"
        or job.resource_id not in set(execution_ids)
        or job.status != "succeeded"
        or job.attempt_no != 1
        or step_counts.get(job.id) != 1
        for job in jobs
    ):
        raise PerformanceError("DATABASE_JOB_STATE_INVALID")
    if any(event.status != "published" or event.attempt_count < 1 for event in outbox):
        raise PerformanceError("DATABASE_OUTBOX_STATE_INVALID")


def main() -> int:
    try:
        if sys.argv == [sys.argv[0], "seed"]:
            seed_database()
            print("LOCAL_PERFORMANCE_SEED_GATE=PASS")
        elif sys.argv == [sys.argv[0], "client"]:
            result = run_client()
            print(
                "LOCAL_PERFORMANCE_RESULT_JSON="
                + json.dumps(
                    result,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            print("LOCAL_PERFORMANCE_LIST_THRESHOLD_GATE=PASS")
            print("LOCAL_PERFORMANCE_UPLOAD_ACCEPTANCE_GATE=PASS")
            print("LOCAL_PERFORMANCE_SCAN_ONLY_WORKER_GATE=PASS")
            print("LOCAL_PERFORMANCE_BATCH_MAX_GATE=PASS")
            print("LOCAL_PERFORMANCE_BATCH_REPLAY_GATE=PASS")
            print("LOCAL_PERFORMANCE_BATCH_PARTIAL_FAILURE_GATE=PASS")
            print("LOCAL_PERFORMANCE_BATCH_LIMIT_GATE=PASS")
            print("LOCAL_PERFORMANCE_AUDIT_CONCURRENCY_GATE=PASS")
            print("LOCAL_PERFORMANCE_CLIENT_GATE=PASS")
        elif sys.argv == [sys.argv[0], "database"]:
            verify_database()
            print("LOCAL_PERFORMANCE_BATCH_DATABASE_GATE=PASS")
            print("LOCAL_PERFORMANCE_DATABASE_GATE=PASS")
        else:
            raise PerformanceError("ARGUMENTS_INVALID")
    except (PerformanceError, SmokeError) as error:
        print("LOCAL_PERFORMANCE_BASELINE=FAIL")
        print(f"LOCAL_PERFORMANCE_REASON={error}")
        return 1
    except Exception:
        print("LOCAL_PERFORMANCE_BASELINE=FAIL")
        print("LOCAL_PERFORMANCE_REASON=UNEXPECTED_FAILURE")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
