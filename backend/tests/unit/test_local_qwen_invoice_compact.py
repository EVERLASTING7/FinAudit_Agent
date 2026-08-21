from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import cast
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_local_qwen_invoice_compact import (  # noqa: E402
    _ground,
    _normalize_model_output,
    _select_blocks,
)

from app.services.invoice_extractor import InvoiceSourceBlock  # noqa: E402

PARSE_ID = UUID("96000000-0000-4000-8000-000000000001")
EVIDENCE_PATH = PROJECT_ROOT / "tests" / "evaluation" / "public-local-qwen-invoice-pilot-v1.json"


def _block(index: int, text: str) -> InvoiceSourceBlock:
    return InvoiceSourceBlock(
        id=UUID(f"96000000-0000-4000-8000-{index + 10:012d}"),
        parse_version_id=PARSE_ID,
        page_no=1,
        block_index=index,
        text=text,
        bbox=None,
        confidence=None,
    )


def _facts() -> dict[str, object]:
    return {
        "invoice_code": "HALLUCINATED",
        "invoice_number": "INV-001",
        "invoice_type": "Invoice",
        "is_red_invoice": False,
        "invoice_date": "2026-06-01",
        "buyer_name": "Buyer LLC",
        "buyer_tax_no": None,
        "seller_name": "Seller LLC",
        "seller_tax_no": "123456789",
        "amount_excluding_tax": "100.00",
        "tax_amount": "6.00",
        "total_amount": "106.00",
        "currency": "USD",
    }


def test_compact_output_normalizes_standard_invoice_synonym() -> None:
    normalized = _normalize_model_output(_facts())

    assert normalized["invoice_type"] == "standard"
    assert normalized["is_red_invoice"] is False


def test_grounding_drops_hallucinated_code_and_keeps_supported_values() -> None:
    blocks = (
        _block(0, "INVOICE"),
        _block(1, "Invoice Number INV-001 Invoice Date 06/01/2026"),
        _block(2, "Bill To Buyer LLC"),
        _block(3, "Seller LLC Federal ID 12-3456789"),
        _block(4, "Subtotal USD 100.00 Sales Tax 6.00 Amount Due 106.00"),
    )

    grounded, evidence = _ground(_normalize_model_output(_facts()), blocks)

    assert grounded["invoice_code"] is None
    assert grounded["invoice_number"] == "INV-001"
    assert grounded["invoice_type"] == "standard"
    assert grounded["is_red_invoice"] is False
    assert grounded["invoice_date"] == "2026-06-01"
    assert grounded["buyer_name"] == "Buyer LLC"
    assert grounded["seller_name"] == "Seller LLC"
    assert grounded["seller_tax_no"] == "123456789"
    assert grounded["amount_excluding_tax"] == "100.00"
    assert grounded["tax_amount"] == "6.00"
    assert grounded["total_amount"] == "106.00"
    assert grounded["currency"] == "USD"
    assert {item.field_code for item in evidence} == {
        field for field, value in grounded.items() if value is not None
    }


def test_block_selection_keeps_first_and_last_relevant_context() -> None:
    blocks = tuple(
        _block(index, f"Invoice total {index}.00" if index % 2 == 0 else "unrelated")
        for index in range(100)
    )

    selected = _select_blocks(blocks)

    assert len(selected) == 40
    assert selected[0].block_index == 0
    assert selected[-1].block_index == 99


def _mapping(value: object) -> dict[str, object]:
    assert type(value) is dict
    return cast(dict[str, object], value)


def test_compact_pilot_evidence_is_bounded_grounded_and_non_acceptance() -> None:
    evidence = _mapping(json.loads(EVIDENCE_PATH.read_bytes()))
    assert evidence["schema_version"] == "public-local-qwen-invoice-pilot-v1"
    for raw_binding in cast(list[object], evidence["source_binding"]):
        binding = _mapping(raw_binding)
        payload = (PROJECT_ROOT / str(binding["path"])).read_bytes()
        assert len(payload) == binding["bytes"]
        assert hashlib.sha256(payload).hexdigest().upper() == binding["sha256"]

    runtime = _mapping(evidence["runtime"])
    assert runtime == {
        "automatic_retry_count": 0,
        "case_count": 8,
        "execution": "cpu",
        "model": "qwen3:8b",
        "num_ctx": 2048,
        "num_predict": 256,
        "paid_cost_cny": "0.000000",
        "provider_network_calls": 0,
        "raw_model_output_persisted_in_evidence": False,
        "temperature": 0,
        "temporary_raw_output_removed": True,
    }
    metrics = _mapping(evidence["metrics"])
    assert metrics == {
        "grounded_non_null_field_count": 74,
        "matched_field_count": 82,
        "model_matched_field_count": 81,
        "model_non_null_field_count": 87,
        "model_provisional_13_field_accuracy": "0.778846",
        "provisional_13_field_accuracy": "0.788462",
        "threshold": "0.950000",
        "threshold_status": "FAILED",
        "total_field_count": 104,
        "valid_output_count": 8,
    }
    cases = [_mapping(case) for case in cast(list[object], evidence["cases"])]
    assert len(cases) == 8
    assert all(case["output_valid"] is True for case in cases)
    assert all(case["evidence_count"] == case["grounded_non_null_field_count"] for case in cases)

    boundary = _mapping(evidence["acceptance_boundary"])
    assert boundary["default_local_profile_changed"] is False
    assert boundary["is_customer_business_representative_dataset"] is False
    assert boundary["is_formal_ac_acceptance"] is False
    assert boundary["may_mark_ac_accepted"] is False
    serialized = json.dumps(evidence, sort_keys=True).lower()
    for forbidden in (
        "raw_response_text",
        "document_text",
        "expected_values",
        "actual_values",
        "tax_id_value",
    ):
        assert forbidden not in serialized
