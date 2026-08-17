"""制度元数据与审批状态的组织锁、幂等和 CAS 访问。"""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.auth import Organization
from app.models.documents import FilePrimaryBusinessObject, FileRecord, KnowledgeBase
from app.models.knowledge import (
    DocumentChunkSet,
    DocumentMarkdownVersion,
    PolicyDocument,
)
from app.repositories.user_write import IdempotencyClaim, UserWriteRepository


class PolicyWriteRepository:
    """组织 → 幂等键 → 制度/来源文件的固定锁序。"""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._idempotency = UserWriteRepository(session)

    def database_now(self) -> datetime:
        return cast(datetime, self._session.scalar(select(func.clock_timestamp())))

    def acquire_api_locks(
        self, organization_id: UUID, actor_id: UUID, idempotency_key: str
    ) -> None:
        self._idempotency.acquire_organization_lock(organization_id)
        self._idempotency.acquire_idempotency_lock(organization_id, actor_id, idempotency_key)

    def lock_active_organization(self, organization_id: UUID) -> Organization | None:
        return self._idempotency.lock_active_organization(organization_id)

    def claim_idempotency(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
        request_method: str,
        request_path: str,
        request_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> IdempotencyClaim:
        return self._idempotency.claim_idempotency(
            organization_id=organization_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request_method=request_method,
            request_path=request_path,
            request_hash=request_hash,
            now=now,
            expires_at=expires_at,
        )

    def complete_idempotency(
        self,
        claim: IdempotencyClaim,
        *,
        response_status: int,
        response_body: dict[str, object],
        resource_id: UUID,
    ) -> None:
        self._idempotency.complete_idempotency(
            claim,
            response_status=response_status,
            response_body=response_body,
            resource_id=resource_id,
            resource_type="policy_document",
        )

    def list_policies(
        self,
        organization_id: UUID,
        cursor_id: UUID | None,
        limit: int,
        *,
        include_unpublished: bool,
        knowledge_base_id: UUID | None = None,
    ) -> tuple[PolicyDocument, ...]:
        statement = select(PolicyDocument).where(
            PolicyDocument.organization_id == organization_id,
            PolicyDocument.deleted_at.is_(None),
        )
        if not include_unpublished:
            statement = statement.where(PolicyDocument.status == "published")
        if knowledge_base_id is not None:
            statement = statement.where(PolicyDocument.knowledge_base_id == knowledge_base_id)
        if cursor_id is not None:
            statement = statement.where(PolicyDocument.id > cursor_id)
        return tuple(
            self._session.scalars(statement.order_by(PolicyDocument.id).limit(limit)).all()
        )

    def get_policy(
        self,
        organization_id: UUID,
        policy_document_id: UUID,
        *,
        include_unpublished: bool,
    ) -> PolicyDocument | None:
        statement = select(PolicyDocument).where(
            PolicyDocument.id == policy_document_id,
            PolicyDocument.organization_id == organization_id,
            PolicyDocument.deleted_at.is_(None),
        )
        if not include_unpublished:
            statement = statement.where(PolicyDocument.status == "published")
        return self._session.scalar(statement)

    def lock_knowledge_base(
        self, organization_id: UUID, knowledge_base_id: UUID
    ) -> KnowledgeBase | None:
        return self._session.execute(
            select(KnowledgeBase)
            .where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.organization_id == organization_id,
                KnowledgeBase.deleted_at.is_(None),
            )
            .with_for_update(of=KnowledgeBase)
        ).scalar_one_or_none()

    def lock_source_file(self, organization_id: UUID, file_id: UUID) -> FileRecord | None:
        return self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
                FileRecord.deleted_at.is_(None),
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()

    def source_binding(self, file_id: UUID) -> FilePrimaryBusinessObject | None:
        return self._session.scalar(
            select(FilePrimaryBusinessObject).where(FilePrimaryBusinessObject.file_id == file_id)
        )

    def active_markdown(
        self, organization_id: UUID, file_id: UUID
    ) -> DocumentMarkdownVersion | None:
        return self._session.scalar(
            select(DocumentMarkdownVersion).where(
                DocumentMarkdownVersion.organization_id == organization_id,
                DocumentMarkdownVersion.file_id == file_id,
                DocumentMarkdownVersion.status == "active",
                DocumentMarkdownVersion.blocking_issue_count == 0,
            )
        )

    def lock_policy(self, organization_id: UUID, policy_document_id: UUID) -> PolicyDocument | None:
        return self._session.execute(
            select(PolicyDocument)
            .where(
                PolicyDocument.id == policy_document_id,
                PolicyDocument.organization_id == organization_id,
                PolicyDocument.deleted_at.is_(None),
            )
            .with_for_update(of=PolicyDocument)
        ).scalar_one_or_none()

    def active_chunk_set(self, policy_document_id: UUID) -> DocumentChunkSet | None:
        return self._session.scalar(
            select(DocumentChunkSet).where(
                DocumentChunkSet.policy_document_id == policy_document_id,
                DocumentChunkSet.status == "active",
            )
        )

    def cas_policy(
        self,
        policy: PolicyDocument,
        expected_row_version: int,
        values: dict[str, object],
    ) -> bool:
        updated_id = self._session.scalar(
            update(PolicyDocument)
            .where(
                PolicyDocument.id == policy.id,
                PolicyDocument.organization_id == policy.organization_id,
                PolicyDocument.deleted_at.is_(None),
                PolicyDocument.row_version == expected_row_version,
            )
            .values(**values, row_version=PolicyDocument.row_version + 1)
            .execution_options(synchronize_session=False)
            .returning(PolicyDocument.id)
        )
        if updated_id is None:
            return False
        self._session.expire(policy)
        self._session.refresh(policy)
        return True

    def add(self, value: object) -> None:
        self._session.add(value)

    def flush(self) -> None:
        self._session.flush()


__all__ = ["PolicyWriteRepository"]
