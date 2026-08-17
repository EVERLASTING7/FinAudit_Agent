from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import smoke_local_invoice_extraction_crash_recovery as subject  # noqa: E402


def test_invoice_crash_state_payload_is_exact_and_run_scoped() -> None:
    file_id = UUID("11111111-1111-4111-8111-111111111111")
    file_job_id = UUID("22222222-2222-4222-8222-222222222222")

    payload = json.loads(
        subject._state_payload(
            run_id="a" * 32,
            file_id=file_id,
            file_job_id=file_job_id,
            file_sha256="c" * 64,
        )
    )

    assert payload == {
        "file_id": str(file_id),
        "file_job_id": str(file_job_id),
        "file_sha256": "c" * 64,
        "phase": "file_ready",
        "run_id": "a" * 32,
        "schema_version": "finaudit-local-invoice-extract-crash-v1",
    }


@pytest.mark.parametrize("run_id", ["", "not-a-run-id", "A" * 32, "a" * 31])
def test_invoice_crash_state_payload_rejects_invalid_run_id(run_id: str) -> None:
    with pytest.raises(subject.InvoiceCrashRecoveryError, match="RUN_ID_INVALID"):
        subject._state_payload(
            run_id=run_id,
            file_id=UUID("11111111-1111-4111-8111-111111111111"),
            file_job_id=UUID("22222222-2222-4222-8222-222222222222"),
            file_sha256="c" * 64,
        )


@pytest.mark.parametrize("file_sha256", ["", "C" * 64, "g" * 64, "c" * 63])
def test_invoice_crash_state_payload_rejects_invalid_sha256(file_sha256: str) -> None:
    with pytest.raises(subject.InvoiceCrashRecoveryError, match="FILE_SHA256_INVALID"):
        subject._state_payload(
            run_id="a" * 32,
            file_id=UUID("11111111-1111-4111-8111-111111111111"),
            file_job_id=UUID("22222222-2222-4222-8222-222222222222"),
            file_sha256=file_sha256,
        )


def test_invoice_crash_identity_is_bounded_for_postgresql() -> None:
    identity = subject._lock_application_name("b" * 32)

    assert identity == "finaudit-invoice-crash-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert len(identity.encode("ascii")) <= 63


def test_backend_image_includes_invoice_crash_gate() -> None:
    dockerfile = (_PROJECT_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert "scripts/smoke_local_invoice_extraction_crash_recovery.py" in dockerfile


def test_local_stack_verifier_exposes_invoice_crash_gate() -> None:
    verifier = (_PROJECT_ROOT / "scripts" / "verify-local-stack.ps1").read_text(encoding="utf-8")

    assert "[switch]$InvoiceExtractionCrashRecovery" in verifier
    assert "LOCAL_INVOICE_EXTRACT_ZERO_FACTS_BEFORE_RECOVERY_GATE=PASS" in verifier
    assert "LOCAL_INVOICE_EXTRACT_CRASH_STACK_RESTORED=PASS" in verifier
