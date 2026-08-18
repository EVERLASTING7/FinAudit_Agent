"""CR-002 的版本化 AI 价格 Profile 与纯整数费用计算。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

_TOKENS_PER_MILLION = 1_000_000


class BillingMode(str, Enum):
    EXTERNAL_USD = "external_usd"
    EXTERNAL_CNY = "external_cny"
    INTERNAL_UNMETERED = "internal_unmetered"


class CostCurrency(str, Enum):
    USD = "USD"
    CNY = "CNY"


def _require_non_empty(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_non_negative_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class PricingProfile:
    """单一模型目标的不可变价格版本；价格单位为 micro_usd/百万 Token。"""

    pricing_version: str
    billing_mode: BillingMode
    input_price_micro_usd_per_million: int
    output_price_micro_usd_per_million: int

    def __post_init__(self) -> None:
        _require_non_empty("pricing_version", self.pricing_version)
        if not isinstance(self.billing_mode, BillingMode):
            raise ValueError("billing_mode must be a BillingMode")
        if self.billing_mode is BillingMode.EXTERNAL_CNY:
            raise ValueError("PricingProfile v1 only supports USD or internal unmetered")
        _require_non_negative_integer(
            "input_price_micro_usd_per_million",
            self.input_price_micro_usd_per_million,
        )
        _require_non_negative_integer(
            "output_price_micro_usd_per_million",
            self.output_price_micro_usd_per_million,
        )
        if self.billing_mode is BillingMode.INTERNAL_UNMETERED and (
            self.input_price_micro_usd_per_million != 0
            or self.output_price_micro_usd_per_million != 0
        ):
            raise ValueError("internal_unmetered prices must both be zero")

    def calculate_request_cost_micro_usd(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> int:
        """按 CR-002 公式计算并向上取整单个物理请求的费用。"""

        _require_non_negative_integer("input_tokens", input_tokens)
        _require_non_negative_integer("output_tokens", output_tokens)
        if self.billing_mode is BillingMode.INTERNAL_UNMETERED:
            return 0

        numerator = (
            input_tokens * self.input_price_micro_usd_per_million
            + output_tokens * self.output_price_micro_usd_per_million
        )
        return (numerator + _TOKENS_PER_MILLION - 1) // _TOKENS_PER_MILLION


@dataclass(frozen=True, slots=True)
class BudgetProfile:
    """单类业务操作的不可变 Provider 请求、Token 与费用上限。"""

    max_provider_attempts_per_business_operation: int
    max_input_tokens_per_request: int
    max_output_tokens_per_request: int
    max_total_tokens: int
    max_cost_micro_usd: int

    def __post_init__(self) -> None:
        _require_non_negative_integer(
            "max_provider_attempts_per_business_operation",
            self.max_provider_attempts_per_business_operation,
        )
        if self.max_provider_attempts_per_business_operation == 0:
            raise ValueError("max_provider_attempts_per_business_operation must be positive")
        _require_non_negative_integer(
            "max_input_tokens_per_request",
            self.max_input_tokens_per_request,
        )
        _require_non_negative_integer(
            "max_output_tokens_per_request",
            self.max_output_tokens_per_request,
        )
        _require_non_negative_integer("max_total_tokens", self.max_total_tokens)
        _require_non_negative_integer("max_cost_micro_usd", self.max_cost_micro_usd)


@dataclass(frozen=True, slots=True)
class AttemptReservation:
    pricing_version: str
    reserved_input_tokens: int
    reserved_output_tokens: int
    reserved_cost_micro_usd: int

    def __post_init__(self) -> None:
        _require_non_empty("pricing_version", self.pricing_version)
        _require_non_negative_integer("reserved_input_tokens", self.reserved_input_tokens)
        _require_non_negative_integer("reserved_output_tokens", self.reserved_output_tokens)
        _require_non_negative_integer(
            "reserved_cost_micro_usd",
            self.reserved_cost_micro_usd,
        )

    @property
    def reserved_total_tokens(self) -> int:
        return self.reserved_input_tokens + self.reserved_output_tokens


@dataclass(frozen=True, slots=True)
class ReconciledUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_micro_usd: int

    def __post_init__(self) -> None:
        _require_non_negative_integer("input_tokens", self.input_tokens)
        _require_non_negative_integer("output_tokens", self.output_tokens)
        _require_non_negative_integer("total_tokens", self.total_tokens)
        _require_non_negative_integer("cost_micro_usd", self.cost_micro_usd)
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")


def calculate_preflight_reservation(
    budget_profile: BudgetProfile,
    pricing_profile: PricingProfile,
    *,
    provider_attempts_used: int,
    future_model_repair_slots: int,
    reserved_total_tokens: int,
    reserved_cost_micro_usd: int,
    input_tokens: int,
    max_output_tokens: int,
    context_window_tokens: int,
) -> AttemptReservation:
    """根据已提交累计值计算下一物理请求的最坏预留，不改变共享状态。"""

    if not isinstance(budget_profile, BudgetProfile):
        raise ValueError("budget_profile must be a BudgetProfile")
    if not isinstance(pricing_profile, PricingProfile):
        raise ValueError("pricing_profile must be a PricingProfile")
    for name, value in (
        ("provider_attempts_used", provider_attempts_used),
        ("future_model_repair_slots", future_model_repair_slots),
        ("reserved_total_tokens", reserved_total_tokens),
        ("reserved_cost_micro_usd", reserved_cost_micro_usd),
        ("input_tokens", input_tokens),
        ("max_output_tokens", max_output_tokens),
        ("context_window_tokens", context_window_tokens),
    ):
        _require_non_negative_integer(name, value)
    if context_window_tokens == 0:
        raise ValueError("context_window_tokens must be positive")

    if (
        provider_attempts_used + 1 + future_model_repair_slots
        > budget_profile.max_provider_attempts_per_business_operation
    ):
        raise ValueError("max_provider_attempts_per_business_operation exceeded")
    if input_tokens > budget_profile.max_input_tokens_per_request:
        raise ValueError("max_input_tokens_per_request exceeded")
    if max_output_tokens > budget_profile.max_output_tokens_per_request:
        raise ValueError("max_output_tokens_per_request exceeded")

    requested_total_tokens = input_tokens + max_output_tokens
    if requested_total_tokens > context_window_tokens:
        raise ValueError("context_window_tokens exceeded")
    if reserved_total_tokens + requested_total_tokens > budget_profile.max_total_tokens:
        raise ValueError("max_total_tokens exceeded")

    reserved_request_cost = pricing_profile.calculate_request_cost_micro_usd(
        input_tokens=input_tokens,
        output_tokens=max_output_tokens,
    )
    if reserved_cost_micro_usd + reserved_request_cost > budget_profile.max_cost_micro_usd:
        raise ValueError("max_cost_micro_usd exceeded")

    return AttemptReservation(
        pricing_version=pricing_profile.pricing_version,
        reserved_input_tokens=input_tokens,
        reserved_output_tokens=max_output_tokens,
        reserved_cost_micro_usd=reserved_request_cost,
    )


def reconcile_actual_usage(
    pricing_profile: PricingProfile,
    reservation: AttemptReservation,
    *,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
) -> ReconciledUsage:
    """校验 Provider usage 并计算实际费用；不会释放已提交的最坏预留。"""

    if not isinstance(pricing_profile, PricingProfile):
        raise ValueError("pricing_profile must be a PricingProfile")
    if not isinstance(reservation, AttemptReservation):
        raise ValueError("reservation must be an AttemptReservation")
    if pricing_profile.pricing_version != reservation.pricing_version:
        raise ValueError("pricing_version must match reservation")
    for name, value in (
        ("input_tokens", input_tokens),
        ("output_tokens", output_tokens),
        ("total_tokens", total_tokens),
    ):
        _require_non_negative_integer(name, value)
    if total_tokens != input_tokens + output_tokens:
        raise ValueError("total_tokens must equal input_tokens + output_tokens")
    if input_tokens > reservation.reserved_input_tokens:
        raise ValueError("input_tokens exceed reservation")
    if output_tokens > reservation.reserved_output_tokens:
        raise ValueError("output_tokens exceed reservation")

    actual_cost = pricing_profile.calculate_request_cost_micro_usd(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    if actual_cost > reservation.reserved_cost_micro_usd:
        raise ValueError("cost_micro_usd exceeds reservation")
    return ReconciledUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_micro_usd=actual_cost,
    )


@dataclass(frozen=True, slots=True)
class PricingProfileV2:
    """CR-022 的币种中立价格；microunit 固定为对应币种的 10^-6。"""

    pricing_version: str
    billing_mode: BillingMode
    cost_currency: CostCurrency | None
    input_price_microunits_per_million: int
    output_price_microunits_per_million: int

    def __post_init__(self) -> None:
        _require_non_empty("pricing_version", self.pricing_version)
        if not isinstance(self.billing_mode, BillingMode):
            raise ValueError("billing_mode must be a BillingMode")
        if self.cost_currency is not None and not isinstance(self.cost_currency, CostCurrency):
            raise ValueError("cost_currency must be a CostCurrency or None")
        _require_non_negative_integer(
            "input_price_microunits_per_million",
            self.input_price_microunits_per_million,
        )
        _require_non_negative_integer(
            "output_price_microunits_per_million",
            self.output_price_microunits_per_million,
        )
        expected_currency = {
            BillingMode.EXTERNAL_USD: CostCurrency.USD,
            BillingMode.EXTERNAL_CNY: CostCurrency.CNY,
            BillingMode.INTERNAL_UNMETERED: None,
        }[self.billing_mode]
        if self.cost_currency is not expected_currency:
            raise ValueError("billing_mode and cost_currency must match")
        if self.billing_mode is BillingMode.INTERNAL_UNMETERED and (
            self.input_price_microunits_per_million != 0
            or self.output_price_microunits_per_million != 0
        ):
            raise ValueError("internal_unmetered prices must both be zero")

    def calculate_request_cost_microunits(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> int:
        _require_non_negative_integer("input_tokens", input_tokens)
        _require_non_negative_integer("output_tokens", output_tokens)
        if self.billing_mode is BillingMode.INTERNAL_UNMETERED:
            return 0
        numerator = (
            input_tokens * self.input_price_microunits_per_million
            + output_tokens * self.output_price_microunits_per_million
        )
        return (numerator + _TOKENS_PER_MILLION - 1) // _TOKENS_PER_MILLION


@dataclass(frozen=True, slots=True)
class BudgetProfileV2:
    max_provider_attempts_per_business_operation: int
    max_input_tokens_per_request: int
    max_output_tokens_per_request: int
    max_total_tokens: int
    cost_currency: CostCurrency | None
    max_cost_microunits: int

    def __post_init__(self) -> None:
        _require_non_negative_integer(
            "max_provider_attempts_per_business_operation",
            self.max_provider_attempts_per_business_operation,
        )
        if self.max_provider_attempts_per_business_operation == 0:
            raise ValueError("max_provider_attempts_per_business_operation must be positive")
        _require_non_negative_integer(
            "max_input_tokens_per_request",
            self.max_input_tokens_per_request,
        )
        _require_non_negative_integer(
            "max_output_tokens_per_request",
            self.max_output_tokens_per_request,
        )
        _require_non_negative_integer("max_total_tokens", self.max_total_tokens)
        _require_non_negative_integer("max_cost_microunits", self.max_cost_microunits)
        if self.cost_currency is not None and not isinstance(self.cost_currency, CostCurrency):
            raise ValueError("cost_currency must be a CostCurrency or None")
        if self.cost_currency is None and self.max_cost_microunits != 0:
            raise ValueError("internal unmetered max cost must be zero")


@dataclass(frozen=True, slots=True)
class AttemptReservationV2:
    pricing_version: str
    cost_currency: CostCurrency | None
    reserved_input_tokens: int
    reserved_output_tokens: int
    reserved_cost_microunits: int

    def __post_init__(self) -> None:
        _require_non_empty("pricing_version", self.pricing_version)
        if self.cost_currency is not None and not isinstance(self.cost_currency, CostCurrency):
            raise ValueError("cost_currency must be a CostCurrency or None")
        _require_non_negative_integer("reserved_input_tokens", self.reserved_input_tokens)
        _require_non_negative_integer("reserved_output_tokens", self.reserved_output_tokens)
        _require_non_negative_integer(
            "reserved_cost_microunits",
            self.reserved_cost_microunits,
        )
        if self.cost_currency is None and self.reserved_cost_microunits != 0:
            raise ValueError("internal unmetered reservation must be zero")

    @property
    def reserved_total_tokens(self) -> int:
        return self.reserved_input_tokens + self.reserved_output_tokens


@dataclass(frozen=True, slots=True)
class ReconciledUsageV2:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_currency: CostCurrency | None
    actual_cost_microunits: int

    def __post_init__(self) -> None:
        _require_non_negative_integer("input_tokens", self.input_tokens)
        _require_non_negative_integer("output_tokens", self.output_tokens)
        _require_non_negative_integer("total_tokens", self.total_tokens)
        _require_non_negative_integer("actual_cost_microunits", self.actual_cost_microunits)
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        if self.cost_currency is None and self.actual_cost_microunits != 0:
            raise ValueError("internal unmetered actual cost must be zero")


def calculate_preflight_reservation_v2(
    budget_profile: BudgetProfileV2,
    pricing_profile: PricingProfileV2,
    *,
    provider_attempts_used: int,
    future_model_repair_slots: int,
    reserved_total_tokens: int,
    reserved_cost_microunits: int,
    input_tokens: int,
    max_output_tokens: int,
    context_window_tokens: int,
) -> AttemptReservationV2:
    if not isinstance(budget_profile, BudgetProfileV2):
        raise ValueError("budget_profile must be a BudgetProfileV2")
    if not isinstance(pricing_profile, PricingProfileV2):
        raise ValueError("pricing_profile must be a PricingProfileV2")
    if budget_profile.cost_currency is not pricing_profile.cost_currency:
        raise ValueError("cost_currency must match budget")
    for name, value in (
        ("provider_attempts_used", provider_attempts_used),
        ("future_model_repair_slots", future_model_repair_slots),
        ("reserved_total_tokens", reserved_total_tokens),
        ("reserved_cost_microunits", reserved_cost_microunits),
        ("input_tokens", input_tokens),
        ("max_output_tokens", max_output_tokens),
        ("context_window_tokens", context_window_tokens),
    ):
        _require_non_negative_integer(name, value)
    if context_window_tokens == 0:
        raise ValueError("context_window_tokens must be positive")
    if (
        provider_attempts_used + 1 + future_model_repair_slots
        > budget_profile.max_provider_attempts_per_business_operation
    ):
        raise ValueError("max_provider_attempts_per_business_operation exceeded")
    if input_tokens > budget_profile.max_input_tokens_per_request:
        raise ValueError("max_input_tokens_per_request exceeded")
    if max_output_tokens > budget_profile.max_output_tokens_per_request:
        raise ValueError("max_output_tokens_per_request exceeded")
    requested_total_tokens = input_tokens + max_output_tokens
    if requested_total_tokens > context_window_tokens:
        raise ValueError("context_window_tokens exceeded")
    if reserved_total_tokens + requested_total_tokens > budget_profile.max_total_tokens:
        raise ValueError("max_total_tokens exceeded")
    request_cost = pricing_profile.calculate_request_cost_microunits(
        input_tokens=input_tokens,
        output_tokens=max_output_tokens,
    )
    if reserved_cost_microunits + request_cost > budget_profile.max_cost_microunits:
        raise ValueError("max_cost_microunits exceeded")
    return AttemptReservationV2(
        pricing_version=pricing_profile.pricing_version,
        cost_currency=pricing_profile.cost_currency,
        reserved_input_tokens=input_tokens,
        reserved_output_tokens=max_output_tokens,
        reserved_cost_microunits=request_cost,
    )


def reconcile_actual_usage_v2(
    pricing_profile: PricingProfileV2,
    reservation: AttemptReservationV2,
    *,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
) -> ReconciledUsageV2:
    if pricing_profile.pricing_version != reservation.pricing_version:
        raise ValueError("pricing_version must match reservation")
    if pricing_profile.cost_currency is not reservation.cost_currency:
        raise ValueError("cost_currency must match reservation")
    for name, value in (
        ("input_tokens", input_tokens),
        ("output_tokens", output_tokens),
        ("total_tokens", total_tokens),
    ):
        _require_non_negative_integer(name, value)
    if total_tokens != input_tokens + output_tokens:
        raise ValueError("total_tokens must equal input_tokens + output_tokens")
    if input_tokens > reservation.reserved_input_tokens:
        raise ValueError("input_tokens exceed reservation")
    if output_tokens > reservation.reserved_output_tokens:
        raise ValueError("output_tokens exceed reservation")
    actual_cost = pricing_profile.calculate_request_cost_microunits(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    if actual_cost > reservation.reserved_cost_microunits:
        raise ValueError("actual_cost_microunits exceeds reservation")
    return ReconciledUsageV2(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_currency=pricing_profile.cost_currency,
        actual_cost_microunits=actual_cost,
    )
