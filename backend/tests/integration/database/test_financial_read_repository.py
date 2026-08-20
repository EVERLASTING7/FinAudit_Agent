from collections.abc import Iterator
from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.db.migration import create_migration_engine
from app.models.auth import Organization, User
from app.models.financial import (
    Contract,
    ContractInvoice,
    Invoice,
    InvoiceItem,
    SupplementaryAgreement,
)
from app.repositories.financial_read import (
    ContractInvoiceReadView,
    ContractReadView,
    FinancialReadIntegrityError,
    FinancialReadRepository,
    FinancialReadView,
    InvoiceItemReadView,
    InvoicePrimaryContractReadView,
    InvoiceReadView,
    SupplementaryAgreementReadView,
)
from app.rules.contract_invoice_matching import ContractInvoiceReasonCode
from app.schemas.business_statuses import InvoiceStatus
from app.services.contract_invoice_candidates import (
    derive_contract_invoice_candidates_from_view,
)
from app.services.contract_primary_invoice_query import ContractPrimaryInvoiceQueryService
from app.services.contract_query import ContractQueryService
from app.services.invoice_primary_contract_query import InvoicePrimaryContractQueryService
from app.services.invoice_query import InvoiceQueryService
from app.services.supplementary_agreement_query import SupplementaryAgreementQueryService
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
)

pytestmark = pytest.mark.integration

ORGANIZATION_ID = UUID("71000000-0000-4000-8000-000000000001")
OUTSIDE_ORGANIZATION_ID = UUID("71000000-0000-4000-8000-000000000099")
USER_ID = UUID("72000000-0000-4000-8000-000000000001")
OUTSIDE_USER_ID = UUID("72000000-0000-4000-8000-000000000099")
NOW = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
BASELINE_DATE = date(2026, 6, 1)
MATCH_REASONS = {
    "tax_no": {"status": "matched", "code": "tax_no_matched"},
    "name": {"status": "matched", "code": "name_matched"},
    "date": {"status": "matched", "code": "date_in_range"},
}


@pytest.fixture
def database_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)

    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()


def _seed_identity(session: Session) -> None:
    session.add(
        Organization(
            id=ORGANIZATION_ID,
            name="只读仓储合成企业",
            unified_social_credit_code="91310000READVIEW01X",
            tax_number="91310000READVIEW01X",
            status="active",
        )
    )
    session.flush()
    session.add(
        User(
            id=USER_ID,
            organization_id=ORGANIZATION_ID,
            username="financial_read_test_user",
            display_name="只读仓储测试用户",
            password_hash="synthetic-test-password-hash",
            status="active",
            password_changed_at=NOW,
        )
    )
    session.flush()


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    return constraint_name if type(constraint_name) is str else None


def _outside_user() -> User:
    return User(
        id=OUTSIDE_USER_ID,
        organization_id=OUTSIDE_ORGANIZATION_ID,
        username="outside_financial_read_test_user",
        display_name="外部组织测试用户",
        password_hash="synthetic-test-password-hash",
        status="active",
        password_changed_at=NOW,
    )


def _contract(
    identity: UUID,
    *,
    contract_no: str | None = None,
    amount: Decimal = Decimal("100.25"),
    deleted: bool = False,
) -> Contract:
    return Contract(
        id=identity,
        organization_id=ORGANIZATION_ID,
        contract_no=contract_no,
        name="合成采购合同",
        party_a_name="合成购买方",
        party_a_tax_no="91310000BUYER0001X",
        party_b_name="合成销售方",
        party_b_tax_no="91310000SELLER001X",
        amount=amount,
        currency="CNY",
        signed_date=date(2026, 1, 1),
        effective_date=date(2026, 1, 1),
        expiry_date=date(2026, 12, 31),
        payment_method="bank_transfer",
        payment_terms="验收后付款",
        confirmation_status="confirmed",
        status="active",
        confirmed_by=USER_ID,
        confirmed_at=NOW,
        critical_fact_hash="a" * 64,
        created_by=USER_ID,
        deleted_at=NOW if deleted else None,
        deleted_by=USER_ID if deleted else None,
        delete_reason="合成软删除" if deleted else None,
    )


def _invoice(
    identity: UUID,
    *,
    total_amount: Decimal = Decimal("100.25"),
    deleted: bool = False,
) -> Invoice:
    return Invoice(
        id=identity,
        organization_id=ORGANIZATION_ID,
        invoice_code="INV-CODE",
        invoice_number="INV-NUMBER",
        invoice_type="standard",
        invoice_date=date(2026, 6, 1),
        buyer_name="合成购买方",
        buyer_tax_no="91310000BUYER0001X",
        seller_name="合成销售方",
        seller_tax_no="91310000SELLER001X",
        amount_excluding_tax=Decimal("80.12"),
        tax_amount=Decimal("20.13"),
        total_amount=total_amount,
        currency="CNY",
        confirmation_status="confirmed",
        duplicate_status="unique",
        status="confirmed",
        field_evidence_json={"facts": ["seller"], "page": 1},
        confirmed_by=USER_ID,
        confirmed_at=NOW,
        critical_fact_hash="b" * 64,
        created_by=USER_ID,
        deleted_at=NOW if deleted else None,
        deleted_by=USER_ID if deleted else None,
        delete_reason="合成软删除" if deleted else None,
    )


def _agreement(
    identity: UUID,
    contract_id: UUID,
    *,
    effective_date: date = BASELINE_DATE,
    status: str = "confirmed",
    confirmation_status: str = "confirmed",
    deleted: bool = False,
) -> SupplementaryAgreement:
    return SupplementaryAgreement(
        id=identity,
        organization_id=ORGANIZATION_ID,
        contract_id=contract_id,
        agreement_no=None,
        name="合成补充协议 header",
        signed_date=date(2026, 5, 1),
        effective_date=effective_date,
        status=status,
        confirmation_status=confirmation_status,
        confirmed_by=USER_ID,
        confirmed_at=NOW,
        confirmation_reason="合成确认",
        critical_fact_hash="c" * 64,
        created_by=USER_ID,
        deleted_at=NOW if deleted else None,
        deleted_by=USER_ID if deleted else None,
        delete_reason="合成软删除" if deleted else None,
    )


def _item(identity: UUID, invoice_id: UUID, line_no: int) -> InvoiceItem:
    return InvoiceItem(
        id=identity,
        invoice_id=invoice_id,
        line_no=line_no,
        item_name=f"合成明细 {line_no}",
        specification="规格",
        unit="项",
        quantity=Decimal("2.125000"),
        unit_price=Decimal("47.176471"),
        amount_excluding_tax=Decimal("80.12"),
        tax_rate=Decimal("0.130000"),
        tax_amount=Decimal("20.13"),
        total_amount=Decimal("100.25"),
        evidence_json={"cells": [line_no]},
    )


def _relation(
    identity: UUID,
    contract_id: UUID,
    invoice_id: UUID,
    *,
    status: str = "candidate",
    deleted: bool = False,
) -> ContractInvoice:
    confirmed = status == "confirmed_primary"
    return ContractInvoice(
        id=identity,
        contract_id=contract_id,
        invoice_id=invoice_id,
        status=status,
        match_reasons_json=MATCH_REASONS,
        suggested_by="system",
        confirmed_by=USER_ID if confirmed else None,
        confirmed_at=NOW if confirmed else None,
        row_version=1,
        created_at=NOW,
        created_by=USER_ID,
        deleted_at=NOW if deleted else None,
    )


def _flush_legacy_relations(
    session: Session,
    relations: list[ContractInvoice],
) -> None:
    """只为只读兼容测试注入 015 之前可能存在的关系快照。"""

    connection = session.connection()
    connection.exec_driver_sql("ALTER TABLE contract_invoices DISABLE TRIGGER USER")
    try:
        session.add_all(relations)
        session.flush()
    finally:
        connection.exec_driver_sql("ALTER TABLE contract_invoices ENABLE TRIGGER USER")


def _flush_legacy_invoice_items(
    session: Session,
    rows: list[object],
) -> None:
    """只为只读兼容测试注入 016 之前可能存在的明细快照。"""

    connection = session.connection()
    connection.exec_driver_sql("ALTER TABLE invoice_items DISABLE TRIGGER USER")
    try:
        session.add_all(rows)
        session.flush()
    finally:
        connection.exec_driver_sql("ALTER TABLE invoice_items ENABLE TRIGGER USER")


def test_read_view_repr_only_keeps_minimum_diagnostic_fields() -> None:
    expected_repr_fields = {
        ContractReadView: {
            "id",
            "organization_id",
            "confirmation_status",
            "status",
            "row_version",
        },
        SupplementaryAgreementReadView: {
            "id",
            "organization_id",
            "contract_id",
            "status",
            "confirmation_status",
            "row_version",
        },
        InvoiceItemReadView: {"id", "invoice_id", "row_version"},
        InvoiceReadView: {
            "id",
            "organization_id",
            "confirmation_status",
            "duplicate_status",
            "status",
            "row_version",
        },
        ContractInvoiceReadView: {
            "id",
            "contract_id",
            "invoice_id",
            "status",
            "row_version",
        },
        InvoicePrimaryContractReadView: set(),
        FinancialReadView: {"organization_id"},
    }
    for view_type, expected in expected_repr_fields.items():
        assert {item.name for item in fields(view_type) if item.repr} == expected

    sentinel = "SENSITIVE_FINANCIAL_READ_REPR_SENTINEL"
    sensitive_date = date(2099, 12, 31)
    sensitive_time = datetime(2099, 12, 31, 23, 59, tzinfo=timezone.utc)
    sensitive_actor = UUID("79000000-0000-4000-8000-000000000099")
    contract_id = UUID("73000000-0000-4000-8000-000000000061")
    invoice_id = UUID("74000000-0000-4000-8000-000000000061")
    item = InvoiceItemReadView(
        id=UUID("76000000-0000-4000-8000-000000000061"),
        invoice_id=invoice_id,
        line_no=987654,
        item_name=sentinel,
        specification=sentinel,
        unit=sentinel,
        quantity=Decimal("98765.43"),
        unit_price=Decimal("98765.43"),
        amount_excluding_tax=Decimal("98765.43"),
        tax_rate=Decimal("0.987654"),
        tax_amount=Decimal("98765.43"),
        total_amount=Decimal("98765.43"),
        evidence={"sensitive": sentinel},
        row_version=1,
    )
    contract = ContractReadView(
        id=contract_id,
        organization_id=ORGANIZATION_ID,
        contract_no=sentinel,
        name=sentinel,
        party_a_name=sentinel,
        party_a_tax_no=sentinel,
        party_b_name=sentinel,
        party_b_tax_no=sentinel,
        supplier_id=sensitive_actor,
        amount=Decimal("98765.43"),
        currency=sentinel,
        signed_date=sensitive_date,
        effective_date=sensitive_date,
        expiry_date=sensitive_date,
        payment_method=sentinel,
        payment_terms=sentinel,
        confirmation_status="confirmed",
        status="active",
        confirmed_by=sensitive_actor,
        confirmed_at=sensitive_time,
        critical_fact_hash=sentinel,
        row_version=1,
    )
    agreement = SupplementaryAgreementReadView(
        id=UUID("75000000-0000-4000-8000-000000000061"),
        organization_id=ORGANIZATION_ID,
        contract_id=contract_id,
        agreement_no=sentinel,
        name=sentinel,
        signed_date=sensitive_date,
        effective_date=sensitive_date,
        status="confirmed",
        confirmation_status="confirmed",
        confirmed_by=sensitive_actor,
        confirmed_at=sensitive_time,
        confirmation_reason=sentinel,
        critical_fact_hash=sentinel,
        row_version=1,
    )
    invoice = InvoiceReadView(
        id=invoice_id,
        organization_id=ORGANIZATION_ID,
        invoice_code=sentinel,
        invoice_number=sentinel,
        invoice_type=sentinel,
        invoice_date=sensitive_date,
        buyer_name=sentinel,
        buyer_tax_no=sentinel,
        seller_name=sentinel,
        seller_tax_no=sentinel,
        supplier_id=sensitive_actor,
        amount_excluding_tax=Decimal("98765.43"),
        tax_amount=Decimal("98765.43"),
        total_amount=Decimal("98765.43"),
        currency=sentinel,
        confirmation_status="confirmed",
        duplicate_status="unique",
        status="confirmed",
        field_evidence={"sensitive": sentinel},
        confirmed_by=sensitive_actor,
        confirmed_at=sensitive_time,
        critical_fact_hash=sentinel,
        row_version=1,
        items=(item,),
    )
    relation = ContractInvoiceReadView(
        id=UUID("77000000-0000-4000-8000-000000000061"),
        contract_id=contract_id,
        invoice_id=invoice_id,
        status="candidate",
        match_reasons={"sensitive": sentinel},
        suggested_by=sentinel,
        confirmed_by=sensitive_actor,
        confirmed_at=sensitive_time,
        cancelled_by=sensitive_actor,
        cancelled_at=sensitive_time,
        cancel_reason=sentinel,
        row_version=1,
        created_at=sensitive_time,
        created_by=sensitive_actor,
    )
    aggregate = FinancialReadView(
        organization_id=ORGANIZATION_ID,
        baseline_date=sensitive_date,
        contracts=(contract,),
        supplementary_agreements=(agreement,),
        invoices=(invoice,),
        contract_invoices=(relation,),
    )

    rendered = "\n".join(
        repr(value) for value in (contract, agreement, item, invoice, relation, aggregate)
    )
    assert sentinel not in rendered
    assert "98765.43" not in rendered
    assert "987654" not in rendered
    assert "2099" not in rendered
    assert str(sensitive_actor) not in rendered


def test_populated_target_does_not_leak_to_outside_organization(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    contract_id = UUID("73000000-0000-4000-8000-000000000031")
    invoice_id = UUID("74000000-0000-4000-8000-000000000031")
    agreement_id = UUID("75000000-0000-4000-8000-000000000031")
    item_id = UUID("76000000-0000-4000-8000-000000000031")
    relation_id = UUID("77000000-0000-4000-8000-000000000031")
    database_session.add_all([_contract(contract_id), _invoice(invoice_id)])
    database_session.flush()
    _flush_legacy_invoice_items(
        database_session,
        [
            _agreement(agreement_id, contract_id),
            _item(item_id, invoice_id, 1),
            _relation(relation_id, contract_id, invoice_id),
        ],
    )
    repository = FinancialReadRepository(database_session)

    target = repository.read_for_organization(ORGANIZATION_ID, BASELINE_DATE)
    outside = repository.read_for_organization(
        OUTSIDE_ORGANIZATION_ID,
        BASELINE_DATE,
    )

    assert target.organization_id == ORGANIZATION_ID
    assert [contract.id for contract in target.contracts] == [contract_id]
    assert [agreement.id for agreement in target.supplementary_agreements] == [agreement_id]
    assert [invoice.id for invoice in target.invoices] == [invoice_id]
    assert [item.id for item in target.invoices[0].items] == [item_id]
    assert [relation.id for relation in target.contract_invoices] == [relation_id]
    assert outside.organization_id == OUTSIDE_ORGANIZATION_ID
    assert outside.contracts == ()
    assert outside.supplementary_agreements == ()
    assert outside.invoices == ()
    assert outside.contract_invoices == ()
    assert database_session.in_transaction()
    with pytest.raises(FrozenInstanceError):
        target.organization_id = OUTSIDE_ORGANIZATION_ID  # type: ignore[misc]


def test_read_invoice_is_organization_scoped_and_excludes_soft_deleted_rows(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    invoice_id = UUID("74000000-0000-4000-8000-000000000039")
    deleted_invoice_id = UUID("74000000-0000-4000-8000-000000000040")
    first_item_id = UUID("76000000-0000-4000-8000-000000000039")
    second_item_id = UUID("76000000-0000-4000-8000-000000000040")
    database_session.add_all([_invoice(invoice_id), _invoice(deleted_invoice_id, deleted=True)])
    database_session.flush()
    _flush_legacy_invoice_items(
        database_session,
        [
            _item(second_item_id, invoice_id, 2),
            _item(first_item_id, invoice_id, 1),
        ],
    )
    repository = FinancialReadRepository(database_session)

    target = repository.read_invoice(ORGANIZATION_ID, invoice_id)

    assert target is not None
    assert target.id == invoice_id
    assert [item.id for item in target.items] == [first_item_id, second_item_id]
    assert repository.read_invoice(OUTSIDE_ORGANIZATION_ID, invoice_id) is None
    assert repository.read_invoice(ORGANIZATION_ID, deleted_invoice_id) is None
    assert database_session.in_transaction()


def test_invoice_query_service_uses_real_current_head_repository(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    invoice_id = UUID("74000000-0000-4000-8000-000000000041")
    deleted_invoice_id = UUID("74000000-0000-4000-8000-000000000042")
    same_date_larger_id = UUID("74000000-0000-4000-8000-000000000043")
    undated_invoice_id = UUID("74000000-0000-4000-8000-000000000044")
    item_id = UUID("76000000-0000-4000-8000-000000000041")
    same_date_invoice = _invoice(same_date_larger_id)
    undated_invoice = _invoice(undated_invoice_id)
    undated_invoice.invoice_date = None
    database_session.add_all(
        [
            _invoice(invoice_id),
            _invoice(deleted_invoice_id, deleted=True),
            same_date_invoice,
            undated_invoice,
        ]
    )
    database_session.flush()
    _flush_legacy_invoice_items(database_session, [_item(item_id, invoice_id, 1)])
    factory = sessionmaker(
        bind=database_session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    service = InvoiceQueryService(factory)

    detail = service.get_detail(ORGANIZATION_ID, invoice_id)

    assert detail.id == invoice_id
    assert detail.total_amount == "100.25"
    assert [item.id for item in detail.items] == [item_id]
    first_page = service.list_page(ORGANIZATION_ID, None, 1)
    assert first_page.next_cursor is not None
    second_page = service.list_page(ORGANIZATION_ID, first_page.next_cursor, 1)
    assert second_page.next_cursor is not None
    third_page = service.list_page(ORGANIZATION_ID, second_page.next_cursor, 1)
    outside_page = service.list_page(OUTSIDE_ORGANIZATION_ID, None, 20)
    assert [invoice.id for invoice in first_page.items] == [same_date_larger_id]
    assert [invoice.id for invoice in second_page.items] == [invoice_id]
    assert [invoice.id for invoice in third_page.items] == [undated_invoice_id]
    assert third_page.next_cursor is None
    assert outside_page.items == ()
    assert outside_page.next_cursor is None
    for organization_id, hidden_invoice_id in (
        (OUTSIDE_ORGANIZATION_ID, invoice_id),
        (ORGANIZATION_ID, deleted_invoice_id),
    ):
        with pytest.raises(AppError) as captured:
            service.get_detail(organization_id, hidden_invoice_id)
        assert captured.value.status_code == 404
        assert captured.value.code == "RESOURCE_NOT_FOUND"


def test_invoice_duplicate_candidates_use_real_current_head_repository(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    source_id = UUID("74000000-0000-4000-8000-000000000070")
    exact_id = UUID("74000000-0000-4000-8000-000000000071")
    archived_id = UUID("74000000-0000-4000-8000-000000000072")
    second_exact_id = UUID("74000000-0000-4000-8000-000000000073")
    voided_id = UUID("74000000-0000-4000-8000-000000000074")
    deleted_id = UUID("74000000-0000-4000-8000-000000000075")
    code_mismatch_id = UUID("74000000-0000-4000-8000-000000000076")
    number_mismatch_id = UUID("74000000-0000-4000-8000-000000000077")
    tax_mismatch_id = UUID("74000000-0000-4000-8000-000000000078")
    incomplete_id = UUID("74000000-0000-4000-8000-000000000079")
    voided_source_id = UUID("74000000-0000-4000-8000-000000000080")
    deleted_source_id = UUID("74000000-0000-4000-8000-000000000081")

    source = _invoice(source_id)
    exact = _invoice(exact_id)
    archived = _invoice(archived_id)
    archived.status = "archived"
    second_exact = _invoice(second_exact_id)
    second_exact.duplicate_status = "confirmed_duplicate"
    voided = _invoice(voided_id)
    voided.status = "voided"
    code_mismatch = _invoice(code_mismatch_id)
    code_mismatch.invoice_code = "INV-CODE "
    number_mismatch = _invoice(number_mismatch_id)
    number_mismatch.invoice_number = "inv-number"
    tax_mismatch = _invoice(tax_mismatch_id)
    tax_mismatch.seller_tax_no = "91310000SELLER002X"
    incomplete = _invoice(incomplete_id)
    incomplete.invoice_number = None
    voided_source = _invoice(voided_source_id)
    voided_source.status = "voided"
    voided_source.invoice_code = None
    database_session.add_all(
        [
            source,
            exact,
            archived,
            second_exact,
            voided,
            _invoice(deleted_id, deleted=True),
            code_mismatch,
            number_mismatch,
            tax_mismatch,
            incomplete,
            voided_source,
            _invoice(deleted_source_id, deleted=True),
        ]
    )
    database_session.flush()
    factory = sessionmaker(
        bind=database_session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    service = InvoiceQueryService(factory)

    first = service.list_duplicate_candidates(ORGANIZATION_ID, source_id, None, 1)
    assert first.basis_status == "ready"
    assert [candidate.id for candidate in first.items] == [exact_id]
    assert first.next_cursor is not None
    second = service.list_duplicate_candidates(
        ORGANIZATION_ID,
        source_id,
        first.next_cursor,
        1,
    )
    assert [candidate.id for candidate in second.items] == [archived_id]
    assert second.items[0].status is InvoiceStatus.ARCHIVED
    assert second.next_cursor is not None
    third = service.list_duplicate_candidates(
        ORGANIZATION_ID,
        source_id,
        second.next_cursor,
        1,
    )
    assert [candidate.id for candidate in third.items] == [second_exact_id]
    assert third.next_cursor is None
    assert [candidate.id for candidate in (*first.items, *second.items, *third.items)] == [
        exact_id,
        archived_id,
        second_exact_id,
    ]

    incomplete_page = service.list_duplicate_candidates(
        ORGANIZATION_ID,
        incomplete_id,
        None,
        20,
    )
    assert incomplete_page.basis_status == "incomplete_identity"
    assert incomplete_page.items == ()
    assert incomplete_page.next_cursor is None
    voided_page = service.list_duplicate_candidates(
        ORGANIZATION_ID,
        voided_source_id,
        None,
        20,
    )
    assert voided_page.basis_status == "source_voided"
    assert voided_page.items == ()
    assert voided_page.next_cursor is None

    for organization_id, hidden_source_id in (
        (OUTSIDE_ORGANIZATION_ID, source_id),
        (ORGANIZATION_ID, deleted_source_id),
    ):
        with pytest.raises(AppError) as captured:
            service.list_duplicate_candidates(
                organization_id,
                hidden_source_id,
                None,
                20,
            )
        assert captured.value.status_code == 404
        assert captured.value.code == "RESOURCE_NOT_FOUND"


def test_invoice_duplicate_candidate_page_uses_one_postgresql_snapshot_statement(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    source_id = UUID("74000000-0000-4000-8000-000000000082")
    candidate_id = UUID("74000000-0000-4000-8000-000000000083")
    database_session.add_all((_invoice(source_id), _invoice(candidate_id)))
    database_session.flush()
    connection = cast(Connection, database_session.get_bind())
    statements: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", capture_statement)
    try:
        result = FinancialReadRepository(database_session).read_invoice_duplicate_candidate_page(
            ORGANIZATION_ID,
            source_id,
            20,
        )
    finally:
        event.remove(connection, "before_cursor_execute", capture_statement)

    assert result is not None
    assert result[0] == "ready"
    assert [candidate.id for candidate in result[1]] == [candidate_id]
    assert result[2] is False
    assert len(statements) == 1
    assert "WITH duplicate_source AS" in statements[0]
    assert "LEFT OUTER JOIN invoices AS candidate_invoice" in statements[0]


def test_invoice_exact_duplicate_pair_uses_real_current_head_self_join(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    source_id = UUID("74000000-0000-4000-8000-000000000090")
    candidate_id = UUID("74000000-0000-4000-8000-000000000091")
    code_mismatch_id = UUID("74000000-0000-4000-8000-000000000092")
    number_mismatch_id = UUID("74000000-0000-4000-8000-000000000093")
    tax_mismatch_id = UUID("74000000-0000-4000-8000-000000000094")
    voided_candidate_id = UUID("74000000-0000-4000-8000-000000000095")
    deleted_candidate_id = UUID("74000000-0000-4000-8000-000000000096")
    incomplete_source_id = UUID("74000000-0000-4000-8000-000000000097")
    voided_source_id = UUID("74000000-0000-4000-8000-000000000098")
    deleted_source_id = UUID("74000000-0000-4000-8000-000000000099")
    blank_source_id = UUID("74000000-0000-4000-8000-000000000100")
    blank_candidate_id = UUID("74000000-0000-4000-8000-000000000101")

    source = _invoice(source_id)
    source.status = "archived"
    candidate = _invoice(candidate_id)
    candidate.status = "archived"
    candidate.duplicate_status = "suspected"
    code_mismatch = _invoice(code_mismatch_id)
    code_mismatch.invoice_code = "INV-CODE "
    number_mismatch = _invoice(number_mismatch_id)
    number_mismatch.invoice_number = "inv-number"
    tax_mismatch = _invoice(tax_mismatch_id)
    tax_mismatch.seller_tax_no = "91310000SELLER002X"
    voided_candidate = _invoice(voided_candidate_id)
    voided_candidate.status = "voided"
    incomplete_source = _invoice(incomplete_source_id)
    incomplete_source.invoice_number = None
    voided_source = _invoice(voided_source_id)
    voided_source.status = "voided"
    blank_source = _invoice(blank_source_id)
    blank_source.invoice_code = ""
    blank_source.invoice_number = " "
    blank_source.seller_tax_no = ""
    blank_candidate = _invoice(blank_candidate_id)
    blank_candidate.invoice_code = ""
    blank_candidate.invoice_number = " "
    blank_candidate.seller_tax_no = ""
    database_session.add_all(
        [
            source,
            candidate,
            code_mismatch,
            number_mismatch,
            tax_mismatch,
            voided_candidate,
            _invoice(deleted_candidate_id, deleted=True),
            incomplete_source,
            voided_source,
            _invoice(deleted_source_id, deleted=True),
            blank_source,
            blank_candidate,
        ]
    )
    database_session.flush()
    factory = sessionmaker(
        bind=database_session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    service = InvoiceQueryService(factory)

    pair = service.get_exact_duplicate_pair(ORGANIZATION_ID, source_id, candidate_id)

    assert pair.source.id == source_id
    assert pair.candidate.id == candidate_id
    assert pair.source.status is InvoiceStatus.ARCHIVED
    assert pair.candidate.status is InvoiceStatus.ARCHIVED
    assert pair.exact_identity.model_dump() == {
        "invoice_code": "INV-CODE",
        "invoice_number": "INV-NUMBER",
        "seller_tax_no": "91310000SELLER001X",
    }
    blank_pair = service.get_exact_duplicate_pair(
        ORGANIZATION_ID,
        blank_source_id,
        blank_candidate_id,
    )
    assert blank_pair.exact_identity.model_dump() == {
        "invoice_code": "",
        "invoice_number": " ",
        "seller_tax_no": "",
    }

    for hidden_source_id, hidden_candidate_id in (
        (source_id, source_id),
        (source_id, code_mismatch_id),
        (source_id, number_mismatch_id),
        (source_id, tax_mismatch_id),
        (source_id, voided_candidate_id),
        (source_id, deleted_candidate_id),
        (incomplete_source_id, candidate_id),
        (voided_source_id, candidate_id),
        (deleted_source_id, candidate_id),
    ):
        with pytest.raises(AppError) as captured:
            service.get_exact_duplicate_pair(
                ORGANIZATION_ID,
                hidden_source_id,
                hidden_candidate_id,
            )
        assert captured.value.status_code == 404
        assert captured.value.code == "RESOURCE_NOT_FOUND"

    with pytest.raises(AppError) as outside:
        service.get_exact_duplicate_pair(
            OUTSIDE_ORGANIZATION_ID,
            source_id,
            candidate_id,
        )
    assert outside.value.status_code == 404
    assert outside.value.code == "RESOURCE_NOT_FOUND"


def test_contract_query_service_uses_real_current_head_repository(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    contract_id = UUID("73000000-0000-4000-8000-000000000041")
    same_date_larger_id = UUID("73000000-0000-4000-8000-000000000042")
    undated_id = UUID("73000000-0000-4000-8000-000000000043")
    deleted_id = UUID("73000000-0000-4000-8000-000000000044")
    undated_larger_id = UUID("73000000-0000-4000-8000-000000000045")
    undated = _contract(undated_id)
    undated.effective_date = None
    undated_larger = _contract(undated_larger_id)
    undated_larger.effective_date = None
    database_session.add_all(
        [
            _contract(contract_id),
            _contract(same_date_larger_id),
            undated,
            _contract(deleted_id, deleted=True),
            undated_larger,
        ]
    )
    database_session.flush()
    factory = sessionmaker(
        bind=database_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    service = ContractQueryService(factory)

    detail = service.get_detail(ORGANIZATION_ID, contract_id)
    first = service.list_page(ORGANIZATION_ID, None, 1)
    assert first.next_cursor is not None
    second = service.list_page(ORGANIZATION_ID, first.next_cursor, 1)
    assert second.next_cursor is not None
    third = service.list_page(ORGANIZATION_ID, second.next_cursor, 1)
    assert third.next_cursor is not None
    fourth = service.list_page(ORGANIZATION_ID, third.next_cursor, 1)

    assert detail.id == contract_id
    assert detail.amount == "100.25"
    assert [item.id for item in first.items] == [same_date_larger_id]
    assert [item.id for item in second.items] == [contract_id]
    assert [item.id for item in third.items] == [undated_larger_id]
    assert [item.id for item in fourth.items] == [undated_id]
    assert fourth.next_cursor is None
    assert service.list_page(OUTSIDE_ORGANIZATION_ID, None, 20).items == ()
    for organization_id, hidden_id in (
        (OUTSIDE_ORGANIZATION_ID, contract_id),
        (ORGANIZATION_ID, deleted_id),
    ):
        with pytest.raises(AppError) as captured:
            service.get_detail(organization_id, hidden_id)
        assert captured.value.code == "RESOURCE_NOT_FOUND"


def test_invoice_primary_contract_service_uses_real_current_head_repository(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    invoice_id = UUID("74000000-0000-4000-8000-000000000051")
    unlinked_invoice_id = UUID("74000000-0000-4000-8000-000000000052")
    deleted_invoice_id = UUID("74000000-0000-4000-8000-000000000053")
    deleted_contract_invoice_id = UUID("74000000-0000-4000-8000-000000000054")
    deleted_relation_invoice_id = UUID("74000000-0000-4000-8000-000000000056")
    primary_contract_id = UUID("73000000-0000-4000-8000-000000000051")
    candidate_contract_id = UUID("73000000-0000-4000-8000-000000000052")
    deleted_contract_id = UUID("73000000-0000-4000-8000-000000000053")
    database_session.add_all(
        [
            _invoice(invoice_id),
            _invoice(unlinked_invoice_id),
            _invoice(deleted_invoice_id, deleted=True),
            _invoice(deleted_contract_invoice_id),
            _invoice(deleted_relation_invoice_id),
            _contract(primary_contract_id),
            _contract(candidate_contract_id),
            _contract(deleted_contract_id, deleted=True),
        ]
    )
    database_session.flush()
    _flush_legacy_relations(
        database_session,
        [
            _relation(
                UUID("77000000-0000-4000-8000-000000000051"),
                primary_contract_id,
                invoice_id,
                status="confirmed_primary",
            ),
            _relation(
                UUID("77000000-0000-4000-8000-000000000052"),
                candidate_contract_id,
                invoice_id,
            ),
            _relation(
                UUID("77000000-0000-4000-8000-000000000053"),
                deleted_contract_id,
                deleted_contract_invoice_id,
                status="confirmed_primary",
            ),
            _relation(
                UUID("77000000-0000-4000-8000-000000000055"),
                candidate_contract_id,
                deleted_relation_invoice_id,
                status="confirmed_primary",
                deleted=True,
            ),
        ],
    )
    factory = sessionmaker(
        bind=database_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    service = InvoicePrimaryContractQueryService(factory)

    primary = service.get(ORGANIZATION_ID, invoice_id)

    assert primary.primary_contract is not None
    assert primary.primary_contract.id == primary_contract_id
    assert service.get(ORGANIZATION_ID, unlinked_invoice_id).primary_contract is None
    assert service.get(ORGANIZATION_ID, deleted_contract_invoice_id).primary_contract is None
    assert service.get(ORGANIZATION_ID, deleted_relation_invoice_id).primary_contract is None
    for organization_id, hidden_invoice_id in (
        (OUTSIDE_ORGANIZATION_ID, invoice_id),
        (ORGANIZATION_ID, deleted_invoice_id),
    ):
        with pytest.raises(AppError) as captured:
            service.get(organization_id, hidden_invoice_id)
        assert captured.value.code == "RESOURCE_NOT_FOUND"


def test_contract_primary_invoice_service_uses_real_current_head_keyset(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    contract_id = UUID("73000000-0000-4000-8000-000000000061")
    empty_contract_id = UUID("73000000-0000-4000-8000-000000000062")
    deleted_contract_id = UUID("73000000-0000-4000-8000-000000000063")
    invoice_ids = tuple(UUID(f"74000000-0000-4000-8000-{number:012d}") for number in range(61, 64))
    candidate_invoice_id = UUID("74000000-0000-4000-8000-000000000064")
    deleted_invoice_id = UUID("74000000-0000-4000-8000-000000000065")
    deleted_relation_invoice_id = UUID("74000000-0000-4000-8000-000000000066")
    database_session.add_all(
        [
            _contract(contract_id),
            _contract(empty_contract_id),
            _contract(deleted_contract_id, deleted=True),
            *(_invoice(invoice_id) for invoice_id in invoice_ids),
            _invoice(candidate_invoice_id),
            _invoice(deleted_invoice_id, deleted=True),
            _invoice(deleted_relation_invoice_id),
        ]
    )
    database_session.flush()
    _flush_legacy_relations(
        database_session,
        [
            *(
                _relation(
                    UUID(f"77000000-0000-4000-8000-{number:012d}"),
                    contract_id,
                    invoice_id,
                    status="confirmed_primary",
                )
                for number, invoice_id in zip(range(61, 64), invoice_ids, strict=True)
            ),
            _relation(
                UUID("77000000-0000-4000-8000-000000000064"),
                contract_id,
                candidate_invoice_id,
            ),
            _relation(
                UUID("77000000-0000-4000-8000-000000000065"),
                contract_id,
                deleted_invoice_id,
                status="confirmed_primary",
            ),
            _relation(
                UUID("77000000-0000-4000-8000-000000000066"),
                contract_id,
                deleted_relation_invoice_id,
                status="confirmed_primary",
                deleted=True,
            ),
        ],
    )
    factory = sessionmaker(
        bind=database_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    service = ContractPrimaryInvoiceQueryService(factory)

    first = service.list_page(ORGANIZATION_ID, contract_id, None, 1)
    assert first.next_cursor is not None
    second = service.list_page(ORGANIZATION_ID, contract_id, first.next_cursor, 1)
    assert second.next_cursor is not None
    third = service.list_page(ORGANIZATION_ID, contract_id, second.next_cursor, 1)

    paged_ids = tuple(item.id for item in (*first.items, *second.items, *third.items))
    assert paged_ids == invoice_ids
    assert len(paged_ids) == len(set(paged_ids))
    assert third.next_cursor is None
    assert candidate_invoice_id not in paged_ids
    assert deleted_invoice_id not in paged_ids
    assert deleted_relation_invoice_id not in paged_ids
    assert service.list_page(ORGANIZATION_ID, empty_contract_id, None, 20).items == ()
    for organization_id, hidden_contract_id in (
        (OUTSIDE_ORGANIZATION_ID, contract_id),
        (ORGANIZATION_ID, deleted_contract_id),
    ):
        with pytest.raises(AppError) as captured:
            service.list_page(organization_id, hidden_contract_id, None, 20)
        assert captured.value.code == "RESOURCE_NOT_FOUND"


def test_supplementary_agreement_header_service_uses_real_current_head_repository(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    contract_id = UUID("73000000-0000-4000-8000-000000000071")
    empty_contract_id = UUID("73000000-0000-4000-8000-000000000072")
    deleted_contract_id = UUID("73000000-0000-4000-8000-000000000073")
    agreement_ids = tuple(
        UUID(f"75000000-0000-4000-8000-{number:012d}") for number in range(71, 76)
    )
    deleted_agreement_id = UUID("75000000-0000-4000-8000-000000000076")
    statuses = (
        "draft",
        "pending_confirmation",
        "confirmed",
        "rejected",
        "archived",
    )
    database_session.add_all(
        [
            _contract(contract_id),
            _contract(empty_contract_id),
            _contract(deleted_contract_id, deleted=True),
        ]
    )
    database_session.flush()
    agreements = []
    for index, (agreement_id, status) in enumerate(zip(agreement_ids, statuses, strict=True)):
        agreement = _agreement(
            agreement_id,
            contract_id,
            effective_date=(date(2026, 7, 1) if index < 2 else date(2026, 6, 30 - index)),
            status=status,
            confirmation_status=("confirmed" if status == "confirmed" else "unconfirmed"),
        )
        agreements.append(agreement)
    agreements.extend(
        [
            _agreement(
                deleted_agreement_id,
                contract_id,
                effective_date=date(2026, 12, 31),
                deleted=True,
            ),
            _agreement(
                UUID("75000000-0000-4000-8000-000000000077"),
                deleted_contract_id,
            ),
        ]
    )
    database_session.add_all(agreements)
    database_session.flush()
    factory = sessionmaker(
        bind=database_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    service = SupplementaryAgreementQueryService(factory)

    first = service.list_headers(ORGANIZATION_ID, contract_id, None, 1)
    assert first.next_cursor is not None
    second = service.list_headers(ORGANIZATION_ID, contract_id, first.next_cursor, 1)
    assert second.next_cursor is not None
    remaining = service.list_headers(ORGANIZATION_ID, contract_id, second.next_cursor, 100)

    assert [item.id for item in first.items] == [agreement_ids[1]]
    assert [item.id for item in second.items] == [agreement_ids[0]]
    paged_ids = tuple(item.id for item in (*first.items, *second.items, *remaining.items))
    assert paged_ids == (
        agreement_ids[1],
        agreement_ids[0],
        agreement_ids[2],
        agreement_ids[3],
        agreement_ids[4],
    )
    assert len(paged_ids) == len(set(paged_ids))
    assert deleted_agreement_id not in paged_ids
    assert {item.status.value for item in (*first.items, *second.items, *remaining.items)} == set(
        statuses
    )
    assert remaining.next_cursor is None
    assert service.list_headers(ORGANIZATION_ID, empty_contract_id, None, 20).items == ()
    for organization_id, hidden_contract_id in (
        (OUTSIDE_ORGANIZATION_ID, contract_id),
        (ORGANIZATION_ID, deleted_contract_id),
    ):
        with pytest.raises(AppError) as captured:
            service.list_headers(organization_id, hidden_contract_id, None, 20)
        assert captured.value.code == "RESOURCE_NOT_FOUND"


def test_repository_view_drives_candidates_and_effective_agreements_fail_closed(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    contract_id = UUID("73000000-0000-4000-8000-000000000032")
    invoice_id = UUID("74000000-0000-4000-8000-000000000032")
    database_session.add_all([_contract(contract_id), _invoice(invoice_id)])
    database_session.flush()
    repository = FinancialReadRepository(database_session)

    view = repository.read_for_organization(ORGANIZATION_ID, BASELINE_DATE)
    candidates = derive_contract_invoice_candidates_from_view(view, invoice_id)

    assert len(candidates) == 1
    assert candidates[0].contract_id == contract_id
    assert candidates[0].tax_no_reason.code is ContractInvoiceReasonCode.TAX_NO_MATCHED
    assert candidates[0].name_reason.code is ContractInvoiceReasonCode.NAME_MATCHED
    assert candidates[0].date_reason.code is ContractInvoiceReasonCode.DATE_IN_RANGE

    database_session.add(
        _agreement(
            UUID("75000000-0000-4000-8000-000000000032"),
            contract_id,
        )
    )
    database_session.flush()
    view_with_effective_agreement = repository.read_for_organization(
        ORGANIZATION_ID,
        BASELINE_DATE,
    )

    with pytest.raises(ValueError, match="effective supplementary agreement field projection"):
        derive_contract_invoice_candidates_from_view(view_with_effective_agreement, invoice_id)


def test_accepted_single_organization_constraints_reject_cross_org_fixtures(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    target_contract_id = UUID("73000000-0000-4000-8000-000000000041")
    target_invoice_id = UUID("74000000-0000-4000-8000-000000000041")
    outside_contract_id = UUID("73000000-0000-4000-8000-000000000099")
    outside_invoice_id = UUID("74000000-0000-4000-8000-000000000099")
    database_session.add_all([_contract(target_contract_id), _invoice(target_invoice_id)])
    database_session.flush()

    outside_organization = Organization(
        id=OUTSIDE_ORGANIZATION_ID,
        name="外部组织合成记录",
        unified_social_credit_code="91310000OUTSIDE001X",
        tax_number="91310000OUTSIDE001X",
        status="active",
    )
    with pytest.raises(IntegrityError) as organization_error:
        with database_session.begin_nested():
            database_session.add(outside_organization)
            database_session.flush()
    assert _constraint_name(organization_error.value) == "uq_organizations_singleton"

    outside_contract = _contract(outside_contract_id)
    outside_contract.organization_id = OUTSIDE_ORGANIZATION_ID
    outside_invoice = _invoice(outside_invoice_id)
    outside_invoice.organization_id = OUTSIDE_ORGANIZATION_ID
    mismatched_agreement = _agreement(
        UUID("75000000-0000-4000-8000-000000000099"),
        target_contract_id,
    )
    mismatched_agreement.organization_id = OUTSIDE_ORGANIZATION_ID
    rejected_rows = (
        (
            _outside_user(),
            "fk_users_organization_id_organizations",
        ),
        (
            outside_contract,
            "fk_contracts_organization_id_organizations",
        ),
        (
            outside_invoice,
            "fk_invoices_organization_id_organizations",
        ),
        (
            mismatched_agreement,
            "fk_supplementary_agreements_organization_id_organizations",
        ),
        (
            _item(
                UUID("76000000-0000-4000-8000-000000000099"),
                outside_invoice_id,
                1,
            ),
            "fk_invoice_items_invoice_id_invoices",
        ),
        (
            _relation(
                UUID("77000000-0000-4000-8000-000000000098"),
                target_contract_id,
                outside_invoice_id,
            ),
            "fk_contract_invoices_invoice_id_invoices",
        ),
        (
            _relation(
                UUID("77000000-0000-4000-8000-000000000099"),
                outside_contract_id,
                target_invoice_id,
            ),
            "fk_contract_invoices_contract_id_contracts",
        ),
    )
    for row, expected_constraint in rejected_rows:
        with pytest.raises(IntegrityError) as row_error:
            with database_session.begin_nested():
                database_session.add(row)
                database_session.flush()
        assert _constraint_name(row_error.value) == expected_constraint

    view = FinancialReadRepository(database_session).read_for_organization(
        ORGANIZATION_ID,
        BASELINE_DATE,
    )
    assert [contract.id for contract in view.contracts] == [target_contract_id]
    assert [invoice.id for invoice in view.invoices] == [target_invoice_id]
    assert view.supplementary_agreements == ()
    outside_view = FinancialReadRepository(database_session).read_for_organization(
        OUTSIDE_ORGANIZATION_ID,
        BASELINE_DATE,
    )
    assert outside_view.contracts == ()
    assert outside_view.supplementary_agreements == ()
    assert outside_view.invoices == ()
    assert outside_view.contract_invoices == ()


def test_agreement_headers_require_confirmation_and_baseline_and_sort_same_day(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    contract_id = UUID("73000000-0000-4000-8000-000000000051")
    same_day_a = UUID("75000000-0000-4000-8000-000000000051")
    same_day_b = UUID("75000000-0000-4000-8000-000000000052")
    unconfirmed = UUID("75000000-0000-4000-8000-000000000053")
    pending_status = UUID("75000000-0000-4000-8000-000000000054")
    future = UUID("75000000-0000-4000-8000-000000000055")
    database_session.add(_contract(contract_id))
    database_session.flush()
    database_session.add_all(
        [
            _agreement(same_day_b, contract_id),
            _agreement(
                future,
                contract_id,
                effective_date=date(2026, 6, 2),
            ),
            _agreement(
                unconfirmed,
                contract_id,
                confirmation_status="unconfirmed",
            ),
            _agreement(
                pending_status,
                contract_id,
                status="pending_confirmation",
            ),
            _agreement(same_day_a, contract_id),
        ]
    )
    database_session.flush()

    repository = FinancialReadRepository(database_session)
    at_baseline = repository.read_for_organization(
        ORGANIZATION_ID,
        BASELINE_DATE,
    )
    before_effective_date = repository.read_for_organization(
        ORGANIZATION_ID,
        date(2026, 5, 31),
    )

    assert at_baseline.baseline_date == BASELINE_DATE
    assert [agreement.id for agreement in at_baseline.supplementary_agreements] == [
        same_day_a,
        same_day_b,
    ]
    assert before_effective_date.supplementary_agreements == ()


def test_visible_graph_is_detached_exact_deeply_read_only_and_stably_sorted(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    contract_a = UUID("73000000-0000-4000-8000-000000000001")
    contract_b = UUID("73000000-0000-4000-8000-000000000002")
    invoice_a = UUID("74000000-0000-4000-8000-000000000001")
    invoice_b = UUID("74000000-0000-4000-8000-000000000002")
    agreement_a = UUID("75000000-0000-4000-8000-000000000001")
    agreement_b = UUID("75000000-0000-4000-8000-000000000002")
    item_a1 = UUID("76000000-0000-4000-8000-000000000001")
    item_a2 = UUID("76000000-0000-4000-8000-000000000002")
    item_b1 = UUID("76000000-0000-4000-8000-000000000003")
    relation_a = UUID("77000000-0000-4000-8000-000000000001")
    relation_b = UUID("77000000-0000-4000-8000-000000000002")

    database_session.add_all(
        [
            _contract(contract_b),
            _contract(contract_a),
            _invoice(invoice_b),
            _invoice(invoice_a),
        ]
    )
    database_session.flush()
    _flush_legacy_invoice_items(
        database_session,
        [
            _agreement(agreement_b, contract_b),
            _agreement(agreement_a, contract_a),
            _item(item_a2, invoice_a, 2),
            _item(item_b1, invoice_b, 1),
            _item(item_a1, invoice_a, 1),
            _relation(relation_b, contract_b, invoice_b),
            _relation(relation_a, contract_a, invoice_a),
        ],
    )

    repository = FinancialReadRepository(database_session)
    view = repository.read_for_organization(ORGANIZATION_ID, BASELINE_DATE)

    assert [contract.id for contract in view.contracts] == [contract_a, contract_b]
    assert [agreement.id for agreement in view.supplementary_agreements] == [
        agreement_a,
        agreement_b,
    ]
    assert [invoice.id for invoice in view.invoices] == [invoice_a, invoice_b]
    assert [item.id for item in view.invoices[0].items] == [item_a1, item_a2]
    assert [item.id for item in view.invoices[1].items] == [item_b1]
    assert [relation.id for relation in view.contract_invoices] == [relation_a, relation_b]
    assert type(view.contracts[0].amount) is Decimal
    assert view.contracts[0].amount == Decimal("100.25")
    assert view.contracts[0].effective_date == date(2026, 1, 1)
    assert str(view.invoices[0].items[0].quantity) == "2.125000"
    assert str(view.invoices[0].items[0].unit_price) == "47.176471"
    assert not hasattr(view.contracts[0], "_sa_instance_state")
    assert type(view.contracts) is tuple
    assert type(view.invoices[0].items) is tuple
    with pytest.raises(TypeError):
        cast(dict[str, object], view.invoices[0].field_evidence)["page"] = 2
    with pytest.raises(TypeError):
        cast(dict[str, object], view.contract_invoices[0].match_reasons)["tax_no_match"] = False

    database_session.expunge_all()
    assert repository.read_for_organization(ORGANIZATION_ID, BASELINE_DATE) == view
    assert database_session.in_transaction()


def test_soft_deleted_roots_children_and_relations_are_excluded(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    live_contract = UUID("73000000-0000-4000-8000-000000000011")
    deleted_contract = UUID("73000000-0000-4000-8000-000000000012")
    live_invoice = UUID("74000000-0000-4000-8000-000000000011")
    deleted_invoice = UUID("74000000-0000-4000-8000-000000000012")
    live_agreement = UUID("75000000-0000-4000-8000-000000000011")
    deleted_agreement = UUID("75000000-0000-4000-8000-000000000012")
    hidden_parent_agreement = UUID("75000000-0000-4000-8000-000000000013")
    live_item = UUID("76000000-0000-4000-8000-000000000011")
    hidden_item = UUID("76000000-0000-4000-8000-000000000012")
    live_relation = UUID("77000000-0000-4000-8000-000000000011")

    database_session.add_all(
        [
            _contract(live_contract),
            _contract(deleted_contract, deleted=True),
            _invoice(live_invoice),
            _invoice(deleted_invoice, deleted=True),
        ]
    )
    database_session.flush()
    non_relation_rows = [
        _agreement(live_agreement, live_contract),
        _agreement(deleted_agreement, live_contract, deleted=True),
        _agreement(hidden_parent_agreement, deleted_contract),
        _item(live_item, live_invoice, 1),
        _item(hidden_item, deleted_invoice, 1),
    ]
    _flush_legacy_invoice_items(database_session, non_relation_rows)
    _flush_legacy_relations(
        database_session,
        [
            _relation(live_relation, live_contract, live_invoice),
            _relation(
                UUID("77000000-0000-4000-8000-000000000012"),
                live_contract,
                live_invoice,
                deleted=True,
            ),
            _relation(
                UUID("77000000-0000-4000-8000-000000000013"),
                deleted_contract,
                live_invoice,
            ),
            _relation(
                UUID("77000000-0000-4000-8000-000000000014"),
                live_contract,
                deleted_invoice,
            ),
        ],
    )

    view = FinancialReadRepository(database_session).read_for_organization(
        ORGANIZATION_ID,
        BASELINE_DATE,
    )

    assert [contract.id for contract in view.contracts] == [live_contract]
    assert [agreement.id for agreement in view.supplementary_agreements] == [live_agreement]
    assert [invoice.id for invoice in view.invoices] == [live_invoice]
    assert [item.id for item in view.invoices[0].items] == [live_item]
    assert [relation.id for relation in view.contract_invoices] == [live_relation]


def test_non_finite_decimal_fails_closed_without_value_disclosure(
    database_session: Session,
) -> None:
    _seed_identity(database_session)
    database_session.add(
        _invoice(
            UUID("74000000-0000-4000-8000-000000000021"),
            total_amount=Decimal("NaN"),
        )
    )
    database_session.flush()

    with pytest.raises(FinancialReadIntegrityError) as exc_info:
        FinancialReadRepository(database_session).read_for_organization(
            ORGANIZATION_ID,
            BASELINE_DATE,
        )

    assert str(exc_info.value) == ("invalid persisted financial value at invoices.total_amount")
    assert "NaN" not in repr(exc_info.value)


def test_repository_rejects_non_exact_organization_identifier(
    database_session: Session,
) -> None:
    _seed_identity(database_session)

    with pytest.raises(
        ValueError,
        match="^organization_id must be an exact uuid.UUID$",
    ):
        FinancialReadRepository(database_session).read_for_organization(
            "71000000-0000-4000-8000-000000000001",  # type: ignore[arg-type]
            BASELINE_DATE,
        )
    with pytest.raises(
        ValueError,
        match="^baseline_date must be an exact datetime.date$",
    ):
        FinancialReadRepository(database_session).read_for_organization(
            ORGANIZATION_ID,
            datetime(2026, 6, 1),
        )
