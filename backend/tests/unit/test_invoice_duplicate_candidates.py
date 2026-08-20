import base64
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import ClauseElement

from app.core.errors import AppError
from app.repositories.financial_read import (
    FinancialReadRepository,
    InvoiceDuplicateCandidateReadView,
    InvoiceExactDuplicatePairReadView,
)
from app.schemas.business_statuses import (
    ConfirmationStatus,
    InvoiceDuplicateStatus,
    InvoiceStatus,
)
from app.schemas.invoices import (
    InvoiceDuplicateCandidateListData,
    InvoiceExactDuplicatePairData,
    InvoiceExactIdentityData,
    InvoiceListItemData,
)
from app.services.invoice_query import (
    InvoiceQueryService,
    _decode_duplicate_cursor,
    _encode_duplicate_cursor_values,
)

ORGANIZATION_ID = UUID("62100000-0000-4000-8000-000000000001")
SOURCE_ID = UUID("62100000-0000-4000-8000-000000000002")
CANDIDATE_ID = UUID("62100000-0000-4000-8000-000000000003")
NEXT_ID = UUID("62100000-0000-4000-8000-000000000004")
LETTERED_ID = UUID("a2100000-0000-4000-8000-000000000002")


def _candidate(
    identity: UUID = CANDIDATE_ID,
    *,
    status: str = "archived",
) -> InvoiceDuplicateCandidateReadView:
    return InvoiceDuplicateCandidateReadView(
        id=identity,
        invoice_code="INV-CODE",
        invoice_number="INV-NUMBER",
        invoice_date=date(2026, 8, 13),
        seller_name="精确候选销售方",
        total_amount=Decimal("1060.00"),
        currency="CNY",
        confirmation_status="confirmed",
        duplicate_status="suspected",
        status=status,
    )


def _candidate_page_row(
    identity: UUID | None,
    *,
    source_invoice_code: str | None = "INV-CODE",
    source_invoice_number: str | None = "INV-NUMBER",
    source_seller_tax_no: str | None = "91310000SELLER001X",
    source_status: str = "confirmed",
) -> SimpleNamespace:
    candidate = None if identity is None else _candidate(identity)
    return SimpleNamespace(
        source_invoice_code=source_invoice_code,
        source_invoice_number=source_invoice_number,
        source_seller_tax_no=source_seller_tax_no,
        source_status=source_status,
        candidate_id=None if candidate is None else candidate.id,
        candidate_invoice_code=None if candidate is None else candidate.invoice_code,
        candidate_invoice_number=None if candidate is None else candidate.invoice_number,
        candidate_invoice_date=None if candidate is None else candidate.invoice_date,
        candidate_seller_name=None if candidate is None else candidate.seller_name,
        candidate_total_amount=None if candidate is None else candidate.total_amount,
        candidate_currency=None if candidate is None else candidate.currency,
        candidate_confirmation_status=(
            None if candidate is None else candidate.confirmation_status
        ),
        candidate_duplicate_status=None if candidate is None else candidate.duplicate_status,
        candidate_status=None if candidate is None else candidate.status,
    )


def _pair_view(
    source_id: UUID = SOURCE_ID,
    candidate_id: UUID = CANDIDATE_ID,
) -> InvoiceExactDuplicatePairReadView:
    return InvoiceExactDuplicatePairReadView(
        source=_candidate(source_id, status="confirmed"),
        candidate=_candidate(candidate_id),
        invoice_code="INV-CODE",
        invoice_number="INV-NUMBER",
        seller_tax_no="91310000SELLER001X",
    )


def _pair_row() -> SimpleNamespace:
    source = _candidate(SOURCE_ID, status="confirmed")
    candidate = _candidate()
    return SimpleNamespace(
        source_id=source.id,
        source_invoice_code=source.invoice_code,
        source_invoice_number=source.invoice_number,
        source_invoice_date=source.invoice_date,
        source_seller_name=source.seller_name,
        source_total_amount=source.total_amount,
        source_currency=source.currency,
        source_confirmation_status=source.confirmation_status,
        source_duplicate_status=source.duplicate_status,
        source_status=source.status,
        exact_seller_tax_no="91310000SELLER001X",
        candidate_id=candidate.id,
        candidate_invoice_code=candidate.invoice_code,
        candidate_invoice_number=candidate.invoice_number,
        candidate_invoice_date=candidate.invoice_date,
        candidate_seller_name=candidate.seller_name,
        candidate_total_amount=candidate.total_amount,
        candidate_currency=candidate.currency,
        candidate_confirmation_status=candidate.confirmation_status,
        candidate_duplicate_status=candidate.duplicate_status,
        candidate_status=candidate.status,
    )


def _item(
    identity: UUID = CANDIDATE_ID,
    *,
    status: InvoiceStatus = InvoiceStatus.ARCHIVED,
) -> InvoiceListItemData:
    return InvoiceListItemData(
        id=identity,
        invoice_code="INV-CODE",
        invoice_number="INV-NUMBER",
        invoice_date=date(2026, 8, 13),
        seller_name="精确候选销售方",
        total_amount="1060.00",
        currency="CNY",
        confirmation_status=ConfirmationStatus.CONFIRMED,
        duplicate_status=InvoiceDuplicateStatus.SUSPECTED,
        status=status,
    )


def _raw_cursor(payload: str) -> str:
    return base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()


def test_duplicate_candidate_schema_enforces_basis_and_strict_id_order() -> None:
    valid = InvoiceDuplicateCandidateListData(
        basis_status="ready",
        items=(_item(CANDIDATE_ID), _item(NEXT_ID)),
        page_size=2,
        next_cursor="canonical_cursor",
    )
    assert valid.items[0].id == CANDIDATE_ID

    with pytest.raises(ValidationError):
        InvoiceDuplicateCandidateListData(
            basis_status="ready",
            items=(_item(NEXT_ID), _item(CANDIDATE_ID)),
            page_size=2,
            next_cursor=None,
        )
    with pytest.raises(ValidationError):
        InvoiceDuplicateCandidateListData(
            basis_status="incomplete_identity",
            items=(_item(),),
            page_size=20,
            next_cursor=None,
        )
    with pytest.raises(ValidationError):
        InvoiceDuplicateCandidateListData(
            basis_status="source_voided",
            items=(),
            page_size=20,
            next_cursor="forbidden_cursor",
        )
    with pytest.raises(ValidationError):
        InvoiceDuplicateCandidateListData(
            basis_status="ready",
            items=(_item(status=InvoiceStatus.VOIDED),),
            page_size=20,
            next_cursor=None,
        )


def test_duplicate_candidate_service_projects_exact_public_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Mock(spec=Session)
    context = MagicMock()
    context.__enter__.return_value = session
    factory = Mock(return_value=context)
    repository = Mock()
    repository.read_invoice_duplicate_candidate_page.return_value = (
        "ready",
        (_candidate(),),
        True,
    )
    monkeypatch.setattr(
        "app.services.invoice_query.FinancialReadRepository",
        Mock(return_value=repository),
    )
    service = InvoiceQueryService(cast(sessionmaker[Session], factory))

    result = service.list_duplicate_candidates(ORGANIZATION_ID, SOURCE_ID, None, 1)
    payload = result.model_dump(mode="json")

    repository.read_invoice_duplicate_candidate_page.assert_called_once_with(
        ORGANIZATION_ID,
        SOURCE_ID,
        1,
        None,
    )
    assert payload == {
        "basis_status": "ready",
        "items": [
            {
                "id": str(CANDIDATE_ID),
                "invoice_code": "INV-CODE",
                "invoice_number": "INV-NUMBER",
                "invoice_date": "2026-08-13",
                "seller_name": "精确候选销售方",
                "total_amount": "1060.00",
                "currency": "CNY",
                "confirmation_status": "confirmed",
                "duplicate_status": "suspected",
                "status": "archived",
            }
        ],
        "page_size": 1,
        "next_cursor": _encode_duplicate_cursor_values(CANDIDATE_ID),
    }


@pytest.mark.parametrize("basis_status", ["incomplete_identity", "source_voided"])
def test_duplicate_candidate_service_preserves_non_ready_basis(
    monkeypatch: pytest.MonkeyPatch,
    basis_status: str,
) -> None:
    context = MagicMock()
    context.__enter__.return_value = Mock(spec=Session)
    repository = Mock()
    repository.read_invoice_duplicate_candidate_page.return_value = (
        basis_status,
        (),
        False,
    )
    monkeypatch.setattr(
        "app.services.invoice_query.FinancialReadRepository",
        Mock(return_value=repository),
    )
    service = InvoiceQueryService(cast(sessionmaker[Session], Mock(return_value=context)))

    result = service.list_duplicate_candidates(ORGANIZATION_ID, SOURCE_ID, None, 20)

    assert result.basis_status == basis_status
    assert result.items == ()
    assert result.next_cursor is None


def test_duplicate_candidate_service_maps_hidden_source_to_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = MagicMock()
    context.__enter__.return_value = Mock(spec=Session)
    repository = Mock()
    repository.read_invoice_duplicate_candidate_page.return_value = None
    monkeypatch.setattr(
        "app.services.invoice_query.FinancialReadRepository",
        Mock(return_value=repository),
    )
    service = InvoiceQueryService(cast(sessionmaker[Session], Mock(return_value=context)))

    with pytest.raises(AppError) as captured:
        service.list_duplicate_candidates(ORGANIZATION_ID, SOURCE_ID, None, 20)

    assert captured.value.status_code == 404
    assert captured.value.code == "RESOURCE_NOT_FOUND"


@pytest.mark.parametrize(
    "cursor",
    [
        "not+base64url",
        "abc=",
        "a" * 257,
        "e30",
        _raw_cursor(f'{{"id":"{SOURCE_ID}","id":"{SOURCE_ID}","v":1}}'),
        _raw_cursor(f'{{"extra":0,"id":"{SOURCE_ID}","v":1}}'),
        _raw_cursor(f'{{"id":"{SOURCE_ID}","v":true}}'),
        _raw_cursor(f'{{"id":"{str(LETTERED_ID).upper()}","v":1}}'),
        _raw_cursor(f'{{"id":"{SOURCE_ID.hex}","v":1}}'),
        _raw_cursor(f'{{"v":1,"id":"{SOURCE_ID}"}}'),
        _raw_cursor(json.dumps({"id": str(SOURCE_ID), "v": 1})),
    ],
)
def test_duplicate_cursor_is_strict_and_checked_before_database(cursor: str) -> None:
    factory = Mock()
    service = InvoiceQueryService(cast(sessionmaker[Session], factory))

    with pytest.raises(AppError) as captured:
        service.list_duplicate_candidates(ORGANIZATION_ID, SOURCE_ID, cursor, 20)

    assert captured.value.status_code == 422
    assert captured.value.details == [{"field": "query.cursor", "reason": "invalid"}]
    assert cursor not in str(captured.value)
    factory.assert_not_called()


def test_duplicate_cursor_round_trips_canonical_uuid() -> None:
    cursor = _encode_duplicate_cursor_values(CANDIDATE_ID)

    assert "=" not in cursor
    assert _decode_duplicate_cursor(cursor) == CANDIDATE_ID


def test_repository_uses_exact_bounded_minimal_projection() -> None:
    session = Mock(spec=Session)
    result_rows = Mock()
    result_rows.all.return_value = [
        _candidate_page_row(CANDIDATE_ID),
        _candidate_page_row(NEXT_ID),
    ]
    session.execute.return_value = result_rows

    result = FinancialReadRepository(session).read_invoice_duplicate_candidate_page(
        ORGANIZATION_ID,
        SOURCE_ID,
        1,
        UUID(int=CANDIDATE_ID.int - 1),
    )

    assert result == ("ready", (_candidate(CANDIDATE_ID),), True)
    assert session.execute.call_count == 1
    statement = cast(ClauseElement, session.execute.call_args.args[0])
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    sql = str(statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    assert "WITH duplicate_source AS" in sql
    assert "invoices.organization_id" in sql
    assert "invoices.deleted_at IS NULL" in sql
    assert "LEFT OUTER JOIN invoices AS candidate_invoice" in sql
    assert "candidate_invoice.id !=" in sql
    assert "candidate_invoice.status != 'voided'" in sql
    assert "candidate_invoice.invoice_code = duplicate_source.invoice_code" in sql
    assert "candidate_invoice.invoice_number = duplicate_source.invoice_number" in sql
    assert "candidate_invoice.seller_tax_no = duplicate_source.seller_tax_no" in sql
    assert "candidate_invoice.id >" in sql
    assert "ORDER BY candidate_invoice.id ASC NULLS LAST" in sql
    assert "LIMIT 2" in sql
    assert "OFFSET" not in sql
    for private_column in (
        "invoices.supplier_id",
        "invoices.field_evidence_json",
        "invoices.confirmed_by",
        "invoices.critical_fact_hash",
        "invoices.created_by",
        "invoices.row_version",
    ):
        assert private_column not in sql
    assert "candidate_invoice.seller_tax_no AS" not in sql


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            _candidate_page_row(
                None,
                source_invoice_code=None,
                source_status="voided",
            ),
            ("source_voided", (), False),
        ),
        (
            _candidate_page_row(
                None,
                source_invoice_number=None,
            ),
            ("incomplete_identity", (), False),
        ),
    ],
)
def test_repository_non_ready_basis_returns_from_single_statement(
    source: SimpleNamespace,
    expected: object,
) -> None:
    session = Mock(spec=Session)
    statement_result = Mock()
    statement_result.all.return_value = [source]
    session.execute.return_value = statement_result

    result = FinancialReadRepository(session).read_invoice_duplicate_candidate_page(
        ORGANIZATION_ID,
        SOURCE_ID,
        20,
    )

    assert result == expected
    assert session.execute.call_count == 1


def test_exact_duplicate_pair_schema_enforces_cross_field_identity() -> None:
    valid = InvoiceExactDuplicatePairData(
        source=_item(SOURCE_ID, status=InvoiceStatus.CONFIRMED),
        candidate=_item(),
        exact_identity=InvoiceExactIdentityData(
            invoice_code="INV-CODE",
            invoice_number="INV-NUMBER",
            seller_tax_no="91310000SELLER001X",
        ),
    )
    assert valid.source.id == SOURCE_ID

    for source, candidate, exact_identity in (
        (
            _item(CANDIDATE_ID, status=InvoiceStatus.CONFIRMED),
            _item(),
            valid.exact_identity,
        ),
        (
            _item(SOURCE_ID, status=InvoiceStatus.VOIDED),
            _item(),
            valid.exact_identity,
        ),
        (
            _item(SOURCE_ID, status=InvoiceStatus.CONFIRMED),
            _item(),
            InvoiceExactIdentityData(
                invoice_code="OTHER",
                invoice_number="INV-NUMBER",
                seller_tax_no="91310000SELLER001X",
            ),
        ),
    ):
        with pytest.raises(ValidationError):
            InvoiceExactDuplicatePairData(
                source=source,
                candidate=candidate,
                exact_identity=exact_identity,
            )


def test_exact_duplicate_pair_schema_preserves_blank_raw_identity() -> None:
    source = InvoiceListItemData(
        id=SOURCE_ID,
        invoice_code="",
        invoice_number=" ",
        invoice_date=None,
        seller_name=None,
        total_amount=None,
        currency="CNY",
        confirmation_status=ConfirmationStatus.UNCONFIRMED,
        duplicate_status=InvoiceDuplicateStatus.NOT_CHECKED,
        status=InvoiceStatus.DRAFT,
    )
    candidate = source.model_copy(update={"id": CANDIDATE_ID})

    result = InvoiceExactDuplicatePairData(
        source=source,
        candidate=candidate,
        exact_identity=InvoiceExactIdentityData(
            invoice_code="",
            invoice_number=" ",
            seller_tax_no="",
        ),
    )

    assert result.exact_identity.seller_tax_no == ""


def test_exact_duplicate_pair_service_projects_and_binds_path_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = MagicMock()
    context.__enter__.return_value = Mock(spec=Session)
    repository = Mock()
    repository.read_invoice_exact_duplicate_pair.return_value = _pair_view()
    monkeypatch.setattr(
        "app.services.invoice_query.FinancialReadRepository",
        Mock(return_value=repository),
    )
    service = InvoiceQueryService(cast(sessionmaker[Session], Mock(return_value=context)))

    result = service.get_exact_duplicate_pair(ORGANIZATION_ID, SOURCE_ID, CANDIDATE_ID)

    repository.read_invoice_exact_duplicate_pair.assert_called_once_with(
        ORGANIZATION_ID,
        SOURCE_ID,
        CANDIDATE_ID,
    )
    assert result.model_dump(mode="json") == {
        "source": {
            "id": str(SOURCE_ID),
            "invoice_code": "INV-CODE",
            "invoice_number": "INV-NUMBER",
            "invoice_date": "2026-08-13",
            "seller_name": "精确候选销售方",
            "total_amount": "1060.00",
            "currency": "CNY",
            "confirmation_status": "confirmed",
            "duplicate_status": "suspected",
            "status": "confirmed",
        },
        "candidate": {
            "id": str(CANDIDATE_ID),
            "invoice_code": "INV-CODE",
            "invoice_number": "INV-NUMBER",
            "invoice_date": "2026-08-13",
            "seller_name": "精确候选销售方",
            "total_amount": "1060.00",
            "currency": "CNY",
            "confirmation_status": "confirmed",
            "duplicate_status": "suspected",
            "status": "archived",
        },
        "exact_identity": {
            "invoice_code": "INV-CODE",
            "invoice_number": "INV-NUMBER",
            "seller_tax_no": "91310000SELLER001X",
        },
    }


@pytest.mark.parametrize(
    "pair",
    [
        _pair_view(source_id=NEXT_ID),
        _pair_view(candidate_id=NEXT_ID),
        _pair_view(source_id=CANDIDATE_ID, candidate_id=SOURCE_ID),
    ],
)
def test_exact_duplicate_pair_service_rejects_unbound_repository_ids(
    monkeypatch: pytest.MonkeyPatch,
    pair: InvoiceExactDuplicatePairReadView,
) -> None:
    context = MagicMock()
    context.__enter__.return_value = Mock(spec=Session)
    repository = Mock()
    repository.read_invoice_exact_duplicate_pair.return_value = pair
    monkeypatch.setattr(
        "app.services.invoice_query.FinancialReadRepository",
        Mock(return_value=repository),
    )
    service = InvoiceQueryService(cast(sessionmaker[Session], Mock(return_value=context)))

    with pytest.raises(ValueError, match="invalid exact duplicate pair repository projection"):
        service.get_exact_duplicate_pair(ORGANIZATION_ID, SOURCE_ID, CANDIDATE_ID)


def test_exact_duplicate_pair_service_maps_all_misses_and_self_pair_to_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = MagicMock()
    context.__enter__.return_value = Mock(spec=Session)
    repository = Mock()
    repository.read_invoice_exact_duplicate_pair.return_value = None
    monkeypatch.setattr(
        "app.services.invoice_query.FinancialReadRepository",
        Mock(return_value=repository),
    )
    service = InvoiceQueryService(cast(sessionmaker[Session], Mock(return_value=context)))

    for candidate_id in (CANDIDATE_ID, SOURCE_ID):
        with pytest.raises(AppError) as captured:
            service.get_exact_duplicate_pair(ORGANIZATION_ID, SOURCE_ID, candidate_id)
        assert captured.value.status_code == 404
        assert captured.value.code == "RESOURCE_NOT_FOUND"


def test_exact_duplicate_pair_repository_uses_one_minimal_self_join_statement() -> None:
    session = Mock(spec=Session)
    result = Mock()
    result.one_or_none.return_value = _pair_row()
    session.execute.return_value = result

    pair = FinancialReadRepository(session).read_invoice_exact_duplicate_pair(
        ORGANIZATION_ID,
        SOURCE_ID,
        CANDIDATE_ID,
    )

    assert pair == _pair_view()
    session.execute.assert_called_once()
    statement = cast(ClauseElement, session.execute.call_args.args[0])
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "FROM invoices AS source_invoice JOIN invoices AS candidate_invoice" in sql
    assert "source_invoice.id != candidate_invoice.id" in sql
    assert "source_invoice.organization_id" in sql
    assert "candidate_invoice.organization_id" in sql
    assert "source_invoice.deleted_at IS NULL" in sql
    assert "candidate_invoice.deleted_at IS NULL" in sql
    assert "source_invoice.status != 'voided'" in sql
    assert "candidate_invoice.status != 'voided'" in sql
    assert "source_invoice.invoice_code IS NOT NULL" in sql
    assert "source_invoice.invoice_number IS NOT NULL" in sql
    assert "source_invoice.seller_tax_no IS NOT NULL" in sql
    assert "candidate_invoice.invoice_code = source_invoice.invoice_code" in sql
    assert "candidate_invoice.invoice_number = source_invoice.invoice_number" in sql
    assert "candidate_invoice.seller_tax_no = source_invoice.seller_tax_no" in sql
    assert "COUNT" not in sql
    assert "ORDER BY" not in sql
    assert "OFFSET" not in sql
    selected = sql.split("FROM", 1)[0]
    for private_column in (
        "organization_id",
        "supplier_id",
        "field_evidence_json",
        "confirmed_by",
        "critical_fact_hash",
        "row_version",
    ):
        assert private_column not in selected
