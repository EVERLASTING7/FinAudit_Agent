from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.repositories.job_runtime import JobSnapshot, OutboxClaim
from app.services.job_dispatcher import (
    CeleryJobMessagePublisher,
    JobMessagePublisher,
    OutboxDispatcher,
)
from app.workers.audit_handler_registry import (
    AUDIT_HANDLER_REGISTRY_HASH,
    AUDIT_HANDLER_REGISTRY_VERSION,
)
from app.workers.contract_handler_registry import (
    CONTRACT_HANDLER_REGISTRY_HASH,
    CONTRACT_HANDLER_REGISTRY_VERSION,
)
from app.workers.file_handler_registry import (
    FILE_HANDLER_REGISTRY_HASH,
    FILE_HANDLER_REGISTRY_VERSION,
)
from app.workers.invoice_handler_registry import (
    INVOICE_HANDLER_REGISTRY_HASH,
    INVOICE_HANDLER_REGISTRY_V1_HASH,
    INVOICE_HANDLER_REGISTRY_V1_VERSION,
    INVOICE_HANDLER_REGISTRY_VERSION,
)
from app.workers.report_handler_registry import (
    REPORT_HANDLER_REGISTRY_HASH,
    REPORT_HANDLER_REGISTRY_VERSION,
)

JOB_ID = UUID("70000000-0000-4000-8000-000000000001")
OUTBOX_ID = UUID("70000000-0000-4000-8000-000000000002")
EVENT_ID = UUID("70000000-0000-4000-8000-000000000003")
ORGANIZATION_ID = UUID("70000000-0000-4000-8000-000000000004")
FILE_ID = UUID("70000000-0000-4000-8000-000000000005")
TRACE_ID = UUID("70000000-0000-4000-8000-000000000006")


class NullSessionFactory:
    def begin(self) -> object:
        raise AssertionError("route resolution does not access the database")


def claim(**job_overrides: object) -> OutboxClaim:
    values: dict[str, object] = {
        "id": JOB_ID,
        "organization_id": ORGANIZATION_ID,
        "job_type": "file_process",
        "resource_type": "file",
        "resource_id": FILE_ID,
        "status": "queued",
        "attempt_no": 0,
        "max_attempts": 3,
        "current_attempt_start_step_code": "scan",
        "input_json": {
            "auto_process_requested": True,
            "file_id": str(FILE_ID),
            "intended_business_type": "contract",
            "processing_scope": "full",
            "target_knowledge_base_id": None,
        },
        "input_schema_version": 1,
        "handler_registry_version": FILE_HANDLER_REGISTRY_VERSION,
        "handler_registry_hash": FILE_HANDLER_REGISTRY_HASH,
        "trace_id": TRACE_ID,
    }
    values.update(job_overrides)
    job = JobSnapshot(**values)  # type: ignore[arg-type]
    return OutboxClaim(
        outbox_id=OUTBOX_ID,
        event_id=EVENT_ID,
        job=job,
        event_type="job.dispatch.requested",
        event_version=1,
        event_sequence=1,
        payload_json={"job_id": str(JOB_ID)},
        attempt_count=1,
        trace_id=TRACE_ID,
    )


def dispatcher() -> OutboxDispatcher:
    settings = cast(
        Settings,
        SimpleNamespace(
            celery_queue_document="queue-document",
            celery_queue_extraction="queue-extraction",
            celery_queue_knowledge="queue-knowledge",
            celery_queue_evaluation="queue-evaluation",
            celery_queue_audit="queue-audit",
            celery_queue_report="queue-report",
            celery_queue_maintenance="queue-maintenance",
        ),
    )
    return OutboxDispatcher(
        cast(sessionmaker[Session], NullSessionFactory()),
        cast(JobMessagePublisher, SimpleNamespace()),
        settings,
    )


def test_dispatcher_resolves_task_and_physical_queue_from_frozen_registry() -> None:
    assert dispatcher()._resolve_route(claim()) == (
        "app.workers.tasks.document.execute_job",
        "queue-document",
    )


def test_dispatcher_resolves_invoice_extraction_registry_to_its_queue() -> None:
    parse_version_id = UUID("70000000-0000-4000-8000-000000000007")
    extraction_claim = claim(
        job_type="invoice_extract",
        current_attempt_start_step_code="extract",
        input_json={
            "file_id": str(FILE_ID),
            "parse_version_id": str(parse_version_id),
        },
        handler_registry_version=INVOICE_HANDLER_REGISTRY_VERSION,
        handler_registry_hash=INVOICE_HANDLER_REGISTRY_HASH,
    )

    assert dispatcher()._resolve_route(extraction_claim) == (
        "app.workers.tasks.extraction.execute_job",
        "queue-extraction",
    )


def test_dispatcher_resolves_contract_extraction_registry_to_its_queue() -> None:
    parse_version_id = UUID("70000000-0000-4000-8000-000000000107")
    extraction_claim = claim(
        job_type="contract_extract",
        current_attempt_start_step_code="extract",
        input_json={
            "file_id": str(FILE_ID),
            "parse_version_id": str(parse_version_id),
        },
        handler_registry_version=CONTRACT_HANDLER_REGISTRY_VERSION,
        handler_registry_hash=CONTRACT_HANDLER_REGISTRY_HASH,
    )

    assert dispatcher()._resolve_route(extraction_claim) == (
        "app.workers.tasks.extraction.execute_job",
        "queue-extraction",
    )


def test_dispatcher_keeps_frozen_invoice_v1_jobs_routable() -> None:
    parse_version_id = UUID("70000000-0000-4000-8000-000000000010")
    legacy_claim = claim(
        job_type="invoice_extract",
        current_attempt_start_step_code="extract",
        input_json={
            "file_id": str(FILE_ID),
            "parse_version_id": str(parse_version_id),
        },
        handler_registry_version=INVOICE_HANDLER_REGISTRY_V1_VERSION,
        handler_registry_hash=INVOICE_HANDLER_REGISTRY_V1_HASH,
    )

    assert dispatcher()._resolve_route(legacy_claim) == (
        "app.workers.tasks.extraction.execute_job",
        "queue-extraction",
    )


def test_dispatcher_resolves_audit_registry_to_its_queue() -> None:
    execution_id = UUID("70000000-0000-4000-8000-000000000008")
    snapshot_id = UUID("70000000-0000-4000-8000-000000000009")
    audit_claim = claim(
        job_type="audit_execute",
        resource_type="audit_task_execution",
        resource_id=execution_id,
        current_attempt_start_step_code="evaluate",
        input_json={
            "execution_id": str(execution_id),
            "snapshot_id": str(snapshot_id),
            "snapshot_sha256": "a" * 64,
        },
        handler_registry_version=AUDIT_HANDLER_REGISTRY_VERSION,
        handler_registry_hash=AUDIT_HANDLER_REGISTRY_HASH,
    )

    assert dispatcher()._resolve_route(audit_claim) == (
        "app.workers.tasks.audit.execute_job",
        "queue-audit",
    )


def test_dispatcher_resolves_report_registry_to_its_queue() -> None:
    execution_id = UUID("70000000-0000-4000-8000-000000000011")
    report_id = UUID("70000000-0000-4000-8000-000000000012")
    report_claim = claim(
        job_type="report_generate",
        resource_type="audit_report",
        resource_id=report_id,
        current_attempt_start_step_code="generate",
        input_json={
            "report_id": str(report_id),
            "execution_id": str(execution_id),
            "payload_sha256": "a" * 64,
        },
        handler_registry_version=REPORT_HANDLER_REGISTRY_VERSION,
        handler_registry_hash=REPORT_HANDLER_REGISTRY_HASH,
    )

    assert dispatcher()._resolve_route(report_claim) == (
        "app.workers.tasks.report.execute_job",
        "queue-report",
    )


def test_celery_publisher_serializes_the_strict_canonical_message() -> None:
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    class RecordingApplication:
        def send_task(self, name: str, *args: object, **kwargs: object) -> object:
            calls.append((name, args, kwargs))
            return object()

    CeleryJobMessagePublisher(RecordingApplication()).publish(
        claim(),
        task_name="app.workers.tasks.document.execute_job",
        queue_name="queue-document",
    )

    assert len(calls) == 1
    task_name, args, kwargs = calls[0]
    assert task_name == "app.workers.tasks.document.execute_job"
    assert args == ()
    assert kwargs["kwargs"] == {
        "job_id": str(JOB_ID),
        "event_schema_version": 1,
    }
    assert kwargs["task_id"] == str(EVENT_ID)
    assert kwargs["queue"] == "queue-document"


@pytest.mark.parametrize(
    "overrides",
    [
        {"job_type": "unknown"},
        {"input_schema_version": 2},
        {"handler_registry_hash": "f" * 64},
        {"input_json": {}},
    ],
)
def test_dispatcher_fails_closed_for_uninstalled_or_drifted_job(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="HANDLER_REGISTRY_INVALID"):
        dispatcher()._resolve_route(claim(**overrides))
