from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from time import monotonic
from uuid import UUID, uuid5

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.events import (
    AiCallCompletedV1,
    AiCallStartedV1,
    parse_ai_call_event_v1,
    validate_ai_call_event_chain,
)
from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.models.audit import AiCallLog
from app.models.auth import Organization
from app.models.reliability import OutboxEvent
from app.repositories.ai_call_audit import (
    AiCallAuditLimits,
    AiCallCompleteStatus,
    AiCallReserveStatus,
)
from app.services.ai_call_audit import AiCallAuditService

_RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_IDENTITY_NAMESPACE = UUID("578cb09e-6b6f-4c5b-b34e-6cd086e3f8bb")
_FINAL_TIMEOUT_SECONDS = 60
_POLL_INTERVAL_SECONDS = 0.25


class AiAuditCrashRecoveryError(RuntimeError):
    pass


def _run_id() -> str:
    value = os.environ.get("FINAUDIT_AI_AUDIT_CRASH_RUN_ID", "")
    if _RUN_ID_PATTERN.fullmatch(value) is None:
        raise AiAuditCrashRecoveryError("RUN_ID_INVALID")
    return value


def _identity(run_id: str, kind: str) -> UUID:
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise AiAuditCrashRecoveryError("RUN_ID_INVALID")
    if kind not in {"event", "operation", "trace"}:
        raise AiAuditCrashRecoveryError("IDENTITY_KIND_INVALID")
    return uuid5(_IDENTITY_NAMESPACE, f"{kind}:{run_id}")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _events(
    run_id: str,
    organization_id: UUID,
    started_at: datetime,
) -> tuple[AiCallStartedV1, AiCallCompletedV1]:
    event_id = _identity(run_id, "event")
    operation_id = _identity(run_id, "operation")
    trace_id = _identity(run_id, "trace")
    policy_hash = _sha256("synthetic-ai-audit-crash-policy-v1")
    common = {
        "event_id": str(event_id),
        "event_version": 1,
        "aggregate_type": "ai_call",
        "aggregate_id": str(event_id),
        "organization_id": str(organization_id),
        "business_operation_id": str(operation_id),
        "job_id": None,
        "request_id": None,
        "trace_id": str(trace_id),
        "policy_version": 1,
        "policy_hash": policy_hash,
    }
    started_payload: dict[str, object] = {
        **common,
        "event_sequence": 1,
        "event_type": "ai.call.started",
        "resource_type": None,
        "resource_id": None,
        "call_type": "embedding",
        "logical_generation_no": 1,
        "provider_attempt_no": 1,
        "adapter_id": "openai_embeddings_v1",
        "endpoint_id": "synthetic-ai-audit-crash",
        "model_id": "synthetic-ai-audit-crash-embedding",
        "model_version": None,
        "prompt_id": None,
        "prompt_version": None,
        "prompt_hash": None,
        "schema_version": None,
        "pricing_version": "synthetic-v1",
        "input_hash": _sha256(f"input:{run_id}"),
        "reserved_input_tokens": 16,
        "reserved_output_tokens": 0,
        "reserved_cost_micro_usd": 0,
        "attempt_count": 1,
        "is_fallback": False,
        "breaker_state": "closed",
        "status": "pending",
        "started_at": _timestamp(started_at),
    }
    completed_payload: dict[str, object] = {
        **common,
        "event_sequence": 2,
        "event_type": "ai.call.completed",
        "status": "succeeded",
        "completed_at": _timestamp(started_at + timedelta(milliseconds=1)),
        "duration_ms": 1,
        "output_hash": _sha256(f"output:{run_id}"),
        "input_tokens": 16,
        "output_tokens": 0,
        "vector_count": 1,
        "http_status": 200,
        "error_category": None,
        "safe_error_code": None,
        "citation_validation_status": None,
    }
    started = parse_ai_call_event_v1(
        json.dumps(started_payload, separators=(",", ":"), sort_keys=True)
    )
    completed = parse_ai_call_event_v1(
        json.dumps(completed_payload, separators=(",", ":"), sort_keys=True)
    )
    if not isinstance(started, AiCallStartedV1) or not isinstance(completed, AiCallCompletedV1):
        raise AiAuditCrashRecoveryError("EVENT_TYPE_INVALID")
    validate_ai_call_event_chain(started, completed)
    return started, completed


def _active_organization_id(factory: sessionmaker[Session]) -> UUID:
    with factory() as session:
        organization_ids = session.scalars(
            select(Organization.id)
            .where(Organization.status == "active")
            .order_by(Organization.id.asc())
            .limit(2)
        ).all()
    if len(organization_ids) != 1:
        raise AiAuditCrashRecoveryError("ACTIVE_ORGANIZATION_INVALID")
    return organization_ids[0]


def _owned_outbox(session: Session, event_id: UUID) -> list[OutboxEvent]:
    return list(
        session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.aggregate_type == "ai_call",
                OutboxEvent.event_id == event_id,
            )
            .order_by(OutboxEvent.event_sequence.asc())
        ).all()
    )


def seed_database() -> None:
    run_id = _run_id()
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        organization_id = _active_organization_id(factory)
        started, completed = _events(run_id, organization_id, datetime.now(timezone.utc))
        service = AiCallAuditService(factory)
        reserve_status = service.reserve_attempt(
            started,
            AiCallAuditLimits(
                max_provider_attempts_per_business_operation=1,
                max_input_tokens_per_request=16,
                max_output_tokens_per_request=0,
                max_total_tokens=16,
                max_cost_micro_usd=0,
            ),
            deadline_monotonic=monotonic() + 30,
        )
        if reserve_status is not AiCallReserveStatus.RESERVED_NEW:
            raise AiAuditCrashRecoveryError("RESERVE_STATUS_INVALID")
        if service.complete_attempt(completed) is not AiCallCompleteStatus.COMPLETED_NEW:
            raise AiAuditCrashRecoveryError("COMPLETE_STATUS_INVALID")
        event_id = UUID(started.event_id)
        with factory() as session:
            outbox = _owned_outbox(session, event_id)
            log = session.get(AiCallLog, event_id)
        if [(row.event_sequence, row.status, row.attempt_count) for row in outbox] != [
            (1, "pending", 0),
            (2, "pending", 0),
        ] or log is not None:
            raise AiAuditCrashRecoveryError("SEEDED_FACTS_INVALID")
    finally:
        engine.dispose()
    print(f"LOCAL_AI_AUDIT_EVENT_ID={started.event_id}")
    print(f"LOCAL_AI_AUDIT_OPERATION_ID={started.business_operation_id}")
    print("LOCAL_AI_AUDIT_SEED_GATE=PASS")


def verify_before_recovery() -> None:
    event_id = _identity(_run_id(), "event")
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            outbox = _owned_outbox(session, event_id)
            log = session.get(AiCallLog, event_id)
        observed = [
            (
                row.event_sequence,
                row.status,
                row.attempt_count,
                row.next_attempt_at,
                row.published_at,
                row.last_error,
            )
            for row in outbox
        ]
        if (
            observed
            != [
                (1, "pending", 0, None, None, None),
                (2, "pending", 0, None, None, None),
            ]
            or log is not None
        ):
            raise AiAuditCrashRecoveryError("PRE_RECOVERY_TRANSACTION_NOT_ROLLED_BACK")
    finally:
        engine.dispose()
    print("LOCAL_AI_AUDIT_ZERO_FACTS_BEFORE_RECOVERY_GATE=PASS")


def verify_final() -> None:
    run_id = _run_id()
    event_id = _identity(run_id, "event")
    operation_id = _identity(run_id, "operation")
    engine = create_application_engine(Settings())
    try:
        factory = create_session_factory(engine)
        deadline = monotonic() + _FINAL_TIMEOUT_SECONDS
        final_state: tuple[list[OutboxEvent], AiCallLog] | None = None
        while monotonic() < deadline:
            with factory() as session:
                outbox = _owned_outbox(session, event_id)
                log = session.get(AiCallLog, event_id)
                if (
                    len(outbox) == 2
                    and all(row.status == "published" for row in outbox)
                    and log is not None
                    and log.status == "succeeded"
                ):
                    final_state = outbox, log
                    break
            time.sleep(_POLL_INTERVAL_SECONDS)
        if final_state is None:
            raise AiAuditCrashRecoveryError("FINAL_PROJECTION_TIMEOUT")
        outbox, log = final_state
        summary = AiCallAuditService(factory).get_operation_summary(
            log.organization_id, operation_id
        )
        if (
            [(row.event_sequence, row.status, row.attempt_count) for row in outbox]
            != [(1, "published", 1), (2, "published", 1)]
            or any(row.published_at is None or row.last_error is not None for row in outbox)
            or log.id != event_id
            or log.event_sequence != 2
            or log.business_operation_id != operation_id
            or log.call_type != "embedding"
            or log.adapter_id != "openai_embeddings_v1"
            or log.input_tokens != 16
            or log.output_tokens != 0
            or log.vector_count != 1
            or log.http_status != 200
            or log.safe_error_code is not None
            or summary is None
            or summary.attempt_count != 1
            or tuple(attempt.status for attempt in summary.attempts) != ("succeeded",)
        ):
            raise AiAuditCrashRecoveryError("FINAL_FACTS_INVALID")
    finally:
        engine.dispose()
    print("LOCAL_AI_AUDIT_OUTBOX_SEQUENCE_GATE=PASS")
    print("LOCAL_AI_AUDIT_UNIQUE_FACTS_DATABASE_GATE=PASS")
    print("LOCAL_AI_AUDIT_CRASH_DATABASE_GATE=PASS")


def cleanup_owned_facts() -> None:
    event_id = _identity(_run_id(), "event")
    engine = create_application_engine(Settings())
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE ai_call_logs DISABLE TRIGGER USER")
            connection.exec_driver_sql("ALTER TABLE outbox_events DISABLE TRIGGER USER")
            try:
                connection.execute(delete(AiCallLog).where(AiCallLog.id == event_id))
                connection.execute(
                    delete(OutboxEvent).where(
                        OutboxEvent.aggregate_type == "ai_call",
                        OutboxEvent.event_id == event_id,
                    )
                )
            finally:
                connection.exec_driver_sql("ALTER TABLE outbox_events ENABLE TRIGGER USER")
                connection.exec_driver_sql("ALTER TABLE ai_call_logs ENABLE TRIGGER USER")
        factory = create_session_factory(engine)
        with factory() as session:
            if _owned_outbox(session, event_id) or session.get(AiCallLog, event_id) is not None:
                raise AiAuditCrashRecoveryError("OWNED_FACTS_CLEANUP_FAILED")
    finally:
        engine.dispose()
    print("LOCAL_AI_AUDIT_ZERO_RESIDUE_GATE=PASS")


def main() -> int:
    try:
        if sys.argv == [sys.argv[0], "seed"]:
            seed_database()
        elif sys.argv == [sys.argv[0], "before-recovery"]:
            verify_before_recovery()
        elif sys.argv == [sys.argv[0], "database"]:
            verify_final()
        elif sys.argv == [sys.argv[0], "cleanup"]:
            cleanup_owned_facts()
        else:
            raise AiAuditCrashRecoveryError("ARGUMENTS_INVALID")
    except AiAuditCrashRecoveryError as error:
        print("LOCAL_AI_AUDIT_CRASH_RECOVERY=FAIL")
        print(f"LOCAL_AI_AUDIT_CRASH_REASON={error}")
        return 1
    except Exception:
        print("LOCAL_AI_AUDIT_CRASH_RECOVERY=FAIL")
        print("LOCAL_AI_AUDIT_CRASH_REASON=UNEXPECTED_FAILURE")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
