from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from app.core.errors import AppError
from app.repositories.financial_read import (
    ContractFieldReadView,
    ContractReadView,
    EffectiveContractReadView,
    SupplementaryChangeReadView,
)
from app.services.effective_contract_query import project_effective_contract

ORG = UUID("6a000000-0000-4000-8000-000000000001")
CONTRACT = UUID("6a000000-0000-4000-8000-000000000002")
AGREEMENT = UUID("6a000000-0000-4000-8000-000000000003")
AGREEMENT_2 = UUID("6a000000-0000-4000-8000-000000000004")


def _contract() -> ContractReadView:
    return ContractReadView(
        id=CONTRACT,
        organization_id=ORG,
        contract_no="HT-1",
        name="合同",
        party_a_name="甲方",
        party_a_tax_no="A-TAX",
        party_b_name="乙方",
        party_b_tax_no="B-TAX",
        supplier_id=None,
        amount=Decimal("100.00"),
        currency="CNY",
        signed_date=date(2026, 1, 1),
        effective_date=date(2026, 1, 1),
        expiry_date=date(2026, 12, 31),
        payment_method="bank",
        payment_terms="原付款条款",
        confirmation_status="confirmed",
        status="active",
        confirmed_by=None,
        confirmed_at=None,
        critical_fact_hash="a" * 64,
        row_version=3,
    )


def _change(
    agreement_id: UUID = AGREEMENT,
    *,
    field_code: str = "expiry_date",
    value_type: str = "date",
    new_value: object = "2027-03-31",
    effective_date: date = date(2026, 12, 1),
    status: str = "confirmed",
) -> SupplementaryChangeReadView:
    return SupplementaryChangeReadView(
        agreement_id=agreement_id,
        field_code=field_code,
        value_type=value_type,
        new_value=new_value,
        agreement_status=status,
        agreement_confirmation_status="confirmed",
        change_confirmation_status="confirmed",
        effective_date=effective_date,
    )


def test_effective_contract_keeps_original_and_applies_whole_confirmed_agreement() -> None:
    view = EffectiveContractReadView(
        contract=_contract(),
        extended_fields=(ContractFieldReadView("clause.audit", "string", "原条款"),),
        changes=(
            _change(),
            _change(
                field_code="amount",
                value_type="number",
                new_value=Decimal("120.50"),
            ),
        ),
    )

    before = project_effective_contract(view, date(2026, 11, 30))
    after = project_effective_contract(view, date(2026, 12, 1))
    before_by_code = {item.field_code: item for item in before.fields}
    after_by_code = {item.field_code: item for item in after.fields}

    assert before_by_code["expiry_date"].effective_value == "2026-12-31"
    assert after_by_code["expiry_date"].original_value == "2026-12-31"
    assert after_by_code["expiry_date"].effective_value == "2027-03-31"
    assert after_by_code["amount"].original_value == "100.00"
    assert after_by_code["amount"].effective_value == "120.50"
    assert after_by_code["clause.audit"].effective_value == "原条款"
    assert after.applied_agreement_ids == (AGREEMENT,)


def test_effective_contract_accepts_identical_core_field_evidence_mirrors() -> None:
    view = EffectiveContractReadView(
        contract=_contract(),
        extended_fields=(
            ContractFieldReadView("contract_no", "string", "HT-1"),
            ContractFieldReadView("amount", "number", "100.00"),
            ContractFieldReadView("effective_date", "date", "2026-01-01"),
        ),
        changes=(),
    )

    result = project_effective_contract(view, date(2026, 5, 1))
    values = {item.field_code: item.effective_value for item in result.fields}

    assert values["contract_no"] == "HT-1"
    assert values["amount"] == "100.00"
    assert values["effective_date"] == "2026-01-01"


@pytest.mark.parametrize(
    "mirror",
    [
        ContractFieldReadView("amount", "string", "100.00"),
        ContractFieldReadView("amount", "number", "100.01"),
    ],
)
def test_effective_contract_rejects_inconsistent_core_field_mirror(
    mirror: ContractFieldReadView,
) -> None:
    with pytest.raises(RuntimeError, match="core field mirror is inconsistent"):
        project_effective_contract(
            EffectiveContractReadView(_contract(), (mirror,), ()),
            date(2026, 5, 1),
        )


def test_effective_contract_does_not_partially_apply_unconfirmed_agreement() -> None:
    confirmed = _change()
    unconfirmed = SupplementaryChangeReadView(
        agreement_id=AGREEMENT,
        field_code="amount",
        value_type="number",
        new_value=Decimal("120"),
        agreement_status="confirmed",
        agreement_confirmation_status="confirmed",
        change_confirmation_status="unconfirmed",
        effective_date=date(2026, 12, 1),
    )
    result = project_effective_contract(
        EffectiveContractReadView(_contract(), (), (confirmed, unconfirmed)),
        date(2027, 1, 1),
    )
    projected = {item.field_code: item.effective_value for item in result.fields}

    assert projected["expiry_date"] == "2026-12-31"
    assert projected["amount"] == "100.00"
    assert result.applied_agreement_ids == ()


def test_effective_contract_maps_same_field_same_day_conflict_to_stable_409() -> None:
    view = EffectiveContractReadView(
        _contract(),
        (),
        (
            _change(),
            _change(AGREEMENT_2, new_value="2027-06-30"),
        ),
    )

    with pytest.raises(AppError) as captured:
        project_effective_contract(view, date(2027, 1, 1))

    assert captured.value.status_code == 409
    assert captured.value.code == "EFFECTIVE_FIELD_CONFLICT"


@pytest.mark.parametrize(
    "change",
    [
        _change(field_code="unknown"),
        _change(field_code="amount", value_type="string", new_value="100"),
    ],
)
def test_effective_contract_rejects_unknown_or_mismatched_change(change: object) -> None:
    assert isinstance(change, SupplementaryChangeReadView)
    with pytest.raises(RuntimeError):
        project_effective_contract(
            EffectiveContractReadView(
                _contract(),
                (),
                (change,),
            ),
            date(2027, 1, 1),
        )
