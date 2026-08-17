from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.suppliers import SupplierCandidateUpdateRequest
from app.services.supplier_runtime import public_tax_number, validate_supplier_state


@pytest.mark.parametrize(
    ("unified_social_credit_code", "tax_number", "expected"),
    [
        (None, None, None),
        (None, "tax-generic", "tax-generic"),
        ("USCC123", None, "USCC123"),
        ("USCC123", "USCC123", "USCC123"),
    ],
)
def test_public_tax_number_uses_exact_coalesce_projection(
    unified_social_credit_code: str | None,
    tax_number: str | None,
    expected: str | None,
) -> None:
    assert public_tax_number(unified_social_credit_code, tax_number) == expected


def test_public_tax_number_rejects_conflicting_sources() -> None:
    with pytest.raises(ValueError, match="tax identity sources conflict"):
        public_tax_number("USCC123", "tax-generic")


@pytest.mark.parametrize(
    ("confirmation_status", "status", "confirmed"),
    [
        ("unconfirmed", "candidate", False),
        ("confirmed", "active", True),
        ("rejected", "inactive", True),
    ],
)
def test_supplier_state_allows_only_frozen_matrix(
    confirmation_status: str,
    status: str,
    confirmed: bool,
) -> None:
    confirmed_by = uuid4() if confirmed else None
    confirmed_at_present = confirmed
    validate_supplier_state(
        confirmation_status,
        status,
        confirmed_by=confirmed_by,
        confirmed_at_present=confirmed_at_present,
    )


@pytest.mark.parametrize(
    ("confirmation_status", "status", "confirmed_by", "confirmed_at_present"),
    [
        ("unconfirmed", "active", None, False),
        ("confirmed", "candidate", uuid4(), True),
        ("rejected", "candidate", uuid4(), True),
        ("unconfirmed", "candidate", uuid4(), True),
        ("confirmed", "active", None, False),
        ("rejected", "inactive", uuid4(), False),
    ],
)
def test_supplier_state_rejects_other_combinations(
    confirmation_status: str,
    status: str,
    confirmed_by: object,
    confirmed_at_present: bool,
) -> None:
    with pytest.raises(ValueError, match="supplier state matrix is invalid"):
        validate_supplier_state(
            confirmation_status,
            status,
            confirmed_by=confirmed_by,
            confirmed_at_present=confirmed_at_present,
        )


def test_supplier_update_request_is_strict_and_requires_a_change() -> None:
    with pytest.raises(ValidationError):
        SupplierCandidateUpdateRequest.model_validate(
            {"row_version": "1", "reason": "人工核对", "unknown": True}
        )
    with pytest.raises(ValidationError):
        SupplierCandidateUpdateRequest.model_validate({"row_version": "1", "reason": "人工核对"})
    with pytest.raises(ValidationError):
        SupplierCandidateUpdateRequest.model_validate(
            {"row_version": "1", "reason": "人工核对", "tax_number": None}
        )


def test_supplier_update_request_preserves_exact_generic_tax_number() -> None:
    payload = SupplierCandidateUpdateRequest.model_validate(
        {
            "row_version": "7",
            "reason": "人工核对",
            "standard_name": "示例供应商",
            "tax_number": "Ab-税-01",
            "decision": "confirmed",
        }
    )

    assert payload.tax_number == "Ab-税-01"
    assert payload.model_dump(exclude_unset=True) == {
        "row_version": "7",
        "reason": "人工核对",
        "standard_name": "示例供应商",
        "tax_number": "Ab-税-01",
        "decision": "confirmed",
    }
