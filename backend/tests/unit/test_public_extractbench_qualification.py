from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_PATH = PROJECT_ROOT / "tests" / "evaluation" / "public-extractbench-qualification-v1.json"


def _mapping(value: object) -> dict[str, object]:
    assert type(value) is dict
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    assert type(value) is list
    return cast(list[object], value)


def _evidence() -> dict[str, object]:
    return _mapping(json.loads(EVIDENCE_PATH.read_bytes()))


def test_extractbench_evidence_binds_current_product_sources() -> None:
    evidence = _evidence()
    assert evidence["schema_version"] == "public-extractbench-qualification-v1"
    for raw_binding in _list(evidence["source_binding"]):
        binding = _mapping(raw_binding)
        payload = (PROJECT_ROOT / str(binding["path"])).read_bytes()
        assert len(payload) == binding["bytes"]
        assert hashlib.sha256(payload).hexdigest().upper() == binding["sha256"]


def test_extractbench_source_profile_is_complete_and_revision_bound() -> None:
    source = _mapping(_evidence()["source"])
    assert source["dataset_revision"] == "f6180e917a050a84582e6366cff85b7dc1e84e58"
    assert source["license"] == "Apache-2.0"
    assert source["declared_document_count"] == 370
    assert source["declared_page_count"] == 4869
    assert source["observed_row_count"] == 370
    assert source["real_document_count"] == 325
    assert source["synthetic_document_count"] == 45
    assert source["domain_counts"] == {
        "D1": 145,
        "D2": 98,
        "D3": 49,
        "D4": 27,
        "D5": 20,
        "D6": 15,
        "D7": 10,
        "D8": 6,
    }
    assert source["perception_challenge_counts"] == {
        "handwriting": 55,
        "rotated_or_image_only": 38,
        "scanned": 134,
    }


def test_extractbench_invoice_source_is_stronger_but_keeps_mapping_gap_explicit() -> None:
    qualification = _mapping(_mapping(_evidence()["invoice"])["source_qualification"])
    assert qualification["case_count"] == 8
    assert qualification["real_document_count"] == 8
    assert qualification["page_count"] == 18
    assert qualification["scanned_case_count"] == 2
    assert qualification["multi_page_case_count"] == 3
    assert qualification["direct_source_field_count"] == 10
    assert qualification["derived_field_count"] == 1
    assert qualification["source_schema_absent_assumption_field_count"] == 2
    assert qualification["source_schema_absent_assumption_fields"] == [
        "invoice_code",
        "buyer_tax_no",
    ]
    assert qualification["verified_direct_rule_count"] == 80
    assert qualification["evidence_required_direct_rule_count"] == 80
    assert qualification["formal_13_field_gate_status"] == (
        "NOT_COMPUTABLE_SOURCE_SCHEMA_MISSING_TWO_FIELDS"
    )


def test_current_default_profile_fails_the_new_invoice_proxy_without_hiding_nulls() -> None:
    runtime = _mapping(_mapping(_evidence()["invoice"])["current_default_profile_runtime"])
    assert runtime["parser_outcome_counts"] == {
        "PASSED": 6,
        "PDF_OCR_RENDERER_NOT_CONFIGURED": 2,
    }
    assert runtime["valid_output_count"] == 6
    assert runtime["invalid_output_count"] == 2
    assert runtime["actual_non_null_field_count"] == 38
    assert runtime["matched_field_count_including_assumed_nulls"] == 48
    assert runtime["total_field_count"] == 104
    assert runtime["provisional_13_field_accuracy"] == "0.461538"
    assert runtime["annotated_non_null_field_count"] == 83
    assert runtime["matched_annotated_non_null_field_count"] == 32
    assert runtime["annotated_non_null_field_accuracy"] == "0.385542"
    assert runtime["threshold_status"] == "FAILED"


def test_extractbench_evidence_does_not_promote_proxy_or_persist_values() -> None:
    evidence = _evidence()
    assert _mapping(evidence["quality_gate_summary"])["overall_status"] == (
        "MEASURED_FAILED_WITH_STRONGER_INVOICE_SOURCE"
    )
    boundary = _mapping(evidence["acceptance_boundary"])
    assert boundary["is_public_cross_domain_technical_proxy"] is True
    assert boundary["is_customer_business_representative_dataset"] is False
    assert boundary["is_human_uat"] is False
    assert boundary["is_formal_ac_acceptance"] is False
    assert boundary["may_claim_invoice_95_passed"] is False
    assert boundary["may_mark_ac_accepted"] is False

    serialized = json.dumps(evidence, sort_keys=True).lower()
    for forbidden in (
        "expected_output",
        "field_rules",
        "document_text",
        "expected_values",
        "actual_values",
        "tax_id_value",
    ):
        assert forbidden not in serialized
    for raw_case in _list(_mapping(evidence["invoice"])["cases"]):
        case = _mapping(raw_case)
        assert "case_id" not in case
        assert "pdf" not in case
