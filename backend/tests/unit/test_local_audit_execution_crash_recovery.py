from __future__ import annotations

import re
import sys
from pathlib import Path
from uuid import UUID

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import smoke_local_audit_execution_crash_recovery as subject  # noqa: E402


def test_audit_crash_seed_identities_are_stable_and_distinct() -> None:
    contract_id, invoice_id, item_id = subject._seed_identities("a" * 32)

    assert (contract_id, invoice_id, item_id) == subject._seed_identities("a" * 32)
    assert len({contract_id, invoice_id, item_id}) == 3
    assert all(identity.version == 5 for identity in (contract_id, invoice_id, item_id))


@pytest.mark.parametrize("run_id", ["", "not-a-run-id", "A" * 32, "a" * 31])
def test_audit_crash_seed_identities_reject_invalid_run_id(run_id: str) -> None:
    with pytest.raises(subject.AuditCrashRecoveryError, match="RUN_ID_INVALID"):
        subject._seed_identities(run_id)


def test_audit_crash_task_payload_is_exact_and_run_scoped() -> None:
    contract_id = UUID("11111111-1111-4111-8111-111111111111")
    invoice_id = UUID("22222222-2222-4222-8222-222222222222")

    assert subject._task_payload("b" * 32, contract_id, invoice_id) == {
        "task_no": "CRASH-AUDIT-BBBBBBBBBBBB",
        "name": "Worker 强杀恢复审核 BBBBBBBB",
        "description": "本地 audit_execute 事务回滚与租约恢复门禁",
        "baseline_date": "2027-01-15",
        "contract_id": str(contract_id),
        "invoice_ids": [str(invoice_id)],
    }


def test_audit_crash_reviewer_credentials_are_bounded_and_secret_derived() -> None:
    username, password = subject._reviewer_credentials("Admin-Secret-123!", "c" * 32)

    assert username == "audit-crash-cccccccccccc"
    assert "Admin-Secret-123!" not in password
    assert 16 <= len(password) <= 128
    assert re.search(r"[A-Z]", password)
    assert re.search(r"[a-z]", password)
    assert re.search(r"[0-9]", password)
    assert re.search(r"[^A-Za-z0-9]", password)


def test_audit_crash_lock_identity_is_bounded_for_postgresql() -> None:
    identity = subject._lock_application_name("d" * 32)

    assert identity == "finaudit-audit-crash-dddddddddddddddddddddddddddddddd"
    assert len(identity.encode("ascii")) <= 63


def test_backend_image_includes_audit_crash_gate() -> None:
    dockerfile = (_PROJECT_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert "scripts/smoke_local_audit_execution_crash_recovery.py" in dockerfile


def test_local_stack_verifier_exposes_audit_crash_gate() -> None:
    verifier = (_PROJECT_ROOT / "scripts" / "verify-local-stack.ps1").read_text(encoding="utf-8")

    assert "[switch]$AuditExecutionCrashRecovery" in verifier
    assert "LOCK TABLE public.rule_executions IN ACCESS EXCLUSIVE MODE" in verifier
    assert "LOCAL_AUDIT_EXECUTE_ZERO_FACTS_BEFORE_RECOVERY_GATE=PASS" in verifier
    assert "LOCAL_AUDIT_EXECUTE_CRASH_STACK_RESTORED=PASS" in verifier
