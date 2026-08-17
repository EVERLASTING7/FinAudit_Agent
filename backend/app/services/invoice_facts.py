"""发票当前事实的规范序列化、证据载体与关键哈希。"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import cast

from pydantic import JsonValue

from app.ai.policy import canonicalize_jcs
from app.models.financial import Invoice, InvoiceItem
from app.schemas.invoices import (
    InvoiceEvidenceData,
    InvoiceFactsWriteData,
    InvoiceFieldEvidenceData,
    InvoiceItemWriteData,
)


def decimal_or_none(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def field_evidence_json(
    values: tuple[InvoiceFieldEvidenceData, ...],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "fields": [
            item.model_dump(mode="json")
            for item in sorted(values, key=lambda item: item.field_code)
        ],
    }


def item_evidence_json(values: tuple[InvoiceEvidenceData, ...]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "evidence": [item.model_dump(mode="json") for item in values],
    }


def parse_field_evidence(value: dict[str, object]) -> tuple[InvoiceFieldEvidenceData, ...]:
    if value == {}:
        return ()
    if value.get("schema_version") != 1 or set(value) != {"schema_version", "fields"}:
        raise ValueError("invoice field evidence shape is invalid")
    fields = value["fields"]
    if type(fields) is not list:
        raise ValueError("invoice field evidence shape is invalid")
    parsed = tuple(
        InvoiceFieldEvidenceData.model_validate_json(
            json.dumps(item, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        )
        for item in fields
    )
    if tuple(item.field_code for item in parsed) != tuple(
        sorted(item.field_code for item in parsed)
    ) or len(parsed) != len({item.field_code for item in parsed}):
        raise ValueError("invoice field evidence order is invalid")
    return parsed


def parse_item_evidence(value: dict[str, object]) -> tuple[InvoiceEvidenceData, ...]:
    if value == {}:
        return ()
    if value.get("schema_version") != 1 or set(value) != {"schema_version", "evidence"}:
        raise ValueError("invoice item evidence shape is invalid")
    evidence = value["evidence"]
    if type(evidence) is not list:
        raise ValueError("invoice item evidence shape is invalid")
    return tuple(
        InvoiceEvidenceData.model_validate_json(
            json.dumps(item, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        )
        for item in evidence
    )


def invoice_critical_fact_hash(
    facts: InvoiceFactsWriteData,
    items: tuple[InvoiceItemWriteData, ...],
) -> str:
    item_facts: list[JsonValue] = []
    for item in items:
        item_payload = item.model_dump(mode="json", exclude={"evidence"})
        item_facts.append(cast(JsonValue, item_payload))
    hash_payload: JsonValue = [
        "invoice-facts-v1",
        cast(JsonValue, facts.model_dump(mode="json")),
        item_facts,
    ]
    return hashlib.sha256(canonicalize_jcs(hash_payload)).hexdigest()


def invoice_snapshot(invoice: Invoice, items: tuple[InvoiceItem, ...]) -> dict[str, object]:
    return {
        "facts": {
            "invoice_code": invoice.invoice_code,
            "invoice_number": invoice.invoice_number,
            "invoice_type": invoice.invoice_type,
            "is_red_invoice": invoice.is_red_invoice,
            "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
            "buyer_name": invoice.buyer_name,
            "buyer_tax_no": invoice.buyer_tax_no,
            "seller_name": invoice.seller_name,
            "seller_tax_no": invoice.seller_tax_no,
            "amount_excluding_tax": (
                format(invoice.amount_excluding_tax, "f")
                if invoice.amount_excluding_tax is not None
                else None
            ),
            "tax_amount": (
                format(invoice.tax_amount, "f") if invoice.tax_amount is not None else None
            ),
            "total_amount": (
                format(invoice.total_amount, "f") if invoice.total_amount is not None else None
            ),
            "currency": invoice.currency,
        },
        "field_evidence": invoice.field_evidence_json,
        "items": [
            {
                "line_no": item.line_no,
                "item_name": item.item_name,
                "specification": item.specification,
                "unit": item.unit,
                "quantity": format(item.quantity, "f") if item.quantity is not None else None,
                "unit_price": (
                    format(item.unit_price, "f") if item.unit_price is not None else None
                ),
                "amount_excluding_tax": (
                    format(item.amount_excluding_tax, "f")
                    if item.amount_excluding_tax is not None
                    else None
                ),
                "tax_rate": format(item.tax_rate, "f") if item.tax_rate is not None else None,
                "tax_amount": (
                    format(item.tax_amount, "f") if item.tax_amount is not None else None
                ),
                "total_amount": (
                    format(item.total_amount, "f") if item.total_amount is not None else None
                ),
                "evidence": item.evidence_json,
            }
            for item in items
        ],
        "confirmation_status": invoice.confirmation_status,
        "duplicate_status": invoice.duplicate_status,
        "status": invoice.status,
    }


__all__ = [
    "decimal_or_none",
    "field_evidence_json",
    "invoice_critical_fact_hash",
    "invoice_snapshot",
    "item_evidence_json",
    "parse_field_evidence",
    "parse_item_evidence",
]
