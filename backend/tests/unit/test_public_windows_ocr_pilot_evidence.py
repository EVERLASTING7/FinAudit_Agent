from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_PATH = PROJECT_ROOT / "tests" / "evaluation" / "public-windows-ocr-pilot-v1.json"


def _mapping(value: object) -> dict[str, object]:
    assert type(value) is dict
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    assert type(value) is list
    return cast(list[object], value)


def _evidence() -> dict[str, object]:
    return _mapping(json.loads(EVIDENCE_PATH.read_bytes()))


def test_windows_ocr_pilot_binds_current_sources_and_removes_raw_output() -> None:
    evidence = _evidence()
    assert evidence["schema_version"] == "public-windows-ocr-pilot-v1"
    for raw_binding in _list(evidence["source_binding"]):
        binding = _mapping(raw_binding)
        source = PROJECT_ROOT / str(binding["path"])
        payload = source.read_bytes()
        assert len(payload) == binding["bytes"]
        assert hashlib.sha256(payload).hexdigest().upper() == binding["sha256"]

    runtime = _mapping(evidence["runtime"])
    assert runtime == {
        "case_count": 77,
        "engine": "windows-media-ocr",
        "languages": ["en-US", "zh-Hans-CN"],
        "paid_cost_cny": "0.000000",
        "provider_network_calls": 0,
        "raw_ocr_text_persisted_in_evidence": False,
        "temporary_raw_ocr_output_removed": True,
    }


def test_windows_ocr_pilot_records_failed_contract_invoice_and_form_quality() -> None:
    metrics = _mapping(_evidence()["metrics"])
    assert metrics["failure_count"] == 0

    invoice = _mapping(metrics["invoice"])
    assert invoice["case_count"] == 20
    assert invoice["matched_direct_field_count"] == 28
    assert invoice["total_direct_field_count"] == 140
    assert invoice["direct_field_accuracy"] == "0.200000"
    assert invoice["threshold_status"] == "FAILED"

    xfund = _mapping(metrics["xfund"])
    assert xfund["case_count"] == 20
    assert xfund["matched_entity_count"] == 1169
    assert xfund["total_entity_count"] == 1418
    assert xfund["entity_recall"] == "0.824401"

    contract = _mapping(metrics["contract"])
    assert contract["case_count"] == 3
    assert contract["matched_direct_field_count"] == 7
    assert contract["total_direct_field_count"] == 27
    assert contract["direct_field_visibility"] == "0.259259"
    assert contract["threshold_status"] == "FAILED"
    assert [_mapping(case)["case_id"] for case in _list(contract["cases"])] == [
        "93691",
        "93704",
        "94358",
    ]


def test_local_qwen_pilot_stopped_without_output_or_external_cost() -> None:
    evidence = _evidence()
    qwen = _mapping(evidence["local_qwen_contract_pilot"])
    assert qwen == {
        "attempt_count": 3,
        "cleanup_listener_11434": False,
        "cleanup_listener_8764": False,
        "cleanup_remaining_process_count": 0,
        "filtered_json_mode_attempt": {
            "block_selection": "field_term_plus_adjacent_lines_max_80",
            "elapsed_ms": "107781.000",
            "eval_count": 806,
            "expected_field_count": 9,
            "matched_field_count": 0,
            "ocr_block_count": 80,
            "output_valid": False,
            "prompt_eval_count": 4098,
            "response_sha256": ("A01C461CE3A02843ED06A4E29C9270D32612679341DD6ACA94DD2D6A445DA8A0"),
            "status": "COMPLETED_INVALID_OUTPUT",
        },
        "full_json_mode_attempt": "TIMEOUT_300_SECONDS",
        "model": "qwen3:8b",
        "model_storage": "preexisting_local_cache",
        "output_adopted": False,
        "paid_cost_cny": "0.000000",
        "production_schema_attempt": "HTTP_400_GRAMMAR_REGEX_UNSUPPORTED",
        "provider_network_calls": 0,
        "retry_count": 0,
    }
    assert _mapping(evidence["quality_gate_summary"])["overall_status"] == "MEASURED_FAILED"
    assert _mapping(evidence["acceptance_boundary"]) == {
        "default_local_profile_changed": False,
        "is_customer_business_representative_dataset": False,
        "is_formal_ac_acceptance": False,
        "is_human_uat": False,
        "may_mark_ac_accepted": False,
    }

    for raw_case in _list(_mapping(_mapping(evidence["metrics"])["contract"])["cases"]):
        case = _mapping(raw_case)
        assert "ocr_text" not in case
        assert "expected_values" not in case
        assert "actual_values" not in case
