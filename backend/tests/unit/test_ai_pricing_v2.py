from __future__ import annotations

import pytest

from app.ai.pricing import (
    BillingMode,
    BudgetProfileV2,
    CostCurrency,
    PricingProfileV2,
    calculate_preflight_reservation_v2,
    reconcile_actual_usage_v2,
)


def _pricing(currency: CostCurrency) -> PricingProfileV2:
    return PricingProfileV2(
        pricing_version=f"synthetic-{currency.value.lower()}-v2",
        billing_mode=(
            BillingMode.EXTERNAL_USD if currency is CostCurrency.USD else BillingMode.EXTERNAL_CNY
        ),
        cost_currency=currency,
        input_price_microunits_per_million=500_000,
        output_price_microunits_per_million=1_000_000,
    )


def _budget(currency: CostCurrency) -> BudgetProfileV2:
    return BudgetProfileV2(
        max_provider_attempts_per_business_operation=2,
        max_input_tokens_per_request=100,
        max_output_tokens_per_request=20,
        max_total_tokens=200,
        cost_currency=currency,
        max_cost_microunits=100,
    )


@pytest.mark.parametrize("currency", [CostCurrency.USD, CostCurrency.CNY])
def test_v2_uses_the_same_integer_formula_without_fx(currency: CostCurrency) -> None:
    reservation = calculate_preflight_reservation_v2(
        _budget(currency),
        _pricing(currency),
        provider_attempts_used=0,
        future_model_repair_slots=0,
        reserved_total_tokens=0,
        reserved_cost_microunits=0,
        input_tokens=3,
        max_output_tokens=2,
        context_window_tokens=1_000,
    )

    assert reservation.cost_currency is currency
    assert reservation.reserved_cost_microunits == 4
    actual = reconcile_actual_usage_v2(
        _pricing(currency),
        reservation,
        input_tokens=2,
        output_tokens=1,
        total_tokens=3,
    )
    assert actual.cost_currency is currency
    assert actual.actual_cost_microunits == 2


def test_v2_rejects_mixed_currency_before_reservation() -> None:
    with pytest.raises(ValueError, match="cost_currency must match budget"):
        calculate_preflight_reservation_v2(
            _budget(CostCurrency.USD),
            _pricing(CostCurrency.CNY),
            provider_attempts_used=0,
            future_model_repair_slots=0,
            reserved_total_tokens=0,
            reserved_cost_microunits=0,
            input_tokens=1,
            max_output_tokens=0,
            context_window_tokens=1_000,
        )


def test_internal_unmetered_requires_null_currency_and_zero_cost() -> None:
    profile = PricingProfileV2(
        pricing_version="internal-v2",
        billing_mode=BillingMode.INTERNAL_UNMETERED,
        cost_currency=None,
        input_price_microunits_per_million=0,
        output_price_microunits_per_million=0,
    )
    budget = BudgetProfileV2(
        max_provider_attempts_per_business_operation=1,
        max_input_tokens_per_request=10,
        max_output_tokens_per_request=0,
        max_total_tokens=10,
        cost_currency=None,
        max_cost_microunits=0,
    )

    reservation = calculate_preflight_reservation_v2(
        budget,
        profile,
        provider_attempts_used=0,
        future_model_repair_slots=0,
        reserved_total_tokens=0,
        reserved_cost_microunits=0,
        input_tokens=10,
        max_output_tokens=0,
        context_window_tokens=10,
    )

    assert reservation.cost_currency is None
    assert reservation.reserved_cost_microunits == 0


@pytest.mark.parametrize(
    ("mode", "currency"),
    [
        (BillingMode.EXTERNAL_USD, CostCurrency.CNY),
        (BillingMode.EXTERNAL_CNY, CostCurrency.USD),
        (BillingMode.INTERNAL_UNMETERED, CostCurrency.USD),
    ],
)
def test_billing_mode_and_currency_cannot_diverge(
    mode: BillingMode,
    currency: CostCurrency,
) -> None:
    with pytest.raises(ValueError, match="billing_mode and cost_currency must match"):
        PricingProfileV2(
            pricing_version="invalid-v2",
            billing_mode=mode,
            cost_currency=currency,
            input_price_microunits_per_million=0,
            output_price_microunits_per_million=0,
        )
