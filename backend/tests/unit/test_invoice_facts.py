from __future__ import annotations

from uuid import UUID

from app.schemas.invoices import InvoiceEvidenceData, InvoiceFieldEvidenceData
from app.services.invoice_facts import (
    field_evidence_json,
    item_evidence_json,
    parse_field_evidence,
    parse_item_evidence,
)


def _evidence() -> InvoiceEvidenceData:
    return InvoiceEvidenceData(
        block_id=UUID("97000000-0000-4000-8000-000000000001"),
        parse_version_id=UUID("97000000-0000-4000-8000-000000000002"),
        page_no=1,
        quote_text="发票号码: 000001",
        bbox={"left": 10, "top": 20},
        confidence="0.95000",
    )


def test_evidence_round_trip_accepts_jsonb_primitive_values() -> None:
    evidence = _evidence()
    field_values = field_evidence_json(
        (InvoiceFieldEvidenceData(field_code="invoice_number", evidence=evidence),)
    )
    item_values = item_evidence_json((evidence,))

    assert parse_field_evidence(field_values) == (
        InvoiceFieldEvidenceData(field_code="invoice_number", evidence=evidence),
    )
    assert parse_item_evidence(item_values) == (evidence,)
