"""OPS-005 组织隔离 AI 调用摘要查询。"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.ai_call_audit import AiCallAuditRepository
from app.schemas.ai_call_audit import AiCallAttemptData, AiCallAuditSummaryData, AiCallStatus


class AiCallAuditQueryService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_summary(
        self,
        organization_id: UUID,
        business_operation_id: UUID,
    ) -> AiCallAuditSummaryData:
        with self._session_factory() as session:
            summary = AiCallAuditRepository(session).get_operation_summary(
                organization_id,
                business_operation_id,
            )
        if summary is None:
            raise AppError(
                status_code=404,
                code="AI_CALL_AUDIT_NOT_FOUND",
                message="AI 调用摘要不存在或无权访问",
            )
        return AiCallAuditSummaryData(
            business_operation_id=summary.business_operation_id,
            attempt_count=summary.attempt_count,
            reserved_input_tokens=summary.reserved_input_tokens,
            reserved_output_tokens=summary.reserved_output_tokens,
            reserved_cost_micro_usd=summary.reserved_cost_micro_usd,
            actual_input_tokens=summary.actual_input_tokens,
            actual_output_tokens=summary.actual_output_tokens,
            attempts=tuple(
                AiCallAttemptData(
                    event_id=item.event_id,
                    provider_attempt_no=item.provider_attempt_no,
                    logical_generation_no=item.logical_generation_no,
                    model_id=item.model_id,
                    is_fallback=item.is_fallback,
                    status=cast(AiCallStatus, item.status),
                    reserved_input_tokens=item.reserved_input_tokens,
                    reserved_output_tokens=item.reserved_output_tokens,
                    reserved_cost_micro_usd=item.reserved_cost_micro_usd,
                    input_tokens=item.input_tokens,
                    output_tokens=item.output_tokens,
                    trace_id=item.trace_id,
                    started_at=item.started_at,
                    completed_at=item.completed_at,
                    safe_error_code=item.safe_error_code,
                )
                for item in summary.attempts
            ),
        )


__all__ = ["AiCallAuditQueryService"]
