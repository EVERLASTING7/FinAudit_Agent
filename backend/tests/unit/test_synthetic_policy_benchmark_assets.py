from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import generate_synthetic_policy_benchmark_assets as subject  # noqa: E402

CORPUS_PATH = PROJECT_ROOT / "tests" / "evaluation" / "synthetic-policy-corpus-v1.json"
BENCHMARK_PATH = PROJECT_ROOT / "tests" / "evaluation" / "synthetic-benchmark-candidate-v1.json"
REVIEW_PACKET_PATH = PROJECT_ROOT / "docs" / "testing" / "synthetic-benchmark-human-review-v1.md"
EXPECTED_CORPUS_SHA256 = "2CE2BE5118ADAC7D185D239AFD4713D3F637BDF9D12D314D7690732A8DFAD9E3"
EXPECTED_BENCHMARK_SHA256 = "A5A9C179B6F344C5CDA8B50089AC85254E87BDB62694D6B9360A6F5D46327C03"


def _asset(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def test_generated_assets_match_checked_in_bytes_and_hashes() -> None:
    _, expected_corpus, _, expected_benchmark = subject.build_assets()
    actual_corpus = CORPUS_PATH.read_bytes()
    actual_benchmark = BENCHMARK_PATH.read_bytes()

    assert actual_corpus == expected_corpus
    assert actual_benchmark == expected_benchmark
    assert hashlib.sha256(actual_corpus).hexdigest().upper() == EXPECTED_CORPUS_SHA256
    assert hashlib.sha256(actual_benchmark).hexdigest().upper() == EXPECTED_BENCHMARK_SHA256


def test_corpus_is_fictional_versioned_and_non_acceptance_only() -> None:
    corpus = _asset(CORPUS_PATH)

    assert corpus["schema_version"] == "synthetic-policy-corpus-v1"
    assert corpus["inventory"] == {
        "clause_count": 36,
        "domain_count": 6,
        "policy_family_count": 6,
        "policy_version_count": 12,
    }
    assert {family["domain"] for family in corpus["policy_families"]} == {
        "reimbursement",
        "vendor",
        "invoice",
        "contract",
        "approval_authority",
        "audit_trail",
    }
    assert corpus["access_model"]["authorized_role_labels"] == [
        "audit_reviewer",
        "contract_admin",
        "finance_reviewer",
    ]
    assert corpus["access_model"]["unauthorized_role_labels"] == [
        "read_only",
        "system_admin",
    ]
    assert corpus["data_safety"] == {
        "fictional_monetary_thresholds_only": True,
        "fictional_only": True,
        "real_company_data_included": False,
        "real_financial_records_included": False,
        "real_person_data_included": False,
        "synthetic_organization_label": "虚构测试组织",
    }
    assert corpus["controls"] == {
        "approved_dataset_created": False,
        "approval_state": "not_submitted",
        "index_activation": "not_run",
        "provider_calls_executed": 0,
        "release_gate_execution": "not_run",
        "runtime_tier": None,
    }
    assert corpus["quality_verification"]["status"] == "passed"
    assert len(corpus["source_inventory"]) == 12


def test_benchmark_has_required_grain_evidence_and_coverage() -> None:
    benchmark = _asset(BENCHMARK_PATH)
    cases = benchmark["candidate_cases"]
    coverage = benchmark["coverage_matrix"]
    proposal = benchmark["formal_candidate_proposal_100"]
    fixed = benchmark["mvp_uat_subset_50"]

    assert len(cases) == 120
    assert len({case["case_id"] for case in cases}) == 120
    assert len({case["query_sha256"] for case in cases}) == 120
    assert proposal["case_count"] == 100
    assert proposal["not_proposed_case_count"] == 20
    assert proposal["status"] == "proposal_only"
    assert fixed["case_count"] == 50
    assert fixed["status"] == "fixed_candidate_subset"
    assert set(fixed["case_ids"]).issubset(proposal["case_ids"])
    assert coverage["candidate_120"]["label_counts"] == {
        "answerable": 72,
        "no_answer": 24,
        "unauthorized": 24,
    }
    assert coverage["formal_candidate_proposal_100"]["label_counts"] == {
        "answerable": 60,
        "no_answer": 20,
        "unauthorized": 20,
    }
    assert coverage["mvp_uat_subset_50"]["label_counts"] == {
        "answerable": 30,
        "no_answer": 10,
        "unauthorized": 10,
    }
    assert coverage["candidate_120"]["domain_counts"] == {
        "approval_authority": 20,
        "audit_trail": 20,
        "contract": 20,
        "invoice": 20,
        "reimbursement": 20,
        "vendor": 20,
    }
    assert coverage["candidate_120"]["scenario_tag_counts"]["synonym_rewrite"] == 36
    assert coverage["mvp_uat_subset_50"]["scenario_tag_counts"]["synonym_rewrite"] == 6
    assert coverage["candidate_120"]["scenario_tag_counts"]["cross_permission"] == 24

    for case in cases:
        assert case["benchmark_date"] in {"2025-06-30", "2026-06-30"}
        assert case["required_permission"] == "knowledge.use"
        assert case["top_k"] == 5
        if case["label"] == "answerable":
            assert len(case["allowed_policy_refs"]) == 1
            assert len(case["expected_evidence_refs"]) == 1
            assert len(case["expected_evidence_sha256"]) == 1
            assert len(case["forbidden_evidence_refs"]) == 1
        elif case["label"] == "no_answer":
            assert len(case["allowed_policy_refs"]) == 1
            assert case["absence_probe"]
            assert case["expected_evidence_refs"] == []
            assert len(case["forbidden_evidence_refs"]) == 3
        else:
            assert case["label"] == "unauthorized"
            assert case["allowed_policy_refs"] == []
            assert case["expected_evidence_refs"] == []
            assert len(case["forbidden_evidence_refs"]) == 1


def test_quality_report_requires_human_review_and_keeps_runtime_boundaries() -> None:
    benchmark = _asset(BENCHMARK_PATH)
    report = benchmark["quality_report"]
    review_queue = benchmark["human_review_queue"]
    proposal_ids = set(benchmark["formal_candidate_proposal_100"]["case_ids"])

    assert report["automated_status"] == "passed"
    assert report["human_review_required_before_approval"] is True
    assert report["human_review_status"] == "pending"
    assert len(report["automated_checks"]) == 8
    assert {check["status"] for check in report["automated_checks"]} == {"passed"}
    assert len(review_queue) == 18
    assert {item["status"] for item in review_queue} == {"pending_human_review"}
    assert {item["case_id"] for item in review_queue}.issubset(proposal_ids)
    assert benchmark["controls"] == {
        "ac_status_changes": 0,
        "approved_dataset_created": False,
        "approval_state": "not_submitted",
        "index_activation": "not_run",
        "provider_calls_executed": 0,
        "release_gate_execution": "not_run",
        "runtime_tier": None,
    }
    serialized = BENCHMARK_PATH.read_text(encoding="utf-8")
    assert '"formal_release"' not in serialized
    assert '"accepted"' not in serialized


def test_human_review_packet_is_complete_but_not_an_approval() -> None:
    benchmark = _asset(BENCHMARK_PATH)
    review_packet = REVIEW_PACKET_PATH.read_text(encoding="utf-8")
    expected_ids = {item["case_id"] for item in benchmark["human_review_queue"]}
    listed_ids = re.findall(
        r"`(SBCV1-(?:A-[A-Z]+-V[12]-\d{2}-[12]|[NU]-[A-Z]+-\d{2}))`",
        review_packet,
    )

    assert len(listed_ids) == 18
    assert set(listed_ids) == expected_ids
    assert EXPECTED_CORPUS_SHA256 in review_packet
    assert EXPECTED_BENCHMARK_SHA256 in review_packet
    assert "状态：`pending_human_review`" in review_packet
    assert "当前审批状态 | `not_submitted`" in review_packet
    assert "人工结论：`待填写`" in review_packet
    assert "Provider 调用 | `0`" in review_packet
    assert "formal_release" not in review_packet
    assert "accepted" not in review_packet


def test_paid_run_estimate_is_source_backed_but_not_executed() -> None:
    benchmark = _asset(BENCHMARK_PATH)
    estimate = benchmark["paid_run_budget_estimate"]
    scenarios = estimate["steps_and_scenarios"]

    assert estimate["actual_run_status"] == "not_run"
    assert estimate["cost_currency"] == "CNY"
    assert estimate["no_fx"] is True
    assert estimate["input_price_microunits_per_million"] == 500000
    assert [scenario["provider_request_count"] for scenario in scenarios] == [
        2,
        50,
        100,
        150,
        152,
    ]
    assert [scenario["input_token_upper_bound"] for scenario in scenarios] == [
        4079,
        4216,
        8281,
        12497,
        16576,
    ]
    assert [scenario["estimated_max_cost_microunits"] for scenario in scenarios] == [
        2040,
        2108,
        4141,
        6249,
        8288,
    ]
    assert all(scenario["actual_input_tokens"] is None for scenario in scenarios)
    assert all(scenario["actual_cost_microunits"] is None for scenario in scenarios)
