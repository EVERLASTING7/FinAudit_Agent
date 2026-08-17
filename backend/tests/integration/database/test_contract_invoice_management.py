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
from app.models.financial import Contract, ContractInvoice, Invoice
from app.models.operations import OperationLog
from app.models.reliability import IdempotencyRecord
from app.schemas.invoices import (
    ContractLinkSuggestionRequest,
    PrimaryContractCancelRequest,
    PrimaryContractSetRequest,
)
from app.services.auth import AuthenticatedActor
from app.services.contract_invoice_management import (
    ContractInvoiceManagementService,
    ContractInvoiceMutationResult,
)
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
)

pytestmark = pytest.mark.integration

ORGANIZATION_ID = UUID("81000000-0000-4000-8000-000000000001")
CONTRACT_ADMIN_ID = UUID("81000000-0000-4000-8000-000000000002")
FINANCE_REVIEWER_ID = UUID("81000000-0000-4000-8000-000000000003")
CONTRACT_A_ID = UUID("81000000-0000-4000-8000-000000000004")
CONTRACT_B_ID = UUID("81000000-0000-4000-8000-000000000005")
INVOICE_ID = UUID("81000000-0000-4000-8000-000000000006")


def _contract_admin_actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=CONTRACT_ADMIN_ID,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=("contract_admin",),
        permissions=("financial.read", "links.suggest"),
    )


def _finance_actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=FINANCE_REVIEWER_ID,
        organization_id=ORGANIZATION_ID,
        session_id=uuid4(),
        roles=("finance_reviewer",),
        permissions=("financial.read", "links.manage_primary"),
    )


def _contract(
    identity: UUID,
    *,
    contract_no: str,
    party_b_name: str,
    party_b_tax_no: str,
    status: str,
    actor_id: UUID,
    now: datetime,
) -> Contract:
    return Contract(
        id=identity,
        organization_id=ORGANIZATION_ID,
        contract_no=contract_no,
        name=f"{party_b_name}采购合同",
        party_a_name="采购方",
        party_a_tax_no="91310000BUYER0001X",
        party_b_name=party_b_name,
        party_b_tax_no=party_b_tax_no,
        supplier_id=None,
        amount=Decimal("1000.00"),
        currency="CNY",
        signed_date=date(2026, 1, 1),
        effective_date=date(2026, 1, 1),
        expiry_date=date(2026, 12, 31),
        payment_method=None,
        payment_terms=None,
        confirmation_status="confirmed",
        status=status,
        confirmed_by=actor_id,
        confirmed_at=now,
        critical_fact_hash="a" * 64,
        created_by=actor_id,
        updated_by=actor_id,
    )


def _seed_subjects(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        now = session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        session.add(
            Organization(
                id=ORGANIZATION_ID,
                name="Synthetic contract-invoice organization",
                unified_social_credit_code="SYNTH-CONTRACT-INVOICE-USCC",
                tax_number="SYNTH-CONTRACT-INVOICE-TAX",
                status="active",
            )
        )
        session.flush()
        session.add_all(
            [
                User(
                    id=CONTRACT_ADMIN_ID,
                    organization_id=ORGANIZATION_ID,
                    username="contract.invoice.admin",
                    display_name="合同管理员",
                    password_hash="synthetic-password-hash",
                    status="active",
                    password_changed_at=now,
                ),
                User(
                    id=FINANCE_REVIEWER_ID,
                    organization_id=ORGANIZATION_ID,
                    username="contract.invoice.finance",
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
                    CONTRACT_A_ID,
                    contract_no="SYNTH-CI-A",
                    party_b_name="匹配供应商",
                    party_b_tax_no="91310000SELLER001X",
                    status="active",
                    actor_id=CONTRACT_ADMIN_ID,
                    now=now,
                ),
                _contract(
                    CONTRACT_B_ID,
                    contract_no="SYNTH-CI-B",
                    party_b_name="历史供应商",
                    party_b_tax_no="91310000SELLER002X",
                    status="expired",
                    actor_id=CONTRACT_ADMIN_ID,
                    now=now,
                ),
            ]
        )
        session.add(
            Invoice(
                id=INVOICE_ID,
                organization_id=ORGANIZATION_ID,
                invoice_code="SYNTH-CI-INV",
                invoice_number="000001",
                invoice_type="vat_special",
                invoice_date=date(2026, 5, 1),
                buyer_name="采购方",
                buyer_tax_no="91310000BUYER0001X",
                seller_name="匹配供应商",
                seller_tax_no="91310000SELLER001X",
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


def _clear_subjects(engine: Engine) -> None:
    table_names = (
        "operation_logs",
        "idempotency_records",
        "user_corrections",
        "contract_invoices",
        "invoices",
        "contracts",
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
) -> tuple[Engine, sessionmaker[Session], ContractInvoiceManagementService]:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    factory = create_session_factory(engine)
    _seed_subjects(factory)
    return engine, factory, ContractInvoiceManagementService(factory)


def _suggest(
    service: ContractInvoiceManagementService,
    contract_id: UUID,
    invoice_row_version: str,
    idempotency_key: str,
) -> ContractInvoiceMutationResult:
    return service.suggest(
        _contract_admin_actor(),
        INVOICE_ID,
        ContractLinkSuggestionRequest(
            contract_id=contract_id,
            invoice_row_version=invoice_row_version,
            reason="基于字段级匹配证据提交候选",
        ),
        idempotency_key,
        uuid4(),
    )


def test_candidate_suggest_confirm_replace_cancel_history_are_transactional_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service = _setup(monkeypatch)
    try:
        candidates = service.list_candidates(ORGANIZATION_ID, INVOICE_ID)
        assert candidates.invoice_row_version == "1"
        assert [item.contract.id for item in candidates.items] == [CONTRACT_A_ID, CONTRACT_B_ID]
        assert candidates.items[0].match_reasons.model_dump(mode="json") == {
            "tax_no": {"status": "matched", "code": "tax_no_matched"},
            "name": {"status": "matched", "code": "name_matched"},
            "date": {"status": "matched", "code": "date_in_range"},
        }
        assert candidates.items[1].contract.status == "expired"
        assert candidates.items[1].match_reasons.tax_no.status == "mismatched"
        assert candidates.items[1].match_reasons.name.status == "mismatched"

        first_suggestion = _suggest(service, CONTRACT_A_ID, "1", "ci-suggest-001")
        first_replay = _suggest(service, CONTRACT_A_ID, "1", "ci-suggest-001")
        assert first_suggestion.replayed is False
        assert first_replay.replayed is True
        assert first_replay.data == first_suggestion.data
        assert first_suggestion.data.invoice_row_version == "2"
        assert first_suggestion.data.relation.status == "suggested"
        assert first_suggestion.data.relation.row_version == "1"

        confirmed = service.set_primary(
            _finance_actor(),
            INVOICE_ID,
            PrimaryContractSetRequest(
                suggestion_id=first_suggestion.data.relation.id,
                invoice_row_version="2",
                relation_row_version="1",
                reason="财务复核确认主合同",
            ),
            "ci-confirm-001",
            uuid4(),
        )
        confirmed_replay = service.set_primary(
            _finance_actor(),
            INVOICE_ID,
            PrimaryContractSetRequest(
                suggestion_id=first_suggestion.data.relation.id,
                invoice_row_version="2",
                relation_row_version="1",
                reason="财务复核确认主合同",
            ),
            "ci-confirm-001",
            uuid4(),
        )
        assert confirmed.replayed is False
        assert confirmed_replay.replayed is True
        assert confirmed_replay.data == confirmed.data
        assert confirmed.data.invoice_row_version == "3"
        assert confirmed.data.relation.status == "confirmed_primary"
        assert confirmed.data.relation.row_version == "2"

        second_suggestion = _suggest(service, CONTRACT_B_ID, "3", "ci-suggest-002")
        replaced = service.set_primary(
            _finance_actor(),
            INVOICE_ID,
            PrimaryContractSetRequest(
                suggestion_id=second_suggestion.data.relation.id,
                invoice_row_version="4",
                relation_row_version="1",
                reason="新证据确认替换原主合同",
            ),
            "ci-replace-001",
            uuid4(),
        )
        assert replaced.data.invoice_row_version == "5"
        assert replaced.data.relation.status == "confirmed_primary"
        assert replaced.data.relation.row_version == "2"
        assert replaced.data.previous_primary_relation_id == first_suggestion.data.relation.id

        cancelled = service.cancel_primary(
            _finance_actor(),
            INVOICE_ID,
            PrimaryContractCancelRequest(
                invoice_row_version="5",
                relation_row_version="2",
                reason="复核后取消当前主合同",
            ),
            "ci-cancel-001",
            uuid4(),
        )
        assert cancelled.data.invoice_row_version == "6"
        assert cancelled.data.relation.status == "cancelled"
        assert cancelled.data.relation.row_version == "3"

        history = service.get_history(ORGANIZATION_ID, INVOICE_ID)
        assert [item.id for item in history.items] == [
            first_suggestion.data.relation.id,
            second_suggestion.data.relation.id,
        ]
        assert [item.status for item in history.items] == ["cancelled", "cancelled"]
        assert history.items[0].confirmed_at is not None
        assert history.items[0].cancel_reason == "新证据确认替换原主合同"
        assert history.items[1].cancel_reason == "复核后取消当前主合同"

        with factory() as session:
            invoice = session.get(Invoice, INVOICE_ID)
            assert invoice is not None
            assert invoice.row_version == 6
            relations = tuple(
                session.scalars(
                    select(ContractInvoice).order_by(
                        ContractInvoice.created_at,
                        ContractInvoice.id,
                    )
                ).all()
            )
            assert [relation.row_version for relation in relations] == [3, 3]
            assert all(relation.status == "cancelled" for relation in relations)
            corrections = tuple(
                session.scalars(
                    select(UserCorrection).order_by(
                        UserCorrection.created_at,
                        UserCorrection.id,
                    )
                ).all()
            )
            assert len(corrections) == 3
            assert all(item.field_path == "primary_contract" for item in corrections)
            assert corrections[0].before_value_json == {"relation": None}
            assert corrections[2].after_value_json == {"relation": None}
            assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 5
            logs = tuple(
                session.scalars(
                    select(OperationLog).order_by(OperationLog.created_at, OperationLog.id)
                ).all()
            )
            assert [log.action_code for log in logs] == [
                "contract_invoices.suggested",
                "contract_invoices.primary_confirmed",
                "contract_invoices.suggested",
                "contract_invoices.primary_replaced",
                "contract_invoices.primary_cancelled",
            ]
    finally:
        _clear_subjects(engine)
        engine.dispose()


def test_concurrent_primary_confirmation_has_exactly_one_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, service = _setup(monkeypatch)
    try:
        first = _suggest(service, CONTRACT_A_ID, "1", "ci-race-suggest-001")
        second = _suggest(service, CONTRACT_B_ID, "2", "ci-race-suggest-002")
        barrier = Barrier(2)

        def confirm(
            suggestion: ContractInvoiceMutationResult,
            idempotency_key: str,
        ) -> ContractInvoiceMutationResult | AppError:
            barrier.wait(timeout=10)
            try:
                return service.set_primary(
                    _finance_actor(),
                    INVOICE_ID,
                    PrimaryContractSetRequest(
                        suggestion_id=suggestion.data.relation.id,
                        invoice_row_version="3",
                        relation_row_version="1",
                        reason="并发确认同一发票主合同",
                    ),
                    idempotency_key,
                    uuid4(),
                )
            except AppError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                executor.map(
                    lambda arguments: confirm(*arguments),
                    (
                        (first, "ci-race-confirm-001"),
                        (second, "ci-race-confirm-002"),
                    ),
                )
            )

        successes = [item for item in results if isinstance(item, ContractInvoiceMutationResult)]
        failures = [item for item in results if isinstance(item, AppError)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert failures[0].code == "ROW_VERSION_CONFLICT"

        with factory() as session:
            invoice = session.get(Invoice, INVOICE_ID)
            assert invoice is not None
            assert invoice.row_version == 4
            relations = tuple(
                session.scalars(select(ContractInvoice).order_by(ContractInvoice.id)).all()
            )
            assert sum(item.status == "confirmed_primary" for item in relations) == 1
            assert sum(item.status == "suggested" for item in relations) == 1
            assert session.scalar(select(func.count()).select_from(UserCorrection)) == 1
            assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 3
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(OperationLog)
                    .where(OperationLog.action_code == "contract_invoices.primary_confirmed")
                )
                == 1
            )
    finally:
        _clear_subjects(engine)
        engine.dispose()
