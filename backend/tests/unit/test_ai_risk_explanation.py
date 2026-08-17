from __future__ import annotations

from collections.abc import Callable
from typing import cast
from uuid import UUID

import pytest

from app.ai.contracts import LlmRequest
from app.ai.live_policy import LIVE_LLM_POLICY, LiveOperationPolicy
from app.ai.output_validation import FrozenRuleResult
from app.ai.policy import canonicalize_jcs
from app.ai.risk_explanation_prompts import RiskExplanationPromptInput
from app.services.ai_risk_explanation import (
    AiRiskExplanationService,
    AiRiskExplanationServiceError,
)
from app.services.audited_llm import (
    AuditedLlmAdoption,
    AuditedLlmInvocationError,
    AuditedLlmInvoker,
    AuditedLlmOutputRejected,
    AuditedLlmResult,
    LlmCallIdentity,
)

_ORGANIZATION_ID = UUID("94000000-0000-4000-8000-000000000001")
_JOB_ID = UUID("94000000-0000-4000-8000-000000000002")
_RISK_ID = UUID("94000000-0000-4000-8000-000000000003")
_TRACE_ID = UUID("94000000-0000-4000-8000-000000000004")


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


def _prompt_input() -> RiskExplanationPromptInput:
    return RiskExplanationPromptInput(
        frozen_rule=FrozenRuleResult(
            rule_code="INV-001",
            rule_version="1",
            rule_status="failed",
            original_risk_level="high",
        ),
        title="发票金额超过合同余额",
        actual_value="1200.00",
        expected_value="1000.00",
        explanation_template="说明实际金额与合同余额差异。",
        requires_policy_citation=False,
        candidates=(),
    )


def _output(*, rule_code: str = "INV-001") -> str:
    return canonicalize_jcs(
        {
            "rule_code": rule_code,
            "rule_version": "1",
            "rule_status": "failed",
            "original_risk_level": "high",
            "summary": "实际金额高于冻结的合同余额。",
            "reasoning_summary": "实际值 1200.00 大于预期值 1000.00。",
            "business_impact": "可能造成超合同支付。",
            "recommended_action": "由审核人核对合同余额与发票。",
            "citations": [],
            "evidence_sufficient": False,
            "warnings": ["当前没有授权政策引用，需人工复核。"],
        }
    ).decode("utf-8")


def _service(invoker: _QueuedInvoker) -> AiRiskExplanationService:
    return AiRiskExplanationService(
        cast(AuditedLlmInvoker, invoker),
        LIVE_LLM_POLICY,
        monotonic_clock=lambda: 100.0,
    )


def _call(service: AiRiskExplanationService):  # type: ignore[no-untyped-def]
    return service.explain(
        organization_id=_ORGANIZATION_ID,
        job_id=_JOB_ID,
        risk_id=_RISK_ID,
        trace_id=_TRACE_ID,
        prompt_input=_prompt_input(),
    )


def test_valid_risk_explanation_returns_pending_atomic_adoption() -> None:
    invoker = _QueuedInvoker([_output()])

    result = _call(_service(invoker))

    assert result.risk_id == _RISK_ID
    assert result.output.rule_code == "INV-001"
    assert result.output.evidence_sufficient is False
    assert result.adoption is invoker.adoption
    assert [identity.call_type for identity in invoker.identities] == ["risk_explanation"]


def test_frozen_rule_drift_uses_a_separately_audited_repair() -> None:
    invoker = _QueuedInvoker([_output(rule_code="MODEL-CHANGED"), _output()])

    result = _call(_service(invoker))

    assert result.output.rule_code == "INV-001"
    assert [identity.prompt_id for identity in invoker.identities] == [
        "risk-explanation",
        "risk-explanation-repair",
    ]
    assert all("MODEL-CHANGED" not in request.user_content for request in invoker.requests)


def test_provider_failure_does_not_trigger_a_structure_repair() -> None:
    invoker = _QueuedInvoker([AuditedLlmInvocationError("AI_RATE_LIMITED")])

    with pytest.raises(AiRiskExplanationServiceError) as exc_info:
        _call(_service(invoker))

    assert exc_info.value.code == "AI_RATE_LIMITED"
    assert len(invoker.identities) == 1
