from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import generate_synthetic_non_acceptance_dataset as subject  # noqa: E402

ASSET_PATH = PROJECT_ROOT / "tests" / "evaluation" / "synthetic-non-acceptance-v1.json"
EXPECTED_ASSET_SHA256 = "E15784ECA50B142FEE05F78DF212766196B95F7859117807E051E4890E2D7880"


def _asset() -> dict[str, object]:
    value = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def test_generated_asset_matches_the_checked_in_bytes() -> None:
    expected = subject.render_payload(subject.build_payload())
    actual = ASSET_PATH.read_bytes()

    assert actual == expected
    assert hashlib.sha256(actual).hexdigest().upper() == EXPECTED_ASSET_SHA256


def test_dataset_has_fixed_deduplication_coverage_and_non_acceptance_controls() -> None:
    asset = _asset()
    candidates = asset["candidates"]
    deduplication = asset["deduplication"]
    fixed_subset = asset["fixed_subset"]
    coverage = asset["coverage_matrix"]

    assert type(candidates) is list
    assert type(deduplication) is dict
    assert type(fixed_subset) is dict
    assert type(coverage) is dict
    assert len(candidates) == 120
    assert deduplication["selected_case_count"] == 100
    assert deduplication["rejected_duplicate_count"] == 20
    assert fixed_subset["case_count"] == 50
    assert coverage["candidate_120"]["label_counts"] == {
        "answerable": 72,
        "no_answer": 24,
        "unauthorized": 24,
    }
    assert coverage["deduplicated_100"]["label_counts"] == {
        "answerable": 60,
        "no_answer": 20,
        "unauthorized": 20,
    }
    assert coverage["fixed_subset_50"]["label_counts"] == {
        "answerable": 30,
        "no_answer": 10,
        "unauthorized": 10,
    }
    assert asset["controls"] == {
        "approval_state": "not_submitted",
        "index_activation": "not_run",
        "provider_calls_executed": 0,
        "runtime_tier": None,
    }
    serialized = ASSET_PATH.read_text(encoding="utf-8")
    assert '"formal_release"' not in serialized
    assert '"accepted"' not in serialized


def test_evidence_and_paid_budget_are_source_backed_but_not_run() -> None:
    asset = _asset()
    evidence = asset["evidence_verification"]
    estimate = asset["paid_run_budget_estimate"]
    source_manifest = asset["source_manifest"]

    assert type(evidence) is dict
    assert type(estimate) is dict
    assert type(source_manifest) is list
    assert evidence["status"] == "passed"
    assert len(evidence["checks"]) == 8
    assert {check["status"] for check in evidence["checks"]} == {"passed"}
    assert len(source_manifest) == 8
    assert estimate["actual_run_status"] == "not_run"
    assert estimate["cost_currency"] == "CNY"
    assert estimate["no_fx"] is True
    assert [scenario["provider_request_count"] for scenario in estimate["scenarios"]] == [
        50,
        51,
        100,
        101,
    ]
    assert [scenario["estimated_max_cost_microunits"] for scenario in estimate["scenarios"]] == [
        1617,
        1760,
        3315,
        3458,
    ]
    assert all(scenario["actual_cost_microunits"] is None for scenario in estimate["scenarios"])
