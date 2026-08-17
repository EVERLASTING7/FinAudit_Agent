from __future__ import annotations

import os
from pathlib import Path
from queue import Empty, Queue
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from celery.contrib.testing.worker import start_worker  # type: ignore[import-untyped]

from app.repositories.job_runtime import JobSnapshot, OutboxClaim
from app.services.file_job_executor import FileJobExecutionResult
from app.services.job_dispatcher import CeleryJobMessagePublisher
from app.workers.bootstrap import create_celery_app
from app.workers.file_handler_registry import (
    FILE_HANDLER_REGISTRY_HASH,
    FILE_HANDLER_REGISTRY_VERSION,
)
from app.workers.messages import JOB_EVENT_SCHEMA_VERSION
from app.workers.runtime import FileWorkerRuntime
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401 - fixture registration
    build_startup_settings,
)

pytestmark = pytest.mark.integration

_BROKER_URL_ENV = "TEST_CELERY_BROKER_URL"
_CONFIRMATION_ENV = "FINAUDIT_ALLOW_LOCAL_CELERY_REDIS_TEST"


def _broker_url() -> str:
    raw_url = os.environ.get(_BROKER_URL_ENV)
    if raw_url is None:
        pytest.skip("real Celery/Redis integration is explicitly opt-in")
    if os.environ.get(_CONFIRMATION_ENV) != "isolated-loopback-redis":
        pytest.fail("local Celery/Redis integration confirmation is invalid", pytrace=False)
    parsed = urlsplit(raw_url)
    if (
        parsed.scheme != "redis"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.username not in (None, "")
        or parsed.password is None
        or parsed.path != "/0"
        or parsed.query
        or parsed.fragment
    ):
        pytest.fail("local Celery/Redis integration profile is unsafe", pytrace=False)
    return raw_url


def _claim(*, job_id: UUID, file_id: UUID, event_id: UUID) -> OutboxClaim:
    organization_id = uuid4()
    trace_id = uuid4()
    return OutboxClaim(
        outbox_id=uuid4(),
        event_id=event_id,
        job=JobSnapshot(
            id=job_id,
            organization_id=organization_id,
            job_type="file_process",
            resource_type="file",
            resource_id=file_id,
            status="queued",
            attempt_no=0,
            max_attempts=3,
            current_attempt_start_step_code="scan",
            input_json={
                "auto_process_requested": True,
                "file_id": str(file_id),
                "intended_business_type": "contract",
                "processing_scope": "full",
                "target_knowledge_base_id": None,
            },
            input_schema_version=1,
            handler_registry_version=FILE_HANDLER_REGISTRY_VERSION,
            handler_registry_hash=FILE_HANDLER_REGISTRY_HASH,
            trace_id=trace_id,
        ),
        event_type="job.dispatch.requested",
        event_version=JOB_EVENT_SCHEMA_VERSION,
        event_sequence=1,
        payload_json={"job_id": str(job_id)},
        attempt_count=1,
        trace_id=trace_id,
    )


def test_real_redis_transports_exact_publisher_envelope_to_document_worker(
    exact_policy_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker_url = _broker_url()
    queue_suffix = uuid4().hex
    settings = build_startup_settings(
        exact_policy_file,
        redis_url=broker_url,
        celery_broker_url=broker_url,
        celery_result_backend=broker_url[:-1] + "1",
        celery_queue_document=f"document-{queue_suffix}",
        celery_queue_extraction=f"extraction-{queue_suffix}",
        celery_queue_knowledge=f"knowledge-{queue_suffix}",
        celery_queue_evaluation=f"evaluation-{queue_suffix}",
        celery_queue_audit=f"audit-{queue_suffix}",
        celery_queue_report=f"report-{queue_suffix}",
        celery_queue_maintenance=f"maintenance-{queue_suffix}",
    )
    calls: Queue[dict[str, object]] = Queue()

    class RecordingExecutor:
        def execute(self, **kwargs: object) -> FileJobExecutionResult:
            calls.put(dict(kwargs))
            return FileJobExecutionResult("succeeded", cast(UUID, kwargs["job_id"]))

    runtime = cast(
        FileWorkerRuntime,
        SimpleNamespace(executor=RecordingExecutor()),
    )
    monkeypatch.setattr(
        "app.workers.tasks.create_file_worker_runtime",
        lambda active_settings: runtime,
    )
    application = create_celery_app(settings)
    application.conf.worker_hijack_root_logger = False
    job_id = uuid4()
    file_id = uuid4()
    event_id = uuid4()

    with start_worker(
        application,
        pool="solo",
        concurrency=1,
        perform_ping_check=False,
        queues=[settings.celery_queue_document],
        hostname="broker-gate@localhost",
        shutdown_timeout=15,
    ):
        CeleryJobMessagePublisher(application).publish(
            _claim(job_id=job_id, file_id=file_id, event_id=event_id),
            task_name="app.workers.tasks.document.execute_job",
            queue_name=settings.celery_queue_document,
        )
        try:
            call = calls.get(timeout=15)
        except Empty:
            pytest.fail("Celery worker did not consume the Redis message", pytrace=False)

    assert call["job_id"] == job_id
    assert call["event_id"] == event_id
    assert call["event_schema_version"] == JOB_EVENT_SCHEMA_VERSION
    worker_id = call["worker_id"]
    assert isinstance(worker_id, str)
    assert 1 <= len(worker_id) <= 100
    assert all(
        character.isascii() and (character.isalnum() or character in "._@:-")
        for character in worker_id
    )
