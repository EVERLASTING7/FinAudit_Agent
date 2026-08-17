"""CR-011-R4 Gate B 的纯内存 AI 调用事件 Sink 合同。

本模块只提供离线 Port 与 Fake。它不提供 durable、transactional、exactly-once、
Outbox-backed 或 restart-safe 语义，也不执行网络、数据库或业务结果采用。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Final, Literal, NoReturn, Protocol, SupportsIndex, runtime_checkable

from app.ai.events import (
    AiCallCompletedV1,
    AiCallEventConflictError,
    AiCallEventV1,
    AiCallLateCompletionV1,
    AiCallStartedV1,
    parse_ai_call_event_v1,
    validate_ai_call_event_chain,
)

EventType = Literal[
    "ai.call.started",
    "ai.call.completed",
    "ai.call.late_completion",
]

_STARTED_EVENT: Final = "ai.call.started"
_COMPLETED_EVENT: Final = "ai.call.completed"
_LATE_EVENT: Final = "ai.call.late_completion"
_PERMIT_FACTORY: Final = object()
_SCOPE_FACTORY: Final = object()


@dataclass(frozen=True, slots=True, init=False, repr=False, eq=False)
class SinkEvent:
    """仅由严格 Event DTO 或经严格解析的 JSON 构造的 Sink 投影。"""

    _event: AiCallEventV1
    _payload_jcs: bytes

    def __init__(self, event: AiCallEventV1) -> None:
        if not isinstance(
            event,
            (AiCallStartedV1, AiCallCompletedV1, AiCallLateCompletionV1),
        ):
            raise TypeError("SINK_EVENT_REQUIRES_AI_CALL_EVENT_V1")
        validated = parse_ai_call_event_v1(event.canonical_payload())
        object.__setattr__(self, "_event", validated)
        object.__setattr__(self, "_payload_jcs", validated.canonical_payload())

    @classmethod
    def from_json(cls, payload: str | bytes | bytearray) -> SinkEvent:
        return cls(parse_ai_call_event_v1(payload))

    @property
    def event_id(self) -> str:
        return self._event.event_id

    @property
    def event_type(self) -> EventType:
        return self._event.event_type

    @property
    def event_status(self) -> str:
        if isinstance(self._event, AiCallLateCompletionV1):
            return self._event.observed_status
        return self._event.status

    @property
    def payload_jcs(self) -> bytes:
        return self._payload_jcs

    def __repr__(self) -> str:
        return f"<SinkEvent event_type={self.event_type!r}>"


@dataclass(frozen=True, slots=True, init=False, repr=False, eq=False)
class CallScopeToken:
    """显式绑定单个进程内调用栈、event_id 与 generation 的 bearer token。"""

    _event_id: str
    _generation: int
    _owner: object

    def __init__(
        self,
        event_id: str,
        generation: int,
        owner: object,
        factory: object,
    ) -> None:
        if factory is not _SCOPE_FACTORY:
            raise TypeError("CALL_SCOPE_CONSTRUCTION_NOT_ALLOWED")
        object.__setattr__(self, "_event_id", event_id)
        object.__setattr__(self, "_generation", generation)
        object.__setattr__(self, "_owner", owner)

    @property
    def event_id(self) -> str:
        return self._event_id

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("PROCESS_LOCAL_SCOPE_NOT_SERIALIZABLE")

    def __repr__(self) -> str:
        return "<CallScopeToken process_local=True>"


class ReserveAttemptStatus(str, Enum):
    RESERVED_NEW = "reserved_new"
    REPLAYED_SAME = "replayed_same"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEADLINE_EXHAUSTED = "deadline_exhausted"


class CompleteAttemptStatus(str, Enum):
    COMPLETED_NEW = "completed_new"
    REPLAYED_SAME = "replayed_same"
    LATE_RECORDED = "late_recorded"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"
    AUDIT_UNAVAILABLE = "audit_unavailable"


class ReserveFault(str, Enum):
    """下一次 reserve 的纯测试故障；不模拟真实事务。"""

    COMMIT_BEFORE_RETURN = "commit_before_return"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEADLINE_EXHAUSTED = "deadline_exhausted"


class CompleteFault(str, Enum):
    """下一次 complete 的纯测试故障；不模拟真实事务。"""

    COMMIT_BEFORE_RETURN = "commit_before_return"
    AUDIT_UNAVAILABLE = "audit_unavailable"


class PermitUseError(RuntimeError):
    """不包含 Event payload 或外部异常文本的稳定 permit 错误。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _SingleUsePermit:
    __slots__ = ("_consume_callback", "_consumed", "_event_id")
    _already_consumed_code: str

    def __init__(
        self,
        event_id: str,
        consume_callback: Callable[[], None],
        factory: object,
    ) -> None:
        if factory is not _PERMIT_FACTORY:
            raise TypeError("PERMIT_CONSTRUCTION_NOT_ALLOWED")
        self._event_id = event_id
        self._consume_callback = consume_callback
        self._consumed = False

    @property
    def event_id(self) -> str:
        return self._event_id

    @property
    def consumed(self) -> bool:
        return self._consumed

    def consume(self) -> None:
        if self._consumed:
            raise PermitUseError(self._already_consumed_code)
        self._consumed = True
        self._consume_callback()

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("PROCESS_LOCAL_PERMIT_NOT_SERIALIZABLE")

    def __repr__(self) -> str:
        return f"<{type(self).__name__} consumed={self._consumed}>"


class SendPermit(_SingleUsePermit):
    """绑定当前 Fake 调用域与 event_id 的一次性发送许可。"""

    _already_consumed_code = "SEND_PERMIT_ALREADY_CONSUMED"


class AdoptPermit(_SingleUsePermit):
    """绑定当前 Fake 调用域与 event_id 的一次性采用许可。"""

    _already_consumed_code = "ADOPT_PERMIT_ALREADY_CONSUMED"


@dataclass(frozen=True, slots=True)
class ReserveAttemptDecision:
    status: ReserveAttemptStatus
    permit: SendPermit | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ReserveAttemptStatus):
            raise ValueError("status must be a ReserveAttemptStatus")
        if self.permit is not None and not isinstance(self.permit, SendPermit):
            raise ValueError("permit must be a SendPermit")
        if self.status is ReserveAttemptStatus.RESERVED_NEW and self.permit is None:
            raise ValueError("reserved_new requires a SendPermit")
        if self.permit is not None and self.status not in {
            ReserveAttemptStatus.RESERVED_NEW,
            ReserveAttemptStatus.REPLAYED_SAME,
        }:
            raise ValueError("reserve result does not allow a SendPermit")


@dataclass(frozen=True, slots=True)
class CompleteAttemptDecision:
    status: CompleteAttemptStatus
    permit: AdoptPermit | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, CompleteAttemptStatus):
            raise ValueError("status must be a CompleteAttemptStatus")
        if self.permit is not None and not isinstance(self.permit, AdoptPermit):
            raise ValueError("permit must be an AdoptPermit")
        if self.permit is not None and self.status not in {
            CompleteAttemptStatus.COMPLETED_NEW,
            CompleteAttemptStatus.REPLAYED_SAME,
        }:
            raise ValueError("complete result does not allow an AdoptPermit")


@runtime_checkable
class AiCallEventSink(Protocol):
    def create_call_scope(self, event: SinkEvent) -> CallScopeToken: ...

    async def reserve_attempt(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> ReserveAttemptDecision: ...

    async def complete_attempt(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> CompleteAttemptDecision: ...


class InMemoryAiCallEventSink:
    """单进程 Gate B Fake；记录保留与 restart 模拟均不构成持久化证据。"""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], bytes] = {}
        self._completed_statuses: dict[str, str] = {}
        self._generation = 0
        self._scope_owner = object()
        self._sent_scope: dict[str, CallScopeToken] = {}
        self._adopted_scope: dict[str, CallScopeToken] = {}
        self._reserve_commit_unknown: set[CallScopeToken] = set()
        self._complete_commit_unknown: set[tuple[CallScopeToken, tuple[str, str]]] = set()
        self._next_reserve_fault: ReserveFault | None = None
        self._next_complete_fault: CompleteFault | None = None

    def create_call_scope(self, event: SinkEvent) -> CallScopeToken:
        if not isinstance(event, SinkEvent):
            raise TypeError("CALL_SCOPE_REQUIRES_SINK_EVENT")
        return CallScopeToken(
            event.event_id,
            self._generation,
            self._scope_owner,
            _SCOPE_FACTORY,
        )

    def inject_next_reserve_fault(self, fault: ReserveFault) -> None:
        if not isinstance(fault, ReserveFault):
            raise ValueError("fault must be a ReserveFault")
        if self._next_reserve_fault is not None:
            raise RuntimeError("RESERVE_FAULT_ALREADY_ARMED")
        self._next_reserve_fault = fault

    def inject_next_complete_fault(self, fault: CompleteFault) -> None:
        if not isinstance(fault, CompleteFault):
            raise ValueError("fault must be a CompleteFault")
        if self._next_complete_fault is not None:
            raise RuntimeError("COMPLETE_FAULT_ALREADY_ARMED")
        self._next_complete_fault = fault

    def simulate_process_restart(self) -> None:
        """使进程内 permit/恢复证据失效；保留记录仅用于 replay-after-restart 测试。"""

        self._generation += 1
        self._sent_scope.clear()
        self._adopted_scope.clear()
        self._reserve_commit_unknown.clear()
        self._complete_commit_unknown.clear()
        self._next_reserve_fault = None
        self._next_complete_fault = None

    async def reserve_attempt(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> ReserveAttemptDecision:
        self._validate_scope(event, scope)
        if event.event_type != _STARTED_EVENT:
            raise ValueError("reserve_attempt requires ai.call.started")

        fault = self._next_reserve_fault
        self._next_reserve_fault = None
        if fault is ReserveFault.BUDGET_EXHAUSTED:
            return ReserveAttemptDecision(ReserveAttemptStatus.BUDGET_EXHAUSTED)
        if fault is ReserveFault.DEADLINE_EXHAUSTED:
            return ReserveAttemptDecision(ReserveAttemptStatus.DEADLINE_EXHAUSTED)

        key = (event.event_id, event.event_type)
        existing = self._records.get(key)
        if existing is not None:
            if existing != event.payload_jcs:
                return ReserveAttemptDecision(ReserveAttemptStatus.CONFLICT)
            if fault is ReserveFault.COMMIT_BEFORE_RETURN:
                return ReserveAttemptDecision(ReserveAttemptStatus.UNKNOWN)
            return ReserveAttemptDecision(
                ReserveAttemptStatus.REPLAYED_SAME,
                self._recover_send_permit(scope),
            )

        self._records[key] = event.payload_jcs
        if fault is ReserveFault.COMMIT_BEFORE_RETURN:
            self._reserve_commit_unknown.add(scope)
            return ReserveAttemptDecision(ReserveAttemptStatus.UNKNOWN)
        return ReserveAttemptDecision(
            ReserveAttemptStatus.RESERVED_NEW,
            self._issue_send_permit(scope),
        )

    async def complete_attempt(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> CompleteAttemptDecision:
        self._validate_scope(event, scope)
        if event.event_type not in {_COMPLETED_EVENT, _LATE_EVENT}:
            raise ValueError("complete_attempt requires completed or late event")
        if (event.event_id, _STARTED_EVENT) not in self._records:
            return CompleteAttemptDecision(CompleteAttemptStatus.UNKNOWN)
        if not self._completion_chain_is_valid(event):
            return CompleteAttemptDecision(CompleteAttemptStatus.CONFLICT)

        fault = self._next_complete_fault
        self._next_complete_fault = None
        if fault is CompleteFault.AUDIT_UNAVAILABLE:
            return CompleteAttemptDecision(CompleteAttemptStatus.AUDIT_UNAVAILABLE)

        key = (event.event_id, event.event_type)
        existing = self._records.get(key)
        if existing is not None:
            if existing != event.payload_jcs:
                return CompleteAttemptDecision(CompleteAttemptStatus.CONFLICT)
            if fault is CompleteFault.COMMIT_BEFORE_RETURN:
                return CompleteAttemptDecision(CompleteAttemptStatus.UNKNOWN)
            return CompleteAttemptDecision(
                CompleteAttemptStatus.REPLAYED_SAME,
                self._recover_adopt_permit(event, scope),
            )

        if event.event_type == _LATE_EVENT:
            if self._completed_statuses.get(event.event_id) != "outcome_unknown":
                return CompleteAttemptDecision(CompleteAttemptStatus.CONFLICT)
            self._records[key] = event.payload_jcs
            if fault is CompleteFault.COMMIT_BEFORE_RETURN:
                return CompleteAttemptDecision(CompleteAttemptStatus.UNKNOWN)
            return CompleteAttemptDecision(CompleteAttemptStatus.LATE_RECORDED)

        if event.event_id in self._completed_statuses:
            return CompleteAttemptDecision(CompleteAttemptStatus.CONFLICT)
        self._records[key] = event.payload_jcs
        self._completed_statuses[event.event_id] = event.event_status
        if fault is CompleteFault.COMMIT_BEFORE_RETURN:
            self._complete_commit_unknown.add((scope, key))
            return CompleteAttemptDecision(CompleteAttemptStatus.UNKNOWN)
        return CompleteAttemptDecision(
            CompleteAttemptStatus.COMPLETED_NEW,
            self._issue_adopt_permit(event, scope),
        )

    def _completion_chain_is_valid(self, event: SinkEvent) -> bool:
        started_payload = self._records.get((event.event_id, _STARTED_EVENT))
        if started_payload is None:
            return False
        started_event = parse_ai_call_event_v1(started_payload)
        if not isinstance(started_event, AiCallStartedV1):
            return False

        try:
            if isinstance(event._event, AiCallCompletedV1):
                validate_ai_call_event_chain(started_event, event._event)
            elif isinstance(event._event, AiCallLateCompletionV1):
                completed_payload = self._records.get((event.event_id, _COMPLETED_EVENT))
                if completed_payload is None:
                    return False
                completed_event = parse_ai_call_event_v1(completed_payload)
                if not isinstance(completed_event, AiCallCompletedV1):
                    return False
                validate_ai_call_event_chain(started_event, completed_event, event._event)
            else:
                return False
        except AiCallEventConflictError:
            return False
        return True

    def _validate_scope(self, event: SinkEvent, scope: CallScopeToken) -> None:
        if not isinstance(scope, CallScopeToken) or scope._owner is not self._scope_owner:
            raise PermitUseError("CALL_SCOPE_NOT_OWNED")
        if scope._generation != self._generation:
            raise PermitUseError("CALL_SCOPE_EXPIRED")
        if scope.event_id != event.event_id:
            raise PermitUseError("CALL_SCOPE_EVENT_MISMATCH")

    def _issue_send_permit(self, scope: CallScopeToken) -> SendPermit:
        return SendPermit(
            scope.event_id,
            lambda: self._consume_send(scope),
            _PERMIT_FACTORY,
        )

    def _recover_send_permit(self, scope: CallScopeToken) -> SendPermit | None:
        if scope not in self._reserve_commit_unknown:
            return None
        self._reserve_commit_unknown.remove(scope)
        if self._sent_scope.get(scope.event_id) is scope:
            return None
        return self._issue_send_permit(scope)

    def _consume_send(self, scope: CallScopeToken) -> None:
        if scope._owner is not self._scope_owner or scope._generation != self._generation:
            raise PermitUseError("SEND_PERMIT_SCOPE_EXPIRED")
        if scope.event_id in self._sent_scope:
            raise PermitUseError("SEND_ALREADY_RECORDED")
        self._sent_scope[scope.event_id] = scope

    def _issue_adopt_permit(
        self,
        event: SinkEvent,
        scope: CallScopeToken,
    ) -> AdoptPermit | None:
        if event.event_type != _COMPLETED_EVENT:
            return None
        if event.event_status == "outcome_unknown":
            return None
        if self._sent_scope.get(event.event_id) is not scope:
            return None
        if event.event_id in self._adopted_scope:
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
        if event.event_type != _COMPLETED_EVENT:
            return None
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


FakeAiCallEventSink = InMemoryAiCallEventSink
