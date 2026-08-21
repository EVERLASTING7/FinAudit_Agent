from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_PATH = PROJECT_ROOT / "tests" / "evaluation" / "public-docubench-qualification-v1.json"


def _mapping(value: object) -> dict[str, object]:
    assert type(value) is dict
    return cast(dict[str, object], value)


def _evidence() -> dict[str, object]:
    return _mapping(json.loads(EVIDENCE_PATH.read_bytes()))


def test_docubench_evidence_binds_current_product_sources() -> None:
    evidence = _evidence()
    assert evidence["schema_version"] == "public-docubench-qualification-v1"
    for raw_binding in cast(list[object], evidence["source_binding"]):
        binding = _mapping(raw_binding)
        payload = (PROJECT_ROOT / str(binding["path"])).read_bytes()
        assert len(payload) == binding["bytes"]
        assert hashlib.sha256(payload).hexdigest().upper() == binding["sha256"]


def test_docubench_profile_covers_hand_verified_multiformat_sources() -> None:
    source = _mapping(_evidence()["source"])
    assert source["upstream_commit"] == "43a3f3bc00e591e711075678ca6d154acfedcf42"
    assert source["document_count"] == 72
    assert source["page_count"] == 448
    assert source["schema_count"] == 72
    assert source["label_count"] == 72
    assert source["document_format_count"] == 10
    assert source["language_count"] == 12
    assert source["format_counts"] == {
        "csv": 1,
        "docx": 1,
        "html": 1,
        "jpeg": 5,
        "pdf": 58,
        "png": 1,
        "tiff": 1,
        "txt": 1,
        "xlsx": 1,
        "xml": 2,
    }
    assert source["ground_truth_method"] == "hand_verified_schema_shaped_labels"


def test_docubench_improves_invoice_and_multiformat_coverage_without_overclaiming() -> None:
    evidence = _evidence()
    invoice = _mapping(evidence["invoice_source_qualification"])
    assert invoice["direct_product_field_count"] == 11
    assert invoice["derived_product_field_count"] == 1
    assert invoice["source_schema_absent_assumption_fields"] == ["invoice_code"]
    assert invoice["formal_13_field_gate_status"] == (
        "NOT_COMPUTABLE_SOURCE_SCHEMA_MISSING_INVOICE_CODE"
    )

    runtime = _mapping(evidence["current_default_profile_runtime"])
    assert runtime["supported_case_count"] == 65
    assert runtime["parser_pass_count"] == 34
    assert runtime["parser_fail_count"] == 31
    assert runtime["parser_pass_rate"] == "0.523077"
    assert runtime["parser_outcome_counts"] == {
        "OCR_NOT_CONFIGURED": 6,
        "PASSED": 34,
        "PDF_OCR_RENDERER_NOT_CONFIGURED": 23,
        "PDF_PARSE_INVALID": 2,
    }
    assert runtime["passed_page_count_total"] == 115
    assert runtime["passed_page_count_range"] == [1, 22]
    assert runtime["passed_block_count_range"] == [2, 1326]
    assert runtime["warning_code_counts"] == {"PYPDF_ROTATED_TEXT_OUTPUT_INCOMPLETE": 12}


def test_docubench_duplicate_pair_is_a_receipt_proxy_not_invoice_proof() -> None:
    evidence = _evidence()
    duplicate = _mapping(evidence["duplicate_capture_proxy"])
    assert duplicate["ground_truth_labels_identical"] is True
    assert duplicate["document_type"] == "receipt_not_invoice"
    assert duplicate["may_claim_duplicate_invoice_quality"] is False
    assert _mapping(evidence["quality_gate_summary"])["overall_status"] == (
        "MEASURED_FAILED_WITH_STRONGER_MULTIFORMAT_SOURCE"
    )


def test_docubench_evidence_persists_no_raw_labels_or_acceptance_claims() -> None:
    evidence = _evidence()
    boundary = _mapping(evidence["acceptance_boundary"])
    assert boundary["is_public_cross_domain_technical_proxy"] is True
    assert boundary["is_customer_business_representative_dataset"] is False
    assert boundary["is_finaudit_human_uat"] is False
    assert boundary["may_claim_invoice_95_passed"] is False
    assert boundary["may_mark_ac_accepted"] is False

    serialized = json.dumps(evidence, sort_keys=True).lower()
    for forbidden in (
        "expected_output",
        "document_text",
        "label_values",
        "actual_values",
        "tax_id_value",
    ):
        assert forbidden not in serialized
