from __future__ import annotations

import json
import pickle
import socket
import time
from collections.abc import Coroutine, Generator
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, NoReturn, TypeVar, cast

import pytest
from pydantic import ValidationError

from app.ai.event_sink import (
    AdoptPermit,
    AiCallEventSink,
    CallScopeToken,
    CompleteAttemptDecision,
    CompleteAttemptStatus,
    CompleteFault,
    FakeAiCallEventSink,
    InMemoryAiCallEventSink,
    PermitUseError,
    ReserveAttemptDecision,
    ReserveAttemptStatus,
    ReserveFault,
    SendPermit,
    SinkEvent,
)
from app.ai.events import AiCallStartedV1, parse_ai_call_event_v1

T = TypeVar("T")
_ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[3] / "docs" / "change-requests" / "artifacts" / "CR-011"
)
_NORMAL_ID = "11111111-1111-4111-8111-111111111111"
_UNKNOWN_ID = "88888888-8888-4888-8888-888888888888"
_ID_2 = "00000000-0000-4000-8000-000000000002"
_ID_3 = "00000000-0000-4000-8000-000000000003"


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    """单步驱动必须同步完成的纯 async 合同；任何 suspend 都立即失败。"""

    try:
        coroutine.send(None)
    except StopIteration as stopped:
        return cast(T, stopped.value)
    except BaseException:
        coroutine.close()
        raise
    coroutine.close()
    raise AssertionError("Gate B coroutine unexpectedly suspended")


def _payload(name: str) -> dict[str, object]:
    value = json.loads((_ARTIFACT_ROOT / name).read_bytes())
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def make_event(
    name: str,
    *,
    event_id: str | None = None,
    marker: int = 0,
    updates: dict[str, object] | None = None,
) -> SinkEvent:
    payload = _payload(name)
    if event_id is not None:
        payload["event_id"] = event_id
        payload["aggregate_id"] = event_id
    if marker:
        event_type = payload["event_type"]
        field = "reserved_input_tokens" if event_type == "ai.call.started" else "duration_ms"
        current = payload[field]
        assert isinstance(current, int) and not isinstance(current, bool)
        payload[field] = current + marker
    if updates is not None:
        payload.update(updates)
    return SinkEvent.from_json(json.dumps(payload, separators=(",", ":")))


def started(*, event_id: str = _NORMAL_ID, marker: int = 0) -> SinkEvent:
    return make_event("ai-call-event-v1.started.json", event_id=event_id, marker=marker)


def completed(*, event_id: str = _NORMAL_ID, marker: int = 0) -> SinkEvent:
    return make_event("ai-call-event-v1.completed.json", event_id=event_id, marker=marker)


def outcome_started() -> SinkEvent:
    return make_event("ai-call-event-v1.started-outcome-unknown.json")


def outcome_completed() -> SinkEvent:
    return make_event("ai-call-event-v1.completed-outcome-unknown.json")


def late(*, marker: int = 0) -> SinkEvent:
    return make_event("ai-call-event-v1.late.json", marker=marker)


def reserve_and_send(
    sink: InMemoryAiCallEventSink,
    event: SinkEvent,
) -> CallScopeToken:
    scope = sink.create_call_scope(event)
    decision = run(sink.reserve_attempt(event, scope))
    assert decision.status is ReserveAttemptStatus.RESERVED_NEW
    assert decision.permit is not None
    decision.permit.consume()
    return scope


def test_sink_event_has_one_strict_dto_source_and_revalidates_untrusted_objects() -> None:
    raw = (_ARTIFACT_ROOT / "ai-call-event-v1.started.json").read_bytes()
    dto = parse_ai_call_event_v1(raw)
    assert isinstance(dto, AiCallStartedV1)

    from_dto = SinkEvent(dto)
    from_json = SinkEvent.from_json(raw)
    untrusted_state = dict(dto.__dict__)
    untrusted_state["event_id"] = _ID_2
    tampered = AiCallStartedV1.model_construct(
        _fields_set=set(dto.__pydantic_fields_set__),
        **untrusted_state,
    )

    assert from_dto.payload_jcs == from_json.payload_jcs
    assert from_dto.event_id == dto.event_id
    assert from_dto.event_type == dto.event_type
    assert from_dto.event_status == dto.status
    with pytest.raises(FrozenInstanceError):
        from_dto._payload_jcs = b"side-channel"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="AiCallEventV1 validation failed"):
        SinkEvent(tampered)
    with pytest.raises(TypeError):
        SinkEvent(  # type: ignore[call-arg]
            event_id=_NORMAL_ID,
            event_type="ai.call.started",
            event_status="pending",
            payload_jcs=raw,
        )


def test_sink_protocol_and_fake_alias_are_explicitly_offline() -> None:
    sink = FakeAiCallEventSink()
    event = started()

    assert FakeAiCallEventSink is InMemoryAiCallEventSink
    assert isinstance(sink, AiCallEventSink)
    assert isinstance(sink.create_call_scope(event), CallScopeToken)


def test_reserve_attempt_covers_all_six_results() -> None:
    sink = InMemoryAiCallEventSink()
    event = started()
    scope = sink.create_call_scope(event)

    reserved = run(sink.reserve_attempt(event, scope))
    replayed = run(sink.reserve_attempt(event, scope))
    conflict = run(sink.reserve_attempt(started(marker=1), scope))

    unknown_sink = InMemoryAiCallEventSink()
    unknown_scope = unknown_sink.create_call_scope(event)
    unknown_sink.inject_next_reserve_fault(ReserveFault.COMMIT_BEFORE_RETURN)
    unknown = run(unknown_sink.reserve_attempt(event, unknown_scope))

    budget_sink = InMemoryAiCallEventSink()
    budget_scope = budget_sink.create_call_scope(event)
    budget_sink.inject_next_reserve_fault(ReserveFault.BUDGET_EXHAUSTED)
    budget = run(budget_sink.reserve_attempt(event, budget_scope))

    deadline_sink = InMemoryAiCallEventSink()
    deadline_scope = deadline_sink.create_call_scope(event)
    deadline_sink.inject_next_reserve_fault(ReserveFault.DEADLINE_EXHAUSTED)
    deadline = run(deadline_sink.reserve_attempt(event, deadline_scope))

    assert reserved.status is ReserveAttemptStatus.RESERVED_NEW
    assert reserved.permit is not None
    assert replayed == ReserveAttemptDecision(ReserveAttemptStatus.REPLAYED_SAME)
    assert conflict == ReserveAttemptDecision(ReserveAttemptStatus.CONFLICT)
    assert unknown == ReserveAttemptDecision(ReserveAttemptStatus.UNKNOWN)
    assert budget == ReserveAttemptDecision(ReserveAttemptStatus.BUDGET_EXHAUSTED)
    assert deadline == ReserveAttemptDecision(ReserveAttemptStatus.DEADLINE_EXHAUSTED)


def test_complete_attempt_covers_all_six_results() -> None:
    sink = InMemoryAiCallEventSink()
    scope = reserve_and_send(sink, started())
    completed_event = completed()

    completed_new = run(sink.complete_attempt(completed_event, scope))
    replayed = run(sink.complete_attempt(completed_event, scope))
    conflict = run(sink.complete_attempt(completed(marker=1), scope))

    unknown_sink = InMemoryAiCallEventSink()
    unknown_started = started(event_id=_ID_2)
    unknown_scope = reserve_and_send(unknown_sink, unknown_started)
    unknown_sink.inject_next_complete_fault(CompleteFault.COMMIT_BEFORE_RETURN)
    unknown = run(unknown_sink.complete_attempt(completed(event_id=_ID_2), unknown_scope))

    audit_sink = InMemoryAiCallEventSink()
    audit_started = started(event_id=_ID_3)
    audit_scope = reserve_and_send(audit_sink, audit_started)
    audit_sink.inject_next_complete_fault(CompleteFault.AUDIT_UNAVAILABLE)
    audit_unavailable = run(audit_sink.complete_attempt(completed(event_id=_ID_3), audit_scope))

    late_sink = InMemoryAiCallEventSink()
    late_scope = reserve_and_send(late_sink, outcome_started())
    outcome_unknown = run(late_sink.complete_attempt(outcome_completed(), late_scope))
    late_recorded = run(late_sink.complete_attempt(late(), late_scope))

    assert completed_new.status is CompleteAttemptStatus.COMPLETED_NEW
    assert completed_new.permit is not None
    assert replayed == CompleteAttemptDecision(CompleteAttemptStatus.REPLAYED_SAME)
    assert conflict == CompleteAttemptDecision(CompleteAttemptStatus.CONFLICT)
    assert unknown == CompleteAttemptDecision(CompleteAttemptStatus.UNKNOWN)
    assert audit_unavailable == CompleteAttemptDecision(CompleteAttemptStatus.AUDIT_UNAVAILABLE)
    assert outcome_unknown == CompleteAttemptDecision(CompleteAttemptStatus.COMPLETED_NEW)
    assert late_recorded == CompleteAttemptDecision(CompleteAttemptStatus.LATE_RECORDED)


def test_completed_event_conflict_does_not_record_or_issue_adopt_permit() -> None:
    sink = InMemoryAiCallEventSink()
    scope = reserve_and_send(sink, started())
    conflicting = make_event(
        "ai-call-event-v1.completed.json",
        updates={"organization_id": _ID_2},
    )

    rejected = run(sink.complete_attempt(conflicting, scope))
    accepted = run(sink.complete_attempt(completed(), scope))

    assert rejected == CompleteAttemptDecision(CompleteAttemptStatus.CONFLICT)
    assert rejected.permit is None
    assert accepted.status is CompleteAttemptStatus.COMPLETED_NEW
    assert accepted.permit is not None


def test_late_event_conflict_does_not_record_or_issue_adopt_permit() -> None:
    sink = InMemoryAiCallEventSink()
    scope = reserve_and_send(sink, outcome_started())
    assert run(sink.complete_attempt(outcome_completed(), scope)).permit is None
    conflicting = make_event(
        "ai-call-event-v1.late.json",
        updates={"organization_id": _ID_2},
    )

    rejected = run(sink.complete_attempt(conflicting, scope))
    accepted = run(sink.complete_attempt(late(), scope))

    assert rejected == CompleteAttemptDecision(CompleteAttemptStatus.CONFLICT)
    assert rejected.permit is None
    assert accepted == CompleteAttemptDecision(CompleteAttemptStatus.LATE_RECORDED)


def test_send_adopt_and_scope_tokens_are_single_process_only() -> None:
    sink = InMemoryAiCallEventSink()
    event = started()
    scope = sink.create_call_scope(event)
    reserve = run(sink.reserve_attempt(event, scope))
    send_permit = reserve.permit
    assert isinstance(send_permit, SendPermit)
    assert repr(send_permit) == "<SendPermit consumed=False>"

    for process_local in (scope, send_permit):
        with pytest.raises(TypeError, match="PROCESS_LOCAL"):
            pickle.dumps(process_local)

    send_permit.consume()
    assert send_permit.consumed is True
    with pytest.raises(PermitUseError, match="SEND_PERMIT_ALREADY_CONSUMED"):
        send_permit.consume()

    complete = run(sink.complete_attempt(completed(), scope))
    adopt_permit = complete.permit
    assert isinstance(adopt_permit, AdoptPermit)
    with pytest.raises(TypeError, match="PROCESS_LOCAL_PERMIT_NOT_SERIALIZABLE"):
        pickle.dumps(adopt_permit)

    adopt_permit.consume()
    assert adopt_permit.consumed is True
    with pytest.raises(PermitUseError, match="ADOPT_PERMIT_ALREADY_CONSUMED"):
        adopt_permit.consume()


def test_reserve_recovery_requires_the_exact_originating_scope_token() -> None:
    sink = InMemoryAiCallEventSink()
    event = started()
    origin = sink.create_call_scope(event)
    foreign = sink.create_call_scope(event)
    sink.inject_next_reserve_fault(ReserveFault.COMMIT_BEFORE_RETURN)

    uncertain = run(sink.reserve_attempt(event, origin))
    foreign_replay = run(sink.reserve_attempt(event, foreign))
    recovered = run(sink.reserve_attempt(event, origin))
    second_replay = run(sink.reserve_attempt(event, origin))

    assert uncertain == ReserveAttemptDecision(ReserveAttemptStatus.UNKNOWN)
    assert foreign_replay == ReserveAttemptDecision(ReserveAttemptStatus.REPLAYED_SAME)
    assert recovered.status is ReserveAttemptStatus.REPLAYED_SAME
    assert recovered.permit is not None
    assert second_replay == ReserveAttemptDecision(ReserveAttemptStatus.REPLAYED_SAME)


def test_complete_recovery_requires_the_exact_originating_scope_token() -> None:
    sink = InMemoryAiCallEventSink()
    scope = reserve_and_send(sink, started())
    foreign = sink.create_call_scope(completed())
    sink.inject_next_complete_fault(CompleteFault.COMMIT_BEFORE_RETURN)

    uncertain = run(sink.complete_attempt(completed(), scope))
    foreign_replay = run(sink.complete_attempt(completed(), foreign))
    recovered = run(sink.complete_attempt(completed(), scope))
    second_replay = run(sink.complete_attempt(completed(), scope))

    assert uncertain == CompleteAttemptDecision(CompleteAttemptStatus.UNKNOWN)
    assert foreign_replay == CompleteAttemptDecision(CompleteAttemptStatus.REPLAYED_SAME)
    assert recovered.status is CompleteAttemptStatus.REPLAYED_SAME
    assert recovered.permit is not None
    assert second_replay == CompleteAttemptDecision(CompleteAttemptStatus.REPLAYED_SAME)


@pytest.mark.parametrize("window", ["return-before-call-site", "crash-before-send"])
def test_unconsumed_send_permit_expires_across_simulated_restart(window: str) -> None:
    del window
    sink = InMemoryAiCallEventSink()
    event = started()
    scope = sink.create_call_scope(event)
    reserved = run(sink.reserve_attempt(event, scope))
    permit = reserved.permit
    assert permit is not None

    sink.simulate_process_restart()
    replay_scope = sink.create_call_scope(event)
    replayed = run(sink.reserve_attempt(event, replay_scope))

    assert replayed == ReserveAttemptDecision(ReserveAttemptStatus.REPLAYED_SAME)
    with pytest.raises(PermitUseError, match="SEND_PERMIT_SCOPE_EXPIRED"):
        permit.consume()
    with pytest.raises(PermitUseError, match="CALL_SCOPE_EXPIRED"):
        run(sink.reserve_attempt(event, scope))


def test_crash_after_send_never_issues_a_replay_permit() -> None:
    sink = InMemoryAiCallEventSink()
    event = started()
    scope = reserve_and_send(sink, event)
    assert scope.event_id == event.event_id

    sink.simulate_process_restart()
    replayed = run(sink.reserve_attempt(event, sink.create_call_scope(event)))

    assert replayed == ReserveAttemptDecision(ReserveAttemptStatus.REPLAYED_SAME)


def test_returned_adopt_permit_expires_before_call_site_after_restart() -> None:
    sink = InMemoryAiCallEventSink()
    scope = reserve_and_send(sink, started())
    completed_event = completed()
    completed_new = run(sink.complete_attempt(completed_event, scope))
    permit = completed_new.permit
    assert permit is not None

    sink.simulate_process_restart()
    replay_scope = sink.create_call_scope(completed_event)
    replayed = run(sink.complete_attempt(completed_event, replay_scope))

    assert replayed == CompleteAttemptDecision(CompleteAttemptStatus.REPLAYED_SAME)
    with pytest.raises(PermitUseError, match="ADOPT_PERMIT_SCOPE_EXPIRED"):
        permit.consume()


def test_outcome_unknown_requires_late_event_and_never_issues_adopt_permit() -> None:
    sink = InMemoryAiCallEventSink()
    scope = reserve_and_send(sink, outcome_started())

    outcome = run(sink.complete_attempt(outcome_completed(), scope))
    invalid_overwrite = run(sink.complete_attempt(completed(event_id=_UNKNOWN_ID), scope))
    late_recorded = run(sink.complete_attempt(late(), scope))
    late_replay = run(sink.complete_attempt(late(), scope))
    late_conflict = run(sink.complete_attempt(late(marker=1), scope))

    assert outcome == CompleteAttemptDecision(CompleteAttemptStatus.COMPLETED_NEW)
    assert invalid_overwrite == CompleteAttemptDecision(CompleteAttemptStatus.CONFLICT)
    assert late_recorded == CompleteAttemptDecision(CompleteAttemptStatus.LATE_RECORDED)
    assert late_replay == CompleteAttemptDecision(CompleteAttemptStatus.REPLAYED_SAME)
    assert late_conflict == CompleteAttemptDecision(CompleteAttemptStatus.CONFLICT)
    assert all(
        decision.permit is None
        for decision in (outcome, invalid_overwrite, late_recorded, late_replay, late_conflict)
    )


@pytest.mark.parametrize(
    "window",
    ["no-fault", "commit-before-return", "audit-unavailable", "restart"],
)
def test_late_same_payload_replay_never_issues_adopt_permit(window: str) -> None:
    sink = InMemoryAiCallEventSink()
    scope = reserve_and_send(sink, outcome_started())
    outcome = run(sink.complete_attempt(outcome_completed(), scope))
    assert outcome.permit is None
    late_event = late()
    decisions: list[CompleteAttemptDecision] = []

    if window == "commit-before-return":
        sink.inject_next_complete_fault(CompleteFault.COMMIT_BEFORE_RETURN)
        decisions.append(run(sink.complete_attempt(late_event, scope)))
    elif window == "audit-unavailable":
        sink.inject_next_complete_fault(CompleteFault.AUDIT_UNAVAILABLE)
        decisions.append(run(sink.complete_attempt(late_event, scope)))

    if window == "restart":
        decisions.append(run(sink.complete_attempt(late_event, scope)))
        sink.simulate_process_restart()
        scope = sink.create_call_scope(late_event)

    decisions.append(run(sink.complete_attempt(late_event, scope)))
    decisions.append(run(sink.complete_attempt(late_event, scope)))

    assert all(decision.permit is None for decision in decisions)
    assert decisions[-1].status is CompleteAttemptStatus.REPLAYED_SAME


def test_replayed_after_restart_and_unknown_never_send_or_adopt() -> None:
    sink = InMemoryAiCallEventSink()
    event = started()
    scope = sink.create_call_scope(event)
    sink.inject_next_reserve_fault(ReserveFault.COMMIT_BEFORE_RETURN)
    assert run(sink.reserve_attempt(event, scope)).status is ReserveAttemptStatus.UNKNOWN

    sink.simulate_process_restart()
    replay_scope = sink.create_call_scope(event)
    reserve_replay = run(sink.reserve_attempt(event, replay_scope))
    completed_event = completed()
    complete_without_send = run(sink.complete_attempt(completed_event, replay_scope))

    assert reserve_replay == ReserveAttemptDecision(ReserveAttemptStatus.REPLAYED_SAME)
    assert complete_without_send == CompleteAttemptDecision(CompleteAttemptStatus.COMPLETED_NEW)


def test_payload_never_appears_in_repr_or_safe_permit_errors() -> None:
    sentinel = "SENSITIVE_BUSINESS_SENTINEL"
    sink = InMemoryAiCallEventSink()
    event = make_event(
        "ai-call-event-v1.started.json",
        updates={"model_id": sentinel},
    )
    scope = sink.create_call_scope(event)
    decision = run(sink.reserve_attempt(event, scope))
    permit = decision.permit
    assert permit is not None
    sink.simulate_process_restart()

    with pytest.raises(PermitUseError) as captured:
        permit.consume()

    assert sentinel not in repr(event)
    assert sentinel not in repr(decision)
    assert sentinel not in str(captured.value)


def test_run_rejects_and_closes_any_coroutine_that_suspends() -> None:
    closed = False

    class SuspendOnce:
        def __await__(self) -> Generator[object, None, None]:
            yield object()

    async def scenario() -> None:
        nonlocal closed
        try:
            await SuspendOnce()
        finally:
            closed = True

    with pytest.raises(AssertionError, match="unexpectedly suspended"):
        run(scenario())
    assert closed is True


def test_fake_sink_does_not_use_socket_dns_or_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_call(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise AssertionError("socket, DNS, and sleep are forbidden")

    monkeypatch.setattr(socket, "socket", unexpected_call)
    monkeypatch.setattr(socket, "create_connection", unexpected_call)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected_call)
    monkeypatch.setattr(time, "sleep", unexpected_call)

    async def scenario() -> None:
        sink = InMemoryAiCallEventSink()
        started_event = started()
        scope = sink.create_call_scope(started_event)
        reserve = await sink.reserve_attempt(started_event, scope)
        assert reserve.permit is not None
        reserve.permit.consume()
        complete = await sink.complete_attempt(completed(), scope)
        assert complete.permit is not None

    run(scenario())
