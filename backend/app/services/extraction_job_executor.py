"""共享 extraction 队列上的发票/合同 Job 路由。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.repositories.job_runtime import JobRuntimeRepository
from app.services.contract_extraction_executor import (
    ContractExtractionExecutionError,
    ContractExtractionExecutionResult,
    ContractExtractionExecutor,
)
from app.services.invoice_extraction_executor import (
    InvoiceExtractionExecutionError,
    InvoiceExtractionExecutionResult,
    InvoiceExtractionExecutor,
)


class ExtractionJobExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExtractionJobExecutionResult:
    outcome: Literal["succeeded", "failed", "duplicate_or_stale"]
    job_id: UUID


class ExtractionJobExecutor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        invoice_executor: InvoiceExtractionExecutor,
        contract_executor: ContractExtractionExecutor,
    ) -> None:
        self._session_factory = session_factory
        self._invoice_executor = invoice_executor
        self._contract_executor = contract_executor

    def execute(
        self,
        *,
        job_id: UUID,
        event_id: UUID,
        event_schema_version: int,
        worker_id: str,
    ) -> ExtractionJobExecutionResult:
        with self._session_factory() as session:
            snapshot = JobRuntimeRepository(session).peek_job(job_id)
        if snapshot is None:
            raise ExtractionJobExecutionError("JOB_NOT_FOUND")
        result: InvoiceExtractionExecutionResult | ContractExtractionExecutionResult
        try:
            if snapshot.job_type == "invoice_extract":
                result = self._invoice_executor.execute(
                    job_id=job_id,
                    event_id=event_id,
                    event_schema_version=event_schema_version,
                    worker_id=worker_id,
                )
            elif snapshot.job_type == "contract_extract":
                result = self._contract_executor.execute(
                    job_id=job_id,
                    event_id=event_id,
                    event_schema_version=event_schema_version,
                    worker_id=worker_id,
                )
            else:
                raise ExtractionJobExecutionError("HANDLER_REGISTRY_INVALID")
        except (InvoiceExtractionExecutionError, ContractExtractionExecutionError) as error:
            raise ExtractionJobExecutionError(error.code) from None
        return ExtractionJobExecutionResult(result.outcome, result.job_id)


__all__ = [
    "ExtractionJobExecutionError",
    "ExtractionJobExecutionResult",
    "ExtractionJobExecutor",
]
