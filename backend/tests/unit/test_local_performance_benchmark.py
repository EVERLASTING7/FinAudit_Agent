from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import benchmark_local_performance as subject  # noqa: E402


def test_p95_uses_nearest_rank_for_twenty_samples() -> None:
    samples = [float(value) for value in range(1, 21)]

    assert subject._p95(samples) == 19.0


def test_p95_rejects_an_empty_sample() -> None:
    with pytest.raises(subject.PerformanceError, match="EMPTY_PERFORMANCE_SAMPLE"):
        subject._p95([])


def test_seed_identities_are_stable_and_separated() -> None:
    run_id = "a" * 32

    assert subject._stable_id(run_id, "invoice", 1) == subject._stable_id(run_id, "invoice", 1)
    assert subject._stable_id(run_id, "invoice", 1) != subject._stable_id(run_id, "invoice", 2)
    assert subject._stable_id(run_id, "invoice", 1) != subject._stable_id(run_id, "invoice-item", 1)


def test_performance_pdf_is_valid_and_unique_per_sample() -> None:
    run_id = "b" * 32

    first = subject._performance_pdf(run_id, 1, 1)
    second = subject._performance_pdf(run_id, 1, 2)

    assert first.startswith(b"%PDF")
    assert first.rstrip().endswith(b"%%EOF")
    assert first != second


def test_task_prefix_is_contract_safe() -> None:
    prefix = subject._task_prefix("c" * 32)

    assert prefix == "LP-CCCCCCCCCCCC-"
    assert len(f"{prefix}3-3") <= 80


def test_batch_file_names_are_run_scoped() -> None:
    first = subject._batch_file_name("a" * 32, 1, 1)
    second = subject._batch_file_name("b" * 32, 1, 1)

    assert first == "local-performance-batch-aaaaaaaaaaaa-01-01.pdf"
    assert first != second


def test_validate_batch_limit_response_accepts_contract_error() -> None:
    response = subject.httpx.Response(
        413,
        json={
            "code": "BATCH_LIMIT_EXCEEDED",
            "trace_id": "70000000-0000-4000-8000-000000000001",
        },
    )

    subject._validate_batch_limit_response(response)


def test_validate_batch_limit_response_rejects_wrong_status() -> None:
    response = subject.httpx.Response(
        422,
        json={
            "code": "BATCH_LIMIT_EXCEEDED",
            "trace_id": "70000000-0000-4000-8000-000000000001",
        },
    )

    with pytest.raises(subject.PerformanceError, match="BATCH_LIMIT_CONTRACT_INVALID"):
        subject._validate_batch_limit_response(response)


def _accepted_batch_item(index: int, *, replayed: bool) -> dict[str, object]:
    file_id = f"70000000-0000-4000-8000-{index + 1:012d}"
    job_id = f"71000000-0000-4000-8000-{index + 1:012d}"
    return {
        "index": index,
        "original_name": f"batch-{index + 1:02d}.pdf",
        "outcome": "accepted",
        "http_status": 202,
        "replayed": replayed,
        "data": {"file_id": file_id, "job_id": job_id},
        "error": None,
    }


def test_validate_batch_response_accepts_ordered_new_items() -> None:
    data = {
        "items": [
            _accepted_batch_item(0, replayed=False),
            _accepted_batch_item(1, replayed=False),
        ],
        "accepted_count": 2,
        "rejected_count": 0,
    }

    identities = subject._validate_batch_response(
        data,
        expected_count=2,
        expected_replayed=False,
    )

    assert identities == (
        (
            subject.UUID("70000000-0000-4000-8000-000000000001"),
            subject.UUID("71000000-0000-4000-8000-000000000001"),
        ),
        (
            subject.UUID("70000000-0000-4000-8000-000000000002"),
            subject.UUID("71000000-0000-4000-8000-000000000002"),
        ),
    )


def test_validate_batch_response_accepts_expected_partial_failure() -> None:
    data = {
        "items": [
            _accepted_batch_item(0, replayed=False),
            {
                "index": 1,
                "original_name": "invalid.txt",
                "outcome": "rejected",
                "http_status": 400,
                "replayed": False,
                "data": None,
                "error": {
                    "code": "FILE_FORMAT_NOT_SUPPORTED",
                    "message": "文件格式不支持",
                },
            },
        ],
        "accepted_count": 1,
        "rejected_count": 1,
    }

    identities = subject._validate_batch_response(
        data,
        expected_count=2,
        expected_replayed=False,
        expected_rejections={1: (400, "FILE_FORMAT_NOT_SUPPORTED")},
    )

    assert len(identities) == 1


def test_validate_batch_response_rejects_duplicate_file_identity() -> None:
    first = _accepted_batch_item(0, replayed=True)
    second = _accepted_batch_item(1, replayed=True)
    second_data = second["data"]
    assert isinstance(second_data, dict)
    first_data = first["data"]
    assert isinstance(first_data, dict)
    second_data["file_id"] = first_data["file_id"]

    with pytest.raises(subject.PerformanceError, match="BATCH_IDENTITY_DUPLICATED"):
        subject._validate_batch_response(
            {
                "items": [first, second],
                "accepted_count": 2,
                "rejected_count": 0,
            },
            expected_count=2,
            expected_replayed=True,
        )
