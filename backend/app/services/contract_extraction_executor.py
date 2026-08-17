"""`contract_extract` Job 的 fencing 与候选持久化。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.models.documents import FilePrimaryBusinessObject
from app.models.financial import Contract, ContractField
from app.repositories.contract_write import ContractWriteRepository
from app.repositories.job_runtime import ClaimedJob, JobRuntimeRepository
from app.repositories.operation_log import OperationLogRepository
from app.services.ai_extraction import AiExtractionService, AiExtractionServiceError
from app.services.audited_llm import AuditedLlmAdoption, AuditedLlmInvocationError
from app.services.contract_extractor import (
    ContractExtractionCandidate,
    extract_contract_candidate,
)
from app.services.contract_facts import (
    CONTRACT_FIELD_VALUE_TYPES,
    contract_critical_fact_hash,
    decimal_or_none,
    fact_json_value,
)
from app.workers.contract_handler_registry import ContractHandlerRuntime, load_contract_handler
from app.workers.handler_registry import HandlerRegistryError


class ContractExtractionExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ContractExtractionExecutionResult:
    outcome: Literal["succeeded", "failed", "duplicate_or_stale"]
    job_id: UUID


class ContractExtractionExecutor:
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
    ) -> ContractExtractionExecutionResult:
        if not worker_id or len(worker_id) > 100:
            raise ContractExtractionExecutionError("WORKER_ID_INVALID")
        with self._session_factory.begin() as session:
            repository = JobRuntimeRepository(session)
            snapshot = repository.peek_job(job_id)
            if snapshot is None:
                raise ContractExtractionExecutionError("JOB_NOT_FOUND")
            handler = self._validated_handler(
                snapshot.input_json,
                snapshot.handler_registry_version,
            )
            if (
                snapshot.job_type != "contract_extract"
                or snapshot.resource_type != "file"
                or snapshot.handler_registry_version != handler.registry_version
                or snapshot.handler_registry_hash != handler.registry_hash
                or snapshot.input_json.get("file_id") != str(snapshot.resource_id)
                or snapshot.current_attempt_start_step_code != "extract"
            ):
                raise ContractExtractionExecutionError("HANDLER_REGISTRY_INVALID")
            claim = repository.claim_job(
                job_id=job_id,
                event_id=event_id,
                event_schema_version=event_schema_version,
                worker_id=worker_id,
                start_step_seq=1,
            )
            if claim is None:
                return ContractExtractionExecutionResult("duplicate_or_stale", job_id)
        return self._execute_claimed(claim, handler)

    def execute_claimed(self, claim: ClaimedJob) -> ContractExtractionExecutionResult:
        handler = self._validated_handler(
            claim.job.input_json,
            claim.job.handler_registry_version,
        )
        if (
            claim.job.job_type != "contract_extract"
            or claim.job.resource_type != "file"
            or claim.job.handler_registry_version != handler.registry_version
            or claim.job.handler_registry_hash != handler.registry_hash
            or claim.job.input_json.get("file_id") != str(claim.job.resource_id)
            or claim.step_code != "extract"
        ):
            raise ContractExtractionExecutionError("HANDLER_REGISTRY_INVALID")
        return self._execute_claimed(claim, handler)

    def _execute_claimed(
        self,
        claim: ClaimedJob,
        handler: ContractHandlerRuntime,
    ) -> ContractExtractionExecutionResult:
        try:
            parse_version_id = UUID(str(claim.job.input_json["parse_version_id"]))
        except (KeyError, ValueError):
            raise ContractExtractionExecutionError("HANDLER_REGISTRY_INVALID") from None

        if self._ai_extraction is None:
            return self._execute_transaction(
                claim,
                handler,
                parse_version_id,
                candidate=None,
                adoption=None,
            )

        with self._session_factory.begin() as session:
            repository = ContractWriteRepository(session)
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
                    error_code="CONTRACT_EXTRACTION_SOURCE_INVALID",
                )
            existing_contract_id = source.existing_contract_id
            source_blocks = source.blocks

        if existing_contract_id is not None:
            return self._execute_transaction(
                claim,
                handler,
                parse_version_id,
                candidate=None,
                adoption=None,
            )

        try:
            extracted = self._ai_extraction.extract_contract(
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
        handler: ContractHandlerRuntime,
        parse_version_id: UUID,
        *,
        candidate: ContractExtractionCandidate | None,
        adoption: AuditedLlmAdoption | None,
    ) -> ContractExtractionExecutionResult:
        with self._session_factory.begin() as session:
            repository = ContractWriteRepository(session)
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
                return self._fail(session, claim, error_code="CONTRACT_EXTRACTION_SOURCE_INVALID")
            if source.existing_contract_id is not None:
                if adoption is not None:
                    adoption.reject_in_transaction(
                        session,
                        safe_error_code="AI_EXTRACTION_DUPLICATE_OR_STALE",
                    )
                existing = repository.lock_contract(
                    claim.job.organization_id,
                    source.existing_contract_id,
                )
                if existing is None:
                    return self._fail(
                        session,
                        claim,
                        error_code="CONTRACT_EXTRACTION_SOURCE_INVALID",
                    )
                summary = {
                    "contract_id": str(existing.id),
                    "field_count": len(repository.lock_fields(existing.id)),
                }
                handler.validate_summary(summary)
                if not JobRuntimeRepository(session).finish_job(
                    claim,
                    status="succeeded",
                    summary=summary,
                ):
                    raise ContractExtractionExecutionError("JOB_FENCING_REJECTED")
                return ContractExtractionExecutionResult("succeeded", claim.job.id)

            if candidate is None:
                candidate = extract_contract_candidate(source.blocks)
            elif not repository.validate_evidence(
                claim.job.organization_id,
                source.file.id,
                tuple(item.evidence for item in candidate.field_evidence),
            ):
                assert adoption is not None
                adoption.reject_in_transaction(
                    session,
                    safe_error_code="AI_EXTRACTION_EVIDENCE_CHANGED",
                )
                return self._fail(
                    session,
                    claim,
                    error_code="CONTRACT_EXTRACTION_SOURCE_INVALID",
                )
            stored_facts = candidate.facts
            contract_id = uuid4()
            if repository.contract_no_exists(
                claim.job.organization_id,
                contract_id,
                stored_facts.contract_no,
            ):
                stored_facts = stored_facts.model_copy(update={"contract_no": None})
            if adoption is not None:
                adoption.adopt_in_transaction(session)
            contract = Contract(
                id=contract_id,
                organization_id=claim.job.organization_id,
                contract_no=stored_facts.contract_no,
                name=stored_facts.name or "",
                party_a_name=stored_facts.party_a_name,
                party_a_tax_no=stored_facts.party_a_tax_no,
                party_b_name=stored_facts.party_b_name,
                party_b_tax_no=stored_facts.party_b_tax_no,
                supplier_id=None,
                amount=decimal_or_none(stored_facts.amount),
                currency=stored_facts.currency,
                signed_date=stored_facts.signed_date,
                effective_date=stored_facts.effective_date,
                expiry_date=stored_facts.expiry_date,
                payment_method=stored_facts.payment_method,
                payment_terms=stored_facts.payment_terms,
                confirmation_status="unconfirmed",
                status="draft",
                confirmed_by=None,
                confirmed_at=None,
                critical_fact_hash=contract_critical_fact_hash(stored_facts),
                row_version=1,
                created_by=source.file.uploaded_by,
                updated_by=source.file.uploaded_by,
            )
            repository.add(contract)
            repository.flush()
            field_rows = tuple(
                ContractField(
                    id=uuid4(),
                    contract_id=contract.id,
                    field_code=item.field_code,
                    value_type=CONTRACT_FIELD_VALUE_TYPES[item.field_code],
                    extracted_value_json=fact_json_value(candidate.facts, item.field_code),
                    confirmed_value_json=None,
                    confidence=(
                        None
                        if item.evidence.confidence is None
                        else Decimal(item.evidence.confidence)
                    ),
                    confirmation_status="unconfirmed",
                    evidence_file_id=source.file.id,
                    evidence_parse_version_id=item.evidence.parse_version_id,
                    evidence_block_id=item.evidence.block_id,
                    page_no=item.evidence.page_no,
                    quote_text=item.evidence.quote_text,
                    bbox_json=item.evidence.bbox,
                    confirmed_by=None,
                    confirmed_at=None,
                    row_version=1,
                )
                for item in candidate.field_evidence
            )
            repository.add_all(field_rows)
            repository.add(
                FilePrimaryBusinessObject(
                    id=uuid4(),
                    file_id=source.file.id,
                    business_type="contract",
                    contract_id=contract.id,
                    invoice_id=None,
                    supplementary_agreement_id=None,
                    policy_document_id=None,
                    bound_by=source.file.uploaded_by,
                )
            )
            repository.flush()
            summary = {
                "contract_id": str(contract.id),
                "field_count": len(field_rows),
            }
            handler.validate_summary(summary)
            OperationLogRepository(session).append(
                organization_id=claim.job.organization_id,
                actor_kind="system",
                actor_id=None,
                action_code="contracts.extraction_created",
                outcome="succeeded",
                resource_type="contract",
                resource_id=contract.id,
                trace_id=claim.job.trace_id,
                change_summary={
                    "field_count": len(field_rows),
                    "row_version": "1",
                },
            )
            if not JobRuntimeRepository(session).finish_job(
                claim,
                status="succeeded",
                summary=summary,
            ):
                raise ContractExtractionExecutionError("JOB_FENCING_REJECTED")
        return ContractExtractionExecutionResult("succeeded", claim.job.id)

    @staticmethod
    def _validated_handler(
        input_json: dict[str, object],
        registry_version: str,
    ) -> ContractHandlerRuntime:
        try:
            handler = load_contract_handler(registry_version)
            handler.validate_input(input_json)
        except (HandlerRegistryError, ValueError):
            raise ContractExtractionExecutionError("HANDLER_REGISTRY_INVALID") from None
        return handler

    @staticmethod
    def _fail(
        session: Session,
        claim: ClaimedJob,
        *,
        error_code: str,
    ) -> ContractExtractionExecutionResult:
        if not JobRuntimeRepository(session).finish_job(
            claim,
            status="failed",
            summary={},
            error_code=error_code,
            error_message="contract extraction failed",
        ):
            raise ContractExtractionExecutionError("JOB_FENCING_REJECTED")
        return ContractExtractionExecutionResult("failed", claim.job.id)


__all__ = [
    "ContractExtractionExecutionError",
    "ContractExtractionExecutionResult",
    "ContractExtractionExecutor",
]
