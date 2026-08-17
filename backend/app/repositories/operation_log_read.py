"""operation-log-read-v1 的组织与匿名范围查询。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.operations import OperationLog


@dataclass(frozen=True, slots=True)
class OperationLogReadView:
    id: UUID
    actor_kind: str
    actor_id: UUID | None
    action_code: str
    outcome: str
    resource_type: str | None
    resource_id: UUID | None
    trace_id: UUID
    change_summary: dict[str, object]
    created_at: datetime


class OperationLogReadRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def read_page(
        self,
        organization_id: UUID,
        page_size: int,
        cursor_created_at: datetime | None,
        cursor_id: UUID | None,
    ) -> tuple[tuple[OperationLogReadView, ...], bool]:
        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact UUID")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size is invalid")
        if (cursor_created_at is None) != (cursor_id is None):
            raise ValueError("cursor fields must be provided together")

        statement = select(OperationLog).where(
            or_(
                OperationLog.organization_id == organization_id,
                and_(
                    OperationLog.organization_id.is_(None),
                    OperationLog.actor_kind == "anonymous",
                ),
            )
        )
        if cursor_created_at is not None and cursor_id is not None:
            statement = statement.where(
                or_(
                    OperationLog.created_at < cursor_created_at,
                    and_(
                        OperationLog.created_at == cursor_created_at,
                        OperationLog.id < cursor_id,
                    ),
                )
            )
        rows = tuple(
            self._session.execute(
                statement.order_by(OperationLog.created_at.desc(), OperationLog.id.desc()).limit(
                    page_size + 1
                )
            ).scalars()
        )
        has_more = len(rows) > page_size
        return (
            tuple(
                OperationLogReadView(
                    id=row.id,
                    actor_kind=row.actor_kind,
                    actor_id=row.actor_id,
                    action_code=row.action_code,
                    outcome=row.outcome,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    trace_id=row.trace_id,
                    change_summary=dict(row.change_summary_json),
                    created_at=row.created_at,
                )
                for row in rows[:page_size]
            ),
            has_more,
        )


__all__ = ["OperationLogReadRepository", "OperationLogReadView"]
