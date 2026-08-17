from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import copy, deepcopy
from pathlib import Path
from typing import TypeVar, cast

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.ai.event_sink import SinkEvent
from app.ai.events import (
    AiCallCompletedV1,
    AiCallEventConflictError,
    AiCallEventV1,
    AiCallLateCompletionV1,
    AiCallStartedV1,
    classify_ai_call_event_replay,
    parse_ai_call_event_v1,
    validate_ai_call_event_chain,
    validate_ai_call_event_v1,
)
from app.ai.policy import canonicalize_jcs

_ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[3] / "docs" / "change-requests" / "artifacts" / "CR-011"
)
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_UUID_OTHER = "99999999-9999-4999-8999-999999999999"
_ModelT = TypeVar("_ModelT", bound=BaseModel)

_VECTOR_EXPECTATIONS = (
    (
        "ai-call-event-v1.started.json",
        AiCallStartedV1,
        1439,
        "8e3411604cda9df587e135ae19444088f5226c06fb28a7336cc6f19d597be538",
    ),
    (
        "ai-call-event-v1.started-outcome-unknown.json",
        AiCallStartedV1,
        1439,
        "aa3cd54d701ed151e83fb94e05457de6f28094f322c1932541e72481829928d0",
    ),
    (
        "ai-call-event-v1.completed.json",
        AiCallCompletedV1,
        904,
        "929634ee88ae21cede551c753cbc3997b6a6e06f2b7371554db285ea8a132ed5",
    ),
    (
        "ai-call-event-v1.completed-failed.json",
        AiCallCompletedV1,
        790,
        "7d24ecbd8c3e5dad40e3853e444be98c6a78cd5db50bf89d8ffed77ac8f798a0",
    ),
    (
        "ai-call-event-v1.completed-degraded.json",
        AiCallCompletedV1,
        797,
        "4625d5977209829664e35a5d573aecf6a2c5bd6f07699569ad08ed994a3f3aac",
    ),
    (
        "ai-call-event-v1.completed-rejected.json",
        AiCallCompletedV1,
        857,
        "26332fc61a97676e04f6709dee09584bf72a58a7dad416fba969a4b43a5991f5",
    ),
    (
        "ai-call-event-v1.completed-outcome-unknown.json",
        AiCallCompletedV1,
        859,
        "61a5dbb6d3efdc9d702742af11495b0edf591015cf8b48c66dea4a737db8de98",
    ),
    (
        "ai-call-event-v1.late.json",
        AiCallLateCompletionV1,
        886,
        "12274499702df844b2680063f3b08628c9141db4be43afb0e4c701f3441a4518",
    ),
)


def _raw(name: str) -> bytes:
    return (_ARTIFACT_ROOT / name).read_bytes()


def _payload(name: str) -> dict[str, object]:
    value = json.loads(_raw(name))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _render_validation_error(error: ValidationError) -> str:
    return "\n".join(
        (
            str(error),
            json.dumps(error.errors(), ensure_ascii=False, default=str),
            error.json(),
        )
    )


def _unsafe_construct_for_attack(model_type: type[_ModelT], payload: dict[str, object]) -> _ModelT:
    construct = cast(Callable[..., _ModelT], model_type.model_construct)
    return construct(**payload)


def _assert_invalid_event_boundaries_are_redacted(
    event: AiCallStartedV1,
    valid: AiCallStartedV1,
    sentinel: str,
) -> None:
    operations: tuple[Callable[[], object], ...] = (
        event.canonical_payload,
        event.payload_sha256,
        lambda: event.replay_key,
        lambda: classify_ai_call_event_replay(valid, event),
    )
    for operation in operations:
        with pytest.raises(ValidationError) as exc_info:
            operation()
        assert sentinel not in _render_validation_error(exc_info.value)


def _assert_tampered_late_projection_is_rejected(
    event: AiCallLateCompletionV1,
    reference: AiCallLateCompletionV1,
) -> None:
    operations: tuple[Callable[[], object], ...] = (
        event.canonical_payload,
        event.payload_sha256,
        lambda: event.replay_key,
        lambda: validate_ai_call_event_v1(event),
        lambda: classify_ai_call_event_replay(reference, event),
        lambda: SinkEvent(event),
    )
    for operation in operations:
        with pytest.raises(ValidationError, match="AiCallEventV1 validation failed"):
            operation()


@pytest.mark.parametrize(("name", "expected_type", "jcs_size", "jcs_sha256"), _VECTOR_EXPECTATIONS)
def test_fixed_event_vectors_match_exact_jcs_projection(
    name: str,
    expected_type: type[object],
    jcs_size: int,
    jcs_sha256: str,
) -> None:
    source = _payload(name)

    event = parse_ai_call_event_v1(_raw(name))

    assert isinstance(event, expected_type)
    assert event.model_dump(mode="json", exclude_unset=True) == source
    assert event.canonical_payload() == canonicalize_jcs(source)
    assert len(event.canonical_payload()) == jcs_size
    assert event.payload_sha256() == jcs_sha256
    assert hashlib.sha256(event.canonical_payload()).hexdigest() == jcs_sha256


def test_event_is_frozen_and_closed() -> None:
    event = parse_ai_call_event_v1(_raw("ai-call-event-v1.started.json"))
    assert isinstance(event, AiCallStartedV1)
    payload = _payload("ai-call-event-v1.started.json")
    payload["api_key"] = "synthetic-secret"
    sentinel = "synthetic-mutation-must-never-be-rendered"

    with pytest.raises(ValidationError, match="AiCallEventV1 validation failed") as exc_info:
        event.model_id = sentinel  # type: ignore[misc]
    rendered = "\n".join(
        (
            str(exc_info.value),
            json.dumps(exc_info.value.errors(), ensure_ascii=False, default=str),
            exc_info.value.json(),
        )
    )
    assert sentinel not in rendered
    with pytest.raises(ValidationError, match="AiCallEventV1 validation failed"):
        validate_ai_call_event_v1(payload)


def test_event_copy_entrypoints_cannot_bypass_validation() -> None:
    event = parse_ai_call_event_v1(_raw("ai-call-event-v1.started.json"))
    assert isinstance(event, AiCallStartedV1)
    sentinel = "synthetic-copy-update-must-never-be-rendered"

    with pytest.raises(TypeError, match="model_copy is forbidden") as model_copy_error:
        event.model_copy(update={"model_id": sentinel})
    with pytest.raises(TypeError, match="model_copy is forbidden"):
        event.model_copy()
    with pytest.raises(TypeError, match="copy is forbidden") as copy_error:
        event.copy(update={"model_id": sentinel})
    with pytest.raises(TypeError, match="copy is forbidden"):
        copy(event)
    with pytest.raises(TypeError, match="copy is forbidden"):
        deepcopy(event)
    with pytest.raises(TypeError, match="copy is forbidden"):
        event.__replace__(model_id=sentinel)

    assert sentinel not in str(model_copy_error.value)
    assert sentinel not in str(copy_error.value)


def test_event_fields_set_projection_is_read_only_and_tamper_evident() -> None:
    late_payload = _payload("ai-call-event-v1.late.json")
    del late_payload["duration_ms"]
    late = AiCallLateCompletionV1.model_validate(late_payload)
    canonical_before = late.canonical_payload()

    fields_snapshot: object = late.model_fields_set
    assert type(fields_snapshot) is frozenset
    with pytest.raises(AttributeError):
        cast(set[str], fields_snapshot).add("duration_ms")
    assert late.canonical_payload() == canonical_before

    late.__pydantic_fields_set__.add("duration_ms")
    with pytest.raises(ValidationError, match="AiCallEventV1 validation failed"):
        late.canonical_payload()

    completed = AiCallCompletedV1.model_validate(_payload("ai-call-event-v1.completed.json"))
    completed.__pydantic_fields_set__.remove("duration_ms")
    with pytest.raises(ValidationError, match="AiCallEventV1 validation failed"):
        completed.payload_sha256()


def test_late_omit_null_projection_cannot_be_synchronized_through_instance_state() -> None:
    trusted_attribute = "_trusted_fields_set"
    omitted_payload = _payload("ai-call-event-v1.late.json")
    del omitted_payload["duration_ms"]
    omitted = AiCallLateCompletionV1.model_validate(omitted_payload)
    omitted_reference = AiCallLateCompletionV1.model_validate(omitted_payload)
    forged_present = frozenset((*omitted.model_fields_set, "duration_ms"))

    with pytest.raises(TypeError, match="trusted projection is immutable"):
        setattr(omitted, trusted_attribute, forged_present)
    omitted.__pydantic_fields_set__.add("duration_ms")
    _assert_tampered_late_projection_is_rejected(omitted, omitted_reference)

    explicit_null = AiCallLateCompletionV1.model_validate(_payload("ai-call-event-v1.late.json"))
    explicit_null_reference = AiCallLateCompletionV1.model_validate(
        _payload("ai-call-event-v1.late.json")
    )
    forged_omitted = frozenset(
        name for name in explicit_null.model_fields_set if name != "vector_count"
    )

    with pytest.raises(TypeError, match="trusted projection is immutable"):
        setattr(explicit_null, trusted_attribute, forged_omitted)
    explicit_null.__pydantic_fields_set__.remove("vector_count")
    _assert_tampered_late_projection_is_rejected(explicit_null, explicit_null_reference)

    started = AiCallStartedV1.model_validate(
        _payload("ai-call-event-v1.started-outcome-unknown.json")
    )
    completed = AiCallCompletedV1.model_validate(
        _payload("ai-call-event-v1.completed-outcome-unknown.json")
    )
    for tampered in (omitted, explicit_null):
        with pytest.raises(AiCallEventConflictError, match="AI_CALL_EVENT_CONFLICT"):
            validate_ai_call_event_chain(started, completed, tampered)


def test_untrusted_construct_and_base_copy_are_revalidated_at_public_boundaries() -> None:
    payload = _payload("ai-call-event-v1.started.json")
    sentinel = "SYNTHETIC_COPY_VALUE_MUST_NOT_BE_RENDERED"
    valid = AiCallStartedV1.model_validate(payload)
    unsafe_construct = _unsafe_construct_for_attack(
        AiCallStartedV1,
        payload | {"attempt_count": 2, "model_id": sentinel},
    )
    with pytest.warns(DeprecationWarning):
        unsafe_copy = BaseModel.copy(
            valid,
            update={"attempt_count": 2, "model_id": sentinel},
        )

    for event in (unsafe_construct, unsafe_copy):
        _assert_invalid_event_boundaries_are_redacted(event, valid, sentinel)

    with pytest.warns(DeprecationWarning):
        valid_copy = BaseModel.copy(valid, update={"model_id": sentinel})
    _assert_invalid_event_boundaries_are_redacted(valid_copy, valid, sentinel)


def test_only_supported_validation_entries_can_construct_events_without_leaking() -> None:
    sentinel = "SYNTHETIC_UNBOUND_ENTRY_MUST_NOT_BE_RENDERED"
    payload = _payload("ai-call-event-v1.started.json")
    payload["event_type"] = sentinel
    payload[sentinel] = "synthetic-value"
    raw = json.dumps(payload)
    unbound_validate = cast(
        Callable[..., object], BaseModel.model_validate.__getattribute__("__func__")
    )
    unbound_validate_json = cast(
        Callable[..., object], BaseModel.model_validate_json.__getattribute__("__func__")
    )
    unsupported_entries: tuple[Callable[[], object], ...] = (
        lambda: unbound_validate(
            AiCallStartedV1,
            payload,
            strict=False,
            extra="allow",
            from_attributes=True,
        ),
        lambda: TypeAdapter(AiCallStartedV1).validate_python(
            payload,
            strict=False,
            extra="allow",
            from_attributes=True,
        ),
        lambda: TypeAdapter(AiCallEventV1).validate_python(
            payload,
            strict=False,
            extra="allow",
            from_attributes=True,
        ),
        lambda: unbound_validate_json(
            AiCallStartedV1,
            raw,
            strict=False,
            extra="allow",
        ),
        lambda: TypeAdapter(AiCallEventV1).validate_json(
            raw,
            strict=False,
            extra="allow",
        ),
    )

    for entry in unsupported_entries:
        with pytest.raises(ValidationError) as exc_info:
            entry()
        rendered = _render_validation_error(exc_info.value)
        assert "AiCallEventV1 validation failed" in rendered
        assert sentinel not in rendered

    supported = validate_ai_call_event_v1(_payload("ai-call-event-v1.started.json"))
    assert isinstance(supported, AiCallStartedV1)
    assert validate_ai_call_event_v1(supported).canonical_payload() == supported.canonical_payload()


def test_json_mathematical_integer_spellings_are_canonicalized() -> None:
    raw = _raw("ai-call-event-v1.started.json").decode()
    raw = raw.replace('"event_version": 1', '"event_version": 1.0', 1)
    raw = raw.replace('"event_sequence": 1', '"event_sequence": 1e0', 1)
    raw = raw.replace('"reserved_cost_micro_usd": 0', '"reserved_cost_micro_usd": -0.0', 1)

    event = parse_ai_call_event_v1(raw)

    assert event.event_version == 1
    assert event.event_sequence == 1
    assert event.reserved_cost_micro_usd == 0
    assert b'"event_sequence":1' in event.canonical_payload()
    assert b'"reserved_cost_micro_usd":0' in event.canonical_payload()


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("policy_version", True),
        ("policy_version", "1"),
        ("policy_version", 1.5),
        ("policy_version", 0),
        ("reserved_input_tokens", -1),
        ("reserved_input_tokens", _MAX_SAFE_INTEGER + 1),
    ],
)
def test_event_rejects_non_safe_or_non_positive_integers(field: str, invalid: object) -> None:
    payload = _payload("ai-call-event-v1.started.json")
    payload[field] = invalid

    with pytest.raises(ValidationError):
        AiCallStartedV1.model_validate(payload)


def test_json_decimal_that_only_rounds_to_an_integer_is_rejected() -> None:
    raw = (
        _raw("ai-call-event-v1.started.json")
        .decode()
        .replace(
            '"policy_version": 1',
            '"policy_version": 1.0000000000000000000000001',
            1,
        )
    )

    with pytest.raises(ValidationError):
        parse_ai_call_event_v1(raw)


def test_started_embedding_matrix_and_attempt_identity() -> None:
    payload = _payload("ai-call-event-v1.started.json")
    payload.update(
        {
            "call_type": "embedding",
            "adapter_id": "openai_embeddings_v1",
            "prompt_id": None,
            "prompt_version": None,
            "prompt_hash": None,
            "schema_version": None,
        }
    )

    event = AiCallStartedV1.model_validate(payload)
    assert event.call_type == "embedding"

    payload["prompt_id"] = "must-stay-null"
    with pytest.raises(ValidationError, match="AiCallEventV1 validation failed"):
        AiCallStartedV1.model_validate(payload)

    payload = _payload("ai-call-event-v1.started.json")
    payload["attempt_count"] = 2
    with pytest.raises(ValidationError, match="AiCallEventV1 validation failed"):
        AiCallStartedV1.model_validate(payload)


@pytest.mark.parametrize(
    ("name", "field", "invalid"),
    [
        ("ai-call-event-v1.completed.json", "output_hash", None),
        ("ai-call-event-v1.completed-failed.json", "citation_validation_status", "invalid"),
        ("ai-call-event-v1.completed-degraded.json", "safe_error_code", None),
        ("ai-call-event-v1.completed-rejected.json", "error_category", None),
        ("ai-call-event-v1.completed-outcome-unknown.json", "input_tokens", 0),
    ],
)
def test_completed_status_nullability_matrix(name: str, field: str, invalid: object) -> None:
    payload = _payload(name)
    payload[field] = invalid

    with pytest.raises(ValidationError):
        AiCallCompletedV1.model_validate(payload)


def test_completed_nullable_fields_are_required() -> None:
    payload = _payload("ai-call-event-v1.completed.json")
    del payload["vector_count"]

    with pytest.raises(ValidationError, match="AiCallEventV1 validation failed"):
        AiCallCompletedV1.model_validate(payload)


def test_late_omitted_and_explicit_null_are_distinct_replay_payloads() -> None:
    omitted_payload = _payload("ai-call-event-v1.late.json")
    del omitted_payload["duration_ms"]
    explicit_null_payload = dict(omitted_payload) | {"duration_ms": None}

    omitted = AiCallLateCompletionV1.model_validate(omitted_payload)
    explicit_null = AiCallLateCompletionV1.model_validate(explicit_null_payload)

    assert "duration_ms" not in omitted.model_dump(mode="json", exclude_unset=True)
    assert explicit_null.model_dump(mode="json", exclude_unset=True)["duration_ms"] is None
    assert omitted.canonical_payload() != explicit_null.canonical_payload()
    assert classify_ai_call_event_replay(omitted, explicit_null) == "conflict"
    assert classify_ai_call_event_replay(omitted, omitted) == "replayed_same"


def test_replay_comparison_requires_the_same_identity() -> None:
    existing = parse_ai_call_event_v1(_raw("ai-call-event-v1.started.json"))
    candidate = parse_ai_call_event_v1(_raw("ai-call-event-v1.started-outcome-unknown.json"))

    with pytest.raises(ValueError, match="do not share a replay key"):
        classify_ai_call_event_replay(existing, candidate)


def test_valid_started_completed_and_late_chains() -> None:
    started = AiCallStartedV1.model_validate(_payload("ai-call-event-v1.started.json"))
    completed = AiCallCompletedV1.model_validate(_payload("ai-call-event-v1.completed.json"))
    unknown_started = AiCallStartedV1.model_validate(
        _payload("ai-call-event-v1.started-outcome-unknown.json")
    )
    unknown_completed = AiCallCompletedV1.model_validate(
        _payload("ai-call-event-v1.completed-outcome-unknown.json")
    )
    late = AiCallLateCompletionV1.model_validate(_payload("ai-call-event-v1.late.json"))

    validate_ai_call_event_chain(started, completed)
    validate_ai_call_event_chain(unknown_started, unknown_completed, late)


def test_chain_rejects_correlation_time_and_llm_vector_conflicts() -> None:
    started = AiCallStartedV1.model_validate(_payload("ai-call-event-v1.started.json"))
    payload = _payload("ai-call-event-v1.completed.json")

    payload["organization_id"] = _UUID_OTHER
    with pytest.raises(AiCallEventConflictError, match="AI_CALL_EVENT_CONFLICT"):
        validate_ai_call_event_chain(started, AiCallCompletedV1.model_validate(payload))

    payload = _payload("ai-call-event-v1.completed.json")
    payload["completed_at"] = "2026-08-07T05:59:59.999999Z"
    with pytest.raises(AiCallEventConflictError):
        validate_ai_call_event_chain(started, AiCallCompletedV1.model_validate(payload))

    payload = _payload("ai-call-event-v1.completed.json")
    payload["vector_count"] = 1
    with pytest.raises(AiCallEventConflictError):
        validate_ai_call_event_chain(started, AiCallCompletedV1.model_validate(payload))


def test_embedding_success_requires_zero_output_tokens_and_positive_vectors() -> None:
    started_payload = _payload("ai-call-event-v1.started.json")
    started_payload.update(
        {
            "call_type": "embedding",
            "adapter_id": "openai_embeddings_v1",
            "prompt_id": None,
            "prompt_version": None,
            "prompt_hash": None,
            "schema_version": None,
        }
    )
    completed_payload = _payload("ai-call-event-v1.completed.json")
    completed_payload.update({"output_tokens": 0, "vector_count": 1})
    started = AiCallStartedV1.model_validate(started_payload)
    completed = AiCallCompletedV1.model_validate(completed_payload)

    validate_ai_call_event_chain(started, completed)

    completed_payload["vector_count"] = 0
    with pytest.raises(AiCallEventConflictError):
        validate_ai_call_event_chain(
            started,
            AiCallCompletedV1.model_validate(completed_payload),
        )


def test_late_requires_an_authoritative_outcome_unknown_completion() -> None:
    started = AiCallStartedV1.model_validate(_payload("ai-call-event-v1.started.json"))
    completed = AiCallCompletedV1.model_validate(_payload("ai-call-event-v1.completed.json"))
    late_payload = _payload("ai-call-event-v1.late.json")
    for field in (
        "event_id",
        "aggregate_id",
        "organization_id",
        "business_operation_id",
        "job_id",
        "request_id",
        "trace_id",
        "policy_version",
        "policy_hash",
    ):
        late_payload[field] = getattr(started, field)
    late = AiCallLateCompletionV1.model_validate(late_payload)

    with pytest.raises(AiCallEventConflictError):
        validate_ai_call_event_chain(started, completed, late)


def test_chain_revalidates_untrusted_model_construct_projections() -> None:
    started_payload = _payload("ai-call-event-v1.started.json")
    completed_payload = _payload("ai-call-event-v1.completed.json")
    unsafe_started = _unsafe_construct_for_attack(
        AiCallStartedV1, started_payload | {"attempt_count": 2}
    )
    completed = AiCallCompletedV1.model_validate(completed_payload)

    with pytest.raises(AiCallEventConflictError):
        validate_ai_call_event_chain(unsafe_started, completed)

    sentinel = "SYNTHETIC_COMPLETION_VALUE_MUST_NOT_BE_RENDERED"
    started = AiCallStartedV1.model_validate(started_payload)
    unsafe_completed = _unsafe_construct_for_attack(
        AiCallCompletedV1,
        completed_payload | {"safe_error_code": sentinel},
    )
    with pytest.raises(AiCallEventConflictError) as completed_error:
        validate_ai_call_event_chain(started, unsafe_completed)
    assert sentinel not in str(completed_error.value)

    unknown_started = AiCallStartedV1.model_validate(
        _payload("ai-call-event-v1.started-outcome-unknown.json")
    )
    unknown_completed = AiCallCompletedV1.model_validate(
        _payload("ai-call-event-v1.completed-outcome-unknown.json")
    )
    late_payload = _payload("ai-call-event-v1.late.json")
    unsafe_late = _unsafe_construct_for_attack(
        AiCallLateCompletionV1, late_payload | {"event_sequence": 2}
    )
    with pytest.raises(AiCallEventConflictError):
        validate_ai_call_event_chain(unknown_started, unknown_completed, unsafe_late)


def test_event_json_rejects_duplicate_keys_before_validation() -> None:
    sentinel = "synthetic-secret-must-not-be-rendered"
    raw = (
        _raw("ai-call-event-v1.started.json")
        .decode()
        .replace(
            '"model_id": "synthetic-extraction-model",',
            f'"model_id": "{sentinel}", "model_id": "synthetic-extraction-model",',
            1,
        )
    )

    with pytest.raises(ValueError, match="duplicate JSON object key") as exc_info:
        parse_ai_call_event_v1(raw)

    assert sentinel not in str(exc_info.value)


@pytest.mark.parametrize("use_json", [False, True])
@pytest.mark.parametrize("error_source", ["value", "discriminator", "unknown_key"])
def test_event_validation_errors_remove_raw_inputs(use_json: bool, error_source: str) -> None:
    sentinel = f"synthetic-secret-{error_source}-must-never-be-rendered"
    payload = _payload("ai-call-event-v1.started.json")
    if error_source == "value":
        payload["api_key"] = sentinel
    elif error_source == "discriminator":
        payload["event_type"] = sentinel
    else:
        payload[sentinel] = "synthetic-value"

    with pytest.raises(ValidationError) as exc_info:
        if use_json:
            parse_ai_call_event_v1(json.dumps(payload))
        else:
            AiCallStartedV1.model_validate(payload)

    rendered = "\n".join(
        (
            str(exc_info.value),
            json.dumps(exc_info.value.errors(), ensure_ascii=False, default=str),
            exc_info.value.json(),
        )
    )
    assert sentinel not in rendered


def test_malformed_json_error_does_not_echo_source() -> None:
    sentinel = "synthetic-secret-must-never-be-rendered"

    with pytest.raises(ValueError, match="invalid AiCallEventV1 JSON") as exc_info:
        parse_ai_call_event_v1(f'{{"api_key":"{sentinel}",')

    assert sentinel not in str(exc_info.value)


def test_event_bytes_require_utf8_without_any_bom() -> None:
    sentinel = "synthetic-encoded-source-must-never-be-rendered"
    text = (
        _raw("ai-call-event-v1.started.json")
        .decode("utf-8")
        .replace(
            "synthetic-extraction-model",
            sentinel,
            1,
        )
    )
    invalid_sources = (
        b"\xff" + sentinel.encode("utf-8"),
        b"\xef\xbb\xbf" + text.encode("utf-8"),
        text.encode("utf-16"),
        text.encode("utf-16-le"),
        text.encode("utf-16-be"),
        text.encode("utf-32"),
        text.encode("utf-32-le"),
        text.encode("utf-32-be"),
    )

    for raw in invalid_sources:
        with pytest.raises(ValueError, match="invalid AiCallEventV1 JSON") as exc_info:
            parse_ai_call_event_v1(raw)
        assert sentinel not in str(exc_info.value)

    with pytest.raises(ValueError, match="invalid AiCallEventV1 JSON"):
        parse_ai_call_event_v1("\ufeff" + text)


def test_event_rejects_invalid_calendar_time_and_non_jcs_string() -> None:
    payload = _payload("ai-call-event-v1.started.json")
    payload["started_at"] = "2026-02-31T06:00:00.000000Z"
    with pytest.raises(ValidationError, match="AiCallEventV1 validation failed"):
        AiCallStartedV1.model_validate(payload)

    payload = _payload("ai-call-event-v1.started.json")
    payload["model_id"] = "\ud800"
    with pytest.raises(ValidationError):
        AiCallStartedV1.model_validate(payload)


def test_event_entry_options_cannot_relax_contract() -> None:
    payload = _payload("ai-call-event-v1.started.json")

    with pytest.raises(ValueError, match="cannot relax strict, extra, or attribute rules"):
        AiCallStartedV1.model_validate(payload, strict=False)
    with pytest.raises(ValueError, match="cannot relax strict, extra, or attribute rules"):
        AiCallStartedV1.model_validate(payload, from_attributes=True)
    with pytest.raises(TypeError, match="does not support model_validate_strings"):
        AiCallStartedV1.model_validate_strings(payload)
