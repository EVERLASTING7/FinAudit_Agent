"""`invoice_extract` Job 的 PostgreSQL fencing 与候选持久化。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.models.documents import FilePrimaryBusinessObject
from app.models.financial import Invoice, InvoiceItem
from app.repositories.invoice_write import InvoiceWriteRepository
from app.repositories.job_runtime import ClaimedJob, JobRuntimeRepository
from app.repositories.operation_log import OperationLogRepository
from app.services.ai_extraction import AiExtractionService, AiExtractionServiceError
from app.services.audited_llm import AuditedLlmAdoption, AuditedLlmInvocationError
from app.services.invoice_extractor import InvoiceExtractionCandidate, extract_invoice_candidate
from app.services.invoice_facts import (
    decimal_or_none,
    field_evidence_json,
    invoice_critical_fact_hash,
    item_evidence_json,
)
from app.workers.handler_registry import HandlerRegistryError
from app.workers.invoice_handler_registry import InvoiceHandlerRuntime, load_invoice_handler


class InvoiceExtractionExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class InvoiceExtractionExecutionResult:
    outcome: Literal["succeeded", "failed", "duplicate_or_stale"]
    job_id: UUID


class InvoiceExtractionExecutor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        ai_extraction: AiExtractionService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._ai_extraction = ai_extraction

    def execute(
        self,
        *,
        job_id: UUID,
        event_id: UUID,
        event_schema_version: int,
        worker_id: str,
    ) -> InvoiceExtractionExecutionResult:
        if not worker_id or len(worker_id) > 100:
            raise InvoiceExtractionExecutionError("WORKER_ID_INVALID")
        with self._session_factory.begin() as session:
            repository = JobRuntimeRepository(session)
            snapshot = repository.peek_job(job_id)
            if snapshot is None:
                raise InvoiceExtractionExecutionError("JOB_NOT_FOUND")
            handler = self._validated_handler(
                snapshot.input_json,
                snapshot.handler_registry_version,
            )
            if (
                snapshot.job_type != "invoice_extract"
                or snapshot.resource_type != "file"
                or snapshot.handler_registry_version != handler.registry_version
                or snapshot.handler_registry_hash != handler.registry_hash
                or snapshot.input_json.get("file_id") != str(snapshot.resource_id)
                or snapshot.current_attempt_start_step_code != "extract"
            ):
                raise InvoiceExtractionExecutionError("HANDLER_REGISTRY_INVALID")
            claim = repository.claim_job(
                job_id=job_id,
                event_id=event_id,
                event_schema_version=event_schema_version,
                worker_id=worker_id,
                start_step_seq=1,
            )
            if claim is None:
                return InvoiceExtractionExecutionResult("duplicate_or_stale", job_id)
        return self._execute_claimed(claim, handler)

    def execute_claimed(self, claim: ClaimedJob) -> InvoiceExtractionExecutionResult:
        handler = self._validated_handler(
            claim.job.input_json,
            claim.job.handler_registry_version,
        )
        if (
            claim.job.job_type != "invoice_extract"
            or claim.job.resource_type != "file"
            or claim.job.handler_registry_version != handler.registry_version
            or claim.job.handler_registry_hash != handler.registry_hash
            or claim.job.input_json.get("file_id") != str(claim.job.resource_id)
            or claim.step_code != "extract"
        ):
            raise InvoiceExtractionExecutionError("HANDLER_REGISTRY_INVALID")
        return self._execute_claimed(claim, handler)

    def _execute_claimed(
        self,
        claim: ClaimedJob,
        handler: InvoiceHandlerRuntime,
    ) -> InvoiceExtractionExecutionResult:
        try:
            parse_version_id = UUID(str(claim.job.input_json["parse_version_id"]))
        except (KeyError, ValueError):
            raise InvoiceExtractionExecutionError("HANDLER_REGISTRY_INVALID") from None

        if self._ai_extraction is None:
            return self._execute_transaction(
                claim,
                handler,
                parse_version_id,
                candidate=None,
                adoption=None,
            )

        with self._session_factory.begin() as session:
            repository = InvoiceWriteRepository(session)
            repository.acquire_domain_lock(claim.job.organization_id)
            source = repository.load_extraction_source(
                claim.job.organization_id,
                claim.job.resource_id,
                parse_version_id,
            )
            if source is None:
                return self._fail(
                    session,
                    claim,
                    error_code="INVOICE_EXTRACTION_SOURCE_INVALID",
                )
            existing_invoice_id = source.existing_invoice_id
            source_blocks = source.blocks

        if existing_invoice_id is not None:
            return self._execute_transaction(
                claim,
                handler,
                parse_version_id,
                candidate=None,
                adoption=None,
            )

        try:
            extracted = self._ai_extraction.extract_invoice(
                organization_id=claim.job.organization_id,
                job_id=claim.job.id,
                file_id=claim.job.resource_id,
                trace_id=claim.job.trace_id,
                blocks=source_blocks,
            )
            return self._execute_transaction(
                claim,
                handler,
                parse_version_id,
                candidate=extracted.candidate,
                adoption=extracted.adoption,
            )
        except (AiExtractionServiceError, AuditedLlmInvocationError):
            with self._session_factory.begin() as session:
                return self._fail(
                    session,
                    claim,
                    error_code="AI_EXTRACTION_FAILED",
                )

    def _execute_transaction(
        self,
        claim: ClaimedJob,
        handler: InvoiceHandlerRuntime,
        parse_version_id: UUID,
        *,
        candidate: InvoiceExtractionCandidate | None,
        adoption: AuditedLlmAdoption | None,
    ) -> InvoiceExtractionExecutionResult:
        with self._session_factory.begin() as session:
            repository = InvoiceWriteRepository(session)
            repository.acquire_domain_lock(claim.job.organization_id)
            source = repository.load_extraction_source(
                claim.job.organization_id,
                claim.job.resource_id,
                parse_version_id,
            )
            if source is None:
                if adoption is not None:
                    adoption.reject_in_transaction(
                        session,
                        safe_error_code="AI_EXTRACTION_SOURCE_CHANGED",
                    )
                return self._fail(
                    session,
                    claim,
                    error_code="INVOICE_EXTRACTION_SOURCE_INVALID",
                )
            if source.existing_invoice_id is not None:
                if adoption is not None:
                    adoption.reject_in_transaction(
                        session,
                        safe_error_code="AI_EXTRACTION_DUPLICATE_OR_STALE",
                    )
                existing = repository.lock_invoice(
                    claim.job.organization_id,
                    source.existing_invoice_id,
                )
                if existing is None:
                    return self._fail(
                        session,
                        claim,
                        error_code="INVOICE_EXTRACTION_SOURCE_INVALID",
                    )
                existing_fields = existing.field_evidence_json.get("fields")
                if type(existing_fields) is not list:
                    return self._fail(
                        session,
                        claim,
                        error_code="INVOICE_EXTRACTION_SOURCE_INVALID",
                    )
                summary = {
                    "invoice_id": str(existing.id),
                    "field_count": len(existing_fields),
                    "item_count": len(repository.lock_items(existing.id)),
                    "duplicate_status": (
                        existing.duplicate_status
                        if existing.duplicate_status in {"not_checked", "unique", "suspected"}
                        else "not_checked"
                    ),
                }
                handler.validate_summary(summary)
                if not JobRuntimeRepository(session).finish_job(
                    claim,
                    status="succeeded",
                    summary=summary,
                ):
                    raise InvoiceExtractionExecutionError("JOB_FENCING_REJECTED")
                return InvoiceExtractionExecutionResult("succeeded", claim.job.id)

            if candidate is None:
                candidate = extract_invoice_candidate(source.blocks)
            else:
                all_evidence = tuple(item.evidence for item in candidate.field_evidence) + tuple(
                    evidence for item in candidate.items for evidence in item.evidence
                )
                if not repository.validate_evidence(
                    claim.job.organization_id,
                    source.file.id,
                    all_evidence,
                ):
                    assert adoption is not None
                    adoption.reject_in_transaction(
                        session,
                        safe_error_code="AI_EXTRACTION_EVIDENCE_CHANGED",
                    )
                    return self._fail(
                        session,
                        claim,
                        error_code="INVOICE_EXTRACTION_SOURCE_INVALID",
                    )
            facts = candidate.facts
            invoice_id = uuid4()
            invoice = Invoice(
                id=invoice_id,
                organization_id=claim.job.organization_id,
                invoice_code=facts.invoice_code,
                invoice_number=facts.invoice_number,
                invoice_type=facts.invoice_type,
                is_red_invoice=facts.is_red_invoice,
                invoice_date=facts.invoice_date,
                buyer_name=facts.buyer_name,
                buyer_tax_no=facts.buyer_tax_no,
                seller_name=facts.seller_name,
                seller_tax_no=facts.seller_tax_no,
                supplier_id=None,
                amount_excluding_tax=decimal_or_none(facts.amount_excluding_tax),
                tax_amount=decimal_or_none(facts.tax_amount),
                total_amount=decimal_or_none(facts.total_amount),
                currency=facts.currency,
                confirmation_status="unconfirmed",
                duplicate_status="not_checked",
                status="draft",
                field_evidence_json=field_evidence_json(candidate.field_evidence),
                confirmed_by=None,
                confirmed_at=None,
                critical_fact_hash=invoice_critical_fact_hash(facts, candidate.items),
                row_version=1,
                created_by=source.file.uploaded_by,
                updated_by=source.file.uploaded_by,
            )
            duplicate_status = (
                "not_checked"
                if not invoice.invoice_code
                or not invoice.invoice_number
                or not invoice.seller_tax_no
                else "suspected"
                if repository.exact_duplicate_ids(invoice, lock=True)
                else "unique"
            )
            invoice.duplicate_status = duplicate_status
            if adoption is not None:
                adoption.adopt_in_transaction(session)
            repository.add(invoice)
            repository.flush()
            items = tuple(
                InvoiceItem(
                    id=uuid4(),
                    invoice_id=invoice.id,
                    line_no=item.line_no,
                    item_name=item.item_name,
                    specification=item.specification,
                    unit=item.unit,
                    quantity=decimal_or_none(item.quantity),
                    unit_price=decimal_or_none(item.unit_price),
                    amount_excluding_tax=decimal_or_none(item.amount_excluding_tax),
                    tax_rate=decimal_or_none(item.tax_rate),
                    tax_amount=decimal_or_none(item.tax_amount),
                    total_amount=decimal_or_none(item.total_amount),
                    evidence_json=item_evidence_json(item.evidence),
                    row_version=1,
                )
                for item in candidate.items
            )
            repository.add_all(items)
            repository.add(
                FilePrimaryBusinessObject(
                    id=uuid4(),
                    file_id=source.file.id,
                    business_type="invoice",
                    contract_id=None,
                    invoice_id=invoice.id,
                    supplementary_agreement_id=None,
                    policy_document_id=None,
                    bound_by=source.file.uploaded_by,
                )
            )
            repository.flush()
            summary = {
                "invoice_id": str(invoice.id),
                "field_count": len(candidate.field_evidence),
                "item_count": len(items),
                "duplicate_status": duplicate_status,
            }
            handler.validate_summary(summary)
            OperationLogRepository(session).append(
                organization_id=claim.job.organization_id,
                actor_kind="system",
                actor_id=None,
                action_code="invoices.extraction_created",
                outcome="succeeded",
                resource_type="invoice",
                resource_id=invoice.id,
                trace_id=claim.job.trace_id,
                change_summary={
                    "field_count": len(candidate.field_evidence),
                    "item_count": len(items),
                    "duplicate_status": duplicate_status,
                    "row_version": "1",
                },
            )
            if not JobRuntimeRepository(session).finish_job(
                claim,
                status="succeeded",
                summary=summary,
            ):
                raise InvoiceExtractionExecutionError("JOB_FENCING_REJECTED")
        return InvoiceExtractionExecutionResult("succeeded", claim.job.id)

    @staticmethod
    def _validated_handler(
        input_json: dict[str, object],
        registry_version: str,
    ) -> InvoiceHandlerRuntime:
        try:
            handler = load_invoice_handler(registry_version)
            handler.validate_input(input_json)
        except (HandlerRegistryError, ValueError):
            raise InvoiceExtractionExecutionError("HANDLER_REGISTRY_INVALID") from None
        return handler

    @staticmethod
    def _fail(
        session: Session,
        claim: ClaimedJob,
        *,
        error_code: str,
    ) -> InvoiceExtractionExecutionResult:
        if not JobRuntimeRepository(session).finish_job(
            claim,
            status="failed",
            summary={},
            error_code=error_code,
            error_message="invoice extraction failed",
        ):
            raise InvoiceExtractionExecutionError("JOB_FENCING_REJECTED")
        return InvoiceExtractionExecutionResult("failed", claim.job.id)


__all__ = [
    "InvoiceExtractionExecutionError",
    "InvoiceExtractionExecutionResult",
    "InvoiceExtractionExecutor",
]
