from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.migration import create_migration_engine
from app.db.session import create_session_factory
from app.models.auth import Organization, User
from app.models.corrections import UserCorrection
from app.models.document_processing import DocumentBlock
from app.models.documents import FileRecord
from app.models.financial import Contract, SupplementaryAgreement, SupplementaryAgreementChange
from app.models.operations import OperationLog
from app.models.reliability import IdempotencyRecord
from app.repositories.document_processing import (
    DocumentProcessingRepository,
    ParseBlockWrite,
    ParsePageWrite,
    ParseVersionWrite,
)
from app.schemas.contracts import (
    SupplementaryAgreementDecisionRequest,
    SupplementaryChangesReplaceRequest,
)
from app.services.auth import AuthenticatedActor
from app.services.effective_contract_query import EffectiveContractQueryService
from app.services.supplementary_agreement_management import (
    SupplementaryAgreementManagementService,
)
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
)

pytestmark = pytest.mark.integration

ORGANIZATION_ID = UUID("7f000000-0000-4000-8000-000000000001")
ACTOR_ID = UUID("7f000000-0000-4000-8000-000000000002")
CONTRACT_ID = UUID("7f000000-0000-4000-8000-000000000003")
AGREEMENT_ID = UUID("7f000000-0000-4000-8000-000000000004")
FILE_ID = UUID("7f000000-0000-4000-8000-000000000005")


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=("contract_admin",),
        permissions=("contracts.manage", "financial.read"),
    )


def _seed_subjects(factory: sessionmaker[Session]) -> UUID:
    with factory.begin() as session:
        session.add(
            Organization(
                id=ORGANIZATION_ID,
                name="Synthetic supplementary agreement organization",
                unified_social_credit_code="SYNTH-SUPPLEMENTARY-USCC",
                tax_number="SYNTH-SUPPLEMENTARY-TAX",
                status="active",
            )
        )
        session.flush()
        session.add(
            User(
                id=ACTOR_ID,
                organization_id=ORGANIZATION_ID,
                username="supplementary.contract.admin",
                display_name="补充协议管理员",
                password_hash="synthetic-password-hash",
                status="active",
                password_changed_at=func.clock_timestamp(),
            )
        )
        session.flush()
        session.add(
            Contract(
                id=CONTRACT_ID,
                organization_id=ORGANIZATION_ID,
                contract_no="SYNTH-CONTRACT-001",
                name="原始合同",
                party_a_name="甲方",
                party_a_tax_no=None,
                party_b_name="乙方",
                party_b_tax_no=None,
                supplier_id=None,
                amount=Decimal("100.00"),
                currency="CNY",
                signed_date=date(2026, 1, 1),
                effective_date=date(2026, 1, 1),
                expiry_date=None,
                payment_method=None,
                payment_terms=None,
                confirmation_status="confirmed",
                status="active",
                confirmed_by=ACTOR_ID,
                confirmed_at=func.clock_timestamp(),
                critical_fact_hash="a" * 64,
                created_by=ACTOR_ID,
                updated_by=ACTOR_ID,
            )
        )
        session.flush()
        session.add(
            SupplementaryAgreement(
                id=AGREEMENT_ID,
                organization_id=ORGANIZATION_ID,
                contract_id=CONTRACT_ID,
                agreement_no="SYNTH-SA-001",
                name="金额调整补充协议",
                signed_date=date(2026, 2, 1),
                effective_date=date(2026, 2, 1),
                status="draft",
                confirmation_status="unconfirmed",
                confirmed_by=None,
                confirmed_at=None,
                confirmation_reason=None,
                critical_fact_hash="b" * 64,
                created_by=ACTOR_ID,
                updated_by=ACTOR_ID,
            )
        )
        file_record = FileRecord(
            id=FILE_ID,
            organization_id=ORGANIZATION_ID,
            original_name="supplementary.pdf",
            extension=".pdf",
            mime_type="application/pdf",
            detected_mime_type="application/pdf",
            size_bytes=128,
            sha256="c" * 64,
            minio_bucket="quarantine",
            minio_object_key=f"{ORGANIZATION_ID}/{FILE_ID}/quarantine",
            original_minio_bucket=None,
            original_minio_object_key=None,
            status="uploaded",
            intended_business_type="supplementary_agreement",
            target_knowledge_base_id=None,
            auto_process_requested=True,
            security_scan_status="pending",
            rejection_code=None,
            rejection_message=None,
            uploaded_by=ACTOR_ID,
            stored_at=None,
            archived_at=None,
            created_by=ACTOR_ID,
            updated_by=ACTOR_ID,
        )
        session.add(file_record)
        session.flush()
        file_record.status = "validating"
        file_record.row_version += 1
        session.flush()
        file_record.status = "stored"
        file_record.security_scan_status = "clean"
        file_record.original_minio_bucket = "originals"
        file_record.original_minio_object_key = f"{ORGANIZATION_ID}/{FILE_ID}/original"
        file_record.stored_at = func.clock_timestamp()
        file_record.row_version += 1
        session.flush()
        parse_version_id = DocumentProcessingRepository(session).append_result(
            organization_id=ORGANIZATION_ID,
            file_id=FILE_ID,
            trace_id=uuid4(),
            result=ParseVersionWrite(
                source_type="parser",
                parser_name="synthetic-parser",
                parser_version="1",
                ocr_name=None,
                ocr_version=None,
                average_confidence=Decimal("0.99"),
                pages=(
                    ParsePageWrite(
                        page_no=1,
                        width=Decimal("595"),
                        height=Decimal("842"),
                        unit="point",
                        text="合同金额调整为 120.00 元",
                        confidence=Decimal("0.99"),
                        blocks=(
                            ParseBlockWrite(
                                block_index=0,
                                block_type="paragraph",
                                text="合同金额调整为 120.00 元",
                                bbox=None,
                                confidence=Decimal("0.99"),
                            ),
                        ),
                    ),
                ),
            ),
        )
        evidence_block_id = session.scalar(
            select(DocumentBlock.id).where(DocumentBlock.parse_version_id == parse_version_id)
        )
        assert isinstance(evidence_block_id, UUID)
        return evidence_block_id


def _clear_subjects(engine: Engine) -> None:
    table_names = (
        "operation_logs",
        "idempotency_records",
        "user_corrections",
        "supplementary_agreement_changes",
        "document_content_exclusions",
        "document_blocks",
        "document_assets",
        "document_pages",
        "document_parse_versions",
        "supplementary_agreements",
        "contracts",
        "files",
        "users",
        "organizations",
    )
    with engine.begin() as connection:
        for table_name in table_names:
            connection.exec_driver_sql(f"ALTER TABLE {table_name} DISABLE TRIGGER USER")
        try:
            for table_name in table_names:
                connection.exec_driver_sql(f"DELETE FROM {table_name}")
        finally:
            for table_name in reversed(table_names):
                connection.exec_driver_sql(f"ALTER TABLE {table_name} ENABLE TRIGGER USER")


def _setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    Engine,
    sessionmaker[Session],
    SupplementaryAgreementManagementService,
    UUID,
]:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    factory = create_session_factory(engine)
    evidence_block_id = _seed_subjects(factory)
    assert evidence_block_id is not None
    return engine, factory, SupplementaryAgreementManagementService(factory), evidence_block_id


def test_replace_confirm_replay_and_effective_projection_are_transactional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service, evidence_block_id = _setup(monkeypatch)
    replace_payload = SupplementaryChangesReplaceRequest.model_validate(
        {
            "row_version": "1",
            "reason": "按补充协议原文替换金额",
            "changes": [
                {
                    "field_code": "amount",
                    "value_type": "number",
                    "new_value": "120.00",
                    "evidence_block_id": str(evidence_block_id),
                    "page_no": 1,
                    "quote_text": "合同金额调整为 120.00 元",
                    "bbox": None,
                }
            ],
        }
    )
    replace_trace_id = uuid4()
    try:
        replaced = service.replace_changes(
            _actor(),
            CONTRACT_ID,
            AGREEMENT_ID,
            replace_payload,
            "supplementary-replace-001",
            replace_trace_id,
        )
        replayed_replace = service.replace_changes(
            _actor(),
            CONTRACT_ID,
            AGREEMENT_ID,
            replace_payload,
            "supplementary-replace-001",
            uuid4(),
        )

        assert replaced.replayed is False
        assert replayed_replace.replayed is True
        assert replayed_replace.data == replaced.data
        assert replaced.data.row_version == "2"
        assert replaced.data.changes[0].old_value == "100.00"
        assert replaced.data.changes[0].new_value == "120.00"
        assert replaced.data.changes[0].confirmation_status == "unconfirmed"

        decision_payload = SupplementaryAgreementDecisionRequest(
            row_version="2",
            decision="confirmed",
            reason="证据链已复核",
        )
        confirmed = service.decide(
            _actor(),
            CONTRACT_ID,
            AGREEMENT_ID,
            decision_payload,
            "supplementary-confirm-001",
            uuid4(),
        )
        replayed_confirmation = service.decide(
            _actor(),
            CONTRACT_ID,
            AGREEMENT_ID,
            decision_payload,
            "supplementary-confirm-001",
            uuid4(),
        )

        assert confirmed.replayed is False
        assert replayed_confirmation.replayed is True
        assert replayed_confirmation.data == confirmed.data
        assert confirmed.data.status == "confirmed"
        assert confirmed.data.confirmation_status == "confirmed"
        assert confirmed.data.changes[0].confirmation_status == "confirmed"
        assert confirmed.data.row_version == "3"

        effective = EffectiveContractQueryService(factory).get_effective_contract(
            ORGANIZATION_ID,
            CONTRACT_ID,
            date(2026, 2, 1),
        )
        amount = next(field for field in effective.fields if field.field_code == "amount")
        assert amount.original_value == "100.00"
        assert amount.effective_value == "120.00"
        assert amount.source_agreement_id == AGREEMENT_ID
        assert effective.applied_agreement_ids == (AGREEMENT_ID,)

        with factory() as session:
            assert session.scalar(select(func.count()).select_from(UserCorrection)) == 1
            assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 2
            logs = tuple(
                session.scalars(
                    select(OperationLog).order_by(OperationLog.created_at, OperationLog.id)
                ).all()
            )
            assert [log.action_code for log in logs] == [
                "supplementary_agreements.changes_replaced",
                "supplementary_agreements.confirmed",
            ]
            assert logs[0].trace_id == replace_trace_id
            agreement = session.get(SupplementaryAgreement, AGREEMENT_ID)
            assert agreement is not None
            assert agreement.status == "confirmed"
            change = session.scalar(
                select(SupplementaryAgreementChange).where(
                    SupplementaryAgreementChange.supplementary_agreement_id == AGREEMENT_ID
                )
            )
            assert change is not None
            assert change.old_value_json == "100.00"
            assert change.new_value_json == "120.00"
            assert change.confirmation_status == "confirmed"
    finally:
        _clear_subjects(engine)
        engine.dispose()
