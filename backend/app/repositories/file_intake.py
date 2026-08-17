"""文件上传的固定锁序、去重、Job/Outbox 与读取投影。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.auth import Organization
from app.models.documents import FileRecord, KnowledgeBase
from app.models.knowledge import DocumentMarkdownVersion
from app.models.reliability import AsyncJob, IdempotencyRecord


@dataclass(frozen=True, slots=True)
class FileJobView:
    file: FileRecord
    job: AsyncJob


class FileIntakeRepository:
    """所有写操作均由调用方持有一个 PostgreSQL 事务。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def database_now(self) -> datetime:
        return cast(datetime, self._session.execute(select(func.clock_timestamp())).scalar_one())

    def acquire_content_lock(self, organization_id: UUID, sha256: str, size_bytes: int) -> None:
        identity = f"finaudit:file-content:{organization_id}:{sha256}:{size_bytes}"
        self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(identity, 0)))
        ).one()

    def acquire_idempotency_lock(
        self,
        organization_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> None:
        identity = f"{organization_id}:{actor_id}:{idempotency_key}"
        self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(identity, 1)))
        ).one()

    def lock_active_organization(self, organization_id: UUID) -> Organization | None:
        return self._session.execute(
            select(Organization)
            .where(
                Organization.id == organization_id,
                Organization.status == "active",
                Organization.deleted_at.is_(None),
            )
            .with_for_update(of=Organization)
        ).scalar_one_or_none()

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
    ) -> tuple[IdempotencyRecord, bool, bool]:
        record = self._session.execute(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.organization_id == organization_id,
                IdempotencyRecord.user_id == actor_id,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
            .with_for_update(of=IdempotencyRecord)
        ).scalar_one_or_none()
        if record is not None and record.expires_at > now:
            conflict = (
                record.request_method != request_method
                or record.request_path != request_path
                or record.request_hash != request_hash
            )
            if conflict:
                return record, False, True
            if record.response_status is None or record.response_body_json is None:
                raise RuntimeError("committed file idempotency record is incomplete")
            return record, True, False
        if record is None:
            record = IdempotencyRecord(
                organization_id=organization_id,
                user_id=actor_id,
                idempotency_key=idempotency_key,
                request_method=request_method,
                request_path=request_path,
                request_hash=request_hash,
                expires_at=expires_at,
                created_at=now,
            )
            self._session.add(record)
        else:
            record.request_method = request_method
            record.request_path = request_path
            record.request_hash = request_hash
            record.response_status = None
            record.response_body_json = None
            record.resource_type = None
            record.resource_id = None
            record.expires_at = expires_at
            record.created_at = now
        return record, False, False

    def lock_active_knowledge_base(
        self,
        organization_id: UUID,
        knowledge_base_id: UUID,
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

    def lock_duplicate(
        self,
        organization_id: UUID,
        sha256: str,
        size_bytes: int,
    ) -> FileRecord | None:
        return self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.organization_id == organization_id,
                FileRecord.sha256 == sha256,
                FileRecord.size_bytes == size_bytes,
                FileRecord.deleted_at.is_(None),
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()

    def lock_file(self, organization_id: UUID, file_id: UUID) -> FileRecord | None:
        return self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
                FileRecord.deleted_at.is_(None),
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()

    def active_markdown(
        self,
        organization_id: UUID,
        file_id: UUID,
    ) -> DocumentMarkdownVersion | None:
        return self._session.execute(
            select(DocumentMarkdownVersion).where(
                DocumentMarkdownVersion.organization_id == organization_id,
                DocumentMarkdownVersion.file_id == file_id,
                DocumentMarkdownVersion.status == "active",
            )
        ).scalar_one_or_none()

    def job_for_file(self, file_id: UUID, *, lock: bool = False) -> AsyncJob | None:
        statement = (
            select(AsyncJob)
            .where(
                AsyncJob.resource_type == "file",
                AsyncJob.resource_id == file_id,
                AsyncJob.job_type.in_(("file_scan", "file_process")),
            )
            .order_by(
                (AsyncJob.job_type == "file_process").desc(),
                AsyncJob.created_at.desc(),
                AsyncJob.id.desc(),
            )
        )
        if lock:
            statement = statement.with_for_update(of=AsyncJob)
        return self._session.execute(statement).scalars().first()

    def read_file(self, organization_id: UUID, file_id: UUID) -> FileJobView | None:
        row = self._session.execute(
            select(FileRecord, AsyncJob)
            .join(
                AsyncJob,
                and_(
                    AsyncJob.resource_type == "file",
                    AsyncJob.resource_id == FileRecord.id,
                    AsyncJob.job_type.in_(("file_scan", "file_process")),
                ),
            )
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
                FileRecord.deleted_at.is_(None),
            )
            .order_by((AsyncJob.job_type == "file_process").desc(), AsyncJob.id.desc())
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        return FileJobView(file=cast(FileRecord, row[0]), job=cast(AsyncJob, row[1]))

    def read_page(
        self,
        organization_id: UUID,
        page_size: int,
        cursor_created_at: datetime | None,
        cursor_id: UUID | None,
    ) -> tuple[tuple[FileJobView, ...], bool]:
        preferred_job = (
            select(AsyncJob.id)
            .where(
                AsyncJob.resource_type == "file",
                AsyncJob.resource_id == FileRecord.id,
                AsyncJob.job_type.in_(("file_scan", "file_process")),
            )
            .order_by((AsyncJob.job_type == "file_process").desc(), AsyncJob.id.desc())
            .limit(1)
            .correlate(FileRecord)
            .scalar_subquery()
        )
        conditions = [
            FileRecord.organization_id == organization_id,
            FileRecord.deleted_at.is_(None),
            AsyncJob.id == preferred_job,
        ]
        if cursor_created_at is not None and cursor_id is not None:
            conditions.append(
                or_(
                    FileRecord.created_at < cursor_created_at,
                    and_(
                        FileRecord.created_at == cursor_created_at,
                        FileRecord.id < cursor_id,
                    ),
                )
            )
        rows = self._session.execute(
            select(FileRecord, AsyncJob)
            .join(AsyncJob, AsyncJob.resource_id == FileRecord.id)
            .where(*conditions)
            .order_by(FileRecord.created_at.desc(), FileRecord.id.desc())
            .limit(page_size + 1)
        ).all()
        has_more = len(rows) > page_size
        return (
            tuple(
                FileJobView(file=cast(FileRecord, row[0]), job=cast(AsyncJob, row[1]))
                for row in rows[:page_size]
            ),
            has_more,
        )

    def add(self, value: object) -> None:
        self._session.add(value)

    def flush(self) -> None:
        self._session.flush()


__all__ = ["FileIntakeRepository", "FileJobView"]
