from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_PATH = PROJECT_ROOT / "tests" / "evaluation" / "public-business-benchmark-runtime-v1.json"


def _mapping(value: object) -> dict[str, object]:
    assert type(value) is dict
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    assert type(value) is list
    return cast(list[object], value)


def _evidence() -> dict[str, object]:
    return _mapping(json.loads(EVIDENCE_PATH.read_bytes()))


def test_public_business_evidence_binds_current_measurement_sources() -> None:
    evidence = _evidence()
    assert evidence["schema_version"] == "public-business-benchmark-runtime-v1"
    assert evidence["source_qualification_status"] == "PASSED"

    for raw_binding in _list(evidence["source_binding"]):
        binding = _mapping(raw_binding)
        source = PROJECT_ROOT / str(binding["path"])
        payload = source.read_bytes()
        assert len(payload) == binding["bytes"]
        assert hashlib.sha256(payload).hexdigest().upper() == binding["sha256"]

    authority = _mapping(evidence["selection_authority"])
    assert authority["approval_ref"] is None
    assert authority["approval_ref_provided"] is False
    assert authority["human_review_claimed"] is False


def test_public_contract_measurement_separates_digital_and_scanned_results() -> None:
    evidence = _evidence()
    cuad = _mapping(_mapping(evidence["contract"])["current_profile_runtime"])
    assert cuad["parser_pass_count"] == 12
    assert cuad["parser_fail_count"] == 0
    assert cuad["total_page_count"] == 490
    assert cuad["min_page_count"] == 8
    assert cuad["max_page_count"] == 82
    assert cuad["expected_direct_field_count"] == 47
    assert cuad["actual_non_null_frozen_field_count"] == 0
    assert cuad["direct_field_accuracy"] == "0.000000"
    assert cuad["threshold_status"] == "FAILED"

    chinese = _mapping(evidence["chinese_government_contracts"])
    source = _mapping(chinese["source"])
    assert source["case_count"] == 10
    assert source["public_disclosure"] is True
    assert source["explicit_open_data_license"] is False
    assert source["raw_redistribution_authorized"] is False
    annotation = _mapping(chinese["annotation_quality"])
    assert annotation["expected_direct_field_count"] == 90
    assert annotation["direct_schema_coverage_count"] == 9
    assert annotation["gold_values_persisted"] is False
    runtime = _mapping(chinese["current_profile_runtime"])
    assert runtime["parser_pass_count"] == 0
    assert runtime["parser_fail_count"] == 10
    assert runtime["parser_outcome_counts"] == {"PDF_OCR_RENDERER_NOT_CONFIGURED": 10}
    assert runtime["total_page_count"] == 196
    assert runtime["min_page_count"] == 6
    assert runtime["max_page_count"] == 51
    assert runtime["matched_direct_field_count"] == 0

    coverage = _mapping(evidence["contract_source_coverage"])
    assert coverage["combined_direct_schema_coverage_count"] == 9
    assert coverage["frozen_field_count"] == 13
    assert coverage["formal_gate_status"] == ("NOT_COMPUTABLE_INSUFFICIENT_SOURCE_FIELD_COVERAGE")


def test_public_invoice_duplicates_and_complex_forms_keep_failed_boundaries() -> None:
    evidence = _evidence()
    invoice = _mapping(evidence["invoice"])
    source = _mapping(invoice["source"])
    assert source["document_count"] == 813
    assert source["image_extension_counts"] == {".jpg": 813}
    runtime = _mapping(invoice["current_profile_runtime"])
    assert runtime["sample_count"] == 50
    assert runtime["valid_output_count"] == 0
    assert runtime["failure_code_counts"] == {"OCR_NOT_CONFIGURED": 50}
    assert runtime["direct_field_accuracy"] == "0.000000"
    assert runtime["threshold_status"] == "FAILED"

    duplicate = _mapping(invoice["duplicate_ground_truth"])
    assert duplicate["duplicate_identity_group_count"] == 55
    assert duplicate["duplicate_identity_document_count"] == 117
    assert duplicate["max_duplicate_group_size"] == 4
    assert duplicate["product_complete_identity_count"] == 0
    assert duplicate["metric_status"] == "NOT_COMPUTABLE_SOURCE_LACKS_INVOICE_CODE"

    xfund = _mapping(evidence["chinese_complex_forms"])
    assert _mapping(xfund["source"])["document_count"] == 50
    assert _mapping(xfund["annotation_quality"])["entity_count"] == 3629
    assert _mapping(xfund["current_profile_runtime"])["failure_code_counts"] == {
        "OCR_NOT_CONFIGURED": 50
    }

    risk = _mapping(evidence["risk_rule_ground_truth"])
    assert risk["independent_matching_label_count"] == 0
    assert risk["metric_status"] == "NOT_COMPUTABLE_NO_INDEPENDENT_MATCHING_GROUND_TRUTH"
    complex_quality = _mapping(evidence["complex_multi_format"])
    assert complex_quality["digital_english_contract_pdf_status"] == "PASSED"
    assert complex_quality["scanned_chinese_contract_pdf_status"] == ("FAILED_OCR_NOT_CONFIGURED")
    assert complex_quality["quality_status"] == (
        "PARTIAL_PDF_PASS_IMAGE_OCR_DISABLED_DOCX_NOT_COVERED"
    )


def test_public_evidence_does_not_claim_business_acceptance_or_persist_raw_values() -> None:
    evidence = _evidence()
    assert _mapping(evidence["quality_gate_summary"])["overall_status"] == "MEASURED_FAILED"
    assert _mapping(evidence["privacy_and_storage"]) == {
        "business_identifiers_persisted_in_evidence": False,
        "raw_annotation_values_persisted_in_evidence": False,
        "raw_data_git_ignored": True,
        "raw_data_path": "data/public-benchmark/",
        "raw_documents_tracked": False,
        "raw_value_cross_check_candidate_count": 4442,
        "raw_value_cross_check_generic_metadata_coincidence_count": 2,
        "raw_value_cross_check_persisted_match_count": 0,
        "tracked_output_contains_only_counts_hashes_and_status": True,
    }
    assert _mapping(evidence["acceptance_boundary"]) == {
        "is_customer_business_representative_dataset": False,
        "is_formal_ac_acceptance": False,
        "is_human_uat": False,
        "is_public_cross_domain_technical_measurement": True,
        "may_claim_contract_85_passed": False,
        "may_claim_invoice_95_passed": False,
        "may_mark_ac_accepted": False,
    }

    for section_name in ("contract", "chinese_government_contracts"):
        for raw_case in _list(_mapping(evidence[section_name])["cases"]):
            case = _mapping(raw_case)
            assert "expected_values" not in case
            assert "actual_values" not in case
            assert "document_text" not in case
