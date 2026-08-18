from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from importlib import resources
from typing import cast
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from app.ai.adapters.openai_compatible import (
    OpenAiChatCompletionsAdapter,
    OpenAiCompatibleProfile,
)
from app.ai.contracts import LlmRequest, ModelTarget
from app.ai.events import AiCallCompletedV2, AiCallLateCompletionV2, AiCallStartedV2
from app.ai.gateway import AiGateway
from app.ai.live_policy import LIVE_LLM_POLICY, LIVE_POLICY_HASH, LIVE_POLICY_ID
from app.ai.network_policy import OutboundNetworkPolicy
from app.ai.policy_loader import ValidatedPolicySnapshot
from app.ai.redis_runtime_control import (
    AiRuntimeControlError,
    AiRuntimeController,
    RuntimeOutcome,
)
from app.ai.routing import P0RateLimitPool
from app.repositories.ai_call_audit import (
    AiCallAuditLimitsV2,
    AiCallCompleteStatus,
    AiCallReserveStatus,
)
from app.services.audited_llm import (
    AuditedLlmInvocationError,
    AuditedLlmInvoker,
    AuditedLlmOutputRejected,
    AuditedLlmResult,
    LlmCallIdentity,
)

_TRACE_ID = UUID("11111111-1111-1111-1111-111111111111")
_ORGANIZATION_ID = UUID("22222222-2222-2222-2222-222222222222")
_JOB_ID = UUID("33333333-3333-3333-3333-333333333333")
_FILE_ID = UUID("44444444-4444-4444-4444-444444444444")
_REGISTRY_BYTES = (
    resources.files("app.ai.artifacts.cr011_v1").joinpath("ip-deny-cidrs-v1.json").read_bytes()
)


class _StaticByteStream(httpx.SyncByteStream):
    def __init__(self, content: bytes) -> None:
        self._content = content

    def __iter__(self) -> Iterator[bytes]:
        yield self._content


class _AuditWriter:
    def __init__(self) -> None:
        self.started: list[AiCallStartedV2] = []
        self.completed: list[AiCallCompletedV2] = []

    def reserve_attempt(
        self,
        event: AiCallStartedV2,
        limits: AiCallAuditLimitsV2,
        *,
        deadline_monotonic: float,
        minimum_attempt_seconds: float = 0.0,
    ) -> AiCallReserveStatus:
        del limits, deadline_monotonic, minimum_attempt_seconds
        self.started.append(event)
        return AiCallReserveStatus.RESERVED_NEW

    def complete_attempt(
        self,
        event: AiCallCompletedV2 | AiCallLateCompletionV2,
    ) -> AiCallCompleteStatus:
        assert isinstance(event, AiCallCompletedV2)
        self.completed.append(event)
        return AiCallCompleteStatus.COMPLETED_NEW


class _RuntimePermit:
    def __init__(
        self,
        *,
        breaker_state: str = "closed",
        fail_on_finish: bool = False,
    ) -> None:
        self.breaker_state = breaker_state
        self.fail_on_finish = fail_on_finish
        self.outcomes: list[RuntimeOutcome] = []

    def finish(self, outcome: RuntimeOutcome) -> None:
        self.outcomes.append(outcome)
        if self.fail_on_finish:
            raise AiRuntimeControlError("AI_RUNTIME_CONTROL_UNAVAILABLE")


class _RuntimeControl:
    def __init__(
        self,
        *,
        permit: _RuntimePermit | None = None,
        error: AiRuntimeControlError | None = None,
    ) -> None:
        self.permit = permit or _RuntimePermit()
        self.error = error
        self.acquisitions: list[tuple[P0RateLimitPool, ModelTarget, int, float]] = []

    def acquire(
        self,
        *,
        pool: P0RateLimitPool,
        target: ModelTarget,
        estimated_tokens: int,
        lease_seconds: float,
    ) -> _RuntimePermit:
        self.acquisitions.append((pool, target, estimated_tokens, lease_seconds))
        if self.error is not None:
            raise self.error
        return self.permit


def _response(
    content: str,
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
) -> httpx.Response:
    body = json.dumps(
        {
            "model": "MiniMax-M3",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        },
        separators=(",", ":"),
    ).encode()
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        stream=_StaticByteStream(body),
    )


def _invoker(
    response: httpx.Response,
    writer: _AuditWriter,
    *,
    register_adapter: bool = True,
    runtime_control: _RuntimeControl | None = None,
) -> tuple[AuditedLlmInvoker, OpenAiChatCompletionsAdapter]:
    policy = OutboundNetworkPolicy(
        endpoint_id=LIVE_LLM_POLICY.endpoint_id,
        network_scope="external_public",
        base_url=LIVE_LLM_POLICY.base_url,
        approved_hostnames=LIVE_LLM_POLICY.approved_hostnames,
        allowed_cidrs=(),
        billing_mode="external_usd",
        address_policy_version="ip-deny-cidrs-v1",
        registry_sha256=("628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"),
    )
    adapter = OpenAiChatCompletionsAdapter(
        OpenAiCompatibleProfile(
            profile_type="chat",
            base_url=LIVE_LLM_POLICY.base_url,
            model_id=LIVE_LLM_POLICY.model_id,
            allowed_response_model_ids=LIVE_LLM_POLICY.allowed_response_model_ids,
            api_key=SecretStr("synthetic-test-key"),
            network_policy=policy,
            registry_bytes=_REGISTRY_BYTES,
            use_max_completion_tokens=True,
            thinking_mode="disabled",
            service_tier="standard",
        ),
        transport=httpx.MockTransport(lambda _request: response),
        resolver=lambda _hostname, _port: ("8.8.8.8",),
        peer_address_reader=lambda _response: "8.8.8.8",
    )
    gateway = AiGateway(
        llm_adapters=({adapter.target.adapter_id: adapter} if register_adapter else {}),
        embedding_adapters={},
    )
    invoker = AuditedLlmInvoker(
        session_factory=cast(sessionmaker[Session], object()),
        gateway=gateway,
        adapter=adapter,
        policy_snapshot=ValidatedPolicySnapshot(
            policy_version=2,
            policy_hash=LIVE_POLICY_HASH,
            raw_sha256="a" * 64,
            provider_calls_enabled=True,
            runtime_profile_id=LIVE_POLICY_ID,
        ),
        llm_policy=LIVE_LLM_POLICY,
        audit_writer=writer,
        runtime_control=(
            None if runtime_control is None else cast(AiRuntimeController, runtime_control)
        ),
    )
    return invoker, adapter


def _identity() -> LlmCallIdentity:
    return LlmCallIdentity(
        organization_id=_ORGANIZATION_ID,
        business_operation_id=_JOB_ID,
        job_id=_JOB_ID,
        resource_type="file",
        resource_id=_FILE_ID,
        trace_id=_TRACE_ID,
        call_type="contract_field_extraction",
        logical_generation_no=1,
        provider_attempt_no=1,
        prompt_id="contract-field-extraction",
        prompt_version="v1",
        prompt_hash="b" * 64,
        schema_version="contract-extraction-output-v1",
    )


def _default_validator(value: str) -> object:
    return cast(object, json.loads(value))


def _invoke(
    invoker: AuditedLlmInvoker,
    *,
    user_content: str = "document",
    validator: Callable[[str], object] = _default_validator,
) -> AuditedLlmResult[object]:
    operation = LIVE_LLM_POLICY.operations["contract_field_extraction"]
    return invoker.invoke(
        request=LlmRequest(
            trace_id=str(_TRACE_ID),
            system_instruction="Return strict JSON.",
            user_content=user_content,
        ),
        identity=_identity(),
        operation=operation,
        deadline_monotonic=time.monotonic() + operation.deadline_seconds,
        future_model_repair_slots=2,
        validate_output=validator,
    )


def test_success_reserves_before_send_and_defers_completion_to_business_uow() -> None:
    writer = _AuditWriter()
    invoker, adapter = _invoker(_response('{"ok":true}'), writer)
    try:
        result = _invoke(invoker)
    finally:
        adapter.close()

    assert result.value == {"ok": True}
    assert len(writer.started) == 1
    assert writer.completed == []
    assert writer.started[0].input_hash != "0" * 64
    assert writer.started[0].reserved_input_tokens > len("document")


def test_invalid_structured_output_is_rejected_and_audited() -> None:
    writer = _AuditWriter()
    invoker, adapter = _invoker(_response("not-json"), writer)
    try:
        with pytest.raises(AuditedLlmOutputRejected):
            _invoke(invoker)
    finally:
        adapter.close()

    assert len(writer.started) == 1
    assert len(writer.completed) == 1
    assert writer.completed[0].status == "rejected"
    assert writer.completed[0].safe_error_code == "AI_STRUCTURED_OUTPUT_INVALID"


def test_provider_usage_over_reservation_is_never_adoptable() -> None:
    writer = _AuditWriter()
    invoker, adapter = _invoker(
        _response('{"ok":true}', prompt_tokens=999_999),
        writer,
    )
    try:
        with pytest.raises(AuditedLlmInvocationError) as exc_info:
            _invoke(invoker)
    finally:
        adapter.close()

    assert exc_info.value.code == "AI_USAGE_EXCEEDS_RESERVATION"
    assert writer.completed[0].status == "rejected"


def test_oversized_input_is_rejected_before_audit_or_provider_send() -> None:
    writer = _AuditWriter()
    invoker, adapter = _invoker(_response('{"ok":true}'), writer)
    try:
        with pytest.raises(AuditedLlmInvocationError) as exc_info:
            _invoke(invoker, user_content="x" * 270_000)
    finally:
        adapter.close()

    assert exc_info.value.code == "AI_BUDGET_PREFLIGHT_REJECTED"
    assert writer.started == []
    assert writer.completed == []


def test_gateway_contract_failure_completes_the_reserved_audit_attempt() -> None:
    writer = _AuditWriter()
    invoker, adapter = _invoker(
        _response('{"ok":true}'),
        writer,
        register_adapter=False,
    )
    try:
        with pytest.raises(AuditedLlmInvocationError) as exc_info:
            _invoke(invoker)
    finally:
        adapter.close()

    assert exc_info.value.code == "AI_GATEWAY_FAILURE"
    assert len(writer.started) == 1
    assert len(writer.completed) == 1
    assert writer.completed[0].status == "failed"
    assert writer.completed[0].safe_error_code == "AI_GATEWAY_FAILURE"


def test_runtime_control_denial_happens_before_durable_reserve_or_send() -> None:
    writer = _AuditWriter()
    control = _RuntimeControl(error=AiRuntimeControlError("AI_RATE_LIMITED"))
    invoker, adapter = _invoker(
        _response('{"ok":true}'),
        writer,
        runtime_control=control,
    )
    try:
        with pytest.raises(AuditedLlmInvocationError) as exc_info:
            _invoke(invoker)
    finally:
        adapter.close()

    assert exc_info.value.code == "AI_RATE_LIMITED"
    assert len(control.acquisitions) == 1
    assert control.acquisitions[0][0] is P0RateLimitPool.ASYNC_GENERATION
    assert control.acquisitions[0][2] > 0
    assert writer.started == []
    assert writer.completed == []


def test_runtime_control_success_is_finished_and_breaker_state_is_audited() -> None:
    writer = _AuditWriter()
    permit = _RuntimePermit(breaker_state="half_open")
    control = _RuntimeControl(permit=permit)
    invoker, adapter = _invoker(
        _response('{"ok":true}'),
        writer,
        runtime_control=control,
    )
    try:
        result = _invoke(invoker)
    finally:
        adapter.close()

    assert result.value == {"ok": True}
    assert permit.outcomes == ["success"]
    assert writer.started[0].breaker_state == "half_open"


def test_runtime_control_records_transient_provider_failure() -> None:
    writer = _AuditWriter()
    permit = _RuntimePermit()
    control = _RuntimeControl(permit=permit)
    response = httpx.Response(
        503,
        headers={"content-type": "application/json"},
        stream=_StaticByteStream(b"{}"),
    )
    invoker, adapter = _invoker(response, writer, runtime_control=control)
    try:
        with pytest.raises(AuditedLlmInvocationError) as exc_info:
            _invoke(invoker)
    finally:
        adapter.close()

    assert exc_info.value.code == "AI_PROVIDER_SERVER_ERROR"
    assert permit.outcomes == ["transient_failure"]
    assert writer.completed[0].safe_error_code == "AI_PROVIDER_SERVER_ERROR"


def test_runtime_control_finish_failure_discards_provider_success_and_is_audited() -> None:
    writer = _AuditWriter()
    permit = _RuntimePermit(fail_on_finish=True)
    control = _RuntimeControl(permit=permit)
    invoker, adapter = _invoker(
        _response('{"ok":true}'),
        writer,
        runtime_control=control,
    )
    try:
        with pytest.raises(AuditedLlmInvocationError) as exc_info:
            _invoke(invoker)
    finally:
        adapter.close()

    assert exc_info.value.code == "AI_RUNTIME_CONTROL_UNAVAILABLE"
    assert permit.outcomes == ["success"]
    assert writer.completed[0].status == "failed"
    assert writer.completed[0].safe_error_code == "AI_RUNTIME_CONTROL_UNAVAILABLE"
