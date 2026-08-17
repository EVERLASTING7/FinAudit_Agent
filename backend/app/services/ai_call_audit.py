"""AI 调用持久审计的事务边界与常驻维护入口。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from time import monotonic
from types import MappingProxyType
from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.events import AiCallCompletedV1, AiCallLateCompletionV1, AiCallStartedV1
from app.core.config import Settings
from app.repositories.ai_call_audit import (
    AiCallAuditLimits,
    AiCallAuditRepository,
    AiCallCompleteStatus,
    AiCallOperationAuditSummary,
    AiCallProjectionResult,
    AiCallReconcileResult,
    AiCallReserveStatus,
)


class TransactionalAiCallCompletionWriter:
    """将 AI completion Outbox 追加到调用方拥有的业务事务。"""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._repository = AiCallAuditRepository(session)

    def complete_attempt(
        self,
        event: AiCallCompletedV1 | AiCallLateCompletionV1,
    ) -> AiCallCompleteStatus:
        return self._repository.append_completion(event)


class AiCallAuditService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        self._session_factory = session_factory
        self._monotonic = monotonic_clock

    def reserve_attempt(
        self,
        event: AiCallStartedV1,
        limits: AiCallAuditLimits,
        *,
        deadline_monotonic: float,
        minimum_attempt_seconds: float = 0.0,
    ) -> AiCallReserveStatus:
        try:
            with self._session_factory.begin() as session:
                return AiCallAuditRepository(session).reserve_attempt(
                    event,
                    limits,
                    deadline_monotonic=deadline_monotonic,
                    monotonic=self._monotonic,
                    minimum_attempt_seconds=minimum_attempt_seconds,
                )
        except DBAPIError:
            # 提交结果不可确认时只能复用同一 event_id 查询/重试，不能换 ID 发送。
            return AiCallReserveStatus.UNKNOWN

    def complete_attempt(
        self,
        event: AiCallCompletedV1 | AiCallLateCompletionV1,
    ) -> AiCallCompleteStatus:
        try:
            with self._session_factory.begin() as session:
                return AiCallAuditRepository(session).append_completion(event)
        except DBAPIError:
            return AiCallCompleteStatus.UNKNOWN

    def project_once(self) -> AiCallProjectionResult:
        with self._session_factory.begin() as session:
            return AiCallAuditRepository(session).project_next()

    def reconcile_once(
        self,
        deadline_seconds_by_call_type: Mapping[str, int],
    ) -> AiCallReconcileResult:
        with self._session_factory.begin() as session:
            return AiCallAuditRepository(session).reconcile_expired_once(
                deadline_seconds_by_call_type
            )

    def get_operation_summary(
        self,
        organization_id: UUID,
        business_operation_id: UUID,
    ) -> AiCallOperationAuditSummary | None:
        with self._session_factory() as session:
            return AiCallAuditRepository(session).get_operation_summary(
                organization_id,
                business_operation_id,
            )


def ai_call_deadlines_from_settings(settings: Settings) -> Mapping[str, int]:
    """只投影已由启动 Policy 交叉校验的六类截止时间。"""

    if not isinstance(settings, Settings):
        raise TypeError("settings must be Settings")
    return MappingProxyType(
        {
            "contract_field_extraction": settings.ai_contract_extraction_deadline_seconds,
            "embedding": settings.ai_embedding_deadline_seconds,
            "invoice_field_extraction": settings.ai_invoice_extraction_deadline_seconds,
            "rag_answer": settings.ai_rag_answer_deadline_seconds,
            "report_draft": settings.ai_report_draft_deadline_seconds,
            "risk_explanation": settings.ai_risk_explanation_deadline_seconds,
        }
    )


__all__ = [
    "AiCallAuditService",
    "TransactionalAiCallCompletionWriter",
    "ai_call_deadlines_from_settings",
]
