from decimal import Decimal
from uuid import UUID

from app.services.invoice_extractor import InvoiceSourceBlock, extract_invoice_candidate

PARSE_VERSION_ID = UUID("96000000-0000-4000-8000-000000000001")


def _block(index: int, text: str, confidence: str = "0.95000") -> InvoiceSourceBlock:
    return InvoiceSourceBlock(
        id=UUID(f"96000000-0000-4000-8000-{index + 10:012d}"),
        parse_version_id=PARSE_VERSION_ID,
        page_no=1,
        block_index=index,
        text=text,
        bbox={"left": 10, "top": index * 20, "width": 300, "height": 18},
        confidence=Decimal(confidence),
    )


def test_extracts_fixture_fields_and_preserves_exact_block_evidence() -> None:
    blocks = tuple(
        _block(index, text)
        for index, text in enumerate(
            (
                "发票代码： 3100260001",
                "发票号码：00000001",
                "开票日期：2026-06-01",
                "购买方税号：91310000MA000001X1",
                "销售方税号：91310000MA000002X2",
                "不含税金额：56,603.77",
                "税额：3396.23",
                "价税合计：60000.00",
                "币种：cny",
                "明细：测试服务费",
            )
        )
    )

    candidate = extract_invoice_candidate(tuple(reversed(blocks)))

    assert candidate.facts.model_dump(mode="json") == {
        "invoice_code": "3100260001",
        "invoice_number": "00000001",
        "invoice_type": None,
        "is_red_invoice": None,
        "invoice_date": "2026-06-01",
        "buyer_name": None,
        "buyer_tax_no": "91310000MA000001X1",
        "seller_name": None,
        "seller_tax_no": "91310000MA000002X2",
        "amount_excluding_tax": "56603.77",
        "tax_amount": "3396.23",
        "total_amount": "60000.00",
        "currency": "CNY",
    }
    assert {item.field_code for item in candidate.field_evidence} == {
        "invoice_code",
        "invoice_number",
        "invoice_date",
        "buyer_tax_no",
        "seller_tax_no",
        "amount_excluding_tax",
        "tax_amount",
        "total_amount",
        "currency",
    }
    invoice_code_evidence = next(
        item.evidence for item in candidate.field_evidence if item.field_code == "invoice_code"
    )
    assert invoice_code_evidence.quote_text == "发票代码： 3100260001"
    assert invoice_code_evidence.block_id == blocks[0].id
    assert invoice_code_evidence.bbox == blocks[0].bbox
    assert invoice_code_evidence.confidence == "0.95000"
    assert len(candidate.items) == 1
    assert candidate.items[0].item_name == "测试服务费"
    assert candidate.items[0].evidence[0].block_id == blocks[-1].id


def test_conflicting_or_invalid_values_are_not_promoted_to_candidates() -> None:
    candidate = extract_invoice_candidate(
        (
            _block(0, "发票号码：00000001"),
            _block(1, "发票号码：DIFFERENT"),
            _block(2, "开票日期：2026-02-30"),
            _block(3, "税额：1.234"),
            _block(4, "币种：RMB"),
        )
    )

    assert candidate.facts.invoice_number is None
    assert candidate.facts.invoice_date is None
    assert candidate.facts.tax_amount is None
    assert candidate.facts.currency == "RMB"
    assert tuple(item.field_code for item in candidate.field_evidence) == ("currency",)
    assert candidate.items == ()


def test_missing_currency_remains_null_instead_of_using_a_local_default() -> None:
    candidate = extract_invoice_candidate((_block(0, "发票号码：00000001"),))

    assert candidate.facts.invoice_number == "00000001"
    assert candidate.facts.currency is None
    assert tuple(item.field_code for item in candidate.field_evidence) == ("invoice_number",)


def test_extracts_standard_english_invoice_labels_without_local_defaults() -> None:
    candidate = extract_invoice_candidate(
        (
            _block(0, "INVOICE"),
            _block(1, "Invoice #: INV-001"),
            _block(2, "Invoice Date: 06/01/2026"),
            _block(3, "Bill To: Buyer Example LLC"),
            _block(4, "Vendor: Seller Example LLC"),
            _block(5, "Federal ID: 12-3456789"),
            _block(6, "Subtotal: $100.00"),
            _block(7, "Sales Tax: $6.25"),
            _block(8, "Amount Due: USD 106.25"),
        )
    )

    assert candidate.facts.model_dump(mode="json") == {
        "invoice_code": None,
        "invoice_number": "INV-001",
        "invoice_type": "standard",
        "is_red_invoice": False,
        "invoice_date": "2026-06-01",
        "buyer_name": "Buyer Example LLC",
        "buyer_tax_no": None,
        "seller_name": "Seller Example LLC",
        "seller_tax_no": "123456789",
        "amount_excluding_tax": "100.00",
        "tax_amount": "6.25",
        "total_amount": "106.25",
        "currency": "USD",
    }
    assert {item.field_code for item in candidate.field_evidence} == {
        "invoice_number",
        "invoice_type",
        "is_red_invoice",
        "invoice_date",
        "buyer_name",
        "seller_name",
        "seller_tax_no",
        "amount_excluding_tax",
        "tax_amount",
        "total_amount",
        "currency",
    }


def test_extracts_multiple_english_fields_from_one_layout_line() -> None:
    candidate = extract_invoice_candidate(
        (
            _block(
                0,
                "Invoice No 44920   Invoice Date 05/18/22   "
                "Subtotal $2,150.00   Sales Tax $0.00   Total $2,150.00",
            ),
        )
    )

    assert candidate.facts.invoice_number == "44920"
    assert candidate.facts.invoice_date is not None
    assert candidate.facts.invoice_date.isoformat() == "2022-05-18"
    assert candidate.facts.amount_excluding_tax == "2150.00"
    assert candidate.facts.tax_amount == "0.00"
    assert candidate.facts.total_amount == "2150.00"
    assert candidate.facts.currency is None
