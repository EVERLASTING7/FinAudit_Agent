"""Celery task 注册和消息包络门禁。"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from typing import Protocol, TypeVar
from uuid import UUID

from celery.exceptions import Reject  # type: ignore[import-untyped]

from app.core.config import Settings
from app.services.audit_job_executor import AuditJobExecutionError
from app.services.extraction_job_executor import ExtractionJobExecutionError
from app.services.file_job_executor import FileJobExecutionError
from app.services.knowledge_job_executor import KnowledgeJobExecutionError
from app.services.report_job_executor import ReportJobExecutionError
from app.workers.messages import JobDispatchMessage
from app.workers.runtime import FileWorkerRuntime, create_file_worker_runtime

_WORKER_ID_PATTERN = re.compile(r"[A-Za-z0-9._@:-]{1,100}\Z", re.ASCII)
_LOGICAL_QUEUES = (
    "document",
    "extraction",
    "knowledge",
    "evaluation",
    "audit",
    "report",
    "maintenance",
)


_FunctionT = TypeVar("_FunctionT", bound=Callable[..., object])


class _TaskApplication(Protocol):
    def task(self, *args: object, **kwargs: object) -> Callable[[_FunctionT], _FunctionT]: ...


class _RuntimeHolder:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._runtime: FileWorkerRuntime | None = None
        self._lock = threading.Lock()

    def get(self) -> FileWorkerRuntime:
        with self._lock:
            if self._runtime is None:
                self._runtime = create_file_worker_runtime(self._settings)
            return self._runtime


def _request_value(request: object, name: str) -> object:
    return getattr(request, name, None)


def _validate_envelope(
    task: object,
    *,
    settings: Settings,
    expected_queue_name: str,
    raw_message: dict[str, object],
) -> tuple[JobDispatchMessage, UUID, str]:
    request = _request_value(task, "request")
    if request is None:
        raise ValueError
    message = JobDispatchMessage.model_validate(raw_message)
    raw_event_id = _request_value(request, "id")
    if type(raw_event_id) is not str:
        raise ValueError
    event_id = UUID(raw_event_id)
    if str(event_id) != raw_event_id:
        raise ValueError
    for name in ("root_id", "correlation_id"):
        value = _request_value(request, name)
        if value is not None and value != raw_event_id:
            raise ValueError
    for name in ("parent_id", "group", "chord", "callbacks", "errbacks", "chain"):
        if _request_value(request, name) not in (None, []):
            raise ValueError
    delivery_info = _request_value(request, "delivery_info")
    if not isinstance(delivery_info, dict):
        raise ValueError
    routing_key = delivery_info.get("routing_key")
    if routing_key != expected_queue_name:
        raise ValueError
    worker_id = _request_value(request, "hostname")
    if type(worker_id) is not str or _WORKER_ID_PATTERN.fullmatch(worker_id) is None:
        raise ValueError
    return message, event_id, worker_id


def register_worker_tasks(application: _TaskApplication, settings: Settings) -> None:
    holder = _RuntimeHolder(settings)
    document_name = "app.workers.tasks.document.execute_job"

    @application.task(bind=True, name=document_name)
    def execute_document_job(task: object, **raw_message: object) -> dict[str, str]:
        try:
            message, event_id, worker_id = _validate_envelope(
                task,
                settings=settings,
                expected_queue_name=settings.celery_queue_document,
                raw_message=raw_message,
            )
        except Exception:
            raise Reject("INVALID_JOB_MESSAGE", requeue=False) from None
        try:
            result = holder.get().executor.execute(
                job_id=message.job_id,
                event_id=event_id,
                event_schema_version=message.event_schema_version,
                worker_id=worker_id,
            )
        except FileJobExecutionError:
            raise
        return {"outcome": result.outcome, "job_id": str(result.job_id)}

    extraction_name = "app.workers.tasks.extraction.execute_job"

    @application.task(bind=True, name=extraction_name)
    def execute_extraction_job(task: object, **raw_message: object) -> dict[str, str]:
        try:
            message, event_id, worker_id = _validate_envelope(
                task,
                settings=settings,
                expected_queue_name=settings.celery_queue_extraction,
                raw_message=raw_message,
            )
        except Exception:
            raise Reject("INVALID_JOB_MESSAGE", requeue=False) from None
        executor = holder.get().extraction_executor
        if executor is None:
            raise Reject("HANDLER_NOT_INSTALLED", requeue=False)
        try:
            result = executor.execute(
                job_id=message.job_id,
                event_id=event_id,
                event_schema_version=message.event_schema_version,
                worker_id=worker_id,
            )
        except ExtractionJobExecutionError:
            raise
        return {"outcome": result.outcome, "job_id": str(result.job_id)}

    def register_knowledge_task(logical_queue: str, expected_queue_name: str) -> None:
        task_name = f"app.workers.tasks.{logical_queue}.execute_job"

        @application.task(bind=True, name=task_name)
        def execute_knowledge_job(task: object, **raw_message: object) -> dict[str, str]:
            try:
                message, event_id, worker_id = _validate_envelope(
                    task,
                    settings=settings,
                    expected_queue_name=expected_queue_name,
                    raw_message=raw_message,
                )
            except Exception:
                raise Reject("INVALID_JOB_MESSAGE", requeue=False) from None
            executor = holder.get().knowledge_executor
            if executor is None:
                raise Reject("HANDLER_NOT_INSTALLED", requeue=False)
            try:
                result = executor.execute(
                    job_id=message.job_id,
                    event_id=event_id,
                    event_schema_version=message.event_schema_version,
                    worker_id=worker_id,
                )
            except KnowledgeJobExecutionError:
                raise
            return {"outcome": result.outcome, "job_id": str(result.job_id)}

    register_knowledge_task("knowledge", settings.celery_queue_knowledge)
    register_knowledge_task("evaluation", settings.celery_queue_evaluation)

    audit_name = "app.workers.tasks.audit.execute_job"

    @application.task(bind=True, name=audit_name)
    def execute_audit_job(task: object, **raw_message: object) -> dict[str, str]:
        try:
            message, event_id, worker_id = _validate_envelope(
                task,
                settings=settings,
                expected_queue_name=settings.celery_queue_audit,
                raw_message=raw_message,
            )
        except Exception:
            raise Reject("INVALID_JOB_MESSAGE", requeue=False) from None
        executor = holder.get().audit_executor
        if executor is None:
            raise Reject("HANDLER_NOT_INSTALLED", requeue=False)
        try:
            result = executor.execute(
                job_id=message.job_id,
                event_id=event_id,
                event_schema_version=message.event_schema_version,
                worker_id=worker_id,
            )
        except AuditJobExecutionError:
            raise
        return {"outcome": result.outcome, "job_id": str(result.job_id)}

    def register_uninstalled(logical_queue: str) -> None:
        task_name = f"app.workers.tasks.{logical_queue}.execute_job"

        @application.task(bind=True, name=task_name)
        def execute_uninstalled(task: object, **raw_message: object) -> None:
            del task, raw_message
            raise Reject("HANDLER_NOT_INSTALLED", requeue=False)

    report_name = "app.workers.tasks.report.execute_job"

    @application.task(bind=True, name=report_name)
    def execute_report_job(task: object, **raw_message: object) -> dict[str, str]:
        try:
            message, event_id, worker_id = _validate_envelope(
                task,
                settings=settings,
                expected_queue_name=settings.celery_queue_report,
                raw_message=raw_message,
            )
        except Exception:
            raise Reject("INVALID_JOB_MESSAGE", requeue=False) from None
        executor = holder.get().report_executor
        if executor is None:
            raise Reject("HANDLER_NOT_INSTALLED", requeue=False)
        try:
            result = executor.execute(
                job_id=message.job_id,
                event_id=event_id,
                event_schema_version=message.event_schema_version,
                worker_id=worker_id,
            )
        except ReportJobExecutionError:
            raise
        return {"outcome": result.outcome, "job_id": str(result.job_id)}

    for logical_queue in _LOGICAL_QUEUES:
        if logical_queue not in {
            "document",
            "extraction",
            "knowledge",
            "evaluation",
            "audit",
            "report",
        }:
            register_uninstalled(logical_queue)


__all__ = ["register_worker_tasks"]
