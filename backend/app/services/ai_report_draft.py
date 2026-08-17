"""正式报告真实 AI 草稿、结构修复和待原子采用结果。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError

from app.ai.live_policy import LiveLlmPolicy
from app.ai.report_draft import (
    REPORT_DRAFT_PROMPT,
    REPORT_DRAFT_REPAIR_PROMPT,
    REPORT_DRAFT_SCHEMA_VERSION,
    ReportDraftOutput,
    ReportDraftPromptInput,
    ReportDraftValidationError,
    build_report_draft_request,
    validate_report_draft,
)
from app.services.audited_llm import (
    AuditedLlmAdoption,
    AuditedLlmInvocationError,
    AuditedLlmInvoker,
    AuditedLlmOutputRejected,
    LlmCallIdentity,
)


class AiReportDraftServiceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AuditedReportDraft:
    output: ReportDraftOutput
    adoption: AuditedLlmAdoption


def _validate_model_output(
    value: str,
    *,
    prompt_input: ReportDraftPromptInput,
) -> ReportDraftOutput:
    try:
        output = ReportDraftOutput.model_validate_json(value)
        return validate_report_draft(output, frozen=prompt_input.frozen)
    except (ValidationError, ReportDraftValidationError, TypeError, ValueError):
        raise ValueError("invalid report draft model output") from None


class AiReportDraftService:
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

    def draft(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
        report_id: UUID,
        trace_id: UUID,
        prompt_input: ReportDraftPromptInput,
    ) -> AuditedReportDraft:
        operation = self._policy.operations["report_draft"]
        deadline = self._monotonic() + operation.deadline_seconds
        for attempt_no in range(1, operation.max_model_repairs + 2):
            prompt = REPORT_DRAFT_PROMPT if attempt_no == 1 else REPORT_DRAFT_REPAIR_PROMPT
            try:
                request = build_report_draft_request(
                    artifact=prompt,
                    trace_id=str(trace_id),
                    prompt_input=prompt_input,
                )
            except ValueError:
                raise AiReportDraftServiceError("AI_REPORT_INPUT_INVALID") from None
            try:
                result = self._invoker.invoke(
                    request=request,
                    identity=LlmCallIdentity(
                        organization_id=organization_id,
                        business_operation_id=report_id,
                        job_id=job_id,
                        resource_type="audit_report",
                        resource_id=report_id,
                        trace_id=trace_id,
                        call_type="report_draft",
                        logical_generation_no=attempt_no,
                        provider_attempt_no=attempt_no,
                        prompt_id=prompt.prompt_id,
                        prompt_version=prompt.prompt_version,
                        prompt_hash=prompt.prompt_hash,
                        schema_version=REPORT_DRAFT_SCHEMA_VERSION,
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
                raise AiReportDraftServiceError(error.code) from None
            return AuditedReportDraft(result.value, result.adoption)
        raise AiReportDraftServiceError("AI_STRUCTURED_OUTPUT_INVALID")


__all__ = [
    "AiReportDraftService",
    "AiReportDraftServiceError",
    "AuditedReportDraft",
]
