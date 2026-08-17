from __future__ import annotations

from collections.abc import Callable
from typing import cast
from uuid import UUID

import pytest

from app.ai.contracts import LlmRequest
from app.ai.live_policy import LIVE_LLM_POLICY, LiveOperationPolicy
from app.ai.policy import canonicalize_jcs
from app.ai.report_draft import FrozenReportFacts, ReportDraftPromptInput
from app.services.ai_report_draft import AiReportDraftService, AiReportDraftServiceError
from app.services.audited_llm import (
    AuditedLlmAdoption,
    AuditedLlmInvocationError,
    AuditedLlmInvoker,
    AuditedLlmOutputRejected,
    AuditedLlmResult,
    LlmCallIdentity,
)

_ORGANIZATION_ID = UUID("95000000-0000-4000-8000-000000000001")
_JOB_ID = UUID("95000000-0000-4000-8000-000000000002")
_REPORT_ID = UUID("95000000-0000-4000-8000-000000000003")
_EXECUTION_ID = UUID("95000000-0000-4000-8000-000000000004")
_TRACE_ID = UUID("95000000-0000-4000-8000-000000000005")


class _QueuedInvoker:
    def __init__(self, outputs: list[str | AuditedLlmInvocationError]) -> None:
        self.outputs = outputs
        self.requests: list[LlmRequest] = []
        self.identities: list[LlmCallIdentity] = []
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
        del operation, deadline_monotonic, future_model_repair_slots
        self.requests.append(request)
        self.identities.append(identity)
        output = self.outputs.pop(0)
        if isinstance(output, AuditedLlmInvocationError):
            raise output
        try:
            value = validate_output(output)
        except ValueError:
            raise AuditedLlmOutputRejected("AI_STRUCTURED_OUTPUT_INVALID") from None
        return AuditedLlmResult(value=value, adoption=self.adoption)


def _frozen() -> FrozenReportFacts:
    return FrozenReportFacts(
        report_id=str(_REPORT_ID),
        execution_id=str(_EXECUTION_ID),
        overall_level="high",
        active_risk_count=2,
        dismissed_risk_count=1,
        has_effective_high=True,
        has_unreviewed_high=False,
    )


def _prompt_input() -> ReportDraftPromptInput:
    return ReportDraftPromptInput(
        frozen=_frozen(),
        facts={"summary": {"active_risk_count": 2, "overall_level": "high"}},
    )


def _output(*, active_risk_count: int = 2) -> str:
    return canonicalize_jcs(
        {
            **_frozen().model_dump(mode="json"),
            "active_risk_count": active_risk_count,
            "executive_summary": "确定性规则识别到两项活动风险。",
            "scope_summary": "草稿覆盖当前冻结执行版本。",
            "risk_summary": "整体风险等级为 high。",
            "recommendations": ["由授权审核人复核风险事实。"],
            "warnings": ["AI 草稿不替代规则结果和人工复核。"],
        }
    ).decode("utf-8")


def _service(invoker: _QueuedInvoker) -> AiReportDraftService:
    return AiReportDraftService(
        cast(AuditedLlmInvoker, invoker),
        LIVE_LLM_POLICY,
        monotonic_clock=lambda: 100.0,
    )


def _call(service: AiReportDraftService):  # type: ignore[no-untyped-def]
    return service.draft(
        organization_id=_ORGANIZATION_ID,
        job_id=_JOB_ID,
        report_id=_REPORT_ID,
        trace_id=_TRACE_ID,
        prompt_input=_prompt_input(),
    )


def test_valid_report_draft_returns_pending_atomic_adoption() -> None:
    invoker = _QueuedInvoker([_output()])

    result = _call(_service(invoker))

    assert result.output.active_risk_count == 2
    assert result.output.report_id == str(_REPORT_ID)
    assert result.adoption is invoker.adoption
    assert [identity.call_type for identity in invoker.identities] == ["report_draft"]


def test_frozen_report_drift_uses_a_separately_audited_repair() -> None:
    invoker = _QueuedInvoker([_output(active_risk_count=3), _output()])

    result = _call(_service(invoker))

    assert result.output.active_risk_count == 2
    assert [identity.prompt_id for identity in invoker.identities] == [
        "report-draft",
        "report-draft-repair",
    ]
    assert all('"active_risk_count":3' not in request.user_content for request in invoker.requests)


def test_provider_failure_does_not_trigger_a_structure_repair() -> None:
    invoker = _QueuedInvoker([AuditedLlmInvocationError("AI_RATE_LIMITED")])

    with pytest.raises(AiReportDraftServiceError) as exc_info:
        _call(_service(invoker))

    assert exc_info.value.code == "AI_RATE_LIMITED"
    assert len(invoker.identities) == 1
