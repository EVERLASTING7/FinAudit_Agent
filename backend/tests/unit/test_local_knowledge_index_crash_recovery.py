from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import smoke_local_knowledge_index_crash_recovery as subject  # noqa: E402


@pytest.mark.parametrize("run_id", ["", "not-a-run-id", "A" * 32, "a" * 31])
def test_knowledge_crash_credentials_reject_invalid_run_id(run_id: str) -> None:
    with pytest.raises(subject.KnowledgeCrashRecoveryError, match="RUN_ID_INVALID"):
        subject._reviewer_credentials("Admin-Secret-123!", run_id, "submitter")


def test_knowledge_crash_credentials_are_bounded_and_secret_derived() -> None:
    username, password = subject._reviewer_credentials("Admin-Secret-123!", "b" * 32, "submitter")

    assert username == "knowledge-crash-submit-bbbbbbbbbbbb"
    assert "Admin-Secret-123!" not in password
    assert 16 <= len(password) <= 128
    assert re.search(r"[A-Z]", password)
    assert re.search(r"[a-z]", password)
    assert re.search(r"[0-9]", password)
    assert re.search(r"[^A-Za-z0-9]", password)


def test_knowledge_crash_credentials_reject_unknown_kind() -> None:
    with pytest.raises(subject.KnowledgeCrashRecoveryError, match="REVIEWER_KIND_INVALID"):
        subject._reviewer_credentials("Admin-Secret-123!", "c" * 32, "unknown")


def test_knowledge_crash_lock_identity_is_bounded_for_postgresql() -> None:
    identity = subject._lock_application_name("d" * 32)

    assert identity == "finaudit-knowledge-crash-dddddddddddddddddddddddddddddddd"
    assert len(identity.encode("ascii")) <= 63


def test_expected_consistency_is_exact() -> None:
    assert subject._expected_consistency(3) == {
        "checked_point_count": 3,
        "member_count_match": True,
        "payload_hash_match": True,
        "vector_hash_match": True,
    }


@pytest.mark.parametrize("member_count", [0, -1, True])
def test_expected_consistency_rejects_invalid_member_count(member_count: int) -> None:
    with pytest.raises(subject.KnowledgeCrashRecoveryError, match="MEMBER_COUNT_INVALID"):
        subject._expected_consistency(member_count)


def test_backend_image_includes_knowledge_crash_gate() -> None:
    dockerfile = (_PROJECT_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert "scripts/smoke_local_knowledge_index_crash_recovery.py" in dockerfile


def test_local_stack_verifier_exposes_knowledge_crash_gate() -> None:
    verifier = (_PROJECT_ROOT / "scripts" / "verify-local-stack.ps1").read_text(encoding="utf-8")

    assert "[switch]$KnowledgeIndexCrashRecovery" in verifier
    assert "LOCAL_KNOWLEDGE_INDEX_KNOWLEDGE_BASE_ID=($canonicalUuid)" in verifier
    assert "LOCK TABLE public.operation_logs IN ACCESS EXCLUSIVE MODE" in verifier
    assert "LOCAL_KNOWLEDGE_INDEX_MATERIALIZED_BEFORE_CRASH_GATE=PASS" in verifier
    assert "LOCAL_KNOWLEDGE_INDEX_CRASH_STACK_RESTORED=PASS" in verifier


def test_knowledge_database_gate_reads_summary_from_attempt_steps() -> None:
    helper = (
        _PROJECT_ROOT / "scripts" / "smoke_local_knowledge_index_crash_recovery.py"
    ).read_text(encoding="utf-8")

    assert "job.summary_json" not in helper
    assert "step.summary_json" in helper
    assert "verify_ready_log=False" in helper
