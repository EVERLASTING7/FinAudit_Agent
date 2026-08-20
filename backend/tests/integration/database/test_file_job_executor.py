from __future__ import annotations

import hashlib
import io
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.malware_scanner import MalwareScanner, ScanResult
from app.adapters.minio_file_runtime import FileStorageError, StoredFileObject
from app.adapters.minio_original_storage import OriginalObjectLocator, OriginalStorageError
from app.adapters.ocr import NotConfiguredOcrEngine
from app.core.config import Settings
from app.models.document_processing import DocumentBlock, DocumentPage, DocumentParseVersion
from app.models.documents import FileRecord
from app.models.knowledge import (
    DocumentMarkdownVersion,
    MarkdownSourceMapping,
    MarkdownValidationResult,
)
from app.models.operations import OperationLog
from app.models.reliability import AsyncJob, AsyncJobStep, OutboxEvent
from app.repositories.job_runtime import JobRuntimeRepository, OutboxClaim
from app.repositories.markdown_write import MarkdownWriteRepository
from app.schemas.files import FileArchiveRequest, FileRetryRequest
from app.services.auth import AuthenticatedActor
from app.services.document_parser import DocumentParser
from app.services.file_job_executor import FileJobExecutor
from app.services.file_management import FileManagementService
from app.services.job_recovery import FileJobRecovery
from tests.integration.database.test_file_intake_service import (
    MemoryQuarantineStorage,
    _actor,
    _clear_subjects,
    _intent,
    _setup,
)

pytestmark = pytest.mark.integration


class _CleanScanner:
    def scan(self, payload: bytes) -> ScanResult:
        assert payload.startswith(b"%PDF")
        return ScanResult(
            outcome="clean",
            scanner_invoked=True,
            adapter_code="synthetic-clean-v1",
            scanner_version="synthetic-1",
            definition_version="definitions-1",
        )


class _UnavailableScanner:
    def scan(self, payload: bytes) -> ScanResult:
        assert payload.startswith(b"%PDF")
        return ScanResult(
            outcome="scan_failed",
            scanner_invoked=True,
            adapter_code="synthetic-unavailable-v1",
            scanner_version=None,
            definition_version=None,
            error_code="DEPENDENCY_UNAVAILABLE",
        )


class _RuntimeStorage:
    def __init__(self, quarantine: MemoryQuarantineStorage) -> None:
        self.quarantine = quarantine
        self.originals: dict[str, bytes] = {}
        self.promotion_count = 0
        self.compensation_count = 0

    def read_verified(
        self,
        *,
        bucket_name: str,
        object_key: str,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes:
        objects = self.quarantine.objects if bucket_name == "quarantine" else self.originals
        payload = objects.get(object_key)
        if (
            payload is None
            or expected_size <= 0
            or expected_size > max_bytes
            or len(payload) != expected_size
            or hashlib.sha256(payload).hexdigest() != expected_sha256
        ):
            raise FileStorageError
        return payload

    def promote_clean(
        self,
        *,
        source_bucket: str,
        source_key: str,
        expected_size: int,
        expected_sha256: str,
    ) -> StoredFileObject:
        payload = self.read_verified(
            bucket_name=source_bucket,
            object_key=source_key,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            max_bytes=expected_size,
        )
        self.originals[source_key] = payload
        self.promotion_count += 1
        return StoredFileObject("originals", source_key)

    def delete_quarantine_after_commit(self, object_key: str) -> None:
        self.quarantine.objects.pop(object_key, None)

    def delete_original_compensation(self, object_key: str) -> None:
        self.originals.pop(object_key, None)
        self.compensation_count += 1


class _OriginalReader:
    def __init__(self, originals: dict[str, bytes]) -> None:
        self._originals = originals

    def read_verified(
        self,
        locator: OriginalObjectLocator,
        *,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes:
        payload = self._originals.get(locator.object_key)
        if (
            locator.bucket_name != "originals"
            or payload is None
            or len(payload) != expected_size
            or len(payload) > max_bytes
            or hashlib.sha256(payload).hexdigest() != expected_sha256
        ):
            raise OriginalStorageError
        return payload


def _manager_actor() -> AuthenticatedActor:
    actor = _actor()
    return AuthenticatedActor(
        user_id=actor.user_id,
        organization_id=actor.organization_id,
        session_id=actor.session_id,
        roles=actor.roles,
        permissions=("files.manage", "files.read", "files.upload"),
    )


def _management_service(
    factory: sessionmaker[Session],
    originals: dict[str, bytes],
) -> FileManagementService:
    settings = cast(Settings, SimpleNamespace(max_upload_size_mb=1))
    return FileManagementService(factory, _OriginalReader(originals), settings)


def _text_pdf() -> bytes:
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=(300, 300), invariant=1)
    document.drawString(20, 250, "Contract Number C-001")
    document.drawString(20, 230, "Amount 1000")
    document.save()
    return output.getvalue()


def _clear_document_subjects(engine: Engine, file_id: UUID) -> None:
    tables = (
        "markdown_validation_results",
        "markdown_source_mappings",
        "document_markdown_versions",
        "document_block_corrections",
        "document_content_exclusions",
        "document_blocks",
        "document_assets",
        "document_pages",
        "document_parse_versions",
    )
    with engine.begin() as connection:
        for table_name in tables:
            connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
        try:
            connection.execute(
                text(
                    "DELETE FROM markdown_validation_results WHERE markdown_version_id IN "
                    "(SELECT id FROM document_markdown_versions WHERE file_id=:file_id)"
                ),
                {"file_id": file_id},
            )
            connection.execute(
                text(
                    "DELETE FROM markdown_source_mappings WHERE markdown_version_id IN "
                    "(SELECT id FROM document_markdown_versions WHERE file_id=:file_id)"
                ),
                {"file_id": file_id},
            )
            connection.execute(
                text("DELETE FROM document_markdown_versions WHERE file_id=:file_id"),
                {"file_id": file_id},
            )
            connection.execute(
                text(
                    "DELETE FROM document_block_corrections "
                    "WHERE source_parse_version_id IN "
                    "(SELECT id FROM document_parse_versions WHERE file_id=:file_id) "
                    "OR result_parse_version_id IN "
                    "(SELECT id FROM document_parse_versions WHERE file_id=:file_id)"
                ),
                {"file_id": file_id},
            )
            for table_name in tables[4:-1]:
                connection.execute(
                    text(
                        f"DELETE FROM {table_name} WHERE parse_version_id IN "
                        "(SELECT id FROM document_parse_versions WHERE file_id=:file_id)"
                    ),
                    {"file_id": file_id},
                )
            connection.execute(
                text("DELETE FROM document_parse_versions WHERE file_id=:file_id"),
                {"file_id": file_id},
            )
        finally:
            for table_name in reversed(tables):
                connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))


def _dispatch_pending(factory: sessionmaker[Session], job_id: UUID) -> OutboxClaim:
    with factory.begin() as session:
        repository = JobRuntimeRepository(session)
        claim = repository.claim_next_outbox()
        assert claim is not None
        assert claim.job.id == job_id
        assert repository.mark_outbox_published(claim)
        return claim


def _executor(
    factory: sessionmaker[Session],
    storage: _RuntimeStorage,
    scanner: MalwareScanner,
) -> FileJobExecutor:
    return FileJobExecutor(
        factory,
        storage,
        scanner,
        DocumentParser(ocr_engine=NotConfiguredOcrEngine(), pdf_renderer=None),
        max_file_bytes=1024 * 1024,
    )


def test_upload_dispatch_scan_promote_parse_and_duplicate_delivery_close_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    file_id: UUID | None = None
    try:
        payload = _text_pdf()
        uploaded = intake.upload(
            _actor(),
            _intent(),
            file_name="contract.pdf",
            declared_mime="application/pdf",
            stream=io.BytesIO(payload),
            idempotency_key="file-job-e2e-001",
            trace_id=uuid4(),
        )
        file_id = uploaded.data.file_id

        outbox_claim = _dispatch_pending(factory, uploaded.data.job_id)

        runtime_storage = _RuntimeStorage(quarantine)
        executor = _executor(factory, runtime_storage, _CleanScanner())
        completed = executor.execute(
            job_id=uploaded.data.job_id,
            event_id=outbox_claim.event_id,
            event_schema_version=outbox_claim.event_version,
            worker_id="integration-worker-1",
        )
        duplicate = executor.execute(
            job_id=uploaded.data.job_id,
            event_id=outbox_claim.event_id,
            event_schema_version=outbox_claim.event_version,
            worker_id="integration-worker-2",
        )

        assert completed.outcome == "succeeded"
        assert duplicate.outcome == "duplicate_or_stale"
        assert runtime_storage.promotion_count == 1
        assert runtime_storage.compensation_count == 0
        assert quarantine.objects == {}
        assert tuple(runtime_storage.originals.values()) == (payload,)

        with factory() as session:
            file = session.get(FileRecord, file_id)
            job = session.get(AsyncJob, uploaded.data.job_id)
            event = session.get(OutboxEvent, outbox_claim.outbox_id)
            assert file is not None
            assert file.status == "stored"
            assert file.security_scan_status == "clean"
            assert file.original_minio_bucket == "originals"
            assert job is not None
            assert job.status == "succeeded"
            assert job.stage == "markdown"
            assert job.attempt_no == 1
            assert event is not None
            assert event.status == "published"

            steps = session.scalars(
                select(AsyncJobStep)
                .where(AsyncJobStep.job_id == job.id)
                .order_by(AsyncJobStep.step_seq)
            ).all()
            assert [(step.step_code, step.status) for step in steps] == [
                ("scan", "succeeded"),
                ("parse", "succeeded"),
                ("markdown", "succeeded"),
            ]
            versions = session.scalars(
                select(DocumentParseVersion).where(DocumentParseVersion.file_id == file_id)
            ).all()
            assert len(versions) == 1
            assert versions[0].status == "active"
            assert versions[0].page_count == 1
            assert session.scalar(select(func.count()).select_from(DocumentPage)) == 1
            stored_blocks = session.scalars(
                select(DocumentBlock).order_by(DocumentBlock.block_index)
            ).all()
            assert len(stored_blocks) == 2
            assert all(block.bbox_json is None for block in stored_blocks)
            assert all(
                block.coordinate_unavailable_reason == "extractor_not_available"
                for block in stored_blocks
            )
            markdown = session.scalar(
                select(DocumentMarkdownVersion).where(DocumentMarkdownVersion.file_id == file_id)
            )
            assert markdown is not None
            assert markdown.status == "active"
            mappings = session.scalars(
                select(MarkdownSourceMapping)
                .where(MarkdownSourceMapping.markdown_version_id == markdown.id)
                .order_by(MarkdownSourceMapping.md_char_start)
            ).all()
            assert len(mappings) == 2
            assert markdown.quality_summary_json == {
                "evidence_source_mapping": {"covered": 2, "total": 2},
                "valid_structure_block": {"covered": 2, "total": 2},
            }
            token_types = markdown.document_metadata_json["parser_token_types"]
            assert not any(
                token_type.startswith(("html_", "link_", "image")) for token_type in token_types
            )
            for index, mapping in enumerate(mappings):
                mapped_text = markdown.markdown_text[mapping.md_char_start : mapping.md_char_end]
                assert mapped_text.strip()
                assert mapping.md_line_start == (
                    markdown.markdown_text[: mapping.md_char_start].count("\n") + 1
                )
                assert mapping.md_line_end == mapping.md_line_start + mapped_text.count("\n")
                assert mapping.coverage_status == "full"
                if index:
                    previous = mappings[index - 1]
                    assert (
                        markdown.markdown_text[previous.md_char_end : mapping.md_char_start]
                        == "\n\n"
                    )
            validation = session.scalar(
                select(MarkdownValidationResult).where(
                    MarkdownValidationResult.markdown_version_id == markdown.id
                )
            )
            assert validation is not None
            assert (
                validation.validator_code,
                validation.issue_code,
                validation.is_blocking,
                validation.details_json,
            ) == (
                "safe-commonmark-gfm-table",
                "PASS",
                False,
                {"raw_html": False, "external_resources": False},
            )

            reused = MarkdownWriteRepository(session).generate_and_activate(
                organization_id=file.organization_id,
                file_id=file.id,
                parse_version_id=versions[0].id,
                trace_id=uuid4(),
                actor_id=_actor().user_id,
            )
            assert reused.outcome == "reused"
            assert reused.markdown_version_id == markdown.id
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DocumentMarkdownVersion)
                    .where(DocumentMarkdownVersion.file_id == file.id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(MarkdownSourceMapping)
                    .where(MarkdownSourceMapping.markdown_version_id == markdown.id)
                )
                == 2
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(MarkdownValidationResult)
                    .where(MarkdownValidationResult.markdown_version_id == markdown.id)
                )
                == 1
            )
    finally:
        if file_id is not None:
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()


def test_completed_file_can_be_previewed_and_irreversibly_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    file_id: UUID | None = None
    try:
        payload = _text_pdf()
        uploaded = intake.upload(
            _actor(),
            _intent(),
            file_name="contract.pdf",
            declared_mime="application/pdf",
            stream=io.BytesIO(payload),
            idempotency_key="file-manage-preview-001",
            trace_id=uuid4(),
        )
        file_id = uploaded.data.file_id
        event = _dispatch_pending(factory, uploaded.data.job_id)
        runtime_storage = _RuntimeStorage(quarantine)
        completed = _executor(factory, runtime_storage, _CleanScanner()).execute(
            job_id=uploaded.data.job_id,
            event_id=event.event_id,
            event_schema_version=event.event_version,
            worker_id="integration-worker-file-manage",
        )
        assert completed.outcome == "succeeded"

        service = _management_service(factory, runtime_storage.originals)
        actor = _manager_actor()
        original = service.preview_original(actor, file_id, uuid4())
        text_preview = service.text_preview(actor, file_id, 1_000, uuid4())
        with factory() as session:
            source = session.get(FileRecord, file_id)
            assert source is not None
            row_version = str(source.row_version)
        archived = service.archive(
            actor,
            file_id,
            FileArchiveRequest(row_version=row_version, reason="测试完成后归档"),
            "file-manage-archive-001",
            uuid4(),
        )
        replay = service.archive(
            actor,
            file_id,
            FileArchiveRequest(row_version=row_version, reason="测试完成后归档"),
            "file-manage-archive-001",
            uuid4(),
        )

        assert original.content == payload
        assert original.mime_type == "application/pdf"
        assert text_preview.file_id == file_id
        assert "Contract Number C\\-001" in text_preview.markdown_text
        assert text_preview.char_count == len(text_preview.markdown_text)
        assert archived.data.status.value == "archived"
        assert archived.replayed is False
        assert replay.data == archived.data
        assert replay.replayed is True
        with factory() as session:
            source = session.get(FileRecord, file_id)
            assert source is not None
            assert source.status == "archived"
            assert source.archived_at is not None
            assert source.original_minio_object_key in runtime_storage.originals
            action_codes = tuple(
                session.scalars(
                    select(OperationLog.action_code)
                    .where(OperationLog.resource_id == file_id)
                    .order_by(OperationLog.created_at, OperationLog.id)
                ).all()
            )
            assert action_codes[-3:] == (
                "files.previewed",
                "files.previewed",
                "files.archived",
            )
    finally:
        if file_id is not None:
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()


def test_authorized_manual_retry_reuses_failed_file_job_and_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    file_id: UUID | None = None
    try:
        payload = _text_pdf()
        uploaded = intake.upload(
            _actor(),
            _intent(),
            file_name="contract.pdf",
            declared_mime="application/pdf",
            stream=io.BytesIO(payload),
            idempotency_key="file-manage-retry-source-001",
            trace_id=uuid4(),
        )
        file_id = uploaded.data.file_id
        first_event = _dispatch_pending(factory, uploaded.data.job_id)
        runtime_storage = _RuntimeStorage(quarantine)
        failed = _executor(factory, runtime_storage, _UnavailableScanner()).execute(
            job_id=uploaded.data.job_id,
            event_id=first_event.event_id,
            event_schema_version=first_event.event_version,
            worker_id="integration-worker-manual-failure",
        )
        assert failed.outcome == "failed"
        with factory() as session:
            source = session.get(FileRecord, file_id)
            failed_job = session.get(AsyncJob, uploaded.data.job_id)
            assert source is not None
            assert failed_job is not None
            row_version = str(source.row_version)
            job_row_version = str(failed_job.row_version)

        service = _management_service(factory, runtime_storage.originals)
        retried = service.retry(
            _manager_actor(),
            file_id,
            FileRetryRequest(
                file_row_version=row_version,
                job_id=uploaded.data.job_id,
                job_row_version=job_row_version,
                reason="人工确认依赖恢复后重试",
            ),
            "file-manage-retry-001",
            uuid4(),
        )
        replay = service.retry(
            _manager_actor(),
            file_id,
            FileRetryRequest(
                file_row_version=row_version,
                job_id=uploaded.data.job_id,
                job_row_version=job_row_version,
                reason="人工确认依赖恢复后重试",
            ),
            "file-manage-retry-001",
            uuid4(),
        )

        assert retried.data.job_id == uploaded.data.job_id
        assert retried.data.job_status == "queued"
        assert retried.replayed is False
        assert replay.data == retried.data
        assert replay.replayed is True
        with factory() as session:
            jobs = session.scalars(select(AsyncJob).where(AsyncJob.resource_id == file_id)).all()
            events = session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.aggregate_id == uploaded.data.job_id)
                .order_by(OutboxEvent.event_sequence)
            ).all()
            assert len(jobs) == 1
            assert jobs[0].status == "queued"
            assert jobs[0].error_code is None
            assert [(event.event_sequence, event.status) for event in events] == [
                (1, "published"),
                (2, "pending"),
            ]
            log = session.scalar(
                select(OperationLog).where(
                    OperationLog.resource_id == file_id,
                    OperationLog.action_code == "files.retry_queued",
                )
            )
            assert log is not None
            assert log.change_summary_json["job_id"] == str(uploaded.data.job_id)
    finally:
        if file_id is not None:
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()


def test_retryable_scan_failure_requeues_new_outbox_and_completes_attempt_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    file_id: UUID | None = None
    try:
        payload = _text_pdf()
        uploaded = intake.upload(
            _actor(),
            _intent(),
            file_name="contract.pdf",
            declared_mime="application/pdf",
            stream=io.BytesIO(payload),
            idempotency_key="file-job-retry-001",
            trace_id=uuid4(),
        )
        file_id = uploaded.data.file_id
        first_event = _dispatch_pending(factory, uploaded.data.job_id)
        runtime_storage = _RuntimeStorage(quarantine)
        failed_executor = _executor(factory, runtime_storage, _UnavailableScanner())
        failed = failed_executor.execute(
            job_id=uploaded.data.job_id,
            event_id=first_event.event_id,
            event_schema_version=first_event.event_version,
            worker_id="integration-worker-failed",
        )
        assert failed.outcome == "failed"

        successful_executor = _executor(factory, runtime_storage, _CleanScanner())
        recovery = FileJobRecovery(factory, successful_executor)
        requeued = recovery.requeue_failed_once()
        assert requeued.outcome == "requeued"
        assert requeued.job_id == str(uploaded.data.job_id)
        second_event = _dispatch_pending(factory, uploaded.data.job_id)
        completed = successful_executor.execute(
            job_id=uploaded.data.job_id,
            event_id=second_event.event_id,
            event_schema_version=second_event.event_version,
            worker_id="integration-worker-retry",
        )
        assert completed.outcome == "succeeded"

        with factory() as session:
            file = session.get(FileRecord, file_id)
            job = session.get(AsyncJob, uploaded.data.job_id)
            steps = session.scalars(
                select(AsyncJobStep)
                .where(AsyncJobStep.job_id == uploaded.data.job_id)
                .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
            ).all()
            events = session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.aggregate_id == uploaded.data.job_id)
                .order_by(OutboxEvent.event_sequence)
            ).all()
            assert file is not None
            assert file.status == "stored"
            assert file.security_scan_status == "clean"
            assert job is not None
            assert job.status == "succeeded"
            assert job.attempt_no == 2
            assert [
                (step.attempt_no, step.step_code, step.status, step.error_code) for step in steps
            ] == [
                (1, "scan", "failed", "DEPENDENCY_UNAVAILABLE"),
                (2, "scan", "succeeded", None),
                (2, "parse", "succeeded", None),
                (2, "markdown", "succeeded", None),
            ]
            assert [(event.event_sequence, event.status) for event in events] == [
                (1, "published"),
                (2, "published"),
            ]
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DocumentParseVersion)
                    .where(DocumentParseVersion.file_id == file_id)
                )
                == 1
            )
    finally:
        if file_id is not None:
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()


def test_expired_markdown_attempt_reuses_committed_parse_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    file_id: UUID | None = None
    original_generate = MarkdownWriteRepository.generate_and_activate
    calls = 0

    def crash_once(self: MarkdownWriteRepository, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic worker crash")
        return original_generate(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(MarkdownWriteRepository, "generate_and_activate", crash_once)
    try:
        payload = _text_pdf()
        uploaded = intake.upload(
            _actor(),
            _intent(),
            file_name="contract.pdf",
            declared_mime="application/pdf",
            stream=io.BytesIO(payload),
            idempotency_key="file-job-markdown-recovery-001",
            trace_id=uuid4(),
        )
        file_id = uploaded.data.file_id
        event = _dispatch_pending(factory, uploaded.data.job_id)
        runtime_storage = _RuntimeStorage(quarantine)
        executor = _executor(factory, runtime_storage, _CleanScanner())

        with pytest.raises(RuntimeError, match="synthetic worker crash"):
            executor.execute(
                job_id=uploaded.data.job_id,
                event_id=event.event_id,
                event_schema_version=event.event_version,
                worker_id="integration-worker-crash",
            )

        with engine.begin() as connection:
            for table_name in ("async_jobs", "async_job_steps"):
                connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
            try:
                connection.execute(
                    text(
                        "WITH clock AS MATERIALIZED (SELECT clock_timestamp() AS t), "
                        "expired AS (UPDATE async_jobs SET "
                        "started_at=clock.t-interval '120 seconds', "
                        "heartbeat_at=clock.t-interval '90 seconds', "
                        "lease_expires_at=clock.t-interval '30 seconds' FROM clock "
                        "WHERE id=:job_id RETURNING id, attempt_no) "
                        "UPDATE async_job_steps SET "
                        "started_at=started_at-interval '120 seconds', "
                        "finished_at=CASE WHEN finished_at IS NULL THEN NULL "
                        "ELSE finished_at-interval '120 seconds' END "
                        "FROM clock, expired WHERE job_id=expired.id "
                        "AND async_job_steps.attempt_no=expired.attempt_no"
                    ),
                    {"job_id": uploaded.data.job_id},
                )
            finally:
                for table_name in reversed(("async_jobs", "async_job_steps")):
                    connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))

        recovered = FileJobRecovery(factory, executor).recover_expired_once(
            worker_id="maintenance-markdown-recovery"
        )
        assert recovered.outcome == "claimed_and_succeeded"
        assert calls == 2

        with factory() as session:
            job = session.get(AsyncJob, uploaded.data.job_id)
            assert job is not None
            assert job.status == "succeeded"
            assert job.attempt_no == 2
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DocumentParseVersion)
                    .where(DocumentParseVersion.file_id == file_id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DocumentMarkdownVersion)
                    .where(DocumentMarkdownVersion.file_id == file_id)
                )
                == 1
            )
            steps = session.scalars(
                select(AsyncJobStep)
                .where(AsyncJobStep.job_id == uploaded.data.job_id)
                .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
            ).all()
            assert [
                (step.attempt_no, step.step_code, step.status, step.error_code) for step in steps
            ] == [
                (1, "scan", "succeeded", None),
                (1, "parse", "succeeded", None),
                (1, "markdown", "failed", "LEASE_EXPIRED"),
                (2, "scan", "skipped", "STEP_SKIPPED"),
                (2, "parse", "succeeded", None),
                (2, "markdown", "succeeded", None),
            ]
    finally:
        if file_id is not None:
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()


def test_expired_worker_lease_is_reclaimed_and_old_attempt_is_fenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    file_id: UUID | None = None
    try:
        payload = _text_pdf()
        uploaded = intake.upload(
            _actor(),
            _intent(),
            file_name="contract.pdf",
            declared_mime="application/pdf",
            stream=io.BytesIO(payload),
            idempotency_key="file-job-lease-001",
            trace_id=uuid4(),
        )
        file_id = uploaded.data.file_id
        event = _dispatch_pending(factory, uploaded.data.job_id)
        with factory.begin() as session:
            claim = JobRuntimeRepository(session).claim_job(
                job_id=uploaded.data.job_id,
                event_id=event.event_id,
                event_schema_version=event.event_version,
                worker_id="crashed-worker",
                start_step_seq=1,
            )
            assert claim is not None

        with engine.begin() as connection:
            for table_name in ("async_jobs", "async_job_steps"):
                connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
            try:
                connection.execute(
                    text(
                        "WITH clock AS MATERIALIZED (SELECT clock_timestamp() AS t), "
                        "expired AS (UPDATE async_jobs SET "
                        "started_at=clock.t-interval '120 seconds', "
                        "heartbeat_at=clock.t-interval '90 seconds', "
                        "lease_expires_at=clock.t-interval '30 seconds' FROM clock "
                        "WHERE id=:job_id RETURNING id, attempt_no) "
                        "UPDATE async_job_steps SET started_at=clock.t-interval '120 seconds' "
                        "FROM clock, expired WHERE job_id=expired.id "
                        "AND async_job_steps.attempt_no=expired.attempt_no "
                        "AND async_job_steps.status='running'"
                    ),
                    {"job_id": uploaded.data.job_id},
                )
            finally:
                for table_name in reversed(("async_jobs", "async_job_steps")):
                    connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))

        runtime_storage = _RuntimeStorage(quarantine)
        recovery = FileJobRecovery(
            factory,
            _executor(factory, runtime_storage, _CleanScanner()),
        )
        recovered = recovery.recover_expired_once(worker_id="maintenance-recovery-1")
        assert recovered.outcome == "claimed_and_succeeded"
        assert recovered.job_id == str(uploaded.data.job_id)

        with factory() as session:
            job = session.get(AsyncJob, uploaded.data.job_id)
            steps = session.scalars(
                select(AsyncJobStep)
                .where(AsyncJobStep.job_id == uploaded.data.job_id)
                .order_by(AsyncJobStep.attempt_no, AsyncJobStep.step_seq)
            ).all()
            assert job is not None
            assert job.status == "succeeded"
            assert job.attempt_no == 2
            assert [
                (step.attempt_no, step.step_code, step.status, step.error_code) for step in steps
            ] == [
                (1, "scan", "failed", "LEASE_EXPIRED"),
                (2, "scan", "succeeded", None),
                (2, "parse", "succeeded", None),
                (2, "markdown", "succeeded", None),
            ]
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DocumentParseVersion)
                    .where(DocumentParseVersion.file_id == file_id)
                )
                == 1
            )
    finally:
        if file_id is not None:
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()
