"""真实 LLM 单次物理调用的预算、持久审计与原子采用边界。"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.ai.adapters.openai_compatible import OpenAiChatCompletionsAdapter
from app.ai.contracts import (
    ExternalError,
    ExternalErrorCategory,
    LlmGenerationParameters,
    LlmRequest,
    LlmResult,
    TransportPolicy,
)
from app.ai.event_sink import (
    CallScopeToken,
    CompleteAttemptStatus,
    ReserveAttemptStatus,
    SinkEvent,
)
from app.ai.events import AiCallCompletedV1, AiCallStartedV1, validate_ai_call_event_v1
from app.ai.gateway import (
    AdapterNotRegisteredError,
    AiGateway,
    GatewayAdapterError,
    GatewayContractError,
)
from app.ai.live_policy import LiveLlmPolicy, LiveOperationPolicy
from app.ai.policy_loader import ValidatedPolicySnapshot
from app.ai.pricing import (
    BillingMode,
    BudgetProfile,
    PricingProfile,
    calculate_preflight_reservation,
    reconcile_actual_usage,
)
from app.repositories.ai_call_audit import AiCallAuditLimits
from app.services.ai_call_audit import (
    AiCallAuditService,
    TransactionalAiCallCompletionWriter,
)
from app.services.ai_call_event_sink import (
    AiCallAuditWriter,
    AiCallReserveContext,
    DurableAiCallEventSink,
)

ValidatedT = TypeVar("ValidatedT")

_SAFE_ERROR_BY_CATEGORY = {
    ExternalErrorCategory.CONNECTION_ERROR: "AI_CONNECTION_ERROR",
    ExternalErrorCategory.CONNECT_TIMEOUT: "AI_CONNECT_TIMEOUT",
    ExternalErrorCategory.READ_TIMEOUT: "AI_READ_TIMEOUT",
    ExternalErrorCategory.RATE_LIMITED: "AI_RATE_LIMITED",
    ExternalErrorCategory.SERVER_ERROR: "AI_PROVIDER_SERVER_ERROR",
    ExternalErrorCategory.CLIENT_ERROR: "AI_PROVIDER_CLIENT_ERROR",
    ExternalErrorCategory.CONTEXT_LIMIT: "AI_CONTEXT_LIMIT",
    ExternalErrorCategory.INVALID_RESPONSE: "AI_INVALID_RESPONSE",
    ExternalErrorCategory.CONTENT_REJECTED: "AI_CONTENT_REJECTED",
    ExternalErrorCategory.PROVIDER_CONFIGURATION_ERROR: "AI_PROVIDER_CONFIGURATION_ERROR",
    ExternalErrorCategory.OUTPUT_TRUNCATED: "AI_OUTPUT_TRUNCATED",
}


class AuditedLlmInvocationError(RuntimeError):
    """不携带 Provider 响应、文档正文或底层异常的固定失败。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AuditedLlmOutputRejected(AuditedLlmInvocationError):
    """Provider 成功返回，但严格业务输出校验失败；允许调用方发起 repair。"""


@dataclass(frozen=True, slots=True)
class LlmCallIdentity:
    organization_id: UUID
    business_operation_id: UUID
    job_id: UUID | None
    resource_type: str | None
    resource_id: UUID | None
    trace_id: UUID
    call_type: str
    logical_generation_no: int
    provider_attempt_no: int
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    schema_version: str
    event_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class _CompletionFacts:
    output_hash: str
    input_tokens: int
    output_tokens: int
    duration_ms: int


@dataclass(slots=True)
class AuditedLlmAdoption:
    """持有当前进程调用域；成功 completion 只能在业务事务内落库。"""

    _sink: DurableAiCallEventSink
    _scope: CallScopeToken
    _success_event: SinkEvent
    _completion_facts: _CompletionFacts
    _identity: LlmCallIdentity
    _policy_snapshot: ValidatedPolicySnapshot
    _used: bool = False

    def adopt_in_transaction(self, session: Session) -> None:
        if self._used:
            raise AuditedLlmInvocationError("AI_ADOPTION_ALREADY_USED")
        decision = self._sink.complete_attempt_in_transaction_sync(
            self._success_event,
            self._scope,
            TransactionalAiCallCompletionWriter(session),
        )
        if decision.status is not CompleteAttemptStatus.COMPLETED_NEW or decision.permit is None:
            raise AuditedLlmInvocationError("AI_AUDIT_ADOPTION_UNAVAILABLE")
        decision.permit.consume()
        self._used = True

    def reject_in_transaction(self, session: Session, *, safe_error_code: str) -> None:
        if self._used:
            raise AuditedLlmInvocationError("AI_ADOPTION_ALREADY_USED")
        rejected = _completed_event(
            identity=self._identity,
            policy_snapshot=self._policy_snapshot,
            status="rejected",
            completed_at=_utc_timestamp(),
            duration_ms=self._completion_facts.duration_ms,
            output_hash=self._completion_facts.output_hash,
            input_tokens=self._completion_facts.input_tokens,
            output_tokens=self._completion_facts.output_tokens,
            http_status=200,
            error_category="invalid_response",
            safe_error_code=safe_error_code,
        )
        decision = self._sink.complete_attempt_in_transaction_sync(
            SinkEvent(rejected),
            self._scope,
            TransactionalAiCallCompletionWriter(session),
        )
        if decision.status is not CompleteAttemptStatus.COMPLETED_NEW:
            raise AuditedLlmInvocationError("AI_AUDIT_REJECTION_UNAVAILABLE")
        self._used = True


@dataclass(frozen=True, slots=True)
class AuditedLlmResult(Generic[ValidatedT]):
    value: ValidatedT
    adoption: AuditedLlmAdoption


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _started_event(
    *,
    event_id: UUID,
    identity: LlmCallIdentity,
    policy_snapshot: ValidatedPolicySnapshot,
    llm_policy: LiveLlmPolicy,
    input_hash: str,
    reserved_input_tokens: int,
    reserved_output_tokens: int,
    reserved_cost_micro_usd: int,
    started_at: str,
) -> AiCallStartedV1:
    event = validate_ai_call_event_v1(
        {
            "event_id": str(event_id),
            "event_version": 1,
            "event_sequence": 1,
            "event_type": "ai.call.started",
            "aggregate_type": "ai_call",
            "aggregate_id": str(event_id),
            "organization_id": str(identity.organization_id),
            "business_operation_id": str(identity.business_operation_id),
            "job_id": None if identity.job_id is None else str(identity.job_id),
            "request_id": None,
            "resource_type": identity.resource_type,
            "resource_id": None if identity.resource_id is None else str(identity.resource_id),
            "trace_id": str(identity.trace_id),
            "call_type": identity.call_type,
            "logical_generation_no": identity.logical_generation_no,
            "provider_attempt_no": identity.provider_attempt_no,
            "adapter_id": "openai_chat_completions_v1",
            "endpoint_id": llm_policy.endpoint_id,
            "model_id": llm_policy.model_id,
            "model_version": llm_policy.model_version,
            "prompt_id": identity.prompt_id,
            "prompt_version": identity.prompt_version,
            "prompt_hash": identity.prompt_hash,
            "schema_version": identity.schema_version,
            "policy_version": policy_snapshot.policy_version,
            "policy_hash": policy_snapshot.policy_hash,
            "pricing_version": llm_policy.pricing_version,
            "input_hash": input_hash,
            "reserved_input_tokens": reserved_input_tokens,
            "reserved_output_tokens": reserved_output_tokens,
            "reserved_cost_micro_usd": reserved_cost_micro_usd,
            "attempt_count": identity.provider_attempt_no,
            "is_fallback": False,
            "breaker_state": None,
            "status": "pending",
            "started_at": started_at,
        }
    )
    if not isinstance(event, AiCallStartedV1):
        raise AuditedLlmInvocationError("AI_EVENT_BUILD_FAILED")
    return event


def _completed_event(
    *,
    identity: LlmCallIdentity,
    policy_snapshot: ValidatedPolicySnapshot,
    status: str,
    completed_at: str,
    duration_ms: int,
    output_hash: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    http_status: int | None,
    error_category: str | None,
    safe_error_code: str | None,
) -> AiCallCompletedV1:
    if identity.event_id is None:
        raise AuditedLlmInvocationError("AI_EVENT_BUILD_FAILED")
    event = validate_ai_call_event_v1(
        {
            "event_id": str(identity.event_id),
            "event_version": 1,
            "event_sequence": 2,
            "event_type": "ai.call.completed",
            "aggregate_type": "ai_call",
            "aggregate_id": str(identity.event_id),
            "organization_id": str(identity.organization_id),
            "business_operation_id": str(identity.business_operation_id),
            "job_id": None if identity.job_id is None else str(identity.job_id),
            "request_id": None,
            "trace_id": str(identity.trace_id),
            "policy_version": policy_snapshot.policy_version,
            "policy_hash": policy_snapshot.policy_hash,
            "status": status,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "output_hash": output_hash,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "vector_count": None,
            "http_status": http_status,
            "error_category": error_category,
            "safe_error_code": safe_error_code,
            "citation_validation_status": None,
        }
    )
    if not isinstance(event, AiCallCompletedV1):
        raise AuditedLlmInvocationError("AI_EVENT_BUILD_FAILED")
    return event


def _event_error_category(category: ExternalErrorCategory) -> str:
    if category in {
        ExternalErrorCategory.CONNECTION_ERROR,
        ExternalErrorCategory.CONNECT_TIMEOUT,
        ExternalErrorCategory.READ_TIMEOUT,
    }:
        return "transient"
    return str(category.value)


class AuditedLlmInvoker:
    """一次调用只发送一次；retry/repair 由上层显式创建新的审计 attempt。"""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        gateway: AiGateway,
        adapter: OpenAiChatCompletionsAdapter,
        policy_snapshot: ValidatedPolicySnapshot,
        llm_policy: LiveLlmPolicy,
        monotonic_clock: Callable[[], float] = time.monotonic,
        audit_writer: AiCallAuditWriter | None = None,
    ) -> None:
        if not policy_snapshot.provider_calls_enabled:
            raise ValueError("provider policy snapshot is not enabled")
        self._gateway = gateway
        self._adapter = adapter
        self._policy_snapshot = policy_snapshot
        self._llm_policy = llm_policy
        self._monotonic = monotonic_clock
        self._audit: AiCallAuditWriter = (
            AiCallAuditService(
                session_factory,
                monotonic_clock=monotonic_clock,
            )
            if audit_writer is None
            else audit_writer
        )

    def invoke(
        self,
        *,
        request: LlmRequest,
        identity: LlmCallIdentity,
        operation: LiveOperationPolicy,
        deadline_monotonic: float,
        future_model_repair_slots: int,
        validate_output: Callable[[str], ValidatedT],
    ) -> AuditedLlmResult[ValidatedT]:
        event_id = uuid4()
        identity = replace(identity, event_id=event_id)
        parameters = LlmGenerationParameters(
            temperature=self._llm_policy.temperature,
            top_p=self._llm_policy.top_p,
            max_tokens=operation.max_output_tokens_per_request,
        )
        request = replace(request, parameters=parameters)
        try:
            request_body = self._adapter.request_body(request, self._adapter.target)
        except ValueError:
            raise AuditedLlmInvocationError("AI_REQUEST_INVALID") from None

        # byte 数 + 4096 是 fail-closed 上界；Provider usage 超过时禁止采用。
        input_token_upper_bound = len(request_body) + 4_096
        pricing = PricingProfile(
            pricing_version=self._llm_policy.pricing_version,
            billing_mode=BillingMode.EXTERNAL_USD,
            input_price_micro_usd_per_million=(self._llm_policy.input_price_micro_usd_per_million),
            output_price_micro_usd_per_million=(
                self._llm_policy.output_price_micro_usd_per_million
            ),
        )
        budget = BudgetProfile(
            max_provider_attempts_per_business_operation=(
                operation.max_provider_attempts_per_business_operation
            ),
            max_input_tokens_per_request=operation.max_input_tokens_per_request,
            max_output_tokens_per_request=operation.max_output_tokens_per_request,
            max_total_tokens=operation.max_total_tokens,
            max_cost_micro_usd=operation.max_cost_micro_usd,
        )
        try:
            reservation = calculate_preflight_reservation(
                budget,
                pricing,
                provider_attempts_used=identity.provider_attempt_no - 1,
                future_model_repair_slots=future_model_repair_slots,
                reserved_total_tokens=0,
                reserved_cost_micro_usd=0,
                input_tokens=input_token_upper_bound,
                max_output_tokens=operation.max_output_tokens_per_request,
                context_window_tokens=self._llm_policy.context_window_tokens,
            )
        except ValueError:
            raise AuditedLlmInvocationError("AI_BUDGET_PREFLIGHT_REJECTED") from None

        started_at = _utc_timestamp()
        started = _started_event(
            event_id=event_id,
            identity=identity,
            policy_snapshot=self._policy_snapshot,
            llm_policy=self._llm_policy,
            input_hash=hashlib.sha256(request_body).hexdigest(),
            reserved_input_tokens=reservation.reserved_input_tokens,
            reserved_output_tokens=reservation.reserved_output_tokens,
            reserved_cost_micro_usd=reservation.reserved_cost_micro_usd,
            started_at=started_at,
        )
        limits = AiCallAuditLimits(
            max_provider_attempts_per_business_operation=(
                operation.max_provider_attempts_per_business_operation
            ),
            max_input_tokens_per_request=operation.max_input_tokens_per_request,
            max_output_tokens_per_request=operation.max_output_tokens_per_request,
            max_total_tokens=operation.max_total_tokens,
            max_cost_micro_usd=operation.max_cost_micro_usd,
        )
        sink = DurableAiCallEventSink(
            self._audit,
            reserve_context_factory=lambda _event: AiCallReserveContext(
                limits=limits,
                deadline_monotonic=deadline_monotonic,
                minimum_attempt_seconds=1.0,
            ),
        )
        started_sink_event = SinkEvent(started)
        scope = sink.create_call_scope(started_sink_event)
        reserve_decision = sink.reserve_attempt_sync(started_sink_event, scope)
        if reserve_decision.status is ReserveAttemptStatus.UNKNOWN:
            reserve_decision = sink.reserve_attempt_sync(started_sink_event, scope)
        if reserve_decision.permit is None or reserve_decision.status not in {
            ReserveAttemptStatus.RESERVED_NEW,
            ReserveAttemptStatus.REPLAYED_SAME,
        }:
            raise AuditedLlmInvocationError("AI_AUDIT_RESERVATION_UNAVAILABLE")

        remaining = deadline_monotonic - self._monotonic()
        if remaining <= 1.0:
            raise AuditedLlmInvocationError("AI_DEADLINE_EXHAUSTED")
        reserve_decision.permit.consume()
        call_started = self._monotonic()
        try:
            outcome = self._gateway.generate(
                request,
                self._adapter.target,
                TransportPolicy(
                    connect_timeout_seconds=min(5.0, remaining),
                    read_timeout_seconds=remaining,
                    total_timeout_seconds=remaining,
                    max_attempts=1,
                ),
            )
        except (AdapterNotRegisteredError, GatewayAdapterError, GatewayContractError):
            duration_ms = max(0, int((self._monotonic() - call_started) * 1_000))
            completed = _completed_event(
                identity=identity,
                policy_snapshot=self._policy_snapshot,
                status="failed",
                completed_at=_utc_timestamp(),
                duration_ms=duration_ms,
                output_hash=None,
                input_tokens=None,
                output_tokens=None,
                http_status=None,
                error_category="provider_configuration_error",
                safe_error_code="AI_GATEWAY_FAILURE",
            )
            self._complete_without_adoption(sink, scope, completed)
            raise AuditedLlmInvocationError("AI_GATEWAY_FAILURE") from None
        duration_ms = max(0, int((self._monotonic() - call_started) * 1_000))
        completed_at = _utc_timestamp()

        if isinstance(outcome, ExternalError):
            completed = _completed_event(
                identity=identity,
                policy_snapshot=self._policy_snapshot,
                status="failed",
                completed_at=completed_at,
                duration_ms=duration_ms,
                output_hash=None,
                input_tokens=None,
                output_tokens=None,
                http_status=outcome.status_code,
                error_category=_event_error_category(outcome.category),
                safe_error_code=_SAFE_ERROR_BY_CATEGORY[outcome.category],
            )
            self._complete_without_adoption(sink, scope, completed)
            raise AuditedLlmInvocationError(_SAFE_ERROR_BY_CATEGORY[outcome.category])

        assert isinstance(outcome, LlmResult)
        if (
            outcome.input_tokens is None
            or outcome.output_tokens is None
            or outcome.response_body_sha256 is None
        ):
            completed = _completed_event(
                identity=identity,
                policy_snapshot=self._policy_snapshot,
                status="failed",
                completed_at=completed_at,
                duration_ms=duration_ms,
                output_hash=outcome.response_body_sha256,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                http_status=200,
                error_category="invalid_response",
                safe_error_code="AI_USAGE_UNAVAILABLE",
            )
            self._complete_without_adoption(sink, scope, completed)
            raise AuditedLlmInvocationError("AI_USAGE_UNAVAILABLE")
        try:
            reconcile_actual_usage(
                pricing,
                reservation,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                total_tokens=outcome.input_tokens + outcome.output_tokens,
            )
        except ValueError:
            completed = _completed_event(
                identity=identity,
                policy_snapshot=self._policy_snapshot,
                status="rejected",
                completed_at=completed_at,
                duration_ms=duration_ms,
                output_hash=outcome.response_body_sha256,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                http_status=200,
                error_category="invalid_response",
                safe_error_code="AI_USAGE_EXCEEDS_RESERVATION",
            )
            self._complete_without_adoption(sink, scope, completed)
            raise AuditedLlmInvocationError("AI_USAGE_EXCEEDS_RESERVATION") from None

        try:
            value = validate_output(outcome.output_text)
        except ValueError:
            completed = _completed_event(
                identity=identity,
                policy_snapshot=self._policy_snapshot,
                status="rejected",
                completed_at=completed_at,
                duration_ms=duration_ms,
                output_hash=outcome.response_body_sha256,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                http_status=200,
                error_category="invalid_response",
                safe_error_code="AI_STRUCTURED_OUTPUT_INVALID",
            )
            self._complete_without_adoption(sink, scope, completed)
            raise AuditedLlmOutputRejected("AI_STRUCTURED_OUTPUT_INVALID") from None

        success = _completed_event(
            identity=identity,
            policy_snapshot=self._policy_snapshot,
            status="succeeded",
            completed_at=completed_at,
            duration_ms=duration_ms,
            output_hash=outcome.response_body_sha256,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            http_status=200,
            error_category=None,
            safe_error_code=None,
        )
        facts = _CompletionFacts(
            output_hash=outcome.response_body_sha256,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            duration_ms=duration_ms,
        )
        return AuditedLlmResult(
            value=value,
            adoption=AuditedLlmAdoption(
                _sink=sink,
                _scope=scope,
                _success_event=SinkEvent(success),
                _completion_facts=facts,
                _identity=identity,
                _policy_snapshot=self._policy_snapshot,
            ),
        )

    @staticmethod
    def _complete_without_adoption(
        sink: DurableAiCallEventSink,
        scope: CallScopeToken,
        completed: AiCallCompletedV1,
    ) -> None:
        event = SinkEvent(completed)
        decision = sink.complete_attempt_sync(event, scope)
        if decision.status is CompleteAttemptStatus.UNKNOWN:
            decision = sink.complete_attempt_sync(event, scope)
        if decision.status not in {
            CompleteAttemptStatus.COMPLETED_NEW,
            CompleteAttemptStatus.REPLAYED_SAME,
        }:
            raise AuditedLlmInvocationError("AI_AUDIT_COMPLETION_UNAVAILABLE")


__all__ = [
    "AuditedLlmAdoption",
    "AuditedLlmInvocationError",
    "AuditedLlmInvoker",
    "AuditedLlmOutputRejected",
    "AuditedLlmResult",
    "LlmCallIdentity",
]
