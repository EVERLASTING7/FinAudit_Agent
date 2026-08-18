from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.ai.events import (
    AiCallCompletedV2,
    AiCallEventConflictError,
    AiCallStartedV2,
    parse_ai_call_event,
    validate_ai_call_event_chain_v2,
    validate_ai_call_event_v1,
    validate_ai_call_event_v2,
)

_EVENT_ID = "11111111-1111-4111-8111-111111111111"
_ORG_ID = "22222222-2222-4222-8222-222222222222"
_OPERATION_ID = "33333333-3333-4333-8333-333333333333"
_TRACE_ID = "44444444-4444-4444-8444-444444444444"
_HASH = "a" * 64


def _started(*, currency: str | None = "CNY") -> dict[str, object]:
    return {
        "event_id": _EVENT_ID,
        "event_version": 2,
        "event_sequence": 1,
        "event_type": "ai.call.started",
        "aggregate_type": "ai_call",
        "aggregate_id": _EVENT_ID,
        "organization_id": _ORG_ID,
        "business_operation_id": _OPERATION_ID,
        "job_id": None,
        "request_id": None,
        "resource_type": "knowledge_index",
        "resource_id": None,
        "trace_id": _TRACE_ID,
        "call_type": "embedding",
        "logical_generation_no": 1,
        "provider_attempt_no": 1,
        "adapter_id": "openai_embeddings_v1",
        "endpoint_id": "synthetic-endpoint-v1",
        "model_id": "synthetic-embedding",
        "model_version": None,
        "prompt_id": None,
        "prompt_version": None,
        "prompt_hash": None,
        "schema_version": None,
        "policy_version": 2,
        "policy_hash": _HASH,
        "pricing_version": "synthetic-cny-v2",
        "input_hash": _HASH,
        "reserved_input_tokens": 20,
        "reserved_output_tokens": 0,
        "cost_currency": currency,
        "reserved_cost_microunits": 10 if currency is not None else 0,
        "attempt_count": 1,
        "is_fallback": False,
        "breaker_state": "closed",
        "status": "pending",
        "started_at": "2026-08-17T01:02:03.000000Z",
    }


def _completed(*, currency: str | None = "CNY") -> dict[str, object]:
    return {
        "event_id": _EVENT_ID,
        "event_version": 2,
        "event_sequence": 2,
        "event_type": "ai.call.completed",
        "aggregate_type": "ai_call",
        "aggregate_id": _EVENT_ID,
        "organization_id": _ORG_ID,
        "business_operation_id": _OPERATION_ID,
        "job_id": None,
        "request_id": None,
        "trace_id": _TRACE_ID,
        "policy_version": 2,
        "policy_hash": _HASH,
        "cost_currency": currency,
        "actual_cost_microunits": 7 if currency is not None else 0,
        "status": "succeeded",
        "completed_at": "2026-08-17T01:02:04.000000Z",
        "duration_ms": 1000,
        "output_hash": _HASH,
        "input_tokens": 14,
        "output_tokens": 0,
        "vector_count": 2,
        "http_status": 200,
        "error_category": None,
        "safe_error_code": None,
        "citation_validation_status": None,
    }


def test_v2_dispatch_is_explicit_and_v1_rejects_v2() -> None:
    started = validate_ai_call_event_v2(_started())

    assert isinstance(started, AiCallStartedV2)
    assert isinstance(parse_ai_call_event(started.canonical_payload()), AiCallStartedV2)
    with pytest.raises(ValidationError):
        validate_ai_call_event_v1(_started())


def test_v2_currency_and_actual_cost_are_chain_bound() -> None:
    started = validate_ai_call_event_v2(_started())
    completed = validate_ai_call_event_v2(_completed())
    assert isinstance(started, AiCallStartedV2)
    assert isinstance(completed, AiCallCompletedV2)

    validate_ai_call_event_chain_v2(started, completed)

    mixed = deepcopy(_completed())
    mixed["cost_currency"] = "USD"
    with pytest.raises(AiCallEventConflictError):
        validate_ai_call_event_chain_v2(
            started,
            validate_ai_call_event_v2(mixed),  # type: ignore[arg-type]
        )


def test_v2_preserves_authoritative_actual_cost_above_reservation() -> None:
    completed_payload = _completed()
    completed_payload["actual_cost_microunits"] = 11
    started = validate_ai_call_event_v2(_started())
    completed = validate_ai_call_event_v2(completed_payload)
    assert isinstance(started, AiCallStartedV2)
    assert isinstance(completed, AiCallCompletedV2)

    validate_ai_call_event_chain_v2(started, completed)
    assert completed.actual_cost_microunits == 11


def test_internal_unmetered_v2_uses_null_currency_and_zero_cost() -> None:
    started = validate_ai_call_event_v2(_started(currency=None))
    completed = validate_ai_call_event_v2(_completed(currency=None))
    assert isinstance(started, AiCallStartedV2)
    assert isinstance(completed, AiCallCompletedV2)
    validate_ai_call_event_chain_v2(started, completed)

    invalid = _started(currency=None)
    invalid["reserved_cost_microunits"] = 1
    with pytest.raises(ValidationError):
        validate_ai_call_event_v2(invalid)
