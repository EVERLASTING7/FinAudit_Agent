from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.db.migration import create_migration_engine
from app.db.session import create_session_factory
from app.models.auth import Organization, User
from app.models.corrections import UserCorrection
from app.models.financial import Contract, Invoice, Supplier
from app.models.operations import OperationLog
from app.models.reliability import IdempotencyRecord
from app.schemas.suppliers import SupplierCandidateUpdateRequest, SupplierSourceResolveRequest
from app.services.auth import AuthenticatedActor
from app.services.supplier_management import SupplierManagementService, SupplierMutationResult
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
)

pytestmark = pytest.mark.integration

ORGANIZATION_ID = UUID("9b000000-0000-4000-8000-000000000001")
CONTRACT_ADMIN_ID = UUID("9b000000-0000-4000-8000-000000000002")
FINANCE_REVIEWER_ID = UUID("9b000000-0000-4000-8000-000000000003")
CONTRACT_ID = UUID("9b000000-0000-4000-8000-000000000004")
INVOICE_ID = UUID("9b000000-0000-4000-8000-000000000005")
SECOND_CONTRACT_ID = UUID("9b000000-0000-4000-8000-000000000006")
UNCONFIRMED_CONTRACT_ID = UUID("9b000000-0000-4000-8000-000000000007")
SHARED_TAX = "Exact-Tax-共享-01"


def _actor(*, finance: bool = False) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=FINANCE_REVIEWER_ID if finance else CONTRACT_ADMIN_ID,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=("finance_reviewer",) if finance else ("contract_admin",),
        permissions=("financial.read", "suppliers.correct"),
    )


def _contract(
    identity: UUID,
    *,
    tax_number: str,
    name: str,
    confirmed: bool,
    now: datetime,
) -> Contract:
    return Contract(
        id=identity,
        organization_id=ORGANIZATION_ID,
        contract_no=f"SUP-{identity.hex[-6:]}",
        name=f"{name}采购合同",
        party_a_name="采购企业",
        party_a_tax_no="BUYER-TAX-01",
        party_b_name=name,
        party_b_tax_no=tax_number,
        supplier_id=None,
        amount=Decimal("1000.00"),
        currency="CNY",
        signed_date=date(2026, 1, 1),
        effective_date=date(2026, 1, 1),
        expiry_date=date(2026, 12, 31),
        payment_method=None,
        payment_terms=None,
        confirmation_status="confirmed" if confirmed else "unconfirmed",
        status="active" if confirmed else "draft",
        confirmed_by=CONTRACT_ADMIN_ID if confirmed else None,
        confirmed_at=now if confirmed else None,
        critical_fact_hash="a" * 64,
        created_by=CONTRACT_ADMIN_ID,
        updated_by=CONTRACT_ADMIN_ID,
    )


def _seed(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        now = session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        session.add(
            Organization(
                id=ORGANIZATION_ID,
                name="Synthetic supplier runtime organization",
                unified_social_credit_code="SUPPLIER-RUNTIME-USCC",
                tax_number="SUPPLIER-RUNTIME-TAX",
                status="active",
            )
        )
        session.flush()
        session.add_all(
            [
                User(
                    id=CONTRACT_ADMIN_ID,
                    organization_id=ORGANIZATION_ID,
                    username="supplier.contract.admin",
                    display_name="合同管理员",
                    password_hash="synthetic-password-hash",
                    status="active",
                    password_changed_at=now,
                ),
                User(
                    id=FINANCE_REVIEWER_ID,
                    organization_id=ORGANIZATION_ID,
                    username="supplier.finance.reviewer",
                    display_name="财务复核员",
                    password_hash="synthetic-password-hash",
                    status="active",
                    password_changed_at=now,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                _contract(
                    CONTRACT_ID,
                    tax_number=SHARED_TAX,
                    name="合同来源供应商",
                    confirmed=True,
                    now=now,
                ),
                _contract(
                    SECOND_CONTRACT_ID,
                    tax_number="Second-Exact-Tax-02",
                    name="第二供应商",
                    confirmed=True,
                    now=now,
                ),
                _contract(
                    UNCONFIRMED_CONTRACT_ID,
                    tax_number="Draft-Tax-03",
                    name="未确认供应商",
                    confirmed=False,
                    now=now,
                ),
            ]
        )
        session.add(
            Invoice(
                id=INVOICE_ID,
                organization_id=ORGANIZATION_ID,
                invoice_code="SUP-INV-01",
                invoice_number="000001",
                invoice_type="vat_special",
                invoice_date=date(2026, 5, 1),
                buyer_name="采购企业",
                buyer_tax_no="BUYER-TAX-01",
                seller_name="发票来源供应商",
                seller_tax_no=SHARED_TAX,
                supplier_id=None,
                amount_excluding_tax=Decimal("884.96"),
                tax_amount=Decimal("115.04"),
                total_amount=Decimal("1000.00"),
                currency="CNY",
                confirmation_status="confirmed",
                duplicate_status="unique",
                status="confirmed",
                field_evidence_json={},
                confirmed_by=FINANCE_REVIEWER_ID,
                confirmed_at=now,
                critical_fact_hash="b" * 64,
                created_by=FINANCE_REVIEWER_ID,
                updated_by=FINANCE_REVIEWER_ID,
            )
        )


def _clear(engine: Engine) -> None:
    trigger_tables = (
        "contracts",
        "invoices",
        "suppliers",
        "operation_logs",
        "user_corrections",
    )
    with engine.begin() as connection:
        for table_name in trigger_tables:
            connection.exec_driver_sql(f"ALTER TABLE {table_name} DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "UPDATE contracts SET supplier_id=NULL WHERE organization_id=%s",
                (str(ORGANIZATION_ID),),
            )
            connection.exec_driver_sql(
                "UPDATE invoices SET supplier_id=NULL WHERE organization_id=%s",
                (str(ORGANIZATION_ID),),
            )
            for table_name in (
                "operation_logs",
                "idempotency_records",
                "user_corrections",
                "suppliers",
                "invoices",
                "contracts",
                "users",
                "organizations",
            ):
                connection.exec_driver_sql(f"DELETE FROM {table_name}")
        finally:
            for table_name in reversed(trigger_tables):
                connection.exec_driver_sql(f"ALTER TABLE {table_name} ENABLE TRIGGER USER")


def _setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Engine, sessionmaker[Session], SupplierManagementService]:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    factory = create_session_factory(engine)
    _seed(factory)
    return engine, factory, SupplierManagementService(factory)


def _resolve(
    service: SupplierManagementService,
    *,
    source_type: str,
    source_id: UUID,
    key: str,
) -> UUID:
    result = service.resolve_source(
        _actor(finance=source_type == "invoice"),
        SupplierSourceResolveRequest(
            source_type=source_type,
            source_id=source_id,
            row_version="1",
        ),
        key,
        uuid4(),
    )
    assert result.replayed is False
    assert result.data.created is True
    assert result.data.reused is False
    assert result.data.supplier.status.value == "candidate"
    assert result.data.supplier.tax_number == (
        SHARED_TAX if source_id in {CONTRACT_ID, INVOICE_ID} else "Second-Exact-Tax-02"
    )
    return result.data.supplier.id


def test_contract_and_invoice_candidates_converge_to_one_active_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service = _setup(monkeypatch)
    try:
        contract_candidate_id = _resolve(
            service,
            source_type="contract",
            source_id=CONTRACT_ID,
            key="supplier-resolve-contract-01",
        )
        invoice_candidate_id = _resolve(
            service,
            source_type="invoice",
            source_id=INVOICE_ID,
            key="supplier-resolve-invoice-01",
        )
        barrier = Barrier(2)

        def confirm(candidate_id: UUID, finance: bool, key: str) -> SupplierMutationResult:
            barrier.wait(timeout=10)
            return service.update_candidate(
                _actor(finance=finance),
                candidate_id,
                SupplierCandidateUpdateRequest(
                    row_version="1",
                    reason="人工确认同一精确税务身份",
                    decision="confirmed",
                ),
                key,
                uuid4(),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(
                    confirm,
                    contract_candidate_id,
                    False,
                    "supplier-confirm-contract-01",
                ),
                executor.submit(
                    confirm,
                    invoice_candidate_id,
                    True,
                    "supplier-confirm-invoice-01",
                ),
            )
            results = tuple(future.result(timeout=30) for future in futures)

        assert sorted(result.data.reused for result in results) == [False, True]
        assert len({result.data.supplier.id for result in results}) == 1
        active_id = results[0].data.supplier.id
        assert all(result.data.supplier.status.value == "active" for result in results)

        replay_index = next(
            index
            for index, result in enumerate(results)
            if result.data.candidate_id == contract_candidate_id
        )
        replay = service.update_candidate(
            _actor(finance=False),
            contract_candidate_id,
            SupplierCandidateUpdateRequest(
                row_version="1",
                reason="人工确认同一精确税务身份",
                decision="confirmed",
            ),
            "supplier-confirm-contract-01",
            uuid4(),
        )
        assert replay.replayed is True
        assert replay.data == results[replay_index].data

        with factory() as session:
            suppliers = tuple(session.scalars(select(Supplier).order_by(Supplier.id)).all())
            contract = session.get(Contract, CONTRACT_ID)
            invoice = session.get(Invoice, INVOICE_ID)
            corrections = tuple(
                session.scalars(
                    select(UserCorrection)
                    .where(UserCorrection.correction_type == "supplier_field")
                    .order_by(UserCorrection.created_at, UserCorrection.id)
                ).all()
            )
            logs = tuple(
                session.scalars(
                    select(OperationLog)
                    .where(OperationLog.action_code.in_(("supplier.resolve", "supplier.update")))
                    .order_by(OperationLog.created_at, OperationLog.id)
                ).all()
            )
            assert contract is not None and invoice is not None
            assert contract.supplier_id == invoice.supplier_id == active_id
            assert sorted((row.confirmation_status, row.status) for row in suppliers) == [
                ("confirmed", "active"),
                ("rejected", "inactive"),
            ]
            assert len(corrections) == 2
            assert all(correction.before_value_json is not None for correction in corrections)
            assert all(correction.after_value_json is not None for correction in corrections)
            assert all(
                "tax_number" not in log.change_summary_json
                and "reason" not in log.change_summary_json
                for log in logs
            )
            assert [log.action_code for log in logs].count("supplier.resolve") == 2
            assert [log.action_code for log in logs].count("supplier.update") == 2
            assert session.scalar(select(func.count(IdempotencyRecord.id))) == 4
    finally:
        _clear(engine)
        engine.dispose()


def test_same_candidate_old_version_has_one_winner_and_rejection_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service = _setup(monkeypatch)
    try:
        candidate_id = _resolve(
            service,
            source_type="contract",
            source_id=SECOND_CONTRACT_ID,
            key="supplier-resolve-second-01",
        )
        barrier = Barrier(2)

        def rename(name: str, key: str) -> SupplierMutationResult | AppError:
            barrier.wait(timeout=10)
            try:
                return service.update_candidate(
                    _actor(),
                    candidate_id,
                    SupplierCandidateUpdateRequest(
                        row_version="1",
                        reason="并发名称复核",
                        standard_name=name,
                    ),
                    key,
                    uuid4(),
                )
            except AppError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                future.result(timeout=30)
                for future in (
                    executor.submit(rename, "第二供应商甲", "supplier-rename-01"),
                    executor.submit(rename, "第二供应商乙", "supplier-rename-02"),
                )
            )
        successes = [result for result in results if isinstance(result, SupplierMutationResult)]
        failures = [result for result in results if isinstance(result, AppError)]
        assert len(successes) == len(failures) == 1
        assert failures[0].code == "RESOURCE_VERSION_CONFLICT"

        rejected = service.update_candidate(
            _actor(),
            candidate_id,
            SupplierCandidateUpdateRequest(
                row_version="2",
                reason="来源主体不纳入供应商主数据",
                decision="rejected",
            ),
            "supplier-reject-01",
            uuid4(),
        )
        assert rejected.data.supplier.status.value == "inactive"
        assert rejected.data.candidate_row_version == "3"
        with pytest.raises(AppError) as stale:
            service.update_candidate(
                _actor(),
                candidate_id,
                SupplierCandidateUpdateRequest(
                    row_version="2",
                    reason="旧版本不得覆盖终态",
                    standard_name="旧值",
                ),
                "supplier-stale-01",
                uuid4(),
            )
        assert stale.value.code == "RESOURCE_VERSION_CONFLICT"

        with pytest.raises(AppError) as unconfirmed:
            service.resolve_source(
                _actor(),
                SupplierSourceResolveRequest(
                    source_type="contract",
                    source_id=UNCONFIRMED_CONTRACT_ID,
                    row_version="1",
                ),
                "supplier-draft-source-01",
                uuid4(),
            )
        assert unconfirmed.value.code == "SUPPLIER_STATE_CONFLICT"

        with factory() as session:
            assert (
                session.scalar(
                    select(func.count(UserCorrection.id)).where(
                        UserCorrection.object_id == candidate_id
                    )
                )
                == 2
            )
            assert (
                session.scalar(
                    select(func.count(OperationLog.id)).where(
                        OperationLog.action_code == "supplier.update",
                        OperationLog.resource_id == candidate_id,
                    )
                )
                == 2
            )
            assert (
                session.scalar(
                    select(func.count(Supplier.id)).where(
                        Supplier.source_contract_id == UNCONFIRMED_CONTRACT_ID
                    )
                )
                == 0
            )
    finally:
        _clear(engine)
        engine.dispose()
