"""索引、评测与 RAG 的组织裁剪查询、锁和 CAS。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.auth import Organization
from app.models.documents import KnowledgeBase
from app.models.knowledge import (
    DocumentChunk,
    DocumentChunkSet,
    DocumentChunkSource,
    PolicyDocument,
)
from app.models.reliability import AsyncJob
from app.models.retrieval import (
    DocumentIndexItem,
    DocumentIndexVersion,
    QaFeedback,
    QaQuery,
    RetrievalEvalCase,
    RetrievalEvalDataset,
    RetrievalEvalRun,
)
from app.repositories.user_write import IdempotencyClaim, UserWriteRepository


@dataclass(frozen=True, slots=True)
class FrozenIndexMember:
    policy_id: UUID
    policy_version: str
    markdown_version_id: UUID
    chunk_set_id: UUID
    chunk_id: UUID
    chunk_index: int
    content_text: str
    content_sha256: str
    title_path: tuple[str, ...]
    start_page_no: int
    end_page_no: int


@dataclass(frozen=True, slots=True)
class MaterializationItem:
    item_id: UUID
    point_id: UUID
    content_text: str
    content_sha256: str
    vector_sha256: str | None
    payload_sha256: str | None


@dataclass(frozen=True, slots=True)
class AuthorizedIndexHit:
    point_id: UUID
    policy_id: UUID
    policy_name: str
    policy_version: str
    markdown_version_id: UUID
    chunk_id: UUID
    content_text: str
    content_sha256: str
    title_path: tuple[str, ...]
    start_page_no: int
    end_page_no: int
    block_ids: tuple[UUID, ...]


class RetrievalRuntimeRepository:
    """调用方持有事务；所有授权谓词都在 PostgreSQL 重验。"""

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

    def inspect_idempotency(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
        request_method: str,
        request_path: str,
        request_hash: str,
        now: datetime,
    ) -> IdempotencyClaim | None:
        return self._idempotency.inspect_idempotency(
            organization_id=organization_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request_method=request_method,
            request_path=request_path,
            request_hash=request_hash,
            now=now,
        )

    def complete_idempotency(
        self,
        claim: IdempotencyClaim,
        *,
        response_status: int,
        response_body: dict[str, object],
        resource_type: str,
        resource_id: UUID,
    ) -> None:
        self._idempotency.complete_idempotency(
            claim,
            response_status=response_status,
            response_body=response_body,
            resource_type=resource_type,
            resource_id=resource_id,
        )

    def lock_knowledge_base(
        self, organization_id: UUID, knowledge_base_id: UUID
    ) -> KnowledgeBase | None:
        return self._session.execute(
            select(KnowledgeBase)
            .where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.organization_id == organization_id,
                KnowledgeBase.status == "active",
                KnowledgeBase.deleted_at.is_(None),
            )
            .with_for_update(of=KnowledgeBase)
        ).scalar_one_or_none()

    def get_knowledge_base(
        self, organization_id: UUID, knowledge_base_id: UUID
    ) -> KnowledgeBase | None:
        return self._session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.organization_id == organization_id,
                KnowledgeBase.status == "active",
                KnowledgeBase.deleted_at.is_(None),
            )
        )

    def next_index_version_no(self, knowledge_base_id: UUID) -> int:
        latest = self._session.scalar(
            select(func.max(DocumentIndexVersion.version_no)).where(
                DocumentIndexVersion.knowledge_base_id == knowledge_base_id
            )
        )
        return int(latest or 0) + 1

    def frozen_index_members(self, knowledge_base_id: UUID) -> tuple[FrozenIndexMember, ...]:
        rows = self._session.execute(
            select(
                PolicyDocument.id,
                PolicyDocument.version,
                DocumentChunkSet.markdown_version_id,
                DocumentChunkSet.id,
                DocumentChunk.id,
                DocumentChunk.chunk_index,
                DocumentChunk.content_text,
                DocumentChunk.content_sha256,
                DocumentChunk.title_path,
                DocumentChunk.start_page_no,
                DocumentChunk.end_page_no,
            )
            .join(
                DocumentChunkSet,
                and_(
                    DocumentChunkSet.policy_document_id == PolicyDocument.id,
                    DocumentChunkSet.status == "active",
                ),
            )
            .join(DocumentChunk, DocumentChunk.chunk_set_id == DocumentChunkSet.id)
            .where(
                PolicyDocument.knowledge_base_id == knowledge_base_id,
                PolicyDocument.status.in_(("business_approved", "published")),
                PolicyDocument.deleted_at.is_(None),
            )
            .order_by(PolicyDocument.id, DocumentChunk.chunk_index, DocumentChunk.id)
            .with_for_update(of=(PolicyDocument, DocumentChunkSet), read=True)
        ).all()
        return tuple(
            FrozenIndexMember(
                policy_id=cast(UUID, row[0]),
                policy_version=cast(str, row[1]),
                markdown_version_id=cast(UUID, row[2]),
                chunk_set_id=cast(UUID, row[3]),
                chunk_id=cast(UUID, row[4]),
                chunk_index=cast(int, row[5]),
                content_text=cast(str, row[6]),
                content_sha256=cast(str, row[7]),
                title_path=tuple(cast(list[str], row[8])),
                start_page_no=cast(int, row[9]),
                end_page_no=cast(int, row[10]),
            )
            for row in rows
        )

    def get_index(
        self, organization_id: UUID, knowledge_base_id: UUID, index_version_id: UUID
    ) -> DocumentIndexVersion | None:
        return self._session.scalar(
            select(DocumentIndexVersion).where(
                DocumentIndexVersion.id == index_version_id,
                DocumentIndexVersion.organization_id == organization_id,
                DocumentIndexVersion.knowledge_base_id == knowledge_base_id,
            )
        )

    def get_active_index(
        self,
        organization_id: UUID,
        knowledge_base_id: UUID,
    ) -> DocumentIndexVersion | None:
        return self._session.scalar(
            select(DocumentIndexVersion).where(
                DocumentIndexVersion.organization_id == organization_id,
                DocumentIndexVersion.knowledge_base_id == knowledge_base_id,
                DocumentIndexVersion.status == "active",
            )
        )

    def lock_index(
        self, organization_id: UUID, index_version_id: UUID
    ) -> DocumentIndexVersion | None:
        return self._session.execute(
            select(DocumentIndexVersion)
            .where(
                DocumentIndexVersion.id == index_version_id,
                DocumentIndexVersion.organization_id == organization_id,
            )
            .with_for_update(of=DocumentIndexVersion)
        ).scalar_one_or_none()

    def job_for_resource(self, resource_type: str, resource_id: UUID) -> AsyncJob | None:
        return self._session.scalar(
            select(AsyncJob)
            .where(
                AsyncJob.resource_type == resource_type,
                AsyncJob.resource_id == resource_id,
            )
            .order_by(AsyncJob.created_at.desc(), AsyncJob.id.desc())
            .limit(1)
        )

    def materialization_items(self, index_version_id: UUID) -> tuple[MaterializationItem, ...]:
        rows = self._session.execute(
            select(
                DocumentIndexItem.id,
                DocumentIndexItem.qdrant_point_id,
                DocumentChunk.content_text,
                DocumentIndexItem.content_sha256,
                DocumentIndexItem.vector_sha256,
                DocumentIndexItem.payload_sha256,
            )
            .join(DocumentChunk, DocumentChunk.id == DocumentIndexItem.chunk_id)
            .where(DocumentIndexItem.index_version_id == index_version_id)
            .order_by(DocumentIndexItem.id)
        ).all()
        return tuple(
            MaterializationItem(
                item_id=cast(UUID, row[0]),
                point_id=cast(UUID, row[1]),
                content_text=cast(str, row[2]),
                content_sha256=cast(str, row[3]),
                vector_sha256=cast(str | None, row[4]),
                payload_sha256=cast(str | None, row[5]),
            )
            for row in rows
        )

    def materialize_item(self, item_id: UUID, vector_sha256: str, payload_sha256: str) -> bool:
        item = self._session.get(DocumentIndexItem, item_id)
        if item is None:
            return False
        if item.vector_sha256 is not None or item.payload_sha256 is not None:
            return item.vector_sha256 == vector_sha256 and item.payload_sha256 == payload_sha256
        item.vector_sha256 = vector_sha256
        item.payload_sha256 = payload_sha256
        self._session.flush()
        return True

    def mark_index_ready(
        self, index_version: DocumentIndexVersion, consistency: dict[str, object]
    ) -> bool:
        updated = self._session.scalar(
            update(DocumentIndexVersion)
            .where(
                DocumentIndexVersion.id == index_version.id,
                DocumentIndexVersion.status == "building",
                DocumentIndexVersion.row_version == index_version.row_version,
            )
            .values(
                status="ready",
                consistency_json=consistency,
                row_version=DocumentIndexVersion.row_version + 1,
            )
            .returning(DocumentIndexVersion.id)
        )
        return updated is not None

    def mark_index_failed(self, index_version: DocumentIndexVersion, failure_code: str) -> bool:
        updated = self._session.scalar(
            update(DocumentIndexVersion)
            .where(
                DocumentIndexVersion.id == index_version.id,
                DocumentIndexVersion.status == "building",
                DocumentIndexVersion.row_version == index_version.row_version,
            )
            .values(
                status="failed",
                failure_code=failure_code,
                row_version=DocumentIndexVersion.row_version + 1,
            )
            .returning(DocumentIndexVersion.id)
        )
        return updated is not None

    def activate_index(
        self,
        index_version: DocumentIndexVersion,
        *,
        actor_id: UUID,
        activated_at: datetime,
    ) -> bool:
        current = self._session.execute(
            select(DocumentIndexVersion)
            .where(
                DocumentIndexVersion.knowledge_base_id == index_version.knowledge_base_id,
                DocumentIndexVersion.status == "active",
            )
            .with_for_update(of=DocumentIndexVersion)
        ).scalar_one_or_none()
        if current is not None:
            superseded = self._session.scalar(
                update(DocumentIndexVersion)
                .where(
                    DocumentIndexVersion.id == current.id,
                    DocumentIndexVersion.status == "active",
                    DocumentIndexVersion.row_version == current.row_version,
                )
                .values(
                    status="superseded",
                    superseded_at=activated_at,
                    row_version=DocumentIndexVersion.row_version + 1,
                )
                .returning(DocumentIndexVersion.id)
            )
            if superseded is None:
                return False
        activated = self._session.scalar(
            update(DocumentIndexVersion)
            .where(
                DocumentIndexVersion.id == index_version.id,
                DocumentIndexVersion.status == "ready",
                DocumentIndexVersion.row_version == index_version.row_version,
            )
            .values(
                status="active",
                activated_by=actor_id,
                activated_at=activated_at,
                row_version=DocumentIndexVersion.row_version + 1,
            )
            .returning(DocumentIndexVersion.id)
        )
        if activated is None:
            return False
        self._session.expire(index_version)
        self._session.refresh(index_version)
        return True

    def active_point_ids(
        self,
        *,
        organization_id: UUID,
        knowledge_base_id: UUID,
        baseline_date: date,
        actor_roles: tuple[str, ...],
        limit: int = 10_000,
    ) -> tuple[UUID, ...]:
        if not 1 <= limit <= 10_000:
            raise ValueError("invalid allowed-set limit")
        role_filter = or_(
            func.cardinality(PolicyDocument.allowed_role_codes) == 0,
            PolicyDocument.allowed_role_codes.overlap(list(actor_roles)),
        )
        rows = self._session.scalars(
            select(DocumentIndexItem.qdrant_point_id)
            .join(
                DocumentIndexVersion,
                and_(
                    DocumentIndexVersion.id == DocumentIndexItem.index_version_id,
                    DocumentIndexVersion.status == "active",
                ),
            )
            .join(PolicyDocument, PolicyDocument.id == DocumentIndexItem.policy_document_id)
            .join(DocumentChunkSet, DocumentChunkSet.id == DocumentIndexItem.chunk_set_id)
            .join(DocumentChunk, DocumentChunk.id == DocumentIndexItem.chunk_id)
            .join(KnowledgeBase, KnowledgeBase.id == DocumentIndexItem.knowledge_base_id)
            .where(
                DocumentIndexItem.organization_id == organization_id,
                DocumentIndexItem.knowledge_base_id == knowledge_base_id,
                KnowledgeBase.organization_id == organization_id,
                KnowledgeBase.status == "active",
                KnowledgeBase.deleted_at.is_(None),
                PolicyDocument.organization_id == organization_id,
                PolicyDocument.knowledge_base_id == knowledge_base_id,
                PolicyDocument.status == "published",
                PolicyDocument.deleted_at.is_(None),
                PolicyDocument.access_scope == "internal",
                PolicyDocument.effective_from <= baseline_date,
                or_(
                    PolicyDocument.effective_to.is_(None),
                    PolicyDocument.effective_to > baseline_date,
                ),
                role_filter,
                DocumentChunkSet.status == "active",
                DocumentChunk.content_sha256 == DocumentIndexItem.content_sha256,
                DocumentIndexItem.vector_sha256.is_not(None),
                DocumentIndexItem.payload_sha256.is_not(None),
            )
            .order_by(DocumentIndexItem.qdrant_point_id)
            .limit(limit + 1)
        ).all()
        if len(rows) > limit:
            raise ValueError("authorized point set exceeds limit")
        return tuple(rows)

    def final_authorized_hits(
        self,
        *,
        organization_id: UUID,
        knowledge_base_id: UUID,
        baseline_date: date,
        actor_roles: tuple[str, ...],
        point_ids: tuple[UUID, ...],
    ) -> tuple[AuthorizedIndexHit, ...]:
        if not point_ids:
            return ()
        role_filter = or_(
            func.cardinality(PolicyDocument.allowed_role_codes) == 0,
            PolicyDocument.allowed_role_codes.overlap(list(actor_roles)),
        )
        rows = self._session.execute(
            select(
                DocumentIndexItem.qdrant_point_id,
                PolicyDocument.id,
                PolicyDocument.name,
                PolicyDocument.version,
                DocumentIndexItem.markdown_version_id,
                DocumentChunk.id,
                DocumentChunk.content_text,
                DocumentChunk.content_sha256,
                DocumentChunk.title_path,
                DocumentChunk.start_page_no,
                DocumentChunk.end_page_no,
            )
            .join(
                DocumentIndexVersion,
                and_(
                    DocumentIndexVersion.id == DocumentIndexItem.index_version_id,
                    DocumentIndexVersion.status == "active",
                ),
            )
            .join(PolicyDocument, PolicyDocument.id == DocumentIndexItem.policy_document_id)
            .join(DocumentChunkSet, DocumentChunkSet.id == DocumentIndexItem.chunk_set_id)
            .join(DocumentChunk, DocumentChunk.id == DocumentIndexItem.chunk_id)
            .join(KnowledgeBase, KnowledgeBase.id == DocumentIndexItem.knowledge_base_id)
            .where(
                DocumentIndexItem.qdrant_point_id.in_(point_ids),
                DocumentIndexItem.organization_id == organization_id,
                DocumentIndexItem.knowledge_base_id == knowledge_base_id,
                KnowledgeBase.status == "active",
                KnowledgeBase.deleted_at.is_(None),
                PolicyDocument.organization_id == organization_id,
                PolicyDocument.status == "published",
                PolicyDocument.deleted_at.is_(None),
                PolicyDocument.access_scope == "internal",
                PolicyDocument.effective_from <= baseline_date,
                or_(
                    PolicyDocument.effective_to.is_(None),
                    PolicyDocument.effective_to > baseline_date,
                ),
                role_filter,
                DocumentChunkSet.status == "active",
                DocumentChunk.content_sha256 == DocumentIndexItem.content_sha256,
            )
            .with_for_update(of=(DocumentIndexVersion, PolicyDocument), read=True)
        ).all()
        by_point = {cast(UUID, row[0]): row for row in rows}
        if set(by_point) != set(point_ids):
            return ()
        chunk_ids = tuple(cast(UUID, row[5]) for row in rows)
        source_rows = self._session.execute(
            select(
                DocumentChunkSource.chunk_id,
                DocumentChunkSource.block_id,
                DocumentChunkSource.source_seq,
            )
            .where(DocumentChunkSource.chunk_id.in_(chunk_ids))
            .order_by(DocumentChunkSource.chunk_id, DocumentChunkSource.source_seq)
        ).all()
        blocks: dict[UUID, list[UUID]] = {}
        for chunk_id, block_id, _ in source_rows:
            blocks.setdefault(cast(UUID, chunk_id), []).append(cast(UUID, block_id))
        if any(not blocks.get(chunk_id) for chunk_id in chunk_ids):
            return ()
        return tuple(
            AuthorizedIndexHit(
                point_id=point_id,
                policy_id=cast(UUID, by_point[point_id][1]),
                policy_name=cast(str, by_point[point_id][2]),
                policy_version=cast(str, by_point[point_id][3]),
                markdown_version_id=cast(UUID, by_point[point_id][4]),
                chunk_id=cast(UUID, by_point[point_id][5]),
                content_text=cast(str, by_point[point_id][6]),
                content_sha256=cast(str, by_point[point_id][7]),
                title_path=tuple(cast(list[str], by_point[point_id][8])),
                start_page_no=cast(int, by_point[point_id][9]),
                end_page_no=cast(int, by_point[point_id][10]),
                block_ids=tuple(blocks[cast(UUID, by_point[point_id][5])]),
            )
            for point_id in point_ids
        )

    def lock_dataset(self, organization_id: UUID, dataset_id: UUID) -> RetrievalEvalDataset | None:
        return self._session.execute(
            select(RetrievalEvalDataset)
            .where(
                RetrievalEvalDataset.id == dataset_id,
                RetrievalEvalDataset.organization_id == organization_id,
            )
            .with_for_update(of=RetrievalEvalDataset)
        ).scalar_one_or_none()

    def get_dataset(
        self, organization_id: UUID, knowledge_base_id: UUID, dataset_id: UUID
    ) -> RetrievalEvalDataset | None:
        return self._session.scalar(
            select(RetrievalEvalDataset).where(
                RetrievalEvalDataset.id == dataset_id,
                RetrievalEvalDataset.organization_id == organization_id,
                RetrievalEvalDataset.knowledge_base_id == knowledge_base_id,
            )
        )

    def transition_dataset(
        self,
        dataset: RetrievalEvalDataset,
        *,
        expected_row_version: int,
        values: dict[str, object],
    ) -> bool:
        updated = self._session.scalar(
            update(RetrievalEvalDataset)
            .where(
                RetrievalEvalDataset.id == dataset.id,
                RetrievalEvalDataset.status == dataset.status,
                RetrievalEvalDataset.row_version == expected_row_version,
            )
            .values(**values, row_version=RetrievalEvalDataset.row_version + 1)
            .returning(RetrievalEvalDataset.id)
        )
        if updated is None:
            return False
        self._session.expire(dataset)
        self._session.refresh(dataset)
        return True

    def next_dataset_version_no(self, knowledge_base_id: UUID, tier: str) -> int:
        latest = self._session.scalar(
            select(func.max(RetrievalEvalDataset.version_no)).where(
                RetrievalEvalDataset.knowledge_base_id == knowledge_base_id,
                RetrievalEvalDataset.tier == tier,
            )
        )
        return int(latest or 0) + 1

    def dataset_cases(self, dataset_id: UUID) -> tuple[RetrievalEvalCase, ...]:
        return tuple(
            self._session.scalars(
                select(RetrievalEvalCase)
                .where(RetrievalEvalCase.dataset_id == dataset_id)
                .order_by(RetrievalEvalCase.case_no)
            ).all()
        )

    def validate_case_references(
        self,
        *,
        knowledge_base_id: UUID,
        allowed_policy_ids: tuple[UUID, ...],
        expected_chunk_ids: tuple[UUID, ...],
        forbidden_chunk_ids: tuple[UUID, ...],
    ) -> bool:
        if allowed_policy_ids:
            policy_count = self._session.scalar(
                select(func.count())
                .select_from(PolicyDocument)
                .where(
                    PolicyDocument.id.in_(allowed_policy_ids),
                    PolicyDocument.knowledge_base_id == knowledge_base_id,
                    PolicyDocument.status.in_(("business_approved", "published")),
                    PolicyDocument.deleted_at.is_(None),
                )
            )
            if policy_count != len(allowed_policy_ids):
                return False
        if expected_chunk_ids:
            expected_count = self._session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .join(DocumentChunkSet, DocumentChunkSet.id == DocumentChunk.chunk_set_id)
                .join(PolicyDocument, PolicyDocument.id == DocumentChunkSet.policy_document_id)
                .where(
                    DocumentChunk.id.in_(expected_chunk_ids),
                    DocumentChunkSet.status == "active",
                    PolicyDocument.knowledge_base_id == knowledge_base_id,
                    PolicyDocument.id.in_(allowed_policy_ids),
                    PolicyDocument.status.in_(("business_approved", "published")),
                    PolicyDocument.deleted_at.is_(None),
                )
            )
            if expected_count != len(expected_chunk_ids):
                return False
        if forbidden_chunk_ids:
            forbidden_count = self._session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .join(DocumentChunkSet, DocumentChunkSet.id == DocumentChunk.chunk_set_id)
                .join(PolicyDocument, PolicyDocument.id == DocumentChunkSet.policy_document_id)
                .where(
                    DocumentChunk.id.in_(forbidden_chunk_ids),
                    DocumentChunkSet.status == "active",
                    PolicyDocument.knowledge_base_id == knowledge_base_id,
                    ~PolicyDocument.id.in_(allowed_policy_ids),
                    PolicyDocument.status.in_(("business_approved", "published")),
                    PolicyDocument.deleted_at.is_(None),
                )
            )
            if forbidden_count != len(forbidden_chunk_ids):
                return False
        return True

    def active_index_contains_policy(
        self, knowledge_base_id: UUID, policy_document_id: UUID
    ) -> DocumentIndexVersion | None:
        return self._session.scalar(
            select(DocumentIndexVersion)
            .join(
                DocumentIndexItem,
                DocumentIndexItem.index_version_id == DocumentIndexVersion.id,
            )
            .where(
                DocumentIndexVersion.knowledge_base_id == knowledge_base_id,
                DocumentIndexVersion.status == "active",
                DocumentIndexItem.policy_document_id == policy_document_id,
                DocumentIndexItem.vector_sha256.is_not(None),
                DocumentIndexItem.payload_sha256.is_not(None),
            )
            .limit(1)
        )

    def eval_allowed_point_ids(
        self,
        *,
        index_version_id: UUID,
        baseline_date: date,
        allowed_policy_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        if not allowed_policy_ids:
            return ()
        return tuple(
            self._session.scalars(
                select(DocumentIndexItem.qdrant_point_id)
                .join(PolicyDocument, PolicyDocument.id == DocumentIndexItem.policy_document_id)
                .join(DocumentChunkSet, DocumentChunkSet.id == DocumentIndexItem.chunk_set_id)
                .join(DocumentChunk, DocumentChunk.id == DocumentIndexItem.chunk_id)
                .where(
                    DocumentIndexItem.index_version_id == index_version_id,
                    DocumentIndexItem.policy_document_id.in_(allowed_policy_ids),
                    PolicyDocument.status.in_(("business_approved", "published")),
                    PolicyDocument.effective_from <= baseline_date,
                    or_(
                        PolicyDocument.effective_to.is_(None),
                        PolicyDocument.effective_to > baseline_date,
                    ),
                    DocumentChunkSet.status == "active",
                    DocumentChunk.content_sha256 == DocumentIndexItem.content_sha256,
                    DocumentIndexItem.vector_sha256.is_not(None),
                )
                .order_by(DocumentIndexItem.qdrant_point_id)
            ).all()
        )

    def eval_hit_identity(
        self, index_version_id: UUID, point_ids: tuple[UUID, ...]
    ) -> dict[UUID, tuple[UUID, UUID, str]]:
        if not point_ids:
            return {}
        rows = self._session.execute(
            select(
                DocumentIndexItem.qdrant_point_id,
                DocumentIndexItem.policy_document_id,
                DocumentIndexItem.chunk_id,
                PolicyDocument.version,
            )
            .join(PolicyDocument, PolicyDocument.id == DocumentIndexItem.policy_document_id)
            .join(DocumentChunk, DocumentChunk.id == DocumentIndexItem.chunk_id)
            .where(
                DocumentIndexItem.index_version_id == index_version_id,
                DocumentIndexItem.qdrant_point_id.in_(point_ids),
                DocumentChunk.content_sha256 == DocumentIndexItem.content_sha256,
            )
        ).all()
        return {
            cast(UUID, row[0]): (cast(UUID, row[1]), cast(UUID, row[2]), cast(str, row[3]))
            for row in rows
        }

    def index_chunk_identity(
        self, index_version_id: UUID, chunk_ids: tuple[UUID, ...]
    ) -> dict[UUID, tuple[UUID, str]]:
        if not chunk_ids:
            return {}
        rows = self._session.execute(
            select(
                DocumentIndexItem.chunk_id,
                DocumentIndexItem.policy_document_id,
                PolicyDocument.version,
            )
            .join(PolicyDocument, PolicyDocument.id == DocumentIndexItem.policy_document_id)
            .where(
                DocumentIndexItem.index_version_id == index_version_id,
                DocumentIndexItem.chunk_id.in_(chunk_ids),
            )
        ).all()
        return {cast(UUID, row[0]): (cast(UUID, row[1]), cast(str, row[2])) for row in rows}

    def lock_run(self, organization_id: UUID, run_id: UUID) -> RetrievalEvalRun | None:
        return self._session.execute(
            select(RetrievalEvalRun)
            .where(
                RetrievalEvalRun.id == run_id,
                RetrievalEvalRun.organization_id == organization_id,
            )
            .with_for_update(of=RetrievalEvalRun)
        ).scalar_one_or_none()

    def get_run(
        self, organization_id: UUID, knowledge_base_id: UUID, run_id: UUID
    ) -> RetrievalEvalRun | None:
        return self._session.scalar(
            select(RetrievalEvalRun).where(
                RetrievalEvalRun.id == run_id,
                RetrievalEvalRun.organization_id == organization_id,
                RetrievalEvalRun.knowledge_base_id == knowledge_base_id,
            )
        )

    def formal_passed_run(self, index_version_id: UUID) -> RetrievalEvalRun | None:
        return self._session.scalar(
            select(RetrievalEvalRun)
            .where(
                RetrievalEvalRun.index_version_id == index_version_id,
                RetrievalEvalRun.tier == "formal_release",
                RetrievalEvalRun.status == "passed",
            )
            .order_by(RetrievalEvalRun.finished_at.desc(), RetrievalEvalRun.id.desc())
            .limit(1)
        )

    def add(self, value: object) -> None:
        self._session.add(value)

    def add_all(self, values: tuple[object, ...]) -> None:
        self._session.add_all(values)

    def flush(self) -> None:
        self._session.flush()

    def get_qa_query(self, organization_id: UUID, query_id: UUID) -> QaQuery | None:
        return self._session.scalar(
            select(QaQuery).where(
                QaQuery.id == query_id,
                QaQuery.organization_id == organization_id,
            )
        )

    def lock_qa_query(self, organization_id: UUID, query_id: UUID) -> QaQuery | None:
        return self._session.execute(
            select(QaQuery)
            .where(
                QaQuery.id == query_id,
                QaQuery.organization_id == organization_id,
            )
            .with_for_update(of=QaQuery)
        ).scalar_one_or_none()

    def feedback_for_actor(self, query_id: UUID, actor_id: UUID) -> QaFeedback | None:
        return self._session.scalar(
            select(QaFeedback).where(
                QaFeedback.qa_query_id == query_id,
                QaFeedback.created_by == actor_id,
            )
        )


__all__ = [
    "AuthorizedIndexHit",
    "FrozenIndexMember",
    "MaterializationItem",
    "RetrievalRuntimeRepository",
]
