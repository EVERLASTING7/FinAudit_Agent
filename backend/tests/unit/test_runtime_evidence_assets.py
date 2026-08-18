from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVALUATION_ROOT = PROJECT_ROOT / "tests" / "evaluation"


def _object(name: str) -> dict[str, object]:
    value = json.loads((EVALUATION_ROOT / name).read_bytes())
    assert type(value) is dict
    return value


def _sha256(name: str) -> str:
    return hashlib.sha256((EVALUATION_ROOT / name).read_bytes()).hexdigest().upper()


def _mapping(value: object) -> dict[str, object]:
    assert type(value) is dict
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    assert type(value) is list
    return cast(list[object], value)


def test_synthetic_benchmark_failure_evidence_is_bounded_and_non_acceptance() -> None:
    evidence = _object("synthetic-benchmark-runtime-evidence-v1.json")
    assert evidence["schema_version"] == "synthetic-benchmark-runtime-evidence-v1"
    binding = _mapping(evidence["source_binding"])
    assert binding["review_asset_sha256"] == _sha256(
        "synthetic-benchmark-owner-delegated-review-v1.json"
    )
    assert binding["corpus_asset_sha256"] == _sha256("synthetic-policy-corpus-v1.json")

    attempts = _list(evidence["attempts"])
    assert len(attempts) == 2
    preflight, paid = (_mapping(attempt) for attempt in attempts)
    assert preflight["provider_request_count"] == 0
    assert preflight["actual_input_tokens"] == 0
    assert preflight["actual_cost_microunits"] == 0
    assert paid["failure_code"] == "MVP-UAT-050_EVALUATION_FAILED"
    assert paid["provider_request_count_exact"] is None
    assert paid["actual_input_tokens_exact"] is None
    assert paid["actual_cost_microunits_exact"] is None
    assert paid["safe_bounds"] == {
        "provider_request_count_max_before_stop": 52,
        "input_token_hard_cap": 50000,
        "cost_hard_cap_microunits": 1000000,
        "cost_currency": "CNY",
    }
    assert paid["retry_performed"] is False
    assert paid["index_status_before_cleanup"] == "ready"
    assert paid["qdrant_collection_deleted"] is True
    assert paid["cleanup_remaining_container_count"] == 0

    boundary = _mapping(evidence["acceptance_boundary"])
    assert boundary == {
        "is_business_representative_dataset": False,
        "is_human_uat": False,
        "is_formal_ac_acceptance": False,
        "may_mark_ac_accepted": False,
        "formal_release_passed": False,
        "index_activated": False,
    }
    serialized = json.dumps(evidence, sort_keys=True)
    for forbidden in ("api_key", "secret", "document_content", "vector_values"):
        assert forbidden not in serialized.lower()


def test_batched_synthetic_benchmark_evidence_is_exact_and_stopped_at_50() -> None:
    evidence = _object("synthetic-benchmark-runtime-evidence-v2.json")
    assert evidence["schema_version"] == "synthetic-benchmark-runtime-evidence-v2"
    binding = _mapping(evidence["dataset_binding"])
    assert binding["review_sha256"] == _sha256("synthetic-benchmark-owner-delegated-review-v1.json")
    assert binding["corpus_sha256"] == _sha256("synthetic-policy-corpus-v1.json")

    authorization = _mapping(evidence["authorization"])
    assert authorization == {
        "authority_ref": "docs/change-requests/CR-026-local-test-batched-retrieval-evaluation.md",
        "automatic_scope_expansion": False,
        "cost_cap_microunits": 10000000,
        "cost_currency": "CNY",
        "evaluation_embedding_batch_size": 20,
        "input_token_cap": 50000,
        "no_fx": True,
        "production": False,
        "provider_request_cap": 100,
        "retry_cap": 0,
    }
    assert (PROJECT_ROOT / str(authorization["authority_ref"])).is_file()

    run = _mapping(evidence["run"])
    assert run["status"] == "failed_and_stopped"
    assert run["runner_code"] == "MVP-UAT-050_EVALUATION_FAILED"
    assert run["evaluation_failed_case_ids_status"] == "not_retained_in_this_run"
    assert run["provider_request_count"] == 5
    assert run["actual_input_tokens"] == 4971
    assert run["actual_cost_microunits"] == 2486
    assert run["event_v2_transactional_adoption_status"] == ("completed_for_index_and_mvp_results")
    assert run["ai_call_log_projection_status"] == "not_run_due_mvp_uat_failure"
    assert run["retry_performed"] is False
    assert run["formal_release_100_status"] == "not_run_due_mvp_uat_failure"
    assert run["index_activation_status"] == "not_run"
    assert run["qdrant_collection_deleted"] is True
    assert run["cleanup_remaining_container_count"] == 0
    metrics = _mapping(run["mvp_uat_50_metrics"])
    assert metrics["case_count"] == 50
    assert metrics["case_pass_count"] == 49
    assert metrics["authorization_leak_count"] == 0
    assert metrics["no_answer_false_positive_rate"] == 0.1

    serialized = json.dumps(evidence, sort_keys=True)
    for forbidden in ("api_key", "secret", "query_text", "document_content", "vector_values"):
        assert forbidden not in serialized.lower()


def test_second_batched_run_keeps_runtime_id_and_mapping_boundary_explicit() -> None:
    evidence = _object("synthetic-benchmark-runtime-evidence-v3.json")
    assert evidence["schema_version"] == "synthetic-benchmark-runtime-evidence-v3"
    run = _mapping(evidence["run"])

    assert run["evaluation_failed_runtime_case_ids"] == ["7623955c-d413-44be-ab26-82ab25e24301"]
    assert run["source_case_id_mapping_status"] == "not_retained_in_this_run"
    assert run["provider_request_count"] == 5
    assert run["actual_input_tokens"] == 4971
    assert run["actual_cost_microunits"] == 2486
    assert run["formal_release_100_status"] == "not_run_due_mvp_uat_failure"
    assert run["cleanup_remaining_container_count"] == 0

    serialized = json.dumps(evidence, sort_keys=True)
    for forbidden in ("api_key", "secret", "query_text", "document_content", "vector_values"):
        assert forbidden not in serialized.lower()


def test_chrome_keyboard_evidence_keeps_unrun_accessibility_boundaries() -> None:
    evidence = _object("browser-keyboard-chrome-local-v1.json")
    assert evidence["schema_version"] == "browser-keyboard-chrome-local-v1"
    runtime = _mapping(evidence["runtime"])
    assert runtime["application_gate_status"] == "passed"
    assert runtime["browser_family"] == "Chrome"
    assert runtime["console_warning_error_count"] == 0
    observations = _mapping(evidence["observations"])
    assert observations["login_native_tab_order"] == [
        "username",
        "password",
        "remember_me_checkbox",
        "login_button",
    ]
    assert observations["skip_link_result"] == {
        "location_hash": "#main-content",
        "active_element_tag": "MAIN",
        "active_element_id": "main-content",
        "main_heading": "工作台",
    }
    assert set(_mapping(evidence["not_run"])) == {
        "edge_native_keyboard",
        "screen_reader",
        "all_p0_route_keyboard_matrix",
    }
    assert evidence["acceptance_boundary"] == {
        "is_formal_accessibility_acceptance": False,
        "may_mark_ac_accepted": False,
        "affected_tasks_remain_partial": True,
    }
