from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.performance_metrics import (
    PERFORMANCE_THRESHOLDS_MS,
    RepresentativePerformanceEvaluationInput,
    evaluate_representative_performance,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import evaluate_representative_performance as cli  # noqa: E402


def _payload() -> dict[str, object]:
    rounds: list[dict[str, object]] = []
    for round_number in range(1, 4):
        started_hour = (round_number - 1) * 2
        rounds.append(
            {
                "round_number": round_number,
                "evidence_ref": f"PERF-EVIDENCE-{round_number:02d}",
                "started_at": f"2026-08-16T{started_hour:02d}:00:00+08:00",
                "completed_at": f"2026-08-16T{started_hour + 1:02d}:00:00+08:00",
                "durations_ms": {
                    workload_id: [threshold_ms] * 20
                    for workload_id, threshold_ms in PERFORMANCE_THRESHOLDS_MS.items()
                },
                "unsuccessful_sample_counts": {
                    workload_id: 0 for workload_id in PERFORMANCE_THRESHOLDS_MS
                },
                "upload_waited_for_long_task": False,
                "parallel_audit_task_count": 3,
                "lost_audit_result_count": 0,
                "duplicate_audit_adoption_count": 0,
            }
        )
    return {
        "schema_version": "representative-performance-evaluation-v1",
        "evidence_set_id": "formal-performance-v1",
        "evidence_set_version": "1.0.0",
        "approval_ref": "UAT-PERFORMANCE-APPROVAL-001",
        "representative": True,
        "profile": {
            "environment_id": "staging-performance-01",
            "application_release": "release-candidate-001",
            "hardware_profile": "approved hardware profile PERF-HW-001",
            "model_profile": "approved chat and embedding profile PERF-AI-001",
            "document_profile": "approved invoice contract and query sets PERF-DOC-001",
            "concurrency_profile": "three parallel audit tasks PERF-CONCURRENCY-001",
        },
        "rounds": rounds,
    }


def test_exact_thresholds_pass_without_claiming_formal_acceptance() -> None:
    result = evaluate_representative_performance(
        RepresentativePerformanceEvaluationInput.model_validate(_payload())
    )

    assert result.round_count == 3
    assert result.threshold_status == "PASSED"
    assert result.formal_acceptance_status == "NOT_DETERMINED"
    assert all(round_result.passed for round_result in result.rounds)
    assert all(
        metric.p95_ms == metric.threshold_ms
        for round_result in result.rounds
        for metric in round_result.workloads
    )


def test_cli_returns_pass_without_echoing_raw_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "approved-performance-evidence.json"
    input_path.write_text(json.dumps(_payload()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["evaluate_representative_performance.py", str(input_path)])

    assert cli.main() == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["threshold_status"] == "PASSED"
    assert output["formal_acceptance_status"] == "NOT_DETERMINED"
    assert "durations_ms" not in captured.out
    assert captured.err == ""


def test_nearest_rank_p95_does_not_use_the_maximum_of_twenty_samples() -> None:
    payload = _payload()
    first_round = payload["rounds"][0]  # type: ignore[index]
    first_round["durations_ms"]["list_request"] = [800] * 19 + [50_000]  # type: ignore[index]

    result = evaluate_representative_performance(
        RepresentativePerformanceEvaluationInput.model_validate(payload)
    )

    first_metric = result.rounds[0].workloads[0]
    assert first_metric.workload_id == "list_request"
    assert first_metric.p95_ms == 800
    assert first_metric.passed is True


def test_any_failed_round_fails_the_threshold_status() -> None:
    payload = _payload()
    second_round = payload["rounds"][1]  # type: ignore[index]
    second_round["durations_ms"]["full_rag_response"] = [15_001]  # type: ignore[index]
    second_round["upload_waited_for_long_task"] = True  # type: ignore[index]
    second_round["parallel_audit_task_count"] = 2  # type: ignore[index]
    second_round["lost_audit_result_count"] = 1  # type: ignore[index]
    second_round["unsuccessful_sample_counts"]["top5_retrieval"] = 1  # type: ignore[index]

    result = evaluate_representative_performance(
        RepresentativePerformanceEvaluationInput.model_validate(payload)
    )

    assert result.threshold_status == "FAILED"
    assert result.rounds[1].passed is False
    assert result.rounds[1].upload_async_passed is False
    assert result.rounds[1].parallel_audit.passed is False
    assert result.rounds[1].workloads[4].passed is False


def test_missing_workload_is_rejected() -> None:
    payload = _payload()
    first_round = payload["rounds"][0]  # type: ignore[index]
    del first_round["durations_ms"]["top5_retrieval"]  # type: ignore[index]

    with pytest.raises(ValidationError, match="every frozen workload"):
        RepresentativePerformanceEvaluationInput.model_validate(payload)


def test_non_consecutive_or_overlapping_rounds_are_rejected() -> None:
    payload = _payload()
    payload["rounds"][1]["round_number"] = 3  # type: ignore[index]
    with pytest.raises(ValidationError, match="round_number must be consecutive"):
        RepresentativePerformanceEvaluationInput.model_validate(payload)

    payload = _payload()
    payload["rounds"][1]["started_at"] = "2026-08-16T00:30:00+08:00"  # type: ignore[index]
    with pytest.raises(ValidationError, match="must not overlap"):
        RepresentativePerformanceEvaluationInput.model_validate(payload)


def test_non_positive_duration_or_excess_unsuccessful_count_is_rejected() -> None:
    payload = _payload()
    first_round = payload["rounds"][0]  # type: ignore[index]
    first_round["durations_ms"]["list_request"] = [0]  # type: ignore[index]
    with pytest.raises(ValidationError, match="greater than 0"):
        RepresentativePerformanceEvaluationInput.model_validate(payload)

    payload = _payload()
    first_round = payload["rounds"][0]  # type: ignore[index]
    first_round["unsuccessful_sample_counts"]["list_request"] = 21  # type: ignore[index]
    with pytest.raises(ValidationError, match="cannot exceed sample count"):
        RepresentativePerformanceEvaluationInput.model_validate(payload)
