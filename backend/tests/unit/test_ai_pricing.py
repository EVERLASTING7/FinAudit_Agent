import socket
import time
from dataclasses import FrozenInstanceError, replace
from inspect import Parameter, signature
from typing import cast

import pytest

from app.ai.pricing import (
    AttemptReservation,
    BillingMode,
    BudgetProfile,
    PricingProfile,
    ReconciledUsage,
    calculate_preflight_reservation,
    reconcile_actual_usage,
)

EXTERNAL_PROFILE = PricingProfile(
    pricing_version="provider-price-2026-08",
    billing_mode=BillingMode.EXTERNAL_USD,
    input_price_micro_usd_per_million=2_500_000,
    output_price_micro_usd_per_million=5_000_000,
)
UNIT_PRICE_PROFILE = PricingProfile(
    pricing_version="unit-price-v1",
    billing_mode=BillingMode.EXTERNAL_USD,
    input_price_micro_usd_per_million=1_000_000,
    output_price_micro_usd_per_million=1_000_000,
)
BUDGET_PROFILE = BudgetProfile(
    max_provider_attempts_per_business_operation=6,
    max_input_tokens_per_request=100,
    max_output_tokens_per_request=20,
    max_total_tokens=500,
    max_cost_micro_usd=200,
)
RESERVATION = AttemptReservation(
    pricing_version=UNIT_PRICE_PROFILE.pricing_version,
    reserved_input_tokens=100,
    reserved_output_tokens=20,
    reserved_cost_micro_usd=120,
)


def test_external_usd_cost_uses_exact_integer_formula() -> None:
    assert (
        EXTERNAL_PROFILE.calculate_request_cost_micro_usd(
            input_tokens=2,
            output_tokens=3,
        )
        == 20
    )


def test_external_usd_cost_rounds_each_physical_request_up() -> None:
    profile = replace(
        EXTERNAL_PROFILE,
        input_price_micro_usd_per_million=1,
        output_price_micro_usd_per_million=0,
    )

    first_cost = profile.calculate_request_cost_micro_usd(input_tokens=1, output_tokens=0)
    second_cost = profile.calculate_request_cost_micro_usd(input_tokens=1, output_tokens=0)

    assert first_cost + second_cost == 2
    assert profile.calculate_request_cost_micro_usd(input_tokens=2, output_tokens=0) == 1


def test_zero_token_request_has_zero_cost() -> None:
    assert (
        EXTERNAL_PROFILE.calculate_request_cost_micro_usd(
            input_tokens=0,
            output_tokens=0,
        )
        == 0
    )


def test_large_token_counts_remain_exact_integers() -> None:
    assert (
        EXTERNAL_PROFILE.calculate_request_cost_micro_usd(
            input_tokens=10**20,
            output_tokens=10**20,
        )
        == 750_000_000_000_000_000_000
    )


def test_internal_unmetered_profile_requires_explicit_zero_prices() -> None:
    profile = PricingProfile(
        pricing_version="internal-v1",
        billing_mode=BillingMode.INTERNAL_UNMETERED,
        input_price_micro_usd_per_million=0,
        output_price_micro_usd_per_million=0,
    )

    assert (
        profile.calculate_request_cost_micro_usd(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        == 0
    )


@pytest.mark.parametrize(
    ("input_price", "output_price"),
    [(1, 0), (0, 1), (1, 1)],
)
def test_internal_unmetered_profile_rejects_non_zero_prices(
    input_price: int,
    output_price: int,
) -> None:
    with pytest.raises(ValueError, match="must both be zero"):
        PricingProfile(
            pricing_version="internal-v1",
            billing_mode=BillingMode.INTERNAL_UNMETERED,
            input_price_micro_usd_per_million=input_price,
            output_price_micro_usd_per_million=output_price,
        )


@pytest.mark.parametrize("invalid", ["", " ", None, 1])
def test_rejects_invalid_pricing_version(invalid: object) -> None:
    with pytest.raises(ValueError, match="pricing_version"):
        replace(EXTERNAL_PROFILE, pricing_version=cast(str, invalid))


@pytest.mark.parametrize("invalid", ["external_usd", "internal_unmetered", None])
def test_rejects_unparsed_or_missing_billing_mode(invalid: object) -> None:
    with pytest.raises(ValueError, match="billing_mode"):
        replace(EXTERNAL_PROFILE, billing_mode=cast(BillingMode, invalid))


@pytest.mark.parametrize("invalid", [-1, 0.5, True, None])
@pytest.mark.parametrize(
    "field",
    ["input_price_micro_usd_per_million", "output_price_micro_usd_per_million"],
)
def test_rejects_invalid_prices(field: str, invalid: object) -> None:
    with pytest.raises(ValueError, match=field):
        replace(EXTERNAL_PROFILE, **{field: invalid})


@pytest.mark.parametrize("invalid", [-1, 0.5, True, None])
@pytest.mark.parametrize("field", ["input_tokens", "output_tokens"])
def test_rejects_invalid_token_counts(field: str, invalid: object) -> None:
    tokens = {"input_tokens": 0, "output_tokens": 0, field: invalid}

    with pytest.raises(ValueError, match=field):
        EXTERNAL_PROFILE.calculate_request_cost_micro_usd(**tokens)


def test_pricing_profile_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        PricingProfile.__setattr__(EXTERNAL_PROFILE, "pricing_version", "changed")


def test_pricing_calculation_does_not_use_network_or_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("pricing calculation must not use network or sleep")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(time, "sleep", fail)

    assert (
        EXTERNAL_PROFILE.calculate_request_cost_micro_usd(
            input_tokens=1,
            output_tokens=1,
        )
        == 8
    )


def test_budget_profile_has_no_defaults_and_is_immutable() -> None:
    assert all(
        parameter.default is Parameter.empty
        for parameter in signature(BudgetProfile).parameters.values()
    )
    with pytest.raises(FrozenInstanceError):
        BudgetProfile.__setattr__(BUDGET_PROFILE, "max_total_tokens", 1)


@pytest.mark.parametrize("invalid", [0, -1, 0.5, True, None])
def test_budget_profile_rejects_invalid_attempt_limit(invalid: object) -> None:
    with pytest.raises(ValueError, match="max_provider_attempts_per_business_operation"):
        replace(
            BUDGET_PROFILE,
            max_provider_attempts_per_business_operation=cast(int, invalid),
        )


@pytest.mark.parametrize("invalid", [-1, 0.5, True, None])
@pytest.mark.parametrize(
    "field",
    [
        "max_input_tokens_per_request",
        "max_output_tokens_per_request",
        "max_total_tokens",
        "max_cost_micro_usd",
    ],
)
def test_budget_profile_rejects_invalid_limits(field: str, invalid: object) -> None:
    with pytest.raises(ValueError, match=field):
        replace(BUDGET_PROFILE, **{field: invalid})


def test_preflight_calculates_worst_case_reservation() -> None:
    reservation = calculate_preflight_reservation(
        BUDGET_PROFILE,
        UNIT_PRICE_PROFILE,
        provider_attempts_used=2,
        future_model_repair_slots=0,
        reserved_total_tokens=100,
        reserved_cost_micro_usd=30,
        input_tokens=20,
        max_output_tokens=10,
        context_window_tokens=100,
    )

    assert reservation == AttemptReservation(
        pricing_version=UNIT_PRICE_PROFILE.pricing_version,
        reserved_input_tokens=20,
        reserved_output_tokens=10,
        reserved_cost_micro_usd=30,
    )
    assert reservation.reserved_total_tokens == 30


def test_preflight_allows_exact_attempt_token_context_and_cost_limits() -> None:
    assert (
        calculate_preflight_reservation(
            BUDGET_PROFILE,
            UNIT_PRICE_PROFILE,
            provider_attempts_used=5,
            future_model_repair_slots=0,
            reserved_total_tokens=380,
            reserved_cost_micro_usd=80,
            input_tokens=100,
            max_output_tokens=20,
            context_window_tokens=120,
        )
        == RESERVATION
    )


def test_preflight_preserves_future_model_repair_attempt_slots() -> None:
    with pytest.raises(ValueError, match="max_provider_attempts_per_business_operation"):
        calculate_preflight_reservation(
            BUDGET_PROFILE,
            UNIT_PRICE_PROFILE,
            provider_attempts_used=5,
            future_model_repair_slots=1,
            reserved_total_tokens=0,
            reserved_cost_micro_usd=0,
            input_tokens=1,
            max_output_tokens=1,
            context_window_tokens=2,
        )

    calculate_preflight_reservation(
        BUDGET_PROFILE,
        UNIT_PRICE_PROFILE,
        provider_attempts_used=4,
        future_model_repair_slots=1,
        reserved_total_tokens=0,
        reserved_cost_micro_usd=0,
        input_tokens=1,
        max_output_tokens=1,
        context_window_tokens=2,
    )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        (
            "provider_attempts_used",
            6,
            "max_provider_attempts_per_business_operation",
        ),
        ("input_tokens", 101, "max_input_tokens_per_request"),
        ("max_output_tokens", 21, "max_output_tokens_per_request"),
        ("context_window_tokens", 119, "context_window_tokens"),
        ("reserved_total_tokens", 381, "max_total_tokens"),
        ("reserved_cost_micro_usd", 81, "max_cost_micro_usd"),
    ],
)
def test_preflight_rejects_exhausted_limits(field: str, value: int, error: str) -> None:
    arguments = {
        "provider_attempts_used": 5,
        "future_model_repair_slots": 0,
        "reserved_total_tokens": 380,
        "reserved_cost_micro_usd": 80,
        "input_tokens": 100,
        "max_output_tokens": 20,
        "context_window_tokens": 120,
        field: value,
    }

    with pytest.raises(ValueError, match=error):
        calculate_preflight_reservation(
            BUDGET_PROFILE,
            UNIT_PRICE_PROFILE,
            **arguments,
        )


@pytest.mark.parametrize("invalid", [-1, 0.5, True, None])
@pytest.mark.parametrize(
    "field",
    [
        "provider_attempts_used",
        "future_model_repair_slots",
        "reserved_total_tokens",
        "reserved_cost_micro_usd",
        "input_tokens",
        "max_output_tokens",
    ],
)
def test_preflight_rejects_invalid_counters(
    field: str,
    invalid: object,
) -> None:
    arguments = {
        "provider_attempts_used": 0,
        "future_model_repair_slots": 0,
        "reserved_total_tokens": 0,
        "reserved_cost_micro_usd": 0,
        "input_tokens": 1,
        "max_output_tokens": 1,
        "context_window_tokens": 2,
        field: invalid,
    }

    with pytest.raises(ValueError, match=field):
        calculate_preflight_reservation(
            BUDGET_PROFILE,
            UNIT_PRICE_PROFILE,
            **arguments,
        )


@pytest.mark.parametrize("invalid", [0, -1, 0.5, True, None])
def test_preflight_rejects_invalid_context_window(invalid: object) -> None:
    with pytest.raises(ValueError, match="context_window_tokens"):
        calculate_preflight_reservation(
            BUDGET_PROFILE,
            UNIT_PRICE_PROFILE,
            provider_attempts_used=0,
            future_model_repair_slots=0,
            reserved_total_tokens=0,
            reserved_cost_micro_usd=0,
            input_tokens=1,
            max_output_tokens=1,
            context_window_tokens=cast(int, invalid),
        )


def test_preflight_internal_unmetered_reserves_zero_cost() -> None:
    internal_profile = PricingProfile(
        pricing_version="internal-v1",
        billing_mode=BillingMode.INTERNAL_UNMETERED,
        input_price_micro_usd_per_million=0,
        output_price_micro_usd_per_million=0,
    )

    assert (
        calculate_preflight_reservation(
            replace(BUDGET_PROFILE, max_cost_micro_usd=0),
            internal_profile,
            provider_attempts_used=0,
            future_model_repair_slots=0,
            reserved_total_tokens=0,
            reserved_cost_micro_usd=0,
            input_tokens=10,
            max_output_tokens=0,
            context_window_tokens=10,
        ).reserved_cost_micro_usd
        == 0
    )


def test_reconcile_actual_usage_calculates_actual_integer_cost() -> None:
    usage = reconcile_actual_usage(
        UNIT_PRICE_PROFILE,
        RESERVATION,
        input_tokens=90,
        output_tokens=10,
        total_tokens=100,
    )

    assert usage == ReconciledUsage(
        input_tokens=90,
        output_tokens=10,
        total_tokens=100,
        cost_micro_usd=100,
    )


def test_reconcile_actual_usage_rejects_inconsistent_total() -> None:
    with pytest.raises(ValueError, match="total_tokens must equal"):
        reconcile_actual_usage(
            UNIT_PRICE_PROFILE,
            RESERVATION,
            input_tokens=90,
            output_tokens=10,
            total_tokens=99,
        )


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens", "error"),
    [
        (101, 0, "input_tokens exceed reservation"),
        (0, 21, "output_tokens exceed reservation"),
    ],
)
def test_reconcile_actual_usage_rejects_tokens_above_reservation(
    input_tokens: int,
    output_tokens: int,
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        reconcile_actual_usage(
            UNIT_PRICE_PROFILE,
            RESERVATION,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )


def test_reconcile_actual_usage_rejects_cost_above_reservation() -> None:
    higher_price = replace(
        UNIT_PRICE_PROFILE,
        input_price_micro_usd_per_million=2_000_000,
        output_price_micro_usd_per_million=2_000_000,
    )

    with pytest.raises(ValueError, match="cost_micro_usd exceeds reservation"):
        reconcile_actual_usage(
            higher_price,
            RESERVATION,
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
        )


def test_reconcile_actual_usage_rejects_pricing_version_drift() -> None:
    with pytest.raises(ValueError, match="pricing_version"):
        reconcile_actual_usage(
            replace(UNIT_PRICE_PROFILE, pricing_version="different-version"),
            RESERVATION,
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
        )


@pytest.mark.parametrize("invalid", [-1, 0.5, True, None])
@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "total_tokens"])
def test_reconcile_actual_usage_rejects_invalid_usage(field: str, invalid: object) -> None:
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, field: invalid}

    with pytest.raises(ValueError, match=field):
        reconcile_actual_usage(UNIT_PRICE_PROFILE, RESERVATION, **usage)


def test_budget_results_are_immutable() -> None:
    usage = reconcile_actual_usage(
        UNIT_PRICE_PROFILE,
        RESERVATION,
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
    )

    with pytest.raises(FrozenInstanceError):
        AttemptReservation.__setattr__(RESERVATION, "reserved_input_tokens", 0)
    with pytest.raises(FrozenInstanceError):
        ReconciledUsage.__setattr__(usage, "input_tokens", 0)


def test_budget_calculations_do_not_use_network_or_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("budget calculation must not use network or sleep")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(time, "sleep", fail)

    reservation = calculate_preflight_reservation(
        BUDGET_PROFILE,
        UNIT_PRICE_PROFILE,
        provider_attempts_used=0,
        future_model_repair_slots=0,
        reserved_total_tokens=0,
        reserved_cost_micro_usd=0,
        input_tokens=1,
        max_output_tokens=1,
        context_window_tokens=2,
    )
    assert (
        reconcile_actual_usage(
            UNIT_PRICE_PROFILE,
            reservation,
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
        ).cost_micro_usd
        == 2
    )
