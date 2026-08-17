from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import smoke_local_report_generation_crash_recovery as subject  # noqa: E402


@pytest.mark.parametrize("run_id", ["", "not-a-run-id", "A" * 32, "a" * 31])
def test_report_crash_reviewer_credentials_reject_invalid_run_id(run_id: str) -> None:
    with pytest.raises(subject.ReportCrashRecoveryError, match="RUN_ID_INVALID"):
        subject._audit_reviewer_credentials("Admin-Secret-123!", run_id)


def test_report_crash_reviewer_credentials_are_bounded_and_secret_derived() -> None:
    username, password = subject._audit_reviewer_credentials("Admin-Secret-123!", "b" * 32)

    assert username == "report-crash-audit-bbbbbbbbbbbb"
    assert "Admin-Secret-123!" not in password
    assert 16 <= len(password) <= 128
    assert re.search(r"[A-Z]", password)
    assert re.search(r"[a-z]", password)
    assert re.search(r"[0-9]", password)
    assert re.search(r"[^A-Za-z0-9]", password)


def test_report_crash_lock_identity_is_bounded_for_postgresql() -> None:
    identity = subject._lock_application_name("c" * 32)

    assert identity == "finaudit-report-crash-cccccccccccccccccccccccccccccccc"
    assert len(identity.encode("ascii")) <= 63


def test_report_crash_client_artifact_expectations_are_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPORT_TEST_HASH", "d" * 64)
    monkeypatch.setenv("REPORT_TEST_SIZE", "123")

    assert subject._required_sha256("REPORT_TEST_HASH") == "d" * 64
    assert subject._required_positive_integer("REPORT_TEST_SIZE") == 123


@pytest.mark.parametrize("value", ["0", "-1", "01x"])
def test_report_crash_client_artifact_size_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("REPORT_TEST_SIZE", value)

    with pytest.raises(subject.ReportCrashRecoveryError, match="REPORT_TEST_SIZE_INVALID"):
        subject._required_positive_integer("REPORT_TEST_SIZE")


def test_backend_image_includes_report_crash_gate() -> None:
    dockerfile = (_PROJECT_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert "scripts/smoke_local_report_generation_crash_recovery.py" in dockerfile


def test_local_stack_verifier_exposes_report_crash_gate() -> None:
    verifier = (_PROJECT_ROOT / "scripts" / "verify-local-stack.ps1").read_text(encoding="utf-8")

    assert "[switch]$ReportGenerationCrashRecovery" in verifier
    assert "LOCK TABLE public.operation_logs IN ACCESS EXCLUSIVE MODE" in verifier
    assert "LOCAL_REPORT_GENERATE_OBJECTS_BEFORE_CRASH_GATE=PASS" in verifier
    assert "LOCAL_REPORT_GENERATE_CRASH_STACK_RESTORED=PASS" in verifier


def test_local_nginx_emits_one_content_type_options_header_for_api() -> None:
    nginx = (_PROJECT_ROOT / "frontend" / "docker" / "nginx.conf").read_text(encoding="utf-8")

    assert "proxy_hide_header X-Content-Type-Options;" in nginx


def test_report_database_gate_reads_summary_from_attempt_steps() -> None:
    helper = (
        _PROJECT_ROOT / "scripts" / "smoke_local_report_generation_crash_recovery.py"
    ).read_text(encoding="utf-8")

    assert "job.summary_json" not in helper
    assert "step.summary_json" in helper
