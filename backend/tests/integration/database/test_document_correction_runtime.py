from __future__ import annotations

import io
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.models.document_processing import DocumentBlock, DocumentPage, DocumentParseVersion
from app.models.documents import FileRecord
from app.models.knowledge import DocumentBlockCorrection, DocumentMarkdownVersion
from app.models.reliability import AsyncJob, AsyncJobStep, IdempotencyRecord, OutboxEvent
from app.repositories.job_runtime import JobRuntimeRepository, OutboxClaim
from app.schemas.document_corrections import (
    DocumentBlockCorrectionRequest,
    DocumentParseActivationRequest,
    SecurityRevalidationRequest,
)
from app.schemas.files import FileArchiveRequest
from app.services.auth import AuthenticatedActor
from app.services.document_correction import DocumentCorrectionService
from app.services.job_recovery import FileJobRecovery
from tests.integration.database.test_file_intake_service import (
    _actor,
    _clear_subjects,
    _intent,
    _setup,
)
from tests.integration.database.test_file_job_executor import (
    _CleanScanner,
    _clear_document_subjects,
    _dispatch_pending,
    _executor,
    _management_service,
    _RuntimeStorage,
    _text_pdf,
)
from tests.integration.database.test_migrations import expire_active_job_lease

pytestmark = pytest.mark.integration


def _correction_actor() -> AuthenticatedActor:
    base = _actor()
    return AuthenticatedActor(
        user_id=base.user_id,
        organization_id=base.organization_id,
        session_id=base.session_id,
        roles=("finance_reviewer",),
        permissions=("files.manage", "files.read"),
    )


def _correction_payload(
    source_parse_version_id: UUID,
    *,
    text: str,
) -> DocumentBlockCorrectionRequest:
    return DocumentBlockCorrectionRequest.model_validate(
        {
            "field_name": "text_content",
            "after_value": text,
            "reason": "修正合成测试文本",
            "source_parse_version_id": str(source_parse_version_id),
        }
    )


def _dispatch_target(factory: sessionmaker[Session], job_id: UUID) -> OutboxClaim:
    with factory.begin() as session:
        repository = JobRuntimeRepository(session)
        while True:
            claim = repository.claim_next_outbox()
            assert claim is not None
            assert repository.mark_outbox_published(claim)
            if claim.job.id == job_id:
                return claim


def _claim_target_for_failure(
    factory: sessionmaker[Session],
    job_id: UUID,
) -> OutboxClaim:
    with factory.begin() as session:
        repository = JobRuntimeRepository(session)
        while True:
            claim = repository.claim_next_outbox()
            assert claim is not None
            if claim.job.id == job_id:
                return claim
            assert repository.mark_outbox_published(claim)


def test_manual_correction_snapshot_is_immutable_and_requires_independent_activation(
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
            idempotency_key="document-correction-source-001",
            trace_id=uuid4(),
        )
        file_id = uploaded.data.file_id
        source_event = _dispatch_pending(factory, uploaded.data.job_id)
        runtime_storage = _RuntimeStorage(quarantine)
        executor = _executor(factory, runtime_storage, _CleanScanner())
        assert (
            executor.execute(
                job_id=uploaded.data.job_id,
                event_id=source_event.event_id,
                event_schema_version=source_event.event_version,
                worker_id="document-correction-source-worker",
            ).outcome
            == "succeeded"
        )

        with factory() as session:
            source = session.scalar(
                select(DocumentParseVersion).where(
                    DocumentParseVersion.file_id == file_id,
                    DocumentParseVersion.status == "active",
                )
            )
            assert source is not None
            source_id = source.id
            source_blocks = tuple(
                session.scalars(
                    select(DocumentBlock)
                    .where(DocumentBlock.parse_version_id == source.id)
                    .order_by(DocumentBlock.block_index)
                ).all()
            )
            assert len(source_blocks) == 2
            first_block_id = source_blocks[0].id
            second_block_id = source_blocks[1].id
            original_first_text = source_blocks[0].text_content

        service = DocumentCorrectionService(factory)
        actor = _correction_actor()
        first_page = service.list_blocks(actor, file_id, None, 1)
        assert first_page.file_id == file_id
        assert first_page.business_type == "contract"
        assert first_page.parse_version_id == source_id
        assert [item.block_id for item in first_page.items] == [first_block_id]
        assert first_page.next_cursor is not None
        second_page = service.list_blocks(actor, file_id, first_page.next_cursor, 1)
        assert [item.block_id for item in second_page.items] == [second_block_id]
        assert second_page.next_cursor is None
        admin_page = service.list_blocks(
            AuthenticatedActor(
                actor.user_id,
                actor.organization_id,
                actor.session_id,
                ("system_admin",),
                ("system.configure",),
            ),
            file_id,
            None,
            1,
        )
        assert admin_page.parse_version_id == source_id
        with pytest.raises(AppError) as invalid_cursor:
            service.list_blocks(actor, file_id, first_page.next_cursor + "=", 1)
        assert (invalid_cursor.value.status_code, invalid_cursor.value.code) == (
            422,
            "VALIDATION_ERROR",
        )
        with pytest.raises(AppError) as wrong_role:
            service.list_blocks(
                AuthenticatedActor(
                    actor.user_id,
                    actor.organization_id,
                    actor.session_id,
                    ("audit_reviewer",),
                    ("files.manage",),
                ),
                file_id,
                None,
                1,
            )
        assert (wrong_role.value.status_code, wrong_role.value.code) == (403, "AUTH_FORBIDDEN")

        first = service.correct_block(
            actor,
            first_block_id,
            _correction_payload(source_id, text="Contract Number C-002"),
            "document-correction-001",
            uuid4(),
        )
        replay = service.correct_block(
            actor,
            first_block_id,
            _correction_payload(source_id, text="Contract Number C-002"),
            "document-correction-001",
            uuid4(),
        )
        assert first.replayed is False
        assert replay.replayed is True
        assert replay.data == first.data

        with factory() as session:
            candidate = session.get(
                DocumentParseVersion,
                first.data.result_parse_version_id,
            )
            job = session.get(AsyncJob, first.data.job_id)
            correction = session.get(DocumentBlockCorrection, first.data.correction_id)
            assert candidate is not None
            assert candidate.status == "queued"
            assert candidate.parent_version_id == source_id
            assert candidate.source_type == "manual_correction"
            assert job is not None
            assert job.status == "queued"
            assert job.resource_id == candidate.id
            assert set(job.input_json) == {
                "file_id",
                "source_parse_version_id",
                "result_parse_version_id",
                "correction_id",
                "handler_code_version",
                "handler_registry_version",
                "handler_registry_hash",
            }
            assert original_first_text not in str(job.input_json)
            assert "修正合成测试文本" not in str(job.input_json)
            assert correction is not None
            assert correction.result_parse_version_id == candidate.id
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DocumentPage)
                    .where(DocumentPage.parse_version_id == candidate.id)
                )
                == 0
            )

        first_event = _dispatch_target(factory, first.data.job_id)
        completed = executor.execute(
            job_id=first.data.job_id,
            event_id=first_event.event_id,
            event_schema_version=first_event.event_version,
            worker_id="document-correction-worker-1",
        )
        assert completed.outcome == "succeeded"

        second = service.correct_block(
            actor,
            second_block_id,
            _correction_payload(source_id, text="Amount 2000"),
            "document-correction-002",
            uuid4(),
        )
        second_event = _dispatch_target(factory, second.data.job_id)
        assert (
            executor.execute(
                job_id=second.data.job_id,
                event_id=second_event.event_id,
                event_schema_version=second_event.event_version,
                worker_id="document-correction-worker-2",
            ).outcome
            == "succeeded"
        )

        with factory() as session:
            candidate = session.get(DocumentParseVersion, first.data.result_parse_version_id)
            source = session.get(DocumentParseVersion, source_id)
            assert candidate is not None and candidate.status == "succeeded"
            assert source is not None and source.status == "active"
            cloned_blocks = tuple(
                session.scalars(
                    select(DocumentBlock)
                    .where(DocumentBlock.parse_version_id == candidate.id)
                    .order_by(DocumentBlock.block_index)
                ).all()
            )
            assert len(cloned_blocks) == 2
            assert cloned_blocks[0].text_content == "Contract Number C-002"
            assert cloned_blocks[1].text_content == source_blocks[1].text_content
            assert cloned_blocks[0].id != first_block_id
            source_first = session.get(DocumentBlock, first_block_id)
            assert source_first is not None
            assert source_first.text_content == original_first_text
            step = session.scalar(
                select(AsyncJobStep).where(AsyncJobStep.job_id == first.data.job_id)
            )
            assert step is not None
            assert (step.step_code, step.status) == ("snapshot_rebuild", "succeeded")

        activated = service.activate_parse(
            actor,
            first.data.result_parse_version_id,
            DocumentParseActivationRequest(reason="采用已核对的合成修正"),
            "document-activation-001",
            uuid4(),
        )
        activation_replay = service.activate_parse(
            actor,
            first.data.result_parse_version_id,
            DocumentParseActivationRequest(reason="采用已核对的合成修正"),
            "document-activation-001",
            uuid4(),
        )
        assert activated.replayed is False
        assert activation_replay.replayed is True
        assert activation_replay.data == activated.data
        assert activated.data.superseded_version_id == source_id

        with pytest.raises(AppError) as stale_cursor:
            service.list_blocks(actor, file_id, first_page.next_cursor, 1)
        assert (stale_cursor.value.status_code, stale_cursor.value.code) == (
            409,
            "PARSE_VERSION_CHANGED",
        )

        with pytest.raises(AppError) as stale:
            service.activate_parse(
                actor,
                second.data.result_parse_version_id,
                DocumentParseActivationRequest(reason="模拟过期 sibling"),
                "document-activation-002",
                uuid4(),
            )
        assert (stale.value.status_code, stale.value.code) == (409, "PARSE_PARENT_STALE")

        before_counts: tuple[int, int]
        with factory() as session:
            source = session.get(DocumentParseVersion, source_id)
            current = session.get(DocumentParseVersion, first.data.result_parse_version_id)
            stale_candidate = session.get(
                DocumentParseVersion,
                second.data.result_parse_version_id,
            )
            assert source is not None and source.status == "superseded"
            assert current is not None and current.status == "active"
            assert stale_candidate is not None and stale_candidate.status == "succeeded"
            active_markdown = session.scalar(
                select(DocumentMarkdownVersion).where(
                    DocumentMarkdownVersion.file_id == file_id,
                    DocumentMarkdownVersion.status == "active",
                )
            )
            assert active_markdown is not None
            assert active_markdown.parse_version_id == current.id
            before_counts = (
                session.scalar(select(func.count()).select_from(DocumentParseVersion)) or 0,
                session.scalar(select(func.count()).select_from(AsyncJob)) or 0,
            )

        with pytest.raises(AppError) as blocked:
            service.request_security_revalidation(
                AuthenticatedActor(
                    actor.user_id,
                    actor.organization_id,
                    actor.session_id,
                    ("system_admin",),
                    ("system.configure",),
                ),
                first.data.result_parse_version_id,
                SecurityRevalidationRequest(
                    reason="合成安全重评",
                    security_policy_version="asset-security-v1",
                    force_recheck=True,
                ),
                "document-security-revalidation-001",
                uuid4(),
            )
        assert (blocked.value.status_code, blocked.value.code) == (
            503,
            "SECURITY_REVALIDATION_CONFIGURATION_ERROR",
        )
        with factory() as session:
            assert before_counts == (
                session.scalar(select(func.count()).select_from(DocumentParseVersion)),
                session.scalar(select(func.count()).select_from(AsyncJob)),
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.aggregate_id == first.data.job_id)
                )
                == 1
            )

        with factory() as session:
            current_block_id = session.scalar(
                select(DocumentBlock.id)
                .where(DocumentBlock.parse_version_id == first.data.result_parse_version_id)
                .order_by(DocumentBlock.block_index)
                .limit(1)
            )
            assert current_block_id is not None

        dispatch_failed = service.correct_block(
            actor,
            current_block_id,
            _correction_payload(first.data.result_parse_version_id, text="Contract Number C-003"),
            "document-correction-dispatch-failure-001",
            uuid4(),
        )
        failed_claim = _claim_target_for_failure(factory, dispatch_failed.data.job_id)
        with factory.begin() as session:
            assert JobRuntimeRepository(session).mark_outbox_failure(
                failed_claim,
                error_code="SERIALIZATION_FAILED",
                broker_called=False,
            )
        with factory() as session:
            failed_job = session.get(AsyncJob, dispatch_failed.data.job_id)
            failed_parse = session.get(
                DocumentParseVersion,
                dispatch_failed.data.result_parse_version_id,
            )
            assert failed_job is not None and failed_job.status == "failed"
            assert failed_job.error_code == "JOB_DISPATCH_FAILED"
            assert failed_parse is not None and failed_parse.status == "failed"
            assert failed_parse.error_code == "JOB_DISPATCH_FAILED"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AsyncJobStep)
                    .where(AsyncJobStep.job_id == failed_job.id)
                )
                == 0
            )

        lease_lost = service.correct_block(
            actor,
            current_block_id,
            _correction_payload(first.data.result_parse_version_id, text="Contract Number C-004"),
            "document-correction-lease-lost-001",
            uuid4(),
        )
        lease_event = _dispatch_target(factory, lease_lost.data.job_id)
        with factory.begin() as session:
            claimed = JobRuntimeRepository(session).claim_job(
                job_id=lease_lost.data.job_id,
                event_id=lease_event.event_id,
                event_schema_version=lease_event.event_version,
                worker_id="document-correction-lost-worker",
                start_step_seq=1,
            )
            assert claimed is not None
        expire_active_job_lease(engine.url, str(lease_lost.data.job_id))
        recovery = FileJobRecovery(factory, executor).recover_expired_once(
            worker_id="document-correction-recovery-worker"
        )
        assert (recovery.outcome, recovery.job_id) == (
            "exhausted",
            str(lease_lost.data.job_id),
        )
        with factory() as session:
            exhausted_job = session.get(AsyncJob, lease_lost.data.job_id)
            exhausted_parse = session.get(
                DocumentParseVersion,
                lease_lost.data.result_parse_version_id,
            )
            assert exhausted_job is not None and exhausted_job.status == "failed"
            assert exhausted_job.error_code == "WORKER_LOST"
            assert exhausted_parse is not None and exhausted_parse.status == "failed"
            assert exhausted_parse.error_code == "WORKER_LOST"

            file = session.get(FileRecord, file_id)
            assert file is not None
            file_row_version = str(file.row_version)

        archived = _management_service(factory, runtime_storage.originals).archive(
            actor,
            file_id,
            FileArchiveRequest(row_version=file_row_version, reason="验证归档后版本写入门禁"),
            "document-correction-archive-001",
            uuid4(),
        )
        assert archived.data.status.value == "archived"

        with pytest.raises(AppError) as archived_read:
            service.list_blocks(actor, file_id, None, 1)
        assert (archived_read.value.status_code, archived_read.value.code) == (
            409,
            "FILE_STATE_CONFLICT",
        )

        with factory() as session:
            archived_counts = (
                session.scalar(select(func.count()).select_from(DocumentParseVersion)) or 0,
                session.scalar(select(func.count()).select_from(DocumentBlockCorrection)) or 0,
                session.scalar(select(func.count()).select_from(AsyncJob)) or 0,
                session.scalar(select(func.count()).select_from(OutboxEvent)) or 0,
                session.scalar(select(func.count()).select_from(IdempotencyRecord)) or 0,
            )

        archived_replay = service.activate_parse(
            actor,
            first.data.result_parse_version_id,
            DocumentParseActivationRequest(reason="采用已核对的合成修正"),
            "document-activation-001",
            uuid4(),
        )
        assert archived_replay.replayed is True
        assert archived_replay.data == activated.data

        with pytest.raises(AppError) as archived_correction:
            service.correct_block(
                actor,
                current_block_id,
                _correction_payload(
                    first.data.result_parse_version_id,
                    text="Contract Number C-005",
                ),
                "document-correction-archived-001",
                uuid4(),
            )
        assert (archived_correction.value.status_code, archived_correction.value.code) == (
            409,
            "FILE_STATE_CONFLICT",
        )

        with pytest.raises(AppError) as archived_activation:
            service.activate_parse(
                actor,
                second.data.result_parse_version_id,
                DocumentParseActivationRequest(reason="归档后不得激活候选"),
                "document-activation-archived-001",
                uuid4(),
            )
        assert (archived_activation.value.status_code, archived_activation.value.code) == (
            409,
            "FILE_STATE_CONFLICT",
        )

        with pytest.raises(AppError) as archived_revalidation:
            service.request_security_revalidation(
                AuthenticatedActor(
                    actor.user_id,
                    actor.organization_id,
                    actor.session_id,
                    ("system_admin",),
                    ("system.configure",),
                ),
                first.data.result_parse_version_id,
                SecurityRevalidationRequest(
                    reason="归档后不得重评",
                    security_policy_version="asset-security-v1",
                    force_recheck=True,
                ),
                "document-revalidation-archived-001",
                uuid4(),
            )
        assert (archived_revalidation.value.status_code, archived_revalidation.value.code) == (
            409,
            "FILE_STATE_CONFLICT",
        )

        with factory() as session:
            assert archived_counts == (
                session.scalar(select(func.count()).select_from(DocumentParseVersion)),
                session.scalar(select(func.count()).select_from(DocumentBlockCorrection)),
                session.scalar(select(func.count()).select_from(AsyncJob)),
                session.scalar(select(func.count()).select_from(OutboxEvent)),
                session.scalar(select(func.count()).select_from(IdempotencyRecord)),
            )
    finally:
        if file_id is not None:
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()
