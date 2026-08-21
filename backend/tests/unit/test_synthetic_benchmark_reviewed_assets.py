from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVALUATION_ROOT = PROJECT_ROOT / "tests" / "evaluation"
SCRIPT = PROJECT_ROOT / "scripts" / "prepare_synthetic_benchmark_reviewed_assets.py"
ASSET = EVALUATION_ROOT / "synthetic-benchmark-owner-delegated-review-v3.json"
PREDECESSOR = EVALUATION_ROOT / "synthetic-benchmark-owner-delegated-review-v2.json"


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
    assert artifact["schema_version"] == "synthetic-benchmark-owner-delegated-review-v3"
    assert artifact["review_authority"] == {
        "authority_ref": "BOSS-P1-KB-QUALITY-V2-DIAGNOSIS-20260820",
        "authority_scope": (
            "fix the retained approval no-answer collision; runtime requires new authorization"
        ),
        "human_review_claimed": False,
        "review_method": "retained_source_case_diagnosis_with_offline_collision_audit",
    }
    boundaries = _mapping(artifact["boundaries"])
    assert boundaries["provider_calls_during_generation"] == 0
    assert boundaries["database_access_during_generation"] is False
    assert boundaries["is_human_uat"] is False
    assert boundaries["may_mark_ac_accepted"] is False

    source_binding = _mapping(artifact["source_binding"])
    assert (
        source_binding["predecessor_sha256"]
        == hashlib.sha256(PREDECESSOR.read_bytes()).hexdigest().upper()
    )


def test_reviewed_asset_revises_the_retained_failed_source_case() -> None:
    artifact = _load()
    revision = _mapping(artifact["revision"])
    audit = _mapping(revision["offline_audit"])
    formal = _mapping(artifact["formal_candidate_100"])
    cases = [_mapping(case) for case in _list(formal["cases"])]
    revised = next(case for case in cases if case["case_id"] == "SBCV1-N-APPROVAL-01")
    prior_revision = next(case for case in cases if case["case_id"] == "SBCV1-N-INVOICE-02")

    assert revision["failed_source_case_id"] == "SBCV1-N-APPROVAL-01"
    assert (
        revision["runtime_evidence_sha256"]
        == hashlib.sha256(
            (EVALUATION_ROOT / "synthetic-benchmark-runtime-evidence-v4.json").read_bytes()
        )
        .hexdigest()
        .upper()
    )
    assert revision["prior_v2_invoice_revision_preserved"] is True
    assert revised["query_text"] == (
        "按2026-06-30有效制度，付款审批通知是否规定统一的邮件标题格式？"
    )
    assert revised["absence_probe"] == "付款审批通知邮件标题"
    assert prior_revision["query_text"] == (
        "按2026-06-30有效制度，发票影像归档文件需要保留多少年？"
    )
    assert audit == {
        "answer_score_threshold": "0.650000",
        "local_files_only": True,
        "model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "not_provider_score_proof": True,
        "original_max_similarity": "0.547008",
        "provider_calls": 0,
        "replacement_max_similarity": "0.453996",
    }


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
        "authorization_state": "requires_new_explicit_authorization",
        "activate_disposable_index": True,
        "automatic_scope_expansion": False,
        "cost_cap_cny": "0.100000",
        "create_disposable_approved_datasets": True,
        "input_token_cap": 50000,
        "no_fx": True,
        "production": False,
        "provider_request_cap": 10,
        "run_formal_release": True,
        "run_mvp_uat": True,
        "single_run": True,
    }
