from __future__ import annotations

import socket
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol, cast

import pytest
from pydantic import BaseModel, ConfigDict

from app.ai.output_validation import (
    CitationValidationError,
    RagAnswerOutput,
    RagCitation,
    RiskExplanationValidationError,
    validate_rag_answer,
)
from app.ai.policy_resolver import ResolvedTargetIdentity
from app.ai.pricing import BillingMode, BudgetProfile, PricingProfile
from app.ai.structured_output import (
    StructuredOutputIssue,
    StructuredOutputIssueCategory,
    StructuredOutputValidationError,
)
from app.ai.structured_repair import (
    StructuredRepairBudgetTracker,
    StructuredRepairRequest,
    StructuredRepairUnavailableError,
    validate_structured_output_with_repair,
)


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int
    status: Literal["valid"]


class AccountingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal
    invoice_date: date


class NestedExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: list[int]


class _CodedError(Protocol):
    code: str


class FakeRepair:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.requests: list[StructuredRepairRequest] = []

    def __call__(self, request: StructuredRepairRequest) -> str:
        self.requests.append(request)
        response = self.responses[len(self.requests) - 1]
        if isinstance(response, BaseException):
            raise response
        return cast(str, response)


class SequenceClock:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


PRICING = PricingProfile(
    pricing_version="test-v1",
    billing_mode=BillingMode.EXTERNAL_USD,
    input_price_micro_usd_per_million=1_000_000,
    output_price_micro_usd_per_million=1_000_000,
)
BUDGET = BudgetProfile(
    max_provider_attempts_per_business_operation=6,
    max_input_tokens_per_request=100,
    max_output_tokens_per_request=100,
    max_total_tokens=1_000,
    max_cost_micro_usd=1_000,
)
TARGET = ResolvedTargetIdentity(
    profile_id="extraction-primary",
    adapter_id="openai_chat_completions_v1",
    endpoint_id="synthetic-endpoint",
    model_id="synthetic-model",
)


def make_budget(
    *,
    provider_attempts_used: int = 4,
    reserved_total_tokens: int = 0,
    reserved_cost_micro_usd: int = 0,
    deadline_monotonic: float = 10.0,
    monotonic: Callable[[], float] = lambda: 0.0,
) -> StructuredRepairBudgetTracker:
    return StructuredRepairBudgetTracker(
        budget_profile=BUDGET,
        pricing_profile=PRICING,
        provider_attempts_used=provider_attempts_used,
        reserved_total_tokens=reserved_total_tokens,
        reserved_cost_micro_usd=reserved_cost_micro_usd,
        deadline_monotonic=deadline_monotonic,
        monotonic=monotonic,
    )


def validate(
    raw_output: str,
    repair: FakeRepair,
    budget: StructuredRepairBudgetTracker,
    *,
    max_model_repairs: int = 2,
    repair_input_tokens: int = 10,
    repair_max_output_tokens: int = 10,
    context_window_tokens: int = 100,
    minimum_attempt_seconds: float = 1.0,
) -> ExtractionOutput:
    return validate_structured_output_with_repair(
        raw_output,
        ExtractionOutput,
        repair_call=repair,
        repair_target=TARGET,
        result_validator=lambda _: None,
        budget=budget,
        max_model_repairs=max_model_repairs,
        repair_input_tokens=repair_input_tokens,
        repair_max_output_tokens=repair_max_output_tokens,
        context_window_tokens=context_window_tokens,
        minimum_attempt_seconds=minimum_attempt_seconds,
    )


@pytest.mark.parametrize(
    "raw_output",
    [
        '{"amount":1,"status":"valid"}',
        '```json\n{"amount":1,"status":"valid"}\n```',
    ],
)
def test_valid_or_locally_cleanable_output_sends_no_repair(raw_output: str) -> None:
    repair = FakeRepair([])
    budget = make_budget()

    assert validate(raw_output, repair, budget) == ExtractionOutput(amount=1, status="valid")
    assert repair.requests == []
    assert budget.provider_attempts_used == 4
    assert budget.reserved_total_tokens == 0
    assert budget.reserved_cost_micro_usd == 0


def test_first_repair_can_succeed_and_commits_worst_case_budget() -> None:
    repair = FakeRepair(['{"amount":2,"status":"valid"}'])
    budget = make_budget()

    assert validate('{"amount":"bad","status":"valid"}', repair, budget).amount == 2
    assert [request.attempt_no for request in repair.requests] == [1]
    assert budget.provider_attempts_used == 5
    assert budget.reserved_total_tokens == 20
    assert budget.reserved_cost_micro_usd == 20


def test_second_repair_uses_latest_safe_issues_and_can_succeed() -> None:
    repair = FakeRepair(
        [
            '{"amount":2}',
            '{"amount":3,"status":"valid"}',
        ]
    )

    result = validate('{"amount":1,"status":"wrong"}', repair, make_budget())

    assert result.amount == 3
    assert [request.attempt_no for request in repair.requests] == [1, 2]
    assert [request.target for request in repair.requests] == [TARGET, TARGET]
    assert repair.requests[0].issues == (
        StructuredOutputIssue("/status", StructuredOutputIssueCategory.ENUM),
    )
    assert repair.requests[1].issues == (
        StructuredOutputIssue("/status", StructuredOutputIssueCategory.REQUIRED),
    )


def test_two_invalid_repairs_fail_with_fixed_error_and_never_send_third() -> None:
    repair = FakeRepair(['{"amount":"bad"}', '{"amount":"still-bad"}'])
    budget = make_budget()

    with pytest.raises(StructuredOutputValidationError) as exc_info:
        validate("not-json", repair, budget)

    assert exc_info.value.code == "AI_SCHEMA_VALIDATION_FAILED"
    assert len(repair.requests) == 2
    assert budget.provider_attempts_used == 6
    assert budget.reserved_total_tokens == 40
    assert budget.reserved_cost_micro_usd == 40


def test_repair_request_never_contains_failed_value_or_provider_output() -> None:
    sentinel = "SENSITIVE-INVOICE-VALUE-991"
    repair = FakeRepair(['{"amount":1,"status":"valid"}'])

    validate(f'{{"amount":1,"status":"{sentinel}"}}', repair, make_budget())

    request = repair.requests[0]
    assert request.issues == (StructuredOutputIssue("/status", StructuredOutputIssueCategory.ENUM),)
    assert sentinel not in repr(request)
    assert sentinel not in str(request)


def test_zero_repair_policy_returns_safe_validation_error_without_send() -> None:
    repair = FakeRepair([])

    with pytest.raises(StructuredOutputValidationError):
        validate("not-json", repair, make_budget(), max_model_repairs=0)

    assert repair.requests == []


@pytest.mark.parametrize(
    ("budget", "kwargs"),
    [
        (make_budget(provider_attempts_used=5), {}),
        (make_budget(reserved_total_tokens=981), {}),
        (make_budget(reserved_cost_micro_usd=981), {}),
        (make_budget(), {"repair_input_tokens": 101}),
        (make_budget(), {"repair_max_output_tokens": 101}),
        (make_budget(), {"context_window_tokens": 19}),
    ],
)
def test_exhausted_attempt_token_cost_or_context_gate_sends_nothing(
    budget: StructuredRepairBudgetTracker,
    kwargs: dict[str, int],
) -> None:
    repair = FakeRepair([])

    with pytest.raises(StructuredRepairUnavailableError):
        validate("not-json", repair, budget, **kwargs)

    assert repair.requests == []


def test_deadline_at_boundary_sends_nothing() -> None:
    repair = FakeRepair([])

    with pytest.raises(StructuredRepairUnavailableError):
        validate("not-json", repair, make_budget(monotonic=lambda: 10.0))

    assert repair.requests == []


def test_valid_initial_output_finishing_at_deadline_is_not_adopted() -> None:
    repair = FakeRepair([])

    with pytest.raises(StructuredRepairUnavailableError):
        validate(
            '{"amount":1,"status":"valid"}',
            repair,
            make_budget(monotonic=lambda: 10.0),
        )

    assert repair.requests == []


def test_remaining_deadline_must_exceed_minimum_attempt_time() -> None:
    repair = FakeRepair([])

    with pytest.raises(StructuredRepairUnavailableError):
        validate(
            "not-json",
            repair,
            make_budget(monotonic=lambda: 4.0),
            minimum_attempt_seconds=6.0,
        )

    assert repair.requests == []


def test_result_finishing_at_deadline_is_rejected_after_one_committed_attempt() -> None:
    repair = FakeRepair(['{"amount":1,"status":"valid"}'])
    budget = make_budget(monotonic=SequenceClock([0.0, 10.0]))

    with pytest.raises(StructuredRepairUnavailableError):
        validate("not-json", repair, budget)

    assert len(repair.requests) == 1
    assert budget.provider_attempts_used == 5


@pytest.mark.parametrize("clock_result", [float("nan"), float("inf"), True])
def test_invalid_clock_result_fails_closed_without_send(clock_result: float) -> None:
    repair = FakeRepair([])

    with pytest.raises(StructuredRepairUnavailableError):
        validate("not-json", repair, make_budget(monotonic=lambda: clock_result))

    assert repair.requests == []


def test_clock_exception_fails_closed_without_send() -> None:
    def broken_clock() -> float:
        raise RuntimeError("SENSITIVE-CLOCK-DATA")

    repair = FakeRepair([])
    with pytest.raises(StructuredRepairUnavailableError) as exc_info:
        validate("not-json", repair, make_budget(monotonic=broken_clock))

    assert repair.requests == []
    assert "SENSITIVE" not in repr(exc_info.value)


def test_repair_exception_is_redacted_and_consumes_committed_attempt() -> None:
    sentinel = "SENSITIVE-PROVIDER-EXCEPTION-771"
    repair = FakeRepair([RuntimeError(sentinel)])
    budget = make_budget()

    with pytest.raises(StructuredRepairUnavailableError) as exc_info:
        validate("not-json", repair, budget)

    assert len(repair.requests) == 1
    assert budget.provider_attempts_used == 5
    assert sentinel not in str(exc_info.value)
    assert sentinel not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.parametrize(
    ("raw_output", "repair_outputs", "expected_request_count"),
    [
        ('{"amount":1,"status":"valid"}', [], 0),
        ("not-json", ['{"amount":2,"status":"valid"}'], 1),
    ],
)
@pytest.mark.parametrize(
    ("error_type", "expected_code"),
    [
        (CitationValidationError, "CITATION_VALIDATION_FAILED"),
        (RiskExplanationValidationError, "AI_SCHEMA_VALIDATION_FAILED"),
    ],
)
def test_safe_business_validator_failure_is_preserved_and_terminal(
    raw_output: str,
    repair_outputs: list[object],
    expected_request_count: int,
    error_type: type[Exception],
    expected_code: str,
) -> None:
    repair = FakeRepair(repair_outputs)
    expected_error = error_type()

    def reject_business_fact(_: ExtractionOutput) -> None:
        raise expected_error

    with pytest.raises(error_type) as exc_info:
        validate_structured_output_with_repair(
            raw_output,
            ExtractionOutput,
            repair_call=repair,
            repair_target=TARGET,
            result_validator=reject_business_fact,
            budget=make_budget(),
            max_model_repairs=2,
            repair_input_tokens=10,
            repair_max_output_tokens=10,
            context_window_tokens=100,
            minimum_attempt_seconds=1.0,
        )

    assert exc_info.value is expected_error
    assert cast(_CodedError, exc_info.value).code == expected_code
    assert str(exc_info.value) == expected_code
    assert len(repair.requests) == expected_request_count


@pytest.mark.parametrize(
    ("raw_output", "repair_outputs", "expected_request_count"),
    [
        ('{"amount":1,"status":"valid"}', [], 0),
        ("not-json", ['{"amount":2,"status":"valid"}'], 1),
    ],
)
def test_unknown_validator_failure_is_redacted_and_terminal(
    raw_output: str,
    repair_outputs: list[object],
    expected_request_count: int,
) -> None:
    sentinel = "SENSITIVE-VALIDATOR-VALUE-881"
    repair = FakeRepair(repair_outputs)

    def fail_with_sensitive_value(_: ExtractionOutput) -> None:
        raise RuntimeError(sentinel)

    with pytest.raises(RuntimeError) as exc_info:
        validate_structured_output_with_repair(
            raw_output,
            ExtractionOutput,
            repair_call=repair,
            repair_target=TARGET,
            result_validator=fail_with_sensitive_value,
            budget=make_budget(),
            max_model_repairs=2,
            repair_input_tokens=10,
            repair_max_output_tokens=10,
            context_window_tokens=100,
            minimum_attempt_seconds=1.0,
        )

    assert cast(_CodedError, exc_info.value).code == "INTERNAL_ERROR"
    assert str(exc_info.value) == "INTERNAL_ERROR"
    assert sentinel not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert len(repair.requests) == expected_request_count


@pytest.mark.parametrize(
    ("raw_output", "repair_outputs", "expected_request_count"),
    [
        ('{"amount":1,"status":"valid"}', [], 0),
        ("not-json", ['{"amount":2,"status":"valid"}'], 1),
    ],
)
def test_async_validator_is_rejected_without_being_silently_skipped(
    raw_output: str,
    repair_outputs: list[object],
    expected_request_count: int,
) -> None:
    repair = FakeRepair(repair_outputs)
    validator_ran = False

    async def async_validator(_: ExtractionOutput) -> None:
        nonlocal validator_ran
        validator_ran = True

    with pytest.raises(RuntimeError) as exc_info:
        validate_structured_output_with_repair(
            raw_output,
            ExtractionOutput,
            repair_call=repair,
            repair_target=TARGET,
            result_validator=cast(Callable[[ExtractionOutput], None], async_validator),
            budget=make_budget(),
            max_model_repairs=2,
            repair_input_tokens=10,
            repair_max_output_tokens=10,
            context_window_tokens=100,
            minimum_attempt_seconds=1.0,
        )

    assert cast(_CodedError, exc_info.value).code == "INTERNAL_ERROR"
    assert str(exc_info.value) == "INTERNAL_ERROR"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert validator_ran is False
    assert len(repair.requests) == expected_request_count


@pytest.mark.parametrize(
    ("raw_output", "repair_outputs", "expected_request_count"),
    [
        ('{"amount":1,"status":"valid"}', [], 0),
        ("not-json", ['{"amount":2,"status":"valid"}'], 1),
    ],
)
def test_async_generator_validator_is_rejected_without_being_silently_skipped(
    raw_output: str,
    repair_outputs: list[object],
    expected_request_count: int,
) -> None:
    repair = FakeRepair(repair_outputs)
    validator_ran = False

    async def async_generator_validator(_: ExtractionOutput) -> AsyncIterator[None]:
        nonlocal validator_ran
        validator_ran = True
        yield None

    with pytest.raises(RuntimeError) as exc_info:
        validate_structured_output_with_repair(
            raw_output,
            ExtractionOutput,
            repair_call=repair,
            repair_target=TARGET,
            result_validator=cast(Callable[[ExtractionOutput], None], async_generator_validator),
            budget=make_budget(),
            max_model_repairs=2,
            repair_input_tokens=10,
            repair_max_output_tokens=10,
            context_window_tokens=100,
            minimum_attempt_seconds=1.0,
        )

    assert getattr(exc_info.value, "code", None) == "INTERNAL_ERROR"
    assert str(exc_info.value) == "INTERNAL_ERROR"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert validator_ran is False
    assert len(repair.requests) == expected_request_count


@pytest.mark.parametrize(
    ("raw_output", "repair_outputs", "expected_request_count"),
    [
        ('{"amount":1,"status":"valid"}', [], 0),
        ("not-json", ['{"amount":2,"status":"valid"}'], 1),
    ],
)
def test_generator_validator_is_rejected_without_being_silently_skipped(
    raw_output: str,
    repair_outputs: list[object],
    expected_request_count: int,
) -> None:
    repair = FakeRepair(repair_outputs)
    validator_ran = False

    def generator_validator(_: ExtractionOutput) -> Iterator[None]:
        nonlocal validator_ran
        validator_ran = True
        yield None

    with pytest.raises(RuntimeError) as exc_info:
        validate_structured_output_with_repair(
            raw_output,
            ExtractionOutput,
            repair_call=repair,
            repair_target=TARGET,
            result_validator=cast(Callable[[ExtractionOutput], None], generator_validator),
            budget=make_budget(),
            max_model_repairs=2,
            repair_input_tokens=10,
            repair_max_output_tokens=10,
            context_window_tokens=100,
            minimum_attempt_seconds=1.0,
        )

    assert cast(_CodedError, exc_info.value).code == "INTERNAL_ERROR"
    assert str(exc_info.value) == "INTERNAL_ERROR"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert validator_ran is False
    assert len(repair.requests) == expected_request_count


@pytest.mark.parametrize(
    ("raw_output", "repair_outputs", "expected_request_count"),
    [
        ('{"amount":1,"status":"valid"}', [], 0),
        ("not-json", ['{"amount":2,"status":"valid"}'], 1),
    ],
)
def test_validator_domain_error_subclass_is_redacted(
    raw_output: str,
    repair_outputs: list[object],
    expected_request_count: int,
) -> None:
    sentinel = "SENSITIVE-VALIDATOR-SUBCLASS-449"
    repair = FakeRepair(repair_outputs)

    class UnsafeCitationValidationError(CitationValidationError):
        def __init__(self) -> None:
            Exception.__init__(self, sentinel)

    def fail_with_unsafe_subclass(_: ExtractionOutput) -> None:
        raise UnsafeCitationValidationError

    with pytest.raises(RuntimeError) as exc_info:
        validate_structured_output_with_repair(
            raw_output,
            ExtractionOutput,
            repair_call=repair,
            repair_target=TARGET,
            result_validator=fail_with_unsafe_subclass,
            budget=make_budget(),
            max_model_repairs=2,
            repair_input_tokens=10,
            repair_max_output_tokens=10,
            context_window_tokens=100,
            minimum_attempt_seconds=1.0,
        )

    assert cast(_CodedError, exc_info.value).code == "INTERNAL_ERROR"
    assert str(exc_info.value) == "INTERNAL_ERROR"
    assert sentinel not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert len(repair.requests) == expected_request_count


@pytest.mark.parametrize(
    ("raw_output", "repair_outputs", "expected_request_count"),
    [
        ('{"values":[1]}', [], 0),
        ("not-json", ['{"values":[1]}'], 1),
    ],
)
def test_validator_cannot_mutate_adopted_result(
    raw_output: str,
    repair_outputs: list[object],
    expected_request_count: int,
) -> None:
    repair = FakeRepair(repair_outputs)

    def mutate_nested_value(value: NestedExtractionOutput) -> None:
        value.values[0] = -999

    result = validate_structured_output_with_repair(
        raw_output,
        NestedExtractionOutput,
        repair_call=repair,
        repair_target=TARGET,
        result_validator=mutate_nested_value,
        budget=make_budget(),
        max_model_repairs=2,
        repair_input_tokens=10,
        repair_max_output_tokens=10,
        context_window_tokens=100,
        minimum_attempt_seconds=1.0,
    )

    assert result.values == [1]
    assert len(repair.requests) == expected_request_count


@pytest.mark.parametrize(
    ("raw_output", "repair_outputs", "expected_amount"),
    [
        ('{"amount":1,"status":"valid"}', [], 1),
        ("not-json", ['{"amount":2,"status":"valid"}'], 2),
    ],
)
def test_validator_return_value_cannot_replace_strictly_parsed_result(
    raw_output: str,
    repair_outputs: list[object],
    expected_amount: int,
) -> None:
    forged = ExtractionOutput.model_construct(amount=-999, status="valid")
    object.__setattr__(forged, "status", "forged")

    result = validate_structured_output_with_repair(
        raw_output,
        ExtractionOutput,
        repair_call=FakeRepair(repair_outputs),
        repair_target=TARGET,
        result_validator=cast(Callable[[ExtractionOutput], None], lambda _: forged),
        budget=make_budget(),
        max_model_repairs=2,
        repair_input_tokens=10,
        repair_max_output_tokens=10,
        context_window_tokens=100,
        minimum_attempt_seconds=1.0,
    )

    assert result == ExtractionOutput(amount=expected_amount, status="valid")


def test_repaired_rag_citation_must_pass_full_candidate_validation() -> None:
    candidate = RagCitation(
        candidate_id="11111111-1111-1111-1111-111111111111",
        policy_document_id="22222222-2222-2222-2222-222222222222",
        policy_version="v1",
        markdown_version_id="33333333-3333-3333-3333-333333333333",
        chunk_id="44444444-4444-4444-4444-444444444444",
        block_ids=("66666666-6666-4666-8666-666666666666",),
        index_version_id="55555555-5555-5555-5555-555555555555",
        page_range="1",
        title_path=("采购制度",),
        quote="approved quote",
        content_sha256="a" * 64,
    )
    tampered = candidate.model_copy(update={"quote": "tampered quote"})
    repaired = RagAnswerOutput(
        answer_status="answered",
        answer="answer",
        reason_code=None,
        citations=(tampered,),
        confidence="0.9",
        warnings=(),
    )
    repair = FakeRepair([repaired.model_dump_json()])

    with pytest.raises(CitationValidationError):
        validate_structured_output_with_repair(
            "not-json",
            RagAnswerOutput,
            repair_call=repair,
            repair_target=TARGET,
            result_validator=lambda result: cast(
                None,
                validate_rag_answer(result, candidates=(candidate,)),
            ),
            budget=make_budget(),
            max_model_repairs=2,
            repair_input_tokens=10,
            repair_max_output_tokens=10,
            context_window_tokens=100,
            minimum_attempt_seconds=1.0,
        )

    assert len(repair.requests) == 1


def test_repaired_decimal_and_date_are_strictly_parsed() -> None:
    repair = FakeRepair(['{"amount":"12.34","invoice_date":"2026-08-11"}'])

    result = validate_structured_output_with_repair(
        '{"amount":"bad","invoice_date":"2026-08-11"}',
        AccountingOutput,
        repair_call=repair,
        repair_target=TARGET,
        result_validator=lambda _: None,
        budget=make_budget(),
        max_model_repairs=2,
        repair_input_tokens=10,
        repair_max_output_tokens=10,
        context_window_tokens=100,
        minimum_attempt_seconds=1.0,
    )

    assert result.amount == Decimal("12.34")
    assert result.invoice_date == date(2026, 8, 11)


def test_repair_orchestrator_never_opens_socket_or_sleeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline repair must not use socket or sleep")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(time, "sleep", fail)
    repair = FakeRepair(['{"amount":1,"status":"valid"}'])

    assert validate("not-json", repair, make_budget()).amount == 1


def test_non_string_repair_result_fails_closed() -> None:
    repair = FakeRepair([cast(str, {"amount": 1, "status": "valid"})])

    with pytest.raises(StructuredRepairUnavailableError):
        validate("not-json", repair, make_budget())

    assert len(repair.requests) == 1


@pytest.mark.parametrize("invalid", [-1, 3, 0.5, True, None])
def test_invalid_model_repair_limit_is_rejected(invalid: object) -> None:
    with pytest.raises(ValueError, match="max_model_repairs"):
        validate(
            "not-json",
            FakeRepair([]),
            make_budget(),
            max_model_repairs=cast(int, invalid),
        )


@pytest.mark.parametrize("invalid", [0, -1, float("nan"), float("inf"), True, None])
def test_invalid_minimum_attempt_time_is_rejected(invalid: object) -> None:
    with pytest.raises(ValueError, match="minimum_attempt_seconds"):
        validate(
            "not-json",
            FakeRepair([]),
            make_budget(),
            minimum_attempt_seconds=cast(float, invalid),
        )


def test_repair_request_is_immutable() -> None:
    repair = FakeRepair(['{"amount":1,"status":"valid"}'])
    validate("not-json", repair, make_budget())

    with pytest.raises(FrozenInstanceError):
        StructuredRepairRequest.__setattr__(repair.requests[0], "attempt_no", 2)
