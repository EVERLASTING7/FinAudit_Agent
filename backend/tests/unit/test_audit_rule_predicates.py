from dataclasses import FrozenInstanceError
from datetime import date, datetime
from decimal import Decimal, localcontext

import pytest

from app.audit.rule_predicates import (
    RuleExecutionStatus,
    RulePredicateResult,
    evaluate_rule_001,
    evaluate_rule_002,
    evaluate_rule_003,
    evaluate_rule_004,
    evaluate_rule_005,
    evaluate_rule_006,
    evaluate_rule_007,
    evaluate_rule_008_currency_pair,
    evaluate_rule_009,
    evaluate_rule_010,
    evaluate_rule_011,
    evaluate_rule_012,
    evaluate_rule_013,
    evaluate_rule_014_identity_pair,
    evaluate_rule_015,
)


@pytest.mark.parametrize(
    ("contract_party_b_tax_no", "invoice_seller_tax_no", "expected_status"),
    (
        ("91310000MA000001X1", "91310000MA000001X1", RuleExecutionStatus.PASSED),
        ("91310000MA000001X1", "91310000MA000002X2", RuleExecutionStatus.FAILED),
        ("91310000MA000001X1", "91310000ma000001x1", RuleExecutionStatus.FAILED),
        (" 91310000MA000001X1 ", "91310000MA000001X1", RuleExecutionStatus.FAILED),
    ),
)
def test_rule_001_compares_tax_numbers_exactly(
    contract_party_b_tax_no: str,
    invoice_seller_tax_no: str,
    expected_status: RuleExecutionStatus,
) -> None:
    result = evaluate_rule_001(
        True,
        contract_party_b_tax_no,
        invoice_seller_tax_no,
    )

    assert result.status is expected_status


@pytest.mark.parametrize(
    ("contract_party_b_tax_no", "invoice_seller_tax_no"),
    ((None, "91310000MA000001X1"), ("91310000MA000001X1", None), (None, None)),
)
def test_rule_001_is_not_applicable_when_a_tax_number_is_missing(
    contract_party_b_tax_no: str | None,
    invoice_seller_tax_no: str | None,
) -> None:
    result = evaluate_rule_001(
        True,
        contract_party_b_tax_no,
        invoice_seller_tax_no,
    )

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


def test_rule_001_is_not_applicable_without_a_confirmed_primary_contract() -> None:
    result = evaluate_rule_001(
        False,
        "91310000MA000001X1",
        "91310000MA000002X2",
    )

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


class Rule001StringSubclass(str):
    pass


@pytest.mark.parametrize("invalid_flag", (None, 0, 1, "true"))
def test_rule_001_rejects_non_exact_contract_flag_before_tax_number_facts(
    invalid_flag: object,
) -> None:
    with pytest.raises(ValueError, match="exact bool"):
        evaluate_rule_001(invalid_flag, "", "")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("contract_party_b_tax_no", "invoice_seller_tax_no"),
    (
        ("", None),
        (None, "   "),
        (Rule001StringSubclass("91310000MA000001X1"), "91310000MA000001X1"),
        ("91310000MA000001X1", 1),
    ),
)
def test_rule_001_rejects_malformed_tax_number_before_not_applicable(
    contract_party_b_tax_no: object,
    invoice_seller_tax_no: object,
) -> None:
    with pytest.raises(ValueError, match="non-blank exact str"):
        evaluate_rule_001(
            False,
            contract_party_b_tax_no,  # type: ignore[arg-type]
            invoice_seller_tax_no,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("organization_tax_number", "invoice_buyer_tax_no", "expected_status"),
    (
        ("91310000MA000001X1", "91310000MA000001X1", RuleExecutionStatus.PASSED),
        ("91310000MA000001X1", "91310000MA000002X2", RuleExecutionStatus.FAILED),
        ("91310000MA000001X1", "91310000ma000001x1", RuleExecutionStatus.FAILED),
        (" 91310000MA000001X1 ", "91310000MA000001X1", RuleExecutionStatus.FAILED),
    ),
)
def test_rule_002_compares_tax_numbers_exactly(
    organization_tax_number: str,
    invoice_buyer_tax_no: str,
    expected_status: RuleExecutionStatus,
) -> None:
    result = evaluate_rule_002(organization_tax_number, invoice_buyer_tax_no)

    assert result.status is expected_status


def test_rule_002_is_not_applicable_when_invoice_buyer_tax_number_is_missing() -> None:
    result = evaluate_rule_002("91310000MA000001X1", None)

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


class Rule002StringSubclass(str):
    pass


@pytest.mark.parametrize(
    "invalid_organization_tax_number",
    (None, "", "   ", Rule002StringSubclass("91310000MA000001X1"), 1),
)
def test_rule_002_rejects_malformed_organization_tax_number_before_missing_invoice_fact(
    invalid_organization_tax_number: object,
) -> None:
    with pytest.raises(ValueError, match="organization_tax_number"):
        evaluate_rule_002(
            invalid_organization_tax_number,  # type: ignore[arg-type]
            None,
        )


@pytest.mark.parametrize(
    "invalid_invoice_buyer_tax_no",
    ("", "\t", Rule002StringSubclass("91310000MA000001X1"), 1),
)
def test_rule_002_rejects_malformed_invoice_buyer_tax_number(
    invalid_invoice_buyer_tax_no: object,
) -> None:
    with pytest.raises(ValueError, match="invoice_buyer_tax_no"):
        evaluate_rule_002(
            "91310000MA000001X1",
            invalid_invoice_buyer_tax_no,  # type: ignore[arg-type]
        )


def test_rule_002_validates_organization_tax_number_before_invoice_fact() -> None:
    with pytest.raises(ValueError, match="organization_tax_number"):
        evaluate_rule_002("", 1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("cumulative_invoice_total", "effective_contract_amount", "expected_status"),
    (
        (Decimal("0"), Decimal("0"), RuleExecutionStatus.PASSED),
        (Decimal("99999.99"), Decimal("100000.00"), RuleExecutionStatus.PASSED),
        (Decimal("100000.00"), Decimal("100000.00"), RuleExecutionStatus.PASSED),
        (Decimal("100000.01"), Decimal("100000.00"), RuleExecutionStatus.FAILED),
        (Decimal("110000.00"), Decimal("100000.00"), RuleExecutionStatus.FAILED),
    ),
)
def test_rule_003_compares_cumulative_total_to_effective_contract_amount(
    cumulative_invoice_total: Decimal,
    effective_contract_amount: Decimal,
    expected_status: RuleExecutionStatus,
) -> None:
    result = evaluate_rule_003(
        True,
        cumulative_invoice_total,
        effective_contract_amount,
    )

    assert result.status is expected_status


@pytest.mark.parametrize(
    ("cumulative_invoice_total", "effective_contract_amount"),
    ((Decimal("110000.00"), Decimal("100000.00")), (None, None)),
)
def test_rule_003_is_not_applicable_without_a_confirmed_primary_contract(
    cumulative_invoice_total: Decimal | None,
    effective_contract_amount: Decimal | None,
) -> None:
    result = evaluate_rule_003(
        False,
        cumulative_invoice_total,
        effective_contract_amount,
    )

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


@pytest.mark.parametrize(
    ("cumulative_invoice_total", "effective_contract_amount"),
    (
        (None, Decimal("100000.00")),
        (Decimal("110000.00"), None),
        (None, None),
    ),
)
def test_rule_003_is_not_applicable_when_an_amount_is_missing(
    cumulative_invoice_total: Decimal | None,
    effective_contract_amount: Decimal | None,
) -> None:
    result = evaluate_rule_003(
        True,
        cumulative_invoice_total,
        effective_contract_amount,
    )

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


class Rule003DecimalSubclass(Decimal):
    pass


@pytest.mark.parametrize("invalid_flag", (None, 0, 1, "true"))
def test_rule_003_rejects_non_exact_contract_flag_before_amounts(
    invalid_flag: object,
) -> None:
    with pytest.raises(ValueError, match="has_confirmed_primary_contract"):
        evaluate_rule_003(invalid_flag, 1, 1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "invalid_amount",
    (
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Rule003DecimalSubclass("1"),
        True,
        1,
        1.0,
        "1.00",
    ),
)
@pytest.mark.parametrize("position", (0, 1))
def test_rule_003_rejects_malformed_amount_before_not_applicable(
    invalid_amount: object,
    position: int,
) -> None:
    amounts: list[object | None] = [None, None]
    amounts[position] = invalid_amount

    with pytest.raises(ValueError, match="finite exact Decimal"):
        evaluate_rule_003(
            False,
            amounts[0],  # type: ignore[arg-type]
            amounts[1],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "invoice_date",
    (
        date(2026, 1, 1),
        date(2026, 3, 15),
        date(2026, 6, 1),
        date(2026, 9, 30),
        date(2026, 12, 31),
    ),
)
def test_rule_004_passes_for_inclusive_contract_interval(invoice_date: date) -> None:
    result = evaluate_rule_004(invoice_date, date(2026, 1, 1), date(2026, 12, 31))

    assert result == RulePredicateResult(RuleExecutionStatus.PASSED)


@pytest.mark.parametrize(
    "invoice_date",
    (
        date(2025, 1, 1),
        date(2025, 12, 30),
        date(2025, 12, 31),
        date(2027, 1, 1),
        date(2030, 1, 1),
    ),
)
def test_rule_004_fails_outside_contract_interval(invoice_date: date) -> None:
    result = evaluate_rule_004(invoice_date, date(2026, 1, 1), date(2026, 12, 31))

    assert result.status is RuleExecutionStatus.FAILED


@pytest.mark.parametrize(
    ("invoice_date", "effective_date", "expiry_date"),
    (
        (None, date(2026, 1, 1), date(2026, 12, 31)),
        (date(2026, 6, 1), None, date(2026, 12, 31)),
        (date(2026, 6, 1), date(2026, 1, 1), None),
    ),
)
def test_rule_004_is_not_applicable_when_any_required_fact_is_missing(
    invoice_date: date | None,
    effective_date: date | None,
    expiry_date: date | None,
) -> None:
    result = evaluate_rule_004(invoice_date, effective_date, expiry_date)

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


def test_rule_004_rejects_an_invalid_contract_interval() -> None:
    with pytest.raises(ValueError, match="effective date"):
        evaluate_rule_004(date(2026, 6, 1), date(2026, 12, 31), date(2026, 1, 1))


def test_rule_004_does_not_hide_an_invalid_interval_behind_a_missing_invoice_date() -> None:
    with pytest.raises(ValueError, match="effective date"):
        evaluate_rule_004(None, date(2026, 12, 31), date(2026, 1, 1))


class DateSubclass(date):
    pass


@pytest.mark.parametrize(
    "invalid_date",
    (
        datetime(2026, 1, 1),
        DateSubclass(2026, 1, 1),
        "2026-01-01",
    ),
)
def test_rule_004_rejects_non_exact_date_values_even_when_another_fact_is_missing(
    invalid_date: object,
) -> None:
    with pytest.raises(ValueError, match="exact datetime.date"):
        evaluate_rule_004(None, invalid_date, None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("has_existing_exact_invoice_identity", "expected_status"),
    (
        (False, RuleExecutionStatus.PASSED),
        (True, RuleExecutionStatus.FAILED),
        (None, RuleExecutionStatus.NOT_APPLICABLE),
    ),
)
def test_rule_005_maps_canonical_duplicate_fact_to_status(
    has_existing_exact_invoice_identity: bool | None,
    expected_status: RuleExecutionStatus,
) -> None:
    result = evaluate_rule_005(has_existing_exact_invoice_identity)

    assert result.status is expected_status


@pytest.mark.parametrize("invalid_fact", (0, 1, "false", Decimal("0")))
def test_rule_005_rejects_non_exact_optional_bool(invalid_fact: object) -> None:
    with pytest.raises(ValueError, match="has_existing_exact_invoice_identity"):
        evaluate_rule_005(invalid_fact)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("presence_facts", "expected_status"),
    (
        ((True, True, True, True), RuleExecutionStatus.PASSED),
        ((False, True, True, True), RuleExecutionStatus.FAILED),
        ((True, False, True, True), RuleExecutionStatus.FAILED),
        ((True, True, False, True), RuleExecutionStatus.FAILED),
        ((True, True, True, False), RuleExecutionStatus.FAILED),
    ),
)
def test_rule_006_checks_each_canonical_contract_presence_fact(
    presence_facts: tuple[bool, bool, bool, bool],
    expected_status: RuleExecutionStatus,
) -> None:
    result = evaluate_rule_006(True, *presence_facts)

    assert result.status is expected_status


@pytest.mark.parametrize(
    "presence_facts",
    ((True, True, True, True), (False, False, False, False)),
)
def test_rule_006_is_not_applicable_without_a_confirmed_primary_contract(
    presence_facts: tuple[bool, bool, bool, bool],
) -> None:
    result = evaluate_rule_006(False, *presence_facts)

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


@pytest.mark.parametrize("invalid_position", range(5))
@pytest.mark.parametrize("invalid_flag", (None, 0, 1, "true"))
def test_rule_006_validates_every_fact_before_not_applicable(
    invalid_position: int,
    invalid_flag: object,
) -> None:
    facts: list[object] = [False, True, True, True, True]
    facts[invalid_position] = invalid_flag

    with pytest.raises(ValueError, match="exact bool"):
        evaluate_rule_006(
            facts[0],  # type: ignore[arg-type]
            facts[1],  # type: ignore[arg-type]
            facts[2],  # type: ignore[arg-type]
            facts[3],  # type: ignore[arg-type]
            facts[4],  # type: ignore[arg-type]
        )


def test_rule_007_passes_when_all_invoice_core_fields_are_present() -> None:
    result = evaluate_rule_007(
        "3100260001",
        "00000001",
        "91310000MA000001X1",
        "91310000MA000002X2",
        date(2026, 8, 8),
        Decimal("0"),
    )

    assert result.status is RuleExecutionStatus.PASSED


@pytest.mark.parametrize("missing_position", range(6))
def test_rule_007_fails_when_any_invoice_core_field_is_missing(missing_position: int) -> None:
    facts: list[object | None] = [
        "3100260001",
        "00000001",
        "91310000MA000001X1",
        "91310000MA000002X2",
        date(2026, 8, 8),
        Decimal("60000.00"),
    ]
    facts[missing_position] = None

    result = evaluate_rule_007(
        facts[0],  # type: ignore[arg-type]
        facts[1],  # type: ignore[arg-type]
        facts[2],  # type: ignore[arg-type]
        facts[3],  # type: ignore[arg-type]
        facts[4],  # type: ignore[arg-type]
        facts[5],  # type: ignore[arg-type]
    )

    assert result.status is RuleExecutionStatus.FAILED


class Rule007StringSubclass(str):
    pass


@pytest.mark.parametrize(
    "invalid_string",
    ("", "   ", Rule007StringSubclass("3100260001"), 1),
)
@pytest.mark.parametrize("position", range(4))
def test_rule_007_rejects_malformed_string_facts_before_missing_result(
    invalid_string: object,
    position: int,
) -> None:
    facts: list[object | None] = ["code", "number", "buyer", None]
    facts[position] = invalid_string

    with pytest.raises(ValueError, match="non-blank exact str"):
        evaluate_rule_007(
            facts[0],  # type: ignore[arg-type]
            facts[1],  # type: ignore[arg-type]
            facts[2],  # type: ignore[arg-type]
            facts[3],  # type: ignore[arg-type]
            None,
            None,
        )


@pytest.mark.parametrize(
    "invalid_date",
    (datetime(2026, 8, 8), DateSubclass(2026, 8, 8), "2026-08-08"),
)
def test_rule_007_rejects_non_exact_date_before_missing_result(invalid_date: object) -> None:
    with pytest.raises(ValueError, match="exact datetime.date"):
        evaluate_rule_007(
            "code",
            "number",
            "buyer",
            "seller",
            invalid_date,  # type: ignore[arg-type]
            None,
        )


class Rule007DecimalSubclass(Decimal):
    pass


@pytest.mark.parametrize(
    "invalid_amount",
    (
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Rule007DecimalSubclass("1"),
        True,
        1,
        1.0,
    ),
)
def test_rule_007_rejects_non_finite_or_non_exact_amount_before_missing_result(
    invalid_amount: object,
) -> None:
    with pytest.raises(ValueError, match="finite exact Decimal"):
        evaluate_rule_007(
            "code",
            "number",
            "buyer",
            "seller",
            None,
            invalid_amount,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("contract_currency", "invoice_currency", "expected_status"),
    (
        ("CNY", "CNY", RuleExecutionStatus.PASSED),
        ("USD", "USD", RuleExecutionStatus.PASSED),
        ("CNY", "USD", RuleExecutionStatus.FAILED),
        ("cny", "CNY", RuleExecutionStatus.FAILED),
        (" CNY ", "CNY", RuleExecutionStatus.FAILED),
    ),
)
def test_rule_008_compares_each_currency_pair_exactly(
    contract_currency: str,
    invoice_currency: str,
    expected_status: RuleExecutionStatus,
) -> None:
    result = evaluate_rule_008_currency_pair(
        True,
        contract_currency,
        invoice_currency,
    )

    assert result.status is expected_status


@pytest.mark.parametrize(
    ("contract_currency", "invoice_currency"),
    ((None, "CNY"), ("CNY", None), (None, None)),
)
def test_rule_008_is_not_applicable_when_a_currency_is_missing(
    contract_currency: str | None,
    invoice_currency: str | None,
) -> None:
    result = evaluate_rule_008_currency_pair(True, contract_currency, invoice_currency)

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


def test_rule_008_is_not_applicable_without_a_confirmed_primary_contract() -> None:
    result = evaluate_rule_008_currency_pair(False, "CNY", "USD")

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


class StringSubclass(str):
    pass


@pytest.mark.parametrize("invalid_flag", (None, 0, 1, "true"))
def test_rule_008_rejects_non_exact_contract_flag(invalid_flag: object) -> None:
    with pytest.raises(ValueError, match="exact bool"):
        evaluate_rule_008_currency_pair(invalid_flag, "CNY", "CNY")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("contract_currency", "invoice_currency"),
    (
        ("", None),
        (None, "   "),
        (StringSubclass("CNY"), "CNY"),
        ("CNY", 1),
    ),
)
def test_rule_008_rejects_malformed_currency_before_not_applicable(
    contract_currency: object,
    invoice_currency: object,
) -> None:
    with pytest.raises(ValueError, match="non-blank exact str"):
        evaluate_rule_008_currency_pair(
            False,
            contract_currency,  # type: ignore[arg-type]
            invoice_currency,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("line_net_amount", "tax_amount", "total_amount"),
    (
        (Decimal("100.00"), Decimal("13.00"), Decimal("113.00")),
        (Decimal("100.00"), Decimal("13.00"), Decimal("112.99")),
        (Decimal("100.00"), Decimal("13.00"), Decimal("113.01")),
        (Decimal("0"), Decimal("0"), Decimal("0")),
        (Decimal("999999999.99"), Decimal("0.01"), Decimal("1000000000.00")),
    ),
)
def test_rule_009_passes_at_or_within_the_absolute_difference_boundary(
    line_net_amount: Decimal,
    tax_amount: Decimal,
    total_amount: Decimal,
) -> None:
    result = evaluate_rule_009(line_net_amount, tax_amount, total_amount)

    assert result.status is RuleExecutionStatus.PASSED


@pytest.mark.parametrize(
    ("line_net_amount", "tax_amount", "total_amount"),
    (
        (Decimal("100.00"), Decimal("13.00"), Decimal("112.989")),
        (Decimal("100.00"), Decimal("13.00"), Decimal("113.011")),
        (Decimal("100.00"), Decimal("0"), Decimal("99.98")),
        (Decimal("0"), Decimal("0"), Decimal("0.0100001")),
        (Decimal("0"), Decimal("0"), Decimal("-0.0100001")),
    ),
)
def test_rule_009_fails_above_the_absolute_difference_boundary(
    line_net_amount: Decimal,
    tax_amount: Decimal,
    total_amount: Decimal,
) -> None:
    result = evaluate_rule_009(line_net_amount, tax_amount, total_amount)

    assert result.status is RuleExecutionStatus.FAILED


def test_rule_009_is_independent_of_the_callers_decimal_precision() -> None:
    with localcontext() as context:
        context.prec = 2
        result = evaluate_rule_009(
            Decimal("100.00"),
            Decimal("13.00"),
            Decimal("113.00"),
        )

    assert result.status is RuleExecutionStatus.PASSED


@pytest.mark.parametrize(
    ("line_net_amount", "tax_amount", "total_amount"),
    (
        (None, Decimal("13.00"), Decimal("113.00")),
        (Decimal("100.00"), None, Decimal("113.00")),
        (Decimal("100.00"), Decimal("13.00"), None),
        (None, None, None),
    ),
)
def test_rule_009_is_not_applicable_when_any_required_fact_is_missing(
    line_net_amount: Decimal | None,
    tax_amount: Decimal | None,
    total_amount: Decimal | None,
) -> None:
    result = evaluate_rule_009(line_net_amount, tax_amount, total_amount)

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


class Rule009DecimalSubclass(Decimal):
    pass


@pytest.mark.parametrize(
    "invalid_amount",
    (
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Rule009DecimalSubclass("1"),
        True,
        1,
        1.0,
    ),
)
@pytest.mark.parametrize("position", (0, 1, 2))
def test_rule_009_rejects_non_finite_or_non_exact_decimal_before_not_applicable(
    invalid_amount: object,
    position: int,
) -> None:
    amounts: list[object | None] = [Decimal("100"), Decimal("13"), None]
    amounts[position] = invalid_amount

    with pytest.raises(ValueError, match="finite exact Decimal"):
        evaluate_rule_009(
            amounts[0],  # type: ignore[arg-type]
            amounts[1],  # type: ignore[arg-type]
            amounts[2],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("has_confirmed_primary_contract", "expected_status"),
    (
        (True, RuleExecutionStatus.PASSED),
        (False, RuleExecutionStatus.FAILED),
    ),
)
def test_rule_010_maps_exact_bool_to_status(
    has_confirmed_primary_contract: bool,
    expected_status: RuleExecutionStatus,
) -> None:
    result = evaluate_rule_010(has_confirmed_primary_contract)

    assert result.status is expected_status


@pytest.mark.parametrize("invalid_flag", (None, 0, 1, "false"))
def test_rule_010_rejects_non_exact_bool(invalid_flag: object) -> None:
    with pytest.raises(ValueError, match="exact bool"):
        evaluate_rule_010(invalid_flag)  # type: ignore[arg-type]


@pytest.mark.parametrize("contract_no", ("CN-001", "合同-2026-001", "0", "A B", "A/B"))
def test_rule_011_passes_for_an_exact_non_blank_contract_number(contract_no: str) -> None:
    result = evaluate_rule_011(True, contract_no)

    assert result.status is RuleExecutionStatus.PASSED


def test_rule_011_fails_when_confirmed_contract_number_is_missing() -> None:
    result = evaluate_rule_011(True, None)

    assert result.status is RuleExecutionStatus.FAILED


@pytest.mark.parametrize("contract_no", (None, "CN-001"))
def test_rule_011_is_not_applicable_without_a_confirmed_primary_contract(
    contract_no: str | None,
) -> None:
    result = evaluate_rule_011(False, contract_no)

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


@pytest.mark.parametrize("invalid_flag", (None, 0, 1, "true"))
def test_rule_011_rejects_non_exact_contract_flag(invalid_flag: object) -> None:
    with pytest.raises(ValueError, match="exact bool"):
        evaluate_rule_011(invalid_flag, None)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_contract_no", ("", "\t", StringSubclass("CN-001"), 1))
def test_rule_011_rejects_malformed_contract_number_before_not_applicable(
    invalid_contract_no: object,
) -> None:
    with pytest.raises(ValueError, match="non-blank exact str"):
        evaluate_rule_011(False, invalid_contract_no)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    (
        "has_confirmed_primary_contract",
        "has_effective_unconfirmed_supplementary_agreement",
        "expected_status",
    ),
    (
        (True, False, RuleExecutionStatus.PASSED),
        (True, True, RuleExecutionStatus.FAILED),
        (False, False, RuleExecutionStatus.NOT_APPLICABLE),
        (False, True, RuleExecutionStatus.NOT_APPLICABLE),
    ),
)
def test_rule_012_maps_canonical_supplementary_agreement_facts_to_status(
    has_confirmed_primary_contract: bool,
    has_effective_unconfirmed_supplementary_agreement: bool,
    expected_status: RuleExecutionStatus,
) -> None:
    result = evaluate_rule_012(
        has_confirmed_primary_contract,
        has_effective_unconfirmed_supplementary_agreement,
    )

    assert result.status is expected_status


@pytest.mark.parametrize("invalid_flag", (None, 0, 1, "true"))
def test_rule_012_rejects_non_exact_contract_flag(invalid_flag: object) -> None:
    with pytest.raises(ValueError, match="has_confirmed_primary_contract"):
        evaluate_rule_012(invalid_flag, False)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_flag", (None, 0, 1, "false"))
def test_rule_012_validates_agreement_fact_before_not_applicable(invalid_flag: object) -> None:
    with pytest.raises(
        ValueError,
        match="has_effective_unconfirmed_supplementary_agreement",
    ):
        evaluate_rule_012(False, invalid_flag)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    (
        "requires_policy_citation",
        "retrieval_completed_successfully",
        "has_applicable_policy_citation",
        "expected_status",
    ),
    (
        (True, True, True, RuleExecutionStatus.PASSED),
        (True, True, False, RuleExecutionStatus.FAILED),
        (False, True, False, RuleExecutionStatus.NOT_APPLICABLE),
        (False, False, False, RuleExecutionStatus.NOT_APPLICABLE),
        (True, False, False, RuleExecutionStatus.NOT_APPLICABLE),
        (True, False, True, RuleExecutionStatus.NOT_APPLICABLE),
    ),
)
def test_rule_013_distinguishes_missing_citation_from_retrieval_degradation(
    requires_policy_citation: bool,
    retrieval_completed_successfully: bool,
    has_applicable_policy_citation: bool,
    expected_status: RuleExecutionStatus,
) -> None:
    result = evaluate_rule_013(
        requires_policy_citation,
        retrieval_completed_successfully,
        has_applicable_policy_citation,
    )

    assert result.status is expected_status


@pytest.mark.parametrize("invalid_position", range(3))
@pytest.mark.parametrize("invalid_flag", (None, 0, 1, "false"))
def test_rule_013_validates_every_fact_before_not_applicable(
    invalid_position: int,
    invalid_flag: object,
) -> None:
    facts: list[object] = [False, False, False]
    facts[invalid_position] = invalid_flag

    with pytest.raises(ValueError, match="exact bool"):
        evaluate_rule_013(
            facts[0],  # type: ignore[arg-type]
            facts[1],  # type: ignore[arg-type]
            facts[2],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("standard_name_a", "standard_name_b", "tax_identity_a", "tax_identity_b", "status"),
    (
        (
            "示例服务有限公司",
            "示例服务有限公司",
            "91310000MA000001X1",
            "91310000MA000001X1",
            RuleExecutionStatus.PASSED,
        ),
        (
            "示例服务有限公司",
            "示例服务有限公司",
            "91310000MA000001X1",
            "91310000MA000002X2",
            RuleExecutionStatus.FAILED,
        ),
        (
            "示例服务有限公司",
            "另一服务有限公司",
            "91310000MA000001X1",
            "91310000MA000002X2",
            RuleExecutionStatus.PASSED,
        ),
        (
            "Example Ltd",
            "example ltd",
            "91310000MA000001X1",
            "91310000MA000002X2",
            RuleExecutionStatus.PASSED,
        ),
        (
            "示例服务有限公司",
            "示例服务有限公司 ",
            "91310000MA000001X1",
            "91310000MA000002X2",
            RuleExecutionStatus.PASSED,
        ),
    ),
)
def test_rule_014_compares_upstream_standardized_facts_exactly(
    standard_name_a: str,
    standard_name_b: str,
    tax_identity_a: str,
    tax_identity_b: str,
    status: RuleExecutionStatus,
) -> None:
    result = evaluate_rule_014_identity_pair(
        standard_name_a,
        standard_name_b,
        tax_identity_a,
        tax_identity_b,
    )

    assert result.status is status


@pytest.mark.parametrize("missing_position", range(4))
def test_rule_014_is_not_applicable_when_any_identity_fact_is_missing(
    missing_position: int,
) -> None:
    facts: list[str | None] = [
        "示例服务有限公司",
        "示例服务有限公司",
        "91310000MA000001X1",
        "91310000MA000002X2",
    ]
    facts[missing_position] = None

    result = evaluate_rule_014_identity_pair(*facts)

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


class Rule014StringSubclass(str):
    pass


@pytest.mark.parametrize("invalid_position", range(4))
@pytest.mark.parametrize(
    "invalid_value",
    ("", "\t", Rule014StringSubclass("示例服务有限公司"), 1),
)
def test_rule_014_validates_every_fact_before_not_applicable(
    invalid_position: int,
    invalid_value: object,
) -> None:
    facts: list[object | None] = [None, None, None, None]
    facts[invalid_position] = invalid_value

    with pytest.raises(ValueError, match="non-blank exact str"):
        evaluate_rule_014_identity_pair(
            facts[0],  # type: ignore[arg-type]
            facts[1],  # type: ignore[arg-type]
            facts[2],  # type: ignore[arg-type]
            facts[3],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "total_amount",
    (
        Decimal("0.01"),
        Decimal("1.00"),
        Decimal("10.00"),
        Decimal("100.00"),
        Decimal("999999999.99"),
    ),
)
def test_rule_015_passes_for_positive_normal_invoice(total_amount: Decimal) -> None:
    result = evaluate_rule_015(total_amount, is_red_invoice=False)

    assert result.status is RuleExecutionStatus.PASSED


@pytest.mark.parametrize(
    "total_amount",
    (
        Decimal("0"),
        Decimal("-0"),
        Decimal("-0.01"),
        Decimal("-1.00"),
        Decimal("-999999999.99"),
    ),
)
def test_rule_015_fails_for_non_positive_normal_invoice(total_amount: Decimal) -> None:
    result = evaluate_rule_015(total_amount, is_red_invoice=False)

    assert result.status is RuleExecutionStatus.FAILED


@pytest.mark.parametrize("total_amount", (Decimal("100"), Decimal("0"), Decimal("-100")))
def test_rule_015_is_not_applicable_to_red_invoice(total_amount: Decimal) -> None:
    result = evaluate_rule_015(total_amount, is_red_invoice=True)

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


@pytest.mark.parametrize(
    ("total_amount", "is_red_invoice"),
    (
        (None, False),
        (Decimal("1"), None),
        (None, None),
    ),
)
def test_rule_015_is_not_applicable_when_a_required_fact_is_missing(
    total_amount: Decimal | None,
    is_red_invoice: bool | None,
) -> None:
    result = evaluate_rule_015(total_amount, is_red_invoice=is_red_invoice)

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE


class DecimalSubclass(Decimal):
    pass


@pytest.mark.parametrize(
    "invalid_amount",
    (
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        DecimalSubclass("1"),
        True,
        1,
        1.0,
    ),
)
def test_rule_015_rejects_non_finite_or_non_exact_decimal(invalid_amount: object) -> None:
    with pytest.raises(ValueError, match="finite exact Decimal"):
        evaluate_rule_015(invalid_amount, is_red_invoice=False)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_flag", (0, 1, "false"))
def test_rule_015_rejects_non_exact_bool(invalid_flag: object) -> None:
    with pytest.raises(ValueError, match="exact bool"):
        evaluate_rule_015(Decimal("1"), is_red_invoice=invalid_flag)  # type: ignore[arg-type]


def test_rule_predicate_result_is_strict_and_immutable() -> None:
    result = RulePredicateResult(RuleExecutionStatus.PASSED)

    with pytest.raises(FrozenInstanceError):
        result.status = RuleExecutionStatus.FAILED  # type: ignore[misc]
    with pytest.raises(ValueError, match="RuleExecutionStatus"):
        RulePredicateResult("passed")  # type: ignore[arg-type]
