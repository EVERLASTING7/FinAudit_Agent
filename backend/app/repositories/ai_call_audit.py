"""AI 调用 durable reserve、Outbox 投影与未知结果补偿。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Final, Literal, TypeAlias, cast
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ai.events import (
    AiCallCompletedV1,
    AiCallCompletedV2,
    AiCallEvent,
    AiCallEventConflictError,
    AiCallLateCompletionV1,
    AiCallLateCompletionV2,
    AiCallStartedV1,
    AiCallStartedV2,
    validate_ai_call_event,
    validate_ai_call_event_chain_any,
)
from app.models.audit import AiCallLog
from app.models.reliability import OutboxEvent

_STARTED_EVENT: Final = "ai.call.started"
_COMPLETED_EVENT: Final = "ai.call.completed"
_LATE_EVENT: Final = "ai.call.late_completion"
_AI_EVENT_TYPES: Final = (_STARTED_EVENT, _COMPLETED_EVENT, _LATE_EVENT)
_OUTCOME_UNKNOWN_GRACE_SECONDS: Final = 30
_CALL_TYPES: Final = (
    "contract_field_extraction",
    "embedding",
    "invoice_field_extraction",
    "rag_answer",
    "report_draft",
    "risk_explanation",
)
AiCallStarted: TypeAlias = AiCallStartedV1 | AiCallStartedV2
AiCallCompletion: TypeAlias = (
    AiCallCompletedV1 | AiCallCompletedV2 | AiCallLateCompletionV1 | AiCallLateCompletionV2
)


class AiCallReserveStatus(str, Enum):
    RESERVED_NEW = "reserved_new"
    REPLAYED_SAME = "replayed_same"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEADLINE_EXHAUSTED = "deadline_exhausted"


class AiCallCompleteStatus(str, Enum):
    COMPLETED_NEW = "completed_new"
    REPLAYED_SAME = "replayed_same"
    LATE_RECORDED = "late_recorded"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"
    AUDIT_UNAVAILABLE = "audit_unavailable"


class AiCallProjectionStatus(str, Enum):
    IDLE = "idle"
    PROJECTED = "projected"
    REPLAYED_SAME = "replayed_same"
    LATE_RECORDED = "late_recorded"
    DEAD_LETTER = "dead_letter"
    STALE = "stale"


class AiCallReconcileStatus(str, Enum):
    IDLE = "idle"
    OUTCOME_UNKNOWN = "outcome_unknown"
    COMPLETION_PROJECTED = "completion_projected"
    BLOCKED = "blocked"
    STALE = "stale"


def _exact_non_negative_integer(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class AiCallAuditLimits:
    max_provider_attempts_per_business_operation: int
    max_input_tokens_per_request: int
    max_output_tokens_per_request: int
    max_total_tokens: int
    max_cost_micro_usd: int

    def __post_init__(self) -> None:
        attempts = _exact_non_negative_integer(
            "max_provider_attempts_per_business_operation",
            self.max_provider_attempts_per_business_operation,
        )
        _exact_non_negative_integer(
            "max_input_tokens_per_request", self.max_input_tokens_per_request
        )
        _exact_non_negative_integer(
            "max_output_tokens_per_request", self.max_output_tokens_per_request
        )
        total_tokens = _exact_non_negative_integer("max_total_tokens", self.max_total_tokens)
        _exact_non_negative_integer("max_cost_micro_usd", self.max_cost_micro_usd)
        if attempts == 0 or total_tokens == 0:
            raise ValueError("attempt and total-token limits must be positive")


@dataclass(frozen=True, slots=True)
class AiCallAuditLimitsV2:
    max_provider_attempts_per_business_operation: int
    max_input_tokens_per_request: int
    max_output_tokens_per_request: int
    max_total_tokens: int
    cost_currency: Literal["USD", "CNY"] | None
    max_cost_microunits: int

    def __post_init__(self) -> None:
        attempts = _exact_non_negative_integer(
            "max_provider_attempts_per_business_operation",
            self.max_provider_attempts_per_business_operation,
        )
        _exact_non_negative_integer(
            "max_input_tokens_per_request", self.max_input_tokens_per_request
        )
        _exact_non_negative_integer(
            "max_output_tokens_per_request", self.max_output_tokens_per_request
        )
        total_tokens = _exact_non_negative_integer("max_total_tokens", self.max_total_tokens)
        _exact_non_negative_integer("max_cost_microunits", self.max_cost_microunits)
        if self.cost_currency not in {"USD", "CNY", None}:
            raise ValueError("cost_currency must be USD, CNY, or None")
        if self.cost_currency is None and self.max_cost_microunits != 0:
            raise ValueError("internal unmetered max cost must be zero")
        if attempts == 0 or total_tokens == 0:
            raise ValueError("attempt and total-token limits must be positive")


AiCallAuditLimit: TypeAlias = AiCallAuditLimits | AiCallAuditLimitsV2


@dataclass(frozen=True, slots=True)
class AiCallProjectionResult:
    status: AiCallProjectionStatus
    event_id: UUID | None = None
    event_type: str | None = None


@dataclass(frozen=True, slots=True)
class AiCallReconcileResult:
    status: AiCallReconcileStatus
    event_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AiCallAttemptAudit:
    event_id: UUID
    provider_attempt_no: int
    logical_generation_no: int
    model_id: str
    is_fallback: bool
    status: str
    reserved_input_tokens: int
    reserved_output_tokens: int
    reserved_cost_micro_usd: int | None
    input_tokens: int | None
    output_tokens: int | None
    trace_id: UUID
    started_at: datetime
    completed_at: datetime | None
    safe_error_code: str | None
    event_version: int = 1
    cost_currency: Literal["USD", "CNY"] | None = None
    reserved_cost_microunits: int | None = None
    actual_cost_microunits: int | None = None


@dataclass(frozen=True, slots=True)
class AiCallOperationAuditSummary:
    organization_id: UUID
    business_operation_id: UUID
    attempt_count: int
    reserved_input_tokens: int
    reserved_output_tokens: int
    reserved_cost_micro_usd: int | None
    actual_input_tokens: int
    actual_output_tokens: int
    attempts: tuple[AiCallAttemptAudit, ...]
    cost_currency: Literal["USD", "CNY"] | None = None
    reserved_cost_microunits: int | None = None
    actual_cost_microunits: int | None = None


@dataclass(frozen=True, slots=True)
class _ClaimedAiEvent:
    outbox_id: UUID
    event_id: UUID
    event_type: str
    event_version: int
    event_sequence: int
    aggregate_type: str
    aggregate_id: UUID
    payload_json: dict[str, object]
    attempt_count: int
    trace_id: UUID


def _strict_event_payload(
    event: AiCallEvent,
) -> dict[str, object]:
    value = json.loads(event.canonical_payload())
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise TypeError("AI_CALL_EVENT_PAYLOAD_INVALID")
    return cast(dict[str, object], value)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    if parsed.tzinfo is None:
        raise ValueError("AI_CALL_EVENT_TIMESTAMP_INVALID")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_deadline(
    *,
    deadline_monotonic: float,
    minimum_attempt_seconds: float,
    monotonic: Callable[[], float],
) -> bool:
    for name, value in (
        ("deadline_monotonic", deadline_monotonic),
        ("minimum_attempt_seconds", minimum_attempt_seconds),
    ):
        if type(value) not in {int, float} or not isfinite(value):
            raise ValueError(f"{name} must be finite")
    if minimum_attempt_seconds < 0:
        raise ValueError("minimum_attempt_seconds must be non-negative")
    current = monotonic()
    if type(current) not in {int, float} or not isfinite(current):
        raise ValueError("monotonic clock must return a finite number")
    return float(current) + float(minimum_attempt_seconds) < float(deadline_monotonic)


class AiCallAuditRepository:
    """调用方负责事务；complete 可与业务结果在同一事务提交。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def reserve_attempt(
        self,
        event: AiCallStarted,
        limits: AiCallAuditLimit,
        *,
        deadline_monotonic: float,
        monotonic: Callable[[], float],
        minimum_attempt_seconds: float = 0.0,
    ) -> AiCallReserveStatus:
        event = self._validated_started(event)
        if isinstance(event, AiCallStartedV1) != isinstance(limits, AiCallAuditLimits):
            raise TypeError("event and audit limits versions must match")
        payload = _strict_event_payload(event)
        event_id = UUID(event.event_id)

        self._lock_event(event_id)
        self._lock_operation(event)
        existing = self._event_row(event_id, _STARTED_EVENT, lock=True)
        if existing is not None:
            if self._outbox_matches(existing, event, payload):
                if existing.status == "dead_letter":
                    return AiCallReserveStatus.UNKNOWN
                return AiCallReserveStatus.REPLAYED_SAME
            return AiCallReserveStatus.CONFLICT

        if not _validate_deadline(
            deadline_monotonic=deadline_monotonic,
            minimum_attempt_seconds=minimum_attempt_seconds,
            monotonic=monotonic,
        ):
            return AiCallReserveStatus.DEADLINE_EXHAUSTED

        committed = self._operation_started_events(event)
        provider_attempt_numbers: set[int] = set()
        reserved_total_tokens = 0
        reserved_cost = 0
        for committed_event, status in committed:
            if status == "dead_letter":
                return AiCallReserveStatus.UNKNOWN
            if (
                committed_event.call_type != event.call_type
                or committed_event.event_version != event.event_version
            ):
                return AiCallReserveStatus.CONFLICT
            provider_attempt_numbers.add(committed_event.provider_attempt_no)
            reserved_total_tokens += (
                committed_event.reserved_input_tokens + committed_event.reserved_output_tokens
            )
            if isinstance(event, AiCallStartedV1):
                if not isinstance(committed_event, AiCallStartedV1):
                    return AiCallReserveStatus.CONFLICT
                reserved_cost += committed_event.reserved_cost_micro_usd
            else:
                if (
                    not isinstance(committed_event, AiCallStartedV2)
                    or committed_event.cost_currency != event.cost_currency
                ):
                    return AiCallReserveStatus.CONFLICT
                reserved_cost += committed_event.reserved_cost_microunits

        if event.provider_attempt_no in provider_attempt_numbers:
            return AiCallReserveStatus.CONFLICT
        cost_exceeded = (
            reserved_cost + event.reserved_cost_micro_usd > limits.max_cost_micro_usd
            if isinstance(event, AiCallStartedV1) and isinstance(limits, AiCallAuditLimits)
            else isinstance(event, AiCallStartedV2)
            and isinstance(limits, AiCallAuditLimitsV2)
            and (
                event.cost_currency != limits.cost_currency
                or reserved_cost + event.reserved_cost_microunits > limits.max_cost_microunits
            )
        )
        if (
            len(committed) + 1 > limits.max_provider_attempts_per_business_operation
            or event.reserved_input_tokens > limits.max_input_tokens_per_request
            or event.reserved_output_tokens > limits.max_output_tokens_per_request
            or reserved_total_tokens + event.reserved_input_tokens + event.reserved_output_tokens
            > limits.max_total_tokens
            or cost_exceeded
        ):
            return AiCallReserveStatus.BUDGET_EXHAUSTED

        self._add_outbox(event, payload)
        self._session.flush()
        return AiCallReserveStatus.RESERVED_NEW

    def append_completion(
        self,
        event: AiCallCompletion,
    ) -> AiCallCompleteStatus:
        event = self._validated_completion(event)
        payload = _strict_event_payload(event)
        event_id = UUID(event.event_id)
        self._lock_event(event_id)

        existing = self._event_row(event_id, event.event_type, lock=True)
        if existing is not None:
            if not self._outbox_matches(existing, event, payload):
                return AiCallCompleteStatus.CONFLICT
            if existing.status == "dead_letter":
                return AiCallCompleteStatus.AUDIT_UNAVAILABLE
            if isinstance(event, (AiCallLateCompletionV1, AiCallLateCompletionV2)):
                return AiCallCompleteStatus.LATE_RECORDED
            return AiCallCompleteStatus.REPLAYED_SAME

        started_row = self._event_row(event_id, _STARTED_EVENT, lock=True)
        if started_row is None or started_row.status == "dead_letter":
            return AiCallCompleteStatus.UNKNOWN
        started = self._event_from_payload(started_row.payload_json)
        if not isinstance(started, (AiCallStartedV1, AiCallStartedV2)):
            return AiCallCompleteStatus.CONFLICT

        try:
            if isinstance(event, (AiCallCompletedV1, AiCallCompletedV2)):
                current_log = self._session.execute(
                    select(AiCallLog).where(AiCallLog.id == event_id)
                ).scalar_one_or_none()
                if current_log is not None and current_log.status == "outcome_unknown":
                    return AiCallCompleteStatus.CONFLICT
                validate_ai_call_event_chain_any(started, event)
            else:
                completed_row = self._event_row(event_id, _COMPLETED_EVENT, lock=True)
                if completed_row is None or completed_row.status != "published":
                    return AiCallCompleteStatus.UNKNOWN
                completed = self._event_from_payload(completed_row.payload_json)
                if not isinstance(completed, (AiCallCompletedV1, AiCallCompletedV2)):
                    return AiCallCompleteStatus.CONFLICT
                validate_ai_call_event_chain_any(started, completed, event)
                current_log = self._session.execute(
                    select(AiCallLog).where(AiCallLog.id == event_id)
                ).scalar_one_or_none()
                if current_log is None or current_log.status != "outcome_unknown":
                    return AiCallCompleteStatus.CONFLICT
        except AiCallEventConflictError:
            return AiCallCompleteStatus.CONFLICT

        self._add_outbox(event, payload)
        self._session.flush()
        if isinstance(event, (AiCallLateCompletionV1, AiCallLateCompletionV2)):
            return AiCallCompleteStatus.LATE_RECORDED
        return AiCallCompleteStatus.COMPLETED_NEW

    def project_next(self) -> AiCallProjectionResult:
        candidate = (
            self._session.execute(
                text(
                    """
                SELECT event.id, event.event_id
                  FROM public.outbox_events AS event
                 WHERE event.aggregate_type='ai_call'
                   AND (
                        event.status='pending'
                        OR (event.status='failed' AND event.next_attempt_at<=clock_timestamp())
                   )
                   AND (
                        event.event_type NOT IN ('ai.call.completed','ai.call.late_completion')
                        OR (event.event_type='ai.call.completed' AND (
                            event.event_sequence<>2 OR EXISTS (
                                SELECT 1 FROM public.outbox_events AS prior
                                 WHERE prior.aggregate_type='ai_call'
                                   AND prior.aggregate_id=event.aggregate_id
                                   AND prior.event_type='ai.call.started'
                                   AND prior.status IN ('published','dead_letter')
                            )
                        ))
                        OR (event.event_type='ai.call.late_completion' AND (
                            event.event_sequence<>3 OR EXISTS (
                                SELECT 1 FROM public.outbox_events AS prior
                                 WHERE prior.aggregate_type='ai_call'
                                   AND prior.aggregate_id=event.aggregate_id
                                   AND prior.event_type='ai.call.completed'
                                   AND prior.status IN ('published','dead_letter')
                            )
                        ))
                   )
                 ORDER BY event.created_at ASC, event.id ASC
                 LIMIT 1
                """
                )
            )
            .mappings()
            .one_or_none()
        )
        if candidate is None:
            return AiCallProjectionResult(AiCallProjectionStatus.IDLE)

        event_id = cast(UUID, candidate["event_id"])
        self._lock_event(event_id)
        claim = self._claim_specific(cast(UUID, candidate["id"]))
        if claim is None:
            return AiCallProjectionResult(AiCallProjectionStatus.STALE, event_id)
        return self._project_claim(claim)

    def reconcile_expired_once(
        self,
        deadline_seconds_by_call_type: Mapping[str, int],
    ) -> AiCallReconcileResult:
        deadlines = self._validated_deadlines(deadline_seconds_by_call_type)
        candidate = self._session.execute(
            text(
                """
                SELECT id
                  FROM public.ai_call_logs
                 WHERE status='pending'
                   AND started_at + make_interval(secs => CASE call_type
                        WHEN 'contract_field_extraction' THEN :contract_deadline
                        WHEN 'embedding' THEN :embedding_deadline
                        WHEN 'invoice_field_extraction' THEN :invoice_deadline
                        WHEN 'rag_answer' THEN :rag_deadline
                        WHEN 'report_draft' THEN :report_deadline
                        WHEN 'risk_explanation' THEN :risk_deadline
                        ELSE 2147483647
                   END) + interval '30 seconds' <= clock_timestamp()
                 ORDER BY started_at ASC, id ASC
                 LIMIT 1
                """
            ),
            {
                "contract_deadline": deadlines["contract_field_extraction"],
                "embedding_deadline": deadlines["embedding"],
                "invoice_deadline": deadlines["invoice_field_extraction"],
                "rag_deadline": deadlines["rag_answer"],
                "report_deadline": deadlines["report_draft"],
                "risk_deadline": deadlines["risk_explanation"],
            },
        ).scalar_one_or_none()
        if candidate is None:
            return AiCallReconcileResult(AiCallReconcileStatus.IDLE)

        event_id = cast(UUID, candidate)
        self._lock_event(event_id)
        completed_row = self._event_row(event_id, _COMPLETED_EVENT, lock=True)
        if completed_row is not None:
            if completed_row.status == "dead_letter":
                return AiCallReconcileResult(AiCallReconcileStatus.BLOCKED, event_id)
            if completed_row.status == "published":
                log = self._session.execute(
                    select(AiCallLog).where(AiCallLog.id == event_id).with_for_update()
                ).scalar_one_or_none()
                if log is not None and log.status != "pending":
                    return AiCallReconcileResult(
                        AiCallReconcileStatus.COMPLETION_PROJECTED, event_id
                    )
                return AiCallReconcileResult(AiCallReconcileStatus.BLOCKED, event_id)
            claim = self._claim_specific(completed_row.id)
            if claim is None:
                return AiCallReconcileResult(AiCallReconcileStatus.STALE, event_id)
            projected = self._project_claim(claim)
            if projected.status in {
                AiCallProjectionStatus.PROJECTED,
                AiCallProjectionStatus.REPLAYED_SAME,
            }:
                return AiCallReconcileResult(AiCallReconcileStatus.COMPLETION_PROJECTED, event_id)
            return AiCallReconcileResult(AiCallReconcileStatus.BLOCKED, event_id)

        log = self._session.execute(
            select(AiCallLog).where(AiCallLog.id == event_id).with_for_update()
        ).scalar_one_or_none()
        if log is None or log.status != "pending":
            return AiCallReconcileResult(AiCallReconcileStatus.STALE, event_id)
        database_now = self._session.execute(text("SELECT clock_timestamp()")).scalar_one()
        if not isinstance(database_now, datetime):
            raise RuntimeError("AI_AUDIT_DATABASE_CLOCK_INVALID")
        deadline = deadlines.get(log.call_type)
        if deadline is None or (
            log.started_at.timestamp() + deadline + _OUTCOME_UNKNOWN_GRACE_SECONDS
            > database_now.timestamp()
        ):
            return AiCallReconcileResult(AiCallReconcileStatus.STALE, event_id)

        started_row = self._event_row(event_id, _STARTED_EVENT, lock=True)
        if started_row is None or started_row.status != "published":
            return AiCallReconcileResult(AiCallReconcileStatus.BLOCKED, event_id)
        started = self._event_from_payload(started_row.payload_json)
        if not isinstance(started, (AiCallStartedV1, AiCallStartedV2)):
            return AiCallReconcileResult(AiCallReconcileStatus.BLOCKED, event_id)
        duration_ms = max(0, int((database_now - log.started_at).total_seconds() * 1_000))
        outcome_payload: dict[str, object] = {
            "event_id": started.event_id,
            "event_version": started.event_version,
            "event_sequence": 2,
            "event_type": _COMPLETED_EVENT,
            "aggregate_type": "ai_call",
            "aggregate_id": started.event_id,
            "organization_id": started.organization_id,
            "business_operation_id": started.business_operation_id,
            "job_id": started.job_id,
            "request_id": started.request_id,
            "trace_id": started.trace_id,
            "policy_version": started.policy_version,
            "policy_hash": started.policy_hash,
            "status": "outcome_unknown",
            "completed_at": _format_timestamp(database_now),
            "duration_ms": duration_ms,
            "output_hash": None,
            "input_tokens": None,
            "output_tokens": None,
            "vector_count": None,
            "http_status": None,
            "error_category": None,
            "safe_error_code": "AI_OUTCOME_UNKNOWN",
            "citation_validation_status": None,
        }
        if isinstance(started, AiCallStartedV2):
            outcome_payload.update(
                cost_currency=started.cost_currency,
                actual_cost_microunits=None,
            )
        outcome_event = validate_ai_call_event(outcome_payload)
        if not isinstance(outcome_event, (AiCallCompletedV1, AiCallCompletedV2)):
            raise RuntimeError("AI_OUTCOME_UNKNOWN_EVENT_INVALID")
        outbox = self._add_outbox(outcome_event, _strict_event_payload(outcome_event))
        self._session.flush()
        claim = self._claim_specific(outbox.id)
        if claim is None:
            raise RuntimeError("AI_OUTCOME_UNKNOWN_CLAIM_FAILED")
        projected = self._project_claim(claim)
        if projected.status is not AiCallProjectionStatus.PROJECTED:
            raise RuntimeError("AI_OUTCOME_UNKNOWN_PROJECTION_FAILED")
        return AiCallReconcileResult(AiCallReconcileStatus.OUTCOME_UNKNOWN, event_id)

    def get_operation_summary(
        self,
        organization_id: UUID,
        business_operation_id: UUID,
    ) -> AiCallOperationAuditSummary | None:
        rows = tuple(
            self._session.execute(
                select(AiCallLog)
                .where(
                    AiCallLog.organization_id == organization_id,
                    AiCallLog.business_operation_id == business_operation_id,
                )
                .order_by(AiCallLog.provider_attempt_no.asc(), AiCallLog.id.asc())
            ).scalars()
        )
        if not rows:
            return None
        attempts = tuple(
            AiCallAttemptAudit(
                event_id=row.id,
                provider_attempt_no=row.provider_attempt_no,
                logical_generation_no=row.logical_generation_no,
                model_id=row.model_id,
                is_fallback=row.is_fallback,
                status=row.status,
                reserved_input_tokens=row.reserved_input_tokens,
                reserved_output_tokens=row.reserved_output_tokens,
                reserved_cost_micro_usd=row.reserved_cost_micro_usd,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                trace_id=row.trace_id,
                started_at=row.started_at,
                completed_at=row.completed_at,
                safe_error_code=row.safe_error_code,
                event_version=row.event_version,
                cost_currency=cast(Literal["USD", "CNY"] | None, row.cost_currency),
                reserved_cost_microunits=row.reserved_cost_microunits,
                actual_cost_microunits=row.actual_cost_microunits,
            )
            for row in rows
        )
        all_v1 = all(item.event_version == 1 for item in attempts)
        all_v2 = all(item.event_version == 2 for item in attempts)
        currencies = {item.cost_currency for item in attempts if item.event_version == 2}
        currency = next(iter(currencies)) if all_v2 and len(currencies) == 1 else None
        actual_costs_authoritative = all(
            item.actual_cost_microunits is not None for item in attempts
        )
        return AiCallOperationAuditSummary(
            organization_id=organization_id,
            business_operation_id=business_operation_id,
            attempt_count=len(attempts),
            reserved_input_tokens=sum(item.reserved_input_tokens for item in attempts),
            reserved_output_tokens=sum(item.reserved_output_tokens for item in attempts),
            reserved_cost_micro_usd=(
                sum(cast(int, item.reserved_cost_micro_usd) for item in attempts)
                if all_v1
                else None
            ),
            actual_input_tokens=sum(item.input_tokens or 0 for item in attempts),
            actual_output_tokens=sum(item.output_tokens or 0 for item in attempts),
            attempts=attempts,
            cost_currency=currency,
            reserved_cost_microunits=(
                sum(cast(int, item.reserved_cost_microunits) for item in attempts)
                if all_v2 and len(currencies) == 1
                else None
            ),
            actual_cost_microunits=(
                sum(cast(int, item.actual_cost_microunits) for item in attempts)
                if all_v2 and len(currencies) == 1 and actual_costs_authoritative
                else None
            ),
        )

    @staticmethod
    def _validated_started(event: AiCallStarted) -> AiCallStarted:
        validated = validate_ai_call_event(event)
        if not isinstance(validated, (AiCallStartedV1, AiCallStartedV2)):
            raise TypeError("reserve_attempt requires a started event")
        return validated

    @staticmethod
    def _validated_completion(
        event: AiCallCompletion,
    ) -> AiCallCompletion:
        validated = validate_ai_call_event(event)
        if not isinstance(
            validated,
            (AiCallCompletedV1, AiCallCompletedV2, AiCallLateCompletionV1, AiCallLateCompletionV2),
        ):
            raise TypeError("append_completion requires completed or late event")
        return validated

    @staticmethod
    def _validated_deadlines(values: Mapping[str, int]) -> dict[str, int]:
        if not isinstance(values, Mapping) or set(values) != set(_CALL_TYPES):
            raise ValueError("deadline mapping must contain the six approved call types")
        deadlines: dict[str, int] = {}
        for call_type in _CALL_TYPES:
            value = values[call_type]
            if type(value) is not int or value <= 0:
                raise ValueError("deadline values must be positive integers")
            deadlines[call_type] = value
        return deadlines

    def _lock_event(self, event_id: UUID) -> None:
        self._advisory_lock(f"finaudit:ai-call:event:{event_id}")

    def _lock_operation(self, event: AiCallStarted) -> None:
        self._advisory_lock(
            "finaudit:ai-call:operation:"
            f"{event.organization_id}:{event.business_operation_id}:{event.policy_version}"
        )

    def _advisory_lock(self, key: str) -> None:
        self._session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(CAST(:lock_key AS text), CAST(0 AS bigint)))"
            ),
            {"lock_key": key},
        ).scalar_one()

    def _event_row(
        self,
        event_id: UUID,
        event_type: str,
        *,
        lock: bool,
    ) -> OutboxEvent | None:
        statement = select(OutboxEvent).where(
            OutboxEvent.event_id == event_id,
            OutboxEvent.event_type == event_type,
        )
        if lock:
            statement = statement.with_for_update(of=OutboxEvent)
        return self._session.execute(statement).scalar_one_or_none()

    def _operation_started_events(
        self,
        event: AiCallStarted,
    ) -> tuple[tuple[AiCallStarted, str], ...]:
        rows = self._session.execute(
            text(
                """
                SELECT payload_json, status
                  FROM public.outbox_events
                 WHERE aggregate_type='ai_call'
                   AND event_type='ai.call.started'
                   AND payload_json->>'organization_id'=:organization_id
                   AND payload_json->>'business_operation_id'=:business_operation_id
                   AND payload_json->>'policy_version'=:policy_version
                 ORDER BY created_at ASC, id ASC
                """
            ),
            {
                "organization_id": event.organization_id,
                "business_operation_id": event.business_operation_id,
                "policy_version": str(event.policy_version),
            },
        ).mappings()
        result: list[tuple[AiCallStarted, str]] = []
        for row in rows:
            payload = row["payload_json"]
            if type(payload) is not dict:
                raise RuntimeError("AI_AUDIT_STORED_EVENT_INVALID")
            parsed = self._event_from_payload(cast(dict[str, object], payload))
            if not isinstance(parsed, (AiCallStartedV1, AiCallStartedV2)):
                raise RuntimeError("AI_AUDIT_STORED_EVENT_INVALID")
            result.append((parsed, cast(str, row["status"])))
        return tuple(result)

    @staticmethod
    def _event_from_payload(
        payload: dict[str, object],
    ) -> AiCallEvent:
        return validate_ai_call_event(payload)

    @staticmethod
    def _outbox_matches(
        row: OutboxEvent,
        event: AiCallEvent,
        payload: dict[str, object],
    ) -> bool:
        return (
            row.aggregate_type == event.aggregate_type
            and row.aggregate_id == UUID(event.aggregate_id)
            and row.event_id == UUID(event.event_id)
            and row.event_type == event.event_type
            and row.event_version == event.event_version
            and row.event_sequence == event.event_sequence
            and row.payload_json == payload
            and row.trace_id == UUID(event.trace_id)
        )

    def _add_outbox(
        self,
        event: AiCallEvent,
        payload: dict[str, object],
    ) -> OutboxEvent:
        row = OutboxEvent(
            id=uuid4(),
            aggregate_type=event.aggregate_type,
            aggregate_id=UUID(event.aggregate_id),
            event_id=UUID(event.event_id),
            event_type=event.event_type,
            event_version=event.event_version,
            event_sequence=event.event_sequence,
            payload_json=payload,
            status="pending",
            attempt_count=0,
            next_attempt_at=None,
            published_at=None,
            last_error=None,
            trace_id=UUID(event.trace_id),
        )
        self._session.add(row)
        return row

    def _claim_specific(self, outbox_id: UUID) -> _ClaimedAiEvent | None:
        row = (
            self._session.execute(
                text(
                    """
                UPDATE public.outbox_events
                   SET status='processing'
                 WHERE id=:outbox_id
                   AND aggregate_type='ai_call'
                   AND (
                        status='pending'
                        OR (status='failed' AND next_attempt_at<=clock_timestamp())
                   )
                RETURNING id,event_id,event_type,event_version,event_sequence,
                          aggregate_type,aggregate_id,payload_json,attempt_count,trace_id
                """
                ),
                {"outbox_id": outbox_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        payload = row["payload_json"]
        if type(payload) is not dict:
            payload = {}
        return _ClaimedAiEvent(
            outbox_id=cast(UUID, row["id"]),
            event_id=cast(UUID, row["event_id"]),
            event_type=cast(str, row["event_type"]),
            event_version=cast(int, row["event_version"]),
            event_sequence=cast(int, row["event_sequence"]),
            aggregate_type=cast(str, row["aggregate_type"]),
            aggregate_id=cast(UUID, row["aggregate_id"]),
            payload_json=cast(dict[str, object], payload),
            attempt_count=cast(int, row["attempt_count"]),
            trace_id=cast(UUID, row["trace_id"]),
        )

    def _project_claim(self, claim: _ClaimedAiEvent) -> AiCallProjectionResult:
        if claim.event_version not in {1, 2}:
            self._dead_letter(claim, "UNSUPPORTED_EVENT_VERSION")
            return AiCallProjectionResult(
                AiCallProjectionStatus.DEAD_LETTER, claim.event_id, claim.event_type
            )
        try:
            event = self._event_from_payload(claim.payload_json)
            if not self._claim_matches_event(claim, event):
                raise ValueError("outbox identity mismatch")
            if isinstance(event, (AiCallStartedV1, AiCallStartedV2)):
                status = self._project_started(event)
            elif isinstance(event, (AiCallCompletedV1, AiCallCompletedV2)):
                status = self._project_completed(event)
            else:
                status = self._project_late(event)
            self._session.flush()
        except (AiCallEventConflictError, TypeError, ValueError):
            self._dead_letter(claim, "SERIALIZATION_FAILED")
            return AiCallProjectionResult(
                AiCallProjectionStatus.DEAD_LETTER, claim.event_id, claim.event_type
            )

        published = self._session.execute(
            text(
                """
                UPDATE public.outbox_events
                   SET status='published'
                 WHERE id=:outbox_id
                   AND status='processing'
                   AND attempt_count=:attempt_count
                RETURNING id
                """
            ),
            {"outbox_id": claim.outbox_id, "attempt_count": claim.attempt_count},
        ).scalar_one_or_none()
        if published is None:
            raise RuntimeError("AI_AUDIT_OUTBOX_FENCE_LOST")
        return AiCallProjectionResult(status, claim.event_id, claim.event_type)

    @staticmethod
    def _claim_matches_event(
        claim: _ClaimedAiEvent,
        event: AiCallEvent,
    ) -> bool:
        return (
            claim.aggregate_type == "ai_call" == event.aggregate_type
            and claim.aggregate_id == UUID(event.aggregate_id)
            and claim.event_id == UUID(event.event_id)
            and claim.event_type == event.event_type
            and claim.event_version == event.event_version
            and claim.event_sequence == event.event_sequence
            and claim.trace_id == UUID(event.trace_id)
            and claim.event_type in _AI_EVENT_TYPES
        )

    def _project_started(self, event: AiCallStarted) -> AiCallProjectionStatus:
        event_id = UUID(event.event_id)
        existing = self._session.execute(
            select(AiCallLog).where(AiCallLog.id == event_id).with_for_update(of=AiCallLog)
        ).scalar_one_or_none()
        values = self._started_values(event)
        if existing is not None:
            if not self._log_started_matches(existing, values):
                raise AiCallEventConflictError
            return AiCallProjectionStatus.REPLAYED_SAME
        self._session.add(
            AiCallLog(
                **values,
                event_sequence=1,
                output_hash=None,
                actual_cost_microunits=None,
                input_tokens=None,
                output_tokens=None,
                vector_count=None,
                citation_validation_status=None,
                status="pending",
                error_category=None,
                safe_error_code=None,
                http_status=None,
                completed_at=None,
                duration_ms=None,
            )
        )
        return AiCallProjectionStatus.PROJECTED

    def _project_completed(
        self, event: AiCallCompletedV1 | AiCallCompletedV2
    ) -> AiCallProjectionStatus:
        event_id = UUID(event.event_id)
        started_row = self._event_row(event_id, _STARTED_EVENT, lock=False)
        if started_row is None or started_row.status != "published":
            raise AiCallEventConflictError
        started = self._event_from_payload(started_row.payload_json)
        if not isinstance(started, (AiCallStartedV1, AiCallStartedV2)):
            raise AiCallEventConflictError
        validate_ai_call_event_chain_any(started, event)

        log = self._session.execute(
            select(AiCallLog).where(AiCallLog.id == event_id).with_for_update(of=AiCallLog)
        ).scalar_one_or_none()
        if log is None:
            raise AiCallEventConflictError
        terminal = self._completed_values(event)
        if log.status != "pending":
            if not self._log_completed_matches(log, terminal):
                raise AiCallEventConflictError
            return AiCallProjectionStatus.REPLAYED_SAME
        for name, value in terminal.items():
            setattr(log, name, value)
        return AiCallProjectionStatus.PROJECTED

    def _project_late(
        self, event: AiCallLateCompletionV1 | AiCallLateCompletionV2
    ) -> AiCallProjectionStatus:
        event_id = UUID(event.event_id)
        started_row = self._event_row(event_id, _STARTED_EVENT, lock=False)
        completed_row = self._event_row(event_id, _COMPLETED_EVENT, lock=False)
        if (
            started_row is None
            or completed_row is None
            or started_row.status != "published"
            or completed_row.status != "published"
        ):
            raise AiCallEventConflictError
        started = self._event_from_payload(started_row.payload_json)
        completed = self._event_from_payload(completed_row.payload_json)
        if not isinstance(started, (AiCallStartedV1, AiCallStartedV2)) or not isinstance(
            completed, (AiCallCompletedV1, AiCallCompletedV2)
        ):
            raise AiCallEventConflictError
        validate_ai_call_event_chain_any(started, completed, event)
        log = self._session.execute(
            select(AiCallLog).where(AiCallLog.id == event_id).with_for_update(of=AiCallLog)
        ).scalar_one_or_none()
        if log is None or log.status != "outcome_unknown":
            raise AiCallEventConflictError
        return AiCallProjectionStatus.LATE_RECORDED

    @staticmethod
    def _started_values(event: AiCallStarted) -> dict[str, object]:
        values: dict[str, object] = {
            "id": UUID(event.event_id),
            "event_version": event.event_version,
            "organization_id": UUID(event.organization_id),
            "business_operation_id": UUID(event.business_operation_id),
            "job_id": UUID(event.job_id) if event.job_id is not None else None,
            "request_id": UUID(event.request_id) if event.request_id is not None else None,
            "resource_type": event.resource_type,
            "resource_id": UUID(event.resource_id) if event.resource_id is not None else None,
            "trace_id": UUID(event.trace_id),
            "call_type": event.call_type,
            "logical_generation_no": event.logical_generation_no,
            "provider_attempt_no": event.provider_attempt_no,
            "adapter_id": event.adapter_id,
            "endpoint_id": event.endpoint_id,
            "model_id": event.model_id,
            "model_version": event.model_version,
            "prompt_id": event.prompt_id,
            "prompt_version": event.prompt_version,
            "prompt_hash": event.prompt_hash,
            "schema_version": event.schema_version,
            "policy_version": str(event.policy_version),
            "policy_hash": event.policy_hash,
            "pricing_version": event.pricing_version,
            "input_hash": event.input_hash,
            "reserved_input_tokens": event.reserved_input_tokens,
            "reserved_output_tokens": event.reserved_output_tokens,
            "attempt_count": event.attempt_count,
            "is_fallback": event.is_fallback,
            "breaker_state": event.breaker_state,
            "started_at": _parse_timestamp(event.started_at),
        }
        if isinstance(event, AiCallStartedV1):
            values.update(
                reserved_cost_micro_usd=event.reserved_cost_micro_usd,
                cost_currency=None,
                reserved_cost_microunits=None,
            )
        else:
            values.update(
                reserved_cost_micro_usd=None,
                cost_currency=event.cost_currency,
                reserved_cost_microunits=event.reserved_cost_microunits,
            )
        return values

    @staticmethod
    def _completed_values(event: AiCallCompletedV1 | AiCallCompletedV2) -> dict[str, object]:
        values: dict[str, object] = {
            "event_sequence": 2,
            "output_hash": event.output_hash,
            "input_tokens": event.input_tokens,
            "output_tokens": event.output_tokens,
            "vector_count": event.vector_count,
            "citation_validation_status": event.citation_validation_status,
            "status": event.status,
            "error_category": event.error_category,
            "safe_error_code": event.safe_error_code,
            "http_status": event.http_status,
            "completed_at": _parse_timestamp(event.completed_at),
            "duration_ms": event.duration_ms,
        }
        if isinstance(event, AiCallCompletedV2):
            values["actual_cost_microunits"] = event.actual_cost_microunits
        return values

    @staticmethod
    def _log_started_matches(log: AiCallLog, values: Mapping[str, object]) -> bool:
        return all(getattr(log, name) == value for name, value in values.items())

    @staticmethod
    def _log_completed_matches(log: AiCallLog, values: Mapping[str, object]) -> bool:
        return all(getattr(log, name) == value for name, value in values.items())

    def _dead_letter(self, claim: _ClaimedAiEvent, error_code: str) -> None:
        marked = self._session.execute(
            text(
                """
                UPDATE public.outbox_events
                   SET status='dead_letter', last_error=:error_code
                 WHERE id=:outbox_id
                   AND status='processing'
                   AND attempt_count=:attempt_count
                RETURNING id
                """
            ),
            {
                "outbox_id": claim.outbox_id,
                "attempt_count": claim.attempt_count,
                "error_code": error_code,
            },
        ).scalar_one_or_none()
        if marked is None:
            raise RuntimeError("AI_AUDIT_OUTBOX_FENCE_LOST")


__all__ = [
    "AiCallAttemptAudit",
    "AiCallAuditLimits",
    "AiCallAuditRepository",
    "AiCallCompleteStatus",
    "AiCallOperationAuditSummary",
    "AiCallProjectionResult",
    "AiCallProjectionStatus",
    "AiCallReconcileResult",
    "AiCallReconcileStatus",
    "AiCallReserveStatus",
]
