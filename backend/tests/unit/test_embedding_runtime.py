from __future__ import annotations

import time
from typing import cast
from uuid import UUID

import pytest

from app.ai.contracts import (
    EmbeddingRequest,
    EmbeddingResult,
    ExternalError,
    ExternalErrorCategory,
    ModelTarget,
    TransportPolicy,
)
from app.ai.embedding_runtime import (
    AuditedEmbeddingResult,
    EmbeddingCallIdentity,
    EmbeddingInvocationError,
    EmbeddingRuntime,
    create_deterministic_embedding_runtime,
)
from app.ai.events import AiCallCompletedV2, AiCallLateCompletionV2, AiCallStartedV2
from app.ai.gateway import AiGateway
from app.ai.live_policy import (
    LIVE_EMBEDDING_POLICY,
    LIVE_POLICY_HASH,
    LIVE_POLICY_ID,
    LIVE_POLICY_RAW_SHA256,
)
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
from app.services.ai_call_event_sink import AiCallAuditWriter

_TRACE_ID = UUID("11111111-1111-4111-8111-111111111111")
_ORGANIZATION_ID = UUID("22222222-2222-4222-8222-222222222222")
_OPERATION_ID = UUID("33333333-3333-4333-8333-333333333333")


class _ErrorAdapter:
    def __init__(self, category: ExternalErrorCategory) -> None:
        self._category = category

    def embed(
        self,
        request: EmbeddingRequest,
        target: ModelTarget,
        policy: TransportPolicy,
    ) -> ExternalError:
        del target, policy
        return ExternalError(trace_id=request.trace_id, category=self._category)


class _SuccessAdapter:
    def embed(
        self,
        request: EmbeddingRequest,
        target: ModelTarget,
        policy: TransportPolicy,
    ) -> EmbeddingResult:
        del policy
        return EmbeddingResult(
            trace_id=request.trace_id,
            target=target,
            vectors=tuple((float(index),) for index, _ in enumerate(request.input_texts)),
        )


class _AuditedSuccessAdapter:
    def __init__(self, *, input_tokens: int = 1) -> None:
        self._input_tokens = input_tokens

    def embed(
        self,
        request: EmbeddingRequest,
        target: ModelTarget,
        policy: TransportPolicy,
    ) -> EmbeddingResult:
        del policy
        return EmbeddingResult(
            trace_id=request.trace_id,
            target=target,
            vectors=tuple((float(index),) for index, _ in enumerate(request.input_texts)),
            input_tokens=self._input_tokens,
            response_body_sha256="d" * 64,
        )


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
    breaker_state = "closed"

    def __init__(self, *, fail_on_finish: bool = False) -> None:
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


def _runtime_with_control(
    adapter: _SuccessAdapter | _ErrorAdapter,
    control: _RuntimeControl,
) -> EmbeddingRuntime:
    target = ModelTarget("embedding-test", "model-test")
    return EmbeddingRuntime(
        gateway=AiGateway(
            llm_adapters={},
            embedding_adapters={target.adapter_id: adapter},
        ),
        target=target,
        transport_policy=TransportPolicy(1, 2, 3, 1),
        runtime_control=cast(AiRuntimeController, control),
    )


def _audited_runtime(
    writer: _AuditWriter,
    *,
    input_tokens: int = 1,
) -> EmbeddingRuntime:
    target = ModelTarget("openai_embeddings_v1", LIVE_EMBEDDING_POLICY.model_id)
    return EmbeddingRuntime(
        gateway=AiGateway(
            llm_adapters={},
            embedding_adapters={
                target.adapter_id: _AuditedSuccessAdapter(input_tokens=input_tokens)
            },
        ),
        target=target,
        transport_policy=TransportPolicy(1, 2, 3, 1),
        policy_snapshot=ValidatedPolicySnapshot(
            policy_version=2,
            policy_hash=LIVE_POLICY_HASH,
            raw_sha256=LIVE_POLICY_RAW_SHA256,
            provider_calls_enabled=True,
            runtime_profile_id=LIVE_POLICY_ID,
        ),
        embedding_policy=LIVE_EMBEDDING_POLICY,
        audit_writer=cast(AiCallAuditWriter, writer),
    )


def _identity() -> EmbeddingCallIdentity:
    return EmbeddingCallIdentity(
        organization_id=_ORGANIZATION_ID,
        business_operation_id=_OPERATION_ID,
        job_id=None,
        request_id=_TRACE_ID,
        resource_type="knowledge_base",
        resource_id=None,
        trace_id=_TRACE_ID,
    )


def test_deterministic_embedding_runtime_uses_the_gateway_contract() -> None:
    runtime = create_deterministic_embedding_runtime(
        model_id="offline-test",
        vector_size=8,
        deadline_seconds=30,
    )

    vectors = runtime.embed_texts(
        trace_id="trace-offline",
        input_texts=("合同金额", "发票日期"),
    )

    assert runtime.target == ModelTarget("deterministic_hash_v1", "offline-test")
    assert len(vectors) == 2
    assert all(len(vector) == 8 for vector in vectors)


def test_embedding_runtime_preserves_transient_disposition_without_provider_details() -> None:
    target = ModelTarget("embedding-test", "model-test")
    runtime = EmbeddingRuntime(
        gateway=AiGateway(
            llm_adapters={},
            embedding_adapters={
                target.adapter_id: _ErrorAdapter(ExternalErrorCategory.RATE_LIMITED)
            },
        ),
        target=target,
        transport_policy=TransportPolicy(1, 2, 3, 1),
    )

    try:
        runtime.embed_texts(trace_id="trace-rate-limit", input_texts=("input",))
    except EmbeddingInvocationError as error:
        assert error.code == "EMBEDDING_RATE_LIMITED"
        assert error.retryable is True
        assert "input" not in repr(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("expected EmbeddingInvocationError")


def test_embedding_runtime_marks_invalid_response_as_permanent() -> None:
    target = ModelTarget("embedding-test", "model-test")
    runtime = EmbeddingRuntime(
        gateway=AiGateway(
            llm_adapters={},
            embedding_adapters={
                target.adapter_id: _ErrorAdapter(ExternalErrorCategory.INVALID_RESPONSE)
            },
        ),
        target=target,
        transport_policy=TransportPolicy(1, 2, 3, 1),
    )

    try:
        runtime.embed_texts(trace_id="trace-invalid", input_texts=("input",))
    except EmbeddingInvocationError as error:
        assert error.code == "EMBEDDING_INVALID_RESPONSE"
        assert error.retryable is False
    else:  # pragma: no cover - assertion branch
        raise AssertionError("expected EmbeddingInvocationError")


def test_embedding_runtime_acquires_and_finishes_shared_control() -> None:
    permit = _RuntimePermit()
    control = _RuntimeControl(permit=permit)
    runtime = _runtime_with_control(_SuccessAdapter(), control)

    vectors = runtime.embed_texts(
        trace_id="trace-controlled",
        input_texts=("合同", "A"),
    )

    assert vectors == ((0.0,), (1.0,))
    assert control.acquisitions == [
        (
            P0RateLimitPool.EMBEDDING,
            ModelTarget("embedding-test", "model-test"),
            7,
            3,
        )
    ]
    assert permit.outcomes == ["success"]


def test_embedding_runtime_marks_transient_provider_failure_for_breaker() -> None:
    permit = _RuntimePermit()
    control = _RuntimeControl(permit=permit)
    runtime = _runtime_with_control(
        _ErrorAdapter(ExternalErrorCategory.RATE_LIMITED),
        control,
    )

    with pytest.raises(EmbeddingInvocationError) as exc_info:
        runtime.embed_texts(trace_id="trace-transient", input_texts=("input",))

    assert exc_info.value.code == "EMBEDDING_RATE_LIMITED"
    assert permit.outcomes == ["transient_failure"]


def test_embedding_runtime_control_denial_prevents_adapter_call() -> None:
    control = _RuntimeControl(error=AiRuntimeControlError("AI_BREAKER_OPEN"))
    runtime = _runtime_with_control(_SuccessAdapter(), control)

    with pytest.raises(EmbeddingInvocationError) as exc_info:
        runtime.embed_texts(trace_id="trace-open", input_texts=("input",))

    assert exc_info.value.code == "AI_BREAKER_OPEN"
    assert exc_info.value.retryable is True


def test_embedding_runtime_discards_success_when_permit_finish_fails() -> None:
    permit = _RuntimePermit(fail_on_finish=True)
    runtime = _runtime_with_control(
        _SuccessAdapter(),
        _RuntimeControl(permit=permit),
    )

    with pytest.raises(EmbeddingInvocationError) as exc_info:
        runtime.embed_texts(trace_id="trace-finish", input_texts=("input",))

    assert exc_info.value.code == "AI_RUNTIME_CONTROL_UNAVAILABLE"
    assert exc_info.value.retryable is True
    assert permit.outcomes == ["success"]


def test_audited_embedding_reserves_cny_before_provider_and_waits_for_adoption() -> None:
    writer = _AuditWriter()
    runtime = _audited_runtime(writer)

    result = runtime.embed_texts_audited(
        trace_id=str(_TRACE_ID),
        input_texts=("A",),
        identity=_identity(),
        deadline_monotonic=time.monotonic() + 30,
    )

    assert isinstance(result, AuditedEmbeddingResult)
    assert result.vectors == ((0.0,),)
    assert result.cost_currency == "CNY"
    assert result.actual_cost_microunits == 1
    assert len(writer.started) == 1
    assert writer.started[0].event_version == 2
    assert writer.started[0].cost_currency == "CNY"
    assert writer.started[0].reserved_cost_microunits == 1
    assert writer.completed == []


def test_audited_embedding_rejects_provider_usage_above_reservation() -> None:
    writer = _AuditWriter()
    runtime = _audited_runtime(writer, input_tokens=2)

    with pytest.raises(EmbeddingInvocationError) as exc_info:
        runtime.embed_texts_audited(
            trace_id=str(_TRACE_ID),
            input_texts=("A",),
            identity=_identity(),
            deadline_monotonic=time.monotonic() + 30,
        )

    assert exc_info.value.code == "EMBEDDING_USAGE_EXCEEDS_RESERVATION"
    assert len(writer.completed) == 1
    assert writer.completed[0].status == "rejected"
    assert writer.completed[0].cost_currency == "CNY"
    assert writer.completed[0].actual_cost_microunits == 1
