from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "scripts" / "prepare_synthetic_benchmark_reviewed_assets.py"
ASSET = PROJECT_ROOT / "tests" / "evaluation" / "synthetic-benchmark-owner-delegated-review-v1.json"


def _load() -> dict[str, object]:
    value = json.loads(ASSET.read_text(encoding="utf-8"))
    assert type(value) is dict
    return cast(dict[str, object], value)


def _mapping(value: object) -> dict[str, object]:
    assert type(value) is dict
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    assert type(value) is list
    return cast(list[object], value)


def _string(value: object) -> str:
    assert type(value) is str
    return value


def test_reviewed_asset_is_reproducible_without_provider_or_database() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "SYNTHETIC_BENCHMARK_REVIEWED_ASSET=PASS"
    assert result.stderr == ""

    artifact = _load()
    assert artifact["schema_version"] == "synthetic-benchmark-owner-delegated-review-v1"
    assert artifact["review_authority"] == {
        "authority_ref": "BOSS-LOCAL-TEST-DELEGATION-20260817",
        "authority_scope": "resolve local/test blockers and run bounded technical evaluation",
        "human_review_claimed": False,
        "review_method": "owner_delegated_agent_semantic_review",
    }
    boundaries = _mapping(artifact["boundaries"])
    assert boundaries["provider_calls_during_generation"] == 0
    assert boundaries["database_access_during_generation"] is False
    assert boundaries["is_human_uat"] is False
    assert boundaries["may_mark_ac_accepted"] is False


def test_reviewed_cases_resolve_queue_and_keep_fixed_50_subset() -> None:
    artifact = _load()
    formal = _mapping(artifact["formal_candidate_100"])
    mvp = _mapping(artifact["mvp_uat_subset_50"])
    decisions = [_mapping(decision) for decision in _list(artifact["human_review_queue_decisions"])]
    formal_cases = [_mapping(case) for case in _list(formal["cases"])]
    formal_case_ids = _list(formal["case_ids"])
    mvp_case_ids = _list(mvp["case_ids"])
    assert formal["approval_state"] == "owner_delegated_local_test_approved"
    assert formal["case_count"] == len(formal_cases) == 100
    assert mvp["case_count"] == len(mvp_case_ids) == 50
    assert set(mvp_case_ids) <= set(formal_case_ids)
    assert len(decisions) == 18
    assert {decision["decision"] for decision in decisions} == {
        "accepted_as_is",
        "revised_and_accepted",
    }
    assert _mapping(artifact["review_summary"])["pending_count"] == 0

    label_counts = {"answerable": 0, "no_answer": 0, "unauthorized": 0}
    no_answer_cases = []
    for case in formal_cases:
        label = _string(case["label"])
        query_text = _string(case["query_text"])
        label_counts[label] += 1
        canonical_query = " ".join(unicodedata.normalize("NFKC", query_text).split()).casefold()
        assert (
            case["query_sha256"]
            == hashlib.sha256(canonical_query.encode("utf-8")).hexdigest().upper()
        )
        if label == "no_answer":
            no_answer_cases.append(case)
    assert label_counts == {"answerable": 60, "no_answer": 20, "unauthorized": 20}
    assert len(no_answer_cases) == 20
    assert all(
        case["review_disposition"] == "revised_for_business_naturalness" for case in no_answer_cases
    )
    rejected_probe_terms = {"装修颜色", "生日月份", "纸张颜色偏好", "界面主题色"}
    assert all(
        not any(term in _string(case["query_text"]) for term in rejected_probe_terms)
        for case in no_answer_cases
    )


def test_reviewed_asset_keeps_bounded_local_test_runtime_authorization() -> None:
    authorization = _mapping(_load()["runtime_authorization"])
    assert authorization == {
        "activate_disposable_index": True,
        "automatic_scope_expansion": False,
        "cost_cap_cny": "1.000000",
        "create_disposable_approved_datasets": True,
        "input_token_cap": 50000,
        "no_fx": True,
        "production": False,
        "provider_request_cap": 152,
        "run_formal_release": True,
        "run_mvp_uat": True,
        "single_run": True,
    }
