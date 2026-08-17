from __future__ import annotations

from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar, cast

import pytest

from app.ai.event_sink import (
    AiCallEventSink,
    CallScopeToken,
    CompleteAttemptDecision,
    CompleteAttemptStatus,
    PermitUseError,
    ReserveAttemptDecision,
    ReserveAttemptStatus,
    SinkEvent,
)
from app.ai.events import AiCallCompletedV1, AiCallLateCompletionV1, AiCallStartedV1
from app.repositories.ai_call_audit import (
    AiCallAuditLimits,
    AiCallCompleteStatus,
    AiCallReserveStatus,
)
from app.services.ai_call_event_sink import (
    AiCallAuditWriter,
    AiCallCompletionWriter,
    AiCallReserveContext,
    DurableAiCallEventSink,
)

T = TypeVar("T")
_ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[3] / "docs" / "change-requests" / "artifacts" / "CR-011"
)
_LIMITS = AiCallAuditLimits(
    max_provider_attempts_per_business_operation=6,
    max_input_tokens_per_request=32_768,
    max_output_tokens_per_request=2_500,
    max_total_tokens=212_000,
    max_cost_micro_usd=500_000,
)
_CONTEXT = AiCallReserveContext(
    limits=_LIMITS,
    deadline_monotonic=120.0,
    minimum_attempt_seconds=1.0,
)


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    try:
        coroutine.send(None)
    except StopIteration as stopped:
        return cast(T, stopped.value)
    except BaseException:
        coroutine.close()
        raise
    coroutine.close()
    raise AssertionError("durable sink coroutine unexpectedly suspended")


def _event(name: str) -> SinkEvent:
    return SinkEvent.from_json((_ARTIFACT_ROOT / name).read_bytes())


class _AuditWriter:
    def __init__(
        self,
        *,
        reserve: list[AiCallReserveStatus] | None = None,
        complete: list[AiCallCompleteStatus] | None = None,
    ) -> None:
        self.reserve_results = list(reserve or [])
        self.complete_results = list(complete or [])
        self.reserve_calls: list[tuple[AiCallStartedV1, AiCallAuditLimits, float, float]] = []
        self.complete_calls: list[AiCallCompletedV1 | AiCallLateCompletionV1] = []

    def reserve_attempt(
        self,
        event: AiCallStartedV1,
        limits: AiCallAuditLimits,
        *,
        deadline_monotonic: float,
        minimum_attempt_seconds: float = 0.0,
    ) -> AiCallReserveStatus:
        self.reserve_calls.append((event, limits, deadline_monotonic, minimum_attempt_seconds))
        return self.reserve_results.pop(0)

    def complete_attempt(
        self,
        event: AiCallCompletedV1 | AiCallLateCompletionV1,
    ) -> AiCallCompleteStatus:
        self.complete_calls.append(event)
        return self.complete_results.pop(0)


def _sink(writer: _AuditWriter) -> DurableAiCallEventSink:
    return DurableAiCallEventSink(
        cast(AiCallAuditWriter, writer),
        reserve_context_factory=lambda event: _CONTEXT,
    )


def _reserve_and_send(
    sink: DurableAiCallEventSink,
    started: SinkEvent,
) -> CallScopeToken:
    scope = sink.create_call_scope(started)
    decision = run(sink.reserve_attempt(started, scope))
    assert decision.status is ReserveAttemptStatus.RESERVED_NEW
    assert decision.permit is not None
    decision.permit.consume()
    return scope


def test_durable_sink_implements_port_and_forwards_exact_context() -> None:
    writer = _AuditWriter(reserve=[AiCallReserveStatus.RESERVED_NEW])
    contexts: list[AiCallStartedV1] = []

    def reserve_context(event: AiCallStartedV1) -> AiCallReserveContext:
        contexts.append(event)
        return _CONTEXT

    sink = DurableAiCallEventSink(
        cast(AiCallAuditWriter, writer),
        reserve_context_factory=reserve_context,
    )
    event = _event("ai-call-event-v1.started.json")
    scope = sink.create_call_scope(event)

    decision = run(sink.reserve_attempt(event, scope))

    assert isinstance(sink, AiCallEventSink)
    assert decision.status is ReserveAttemptStatus.RESERVED_NEW
    assert decision.permit is not None
    assert len(contexts) == 1
    persisted_event, limits, deadline, minimum = writer.reserve_calls[0]
    assert persisted_event.canonical_payload() == event.payload_jcs
    assert limits is _LIMITS
    assert deadline == 120.0
    assert minimum == 1.0


@pytest.mark.parametrize(
    ("persisted", "expected", "has_permit"),
    [
        (AiCallReserveStatus.RESERVED_NEW, ReserveAttemptStatus.RESERVED_NEW, True),
        (AiCallReserveStatus.REPLAYED_SAME, ReserveAttemptStatus.REPLAYED_SAME, False),
        (AiCallReserveStatus.CONFLICT, ReserveAttemptStatus.CONFLICT, False),
        (AiCallReserveStatus.UNKNOWN, ReserveAttemptStatus.UNKNOWN, False),
        (
            AiCallReserveStatus.BUDGET_EXHAUSTED,
            ReserveAttemptStatus.BUDGET_EXHAUSTED,
            False,
        ),
        (
            AiCallReserveStatus.DEADLINE_EXHAUSTED,
            ReserveAttemptStatus.DEADLINE_EXHAUSTED,
            False,
        ),
    ],
)
def test_reserve_maps_all_persistent_results(
    persisted: AiCallReserveStatus,
    expected: ReserveAttemptStatus,
    has_permit: bool,
) -> None:
    writer = _AuditWriter(reserve=[persisted])
    sink = _sink(writer)
    event = _event("ai-call-event-v1.started.json")
    decision = run(sink.reserve_attempt(event, sink.create_call_scope(event)))

    assert decision.status is expected
    assert (decision.permit is not None) is has_permit


def test_reserve_unknown_recovers_only_for_exact_originating_scope() -> None:
    writer = _AuditWriter(
        reserve=[
            AiCallReserveStatus.UNKNOWN,
            AiCallReserveStatus.REPLAYED_SAME,
            AiCallReserveStatus.REPLAYED_SAME,
            AiCallReserveStatus.REPLAYED_SAME,
        ]
    )
    sink = _sink(writer)
    event = _event("ai-call-event-v1.started.json")
    origin = sink.create_call_scope(event)
    foreign = sink.create_call_scope(event)

    unknown = run(sink.reserve_attempt(event, origin))
    foreign_replay = run(sink.reserve_attempt(event, foreign))
    recovered = run(sink.reserve_attempt(event, origin))
    second_replay = run(sink.reserve_attempt(event, origin))

    assert unknown == ReserveAttemptDecision(ReserveAttemptStatus.UNKNOWN)
    assert foreign_replay == ReserveAttemptDecision(ReserveAttemptStatus.REPLAYED_SAME)
    assert recovered.status is ReserveAttemptStatus.REPLAYED_SAME
    assert recovered.permit is not None
    assert second_replay == ReserveAttemptDecision(ReserveAttemptStatus.REPLAYED_SAME)


def test_reserve_unknown_can_recover_when_retry_commits_new_record() -> None:
    writer = _AuditWriter(reserve=[AiCallReserveStatus.UNKNOWN, AiCallReserveStatus.RESERVED_NEW])
    sink = _sink(writer)
    event = _event("ai-call-event-v1.started.json")
    scope = sink.create_call_scope(event)

    assert run(sink.reserve_attempt(event, scope)).permit is None
    recovered = run(sink.reserve_attempt(event, scope))

    assert recovered.status is ReserveAttemptStatus.RESERVED_NEW
    assert recovered.permit is not None


def test_new_sink_instance_never_recovers_previous_process_unknown() -> None:
    writer = _AuditWriter(reserve=[AiCallReserveStatus.UNKNOWN, AiCallReserveStatus.REPLAYED_SAME])
    event = _event("ai-call-event-v1.started.json")
    first = _sink(writer)
    first_scope = first.create_call_scope(event)
    assert run(first.reserve_attempt(event, first_scope)).status is ReserveAttemptStatus.UNKNOWN

    restarted = _sink(writer)
    replay = run(restarted.reserve_attempt(event, restarted.create_call_scope(event)))

    assert replay == ReserveAttemptDecision(ReserveAttemptStatus.REPLAYED_SAME)


@pytest.mark.parametrize(
    ("persisted", "expected", "has_permit"),
    [
        (AiCallCompleteStatus.COMPLETED_NEW, CompleteAttemptStatus.COMPLETED_NEW, True),
        (AiCallCompleteStatus.REPLAYED_SAME, CompleteAttemptStatus.REPLAYED_SAME, False),
        (AiCallCompleteStatus.LATE_RECORDED, CompleteAttemptStatus.LATE_RECORDED, False),
        (AiCallCompleteStatus.CONFLICT, CompleteAttemptStatus.CONFLICT, False),
        (AiCallCompleteStatus.UNKNOWN, CompleteAttemptStatus.UNKNOWN, False),
        (
            AiCallCompleteStatus.AUDIT_UNAVAILABLE,
            CompleteAttemptStatus.AUDIT_UNAVAILABLE,
            False,
        ),
    ],
)
def test_complete_maps_all_persistent_results(
    persisted: AiCallCompleteStatus,
    expected: CompleteAttemptStatus,
    has_permit: bool,
) -> None:
    writer = _AuditWriter(
        reserve=[AiCallReserveStatus.RESERVED_NEW],
        complete=[persisted],
    )
    sink = _sink(writer)
    started = _event("ai-call-event-v1.started.json")
    scope = _reserve_and_send(sink, started)
    completed = _event("ai-call-event-v1.completed.json")

    decision = run(sink.complete_attempt(completed, scope))

    assert decision.status is expected
    assert (decision.permit is not None) is has_permit
    assert writer.complete_calls[0].canonical_payload() == completed.payload_jcs


def test_completion_can_use_the_business_transaction_writer() -> None:
    reserve_writer = _AuditWriter(reserve=[AiCallReserveStatus.RESERVED_NEW])
    transaction_writer = _AuditWriter(complete=[AiCallCompleteStatus.COMPLETED_NEW])
    sink = _sink(reserve_writer)
    started = _event("ai-call-event-v1.started.json")
    scope = _reserve_and_send(sink, started)
    completed = _event("ai-call-event-v1.completed.json")

    decision = run(
        sink.complete_attempt_in_transaction(
            completed,
            scope,
            cast(AiCallCompletionWriter, transaction_writer),
        )
    )

    assert decision.status is CompleteAttemptStatus.COMPLETED_NEW
    assert decision.permit is not None
    decision.permit.consume()
    assert reserve_writer.complete_calls == []
    assert transaction_writer.complete_calls[0].canonical_payload() == completed.payload_jcs


def test_complete_unknown_recovers_only_for_sent_origin_scope() -> None:
    writer = _AuditWriter(
        reserve=[AiCallReserveStatus.RESERVED_NEW],
        complete=[
            AiCallCompleteStatus.UNKNOWN,
            AiCallCompleteStatus.REPLAYED_SAME,
            AiCallCompleteStatus.REPLAYED_SAME,
        ],
    )
    sink = _sink(writer)
    started = _event("ai-call-event-v1.started.json")
    scope = _reserve_and_send(sink, started)
    completed = _event("ai-call-event-v1.completed.json")
    foreign = sink.create_call_scope(completed)

    unknown = run(sink.complete_attempt(completed, scope))
    foreign_replay = run(sink.complete_attempt(completed, foreign))
    recovered = run(sink.complete_attempt(completed, scope))

    assert unknown == CompleteAttemptDecision(CompleteAttemptStatus.UNKNOWN)
    assert foreign_replay == CompleteAttemptDecision(CompleteAttemptStatus.REPLAYED_SAME)
    assert recovered.status is CompleteAttemptStatus.REPLAYED_SAME
    assert recovered.permit is not None
    recovered.permit.consume()


def test_complete_without_consumed_send_never_issues_adopt_permit() -> None:
    writer = _AuditWriter(
        reserve=[AiCallReserveStatus.RESERVED_NEW],
        complete=[AiCallCompleteStatus.COMPLETED_NEW],
    )
    sink = _sink(writer)
    started = _event("ai-call-event-v1.started.json")
    scope = sink.create_call_scope(started)
    reserve = run(sink.reserve_attempt(started, scope))
    assert reserve.permit is not None

    completed = run(sink.complete_attempt(_event("ai-call-event-v1.completed.json"), scope))

    assert completed == CompleteAttemptDecision(CompleteAttemptStatus.COMPLETED_NEW)


def test_outcome_unknown_and_late_completion_never_issue_adopt_permit() -> None:
    writer = _AuditWriter(
        reserve=[AiCallReserveStatus.RESERVED_NEW],
        complete=[AiCallCompleteStatus.COMPLETED_NEW, AiCallCompleteStatus.LATE_RECORDED],
    )
    sink = _sink(writer)
    started = _event("ai-call-event-v1.started-outcome-unknown.json")
    scope = _reserve_and_send(sink, started)

    outcome = run(
        sink.complete_attempt(
            _event("ai-call-event-v1.completed-outcome-unknown.json"),
            scope,
        )
    )
    late = run(
        sink.complete_attempt(
            _event("ai-call-event-v1.late.json"),
            scope,
        )
    )

    assert outcome == CompleteAttemptDecision(CompleteAttemptStatus.COMPLETED_NEW)
    assert late == CompleteAttemptDecision(CompleteAttemptStatus.LATE_RECORDED)


def test_foreign_scope_and_missing_reserve_context_fail_closed() -> None:
    writer = _AuditWriter(reserve=[AiCallReserveStatus.RESERVED_NEW])
    first = _sink(writer)
    second = _sink(writer)
    started = _event("ai-call-event-v1.started.json")
    foreign = first.create_call_scope(started)

    with pytest.raises(PermitUseError, match="CALL_SCOPE_NOT_OWNED"):
        run(second.reserve_attempt(started, foreign))

    completed_scope = second.create_call_scope(_event("ai-call-event-v1.completed.json"))
    with pytest.raises(PermitUseError, match="CALL_SCOPE_RESERVE_CONTEXT_MISSING"):
        run(second.reserve_attempt(started, completed_scope))


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("deadline_monotonic", True, "deadline_monotonic must be finite"),
        ("deadline_monotonic", float("inf"), "deadline_monotonic must be finite"),
        (
            "minimum_attempt_seconds",
            -1.0,
            "minimum_attempt_seconds must be non-negative",
        ),
    ],
)
def test_reserve_context_rejects_unsafe_deadlines(
    field: str,
    value: object,
    error: str,
) -> None:
    values: dict[str, object] = {
        "limits": _LIMITS,
        "deadline_monotonic": 120.0,
        "minimum_attempt_seconds": 1.0,
    }
    values[field] = value

    with pytest.raises(ValueError, match=error):
        AiCallReserveContext(**cast(Any, values))


def test_context_factory_must_return_typed_context() -> None:
    writer = _AuditWriter()
    sink = DurableAiCallEventSink(
        cast(AiCallAuditWriter, writer),
        reserve_context_factory=cast(Any, lambda event: object()),
    )

    with pytest.raises(TypeError, match="must return AiCallReserveContext"):
        sink.create_call_scope(_event("ai-call-event-v1.started.json"))
