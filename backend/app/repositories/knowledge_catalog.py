"""知识库目录的组织范围只读查询。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import KnowledgeBase


class KnowledgeCatalogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_knowledge_bases(
        self,
        organization_id: UUID,
        cursor_id: UUID | None,
        limit: int,
    ) -> tuple[KnowledgeBase, ...]:
        statement = select(KnowledgeBase).where(
            KnowledgeBase.organization_id == organization_id,
            KnowledgeBase.deleted_at.is_(None),
        )
        if cursor_id is not None:
            statement = statement.where(KnowledgeBase.id > cursor_id)
        return tuple(self._session.scalars(statement.order_by(KnowledgeBase.id).limit(limit)).all())

    def get_knowledge_base(
        self,
        organization_id: UUID,
        knowledge_base_id: UUID,
    ) -> KnowledgeBase | None:
        return self._session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.organization_id == organization_id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )


__all__ = ["KnowledgeCatalogRepository"]
