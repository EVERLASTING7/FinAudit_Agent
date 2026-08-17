from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from app.ai.contracts import LlmRequest
from app.ai.live_policy import LIVE_LLM_POLICY, LiveOperationPolicy
from app.ai.policy import canonicalize_jcs
from app.services.ai_extraction import AiExtractionService, AiExtractionServiceError
from app.services.audited_llm import (
    AuditedLlmAdoption,
    AuditedLlmInvocationError,
    AuditedLlmInvoker,
    AuditedLlmOutputRejected,
    AuditedLlmResult,
    LlmCallIdentity,
)
from app.services.contract_extractor import ContractSourceBlock
from app.services.invoice_extractor import InvoiceSourceBlock

_ORGANIZATION_ID = UUID("92000000-0000-4000-8000-000000000001")
_JOB_ID = UUID("92000000-0000-4000-8000-000000000002")
_FILE_ID = UUID("92000000-0000-4000-8000-000000000003")
_TRACE_ID = UUID("92000000-0000-4000-8000-000000000004")
_PARSE_VERSION_ID = UUID("92000000-0000-4000-8000-000000000005")
_BLOCK_ID = UUID("92000000-0000-4000-8000-000000000006")

_CONTRACT_FIELDS = (
    "contract_no",
    "name",
    "party_a_name",
    "party_a_tax_no",
    "party_b_name",
    "party_b_tax_no",
    "amount",
    "currency",
    "signed_date",
    "effective_date",
    "expiry_date",
    "payment_method",
    "payment_terms",
)
_INVOICE_FIELDS = (
    "invoice_code",
    "invoice_number",
    "invoice_type",
    "is_red_invoice",
    "invoice_date",
    "buyer_name",
    "buyer_tax_no",
    "seller_name",
    "seller_tax_no",
    "amount_excluding_tax",
    "tax_amount",
    "total_amount",
    "currency",
)


class _QueuedInvoker:
    def __init__(self, outputs: list[str | AuditedLlmInvocationError]) -> None:
        self.outputs = outputs
        self.requests: list[LlmRequest] = []
        self.identities: list[LlmCallIdentity] = []
        self.repair_slots: list[int] = []
        self.adoption = cast(AuditedLlmAdoption, object())

    def invoke(
        self,
        *,
        request: LlmRequest,
        identity: LlmCallIdentity,
        operation: LiveOperationPolicy,
        deadline_monotonic: float,
        future_model_repair_slots: int,
        validate_output: Callable[[str], object],
    ) -> AuditedLlmResult[object]:
        del operation, deadline_monotonic
        self.requests.append(request)
        self.identities.append(identity)
        self.repair_slots.append(future_model_repair_slots)
        output = self.outputs.pop(0)
        if isinstance(output, AuditedLlmInvocationError):
            raise output
        try:
            value = validate_output(output)
        except ValueError:
            raise AuditedLlmOutputRejected("AI_STRUCTURED_OUTPUT_INVALID") from None
        return AuditedLlmResult(value=value, adoption=self.adoption)


def _evidence(text: str) -> dict[str, object]:
    return {
        "block_id": str(_BLOCK_ID),
        "parse_version_id": str(_PARSE_VERSION_ID),
        "page_no": 1,
        "quote_text": text,
        "bbox": {"left": 1, "top": 2, "width": 100, "height": 10},
        "confidence": "0.95000",
    }


def _contract_output(text: str) -> str:
    facts: dict[str, object] = {field: None for field in _CONTRACT_FIELDS}
    facts["contract_no"] = "HT-001"
    return canonicalize_jcs(
        {
            "facts": facts,
            "field_evidence": [{"field_code": "contract_no", "evidence": _evidence(text)}],
        }
    ).decode("utf-8")


def _invoice_output(text: str) -> str:
    facts: dict[str, object] = {field: None for field in _INVOICE_FIELDS}
    facts["invoice_number"] = "INV-001"
    return canonicalize_jcs(
        {
            "facts": facts,
            "field_evidence": [{"field_code": "invoice_number", "evidence": _evidence(text)}],
            "items": [],
        }
    ).decode("utf-8")


def _contract_block() -> ContractSourceBlock:
    return ContractSourceBlock(
        id=_BLOCK_ID,
        parse_version_id=_PARSE_VERSION_ID,
        page_no=1,
        block_index=0,
        text="合同编号：HT-001",
        bbox={"left": 1, "top": 2, "width": 100, "height": 10},
        confidence=Decimal("0.95000"),
    )


def _invoice_block() -> InvoiceSourceBlock:
    return InvoiceSourceBlock(
        id=_BLOCK_ID,
        parse_version_id=_PARSE_VERSION_ID,
        page_no=1,
        block_index=0,
        text="发票号码：INV-001",
        bbox={"left": 1, "top": 2, "width": 100, "height": 10},
        confidence=Decimal("0.95000"),
    )


def _service(invoker: _QueuedInvoker) -> AiExtractionService:
    return AiExtractionService(
        cast(AuditedLlmInvoker, invoker),
        LIVE_LLM_POLICY,
        monotonic_clock=lambda: 100.0,
    )


def test_contract_invalid_output_uses_a_separately_audited_repair_call() -> None:
    invoker = _QueuedInvoker(["not-json", _contract_output("合同编号：HT-001")])

    result = _service(invoker).extract_contract(
        organization_id=_ORGANIZATION_ID,
        job_id=_JOB_ID,
        file_id=_FILE_ID,
        trace_id=_TRACE_ID,
        blocks=(_contract_block(),),
    )

    assert result.candidate.facts.contract_no == "HT-001"
    assert result.adoption is invoker.adoption
    assert [item.logical_generation_no for item in invoker.identities] == [1, 2]
    assert [item.provider_attempt_no for item in invoker.identities] == [1, 2]
    assert [item.prompt_id for item in invoker.identities] == [
        "contract-field-extraction",
        "contract-field-extraction-repair",
    ]
    assert invoker.repair_slots == [2, 1]
    assert all("not-json" not in request.user_content for request in invoker.requests)


def test_invoice_valid_output_is_returned_without_repair() -> None:
    invoker = _QueuedInvoker([_invoice_output("发票号码：INV-001")])

    result = _service(invoker).extract_invoice(
        organization_id=_ORGANIZATION_ID,
        job_id=_JOB_ID,
        file_id=_FILE_ID,
        trace_id=_TRACE_ID,
        blocks=(_invoice_block(),),
    )

    assert result.candidate.facts.invoice_number == "INV-001"
    assert result.candidate.items == ()
    assert [item.prompt_id for item in invoker.identities] == ["invoice-field-extraction"]
    assert invoker.repair_slots == [2]


def test_extraction_stops_after_the_policy_repair_limit() -> None:
    invoker = _QueuedInvoker(["invalid-1", "invalid-2", "invalid-3"])

    with pytest.raises(AiExtractionServiceError) as exc_info:
        _service(invoker).extract_contract(
            organization_id=_ORGANIZATION_ID,
            job_id=_JOB_ID,
            file_id=_FILE_ID,
            trace_id=_TRACE_ID,
            blocks=(_contract_block(),),
        )

    assert exc_info.value.code == "AI_STRUCTURED_OUTPUT_INVALID"
    assert [item.logical_generation_no for item in invoker.identities] == [1, 2, 3]
    assert invoker.repair_slots == [2, 1, 0]


def test_provider_failure_does_not_trigger_a_model_repair() -> None:
    invoker = _QueuedInvoker([AuditedLlmInvocationError("AI_RATE_LIMITED")])

    with pytest.raises(AiExtractionServiceError) as exc_info:
        _service(invoker).extract_invoice(
            organization_id=_ORGANIZATION_ID,
            job_id=_JOB_ID,
            file_id=_FILE_ID,
            trace_id=_TRACE_ID,
            blocks=(_invoice_block(),),
        )

    assert exc_info.value.code == "AI_RATE_LIMITED"
    assert len(invoker.identities) == 1
