from itertools import product

import pytest
from pydantic import ValidationError

from app.schemas.business_statuses import (
    ConfirmationStatus,
    InvoiceDuplicateStatus,
    InvoiceStatus,
    InvoiceStatuses,
)


def test_invoice_status_enums_are_exact() -> None:
    assert tuple(status.value for status in ConfirmationStatus) == (
        "unconfirmed",
        "confirmed",
        "rejected",
    )
    assert tuple(status.value for status in InvoiceStatus) == (
        "draft",
        "confirmed",
        "voided",
        "archived",
    )
    assert tuple(status.value for status in InvoiceDuplicateStatus) == (
        "not_checked",
        "unique",
        "suspected",
        "confirmed_duplicate",
        "exception_approved",
    )


def test_invoice_status_facts_are_independent() -> None:
    for confirmation_status, status, duplicate_status in product(
        ConfirmationStatus,
        InvoiceStatus,
        InvoiceDuplicateStatus,
    ):
        facts = InvoiceStatuses(
            confirmation_status=confirmation_status,
            status=status,
            duplicate_status=duplicate_status,
        )

        assert facts.confirmation_status is confirmation_status
        assert facts.status is status
        assert facts.duplicate_status is duplicate_status


def test_invoice_statuses_parse_and_serialize_exact_json_values() -> None:
    facts = InvoiceStatuses.model_validate(
        {
            "confirmation_status": "confirmed",
            "status": "draft",
            "duplicate_status": "suspected",
        }
    )

    assert facts.model_dump(mode="json") == {
        "confirmation_status": "confirmed",
        "status": "draft",
        "duplicate_status": "suspected",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("confirmation_status", "pending"),
        ("status", "active"),
        ("duplicate_status", "duplicate"),
    ),
)
def test_invoice_statuses_reject_unknown_values(field: str, value: str) -> None:
    payload = {
        "confirmation_status": "unconfirmed",
        "status": "draft",
        "duplicate_status": "not_checked",
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        InvoiceStatuses.model_validate(payload)


def test_invoice_statuses_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        InvoiceStatuses.model_validate(
            {
                "confirmation_status": "unconfirmed",
                "status": "draft",
                "duplicate_status": "not_checked",
                "confirmation_eligible": True,
            }
        )


def test_invoice_statuses_are_frozen() -> None:
    facts = InvoiceStatuses(
        confirmation_status=ConfirmationStatus.UNCONFIRMED,
        status=InvoiceStatus.DRAFT,
        duplicate_status=InvoiceDuplicateStatus.NOT_CHECKED,
    )

    with pytest.raises(ValidationError):
        facts.status = InvoiceStatus.CONFIRMED
