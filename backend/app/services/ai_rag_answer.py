"""RAG 真实生成、显式结构修复与待原子采用结果。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError

from app.ai.live_policy import LiveLlmPolicy
from app.ai.output_validation import (
    CitationValidationError,
    RagAnswerOutput,
    validate_rag_answer,
)
from app.ai.rag_prompts import (
    RAG_ANSWER_PROMPT,
    RAG_ANSWER_REPAIR_PROMPT,
    RAG_ANSWER_SCHEMA_VERSION,
    RagPromptCandidate,
    build_rag_prompt_request,
)
from app.services.audited_llm import (
    AuditedLlmAdoption,
    AuditedLlmInvocationError,
    AuditedLlmInvoker,
    AuditedLlmOutputRejected,
    LlmCallIdentity,
)


class AiRagAnswerServiceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AuditedRagAnswer:
    output: RagAnswerOutput
    adoption: AuditedLlmAdoption


def _validate_model_output(
    value: str,
    *,
    candidates: tuple[RagPromptCandidate, ...],
) -> RagAnswerOutput:
    try:
        output = RagAnswerOutput.model_validate_json(value)
        validated = validate_rag_answer(
            output,
            candidates=tuple(candidate.citation for candidate in candidates),
        )
    except (ValidationError, CitationValidationError, TypeError, ValueError):
        raise ValueError("invalid RAG model output") from None
    if validated.answer_status == "service_degraded":
        raise ValueError("model cannot decide service availability")
    if validated.answer_status == "refused" and validated.reason_code != "EVIDENCE_CONFLICT":
        raise ValueError("model refusal reason is outside its authority")
    return validated


class AiRagAnswerService:
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

    def answer(
        self,
        *,
        organization_id: UUID,
        query_id: UUID,
        trace_id: UUID,
        question: str,
        candidates: tuple[RagPromptCandidate, ...],
    ) -> AuditedRagAnswer:
        operation = self._policy.operations["rag_answer"]
        deadline = self._monotonic() + operation.deadline_seconds
        for attempt_no in range(1, operation.max_model_repairs + 2):
            prompt = RAG_ANSWER_PROMPT if attempt_no == 1 else RAG_ANSWER_REPAIR_PROMPT
            try:
                request = build_rag_prompt_request(
                    artifact=prompt,
                    trace_id=str(trace_id),
                    question=question,
                    candidates=candidates,
                )
            except ValueError:
                raise AiRagAnswerServiceError("AI_RAG_INPUT_INVALID") from None
            try:
                result = self._invoker.invoke(
                    request=request,
                    identity=LlmCallIdentity(
                        organization_id=organization_id,
                        business_operation_id=query_id,
                        job_id=None,
                        resource_type="qa_query",
                        resource_id=query_id,
                        trace_id=trace_id,
                        call_type="rag_answer",
                        logical_generation_no=attempt_no,
                        provider_attempt_no=attempt_no,
                        prompt_id=prompt.prompt_id,
                        prompt_version=prompt.prompt_version,
                        prompt_hash=prompt.prompt_hash,
                        schema_version=RAG_ANSWER_SCHEMA_VERSION,
                    ),
                    operation=operation,
                    deadline_monotonic=deadline,
                    future_model_repair_slots=operation.max_model_repairs - (attempt_no - 1),
                    validate_output=lambda value: _validate_model_output(
                        value,
                        candidates=candidates,
                    ),
                )
            except AuditedLlmOutputRejected:
                continue
            except AuditedLlmInvocationError as error:
                raise AiRagAnswerServiceError(error.code) from None
            return AuditedRagAnswer(result.value, result.adoption)
        raise AiRagAnswerServiceError("AI_STRUCTURED_OUTPUT_INVALID")


__all__ = [
    "AiRagAnswerService",
    "AiRagAnswerServiceError",
    "AuditedRagAnswer",
]
