import base64
from datetime import date
from decimal import Decimal
from typing import cast
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateIndex

from app.core.errors import AppError
from app.models.financial import ContractInvoice
from app.repositories.financial_read import FinancialReadRepository, InvoiceReadView
from app.schemas.invoices import (
    ContractPrimaryInvoiceListData,
    ContractPrimaryInvoiceListQuery,
)
from app.services.contract_primary_invoice_query import (
    ContractPrimaryInvoiceQueryService,
    _decode_cursor,
    _encode_cursor_values,
)
from app.services.invoice_query import project_invoice_list_item

ORGANIZATION_ID = UUID("68000000-0000-4000-8000-000000000001")
CONTRACT_ID = UUID("68000000-0000-4000-8000-000000000002")
INVOICE_ID = UUID("68000000-0000-4000-8000-000000000003")


def _view(identity: UUID = INVOICE_ID, *, currency: str = "CNY") -> InvoiceReadView:
    return InvoiceReadView(
        id=identity,
        organization_id=ORGANIZATION_ID,
        invoice_code="INV-CODE",
        invoice_number="INV-NUMBER",
        invoice_type="standard",
        invoice_date=date(2026, 8, 1),
        buyer_name="buyer",
        buyer_tax_no="buyer-tax",
        seller_name="seller",
        seller_tax_no="seller-tax",
        supplier_id=None,
        amount_excluding_tax=Decimal("80.12"),
        tax_amount=Decimal("20.13"),
        total_amount=Decimal("1E+3"),
        currency=currency,
        confirmation_status="confirmed",
        duplicate_status="unique",
        status="confirmed",
        field_evidence={"private": True},
        confirmed_by=None,
        confirmed_at=None,
        critical_fact_hash="a" * 64,
        row_version=3,
        items=(),
    )


def _service(
    repository: Mock, monkeypatch: pytest.MonkeyPatch
) -> ContractPrimaryInvoiceQueryService:
    context = MagicMock()
    context.__enter__.return_value = Mock(spec=Session)
    monkeypatch.setattr(
        "app.services.contract_primary_invoice_query.FinancialReadRepository",
        Mock(return_value=repository),
    )
    return ContractPrimaryInvoiceQueryService(
        cast(sessionmaker[Session], Mock(return_value=context))
    )


def _raw_cursor(payload: str) -> str:
    return base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()


def _raw_bytes_cursor(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def _alias_pad_bits(cursor: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    index = alphabet.index(cursor[-1])
    return cursor[:-1] + alphabet[index | 1]


def test_service_projects_exact_invoice_summary_and_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock()
    repository.read_contract_primary_invoice_page.return_value = ((_view(),), True)
    service = _service(repository, monkeypatch)

    result = service.list_page(ORGANIZATION_ID, CONTRACT_ID, None, 1)

    repository.read_contract_primary_invoice_page.assert_called_once_with(
        ORGANIZATION_ID, CONTRACT_ID, 1, None
    )
    assert result.next_cursor is not None
    assert _decode_cursor(result.next_cursor) == INVOICE_ID
    assert result.model_dump(mode="json")["items"] == [
        {
            "id": str(INVOICE_ID),
            "invoice_code": "INV-CODE",
            "invoice_number": "INV-NUMBER",
            "invoice_date": "2026-08-01",
            "seller_name": "seller",
            "total_amount": "1000",
            "currency": "CNY",
            "confirmation_status": "confirmed",
            "duplicate_status": "unique",
            "status": "confirmed",
        }
    ]
    rendered = result.model_dump_json()
    assert "organization_id" not in rendered
    assert "field_evidence" not in rendered
    assert "row_version" not in rendered


def test_service_maps_invisible_parent_to_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = Mock()
    repository.read_contract_primary_invoice_page.return_value = None

    with pytest.raises(AppError) as captured:
        _service(repository, monkeypatch).list_page(ORGANIZATION_ID, CONTRACT_ID, None, 20)

    assert captured.value.status_code == 404
    assert captured.value.code == "RESOURCE_NOT_FOUND"


def test_projection_and_page_schema_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = Mock()
    repository.read_contract_primary_invoice_page.return_value = (
        (_view(currency="cny"),),
        False,
    )
    with pytest.raises(ValidationError):
        _service(repository, monkeypatch).list_page(ORGANIZATION_ID, CONTRACT_ID, None, 20)

    with pytest.raises(ValidationError):
        ContractPrimaryInvoiceListData(items=(), page_size=1, next_cursor="invalid")
    with pytest.raises(ValidationError):
        ContractPrimaryInvoiceListData(
            items=(
                project_invoice_list_item(_view(INVOICE_ID)),
                project_invoice_list_item(_view(UUID(int=INVOICE_ID.int - 1))),
            ),
            page_size=2,
            next_cursor=None,
        )


def test_public_list_schemas_are_strict_frozen_and_extra_forbid() -> None:
    query = ContractPrimaryInvoiceListQuery()
    data = ContractPrimaryInvoiceListData(items=(), page_size=20, next_cursor=None)

    with pytest.raises(ValidationError):
        ContractPrimaryInvoiceListQuery.model_validate({"page": 1})
    with pytest.raises(ValidationError):
        ContractPrimaryInvoiceListData(
            items=(),
            page_size=20,
            next_cursor=None,
            private="sentinel",  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        query.page_size = 1
    with pytest.raises(ValidationError):
        data.next_cursor = "mutated"


@pytest.mark.parametrize(
    "cursor",
    [
        "not+url",
        "abc=",
        "a" * 257,
        "e30",
        _alias_pad_bits("e30"),
        _raw_cursor('{"id":"68000000-0000-4000-8000-000000000003","v":1,"v":1}'),
        _raw_cursor('{"extra":null,"id":"68000000-0000-4000-8000-000000000003","v":1}'),
        _raw_cursor('{"id":"68000000-0000-4000-8000-000000000003","v":true}'),
        _raw_cursor('{"id":"68000000-0000-4000-8000-000000000003","v":2}'),
        _raw_cursor('{"id":"68000000-0000-4000-8000-00000000000A","v":1}'),
        _raw_cursor('{"id":"68000000000040008000000000000003","v":1}'),
        _raw_cursor('{"id":null,"v":1}'),
        _raw_cursor('{"v":1,"id":"68000000-0000-4000-8000-000000000003"}'),
        _raw_cursor('{ "v": 1, "id": "68000000-0000-4000-8000-000000000003" }'),
        _raw_bytes_cursor(b"\xff"),
    ],
)
def test_service_rejects_untrusted_cursor(cursor: str) -> None:
    service = ContractPrimaryInvoiceQueryService(cast(sessionmaker[Session], Mock()))

    with pytest.raises(AppError) as captured:
        service.list_page(ORGANIZATION_ID, CONTRACT_ID, cursor, 20)

    assert captured.value.status_code == 422
    assert captured.value.code == "VALIDATION_ERROR"
    assert captured.value.details == [{"field": "query.cursor", "reason": "invalid"}]


def test_cursor_round_trips_canonical_id() -> None:
    cursor = _encode_cursor_values(INVOICE_ID)

    assert "=" not in cursor
    assert _decode_cursor(cursor) == INVOICE_ID


def test_repository_uses_parent_scoped_active_pair_keyset_statement() -> None:
    session = Mock(spec=Session)
    session.scalar.return_value = CONTRACT_ID
    session.scalars.return_value.all.return_value = []
    repository = FinancialReadRepository(session)

    result = repository.read_contract_primary_invoice_page(
        ORGANIZATION_ID,
        CONTRACT_ID,
        2,
        INVOICE_ID,
    )

    assert result == ((), False)
    anchor_sql = str(session.scalar.call_args.args[0])
    page_sql = str(
        session.scalars.call_args.args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "contracts.organization_id" in anchor_sql
    assert "contracts.deleted_at IS NULL" in anchor_sql
    assert f"contract_invoices.contract_id = '{CONTRACT_ID}'" in page_sql
    assert "contract_invoices.status = 'confirmed_primary'" in page_sql
    assert "contract_invoices.deleted_at IS NULL" in page_sql
    assert f"contract_invoices.invoice_id > '{INVOICE_ID}'" in page_sql
    assert "contracts.organization_id" in page_sql
    assert "contracts.deleted_at IS NULL" in page_sql
    assert "invoices.organization_id" in page_sql
    assert "invoices.deleted_at IS NULL" in page_sql
    assert "ORDER BY contract_invoices.invoice_id ASC" in page_sql
    assert "LIMIT 3" in page_sql
    assert "OFFSET" not in page_sql
    active_pair_index = next(
        index
        for index in ContractInvoice.__table__.indexes
        if index.name == "uq_contract_invoice_pair_active"
    )
    index_sql = " ".join(
        str(CreateIndex(active_pair_index).compile(dialect=postgresql.dialect())).split()
    )
    assert index_sql.endswith(
        "(contract_id, invoice_id) WHERE deleted_at IS NULL AND status <> 'cancelled'"
    )
