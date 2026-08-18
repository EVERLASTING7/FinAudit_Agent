"""Embedding 运行时及真实 Provider 的预算、审计与原子采用边界。"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.ai.adapters.deterministic_hash import DeterministicHashEmbeddingAdapter
from app.ai.contracts import (
    EmbeddingRequest,
    EmbeddingResult,
    ErrorDisposition,
    ExternalError,
    ExternalErrorCategory,
    ModelTarget,
    TransportPolicy,
)
from app.ai.event_sink import (
    CallScopeToken,
    CompleteAttemptStatus,
    ReserveAttemptStatus,
    SinkEvent,
)
from app.ai.events import AiCallCompletedV2, AiCallStartedV2, validate_ai_call_event_v2
from app.ai.gateway import (
    AdapterNotRegisteredError,
    AiGateway,
    GatewayAdapterError,
    GatewayContractError,
)
from app.ai.live_policy import LiveEmbeddingPolicy
from app.ai.policy import canonicalize_jcs
from app.ai.policy_loader import ValidatedPolicySnapshot
from app.ai.pricing import (
    BillingMode,
    BudgetProfileV2,
    CostCurrency,
    PricingProfileV2,
    calculate_preflight_reservation_v2,
    reconcile_actual_usage_v2,
)
from app.ai.redis_runtime_control import (
    AiRuntimeControlError,
    AiRuntimeController,
    AiRuntimePermit,
    RuntimeOutcome,
)
from app.ai.routing import P0RateLimitPool
from app.repositories.ai_call_audit import AiCallAuditLimitsV2
from app.services.ai_call_audit import TransactionalAiCallCompletionWriter
from app.services.ai_call_event_sink import (
    AiCallAuditWriter,
    AiCallReserveContext,
    DurableAiCallEventSink,
)

_SAFE_ERROR_BY_CATEGORY = {
    ExternalErrorCategory.CONNECTION_ERROR: "EMBEDDING_CONNECTION_ERROR",
    ExternalErrorCategory.CONNECT_TIMEOUT: "EMBEDDING_CONNECT_TIMEOUT",
    ExternalErrorCategory.READ_TIMEOUT: "EMBEDDING_READ_TIMEOUT",
    ExternalErrorCategory.RATE_LIMITED: "EMBEDDING_RATE_LIMITED",
    ExternalErrorCategory.SERVER_ERROR: "EMBEDDING_PROVIDER_SERVER_ERROR",
    ExternalErrorCategory.CLIENT_ERROR: "EMBEDDING_PROVIDER_CLIENT_ERROR",
    ExternalErrorCategory.CONTEXT_LIMIT: "EMBEDDING_CONTEXT_LIMIT",
    ExternalErrorCategory.INVALID_RESPONSE: "EMBEDDING_INVALID_RESPONSE",
    ExternalErrorCategory.CONTENT_REJECTED: "EMBEDDING_CONTENT_REJECTED",
    ExternalErrorCategory.PROVIDER_CONFIGURATION_ERROR: ("EMBEDDING_PROVIDER_CONFIGURATION_ERROR"),
    ExternalErrorCategory.OUTPUT_TRUNCATED: "EMBEDDING_OUTPUT_TRUNCATED",
}


class EmbeddingInvocationError(RuntimeError):
    """不携带输入文本、Provider 响应或底层异常的固定失败。"""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class EmbeddingCallIdentity:
    organization_id: UUID
    business_operation_id: UUID
    job_id: UUID | None
    request_id: UUID | None
    resource_type: str | None
    resource_id: UUID | None
    trace_id: UUID
    logical_generation_no: int = 1
    provider_attempt_no: int = 1
    event_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class _EmbeddingCompletionFacts:
    output_hash: str
    input_tokens: int
    vector_count: int
    duration_ms: int
    actual_cost_microunits: int


@dataclass(slots=True)
class AuditedEmbeddingAdoption:
    """把真实向量的 completion 与调用方业务事实放入同一 PostgreSQL 事务。"""

    _sink: DurableAiCallEventSink
    _scope: CallScopeToken
    _success_event: SinkEvent
    _facts: _EmbeddingCompletionFacts
    _identity: EmbeddingCallIdentity
    _policy_snapshot: ValidatedPolicySnapshot
    _used: bool = False

    def adopt_in_transaction(self, session: Session) -> None:
        if self._used:
            raise EmbeddingInvocationError("EMBEDDING_ADOPTION_ALREADY_USED", retryable=False)
        decision = self._sink.complete_attempt_in_transaction_sync(
            self._success_event,
            self._scope,
            TransactionalAiCallCompletionWriter(session),
        )
        if decision.status is not CompleteAttemptStatus.COMPLETED_NEW or decision.permit is None:
            raise EmbeddingInvocationError(
                "EMBEDDING_AUDIT_ADOPTION_UNAVAILABLE",
                retryable=True,
            )
        decision.permit.consume()
        self._used = True

    def reject_in_transaction(self, session: Session, *, safe_error_code: str) -> None:
        if self._used:
            raise EmbeddingInvocationError("EMBEDDING_ADOPTION_ALREADY_USED", retryable=False)
        rejected = _completed_event(
            identity=self._identity,
            policy_snapshot=self._policy_snapshot,
            status="rejected",
            completed_at=_utc_timestamp(),
            duration_ms=self._facts.duration_ms,
            output_hash=self._facts.output_hash,
            input_tokens=self._facts.input_tokens,
            vector_count=self._facts.vector_count,
            http_status=200,
            error_category="invalid_response",
            safe_error_code=safe_error_code,
            actual_cost_microunits=self._facts.actual_cost_microunits,
        )
        decision = self._sink.complete_attempt_in_transaction_sync(
            SinkEvent(rejected),
            self._scope,
            TransactionalAiCallCompletionWriter(session),
        )
        if decision.status is not CompleteAttemptStatus.COMPLETED_NEW:
            raise EmbeddingInvocationError(
                "EMBEDDING_AUDIT_REJECTION_UNAVAILABLE",
                retryable=True,
            )
        self._used = True


@dataclass(frozen=True, slots=True)
class AuditedEmbeddingResult:
    vectors: tuple[tuple[float, ...], ...]
    input_tokens: int
    response_body_sha256: str
    cost_currency: Literal["CNY"]
    actual_cost_microunits: int
    adoption: AuditedEmbeddingAdoption


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _event_error_category(category: ExternalErrorCategory) -> str:
    if category in {
        ExternalErrorCategory.CONNECTION_ERROR,
        ExternalErrorCategory.CONNECT_TIMEOUT,
        ExternalErrorCategory.READ_TIMEOUT,
    }:
        return "transient"
    return str(category.value)


def _started_event(
    *,
    event_id: UUID,
    identity: EmbeddingCallIdentity,
    policy_snapshot: ValidatedPolicySnapshot,
    policy: LiveEmbeddingPolicy,
    input_hash: str,
    reserved_input_tokens: int,
    reserved_cost_microunits: int,
    started_at: str,
    breaker_state: Literal["closed", "half_open"] | None,
) -> AiCallStartedV2:
    event = validate_ai_call_event_v2(
        {
            "event_id": str(event_id),
            "event_version": 2,
            "event_sequence": 1,
            "event_type": "ai.call.started",
            "aggregate_type": "ai_call",
            "aggregate_id": str(event_id),
            "organization_id": str(identity.organization_id),
            "business_operation_id": str(identity.business_operation_id),
            "job_id": None if identity.job_id is None else str(identity.job_id),
            "request_id": None if identity.request_id is None else str(identity.request_id),
            "resource_type": identity.resource_type,
            "resource_id": None if identity.resource_id is None else str(identity.resource_id),
            "trace_id": str(identity.trace_id),
            "call_type": "embedding",
            "logical_generation_no": identity.logical_generation_no,
            "provider_attempt_no": identity.provider_attempt_no,
            "adapter_id": "openai_embeddings_v1",
            "endpoint_id": policy.endpoint_id,
            "model_id": policy.model_id,
            "model_version": None,
            "prompt_id": None,
            "prompt_version": None,
            "prompt_hash": None,
            "schema_version": None,
            "policy_version": policy_snapshot.policy_version,
            "policy_hash": policy_snapshot.policy_hash,
            "pricing_version": policy.pricing_version,
            "input_hash": input_hash,
            "reserved_input_tokens": reserved_input_tokens,
            "reserved_output_tokens": 0,
            "cost_currency": "CNY",
            "reserved_cost_microunits": reserved_cost_microunits,
            "attempt_count": identity.provider_attempt_no,
            "is_fallback": False,
            "breaker_state": breaker_state,
            "status": "pending",
            "started_at": started_at,
        }
    )
    if not isinstance(event, AiCallStartedV2):
        raise EmbeddingInvocationError("EMBEDDING_EVENT_BUILD_FAILED", retryable=False)
    return event


def _completed_event(
    *,
    identity: EmbeddingCallIdentity,
    policy_snapshot: ValidatedPolicySnapshot,
    status: str,
    completed_at: str,
    duration_ms: int,
    output_hash: str | None,
    input_tokens: int | None,
    vector_count: int | None,
    http_status: int | None,
    error_category: str | None,
    safe_error_code: str | None,
    actual_cost_microunits: int | None = None,
) -> AiCallCompletedV2:
    if identity.event_id is None:
        raise EmbeddingInvocationError("EMBEDDING_EVENT_BUILD_FAILED", retryable=False)
    event = validate_ai_call_event_v2(
        {
            "event_id": str(identity.event_id),
            "event_version": 2,
            "event_sequence": 2,
            "event_type": "ai.call.completed",
            "aggregate_type": "ai_call",
            "aggregate_id": str(identity.event_id),
            "organization_id": str(identity.organization_id),
            "business_operation_id": str(identity.business_operation_id),
            "job_id": None if identity.job_id is None else str(identity.job_id),
            "request_id": None if identity.request_id is None else str(identity.request_id),
            "trace_id": str(identity.trace_id),
            "policy_version": policy_snapshot.policy_version,
            "policy_hash": policy_snapshot.policy_hash,
            "cost_currency": "CNY",
            "actual_cost_microunits": actual_cost_microunits,
            "status": status,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "output_hash": output_hash,
            "input_tokens": input_tokens,
            "output_tokens": 0 if input_tokens is not None else None,
            "vector_count": vector_count,
            "http_status": http_status,
            "error_category": error_category,
            "safe_error_code": safe_error_code,
            "citation_validation_status": None,
        }
    )
    if not isinstance(event, AiCallCompletedV2):
        raise EmbeddingInvocationError("EMBEDDING_EVENT_BUILD_FAILED", retryable=False)
    return event


@dataclass(frozen=True, slots=True)
class EmbeddingRuntime:
    gateway: AiGateway
    target: ModelTarget
    transport_policy: TransportPolicy
    runtime_control: AiRuntimeController | None = None
    policy_snapshot: ValidatedPolicySnapshot | None = None
    embedding_policy: LiveEmbeddingPolicy | None = None
    audit_writer: AiCallAuditWriter | None = None
    monotonic_clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        audit_values = (self.policy_snapshot, self.embedding_policy, self.audit_writer)
        if any(value is not None for value in audit_values) and not all(
            value is not None for value in audit_values
        ):
            raise ValueError("embedding audit configuration must be complete")
        if self.policy_snapshot is not None:
            if (
                not self.policy_snapshot.provider_calls_enabled
                or self.policy_snapshot.policy_version != 2
            ):
                raise ValueError("provider Policy v2 snapshot is not enabled")
            if self.embedding_policy is None or self.embedding_policy.cost_currency != "CNY":
                raise ValueError("embedding cost currency must be CNY")

    @property
    def requires_audit(self) -> bool:
        return self.audit_writer is not None

    def embed_texts(
        self,
        *,
        trace_id: str,
        input_texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        """仅供离线确定性运行时；真实 Provider 必须使用显式审计采用接口。"""

        if self.requires_audit:
            raise EmbeddingInvocationError("EMBEDDING_AUDIT_IDENTITY_REQUIRED", retryable=False)
        request = EmbeddingRequest(trace_id=trace_id, input_texts=input_texts)
        permit = self._acquire_runtime_permit(request, lease_seconds=None)
        try:
            outcome = self.gateway.embed(request, self.target, self.transport_policy)
        except AdapterNotRegisteredError:
            self._finish_runtime_permit_or_raise(permit, "neutral")
            raise EmbeddingInvocationError(
                "EMBEDDING_ADAPTER_NOT_REGISTERED",
                retryable=False,
            ) from None
        except GatewayAdapterError:
            self._finish_runtime_permit_or_raise(permit, "transient_failure")
            raise EmbeddingInvocationError("EMBEDDING_ADAPTER_ERROR", retryable=False) from None
        except GatewayContractError:
            self._finish_runtime_permit_or_raise(permit, "neutral")
            raise EmbeddingInvocationError("EMBEDDING_ADAPTER_ERROR", retryable=False) from None
        if isinstance(outcome, ExternalError):
            self._finish_runtime_permit_or_raise(
                permit,
                (
                    "transient_failure"
                    if outcome.disposition is ErrorDisposition.TRANSIENT
                    else "neutral"
                ),
            )
            raise EmbeddingInvocationError(
                _SAFE_ERROR_BY_CATEGORY[outcome.category],
                retryable=outcome.disposition is ErrorDisposition.TRANSIENT,
            )
        if not isinstance(outcome, EmbeddingResult):  # pragma: no cover - Gateway guard
            self._finish_runtime_permit_or_raise(permit, "neutral")
            raise EmbeddingInvocationError("EMBEDDING_ADAPTER_ERROR", retryable=False)
        self._finish_runtime_permit_or_raise(permit, "success")
        return outcome.vectors

    def embed_texts_audited(
        self,
        *,
        trace_id: str,
        input_texts: tuple[str, ...],
        identity: EmbeddingCallIdentity,
        deadline_monotonic: float,
    ) -> AuditedEmbeddingResult:
        policy_snapshot = self.policy_snapshot
        policy = self.embedding_policy
        audit_writer = self.audit_writer
        if policy_snapshot is None or policy is None or audit_writer is None:
            raise EmbeddingInvocationError("EMBEDDING_AUDIT_NOT_CONFIGURED", retryable=False)
        if str(identity.trace_id) != trace_id:
            raise EmbeddingInvocationError("EMBEDDING_TRACE_ID_MISMATCH", retryable=False)
        request = EmbeddingRequest(trace_id=trace_id, input_texts=input_texts)
        if len(request.input_texts) > policy.operation.max_batch_size:
            raise EmbeddingInvocationError("EMBEDDING_BATCH_LIMIT_EXCEEDED", retryable=False)
        token_upper_bounds = tuple(len(value.encode("utf-8")) for value in request.input_texts)
        if any(value > policy.operation.max_input_tokens_per_text for value in token_upper_bounds):
            raise EmbeddingInvocationError("EMBEDDING_INPUT_LIMIT_EXCEEDED", retryable=False)
        input_token_upper_bound = sum(token_upper_bounds)
        pricing = PricingProfileV2(
            pricing_version=policy.pricing_version,
            billing_mode=BillingMode.EXTERNAL_CNY,
            cost_currency=CostCurrency.CNY,
            input_price_microunits_per_million=policy.input_price_microunits_per_million,
            output_price_microunits_per_million=policy.output_price_microunits_per_million,
        )
        budget = BudgetProfileV2(
            max_provider_attempts_per_business_operation=(
                policy.operation.max_provider_attempts_per_business_operation
            ),
            max_input_tokens_per_request=policy.operation.max_total_tokens,
            max_output_tokens_per_request=0,
            max_total_tokens=policy.operation.max_total_tokens,
            cost_currency=CostCurrency.CNY,
            max_cost_microunits=policy.operation.max_cost_microunits,
        )
        try:
            reservation = calculate_preflight_reservation_v2(
                budget,
                pricing,
                provider_attempts_used=identity.provider_attempt_no - 1,
                future_model_repair_slots=0,
                reserved_total_tokens=0,
                reserved_cost_microunits=0,
                input_tokens=input_token_upper_bound,
                max_output_tokens=0,
                context_window_tokens=policy.operation.max_total_tokens,
            )
        except ValueError:
            raise EmbeddingInvocationError(
                "EMBEDDING_BUDGET_PREFLIGHT_REJECTED",
                retryable=False,
            ) from None

        remaining = deadline_monotonic - self.monotonic_clock()
        if remaining <= 1.0:
            raise EmbeddingInvocationError("EMBEDDING_DEADLINE_EXHAUSTED", retryable=True)
        permit = self._acquire_runtime_permit(request, lease_seconds=remaining)
        event_id = uuid4()
        identity = replace(identity, event_id=event_id)
        input_hash = hashlib.sha256(
            canonicalize_jcs(
                {
                    "dimensions": policy.embedding_dimension,
                    "input": list(request.input_texts),
                    "model": self.target.model_id,
                }
            )
        ).hexdigest()
        started = _started_event(
            event_id=event_id,
            identity=identity,
            policy_snapshot=policy_snapshot,
            policy=policy,
            input_hash=input_hash,
            reserved_input_tokens=reservation.reserved_input_tokens,
            reserved_cost_microunits=reservation.reserved_cost_microunits,
            started_at=_utc_timestamp(),
            breaker_state=None if permit is None else permit.breaker_state,
        )
        limits = AiCallAuditLimitsV2(
            max_provider_attempts_per_business_operation=(
                policy.operation.max_provider_attempts_per_business_operation
            ),
            max_input_tokens_per_request=policy.operation.max_total_tokens,
            max_output_tokens_per_request=0,
            max_total_tokens=policy.operation.max_total_tokens,
            cost_currency="CNY",
            max_cost_microunits=policy.operation.max_cost_microunits,
        )
        sink = DurableAiCallEventSink(
            audit_writer,
            reserve_context_factory=lambda _event: AiCallReserveContext(
                limits=limits,
                deadline_monotonic=deadline_monotonic,
                minimum_attempt_seconds=1.0,
            ),
        )
        started_sink_event = SinkEvent(started)
        scope = sink.create_call_scope(started_sink_event)
        try:
            reserve_decision = sink.reserve_attempt_sync(started_sink_event, scope)
            if reserve_decision.status is ReserveAttemptStatus.UNKNOWN:
                reserve_decision = sink.reserve_attempt_sync(started_sink_event, scope)
            if reserve_decision.permit is None or reserve_decision.status not in {
                ReserveAttemptStatus.RESERVED_NEW,
                ReserveAttemptStatus.REPLAYED_SAME,
            }:
                raise EmbeddingInvocationError(
                    "EMBEDDING_AUDIT_RESERVATION_UNAVAILABLE",
                    retryable=True,
                )
            remaining = deadline_monotonic - self.monotonic_clock()
            if remaining <= 1.0:
                raise EmbeddingInvocationError("EMBEDDING_DEADLINE_EXHAUSTED", retryable=True)
            reserve_decision.permit.consume()
        except Exception:
            self._finish_runtime_permit(permit, "neutral")
            raise

        call_started = self.monotonic_clock()
        try:
            outcome = self.gateway.embed(
                request,
                self.target,
                TransportPolicy(
                    connect_timeout_seconds=min(
                        self.transport_policy.connect_timeout_seconds,
                        remaining,
                    ),
                    read_timeout_seconds=remaining,
                    total_timeout_seconds=remaining,
                    max_attempts=1,
                ),
            )
        except (AdapterNotRegisteredError, GatewayAdapterError, GatewayContractError) as error:
            self._finish_runtime_permit(
                permit,
                "transient_failure" if isinstance(error, GatewayAdapterError) else "neutral",
            )
            completed = _completed_event(
                identity=identity,
                policy_snapshot=policy_snapshot,
                status="failed",
                completed_at=_utc_timestamp(),
                duration_ms=max(0, int((self.monotonic_clock() - call_started) * 1_000)),
                output_hash=None,
                input_tokens=None,
                vector_count=None,
                http_status=None,
                error_category="provider_configuration_error",
                safe_error_code="EMBEDDING_GATEWAY_FAILURE",
            )
            self._complete_without_adoption(sink, scope, completed)
            raise EmbeddingInvocationError("EMBEDDING_GATEWAY_FAILURE", retryable=True) from None

        duration_ms = max(0, int((self.monotonic_clock() - call_started) * 1_000))
        completed_at = _utc_timestamp()
        if isinstance(outcome, ExternalError):
            self._finish_runtime_permit(
                permit,
                (
                    "transient_failure"
                    if outcome.disposition is ErrorDisposition.TRANSIENT
                    else "neutral"
                ),
            )
            completed = _completed_event(
                identity=identity,
                policy_snapshot=policy_snapshot,
                status="failed",
                completed_at=completed_at,
                duration_ms=duration_ms,
                output_hash=None,
                input_tokens=None,
                vector_count=None,
                http_status=outcome.status_code,
                error_category=_event_error_category(outcome.category),
                safe_error_code=_SAFE_ERROR_BY_CATEGORY[outcome.category],
            )
            self._complete_without_adoption(sink, scope, completed)
            raise EmbeddingInvocationError(
                _SAFE_ERROR_BY_CATEGORY[outcome.category],
                retryable=outcome.disposition is ErrorDisposition.TRANSIENT,
            )

        assert isinstance(outcome, EmbeddingResult)
        if outcome.input_tokens is None or outcome.response_body_sha256 is None:
            self._finish_runtime_permit(permit, "neutral")
            completed = _completed_event(
                identity=identity,
                policy_snapshot=policy_snapshot,
                status="failed",
                completed_at=completed_at,
                duration_ms=duration_ms,
                output_hash=outcome.response_body_sha256,
                input_tokens=outcome.input_tokens,
                vector_count=len(outcome.vectors),
                http_status=200,
                error_category="invalid_response",
                safe_error_code="EMBEDDING_USAGE_UNAVAILABLE",
            )
            self._complete_without_adoption(sink, scope, completed)
            raise EmbeddingInvocationError("EMBEDDING_USAGE_UNAVAILABLE", retryable=False)

        reported_cost = pricing.calculate_request_cost_microunits(
            input_tokens=outcome.input_tokens,
            output_tokens=0,
        )
        try:
            reconciled = reconcile_actual_usage_v2(
                pricing,
                reservation,
                input_tokens=outcome.input_tokens,
                output_tokens=0,
                total_tokens=outcome.input_tokens,
            )
        except ValueError:
            self._finish_runtime_permit(permit, "neutral")
            completed = _completed_event(
                identity=identity,
                policy_snapshot=policy_snapshot,
                status="rejected",
                completed_at=completed_at,
                duration_ms=duration_ms,
                output_hash=outcome.response_body_sha256,
                input_tokens=outcome.input_tokens,
                vector_count=len(outcome.vectors),
                http_status=200,
                error_category="invalid_response",
                safe_error_code="EMBEDDING_USAGE_EXCEEDS_RESERVATION",
                actual_cost_microunits=reported_cost,
            )
            self._complete_without_adoption(sink, scope, completed)
            raise EmbeddingInvocationError(
                "EMBEDDING_USAGE_EXCEEDS_RESERVATION",
                retryable=False,
            ) from None

        if not self._finish_runtime_permit(permit, "success"):
            completed = _completed_event(
                identity=identity,
                policy_snapshot=policy_snapshot,
                status="failed",
                completed_at=completed_at,
                duration_ms=duration_ms,
                output_hash=outcome.response_body_sha256,
                input_tokens=outcome.input_tokens,
                vector_count=len(outcome.vectors),
                http_status=200,
                error_category="transient",
                safe_error_code="AI_RUNTIME_CONTROL_UNAVAILABLE",
                actual_cost_microunits=reconciled.actual_cost_microunits,
            )
            self._complete_without_adoption(sink, scope, completed)
            raise EmbeddingInvocationError("AI_RUNTIME_CONTROL_UNAVAILABLE", retryable=True)

        success = _completed_event(
            identity=identity,
            policy_snapshot=policy_snapshot,
            status="succeeded",
            completed_at=completed_at,
            duration_ms=duration_ms,
            output_hash=outcome.response_body_sha256,
            input_tokens=outcome.input_tokens,
            vector_count=len(outcome.vectors),
            http_status=200,
            error_category=None,
            safe_error_code=None,
            actual_cost_microunits=reconciled.actual_cost_microunits,
        )
        facts = _EmbeddingCompletionFacts(
            output_hash=outcome.response_body_sha256,
            input_tokens=outcome.input_tokens,
            vector_count=len(outcome.vectors),
            duration_ms=duration_ms,
            actual_cost_microunits=reconciled.actual_cost_microunits,
        )
        return AuditedEmbeddingResult(
            vectors=outcome.vectors,
            input_tokens=outcome.input_tokens,
            response_body_sha256=outcome.response_body_sha256,
            cost_currency="CNY",
            actual_cost_microunits=reconciled.actual_cost_microunits,
            adoption=AuditedEmbeddingAdoption(
                _sink=sink,
                _scope=scope,
                _success_event=SinkEvent(success),
                _facts=facts,
                _identity=identity,
                _policy_snapshot=policy_snapshot,
            ),
        )

    def _acquire_runtime_permit(
        self,
        request: EmbeddingRequest,
        *,
        lease_seconds: float | None,
    ) -> AiRuntimePermit | None:
        if self.runtime_control is None:
            return None
        estimated_tokens = max(
            1,
            sum(len(value.encode("utf-8")) for value in request.input_texts),
        )
        try:
            return self.runtime_control.acquire(
                pool=P0RateLimitPool.EMBEDDING,
                target=self.target,
                estimated_tokens=estimated_tokens,
                lease_seconds=(
                    self.transport_policy.total_timeout_seconds
                    if lease_seconds is None
                    else lease_seconds
                ),
            )
        except AiRuntimeControlError as error:
            raise EmbeddingInvocationError(error.code, retryable=True) from None

    @staticmethod
    def _finish_runtime_permit(
        permit: AiRuntimePermit | None,
        outcome: RuntimeOutcome,
    ) -> bool:
        if permit is None:
            return True
        try:
            permit.finish(outcome)
        except AiRuntimeControlError:
            return False
        return True

    @classmethod
    def _finish_runtime_permit_or_raise(
        cls,
        permit: AiRuntimePermit | None,
        outcome: RuntimeOutcome,
    ) -> None:
        if not cls._finish_runtime_permit(permit, outcome):
            raise EmbeddingInvocationError("AI_RUNTIME_CONTROL_UNAVAILABLE", retryable=True)

    @staticmethod
    def _complete_without_adoption(
        sink: DurableAiCallEventSink,
        scope: CallScopeToken,
        completed: AiCallCompletedV2,
    ) -> None:
        event = SinkEvent(completed)
        decision = sink.complete_attempt_sync(event, scope)
        if decision.status is CompleteAttemptStatus.UNKNOWN:
            decision = sink.complete_attempt_sync(event, scope)
        if decision.status not in {
            CompleteAttemptStatus.COMPLETED_NEW,
            CompleteAttemptStatus.REPLAYED_SAME,
        }:
            raise EmbeddingInvocationError(
                "EMBEDDING_AUDIT_COMPLETION_UNAVAILABLE",
                retryable=True,
            )


def create_deterministic_embedding_runtime(
    *,
    model_id: str,
    vector_size: int,
    deadline_seconds: float,
) -> EmbeddingRuntime:
    adapter = DeterministicHashEmbeddingAdapter(model_id=model_id, vector_size=vector_size)
    return EmbeddingRuntime(
        gateway=AiGateway(
            llm_adapters={},
            embedding_adapters={adapter.target.adapter_id: adapter},
        ),
        target=adapter.target,
        transport_policy=TransportPolicy(
            connect_timeout_seconds=deadline_seconds,
            read_timeout_seconds=deadline_seconds,
            total_timeout_seconds=deadline_seconds,
            max_attempts=1,
        ),
    )


__all__ = [
    "AuditedEmbeddingAdoption",
    "AuditedEmbeddingResult",
    "EmbeddingCallIdentity",
    "EmbeddingInvocationError",
    "EmbeddingRuntime",
    "create_deterministic_embedding_runtime",
]
