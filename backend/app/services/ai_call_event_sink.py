"""AI-005 持久审计服务到 AI 调用 EventSink Port 的安全适配层。

持久记录由注入的 audit writer 负责；发送与采用许可始终只存在于当前进程。
本模块不启用 Provider，也不让独立 completion 事务自动等价于业务事实原子采用。
需要写入 AI 派生业务事实的调用方仍必须注入共享事务边界。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from app.ai.event_sink import (
    _PERMIT_FACTORY,
    _SCOPE_FACTORY,
    AdoptPermit,
    CallScopeToken,
    CompleteAttemptDecision,
    CompleteAttemptStatus,
    PermitUseError,
    ReserveAttemptDecision,
    ReserveAttemptStatus,
    SendPermit,
    SinkEvent,
)
from app.ai.events import (
    AiCallCompletedV1,
    AiCallCompletedV2,
    AiCallLateCompletionV1,
    AiCallLateCompletionV2,
    AiCallStartedV1,
    AiCallStartedV2,
    parse_ai_call_event,
)
from app.repositories.ai_call_audit import (
    AiCallAuditLimit,
    AiCallAuditLimits,
    AiCallAuditLimitsV2,
    AiCallCompleteStatus,
    AiCallReserveStatus,
)


class AiCallAuditWriter(Protocol):
    """可由独立 Service 或调用方共享事务实现的最小持久写入边界。"""

    def reserve_attempt(
        self,
        event: AiCallStartedV1 | AiCallStartedV2,
        limits: AiCallAuditLimit,
        *,
        deadline_monotonic: float,
        minimum_attempt_seconds: float = 0.0,
    ) -> AiCallReserveStatus: ...

    def complete_attempt(
        self,
        event: AiCallCompletedV1
        | AiCallCompletedV2
        | AiCallLateCompletionV1
        | AiCallLateCompletionV2,
    ) -> AiCallCompleteStatus: ...


class AiCallCompletionWriter(Protocol):
    """由业务 Unit of Work 提供的 completion-only 共享事务写入边界。"""

    def complete_attempt(
        self,
        event: AiCallCompletedV1
        | AiCallCompletedV2
        | AiCallLateCompletionV1
        | AiCallLateCompletionV2,
    ) -> AiCallCompleteStatus: ...


@dataclass(frozen=True, slots=True)
class AiCallReserveContext:
    """由调用方冻结的绝对 deadline 与同源持久预算。"""

    limits: AiCallAuditLimit
    deadline_monotonic: float
    minimum_attempt_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.limits, (AiCallAuditLimits, AiCallAuditLimitsV2)):
            raise TypeError("limits must be an AI call audit limits value")
        for name, value in (
            ("deadline_monotonic", self.deadline_monotonic),
            ("minimum_attempt_seconds", self.minimum_attempt_seconds),
        ):
            if type(value) not in {int, float} or not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.minimum_attempt_seconds < 0:
            raise ValueError("minimum_attempt_seconds must be non-negative")


ReserveContextFactory = Callable[[AiCallStartedV1 | AiCallStartedV2], AiCallReserveContext]

_RESERVE_STATUS = {
    AiCallReserveStatus.RESERVED_NEW: ReserveAttemptStatus.RESERVED_NEW,
    AiCallReserveStatus.REPLAYED_SAME: ReserveAttemptStatus.REPLAYED_SAME,
    AiCallReserveStatus.CONFLICT: ReserveAttemptStatus.CONFLICT,
    AiCallReserveStatus.UNKNOWN: ReserveAttemptStatus.UNKNOWN,
    AiCallReserveStatus.BUDGET_EXHAUSTED: ReserveAttemptStatus.BUDGET_EXHAUSTED,
    AiCallReserveStatus.DEADLINE_EXHAUSTED: ReserveAttemptStatus.DEADLINE_EXHAUSTED,
}
_COMPLETE_STATUS = {
    AiCallCompleteStatus.COMPLETED_NEW: CompleteAttemptStatus.COMPLETED_NEW,
    AiCallCompleteStatus.REPLAYED_SAME: CompleteAttemptStatus.REPLAYED_SAME,
    AiCallCompleteStatus.LATE_RECORDED: CompleteAttemptStatus.LATE_RECORDED,
    AiCallCompleteStatus.CONFLICT: CompleteAttemptStatus.CONFLICT,
    AiCallCompleteStatus.UNKNOWN: CompleteAttemptStatus.UNKNOWN,
    AiCallCompleteStatus.AUDIT_UNAVAILABLE: CompleteAttemptStatus.AUDIT_UNAVAILABLE,
}


class DurableAiCallEventSink:
    """持久 Event 写入 + 当前进程许可恢复；重建实例即失去全部许可证据。"""

    def __init__(
        self,
        audit_writer: AiCallAuditWriter,
        *,
        reserve_context_factory: ReserveContextFactory,
    ) -> None:
        if not callable(reserve_context_factory):
            raise TypeError("reserve_context_factory must be callable")
        self._audit_writer = audit_writer
        self._reserve_context_factory = reserve_context_factory
        self._scope_owner = object()
        self._generation = 0
        self._reserve_contexts: dict[CallScopeToken, AiCallReserveContext] = {}
        self._sent_scope: dict[str, CallScopeToken] = {}
        self._adopted_scope: dict[str, CallScopeToken] = {}
        self._reserve_commit_unknown: set[CallScopeToken] = set()
        self._complete_commit_unknown: set[tuple[CallScopeToken, tuple[str, str]]] = set()

    def create_call_scope(self, event: SinkEvent) -> CallScopeToken:
        if not isinstance(event, SinkEvent):
            raise TypeError("CALL_SCOPE_REQUIRES_SINK_EVENT")
        dto = parse_ai_call_event(event.payload_jcs)
        scope = CallScopeToken(
            event.event_id,
            self._generation,
            self._scope_owner,
            _SCOPE_FACTORY,
        )
        if isinstance(dto, (AiCallStartedV1, AiCallStartedV2)):
            context = self._reserve_context_factory(dto)
            if not isinstance(context, AiCallReserveContext):
                raise TypeError("reserve_context_factory must return AiCallReserveContext")
            self._reserve_contexts[scope] = context
        return scope

    async def reserve_attempt(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> ReserveAttemptDecision:
        return self.reserve_attempt_sync(event, scope)

    def reserve_attempt_sync(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> ReserveAttemptDecision:
        """同步 Worker 边界；与 async Port 共享完全相同的状态机。"""

        self._validate_scope(event, scope)
        dto = parse_ai_call_event(event.payload_jcs)
        if not isinstance(dto, (AiCallStartedV1, AiCallStartedV2)):
            raise ValueError("reserve_attempt requires ai.call.started")
        context = self._reserve_contexts.get(scope)
        if context is None:
            raise PermitUseError("CALL_SCOPE_RESERVE_CONTEXT_MISSING")

        persisted = self._audit_writer.reserve_attempt(
            dto,
            context.limits,
            deadline_monotonic=context.deadline_monotonic,
            minimum_attempt_seconds=context.minimum_attempt_seconds,
        )
        status = _RESERVE_STATUS.get(persisted)
        if status is None:
            raise RuntimeError("AI_AUDIT_RESERVE_STATUS_INVALID")

        if status is ReserveAttemptStatus.UNKNOWN:
            if event.event_id not in self._sent_scope:
                self._reserve_commit_unknown.add(scope)
            return ReserveAttemptDecision(status)

        if status is ReserveAttemptStatus.RESERVED_NEW:
            self._reserve_commit_unknown.discard(scope)
            return ReserveAttemptDecision(status, self._issue_send_permit(scope))

        if status is ReserveAttemptStatus.REPLAYED_SAME:
            return ReserveAttemptDecision(status, self._recover_send_permit(scope))

        self._reserve_commit_unknown.discard(scope)
        return ReserveAttemptDecision(status)

    async def complete_attempt(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> CompleteAttemptDecision:
        return self.complete_attempt_sync(event, scope)

    def complete_attempt_sync(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> CompleteAttemptDecision:
        self._validate_scope(event, scope)
        dto = parse_ai_call_event(event.payload_jcs)
        if not isinstance(
            dto,
            (AiCallCompletedV1, AiCallCompletedV2, AiCallLateCompletionV1, AiCallLateCompletionV2),
        ):
            raise ValueError("complete_attempt requires completed or late event")

        return self._complete_with_writer(event, scope, dto, self._audit_writer)

    async def complete_attempt_in_transaction(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
        writer: AiCallCompletionWriter,
    ) -> CompleteAttemptDecision:
        return self.complete_attempt_in_transaction_sync(event, scope, writer)

    def complete_attempt_in_transaction_sync(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
        writer: AiCallCompletionWriter,
    ) -> CompleteAttemptDecision:
        """把 sequence-2 与 AI 派生业务事实放入调用方同一事务。"""

        self._validate_scope(event, scope)
        dto = parse_ai_call_event(event.payload_jcs)
        if not isinstance(
            dto,
            (AiCallCompletedV1, AiCallCompletedV2, AiCallLateCompletionV1, AiCallLateCompletionV2),
        ):
            raise ValueError("complete_attempt requires completed or late event")
        if not callable(getattr(writer, "complete_attempt", None)):
            raise TypeError("writer must provide complete_attempt")
        return self._complete_with_writer(event, scope, dto, writer)

    def _complete_with_writer(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
        dto: AiCallCompletedV1
        | AiCallCompletedV2
        | AiCallLateCompletionV1
        | AiCallLateCompletionV2,
        writer: AiCallCompletionWriter,
    ) -> CompleteAttemptDecision:
        persisted = writer.complete_attempt(dto)
        status = _COMPLETE_STATUS.get(persisted)
        if status is None:
            raise RuntimeError("AI_AUDIT_COMPLETE_STATUS_INVALID")

        recovery_key = (scope, (event.event_id, event.event_type))
        if status is CompleteAttemptStatus.UNKNOWN:
            if self._completion_can_be_adopted(event, scope):
                self._complete_commit_unknown.add(recovery_key)
            return CompleteAttemptDecision(status)

        if status is CompleteAttemptStatus.COMPLETED_NEW:
            self._complete_commit_unknown.discard(recovery_key)
            return CompleteAttemptDecision(
                status,
                self._issue_adopt_permit(event, scope),
            )

        if status is CompleteAttemptStatus.REPLAYED_SAME:
            return CompleteAttemptDecision(
                status,
                self._recover_adopt_permit(event, scope),
            )

        self._complete_commit_unknown.discard(recovery_key)
        return CompleteAttemptDecision(status)

    def _validate_scope(self, event: SinkEvent, scope: CallScopeToken) -> None:
        if not isinstance(scope, CallScopeToken) or scope._owner is not self._scope_owner:
            raise PermitUseError("CALL_SCOPE_NOT_OWNED")
        if scope._generation != self._generation:
            raise PermitUseError("CALL_SCOPE_EXPIRED")
        if scope.event_id != event.event_id:
            raise PermitUseError("CALL_SCOPE_EVENT_MISMATCH")

    def _issue_send_permit(self, scope: CallScopeToken) -> SendPermit:
        if scope.event_id in self._sent_scope:
            raise RuntimeError("AI_AUDIT_SEND_STATE_CONFLICT")
        return SendPermit(
            scope.event_id,
            lambda: self._consume_send(scope),
            _PERMIT_FACTORY,
        )

    def _recover_send_permit(self, scope: CallScopeToken) -> SendPermit | None:
        if scope not in self._reserve_commit_unknown:
            return None
        self._reserve_commit_unknown.remove(scope)
        if scope.event_id in self._sent_scope:
            return None
        return self._issue_send_permit(scope)

    def _consume_send(self, scope: CallScopeToken) -> None:
        if scope._owner is not self._scope_owner or scope._generation != self._generation:
            raise PermitUseError("SEND_PERMIT_SCOPE_EXPIRED")
        if scope.event_id in self._sent_scope:
            raise PermitUseError("SEND_ALREADY_RECORDED")
        self._sent_scope[scope.event_id] = scope

    def _completion_can_be_adopted(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> bool:
        return (
            event.event_type == "ai.call.completed"
            and event.event_status != "outcome_unknown"
            and self._sent_scope.get(event.event_id) is scope
            and event.event_id not in self._adopted_scope
        )

    def _issue_adopt_permit(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> AdoptPermit | None:
        if not self._completion_can_be_adopted(event, scope):
            return None
        return AdoptPermit(
            event.event_id,
            lambda: self._consume_adopt(scope),
            _PERMIT_FACTORY,
        )

    def _recover_adopt_permit(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> AdoptPermit | None:
        recovery_key = (scope, (event.event_id, event.event_type))
        if recovery_key not in self._complete_commit_unknown:
            return None
        self._complete_commit_unknown.remove(recovery_key)
        return self._issue_adopt_permit(event, scope)

    def _consume_adopt(self, scope: CallScopeToken) -> None:
        if scope._owner is not self._scope_owner or scope._generation != self._generation:
            raise PermitUseError("ADOPT_PERMIT_SCOPE_EXPIRED")
        if self._sent_scope.get(scope.event_id) is not scope:
            raise PermitUseError("SEND_PERMIT_NOT_CONSUMED")
        if scope.event_id in self._adopted_scope:
            raise PermitUseError("AI_RESULT_ALREADY_ADOPTED")
        self._adopted_scope[scope.event_id] = scope


__all__ = [
    "AiCallCompletionWriter",
    "AiCallAuditWriter",
    "AiCallReserveContext",
    "DurableAiCallEventSink",
    "ReserveContextFactory",
]
