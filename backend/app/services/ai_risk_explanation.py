"""确定性风险事实之上的真实 AI 解释与待原子采用结果。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError

from app.ai.live_policy import LiveLlmPolicy
from app.ai.output_validation import (
    CitationValidationError,
    RiskExplanationOutput,
    RiskExplanationValidationError,
    validate_risk_explanation,
)
from app.ai.risk_explanation_prompts import (
    RISK_EXPLANATION_PROMPT,
    RISK_EXPLANATION_REPAIR_PROMPT,
    RISK_EXPLANATION_SCHEMA_VERSION,
    RiskExplanationPromptInput,
    build_risk_explanation_request,
)
from app.services.audited_llm import (
    AuditedLlmAdoption,
    AuditedLlmInvocationError,
    AuditedLlmInvoker,
    AuditedLlmOutputRejected,
    LlmCallIdentity,
)


class AiRiskExplanationServiceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AuditedRiskExplanation:
    risk_id: UUID
    output: RiskExplanationOutput
    adoption: AuditedLlmAdoption


def _validate_model_output(
    value: str,
    *,
    prompt_input: RiskExplanationPromptInput,
) -> RiskExplanationOutput:
    try:
        output = RiskExplanationOutput.model_validate_json(value)
        return validate_risk_explanation(
            output,
            frozen_rule=prompt_input.frozen_rule,
            candidates=prompt_input.candidates,
        )
    except (
        ValidationError,
        CitationValidationError,
        RiskExplanationValidationError,
        TypeError,
        ValueError,
    ):
        raise ValueError("invalid risk explanation model output") from None


class AiRiskExplanationService:
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

    def explain(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
        risk_id: UUID,
        trace_id: UUID,
        prompt_input: RiskExplanationPromptInput,
    ) -> AuditedRiskExplanation:
        operation = self._policy.operations["risk_explanation"]
        deadline = self._monotonic() + operation.deadline_seconds
        for attempt_no in range(1, operation.max_model_repairs + 2):
            prompt = RISK_EXPLANATION_PROMPT if attempt_no == 1 else RISK_EXPLANATION_REPAIR_PROMPT
            try:
                request = build_risk_explanation_request(
                    artifact=prompt,
                    trace_id=str(trace_id),
                    prompt_input=prompt_input,
                )
            except ValueError:
                raise AiRiskExplanationServiceError("AI_RISK_INPUT_INVALID") from None
            try:
                result = self._invoker.invoke(
                    request=request,
                    identity=LlmCallIdentity(
                        organization_id=organization_id,
                        business_operation_id=risk_id,
                        job_id=job_id,
                        resource_type="audit_risk",
                        resource_id=risk_id,
                        trace_id=trace_id,
                        call_type="risk_explanation",
                        logical_generation_no=attempt_no,
                        provider_attempt_no=attempt_no,
                        prompt_id=prompt.prompt_id,
                        prompt_version=prompt.prompt_version,
                        prompt_hash=prompt.prompt_hash,
                        schema_version=RISK_EXPLANATION_SCHEMA_VERSION,
                    ),
                    operation=operation,
                    deadline_monotonic=deadline,
                    future_model_repair_slots=operation.max_model_repairs - (attempt_no - 1),
                    validate_output=lambda value: _validate_model_output(
                        value,
                        prompt_input=prompt_input,
                    ),
                )
            except AuditedLlmOutputRejected:
                continue
            except AuditedLlmInvocationError as error:
                raise AiRiskExplanationServiceError(error.code) from None
            return AuditedRiskExplanation(risk_id, result.value, result.adoption)
        raise AiRiskExplanationServiceError("AI_STRUCTURED_OUTPUT_INVALID")


__all__ = [
    "AiRiskExplanationService",
    "AiRiskExplanationServiceError",
    "AuditedRiskExplanation",
]
