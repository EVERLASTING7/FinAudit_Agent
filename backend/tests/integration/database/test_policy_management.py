from __future__ import annotations

import io
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.models.auth import User
from app.models.documents import FilePrimaryBusinessObject, KnowledgeBase
from app.models.knowledge import (
    ChunkingConfig,
    DocumentChunk,
    DocumentChunkSet,
    DocumentChunkSource,
    PolicyApprovalRecord,
    PolicyDocument,
)
from app.models.operations import OperationLog
from app.schemas.files import FileUploadIntent, IntendedBusinessType
from app.schemas.policies import PolicyCreateRequest, PolicyTransitionRequest
from app.services.auth import AuthenticatedActor
from app.services.knowledge_catalog import KnowledgeCatalogService
from app.services.policy_management import PolicyManagementService
from tests.integration.database.test_file_intake_service import (
    ACTOR_ID,
    ORGANIZATION_ID,
    _clear_subjects,
    _setup,
)
from tests.integration.database.test_file_job_executor import (
    _CleanScanner,
    _clear_document_subjects,
    _dispatch_pending,
    _executor,
    _RuntimeStorage,
)

pytestmark = pytest.mark.integration

KNOWLEDGE_BASE_ID = UUID("6e000000-0000-4000-8000-000000000101")
APPROVER_ID = UUID("6e000000-0000-4000-8000-000000000102")


def _policy_pdf() -> bytes:
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=(300, 300), invariant=1)
    document.drawString(20, 250, "Travel Reimbursement Policy")
    document.drawString(20, 230, "Receipts are required for expenses above 100.")
    document.save()
    return output.getvalue()


def _actor(user_id: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=user_id,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=("audit_reviewer",),
        permissions=(
            "files.read",
            "files.upload",
            "knowledge.use",
            "knowledge.submit",
            "knowledge.approve",
        ),
    )


def _seed_knowledge_subjects(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        session.add(
            User(
                id=APPROVER_ID,
                organization_id=ORGANIZATION_ID,
                username="policy.approver",
                display_name="制度独立批准人",
                password_hash="synthetic-password-hash",
                status="active",
                password_changed_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            KnowledgeBase(
                id=KNOWLEDGE_BASE_ID,
                organization_id=ORGANIZATION_ID,
                code="policy-kb",
                name="制度知识库",
                description=None,
                status="active",
                default_top_k=5,
                default_score_threshold=None,
                row_version=1,
                created_by=ACTOR_ID,
                updated_by=ACTOR_ID,
                deleted_at=None,
                deleted_by=None,
                delete_reason=None,
            )
        )


def _clear_policy_subjects(engine: Engine, policy_id: UUID) -> None:
    tables = (
        "document_chunk_sources",
        "document_chunks",
        "document_chunk_sets",
        "chunking_configs",
        "policy_approval_records",
        "file_primary_business_objects",
    )
    with engine.begin() as connection:
        for table_name in tables:
            connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
        try:
            connection.execute(
                text(
                    "DELETE FROM document_chunk_sources WHERE chunk_id IN "
                    "(SELECT id FROM document_chunks WHERE chunk_set_id IN "
                    "(SELECT id FROM document_chunk_sets WHERE policy_document_id=:policy_id))"
                ),
                {"policy_id": policy_id},
            )
            connection.execute(
                text(
                    "DELETE FROM document_chunks WHERE chunk_set_id IN "
                    "(SELECT id FROM document_chunk_sets WHERE policy_document_id=:policy_id)"
                ),
                {"policy_id": policy_id},
            )
            connection.execute(
                text("DELETE FROM document_chunk_sets WHERE policy_document_id=:policy_id"),
                {"policy_id": policy_id},
            )
            connection.execute(
                text("DELETE FROM policy_approval_records WHERE policy_document_id=:policy_id"),
                {"policy_id": policy_id},
            )
            connection.execute(
                text(
                    "DELETE FROM file_primary_business_objects WHERE policy_document_id=:policy_id"
                ),
                {"policy_id": policy_id},
            )
            connection.execute(
                text("DELETE FROM policy_documents WHERE id=:policy_id"),
                {"policy_id": policy_id},
            )
            connection.execute(
                text("DELETE FROM chunking_configs WHERE organization_id=:organization_id"),
                {"organization_id": ORGANIZATION_ID},
            )
        finally:
            for table_name in reversed(tables):
                connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))


def test_policy_create_submit_independent_approve_activates_traceable_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    file_id: UUID | None = None
    policy_id: UUID | None = None
    try:
        _seed_knowledge_subjects(factory)
        catalog = KnowledgeCatalogService(factory)
        catalog_page = catalog.list_page(ORGANIZATION_ID, None, 20)
        assert [item.id for item in catalog_page.items] == [KNOWLEDGE_BASE_ID]
        assert catalog.get_detail(ORGANIZATION_ID, KNOWLEDGE_BASE_ID).default_top_k == 5
        payload = _policy_pdf()
        uploaded = intake.upload(
            _actor(ACTOR_ID),
            FileUploadIntent(
                intended_business_type=IntendedBusinessType.POLICY,
                target_knowledge_base_id=KNOWLEDGE_BASE_ID,
            ),
            file_name="policy.pdf",
            declared_mime="application/pdf",
            stream=io.BytesIO(payload),
            idempotency_key="policy-file-e2e-001",
            trace_id=uuid4(),
        )
        file_id = uploaded.data.file_id
        outbox_claim = _dispatch_pending(factory, uploaded.data.job_id)
        completed = _executor(
            factory,
            _RuntimeStorage(quarantine),
            _CleanScanner(),
        ).execute(
            job_id=uploaded.data.job_id,
            event_id=outbox_claim.event_id,
            event_schema_version=outbox_claim.event_version,
            worker_id="policy-integration-worker",
        )
        assert completed.outcome == "succeeded"

        service = PolicyManagementService(factory)
        create_request = PolicyCreateRequest(
            knowledge_base_id=KNOWLEDGE_BASE_ID,
            source_file_id=file_id,
            policy_code="TRAVEL-001",
            name="差旅报销制度",
            version="1.0",
            issuing_department="财务部",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            scope={"country": "CN"},
        )
        created = service.create(_actor(ACTOR_ID), create_request, "policy-create-001", uuid4())
        policy_id = created.data.policy.id
        replay = service.create(_actor(ACTOR_ID), create_request, "policy-create-001", uuid4())
        assert created.status_code == 201
        assert created.replayed is False
        assert replay.replayed is True
        assert replay.data == created.data
        assert created.data.policy.status.value == "draft"
        filtered = service.list_page(
            _actor(ACTOR_ID),
            None,
            20,
            knowledge_base_id=KNOWLEDGE_BASE_ID,
        )
        assert [item.id for item in filtered.items] == [policy_id]

        submitted = service.submit(
            _actor(ACTOR_ID),
            policy_id,
            PolicyTransitionRequest(row_version="1", reason="内容已复核，提交业务审批"),
            "policy-submit-001",
            uuid4(),
        )
        assert submitted.data.policy.status.value == "submitted"
        assert submitted.data.policy.row_version == "2"
        submitted_replay = service.submit(
            _actor(ACTOR_ID),
            policy_id,
            PolicyTransitionRequest(row_version="1", reason="内容已复核，提交业务审批"),
            "policy-submit-001",
            uuid4(),
        )
        assert submitted_replay.replayed is True
        assert submitted_replay.data == submitted.data

        with pytest.raises(AppError) as captured:
            service.approve(
                _actor(ACTOR_ID),
                policy_id,
                PolicyTransitionRequest(row_version="2", reason="尝试自批"),
                "policy-approve-self-001",
                uuid4(),
            )
        assert captured.value.code == "POLICY_SELF_APPROVAL_FORBIDDEN"

        approved = service.approve(
            _actor(APPROVER_ID),
            policy_id,
            PolicyTransitionRequest(row_version="2", reason="独立审核通过"),
            "policy-approve-001",
            uuid4(),
        )
        assert approved.data.policy.status.value == "business_approved"
        assert approved.data.policy.row_version == "3"
        assert approved.data.chunk_set is not None
        assert approved.data.chunk_set.status == "active"
        assert approved.data.chunk_set.chunk_count >= 1
        approved_replay = service.approve(
            _actor(APPROVER_ID),
            policy_id,
            PolicyTransitionRequest(row_version="2", reason="独立审核通过"),
            "policy-approve-001",
            uuid4(),
        )
        assert approved_replay.replayed is True
        assert approved_replay.data == approved.data

        with factory() as session:
            policy = session.get(PolicyDocument, policy_id)
            assert policy is not None
            assert policy.submitted_by == ACTOR_ID
            assert policy.business_approved_by == APPROVER_ID
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(FilePrimaryBusinessObject)
                    .where(FilePrimaryBusinessObject.policy_document_id == policy_id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(PolicyApprovalRecord)
                    .where(PolicyApprovalRecord.policy_document_id == policy_id)
                )
                == 2
            )
            chunk_set = session.scalar(
                select(DocumentChunkSet).where(
                    DocumentChunkSet.policy_document_id == policy_id,
                    DocumentChunkSet.status == "active",
                )
            )
            assert chunk_set is not None
            assert chunk_set.content_manifest_hash == approved.data.chunk_set.content_manifest_hash
            chunk_count = session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.chunk_set_id == chunk_set.id)
            )
            source_count = session.scalar(select(func.count()).select_from(DocumentChunkSource))
            assert chunk_count == chunk_set.chunk_count
            assert source_count is not None and source_count >= chunk_set.chunk_count
            assert session.scalar(select(func.count()).select_from(ChunkingConfig)) == 1
            assert tuple(
                session.scalars(
                    select(OperationLog.action_code)
                    .where(OperationLog.resource_id == policy_id)
                    .order_by(OperationLog.created_at, OperationLog.id)
                ).all()
            ) == (
                "policy.created",
                "policy.submitted",
                "policy.business_approved",
            )
    finally:
        if policy_id is not None:
            _clear_policy_subjects(engine, policy_id)
        if file_id is not None:
            _clear_document_subjects(engine, file_id)
        _clear_subjects(engine)
        engine.dispose()
