from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from app.ai.extraction_output import (
    ExtractionOutputError,
    validate_contract_extraction_output,
    validate_invoice_extraction_output,
)
from app.ai.extraction_prompts import ExtractionPromptBlock
from app.ai.policy import canonicalize_jcs

PARSE_VERSION_ID = UUID("96000000-0000-4000-8000-000000000001")
BLOCK_ID = UUID("96000000-0000-4000-8000-000000000002")
INVOICE_FIELD_CODES = (
    "invoice_code",
    "invoice_number",
    "invoice_type",
    "is_red_invoice",
    "invoice_date",
    "buyer_name",
    "buyer_tax_no",
    "seller_name",
    "seller_tax_no",
    "amount_excluding_tax",
    "tax_amount",
    "total_amount",
    "currency",
)
CONTRACT_FIELD_CODES = (
    "contract_no",
    "name",
    "party_a_name",
    "party_a_tax_no",
    "party_b_name",
    "party_b_tax_no",
    "amount",
    "currency",
    "signed_date",
    "effective_date",
    "expiry_date",
    "payment_method",
    "payment_terms",
)


def source_block(text: str = "合同编号：HT-001") -> ExtractionPromptBlock:
    return ExtractionPromptBlock(
        block_id=BLOCK_ID,
        parse_version_id=PARSE_VERSION_ID,
        page_no=1,
        block_index=0,
        text=text,
        bbox={"height": 10, "left": 1, "top": 2, "width": 100},
        confidence=Decimal("0.95000"),
    )


def evidence(text: str = "合同编号：HT-001") -> dict[str, object]:
    return {
        "block_id": str(BLOCK_ID),
        "parse_version_id": str(PARSE_VERSION_ID),
        "page_no": 1,
        "quote_text": text,
        "bbox": {"height": 10, "left": 1, "top": 2, "width": 100},
        "confidence": "0.95000",
    }


def encoded(payload: object) -> str:
    return canonicalize_jcs(payload).decode("utf-8")


def contract_payload() -> dict[str, object]:
    facts = {field_code: None for field_code in CONTRACT_FIELD_CODES}
    facts["contract_no"] = "HT-001"
    return {
        "facts": facts,
        "field_evidence": [{"field_code": "contract_no", "evidence": evidence()}],
    }


def invoice_payload() -> dict[str, object]:
    facts = {field_code: None for field_code in INVOICE_FIELD_CODES}
    facts["invoice_number"] = "INV-001"
    return {
        "facts": facts,
        "field_evidence": [
            {"field_code": "invoice_number", "evidence": evidence("发票号码：INV-001")}
        ],
        "items": [
            {
                "line_no": 1,
                "item_name": "服务费",
                "specification": None,
                "unit": None,
                "quantity": None,
                "unit_price": None,
                "amount_excluding_tax": None,
                "tax_rate": None,
                "tax_amount": None,
                "total_amount": None,
                "evidence": [evidence("发票号码：INV-001")],
            }
        ],
    }


def test_contract_output_accepts_exact_facts_and_source_evidence() -> None:
    output = validate_contract_extraction_output(
        encoded(contract_payload()),
        blocks=(source_block(),),
    )

    assert output.facts.contract_no == "HT-001"
    assert output.facts.currency is None
    assert output.field_evidence[0].evidence.confidence == "0.95000"


@pytest.mark.parametrize("mutation", ["quote", "block", "page", "bbox", "confidence"])
def test_contract_output_rejects_any_evidence_drift(mutation: str) -> None:
    payload = contract_payload()
    record = payload["field_evidence"][0]["evidence"]  # type: ignore[index]
    if mutation == "quote":
        record["quote_text"] = "tampered"  # type: ignore[index]
    elif mutation == "block":
        record["block_id"] = "96000000-0000-4000-8000-000000000099"  # type: ignore[index]
    elif mutation == "page":
        record["page_no"] = 2  # type: ignore[index]
    elif mutation == "bbox":
        record["bbox"] = {"left": 99}  # type: ignore[index]
    else:
        record["confidence"] = "0.95"  # type: ignore[index]

    with pytest.raises(ExtractionOutputError):
        validate_contract_extraction_output(
            encoded(payload),
            blocks=(source_block(),),
        )


def test_contract_output_requires_all_fact_keys_and_exact_evidence_matrix() -> None:
    missing_key = contract_payload()
    del missing_key["facts"]["currency"]  # type: ignore[index]
    missing_evidence = contract_payload()
    missing_evidence["field_evidence"] = []
    extra_evidence = contract_payload()
    extra_evidence["field_evidence"].append(  # type: ignore[union-attr]
        {"field_code": "currency", "evidence": evidence()}
    )

    for payload in (missing_key, missing_evidence, extra_evidence):
        with pytest.raises(ExtractionOutputError):
            validate_contract_extraction_output(
                encoded(payload),
                blocks=(source_block(),),
            )


def test_output_rejects_markdown_duplicate_keys_and_never_reflects_source() -> None:
    sentinel = "private-model-output-must-not-leak"
    values = (
        f'```json\n{{"{sentinel}":true}}\n```',
        '{"facts":{},"facts":{}}',
        f'{{"{sentinel}":',
    )

    for value in values:
        with pytest.raises(ExtractionOutputError) as error:
            validate_contract_extraction_output(value, blocks=(source_block(),))
        assert sentinel not in str(error.value)
        assert sentinel not in repr(error.value)


def test_invoice_output_allows_null_currency_but_requires_exact_evidence() -> None:
    block = source_block("发票号码：INV-001")
    output = validate_invoice_extraction_output(
        encoded(invoice_payload()),
        blocks=(block,),
    )

    assert output.facts.invoice_number == "INV-001"
    assert output.facts.currency is None
    assert output.items[0].line_no == 1
    assert output.items[0].item_name == "服务费"


@pytest.mark.parametrize("invalid_item", ["line", "empty", "no_evidence", "duplicate_evidence"])
def test_invoice_output_rejects_invalid_item_shape(invalid_item: str) -> None:
    payload = invoice_payload()
    item = payload["items"][0]  # type: ignore[index]
    if invalid_item == "line":
        item["line_no"] = 2  # type: ignore[index]
    elif invalid_item == "empty":
        item["item_name"] = None  # type: ignore[index]
    elif invalid_item == "no_evidence":
        item["evidence"] = []  # type: ignore[index]
    else:
        item["evidence"].append(evidence("发票号码：INV-001"))  # type: ignore[union-attr]

    with pytest.raises(ExtractionOutputError):
        validate_invoice_extraction_output(
            encoded(payload),
            blocks=(source_block("发票号码：INV-001"),),
        )
