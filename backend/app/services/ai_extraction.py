"""合同与发票真实 AI 提取、严格修复和待原子采用候选。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

from app.ai.extraction_output import (
    CONTRACT_EXTRACTION_SCHEMA_VERSION,
    INVOICE_EXTRACTION_SCHEMA_VERSION,
    ContractExtractionOutput,
    InvoiceExtractionOutput,
    validate_contract_extraction_output,
    validate_invoice_extraction_output,
)
from app.ai.extraction_prompts import (
    CONTRACT_EXTRACTION_PROMPT,
    CONTRACT_EXTRACTION_REPAIR_PROMPT,
    INVOICE_EXTRACTION_PROMPT,
    INVOICE_EXTRACTION_REPAIR_PROMPT,
    ExtractionPromptArtifact,
    ExtractionPromptBlock,
    build_extraction_prompt_request,
)
from app.ai.live_policy import LiveLlmPolicy
from app.services.audited_llm import (
    AuditedLlmAdoption,
    AuditedLlmInvocationError,
    AuditedLlmInvoker,
    AuditedLlmOutputRejected,
    LlmCallIdentity,
)
from app.services.contract_extractor import (
    ContractExtractionCandidate,
    ContractSourceBlock,
)
from app.services.invoice_extractor import InvoiceExtractionCandidate, InvoiceSourceBlock

SourceBlockT = TypeVar("SourceBlockT", ContractSourceBlock, InvoiceSourceBlock)
OutputT = TypeVar("OutputT", ContractExtractionOutput, InvoiceExtractionOutput)


class AiExtractionServiceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AuditedContractExtraction:
    candidate: ContractExtractionCandidate
    adoption: AuditedLlmAdoption


@dataclass(frozen=True, slots=True)
class AuditedInvoiceExtraction:
    candidate: InvoiceExtractionCandidate
    adoption: AuditedLlmAdoption


def _prompt_blocks(
    blocks: tuple[SourceBlockT, ...],
) -> tuple[ExtractionPromptBlock, ...]:
    try:
        return tuple(
            ExtractionPromptBlock(
                block_id=block.id,
                parse_version_id=block.parse_version_id,
                page_no=block.page_no,
                block_index=block.block_index,
                text=block.text,
                bbox=block.bbox,  # type: ignore[arg-type]
                confidence=block.confidence,
            )
            for block in blocks
        )
    except (TypeError, ValueError):
        raise AiExtractionServiceError("AI_EXTRACTION_SOURCE_INVALID") from None


class AiExtractionService:
    def __init__(
        self,
        invoker: AuditedLlmInvoker,
        llm_policy: LiveLlmPolicy,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._invoker = invoker
        self._policy = llm_policy
        self._monotonic = monotonic_clock

    def extract_contract(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
        file_id: UUID,
        trace_id: UUID,
        blocks: tuple[ContractSourceBlock, ...],
    ) -> AuditedContractExtraction:
        prompt_blocks = _prompt_blocks(blocks)
        output, adoption = self._invoke_with_repairs(
            organization_id=organization_id,
            job_id=job_id,
            file_id=file_id,
            trace_id=trace_id,
            call_type="contract_field_extraction",
            schema_version=CONTRACT_EXTRACTION_SCHEMA_VERSION,
            primary_prompt=CONTRACT_EXTRACTION_PROMPT,
            repair_prompt=CONTRACT_EXTRACTION_REPAIR_PROMPT,
            prompt_blocks=prompt_blocks,
            validator=lambda value: validate_contract_extraction_output(
                value,
                blocks=prompt_blocks,
            ),
        )
        return AuditedContractExtraction(
            candidate=ContractExtractionCandidate(
                facts=output.facts,
                field_evidence=output.field_evidence,
            ),
            adoption=adoption,
        )

    def extract_invoice(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
        file_id: UUID,
        trace_id: UUID,
        blocks: tuple[InvoiceSourceBlock, ...],
    ) -> AuditedInvoiceExtraction:
        prompt_blocks = _prompt_blocks(blocks)
        output, adoption = self._invoke_with_repairs(
            organization_id=organization_id,
            job_id=job_id,
            file_id=file_id,
            trace_id=trace_id,
            call_type="invoice_field_extraction",
            schema_version=INVOICE_EXTRACTION_SCHEMA_VERSION,
            primary_prompt=INVOICE_EXTRACTION_PROMPT,
            repair_prompt=INVOICE_EXTRACTION_REPAIR_PROMPT,
            prompt_blocks=prompt_blocks,
            validator=lambda value: validate_invoice_extraction_output(
                value,
                blocks=prompt_blocks,
            ),
        )
        return AuditedInvoiceExtraction(
            candidate=InvoiceExtractionCandidate(
                facts=output.facts,
                field_evidence=output.field_evidence,
                items=output.items,
            ),
            adoption=adoption,
        )

    def _invoke_with_repairs(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
        file_id: UUID,
        trace_id: UUID,
        call_type: str,
        schema_version: str,
        primary_prompt: ExtractionPromptArtifact,
        repair_prompt: ExtractionPromptArtifact,
        prompt_blocks: tuple[ExtractionPromptBlock, ...],
        validator: Callable[[str], OutputT],
    ) -> tuple[OutputT, AuditedLlmAdoption]:
        operation = self._policy.operations[call_type]
        deadline = self._monotonic() + operation.deadline_seconds
        for attempt_no in range(1, operation.max_model_repairs + 2):
            prompt = primary_prompt if attempt_no == 1 else repair_prompt
            request = build_extraction_prompt_request(
                artifact=prompt,
                trace_id=str(trace_id),
                blocks=prompt_blocks,
            )
            try:
                result = self._invoker.invoke(
                    request=request,
                    identity=LlmCallIdentity(
                        organization_id=organization_id,
                        business_operation_id=job_id,
                        job_id=job_id,
                        resource_type="file",
                        resource_id=file_id,
                        trace_id=trace_id,
                        call_type=call_type,
                        logical_generation_no=attempt_no,
                        provider_attempt_no=attempt_no,
                        prompt_id=prompt.prompt_id,
                        prompt_version=prompt.prompt_version,
                        prompt_hash=prompt.prompt_hash,
                        schema_version=schema_version,
                    ),
                    operation=operation,
                    deadline_monotonic=deadline,
                    future_model_repair_slots=(operation.max_model_repairs - (attempt_no - 1)),
                    validate_output=validator,
                )
            except AuditedLlmOutputRejected:
                continue
            except AuditedLlmInvocationError as error:
                raise AiExtractionServiceError(error.code) from None
            return result.value, result.adoption
        raise AiExtractionServiceError("AI_STRUCTURED_OUTPUT_INVALID")


__all__ = [
    "AiExtractionService",
    "AiExtractionServiceError",
    "AuditedContractExtraction",
    "AuditedInvoiceExtraction",
]
