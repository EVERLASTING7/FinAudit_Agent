from dataclasses import FrozenInstanceError
from datetime import date, datetime
from enum import Enum
from uuid import UUID

import pytest

from app.rules.contract_invoice_matching import (
    ContractInvoiceCandidate,
    ContractInvoiceMatchReason,
    ContractInvoiceMatchReasons,
    ContractInvoiceReasonCode,
    ContractMatchFacts,
    InvoiceMatchFacts,
    MatchEvidenceStatus,
    derive_contract_invoice_candidates,
    derive_contract_invoice_match_reasons,
)

_DEFAULT_INVOICE_ID = UUID(int=100)
_DEFAULT_CONTRACT_ID = UUID(int=1)


def _valid_facts() -> list[object]:
    return [
        "91310000MA000002X2",
        "91310000MA000002X2",
        "示例服务有限公司",
        "示例服务有限公司",
        date(2026, 6, 1),
        date(2026, 1, 1),
        date(2026, 12, 31),
    ]


def _derive(facts: list[object]) -> ContractInvoiceMatchReasons:
    return derive_contract_invoice_match_reasons(
        facts[0],  # type: ignore[arg-type]
        facts[1],  # type: ignore[arg-type]
        facts[2],  # type: ignore[arg-type]
        facts[3],  # type: ignore[arg-type]
        facts[4],  # type: ignore[arg-type]
        facts[5],  # type: ignore[arg-type]
        facts[6],  # type: ignore[arg-type]
    )


def test_derives_three_true_independent_reasons_and_returns_frozen_result() -> None:
    result = _derive(_valid_facts())

    assert result == ContractInvoiceMatchReasons(
        tax_no_match=True,
        name_match=True,
        date_in_range=True,
    )
    with pytest.raises(FrozenInstanceError):
        result.tax_no_match = False  # type: ignore[misc]


@pytest.mark.parametrize(
    ("position", "different_value", "expected"),
    (
        (1, "91310000MA000099X9", ContractInvoiceMatchReasons(False, True, True)),
        (3, "另一供应商有限公司", ContractInvoiceMatchReasons(True, False, True)),
        (4, date(2027, 1, 1), ContractInvoiceMatchReasons(True, True, False)),
    ),
)
def test_each_match_reason_can_be_false_independently(
    position: int,
    different_value: object,
    expected: ContractInvoiceMatchReasons,
) -> None:
    facts = _valid_facts()
    facts[position] = different_value

    assert _derive(facts) == expected


def test_compares_text_verbatim_without_inventing_upstream_normalization() -> None:
    facts = _valid_facts()
    facts[0] = " TAX "
    facts[1] = "TAX"
    facts[2] = "Cafe\u0301"
    facts[3] = "Café"

    result = _derive(facts)

    assert result.tax_no_match is False
    assert result.name_match is False


@pytest.mark.parametrize("invoice_date", (date(2026, 1, 1), date(2026, 12, 31)))
def test_date_range_is_inclusive_at_both_boundaries(invoice_date: date) -> None:
    facts = _valid_facts()
    facts[4] = invoice_date

    assert _derive(facts).date_in_range is True


def test_rejects_an_invalid_contract_interval() -> None:
    facts = _valid_facts()
    facts[5] = date(2026, 12, 31)
    facts[6] = date(2026, 1, 1)

    with pytest.raises(ValueError, match="effective date"):
        _derive(facts)


class StringSubclass(str):
    pass


@pytest.mark.parametrize("position", range(4))
@pytest.mark.parametrize("invalid_value", ("", "   ", StringSubclass("normalized"), 1))
def test_rejects_each_malformed_text_fact(
    position: int,
    invalid_value: object,
) -> None:
    facts = _valid_facts()
    facts[position] = invalid_value

    with pytest.raises(ValueError, match="non-blank exact str"):
        _derive(facts)


class DateSubclass(date):
    pass


@pytest.mark.parametrize("position", (4, 5, 6))
@pytest.mark.parametrize(
    "invalid_value",
    (datetime(2026, 6, 1), DateSubclass(2026, 6, 1), "2026-06-01", 1),
)
def test_rejects_each_non_exact_date_fact(
    position: int,
    invalid_value: object,
) -> None:
    facts = _valid_facts()
    facts[position] = invalid_value

    with pytest.raises(ValueError, match="exact datetime.date"):
        _derive(facts)


def test_validates_text_before_dates_and_contract_interval() -> None:
    facts = _valid_facts()
    facts[0] = ""
    facts[4] = datetime(2026, 6, 1)
    facts[5] = date(2026, 12, 31)
    facts[6] = date(2026, 1, 1)

    with pytest.raises(ValueError, match="contract_party_b_tax_no"):
        _derive(facts)


def test_validates_dates_before_contract_interval() -> None:
    facts = _valid_facts()
    facts[4] = datetime(2026, 6, 1)
    facts[5] = date(2026, 12, 31)
    facts[6] = date(2026, 1, 1)

    with pytest.raises(ValueError, match="invoice_date"):
        _derive(facts)


@pytest.mark.parametrize("invalid_value", (0, 1, "true"))
def test_match_reasons_dto_rejects_non_exact_bool(invalid_value: object) -> None:
    with pytest.raises(ValueError, match="exact bool"):
        ContractInvoiceMatchReasons(invalid_value, True, True)  # type: ignore[arg-type]


def _invoice_match_facts(
    *,
    invoice_id: UUID = _DEFAULT_INVOICE_ID,
    seller_tax_no: str | None = "91310000MA000002X2",
    seller_name: str | None = "示例服务有限公司",
    invoice_date: date | None = date(2026, 6, 1),
) -> InvoiceMatchFacts:
    return InvoiceMatchFacts(
        invoice_id=invoice_id,
        seller_tax_no=seller_tax_no,
        seller_name=seller_name,
        invoice_date=invoice_date,
    )


def _contract_match_facts(
    *,
    contract_id: UUID = _DEFAULT_CONTRACT_ID,
    party_b_tax_no: str | None = "91310000MA000002X2",
    party_b_name: str | None = "示例服务有限公司",
    effective_date: date | None = date(2026, 1, 1),
    expiry_date: date | None = date(2026, 12, 31),
) -> ContractMatchFacts:
    return ContractMatchFacts(
        contract_id=contract_id,
        party_b_tax_no=party_b_tax_no,
        party_b_name=party_b_name,
        effective_date=effective_date,
        expiry_date=expiry_date,
    )


def test_candidates_preserve_exact_facts_and_explain_all_matches() -> None:
    invoice = _invoice_match_facts()
    contract = _contract_match_facts()

    result = derive_contract_invoice_candidates(invoice, (contract,))

    assert len(result) == 1
    candidate = result[0]
    assert candidate == ContractInvoiceCandidate(
        invoice_id=invoice.invoice_id,
        contract_id=contract.contract_id,
        tax_no_reason=ContractInvoiceMatchReason(
            MatchEvidenceStatus.MATCHED,
            ContractInvoiceReasonCode.TAX_NO_MATCHED,
        ),
        name_reason=ContractInvoiceMatchReason(
            MatchEvidenceStatus.MATCHED,
            ContractInvoiceReasonCode.NAME_MATCHED,
        ),
        date_reason=ContractInvoiceMatchReason(
            MatchEvidenceStatus.MATCHED,
            ContractInvoiceReasonCode.DATE_IN_RANGE,
        ),
        contract_party_b_tax_no=contract.party_b_tax_no,
        invoice_seller_tax_no=invoice.seller_tax_no,
        contract_party_b_name=contract.party_b_name,
        invoice_seller_name=invoice.seller_name,
        invoice_date=invoice.invoice_date,
        contract_effective_date=contract.effective_date,
        contract_expiry_date=contract.expiry_date,
    )
    assert not hasattr(candidate, "score")
    assert not hasattr(candidate, "is_primary_contract")


def test_candidates_distinguish_mismatch_from_unavailable_facts() -> None:
    invoice = _invoice_match_facts(seller_name=None)
    contract = _contract_match_facts(
        party_b_tax_no="91310000MA000099X9",
        effective_date=None,
    )

    candidate = derive_contract_invoice_candidates(invoice, (contract,))[0]

    assert candidate.tax_no_reason == ContractInvoiceMatchReason(
        MatchEvidenceStatus.MISMATCHED,
        ContractInvoiceReasonCode.TAX_NO_MISMATCHED,
    )
    assert candidate.name_reason == ContractInvoiceMatchReason(
        MatchEvidenceStatus.UNAVAILABLE,
        ContractInvoiceReasonCode.NAME_UNAVAILABLE,
    )
    assert candidate.date_reason == ContractInvoiceMatchReason(
        MatchEvidenceStatus.UNAVAILABLE,
        ContractInvoiceReasonCode.DATE_UNAVAILABLE,
    )


@pytest.mark.parametrize(
    ("invoice_tax_no", "contract_tax_no"),
    ((None, "TAX"), ("TAX", None), (None, None)),
)
def test_missing_tax_fact_on_either_side_is_unavailable_not_mismatched(
    invoice_tax_no: str | None,
    contract_tax_no: str | None,
) -> None:
    invoice = _invoice_match_facts(seller_tax_no=invoice_tax_no)
    contract = _contract_match_facts(party_b_tax_no=contract_tax_no)

    candidate = derive_contract_invoice_candidates(invoice, (contract,))[0]

    assert candidate.tax_no_reason == ContractInvoiceMatchReason(
        MatchEvidenceStatus.UNAVAILABLE,
        ContractInvoiceReasonCode.TAX_NO_UNAVAILABLE,
    )


def test_candidates_compare_upstream_text_verbatim_without_normalizing() -> None:
    invoice = _invoice_match_facts(
        seller_tax_no="TAX",
        seller_name="Café",
    )
    contract = _contract_match_facts(
        party_b_tax_no=" TAX ",
        party_b_name="Cafe\u0301",
    )

    candidate = derive_contract_invoice_candidates(invoice, (contract,))[0]

    assert candidate.tax_no_reason == ContractInvoiceMatchReason(
        MatchEvidenceStatus.MISMATCHED,
        ContractInvoiceReasonCode.TAX_NO_MISMATCHED,
    )
    assert candidate.name_reason == ContractInvoiceMatchReason(
        MatchEvidenceStatus.MISMATCHED,
        ContractInvoiceReasonCode.NAME_MISMATCHED,
    )


@pytest.mark.parametrize("invoice_date", (date(2026, 1, 1), date(2026, 12, 31)))
def test_candidate_date_match_is_inclusive_at_both_boundaries(invoice_date: date) -> None:
    invoice = _invoice_match_facts(invoice_date=invoice_date)

    candidate = derive_contract_invoice_candidates(invoice, (_contract_match_facts(),))[0]

    assert candidate.date_reason == ContractInvoiceMatchReason(
        MatchEvidenceStatus.MATCHED,
        ContractInvoiceReasonCode.DATE_IN_RANGE,
    )


def test_candidate_date_outside_contract_range_is_an_explicit_mismatch() -> None:
    invoice = _invoice_match_facts(invoice_date=date(2027, 1, 1))

    candidate = derive_contract_invoice_candidates(invoice, (_contract_match_facts(),))[0]

    assert candidate.date_reason == ContractInvoiceMatchReason(
        MatchEvidenceStatus.MISMATCHED,
        ContractInvoiceReasonCode.DATE_OUT_OF_RANGE,
    )


def test_candidate_sort_uses_tax_then_name_then_date_then_contract_uuid() -> None:
    invoice = _invoice_match_facts()
    matched_tie_later = _contract_match_facts(contract_id=UUID(int=2))
    matched_tie_earlier = _contract_match_facts(contract_id=UUID(int=1))
    date_unavailable = _contract_match_facts(
        contract_id=UUID(int=3),
        effective_date=None,
    )
    name_mismatched = _contract_match_facts(
        contract_id=UUID(int=4),
        party_b_name="另一服务有限公司",
    )
    tax_mismatched = _contract_match_facts(
        contract_id=UUID(int=5),
        party_b_tax_no="91310000MA000099X9",
    )
    tax_unavailable = _contract_match_facts(
        contract_id=UUID(int=6),
        party_b_tax_no=None,
    )
    contracts = (
        tax_unavailable,
        tax_mismatched,
        name_mismatched,
        date_unavailable,
        matched_tie_later,
        matched_tie_earlier,
    )

    result = derive_contract_invoice_candidates(invoice, contracts)

    assert tuple(candidate.contract_id for candidate in result) == (
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
        UUID(int=5),
        UUID(int=6),
    )
    assert derive_contract_invoice_candidates(invoice, tuple(reversed(contracts))) == result


def test_candidate_derivation_returns_an_empty_tuple_for_no_contracts() -> None:
    assert derive_contract_invoice_candidates(_invoice_match_facts(), ()) == ()


def test_candidate_derivation_does_not_mutate_immutable_inputs_or_results() -> None:
    invoice = _invoice_match_facts()
    contract = _contract_match_facts()
    contracts = (contract,)

    result = derive_contract_invoice_candidates(invoice, contracts)

    assert contracts == (contract,)
    with pytest.raises(FrozenInstanceError):
        InvoiceMatchFacts.__setattr__(invoice, "seller_name", "已修改")
    with pytest.raises(FrozenInstanceError):
        ContractMatchFacts.__setattr__(contract, "party_b_name", "已修改")
    with pytest.raises(FrozenInstanceError):
        ContractInvoiceCandidate.__setattr__(result[0], "contract_id", UUID(int=9))
    with pytest.raises(FrozenInstanceError):
        ContractInvoiceMatchReason.__setattr__(
            result[0].tax_no_reason,
            "status",
            MatchEvidenceStatus.MISMATCHED,
        )


def test_candidate_and_input_repr_hide_sensitive_comparison_strings() -> None:
    sensitive_tax_no = "SENSITIVE-TAX-NUMBER"
    sensitive_name = "SENSITIVE-COMPANY-NAME"
    invoice = _invoice_match_facts(
        seller_tax_no=sensitive_tax_no,
        seller_name=sensitive_name,
    )
    contract = _contract_match_facts(
        party_b_tax_no=sensitive_tax_no,
        party_b_name=sensitive_name,
    )

    candidate = derive_contract_invoice_candidates(invoice, (contract,))[0]

    for rendered in (repr(invoice), repr(contract), repr(candidate)):
        assert sensitive_tax_no not in rendered
        assert sensitive_name not in rendered
    assert candidate.invoice_seller_tax_no == sensitive_tax_no
    assert candidate.contract_party_b_name == sensitive_name


class UuidSubclass(UUID):
    pass


@pytest.mark.parametrize("invalid_id", ("id", 1, UuidSubclass(int=1)))
def test_input_facts_reject_non_exact_uuid_values(invalid_id: object) -> None:
    with pytest.raises(ValueError, match="invoice_id must be an exact UUID"):
        InvoiceMatchFacts(
            invoice_id=invalid_id,  # type: ignore[arg-type]
            seller_tax_no=None,
            seller_name=None,
            invoice_date=None,
        )
    with pytest.raises(ValueError, match="contract_id must be an exact UUID"):
        ContractMatchFacts(
            contract_id=invalid_id,  # type: ignore[arg-type]
            party_b_tax_no=None,
            party_b_name=None,
            effective_date=None,
            expiry_date=None,
        )


@pytest.mark.parametrize("invalid_text", ("", "   ", StringSubclass("value"), 1))
def test_input_facts_reject_malformed_optional_text(invalid_text: object) -> None:
    with pytest.raises(ValueError, match="seller_tax_no"):
        InvoiceMatchFacts(
            invoice_id=UUID(int=1),
            seller_tax_no=invalid_text,  # type: ignore[arg-type]
            seller_name=None,
            invoice_date=None,
        )
    with pytest.raises(ValueError, match="party_b_name"):
        ContractMatchFacts(
            contract_id=UUID(int=2),
            party_b_tax_no=None,
            party_b_name=invalid_text,  # type: ignore[arg-type]
            effective_date=None,
            expiry_date=None,
        )


@pytest.mark.parametrize(
    "invalid_date",
    (datetime(2026, 1, 1), DateSubclass(2026, 1, 1), "2026-01-01"),
)
def test_input_facts_reject_non_exact_optional_dates(invalid_date: object) -> None:
    with pytest.raises(ValueError, match="invoice_date"):
        _invoice_match_facts(invoice_date=invalid_date)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="effective_date"):
        _contract_match_facts(effective_date=invalid_date)  # type: ignore[arg-type]


def test_contract_facts_reject_an_invalid_complete_date_interval() -> None:
    with pytest.raises(ValueError, match="effective date"):
        _contract_match_facts(
            effective_date=date(2026, 12, 31),
            expiry_date=date(2026, 1, 1),
        )


@pytest.mark.parametrize("invalid_contracts", ([], "contracts", ("contract",), None))
def test_candidate_derivation_rejects_non_exact_contract_tuples(
    invalid_contracts: object,
) -> None:
    with pytest.raises(ValueError, match="tuple of ContractMatchFacts"):
        derive_contract_invoice_candidates(
            _invoice_match_facts(),
            invalid_contracts,  # type: ignore[arg-type]
        )


def test_candidate_derivation_rejects_duplicate_contract_ids() -> None:
    with pytest.raises(ValueError, match="contract_id must be unique"):
        derive_contract_invoice_candidates(
            _invoice_match_facts(),
            (
                _contract_match_facts(contract_id=UUID(int=1)),
                _contract_match_facts(contract_id=UUID(int=1), party_b_name="另一名称"),
            ),
        )


def test_candidate_derivation_rejects_non_exact_invoice_contract() -> None:
    with pytest.raises(ValueError, match="InvoiceMatchFacts"):
        derive_contract_invoice_candidates(  # type: ignore[arg-type]
            "invoice",
            (),
        )


class UnrelatedStatus(str, Enum):
    MATCHED = "matched"


def test_reason_contract_rejects_non_exact_or_inconsistent_enum_pairs() -> None:
    with pytest.raises(ValueError, match="MatchEvidenceStatus"):
        ContractInvoiceMatchReason(  # type: ignore[arg-type]
            UnrelatedStatus.MATCHED,
            ContractInvoiceReasonCode.TAX_NO_MATCHED,
        )
    with pytest.raises(ValueError, match="ContractInvoiceReasonCode"):
        ContractInvoiceMatchReason(  # type: ignore[arg-type]
            MatchEvidenceStatus.MATCHED,
            "tax_no_matched",
        )
    with pytest.raises(ValueError, match="must match"):
        ContractInvoiceMatchReason(
            MatchEvidenceStatus.MISMATCHED,
            ContractInvoiceReasonCode.TAX_NO_MATCHED,
        )
