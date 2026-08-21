from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "run_live_bailian_synthetic_benchmark.py"


def _load_subject() -> Any:
    """Load the script module through its dynamic boundary for focused tests."""
    spec = importlib.util.spec_from_file_location("live_synthetic_benchmark_subject", SCRIPT)
    assert spec is not None and spec.loader is not None
    subject = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(subject)
    return subject


def _run(*, confirmed: bool) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["EMBEDDING_API_KEY"] = ""
    environment.pop("FINAUDIT_REUSE_REPOSITORY_BAILIAN_KEY", None)
    if confirmed:
        environment["FINAUDIT_LIVE_BAILIAN_SYNTHETIC_BENCHMARK"] = (
            "RUN_BAILIAN_V3_AUTHORIZED_20260820"
        )
    else:
        environment.pop("FINAUDIT_LIVE_BAILIAN_SYNTHETIC_BENCHMARK", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )


def test_live_synthetic_benchmark_requires_explicit_paid_run_confirmation() -> None:
    result = _run(confirmed=False)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "code": "LIVE_SYNTHETIC_BENCHMARK_CONFIRMATION_REQUIRED",
        "status": "failed",
    }
    assert result.stderr == ""


def test_authorized_benchmark_still_requires_explicit_repository_key_reuse() -> None:
    result = _run(confirmed=True)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "code": "EMBEDDING_API_KEY_REQUIRED",
        "status": "failed",
    }
    assert result.stderr == ""


def test_live_synthetic_benchmark_failure_emits_only_safe_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subject = _load_subject()

    def failed_run() -> dict[str, object]:
        subject._SAFE_FAILURE_TELEMETRY.update(
            actual_cost_microunits=4321,
            actual_input_tokens=8765,
            authorization_receipt_sha256=subject._AUTHORIZATION_SHA256,
            automatic_provider_retry_count=0,
            cost_cap_microunits=10_000_000,
            cost_currency="CNY",
            evaluation_failed_case_ids=("MVP-UAT-050-CASE-017",),
            evaluation_failure_code="RETRIEVAL_QUALITY_GATE_FAILED",
            evaluation_metrics={"case_pass_count": 49},
            evaluation_status="failed",
            evaluation_tier="mvp-uat-050",
            input_token_upper_bound=16576,
            input_token_cap=50_000,
            provider_request_cap=10,
            provider_request_count=5,
            retest_authorized_within_remaining_cumulative_caps=True,
        )
        raise subject.LiveSyntheticBenchmarkError("MVP-UAT-050_EVALUATION_FAILED")

    monkeypatch.setattr(subject, "_run", failed_run)
    assert subject.main() == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    result = json.loads(captured.out)
    assert result == {
        "actual_cost_microunits": 4321,
        "actual_input_tokens": 8765,
        "authorization_receipt_sha256": subject._AUTHORIZATION_SHA256,
        "automatic_provider_retry_count": 0,
        "code": "MVP-UAT-050_EVALUATION_FAILED",
        "cost_cap_microunits": 10_000_000,
        "cost_currency": "CNY",
        "evaluation_failed_case_ids": ["MVP-UAT-050-CASE-017"],
        "evaluation_failure_code": "RETRIEVAL_QUALITY_GATE_FAILED",
        "evaluation_metrics": {"case_pass_count": 49},
        "evaluation_status": "failed",
        "evaluation_tier": "mvp-uat-050",
        "input_token_upper_bound": 16576,
        "input_token_cap": 50_000,
        "provider_request_cap": 10,
        "provider_request_count": 5,
        "retest_authorized_within_remaining_cumulative_caps": True,
        "status": "failed",
    }
    serialized = json.dumps(result, sort_keys=True)
    assert "api_key" not in serialized
    assert "query_text" not in serialized
    assert "vector" not in serialized


def test_live_synthetic_benchmark_freezes_the_batched_request_plan() -> None:
    subject = _load_subject()
    review, corpus = subject._load_assets()

    mvp_calls = subject._batched_texts(
        tuple(f"mvp-{index}" for index in range(50)),
        subject._EVALUATION_EMBEDDING_BATCH_SIZE,
    )
    formal_calls = subject._batched_texts(
        tuple(f"formal-{index}" for index in range(100)),
        subject._EVALUATION_EMBEDDING_BATCH_SIZE,
    )

    assert review["schema_version"] == "synthetic-benchmark-owner-delegated-review-v3"
    assert review["runtime_authorization"]["authorization_state"] == (
        "requires_new_explicit_authorization"
    )
    assert review["runtime_authorization"]["provider_request_cap"] == 10
    assert corpus["schema_version"] == "synthetic-policy-corpus-v1"
    assert tuple(map(len, mvp_calls)) == (20, 20, 10)
    assert tuple(map(len, formal_calls)) == (20, 20, 20, 20, 20)
    assert 2 + len(mvp_calls) + len(formal_calls) == subject._EXPECTED_PROVIDER_REQUESTS == 10
    assert subject._MAX_PROVIDER_REQUESTS == 10
    assert subject._MAX_INPUT_TOKENS == 50_000
    assert subject._MAX_COST_MICROCNY == 10_000_000
    assert subject._AUTHORIZATION_GRANTED is True
    assert subject._AUTHORIZATION_SHA256 == (
        "120618F65F519700E10EC0FB9CAFC94B44B03EE757FAE0A78D732126A2720B72"
    )
    source = SCRIPT.read_text(encoding="utf-8")
    assert "len(logs) != _EXPECTED_PROVIDER_REQUESTS" in source
    assert "len(logs) != _MAX_PROVIDER_REQUESTS" not in source
    assert "case_source_ids[value]" in source
    assert "evaluation_failed_case_ids=failed_case_ids" in source
