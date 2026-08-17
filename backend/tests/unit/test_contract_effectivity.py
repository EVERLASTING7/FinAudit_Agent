from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import cast
from uuid import UUID

import pytest
from pydantic import TypeAdapter

from app.schemas.business_statuses import ConfirmationStatus
from app.services.contract_effectivity import (
    EffectiveFieldSource,
    SupplementaryAgreementStatus,
    SupplementaryFieldChange,
    is_supplementary_change_effective,
    project_effective_fields,
)

EFFECTIVE_DATE = date(2026, 12, 1)
AGREEMENT_A = UUID("31000000-0000-0000-0000-000000000001")
AGREEMENT_B = UUID("31000000-0000-0000-0000-000000000002")
AGREEMENT_C = UUID("31000000-0000-0000-0000-000000000003")


def is_effective(
    *,
    agreement_status: SupplementaryAgreementStatus = SupplementaryAgreementStatus.CONFIRMED,
    agreement_confirmation_status: ConfirmationStatus = ConfirmationStatus.CONFIRMED,
    change_confirmation_status: ConfirmationStatus = ConfirmationStatus.CONFIRMED,
    effective_date: date = EFFECTIVE_DATE,
    baseline_date: date = EFFECTIVE_DATE,
) -> bool:
    return is_supplementary_change_effective(
        agreement_status=agreement_status,
        agreement_confirmation_status=agreement_confirmation_status,
        change_confirmation_status=change_confirmation_status,
        effective_date=effective_date,
        baseline_date=baseline_date,
    )


def field_change(
    *,
    agreement_id: UUID = AGREEMENT_A,
    field_code: str = "expiry_date",
    new_value: object = "2027-03-31",
    agreement_status: SupplementaryAgreementStatus = SupplementaryAgreementStatus.CONFIRMED,
    agreement_confirmation_status: ConfirmationStatus = ConfirmationStatus.CONFIRMED,
    change_confirmation_status: ConfirmationStatus = ConfirmationStatus.CONFIRMED,
    effective_date: date = EFFECTIVE_DATE,
) -> SupplementaryFieldChange:
    return SupplementaryFieldChange(
        agreement_id=agreement_id,
        field_code=field_code,
        new_value=new_value,
        agreement_status=agreement_status,
        agreement_confirmation_status=agreement_confirmation_status,
        change_confirmation_status=change_confirmation_status,
        effective_date=effective_date,
    )


def test_status_enums_are_exact() -> None:
    assert tuple(status.value for status in ConfirmationStatus) == (
        "unconfirmed",
        "confirmed",
        "rejected",
    )
    assert tuple(status.value for status in SupplementaryAgreementStatus) == (
        "draft",
        "pending_confirmation",
        "confirmed",
        "rejected",
        "archived",
    )


@pytest.mark.parametrize(
    ("baseline_date", "expected"),
    (
        (date(2026, 11, 30), False),
        (date(2026, 12, 1), True),
        (date(2026, 12, 2), True),
    ),
)
def test_effective_date_boundary_is_inclusive(baseline_date: date, expected: bool) -> None:
    assert is_effective(baseline_date=baseline_date) is expected


@pytest.mark.parametrize(
    "agreement_status",
    (
        SupplementaryAgreementStatus.DRAFT,
        SupplementaryAgreementStatus.PENDING_CONFIRMATION,
        SupplementaryAgreementStatus.REJECTED,
        SupplementaryAgreementStatus.ARCHIVED,
    ),
)
def test_only_confirmed_agreement_status_is_effective(
    agreement_status: SupplementaryAgreementStatus,
) -> None:
    assert is_effective(agreement_status=agreement_status) is False


@pytest.mark.parametrize(
    "agreement_confirmation_status",
    (ConfirmationStatus.UNCONFIRMED, ConfirmationStatus.REJECTED),
)
def test_agreement_must_be_confirmed(
    agreement_confirmation_status: ConfirmationStatus,
) -> None:
    assert is_effective(agreement_confirmation_status=agreement_confirmation_status) is False


@pytest.mark.parametrize(
    "change_confirmation_status",
    (ConfirmationStatus.UNCONFIRMED, ConfirmationStatus.REJECTED),
)
def test_change_must_be_confirmed(change_confirmation_status: ConfirmationStatus) -> None:
    assert is_effective(change_confirmation_status=change_confirmation_status) is False


class UnrelatedConfirmationStatus(str, Enum):
    CONFIRMED = "confirmed"


class UnrelatedAgreementStatus(str, Enum):
    CONFIRMED = "confirmed"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        (
            "agreement_status",
            "confirmed",
            "agreement_status must be a SupplementaryAgreementStatus",
        ),
        (
            "agreement_status",
            UnrelatedAgreementStatus.CONFIRMED,
            "agreement_status must be a SupplementaryAgreementStatus",
        ),
        (
            "agreement_confirmation_status",
            "confirmed",
            "agreement_confirmation_status must be a ConfirmationStatus",
        ),
        (
            "agreement_confirmation_status",
            UnrelatedConfirmationStatus.CONFIRMED,
            "agreement_confirmation_status must be a ConfirmationStatus",
        ),
        (
            "change_confirmation_status",
            "confirmed",
            "change_confirmation_status must be a ConfirmationStatus",
        ),
        (
            "change_confirmation_status",
            UnrelatedConfirmationStatus.CONFIRMED,
            "change_confirmation_status must be a ConfirmationStatus",
        ),
    ),
)
def test_status_inputs_require_exact_enum_types(field: str, value: object, message: str) -> None:
    arguments: dict[str, object] = {
        "agreement_status": SupplementaryAgreementStatus.CONFIRMED,
        "agreement_confirmation_status": ConfirmationStatus.CONFIRMED,
        "change_confirmation_status": ConfirmationStatus.CONFIRMED,
        "effective_date": EFFECTIVE_DATE,
        "baseline_date": EFFECTIVE_DATE,
    }
    arguments[field] = value

    with pytest.raises(ValueError, match=f"^{message}$"):
        is_supplementary_change_effective(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        (
            "effective_date",
            datetime(2026, 12, 1),
            "effective_date must be an exact datetime.date",
        ),
        (
            "effective_date",
            "2026-12-01",
            "effective_date must be an exact datetime.date",
        ),
        (
            "baseline_date",
            datetime(2026, 12, 1),
            "baseline_date must be an exact datetime.date",
        ),
        (
            "baseline_date",
            "2026-12-01",
            "baseline_date must be an exact datetime.date",
        ),
    ),
)
def test_date_inputs_require_exact_date_types(field: str, value: object, message: str) -> None:
    arguments: dict[str, object] = {
        "agreement_status": SupplementaryAgreementStatus.CONFIRMED,
        "agreement_confirmation_status": ConfirmationStatus.CONFIRMED,
        "change_confirmation_status": ConfirmationStatus.CONFIRMED,
        "effective_date": EFFECTIVE_DATE,
        "baseline_date": EFFECTIVE_DATE,
    }
    arguments[field] = value

    with pytest.raises(ValueError, match=f"^{message}$"):
        is_supplementary_change_effective(**arguments)  # type: ignore[arg-type]


def test_all_inputs_are_validated_before_an_ineligible_result() -> None:
    with pytest.raises(
        ValueError,
        match="^baseline_date must be an exact datetime.date$",
    ):
        is_supplementary_change_effective(
            agreement_status=SupplementaryAgreementStatus.DRAFT,
            agreement_confirmation_status=ConfirmationStatus.UNCONFIRMED,
            change_confirmation_status=ConfirmationStatus.REJECTED,
            effective_date=EFFECTIVE_DATE,
            baseline_date="2026-12-01",  # type: ignore[arg-type]
        )


def test_projection_replays_confirmed_changes_without_mutating_original_fields() -> None:
    original = {
        "amount": "100000.00",
        "currency": "CNY",
        "expiry_date": "2026-12-31",
    }
    changes = (
        field_change(
            agreement_id=AGREEMENT_B,
            new_value="2028-03-31",
            effective_date=date(2027, 1, 1),
        ),
        field_change(
            field_code="payment_terms",
            new_value="30 days",
        ),
        field_change(new_value="2027-03-31"),
        field_change(
            agreement_id=AGREEMENT_C,
            field_code="amount",
            new_value="DO_NOT_APPLY_FUTURE_VALUE",
            effective_date=date(2028, 1, 1),
        ),
    )

    projection = project_effective_fields(original, changes, date(2027, 6, 1))
    reordered = project_effective_fields(original, tuple(reversed(changes)), date(2027, 6, 1))

    assert projection == reordered
    assert projection.field_values == {
        "amount": "100000.00",
        "currency": "CNY",
        "expiry_date": "2028-03-31",
        "payment_terms": "30 days",
    }
    assert projection.field_sources == {
        "amount": EffectiveFieldSource(),
        "currency": EffectiveFieldSource(),
        "expiry_date": EffectiveFieldSource(AGREEMENT_B, date(2027, 1, 1)),
        "payment_terms": EffectiveFieldSource(AGREEMENT_A, EFFECTIVE_DATE),
    }
    assert projection.applied_agreement_ids == (AGREEMENT_A, AGREEMENT_B)
    assert original == {
        "amount": "100000.00",
        "currency": "CNY",
        "expiry_date": "2026-12-31",
    }

    with pytest.raises(TypeError):
        cast(dict[str, object], projection.field_values)["amount"] = "changed"
    with pytest.raises(TypeError):
        cast(dict[str, EffectiveFieldSource], projection.field_sources)["amount"] = (
            EffectiveFieldSource()
        )


@pytest.mark.parametrize(
    "change",
    (
        field_change(agreement_status=SupplementaryAgreementStatus.DRAFT),
        field_change(agreement_confirmation_status=ConfirmationStatus.UNCONFIRMED),
        field_change(change_confirmation_status=ConfirmationStatus.REJECTED),
        field_change(effective_date=date(2027, 1, 1)),
    ),
)
def test_projection_ignores_any_change_not_effective_at_the_baseline(
    change: SupplementaryFieldChange,
) -> None:
    projection = project_effective_fields(
        {"expiry_date": "2026-12-31"},
        (change,),
        date(2026, 12, 31),
    )

    assert projection.field_values == {"expiry_date": "2026-12-31"}
    assert projection.field_sources == {"expiry_date": EffectiveFieldSource()}
    assert projection.applied_agreement_ids == ()


@pytest.mark.parametrize(
    "second_change",
    (
        field_change(field_code="amount", effective_date=date(2026, 12, 2)),
        field_change(
            field_code="amount",
            agreement_status=SupplementaryAgreementStatus.DRAFT,
        ),
        field_change(
            field_code="amount",
            agreement_confirmation_status=ConfirmationStatus.UNCONFIRMED,
        ),
    ),
)
def test_all_changes_from_one_agreement_share_the_same_agreement_facts(
    second_change: SupplementaryFieldChange,
) -> None:
    changes = (field_change(), second_change)

    with pytest.raises(
        ValueError,
        match="^supplementary agreement facts must be consistent$",
    ):
        project_effective_fields({}, changes, date(2026, 12, 2))


def test_agreement_is_not_partially_applied_when_any_change_is_unconfirmed() -> None:
    changes = (
        field_change(field_code="expiry_date", new_value="2027-03-31"),
        field_change(
            field_code="amount",
            new_value="120000.00",
            change_confirmation_status=ConfirmationStatus.UNCONFIRMED,
        ),
    )

    projection = project_effective_fields(
        {"amount": "100000.00", "expiry_date": "2026-12-31"},
        changes,
        EFFECTIVE_DATE,
    )

    assert projection.field_values == {
        "amount": "100000.00",
        "expiry_date": "2026-12-31",
    }
    assert projection.applied_agreement_ids == ()


def test_nested_field_values_are_isolated_and_recursively_frozen() -> None:
    original_terms = {"milestones": ["base"]}
    changed_terms = {"milestones": ["new"]}
    projection = project_effective_fields(
        {"original_terms": original_terms},
        (field_change(field_code="changed_terms", new_value=changed_terms),),
        EFFECTIVE_DATE,
    )

    original_terms["milestones"].append("mutated")
    changed_terms["milestones"].append("mutated")

    frozen_original = cast(Mapping[str, object], projection.field_values["original_terms"])
    frozen_changed = cast(Mapping[str, object], projection.field_values["changed_terms"])
    assert frozen_original["milestones"] == ("base",)
    assert frozen_changed["milestones"] == ("new",)
    with pytest.raises(TypeError):
        cast(dict[str, object], frozen_changed)["milestones"] = ("changed",)

    materialized = projection.materialize_field_values()
    assert TypeAdapter(dict[str, object]).dump_python(materialized, mode="json") == {
        "changed_terms": {"milestones": ["new"]},
        "original_terms": {"milestones": ["base"]},
    }
    cast(dict[str, object], materialized["changed_terms"])["milestones"] = ["changed"]
    assert frozen_changed["milestones"] == ("new",)


def test_same_agreement_and_field_duplicate_fails_closed_without_value_leakage() -> None:
    sentinel = "SENSITIVE_SUPPLEMENTARY_VALUE_MUST_NOT_ESCAPE"
    changes = (
        field_change(new_value=sentinel),
        field_change(new_value="second", effective_date=date(2027, 1, 1)),
    )

    with pytest.raises(ValueError) as exc_info:
        project_effective_fields({}, changes, date(2027, 1, 1))

    assert str(exc_info.value) == "duplicate supplementary agreement field change"
    assert sentinel not in repr(exc_info.value)


def test_same_agreement_and_field_duplicate_is_rejected_even_if_one_is_ineligible() -> None:
    changes = (
        field_change(),
        field_change(agreement_status=SupplementaryAgreementStatus.DRAFT),
    )

    with pytest.raises(
        ValueError,
        match="^duplicate supplementary agreement field change$",
    ):
        project_effective_fields({}, changes, EFFECTIVE_DATE)


def test_same_field_and_date_from_different_agreements_fails_closed() -> None:
    sentinel = "SENSITIVE_CONFLICT_VALUE_MUST_NOT_ESCAPE"
    changes = (
        field_change(agreement_id=AGREEMENT_A, new_value=sentinel),
        field_change(agreement_id=AGREEMENT_B, new_value="other"),
    )

    with pytest.raises(ValueError) as exc_info:
        project_effective_fields({}, tuple(reversed(changes)), EFFECTIVE_DATE)

    assert str(exc_info.value) == "conflicting supplementary agreement field changes"
    assert sentinel not in repr(exc_info.value)


def test_change_is_frozen_and_hides_new_value_from_repr() -> None:
    sentinel = "SENSITIVE_NEW_VALUE_MUST_NOT_APPEAR"
    change = field_change(new_value=sentinel)
    projection = project_effective_fields({}, (change,), EFFECTIVE_DATE)

    assert sentinel not in repr(change)
    assert sentinel not in repr(projection)
    with pytest.raises(FrozenInstanceError):
        SupplementaryFieldChange.__setattr__(change, "field_code", "changed")


@pytest.mark.parametrize("field_code", ["", "   ", 1, True, None])
def test_change_requires_a_non_empty_exact_string_field_code(field_code: object) -> None:
    with pytest.raises(ValueError, match="^field_code must be a non-empty exact str$"):
        field_change(field_code=cast(str, field_code))


def test_projection_rejects_non_contract_container_and_date_types() -> None:
    with pytest.raises(ValueError, match="^original_fields must be a mapping$"):
        project_effective_fields(cast(dict[str, object], []), (), EFFECTIVE_DATE)
    with pytest.raises(ValueError, match="^field_code must be a non-empty exact str$"):
        project_effective_fields({" ": "value"}, (), EFFECTIVE_DATE)
    with pytest.raises(
        ValueError,
        match="^changes must be a tuple of SupplementaryFieldChange values$",
    ):
        project_effective_fields({}, cast(tuple[SupplementaryFieldChange, ...], []), EFFECTIVE_DATE)
    with pytest.raises(
        ValueError,
        match="^changes must be a tuple of SupplementaryFieldChange values$",
    ):
        project_effective_fields(
            {},
            cast(tuple[SupplementaryFieldChange, ...], ("change",)),
            EFFECTIVE_DATE,
        )
    with pytest.raises(
        ValueError,
        match="^baseline_date must be an exact datetime.date$",
    ):
        project_effective_fields({}, (), datetime(2026, 12, 1))


@pytest.mark.parametrize(
    "non_finite",
    (
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ),
)
def test_projection_rejects_non_finite_decimal_values(non_finite: Decimal) -> None:
    with pytest.raises(ValueError, match="^contract field values must be finite$"):
        project_effective_fields({"amount": non_finite}, (), EFFECTIVE_DATE)
    with pytest.raises(ValueError, match="^contract field values must be finite$"):
        project_effective_fields(
            {},
            (field_change(new_value={"nested": [non_finite]}),),
            EFFECTIVE_DATE,
        )


@pytest.mark.parametrize(
    "finite",
    (
        Decimal("0"),
        Decimal("-0"),
        Decimal("12.3400"),
        Decimal("1E+999999"),
        Decimal("1E-999999"),
    ),
)
def test_projection_preserves_finite_decimal_values(finite: Decimal) -> None:
    projection = project_effective_fields(
        {"original_amount": finite},
        (
            field_change(
                field_code="changed_amount",
                new_value={"nested": [finite]},
            ),
        ),
        EFFECTIVE_DATE,
    )

    assert projection.field_values["original_amount"] == finite
    assert projection.materialize_field_values() == {
        "original_amount": finite,
        "changed_amount": {"nested": [finite]},
    }
