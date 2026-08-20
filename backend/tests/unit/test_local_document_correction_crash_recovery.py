from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import smoke_local_document_correction_crash_recovery as subject  # noqa: E402


def _file_ready_state(run_id: str) -> dict[str, object]:
    return {
        "schema_version": "finaudit-local-document-correction-crash-v1",
        "phase": "file_ready",
        "run_id": run_id,
        "file_id": "10000000-0000-4000-8000-000000000001",
        "file_job_id": "10000000-0000-4000-8000-000000000002",
        "file_sha256": "a" * 64,
        "source_parse_version_id": "10000000-0000-4000-8000-000000000003",
        "source_block_id": "10000000-0000-4000-8000-000000000004",
        "source_text_sha256": "b" * 64,
        "source_block_count": 3,
    }


def test_source_pdf_is_valid_clean_and_run_scoped() -> None:
    run_id = "c" * 32
    payload = subject._source_pdf(run_id)
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(payload)).pages
    )

    assert payload.startswith(b"%PDF")
    assert payload.rstrip().endswith(b"%%EOF")
    assert subject._SOURCE_TEXT_PREFIX in extracted
    assert run_id[:12] in extracted
    assert subject._CORRECTED_TEXT_PREFIX not in extracted


def test_reviewer_credentials_are_deterministic_and_run_scoped() -> None:
    first = subject._reviewer_credentials("Synthetic-Admin!", "d" * 32)
    replay = subject._reviewer_credentials("Synthetic-Admin!", "d" * 32)
    second = subject._reviewer_credentials("Synthetic-Admin!", "e" * 32)

    assert first == replay
    assert first != second
    assert first[0] == f"correction-crash-{'d' * 12}"
    assert first[1].startswith("Dc9!")
    assert "Synthetic-Admin" not in first[1]


def test_state_round_trip_is_exact_and_phase_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "status.json"
    monkeypatch.setattr(subject, "_state_path", lambda: path)
    file_ready = _file_ready_state("f" * 32)

    subject._write_state(file_ready)

    assert subject._read_state("file_ready") == file_ready
    with pytest.raises(subject.DocumentCorrectionCrashError, match="STATE_FILE_INVALID"):
        subject._read_state("correction_requested")

    requested = {
        **file_ready,
        "phase": "correction_requested",
        "correction_id": "10000000-0000-4000-8000-000000000005",
        "result_parse_version_id": "10000000-0000-4000-8000-000000000006",
        "correction_job_id": "10000000-0000-4000-8000-000000000007",
        "correction_trace_id": "10000000-0000-4000-8000-000000000008",
    }
    subject._write_state(requested)
    assert subject._read_state("correction_requested") == requested


@pytest.mark.parametrize(
    ("mode", "function_name"),
    [
        ("prepare", "run_prepare_client"),
        ("request", "run_request_client"),
        ("wait-running", "run_wait_for_correction"),
        ("before-recovery", "run_before_recovery_verification"),
        ("verify-client", "run_verify_client"),
        ("database", "run_final_database_verification"),
    ],
)
def test_main_dispatches_exact_modes(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    function_name: str,
) -> None:
    called = False

    def run() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(subject, function_name, run)
    monkeypatch.setattr(sys, "argv", [subject.__file__, mode])

    assert subject.main() == 0
    assert called is True


def test_main_rejects_unknown_mode_without_runtime_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", [subject.__file__, "unknown"])

    assert subject.main() == 1


def test_wrapper_and_image_include_isolated_fail_safe_gate() -> None:
    wrapper = (_PROJECT_ROOT / "scripts/verify-local-stack.ps1").read_text(encoding="utf-8")
    dockerfile = (_PROJECT_ROOT / "backend/Dockerfile").read_text(encoding="utf-8")

    assert "[switch]$DocumentCorrectionCrashRecovery" in wrapper
    assert "$extractionTable = 'document_content_exclusions'" in wrapper
    assert "$expectedMaintenanceOutcome = 'exhausted'" in wrapper
    assert "LOCAL_DOCUMENT_CORRECTION_TERMINAL_FAILURE_GATE=PASS" in wrapper
    assert "LOCAL_DOCUMENT_CORRECTION_OLD_ACTIVE_PRESERVED_GATE=PASS" in wrapper
    assert "smoke_local_document_correction_crash_recovery.py" in dockerfile


def test_runtime_evidence_is_fail_safe_cleaned_and_source_bound() -> None:
    evidence = json.loads(
        (
            _PROJECT_ROOT / "tests/evaluation/local-document-correction-crash-recovery-v1.json"
        ).read_text(encoding="utf-8")
    )

    assert evidence["schema_version"] == "local-document-correction-crash-recovery-v1"
    assert evidence["fault_injection"] == {
        "database_lock": "document_content_exclusions_access_exclusive",
        "expected_maintenance_outcome": "exhausted",
        "lease_grace_seconds": 15,
        "lease_seconds": 60,
        "max_attempts": 1,
        "worker_exit_code": 137,
        "worker_signal": "SIGKILL",
    }
    assert evidence["post_failure_invariants"] == {
        "activation_error_code": "PARSE_STATE_CONFLICT",
        "candidate_block_count": 0,
        "candidate_error_code": "WORKER_LOST",
        "candidate_markdown_count": 0,
        "candidate_page_count": 0,
        "candidate_status": "failed",
        "correction_attempt_count": 1,
        "correction_step_error_code": "WORKER_LOST",
        "job_error_code": "WORKER_LOST",
        "job_status": "failed",
        "old_active_status": "active",
        "source_preview_sha256_unchanged": True,
    }
    assert all(value == "passed" for value in evidence["gates"].values())
    assert evidence["cleanup"] == {
        "container_count": 0,
        "image_tag_count": 0,
        "network_count": 0,
        "process_env_count": 0,
        "runtime_directory_present": False,
        "runtime_secrets_present": False,
        "volume_count": 0,
    }
    for key in ("runner", "wrapper", "dockerfile"):
        path = _PROJECT_ROOT / evidence["source_binding"][f"{key}_path"]
        payload = path.read_bytes()
        assert len(payload) == evidence["source_binding"][f"{key}_bytes"]
        assert hashlib.sha256(payload).hexdigest() == evidence["source_binding"][f"{key}_sha256"]
