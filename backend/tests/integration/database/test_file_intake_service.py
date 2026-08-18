from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from threading import Lock
from types import SimpleNamespace
from typing import BinaryIO, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.minio_quarantine import MinioQuarantineAdapter, QuarantineObject
from app.core.config import Settings
from app.core.errors import AppError
from app.db.migration import create_migration_engine
from app.db.session import create_session_factory
from app.models.auth import Organization, User
from app.models.documents import FileRecord
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, IdempotencyRecord, OutboxEvent
from app.repositories.operation_log import OperationLogRepository
from app.schemas.files import FileUploadIntent, IntendedBusinessType
from app.services.auth import AuthenticatedActor
from app.services.file_intake import (
    FILE_HANDLER_REGISTRY_HASH,
    FILE_HANDLER_REGISTRY_VERSION,
    FileIntakeService,
    FileQueryService,
    FileUploadResult,
)
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
)

pytestmark = pytest.mark.integration

ORGANIZATION_ID = UUID("6e000000-0000-4000-8000-000000000001")
ACTOR_ID = UUID("6e000000-0000-4000-8000-000000000002")
PDF_CONTENT = b"%PDF-1.7\nsynthetic transactional file intake"


class MemoryQuarantineStorage:
    def __init__(self) -> None:
        self._lock = Lock()
        self.objects: dict[str, bytes] = {}
        self.put_count = 0
        self.delete_count = 0

    def put_quarantine(
        self,
        *,
        organization_id: UUID,
        file_id: UUID,
        sha256: str,
        data: BinaryIO,
        length: int,
        content_type: str,
    ) -> QuarantineObject:
        del content_type
        data.seek(0)
        payload = data.read(length)
        assert len(payload) == length
        assert hashlib.sha256(payload).hexdigest() == sha256
        locator = QuarantineObject(
            "quarantine",
            f"organizations/{organization_id.hex}/files/{file_id.hex}/source",
        )
        with self._lock:
            self.objects[locator.object_key] = payload
            self.put_count += 1
        return locator

    def delete_quarantine(self, locator: QuarantineObject) -> None:
        with self._lock:
            self.objects.pop(locator.object_key, None)
            self.delete_count += 1


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=("finance_reviewer",),
        permissions=("files.read", "files.upload"),
    )


def _intent() -> FileUploadIntent:
    return FileUploadIntent(intended_business_type=IntendedBusinessType.CONTRACT)


def _seed_actor(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        session.add(
            Organization(
                id=ORGANIZATION_ID,
                name="Synthetic file-intake organization",
                unified_social_credit_code="SYNTH-FILE-INTAKE-USCC",
                tax_number="SYNTH-FILE-INTAKE-TAX",
                status="active",
            )
        )
        session.flush()
        session.add(
            User(
                id=ACTOR_ID,
                organization_id=ORGANIZATION_ID,
                username="file.intake.actor",
                display_name="文件接入测试用户",
                password_hash="$argon2id$v=19$m=65536,t=3,p=4$synthetic$synthetic",
                status="active",
                password_changed_at=datetime.now(timezone.utc),
            )
        )


def _clear_subjects(engine: Engine) -> None:
    with engine.begin() as connection:
        protected_tables = (
            "operation_logs",
            "outbox_events",
            "async_job_steps",
            "async_jobs",
            "files",
            "knowledge_bases",
        )
        for table_name in protected_tables:
            connection.exec_driver_sql(f"ALTER TABLE {table_name} DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM outbox_events WHERE aggregate_id IN "
                "(SELECT id FROM async_jobs WHERE organization_id = %s)",
                (ORGANIZATION_ID,),
            )
            connection.exec_driver_sql(
                "DELETE FROM async_job_steps WHERE job_id IN "
                "(SELECT id FROM async_jobs WHERE organization_id = %s)",
                (ORGANIZATION_ID,),
            )
            connection.exec_driver_sql(
                "DELETE FROM async_jobs WHERE organization_id = %s", (ORGANIZATION_ID,)
            )
            connection.exec_driver_sql(
                "DELETE FROM idempotency_records WHERE organization_id = %s",
                (ORGANIZATION_ID,),
            )
            connection.exec_driver_sql(
                "DELETE FROM operation_logs WHERE organization_id = %s", (ORGANIZATION_ID,)
            )
            connection.exec_driver_sql(
                "DELETE FROM files WHERE organization_id = %s", (ORGANIZATION_ID,)
            )
            connection.exec_driver_sql(
                "DELETE FROM knowledge_bases WHERE organization_id = %s",
                (ORGANIZATION_ID,),
            )
            connection.exec_driver_sql(
                "DELETE FROM users WHERE organization_id = %s", (ORGANIZATION_ID,)
            )
            connection.exec_driver_sql(
                "DELETE FROM organizations WHERE id = %s", (ORGANIZATION_ID,)
            )
        finally:
            for table_name in reversed(protected_tables):
                connection.exec_driver_sql(f"ALTER TABLE {table_name} ENABLE TRIGGER USER")


def _setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    Engine,
    sessionmaker[Session],
    FileIntakeService,
    MemoryQuarantineStorage,
]:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    factory = create_session_factory(engine)
    _seed_actor(factory)
    storage = MemoryQuarantineStorage()
    settings = cast(
        Settings,
        SimpleNamespace(max_upload_size_mb=1, max_batch_file_count=20),
    )
    service = FileIntakeService(
        factory,
        cast(MinioQuarantineAdapter, storage),
        settings,
    )
    return engine, factory, service, storage


def _upload(
    service: FileIntakeService,
    key: str,
    *,
    content: bytes = PDF_CONTENT,
    file_name: str = "contract.pdf",
) -> FileUploadResult:
    return service.upload(
        _actor(),
        _intent(),
        file_name=file_name,
        declared_mime="application/pdf",
        stream=BytesIO(content),
        idempotency_key=key,
        trace_id=uuid4(),
    )


def test_upload_commits_file_idempotency_job_outbox_and_log_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service, storage = _setup(monkeypatch)
    try:
        first = _upload(service, "file-intake-001")
        replay = _upload(service, "file-intake-001")

        assert first.replayed is False
        assert first.data.reused is False
        assert replay.replayed is True
        assert replay.data == first.data
        assert storage.put_count == 1
        assert tuple(storage.objects.values()) == (PDF_CONTENT,)
        with factory() as session:
            file = session.get(FileRecord, first.data.file_id)
            job = session.get(AsyncJob, first.data.job_id)
            assert file is not None
            assert file.status == "uploaded"
            assert file.security_scan_status == "pending"
            assert file.sha256 == hashlib.sha256(PDF_CONTENT).hexdigest()
            assert job is not None
            assert job.job_type == "file_process"
            assert job.status == "queued"
            assert job.current_attempt_start_step_code == "scan"
            assert job.handler_registry_version == FILE_HANDLER_REGISTRY_VERSION
            assert job.handler_registry_hash == FILE_HANDLER_REGISTRY_HASH
            assert job.input_json == {
                "auto_process_requested": True,
                "file_id": str(file.id),
                "intended_business_type": "contract",
                "processing_scope": "full",
                "target_knowledge_base_id": None,
            }
            idempotency = session.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.idempotency_key == "file-intake-001"
                )
            ).scalar_one()
            assert idempotency.response_status == 202
            assert idempotency.resource_id == file.id
            assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
            outbox = session.scalar(select(OutboxEvent))
            assert outbox is not None
            assert outbox.event_type == "job.dispatch.requested"
            assert outbox.aggregate_id == job.id
            assert outbox.event_version == 1
            assert outbox.payload_json == {"job_id": str(job.id)}
            log = session.execute(
                select(OperationLog).where(OperationLog.resource_id == file.id)
            ).scalar_one()
            assert log.action_code == "files.uploaded"
            assert log.change_summary_json == {
                "intended_business_type": "contract",
                "job_scope": "full",
                "row_version": "1",
            }
    finally:
        _clear_subjects(engine)
        engine.dispose()


def test_query_pages_files_and_hides_other_organizations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service, _storage = _setup(monkeypatch)
    try:
        first = _upload(
            service,
            "file-query-001",
            content=b"%PDF-1.7\nsynthetic file query first",
            file_name="first.pdf",
        )
        second = _upload(
            service,
            "file-query-002",
            content=b"%PDF-1.7\nsynthetic file query second",
            file_name="second.pdf",
        )
        query = FileQueryService(factory)

        first_page = query.list_page(ORGANIZATION_ID, None, 1)
        assert len(first_page.items) == 1
        assert first_page.next_cursor is not None
        second_page = query.list_page(ORGANIZATION_ID, first_page.next_cursor, 1)
        assert len(second_page.items) == 1
        assert second_page.next_cursor is None
        assert {first_page.items[0].file_id, second_page.items[0].file_id} == {
            first.data.file_id,
            second.data.file_id,
        }
        assert query.get(ORGANIZATION_ID, first.data.file_id).job_id == first.data.job_id

        outside_organization = UUID(int=ORGANIZATION_ID.int + 1)
        assert query.list_page(outside_organization, None, 20).items == ()
        with pytest.raises(AppError) as hidden:
            query.get(outside_organization, first.data.file_id)
        assert hidden.value.status_code == 404
        assert hidden.value.code == "RESOURCE_NOT_FOUND"

        with pytest.raises(AppError) as invalid_cursor:
            query.list_page(ORGANIZATION_ID, "not-canonical", 20)
        assert invalid_cursor.value.status_code == 422
        assert invalid_cursor.value.details == [{"field": "query.cursor", "reason": "invalid"}]
    finally:
        _clear_subjects(engine)
        engine.dispose()


def test_same_content_concurrency_stores_one_object_and_reuses_one_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service, storage = _setup(monkeypatch)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                executor.map(lambda key: _upload(service, key), ("file-race-001", "file-race-002"))
            )

        assert {result.data.reused for result in results} == {False, True}
        assert len({result.data.file_id for result in results}) == 1
        assert len({result.data.job_id for result in results}) == 1
        assert storage.put_count == 1
        with factory() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(FileRecord)
                    .where(FileRecord.organization_id == ORGANIZATION_ID)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AsyncJob)
                    .where(AsyncJob.organization_id == ORGANIZATION_ID)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecord)
                    .where(IdempotencyRecord.organization_id == ORGANIZATION_ID)
                )
                == 2
            )
    finally:
        _clear_subjects(engine)
        engine.dispose()


def test_post_storage_transaction_failure_compensates_and_rolls_back_every_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service, storage = _setup(monkeypatch)
    monkeypatch.setattr(
        OperationLogRepository,
        "append",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic DB failure")),
    )
    try:
        with pytest.raises(RuntimeError, match="synthetic DB failure"):
            _upload(service, "file-rollback-001")

        assert storage.put_count == 1
        assert storage.delete_count == 1
        assert storage.objects == {}
        with factory() as session:
            for model in (FileRecord, AsyncJob, IdempotencyRecord, OutboxEvent, OperationLog):
                assert session.scalar(select(func.count()).select_from(model)) == 0
    finally:
        _clear_subjects(engine)
        engine.dispose()


def test_same_content_with_changed_classification_is_rejected_without_touching_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _factory, service, storage = _setup(monkeypatch)
    try:
        created = _upload(service, "file-classify-001")
        invoice_intent = FileUploadIntent(intended_business_type=IntendedBusinessType.INVOICE)
        with pytest.raises(AppError) as captured:
            service.upload(
                _actor(),
                invoice_intent,
                file_name="invoice.pdf",
                declared_mime="application/pdf",
                stream=BytesIO(PDF_CONTENT),
                idempotency_key="file-classify-002",
                trace_id=uuid4(),
            )

        assert created.data.reused is False
        assert captured.value.code == "FILE_CLASSIFICATION_CONFLICT"
        assert storage.put_count == 1
        assert storage.delete_count == 0
        assert tuple(storage.objects.values()) == (PDF_CONTENT,)
    finally:
        _clear_subjects(engine)
        engine.dispose()
