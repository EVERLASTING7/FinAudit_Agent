from __future__ import annotations

import json
from asyncio import run as run_async
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.ai.event_sink import (
    CompleteAttemptStatus,
    ReserveAttemptStatus,
    SinkEvent,
)
from app.ai.events import (
    AiCallCompletedV1,
    AiCallCompletedV2,
    AiCallLateCompletionV1,
    AiCallStartedV1,
    AiCallStartedV2,
    parse_ai_call_event_v1,
    validate_ai_call_event_v2,
)
from app.db.migration import create_migration_engine
from app.db.session import create_session_factory
from app.models.audit import AiCallLog
from app.models.auth import Organization
from app.models.reliability import OutboxEvent
from app.repositories.ai_call_audit import (
    AiCallAuditLimits,
    AiCallAuditLimitsV2,
    AiCallAuditRepository,
    AiCallCompleteStatus,
    AiCallProjectionStatus,
    AiCallReconcileStatus,
    AiCallReserveStatus,
)
from app.services.ai_call_audit import AiCallAuditService
from app.services.ai_call_event_sink import (
    AiCallReserveContext,
    DurableAiCallEventSink,
)
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
)

pytestmark = pytest.mark.integration

_ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[4] / "docs" / "change-requests" / "artifacts" / "CR-011"
)
_ORGANIZATION_ID = UUID("22222222-2222-4222-8222-222222222222")
_OPERATION_ID = UUID("33333333-3333-4333-8333-333333333333")
_EVENT_1 = UUID("11111111-1111-4111-8111-111111111111")
_EVENT_2 = UUID("11111111-1111-4111-8111-111111111112")
_EVENT_3 = UUID("11111111-1111-4111-8111-111111111113")
_EVENT_4 = UUID("11111111-1111-4111-8111-111111111114")
_EVENT_5 = UUID("11111111-1111-4111-8111-111111111115")
_EVENT_6 = UUID("11111111-1111-4111-8111-111111111116")
_EVENT_7 = UUID("11111111-1111-4111-8111-111111111117")
_EVENT_8 = UUID("11111111-1111-4111-8111-111111111118")
_EVENT_9 = UUID("11111111-1111-4111-8111-111111111119")
_EVENT_10 = UUID("11111111-1111-4111-8111-111111111120")
_EVENT_11 = UUID("11111111-1111-4111-8111-111111111121")
_EVENT_12 = UUID("11111111-1111-4111-8111-111111111122")
_EVENT_13 = UUID("11111111-1111-4111-8111-111111111123")
_EVENT_14 = UUID("11111111-1111-4111-8111-111111111124")
_EVENT_15 = UUID("11111111-1111-4111-8111-111111111125")
_EVENT_16 = UUID("11111111-1111-4111-8111-111111111126")
_EVENT_17 = UUID("11111111-1111-4111-8111-111111111127")
_EVENT_IDS = (
    _EVENT_1,
    _EVENT_2,
    _EVENT_3,
    _EVENT_4,
    _EVENT_5,
    _EVENT_6,
    _EVENT_7,
    _EVENT_8,
    _EVENT_9,
    _EVENT_10,
    _EVENT_11,
    _EVENT_12,
    _EVENT_13,
    _EVENT_14,
    _EVENT_15,
    _EVENT_16,
    _EVENT_17,
)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _payload(name: str) -> dict[str, object]:
    value = json.loads((_ARTIFACT_ROOT / name).read_bytes())
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _started(
    event_id: UUID,
    *,
    operation_id: UUID = _OPERATION_ID,
    attempt_no: int = 1,
    started_at: datetime,
    reserved_input_tokens: int = 128,
    reserved_output_tokens: int = 2_500,
    reserved_cost_micro_usd: int = 0,
) -> AiCallStartedV1:
    payload = _payload("ai-call-event-v1.started.json")
    payload.update(
        {
            "event_id": str(event_id),
            "aggregate_id": str(event_id),
            "business_operation_id": str(operation_id),
            "job_id": None,
            "provider_attempt_no": attempt_no,
            "attempt_count": attempt_no,
            "reserved_input_tokens": reserved_input_tokens,
            "reserved_output_tokens": reserved_output_tokens,
            "reserved_cost_micro_usd": reserved_cost_micro_usd,
            "started_at": _timestamp(started_at),
        }
    )
    event = parse_ai_call_event_v1(json.dumps(payload, separators=(",", ":")))
    assert isinstance(event, AiCallStartedV1)
    return event


def _completed(
    event_id: UUID,
    *,
    operation_id: UUID = _OPERATION_ID,
    completed_at: datetime,
    duration_ms: int = 750,
) -> AiCallCompletedV1:
    payload = _payload("ai-call-event-v1.completed.json")
    payload.update(
        {
            "event_id": str(event_id),
            "aggregate_id": str(event_id),
            "business_operation_id": str(operation_id),
            "job_id": None,
            "completed_at": _timestamp(completed_at),
            "duration_ms": duration_ms,
        }
    )
    event = parse_ai_call_event_v1(json.dumps(payload, separators=(",", ":")))
    assert isinstance(event, AiCallCompletedV1)
    return event


def _started_v2(
    event_id: UUID,
    *,
    operation_id: UUID,
    started_at: datetime,
    currency: str = "CNY",
    reserved_cost_microunits: int = 10,
) -> AiCallStartedV2:
    event = validate_ai_call_event_v2(
        {
            "event_id": str(event_id),
            "event_version": 2,
            "event_sequence": 1,
            "event_type": "ai.call.started",
            "aggregate_type": "ai_call",
            "aggregate_id": str(event_id),
            "organization_id": str(_ORGANIZATION_ID),
            "business_operation_id": str(operation_id),
            "job_id": None,
            "request_id": None,
            "resource_type": "knowledge_index",
            "resource_id": None,
            "trace_id": "66666666-6666-4666-8666-666666666666",
            "call_type": "embedding",
            "logical_generation_no": 1,
            "provider_attempt_no": 1,
            "adapter_id": "openai_embeddings_v1",
            "endpoint_id": "synthetic-endpoint-v2",
            "model_id": "synthetic-embedding-v2",
            "model_version": None,
            "prompt_id": None,
            "prompt_version": None,
            "prompt_hash": None,
            "schema_version": None,
            "policy_version": 2,
            "policy_hash": "a" * 64,
            "pricing_version": "synthetic-cny-v2",
            "input_hash": "b" * 64,
            "reserved_input_tokens": 20,
            "reserved_output_tokens": 0,
            "cost_currency": currency,
            "reserved_cost_microunits": reserved_cost_microunits,
            "attempt_count": 1,
            "is_fallback": False,
            "breaker_state": "closed",
            "status": "pending",
            "started_at": _timestamp(started_at),
        }
    )
    assert isinstance(event, AiCallStartedV2)
    return event


def _completed_v2(
    event_id: UUID,
    *,
    operation_id: UUID,
    completed_at: datetime,
    actual_cost_microunits: int = 7,
) -> AiCallCompletedV2:
    event = validate_ai_call_event_v2(
        {
            "event_id": str(event_id),
            "event_version": 2,
            "event_sequence": 2,
            "event_type": "ai.call.completed",
            "aggregate_type": "ai_call",
            "aggregate_id": str(event_id),
            "organization_id": str(_ORGANIZATION_ID),
            "business_operation_id": str(operation_id),
            "job_id": None,
            "request_id": None,
            "trace_id": "66666666-6666-4666-8666-666666666666",
            "policy_version": 2,
            "policy_hash": "a" * 64,
            "cost_currency": "CNY",
            "actual_cost_microunits": actual_cost_microunits,
            "status": "succeeded",
            "completed_at": _timestamp(completed_at),
            "duration_ms": 1000,
            "output_hash": "c" * 64,
            "input_tokens": 14,
            "output_tokens": 0,
            "vector_count": 2,
            "http_status": 200,
            "error_category": None,
            "safe_error_code": None,
            "citation_validation_status": None,
        }
    )
    assert isinstance(event, AiCallCompletedV2)
    return event


def _late(
    event_id: UUID,
    *,
    operation_id: UUID,
    completed_at: datetime,
) -> AiCallLateCompletionV1:
    payload = _payload("ai-call-event-v1.late.json")
    payload.update(
        {
            "event_id": str(event_id),
            "aggregate_id": str(event_id),
            "business_operation_id": str(operation_id),
            "job_id": None,
            "request_id": "44444444-4444-4444-8444-444444444444",
            "trace_id": "66666666-6666-4666-8666-666666666666",
            "provider_completed_at": _timestamp(completed_at),
        }
    )
    event = parse_ai_call_event_v1(json.dumps(payload, separators=(",", ":")))
    assert isinstance(event, AiCallLateCompletionV1)
    return event


def _outbox(
    event: AiCallStartedV1 | AiCallCompletedV1 | AiCallLateCompletionV1,
    *,
    event_version: int | None = None,
    payload: dict[str, object] | None = None,
) -> OutboxEvent:
    canonical_payload = json.loads(event.canonical_payload())
    assert isinstance(canonical_payload, dict)
    return OutboxEvent(
        id=uuid4(),
        aggregate_type=event.aggregate_type,
        aggregate_id=UUID(event.aggregate_id),
        event_id=UUID(event.event_id),
        event_type=event.event_type,
        event_version=event.event_version if event_version is None else event_version,
        event_sequence=event.event_sequence,
        payload_json=cast(dict[str, object], canonical_payload) if payload is None else payload,
        status="pending",
        attempt_count=0,
        next_attempt_at=None,
        published_at=None,
        last_error=None,
        trace_id=UUID(event.trace_id),
    )


def _setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Engine, sessionmaker[Session], AiCallAuditService]:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        session.add(
            Organization(
                id=_ORGANIZATION_ID,
                name="Synthetic AI audit organization",
                unified_social_credit_code="SYNTH-AI-AUDIT-USCC",
                tax_number="SYNTH-AI-AUDIT-TAX",
                status="active",
            )
        )
    return engine, factory, AiCallAuditService(factory)


def _clear_owned_test_facts(engine: Engine) -> None:
    """仅回收本测试的固定事实，避免污染同一临时库中的后续迁移用例。"""

    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE ai_call_logs DISABLE TRIGGER USER")
        connection.exec_driver_sql("ALTER TABLE outbox_events DISABLE TRIGGER USER")
        try:
            connection.execute(delete(AiCallLog).where(AiCallLog.id.in_(_EVENT_IDS)))
            connection.execute(delete(OutboxEvent).where(OutboxEvent.event_id.in_(_EVENT_IDS)))
        finally:
            connection.exec_driver_sql("ALTER TABLE outbox_events ENABLE TRIGGER USER")
            connection.exec_driver_sql("ALTER TABLE ai_call_logs ENABLE TRIGGER USER")
        connection.execute(delete(Organization).where(Organization.id == _ORGANIZATION_ID))


def _limits(
    *,
    max_attempts: int = 6,
    max_input_tokens: int = 32_768,
    max_output_tokens: int = 2_500,
    max_total_tokens: int = 212_000,
    max_cost_micro_usd: int = 500_000,
) -> AiCallAuditLimits:
    return AiCallAuditLimits(
        max_provider_attempts_per_business_operation=max_attempts,
        max_input_tokens_per_request=max_input_tokens,
        max_output_tokens_per_request=max_output_tokens,
        max_total_tokens=max_total_tokens,
        max_cost_micro_usd=max_cost_micro_usd,
    )


def test_durable_reserve_complete_projection_query_and_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service = _setup(monkeypatch)
    base_time = datetime.now(timezone.utc) - timedelta(seconds=5)
    started = _started(_EVENT_1, started_at=base_time)
    completed = _completed(_EVENT_1, completed_at=base_time + timedelta(milliseconds=750))
    deadline = monotonic() + 30

    try:
        sink = DurableAiCallEventSink(
            service,
            reserve_context_factory=lambda event: AiCallReserveContext(
                limits=_limits(),
                deadline_monotonic=deadline,
            ),
        )
        started_sink_event = SinkEvent(started)
        scope = sink.create_call_scope(started_sink_event)
        reserved = run_async(sink.reserve_attempt(started_sink_event, scope))
        assert reserved.status is ReserveAttemptStatus.RESERVED_NEW
        assert reserved.permit is not None
        reserved.permit.consume()

        restarted_sink = DurableAiCallEventSink(
            service,
            reserve_context_factory=lambda event: AiCallReserveContext(
                limits=_limits(),
                deadline_monotonic=deadline,
            ),
        )
        restarted_scope = restarted_sink.create_call_scope(started_sink_event)
        replayed = run_async(restarted_sink.reserve_attempt(started_sink_event, restarted_scope))
        assert replayed.status is ReserveAttemptStatus.REPLAYED_SAME
        assert replayed.permit is None
        conflicting_started = _started(
            _EVENT_1,
            started_at=base_time,
            reserved_input_tokens=129,
        )
        assert (
            service.reserve_attempt(
                conflicting_started,
                _limits(),
                deadline_monotonic=deadline,
            )
            is AiCallReserveStatus.CONFLICT
        )

        completed_decision = run_async(sink.complete_attempt(SinkEvent(completed), scope))
        assert completed_decision.status is CompleteAttemptStatus.COMPLETED_NEW
        assert completed_decision.permit is not None
        completed_decision.permit.consume()
        assert service.complete_attempt(completed) is AiCallCompleteStatus.REPLAYED_SAME
        assert (
            service.complete_attempt(
                _completed(
                    _EVENT_1,
                    completed_at=base_time + timedelta(milliseconds=751),
                    duration_ms=751,
                )
            )
            is AiCallCompleteStatus.CONFLICT
        )

        first_projection = service.project_once()
        second_projection = service.project_once()
        assert first_projection.status is AiCallProjectionStatus.PROJECTED
        assert first_projection.event_type == "ai.call.started"
        assert second_projection.status is AiCallProjectionStatus.PROJECTED
        assert second_projection.event_type == "ai.call.completed"

        summary = service.get_operation_summary(_ORGANIZATION_ID, _OPERATION_ID)
        assert summary is not None
        assert summary.attempt_count == 1
        assert summary.reserved_input_tokens == 128
        assert summary.reserved_output_tokens == 2_500
        assert summary.reserved_cost_micro_usd == 0
        assert summary.actual_input_tokens == 128
        assert summary.actual_output_tokens == 96
        assert tuple(attempt.status for attempt in summary.attempts) == ("succeeded",)

        expired_operation = UUID("33333333-3333-4333-8333-333333333334")
        expired_started = _started(
            _EVENT_2,
            operation_id=expired_operation,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert (
            service.reserve_attempt(
                expired_started,
                _limits(),
                deadline_monotonic=monotonic() + 30,
            )
            is AiCallReserveStatus.RESERVED_NEW
        )
        assert service.project_once().event_type == "ai.call.started"

        reconciled = service.reconcile_once(
            {
                "contract_field_extraction": 120,
                "embedding": 30,
                "invoice_field_extraction": 60,
                "rag_answer": 90,
                "report_draft": 90,
                "risk_explanation": 60,
            }
        )
        assert reconciled.status is AiCallReconcileStatus.OUTCOME_UNKNOWN
        assert reconciled.event_id == _EVENT_2

        late = _late(
            _EVENT_2,
            operation_id=expired_operation,
            completed_at=datetime.now(timezone.utc),
        )
        assert service.complete_attempt(late) is AiCallCompleteStatus.LATE_RECORDED
        late_projection = service.project_once()
        assert late_projection.status is AiCallProjectionStatus.LATE_RECORDED

        expired_summary = service.get_operation_summary(_ORGANIZATION_ID, expired_operation)
        assert expired_summary is not None
        assert tuple(attempt.status for attempt in expired_summary.attempts) == ("outcome_unknown",)

        with factory.begin() as session:
            assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 5
            assert session.scalar(select(func.count()).select_from(AiCallLog)) == 2

        concurrent_operation = UUID("33333333-3333-4333-8333-333333333335")
        concurrent_time = datetime.now(timezone.utc)
        first = _started(
            _EVENT_3,
            operation_id=concurrent_operation,
            started_at=concurrent_time,
            reserved_output_tokens=0,
        )
        second = _started(
            _EVENT_4,
            operation_id=concurrent_operation,
            attempt_no=2,
            started_at=concurrent_time + timedelta(microseconds=1),
            reserved_output_tokens=0,
        )
        single_attempt = _limits(max_attempts=1, max_total_tokens=128)
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = tuple(
                executor.map(
                    lambda event: service.reserve_attempt(
                        event,
                        single_attempt,
                        deadline_monotonic=monotonic() + 30,
                    ),
                    (first, second),
                )
            )
        assert sorted(status.value for status in statuses) == [
            "budget_exhausted",
            "reserved_new",
        ]

        winning_event = first if statuses[0] is AiCallReserveStatus.RESERVED_NEW else second
        completion = _completed(
            UUID(winning_event.event_id),
            operation_id=concurrent_operation,
            completed_at=concurrent_time + timedelta(seconds=1),
            duration_ms=1_000,
        )
        with pytest.raises(RuntimeError, match="ROLLBACK_BUSINESS_WRITE"):
            with factory.begin() as session:
                repository = AiCallAuditRepository(session)
                assert repository.append_completion(completion) is (
                    AiCallCompleteStatus.COMPLETED_NEW
                )
                raise RuntimeError("ROLLBACK_BUSINESS_WRITE")

        with factory.begin() as session:
            completed_count = session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.event_id == UUID(winning_event.event_id),
                    OutboxEvent.event_type == "ai.call.completed",
                )
            )
            assert completed_count == 0

        # 投影 claim、日志写入和 published 标记必须同事务；消费者崩溃后由新实例重放。
        with pytest.raises(RuntimeError, match="SYNTHETIC_CONSUMER_CRASH"):
            with factory.begin() as session:
                projected = AiCallAuditRepository(session).project_next()
                assert projected.status is AiCallProjectionStatus.PROJECTED
                assert projected.event_id == UUID(winning_event.event_id)
                raise RuntimeError("SYNTHETIC_CONSUMER_CRASH")

        with factory.begin() as session:
            winning_outbox = session.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.event_id == UUID(winning_event.event_id),
                    OutboxEvent.event_type == "ai.call.started",
                )
            )
            assert winning_outbox is not None
            assert winning_outbox.status == "pending"
            assert session.get(AiCallLog, UUID(winning_event.event_id)) is None

        restarted_service = AiCallAuditService(factory)
        assert (
            restarted_service.reserve_attempt(
                winning_event,
                single_attempt,
                deadline_monotonic=monotonic() + 30,
            )
            is AiCallReserveStatus.REPLAYED_SAME
        )
        recovered_projection = restarted_service.project_once()
        assert recovered_projection.status is AiCallProjectionStatus.PROJECTED
        assert recovered_projection.event_id == UUID(winning_event.event_id)

        # sequence 2 先可见时必须等待，sequence 1 投影后再按序消费。
        out_of_order_operation = UUID("33333333-3333-4333-8333-333333333336")
        out_of_order_started = _started(
            _EVENT_5,
            operation_id=out_of_order_operation,
            started_at=datetime.now(timezone.utc),
        )
        out_of_order_completed = _completed(
            _EVENT_5,
            operation_id=out_of_order_operation,
            completed_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            duration_ms=1_000,
        )
        with factory.begin() as session:
            session.add(_outbox(out_of_order_completed))
        assert restarted_service.project_once().status is AiCallProjectionStatus.IDLE
        assert (
            restarted_service.reserve_attempt(
                out_of_order_started,
                _limits(),
                deadline_monotonic=monotonic() + 30,
            )
            is AiCallReserveStatus.RESERVED_NEW
        )
        assert restarted_service.project_once().event_type == "ai.call.started"
        assert restarted_service.project_once().event_type == "ai.call.completed"

        # 未知版本与不可解析载荷只能隔离，不能创建或覆盖审计事实。
        unknown_version_started = _started(
            _EVENT_6,
            operation_id=UUID("33333333-3333-4333-8333-333333333337"),
            started_at=datetime.now(timezone.utc),
        )
        malformed_started = _started(
            _EVENT_7,
            operation_id=UUID("33333333-3333-4333-8333-333333333338"),
            started_at=datetime.now(timezone.utc),
        )
        malformed_payload = json.loads(malformed_started.canonical_payload())
        assert isinstance(malformed_payload, dict)
        malformed_payload.pop("model_id")
        with factory.begin() as session:
            session.add(_outbox(unknown_version_started, event_version=3))
            session.add(
                _outbox(
                    malformed_started,
                    payload=cast(dict[str, object], malformed_payload),
                )
            )

        unknown_projection = restarted_service.project_once()
        malformed_projection = restarted_service.project_once()
        assert unknown_projection.status is AiCallProjectionStatus.DEAD_LETTER
        assert malformed_projection.status is AiCallProjectionStatus.DEAD_LETTER
        assert {unknown_projection.event_id, malformed_projection.event_id} == {
            _EVENT_6,
            _EVENT_7,
        }
        with factory.begin() as session:
            isolated = tuple(
                session.execute(
                    select(OutboxEvent.event_id, OutboxEvent.last_error)
                    .where(OutboxEvent.event_id.in_((_EVENT_6, _EVENT_7)))
                    .order_by(OutboxEvent.event_id.asc())
                )
            )
            assert isolated == (
                (_EVENT_6, "UNSUPPORTED_EVENT_VERSION"),
                (_EVENT_7, "SERIALIZATION_FAILED"),
            )
            assert session.get(AiCallLog, _EVENT_6) is None
            assert session.get(AiCallLog, _EVENT_7) is None

        # 持久 reserve 必须分别守住费用、总 Token、单请求 Token 与 deadline 边界。
        cost_operation = UUID("33333333-3333-4333-8333-333333333339")
        cost_limits = _limits(
            max_attempts=3,
            max_total_tokens=256,
            max_cost_micro_usd=500,
        )
        assert (
            restarted_service.reserve_attempt(
                _started(
                    _EVENT_8,
                    operation_id=cost_operation,
                    attempt_no=1,
                    started_at=datetime.now(timezone.utc),
                    reserved_input_tokens=128,
                    reserved_output_tokens=0,
                    reserved_cost_micro_usd=300,
                ),
                cost_limits,
                deadline_monotonic=monotonic() + 30,
            )
            is AiCallReserveStatus.RESERVED_NEW
        )
        assert (
            restarted_service.reserve_attempt(
                _started(
                    _EVENT_9,
                    operation_id=cost_operation,
                    attempt_no=2,
                    started_at=datetime.now(timezone.utc),
                    reserved_input_tokens=128,
                    reserved_output_tokens=0,
                    reserved_cost_micro_usd=200,
                ),
                cost_limits,
                deadline_monotonic=monotonic() + 30,
            )
            is AiCallReserveStatus.RESERVED_NEW
        )
        assert (
            restarted_service.reserve_attempt(
                _started(
                    _EVENT_10,
                    operation_id=cost_operation,
                    attempt_no=3,
                    started_at=datetime.now(timezone.utc),
                    reserved_input_tokens=0,
                    reserved_output_tokens=0,
                    reserved_cost_micro_usd=1,
                ),
                cost_limits,
                deadline_monotonic=monotonic() + 30,
            )
            is AiCallReserveStatus.BUDGET_EXHAUSTED
        )

        token_operation = UUID("33333333-3333-4333-8333-333333333340")
        token_limits = _limits(max_attempts=2, max_total_tokens=256)
        assert (
            restarted_service.reserve_attempt(
                _started(
                    _EVENT_11,
                    operation_id=token_operation,
                    attempt_no=1,
                    started_at=datetime.now(timezone.utc),
                    reserved_input_tokens=128,
                    reserved_output_tokens=0,
                ),
                token_limits,
                deadline_monotonic=monotonic() + 30,
            )
            is AiCallReserveStatus.RESERVED_NEW
        )
        assert (
            restarted_service.reserve_attempt(
                _started(
                    _EVENT_12,
                    operation_id=token_operation,
                    attempt_no=2,
                    started_at=datetime.now(timezone.utc),
                    reserved_input_tokens=129,
                    reserved_output_tokens=0,
                ),
                token_limits,
                deadline_monotonic=monotonic() + 30,
            )
            is AiCallReserveStatus.BUDGET_EXHAUSTED
        )

        request_operation = UUID("33333333-3333-4333-8333-333333333341")
        request_limits = _limits(max_total_tokens=100_000)
        for rejected_event in (
            _started(
                _EVENT_13,
                operation_id=request_operation,
                attempt_no=1,
                started_at=datetime.now(timezone.utc),
                reserved_input_tokens=32_769,
                reserved_output_tokens=0,
            ),
            _started(
                _EVENT_14,
                operation_id=request_operation,
                attempt_no=2,
                started_at=datetime.now(timezone.utc),
                reserved_input_tokens=0,
                reserved_output_tokens=2_501,
            ),
        ):
            assert (
                restarted_service.reserve_attempt(
                    rejected_event,
                    request_limits,
                    deadline_monotonic=monotonic() + 30,
                )
                is AiCallReserveStatus.BUDGET_EXHAUSTED
            )

        assert (
            restarted_service.reserve_attempt(
                _started(
                    _EVENT_15,
                    operation_id=UUID("33333333-3333-4333-8333-333333333342"),
                    started_at=datetime.now(timezone.utc),
                    reserved_input_tokens=0,
                    reserved_output_tokens=0,
                ),
                _limits(),
                deadline_monotonic=monotonic(),
            )
            is AiCallReserveStatus.DEADLINE_EXHAUSTED
        )
    finally:
        _clear_owned_test_facts(engine)
        engine.dispose()


def test_event_v2_cny_projection_and_operation_currency_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _, service = _setup(monkeypatch)
    operation_id = UUID("33333333-3333-4333-8333-333333333343")
    started_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    started = _started_v2(
        _EVENT_16,
        operation_id=operation_id,
        started_at=started_at,
    )
    limits = AiCallAuditLimitsV2(
        max_provider_attempts_per_business_operation=2,
        max_input_tokens_per_request=100,
        max_output_tokens_per_request=0,
        max_total_tokens=100,
        cost_currency="CNY",
        max_cost_microunits=100,
    )

    try:
        assert (
            service.reserve_attempt(
                started,
                limits,
                deadline_monotonic=monotonic() + 30,
            )
            is AiCallReserveStatus.RESERVED_NEW
        )
        assert service.project_once().status is AiCallProjectionStatus.PROJECTED

        mixed_currency = _started_v2(
            _EVENT_17,
            operation_id=operation_id,
            started_at=started_at + timedelta(microseconds=1),
            currency="USD",
        )
        usd_limits = AiCallAuditLimitsV2(
            max_provider_attempts_per_business_operation=2,
            max_input_tokens_per_request=100,
            max_output_tokens_per_request=0,
            max_total_tokens=100,
            cost_currency="USD",
            max_cost_microunits=100,
        )
        assert (
            service.reserve_attempt(
                mixed_currency,
                usd_limits,
                deadline_monotonic=monotonic() + 30,
            )
            is AiCallReserveStatus.CONFLICT
        )

        completed = _completed_v2(
            _EVENT_16,
            operation_id=operation_id,
            completed_at=started_at + timedelta(seconds=1),
        )
        assert service.complete_attempt(completed) is AiCallCompleteStatus.COMPLETED_NEW
        assert service.project_once().status is AiCallProjectionStatus.PROJECTED

        summary = service.get_operation_summary(_ORGANIZATION_ID, operation_id)
        assert summary is not None
        assert summary.attempt_count == 1
        assert summary.reserved_cost_micro_usd is None
        assert summary.cost_currency == "CNY"
        assert summary.reserved_cost_microunits == 10
        assert summary.actual_cost_microunits == 7
        assert summary.attempts[0].event_version == 2
        assert summary.attempts[0].reserved_cost_micro_usd is None
        assert summary.attempts[0].cost_currency == "CNY"
        assert summary.attempts[0].actual_cost_microunits == 7
    finally:
        _clear_owned_test_facts(engine)
        engine.dispose()
