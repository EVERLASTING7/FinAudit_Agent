"""Outbox 到 Celery/Redis 的单次可靠投递编排。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kombu.exceptions import OperationalError  # type: ignore[import-untyped]
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.repositories.job_runtime import JobRuntimeRepository, OutboxClaim, OutboxFailureCode
from app.workers.audit_handler_registry import AuditHandlerRuntime, load_audit_handler
from app.workers.contract_handler_registry import ContractHandlerRuntime, load_contract_handler
from app.workers.file_handler_registry import FileHandlerRuntime, load_file_handler
from app.workers.handler_registry import HandlerRegistryError
from app.workers.invoice_handler_registry import InvoiceHandlerRuntime, load_invoice_handler
from app.workers.knowledge_handler_registry import KnowledgeHandlerRuntime, load_knowledge_handler
from app.workers.messages import JOB_EVENT_SCHEMA_VERSION, JobDispatchMessage
from app.workers.report_handler_registry import ReportHandlerRuntime, load_report_handler


class JobMessagePublisher(Protocol):
    def publish(self, claim: OutboxClaim, *, task_name: str, queue_name: str) -> None: ...


class _CeleryApplication(Protocol):
    def send_task(self, name: str, *args: object, **kwargs: object) -> object: ...


@dataclass(frozen=True, slots=True)
class DispatchResult:
    outcome: str
    outbox_id: str | None = None
    job_id: str | None = None


class CeleryJobMessagePublisher:
    """显式关闭 Celery 自重试；一次调用只对应一个 Outbox attempt。"""

    def __init__(self, application: _CeleryApplication) -> None:
        self._application = application

    def publish(self, claim: OutboxClaim, *, task_name: str, queue_name: str) -> None:
        message = JobDispatchMessage.model_validate(
            {
                "job_id": str(claim.job.id),
                "event_schema_version": JOB_EVENT_SCHEMA_VERSION,
            }
        )
        self._application.send_task(
            task_name,
            args=[],
            kwargs=message.model_dump(mode="json"),
            task_id=str(claim.event_id),
            correlation_id=str(claim.event_id),
            queue=queue_name,
            routing_key=queue_name,
            serializer="json",
            retry=False,
            retries=0,
            root_id=str(claim.event_id),
            ignore_result=True,
            add_to_parent=False,
        )


class OutboxDispatcher:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        publisher: JobMessagePublisher,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher
        self._queue_names = {
            "document": settings.celery_queue_document,
            "extraction": settings.celery_queue_extraction,
            "knowledge": settings.celery_queue_knowledge,
            "evaluation": settings.celery_queue_evaluation,
            "audit": settings.celery_queue_audit,
            "report": settings.celery_queue_report,
            "maintenance": settings.celery_queue_maintenance,
        }

    def dispatch_once(self) -> DispatchResult:
        with self._session_factory.begin() as session:
            claim = JobRuntimeRepository(session).claim_next_outbox()
        if claim is None:
            return DispatchResult("idle")

        broker_called = False
        try:
            task_name, queue_name = self._resolve_route(claim)
        except HandlerRegistryError:
            return self._fail(
                claim,
                error_code="SERIALIZATION_FAILED",
                broker_called=False,
                outcome="dead_letter",
            )
        if claim.event_version != JOB_EVENT_SCHEMA_VERSION:
            return self._fail(
                claim,
                error_code="UNSUPPORTED_EVENT_VERSION",
                broker_called=False,
                outcome="dead_letter",
            )

        try:
            broker_called = True
            self._publisher.publish(claim, task_name=task_name, queue_name=queue_name)
        except (ConnectionError, ConnectionRefusedError, OperationalError):
            return self._fail(
                claim,
                error_code="BROKER_UNAVAILABLE",
                broker_called=broker_called,
                outcome="retry_scheduled",
            )
        except TimeoutError:
            return self._fail(
                claim,
                error_code="PUBLISH_CONFIRM_UNKNOWN",
                broker_called=broker_called,
                outcome="retry_scheduled",
            )
        except Exception:
            return self._fail(
                claim,
                error_code="UNKNOWN_DELIVERY_ERROR",
                broker_called=broker_called,
                outcome="dead_letter",
            )

        with self._session_factory.begin() as session:
            marked = JobRuntimeRepository(session).mark_outbox_published(claim)
        return DispatchResult(
            "published" if marked else "stale",
            str(claim.outbox_id),
            str(claim.job.id),
        )

    def reap_expired_once(self) -> DispatchResult:
        with self._session_factory.begin() as session:
            repository = JobRuntimeRepository(session)
            claim = repository.next_expired_processing_outbox()
            if claim is None:
                return DispatchResult("idle")
            marked = repository.mark_outbox_failure(
                claim,
                error_code="PROCESSING_LEASE_EXPIRED",
                broker_called=True,
            )
        return DispatchResult(
            "retry_scheduled" if marked and claim.attempt_count < 8 else "dead_letter",
            str(claim.outbox_id),
            str(claim.job.id),
        )

    def _resolve_route(self, claim: OutboxClaim) -> tuple[str, str]:
        if (
            claim.event_type != "job.dispatch.requested"
            or claim.event_sequence != claim.job.attempt_no + 1
            or claim.payload_json != {"job_id": str(claim.job.id)}
            or claim.job.input_schema_version != 1
        ):
            raise HandlerRegistryError
        handler: (
            FileHandlerRuntime
            | ContractHandlerRuntime
            | InvoiceHandlerRuntime
            | KnowledgeHandlerRuntime
            | AuditHandlerRuntime
            | ReportHandlerRuntime
        )
        if claim.job.job_type in {"file_process", "file_scan"}:
            handler = load_file_handler(claim.job.job_type)
        elif claim.job.job_type == "invoice_extract":
            handler = load_invoice_handler(claim.job.handler_registry_version)
        elif claim.job.job_type == "contract_extract":
            handler = load_contract_handler(claim.job.handler_registry_version)
        elif claim.job.job_type in {"knowledge_index_build", "retrieval_eval"}:
            handler = load_knowledge_handler(claim.job.job_type)
        elif claim.job.job_type == "audit_execute":
            handler = load_audit_handler()
        elif claim.job.job_type == "report_generate":
            handler = load_report_handler()
        else:
            raise HandlerRegistryError
        if (
            claim.job.handler_registry_version != handler.registry_version
            or claim.job.handler_registry_hash != handler.registry_hash
        ):
            raise HandlerRegistryError
        handler.validate_input(claim.job.input_json)
        logical_queue = handler.handler.logical_queue
        return (
            f"app.workers.tasks.{logical_queue}.execute_job",
            self._queue_names[logical_queue],
        )

    def _fail(
        self,
        claim: OutboxClaim,
        *,
        error_code: OutboxFailureCode,
        broker_called: bool,
        outcome: str,
    ) -> DispatchResult:
        with self._session_factory.begin() as session:
            marked = JobRuntimeRepository(session).mark_outbox_failure(
                claim,
                error_code=error_code,
                broker_called=broker_called,
            )
        return DispatchResult(
            outcome if marked else "stale",
            str(claim.outbox_id),
            str(claim.job.id),
        )


__all__ = [
    "CeleryJobMessagePublisher",
    "DispatchResult",
    "JobMessagePublisher",
    "OutboxDispatcher",
]
