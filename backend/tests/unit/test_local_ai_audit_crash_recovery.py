from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import smoke_local_ai_audit_crash_recovery as subject  # noqa: E402


@pytest.mark.parametrize("run_id", ["", "not-a-run-id", "A" * 32, "a" * 31])
def test_ai_audit_crash_identity_rejects_invalid_run_id(run_id: str) -> None:
    with pytest.raises(subject.AiAuditCrashRecoveryError, match="RUN_ID_INVALID"):
        subject._identity(run_id, "event")


def test_ai_audit_crash_identities_are_stable_and_distinct() -> None:
    run_id = "b" * 32
    identities = tuple(subject._identity(run_id, kind) for kind in ("event", "operation", "trace"))

    assert len(set(identities)) == 3
    assert all(isinstance(value, UUID) and value.version == 5 for value in identities)
    assert subject._identity(run_id, "event") == identities[0]


def test_ai_audit_crash_identity_rejects_unknown_kind() -> None:
    with pytest.raises(subject.AiAuditCrashRecoveryError, match="IDENTITY_KIND_INVALID"):
        subject._identity("c" * 32, "unknown")


def test_ai_audit_crash_events_form_one_valid_embedding_chain() -> None:
    organization_id = UUID("22222222-2222-4222-8222-222222222222")
    started, completed = subject._events(
        "d" * 32,
        organization_id,
        datetime(2026, 8, 16, tzinfo=timezone.utc),
    )

    assert started.event_id == completed.event_id
    assert started.organization_id == completed.organization_id == str(organization_id)
    assert started.call_type == "embedding"
    assert started.reserved_input_tokens == completed.input_tokens == 16
    assert completed.output_tokens == 0
    assert completed.vector_count == 1


def test_backend_image_includes_ai_audit_crash_gate() -> None:
    dockerfile = (_PROJECT_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert "scripts/smoke_local_ai_audit_crash_recovery.py" in dockerfile


def test_local_stack_verifier_exposes_ai_audit_crash_gate() -> None:
    verifier = (_PROJECT_ROOT / "scripts" / "verify-local-stack.ps1").read_text(encoding="utf-8")

    assert "[switch]$AiAuditCrashRecovery" in verifier
    assert "LOCK TABLE public.ai_call_logs IN ACCESS EXCLUSIVE MODE" in verifier
    assert "LOCAL_AI_AUDIT_ZERO_FACTS_BEFORE_RECOVERY_GATE=PASS" in verifier
    assert "LOCAL_AI_AUDIT_MAINTENANCE_SIGKILL_GATE=PASS" in verifier
    assert "LOCAL_AI_AUDIT_CRASH_STACK_RESTORED=PASS" in verifier
    assert "AI_AUDIT_PROJECTION outcome=projected" in verifier
    assert verifier.index("@('seed')") < verifier.index(
        "LOCK TABLE public.ai_call_logs IN ACCESS EXCLUSIVE MODE"
    )
    kill_index = verifier.index("'--signal', 'KILL'")
    release_index = verifier.index(
        "$terminated = Read-PostgresScalar $postgresqlId $terminateLockQuery"
    )
    verify_rollback_index = verifier.index("@('before-recovery')")
    assert kill_index < release_index < verify_rollback_index
    assert "$projectorDatabasePid = Read-PostgresScalar" in verifier


def test_ai_audit_crash_cleanup_is_identity_scoped() -> None:
    helper = (_PROJECT_ROOT / "scripts" / "smoke_local_ai_audit_crash_recovery.py").read_text(
        encoding="utf-8"
    )

    assert "delete(AiCallLog).where(AiCallLog.id == event_id)" in helper
    assert "OutboxEvent.event_id == event_id" in helper
    assert "delete(Organization)" not in helper
