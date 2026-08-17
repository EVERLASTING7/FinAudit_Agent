from __future__ import annotations

from pathlib import Path
from typing import NoReturn, cast

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.events import AiCallCompletedV1, AiCallStartedV1, parse_ai_call_event_v1
from app.repositories.ai_call_audit import (
    AiCallAuditLimits,
    AiCallCompleteStatus,
    AiCallReserveStatus,
)
from app.services.ai_call_audit import AiCallAuditService

_ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[3] / "docs" / "change-requests" / "artifacts" / "CR-011"
)


class _CommitOutcomeUnknown:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> NoReturn:
        del exc_type, exc, traceback
        raise DBAPIError(
            None,
            None,
            RuntimeError("synthetic commit outcome unknown"),
            connection_invalidated=True,
        )


class _SessionFactory:
    def begin(self) -> _CommitOutcomeUnknown:
        return _CommitOutcomeUnknown()


class _SuccessfulRepository:
    def __init__(self, session: object) -> None:
        del session

    def reserve_attempt(
        self,
        event: AiCallStartedV1,
        limits: AiCallAuditLimits,
        *,
        deadline_monotonic: float,
        monotonic: object,
        minimum_attempt_seconds: float,
    ) -> AiCallReserveStatus:
        del event, limits, deadline_monotonic, monotonic, minimum_attempt_seconds
        return AiCallReserveStatus.RESERVED_NEW

    def append_completion(self, event: AiCallCompletedV1) -> AiCallCompleteStatus:
        del event
        return AiCallCompleteStatus.COMPLETED_NEW


def _event(name: str) -> AiCallStartedV1 | AiCallCompletedV1:
    event = parse_ai_call_event_v1((_ARTIFACT_ROOT / name).read_bytes())
    assert isinstance(event, (AiCallStartedV1, AiCallCompletedV1))
    return event


def test_commit_outcome_unknown_never_returns_a_false_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.ai_call_audit.AiCallAuditRepository",
        _SuccessfulRepository,
    )
    service = AiCallAuditService(
        cast(sessionmaker[Session], _SessionFactory()),
        monotonic_clock=lambda: 1.0,
    )
    started = _event("ai-call-event-v1.started.json")
    completed = _event("ai-call-event-v1.completed.json")
    assert isinstance(started, AiCallStartedV1)
    assert isinstance(completed, AiCallCompletedV1)
    limits = AiCallAuditLimits(
        max_provider_attempts_per_business_operation=6,
        max_input_tokens_per_request=32_768,
        max_output_tokens_per_request=2_500,
        max_total_tokens=212_000,
        max_cost_micro_usd=500_000,
    )

    assert (
        service.reserve_attempt(started, limits, deadline_monotonic=30.0)
        is AiCallReserveStatus.UNKNOWN
    )
    assert service.complete_attempt(completed) is AiCallCompleteStatus.UNKNOWN
