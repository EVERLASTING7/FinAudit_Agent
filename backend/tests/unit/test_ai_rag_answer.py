from __future__ import annotations

from collections.abc import Callable
from typing import cast
from uuid import UUID

import pytest

from app.ai.contracts import LlmRequest
from app.ai.live_policy import LIVE_LLM_POLICY, LiveOperationPolicy
from app.ai.output_validation import RagCitation
from app.ai.policy import canonicalize_jcs
from app.ai.rag_prompts import RagPromptCandidate
from app.services.ai_rag_answer import AiRagAnswerService, AiRagAnswerServiceError
from app.services.audited_llm import (
    AuditedLlmAdoption,
    AuditedLlmInvocationError,
    AuditedLlmInvoker,
    AuditedLlmOutputRejected,
    AuditedLlmResult,
    LlmCallIdentity,
)

_ORGANIZATION_ID = UUID("93000000-0000-4000-8000-000000000001")
_QUERY_ID = UUID("93000000-0000-4000-8000-000000000002")
_TRACE_ID = UUID("93000000-0000-4000-8000-000000000003")
_POLICY_ID = UUID("93000000-0000-4000-8000-000000000004")
_MARKDOWN_ID = UUID("93000000-0000-4000-8000-000000000005")
_CHUNK_ID = UUID("93000000-0000-4000-8000-000000000006")
_BLOCK_ID = UUID("93000000-0000-4000-8000-000000000007")
_INDEX_ID = UUID("93000000-0000-4000-8000-000000000008")
_POINT_ID = UUID("93000000-0000-4000-8000-000000000009")


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


def _citation(*, quote: str = "差旅住宿费标准为每晚五百元。") -> RagCitation:
    return RagCitation(
        candidate_id=str(_POINT_ID),
        policy_document_id=str(_POLICY_ID),
        policy_version="1.0",
        markdown_version_id=str(_MARKDOWN_ID),
        chunk_id=str(_CHUNK_ID),
        block_ids=(str(_BLOCK_ID),),
        index_version_id=str(_INDEX_ID),
        page_range="2-3",
        title_path=("差旅", "住宿"),
        quote=quote,
        content_sha256="a" * 64,
    )


def _candidate() -> RagPromptCandidate:
    return RagPromptCandidate(
        citation=_citation(),
        policy_name="差旅管理制度",
        content="差旅住宿费标准为每晚五百元。",
    )


def _answer(*, citation: RagCitation | None = None) -> str:
    return canonicalize_jcs(
        {
            "answer_status": "answered",
            "answer": "住宿费标准为每晚五百元。",
            "reason_code": None,
            "citations": [(citation or _citation()).model_dump(mode="json")],
            "confidence": "0.900000",
            "warnings": [],
        }
    ).decode("utf-8")


def _service(invoker: _QueuedInvoker) -> AiRagAnswerService:
    return AiRagAnswerService(
        cast(AuditedLlmInvoker, invoker),
        LIVE_LLM_POLICY,
        monotonic_clock=lambda: 100.0,
    )


def _call(service: AiRagAnswerService):  # type: ignore[no-untyped-def]
    return service.answer(
        organization_id=_ORGANIZATION_ID,
        query_id=_QUERY_ID,
        trace_id=_TRACE_ID,
        question="差旅住宿费标准是多少？",
        candidates=(_candidate(),),
    )


def test_valid_rag_answer_returns_a_pending_atomic_adoption() -> None:
    invoker = _QueuedInvoker([_answer()])

    result = _call(_service(invoker))

    assert result.output.answer == "住宿费标准为每晚五百元。"
    assert result.output.citations == (_citation(),)
    assert result.adoption is invoker.adoption
    assert [identity.call_type for identity in invoker.identities] == ["rag_answer"]
    assert [identity.business_operation_id for identity in invoker.identities] == [_QUERY_ID]


def test_citation_drift_uses_a_separately_audited_repair_without_echoing_output() -> None:
    invalid = _answer(citation=_citation(quote="被模型改写的引用"))
    invoker = _QueuedInvoker([invalid, _answer()])

    result = _call(_service(invoker))

    assert result.output.answer_status == "answered"
    assert [identity.prompt_id for identity in invoker.identities] == [
        "rag-answer",
        "rag-answer-repair",
    ]
    assert invoker.repair_slots == [2, 1]
    assert all("被模型改写的引用" not in request.user_content for request in invoker.requests)


def test_model_cannot_claim_a_system_owned_refusal_reason() -> None:
    forbidden_refusal = canonicalize_jcs(
        {
            "answer_status": "refused",
            "answer": None,
            "reason_code": "UNAUTHORIZED_EVIDENCE",
            "citations": [],
            "confidence": None,
            "warnings": [],
        }
    ).decode("utf-8")
    invoker = _QueuedInvoker([forbidden_refusal] * 3)

    with pytest.raises(AiRagAnswerServiceError) as exc_info:
        _call(_service(invoker))

    assert exc_info.value.code == "AI_STRUCTURED_OUTPUT_INVALID"
    assert len(invoker.identities) == 3


def test_provider_failure_does_not_trigger_a_structure_repair() -> None:
    invoker = _QueuedInvoker([AuditedLlmInvocationError("AI_RATE_LIMITED")])

    with pytest.raises(AiRagAnswerServiceError) as exc_info:
        _call(_service(invoker))

    assert exc_info.value.code == "AI_RATE_LIMITED"
    assert len(invoker.identities) == 1
