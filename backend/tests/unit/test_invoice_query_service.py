from datetime import date
from decimal import Decimal
from typing import cast
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.financial_read import InvoiceItemReadView, InvoiceReadView
from app.schemas.business_statuses import (
    ConfirmationStatus,
    InvoiceDuplicateStatus,
    InvoiceStatus,
)
from app.schemas.invoices import InvoiceDetailData, InvoiceListData
from app.services.invoice_query import (
    InvoiceQueryService,
    _decode_cursor,
    _project_invoice,
)

INVOICE_ID = UUID("62000000-0000-4000-8000-000000000001")
ITEM_ID = UUID("62000000-0000-4000-8000-000000000002")
ORGANIZATION_ID = UUID("62000000-0000-4000-8000-000000000003")


def _read_view(*, currency: str = "CNY", status: str = "confirmed") -> InvoiceReadView:
    return InvoiceReadView(
        id=INVOICE_ID,
        organization_id=ORGANIZATION_ID,
        invoice_code="3100",
        invoice_number="0001",
        invoice_type="standard",
        invoice_date=date(2026, 8, 12),
        buyer_name="购买方",
        buyer_tax_no=None,
        seller_name="销售方",
        seller_tax_no="91310000TEST00001X",
        supplier_id=UUID("62000000-0000-4000-8000-000000000004"),
        amount_excluding_tax=Decimal("1E+3"),
        tax_amount=Decimal("60.00"),
        total_amount=Decimal("1060.00"),
        currency=currency,
        confirmation_status="confirmed",
        duplicate_status="unique",
        status=status,
        field_evidence={"secret": "must-not-leak"},
        confirmed_by=UUID("62000000-0000-4000-8000-000000000005"),
        confirmed_at=None,
        critical_fact_hash="a" * 64,
        row_version=2,
        items=(
            InvoiceItemReadView(
                id=ITEM_ID,
                invoice_id=INVOICE_ID,
                line_no=1,
                item_name="服务费",
                specification=None,
                unit=None,
                quantity=Decimal("1.000000"),
                unit_price=Decimal("1E+3"),
                amount_excluding_tax=Decimal("1000.00"),
                tax_rate=Decimal("0.060000"),
                tax_amount=Decimal("60.00"),
                total_amount=Decimal("1060.00"),
                evidence={"secret": "must-not-leak"},
                row_version=1,
            ),
        ),
    )


def test_invoice_projection_uses_plain_decimal_strings_and_hides_internal_facts() -> None:
    projected = _project_invoice(_read_view())
    payload = projected.model_dump(mode="json")

    assert payload["amount_excluding_tax"] == "1000"
    assert payload["row_version"] == "2"
    assert payload["items"][0]["unit_price"] == "1000"
    assert payload["items"][0]["row_version"] == "1"
    for value in (
        payload["amount_excluding_tax"],
        payload["tax_amount"],
        payload["total_amount"],
        payload["items"][0]["quantity"],
        payload["items"][0]["unit_price"],
        payload["items"][0]["amount_excluding_tax"],
        payload["items"][0]["tax_rate"],
        payload["items"][0]["tax_amount"],
        payload["items"][0]["total_amount"],
    ):
        assert "E" not in value
    assert set(payload).isdisjoint(
        {"organization_id", "supplier_id", "field_evidence", "confirmed_by", "critical_fact_hash"}
    )
    assert set(payload["items"][0]).isdisjoint({"invoice_id", "evidence"})


@pytest.mark.parametrize(
    ("currency", "status"),
    [("cny", "confirmed"), ("CNY", "unknown")],
)
def test_invoice_projection_rejects_invalid_persisted_public_values(
    currency: str,
    status: str,
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        _project_invoice(_read_view(currency=currency, status=status))


def test_invoice_schema_is_strict_frozen_and_forbids_exponential_decimal_strings() -> None:
    with pytest.raises(ValidationError):
        InvoiceDetailData(
            id=INVOICE_ID,
            invoice_code=None,
            invoice_number=None,
            invoice_type=None,
            is_red_invoice=None,
            invoice_date=None,
            buyer_name=None,
            buyer_tax_no=None,
            seller_name=None,
            seller_tax_no=None,
            amount_excluding_tax="1E+3",
            tax_amount=None,
            total_amount=None,
            currency="CNY",
            confirmation_status=ConfirmationStatus.CONFIRMED,
            duplicate_status=InvoiceDuplicateStatus.UNIQUE,
            status=InvoiceStatus.CONFIRMED,
            row_version="1",
            items=(),
        )


def test_invoice_query_service_uses_organization_boundary_and_maps_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Mock(spec=Session)
    session_context = MagicMock()
    session_context.__enter__.return_value = session
    factory = Mock(return_value=session_context)
    repository = Mock()
    repository.read_invoice.return_value = None
    repository_type = Mock(return_value=repository)
    monkeypatch.setattr("app.services.invoice_query.FinancialReadRepository", repository_type)
    service = InvoiceQueryService(cast(sessionmaker[Session], factory))

    with pytest.raises(AppError) as captured:
        service.get_detail(ORGANIZATION_ID, INVOICE_ID)

    repository_type.assert_called_once_with(session)
    repository.read_invoice.assert_called_once_with(ORGANIZATION_ID, INVOICE_ID)
    assert captured.value.status_code == 404
    assert captured.value.code == "RESOURCE_NOT_FOUND"


def test_invoice_list_service_projects_only_frozen_summary_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Mock(spec=Session)
    session_context = MagicMock()
    session_context.__enter__.return_value = session
    factory = Mock(return_value=session_context)
    repository = Mock()
    repository.read_invoice_page.return_value = ((_read_view(),), True)
    repository_type = Mock(return_value=repository)
    monkeypatch.setattr("app.services.invoice_query.FinancialReadRepository", repository_type)
    service = InvoiceQueryService(cast(sessionmaker[Session], factory))

    result = service.list_page(ORGANIZATION_ID, None, 1)
    payload = result.model_dump(mode="json")

    repository.read_invoice_page.assert_called_once_with(ORGANIZATION_ID, 1, None, None)
    assert payload["items"] == [
        {
            "id": str(INVOICE_ID),
            "invoice_code": "3100",
            "invoice_number": "0001",
            "invoice_date": "2026-08-12",
            "seller_name": "销售方",
            "total_amount": "1060.00",
            "currency": "CNY",
            "confirmation_status": "confirmed",
            "duplicate_status": "unique",
            "status": "confirmed",
        }
    ]
    assert payload["page_size"] == 1
    assert type(payload["next_cursor"]) is str
    assert _decode_cursor(payload["next_cursor"]) == (date(2026, 8, 12), INVOICE_ID)


def test_invoice_list_schema_rejects_cursor_on_partial_page() -> None:
    with pytest.raises(ValidationError):
        InvoiceListData(
            items=(),
            page_size=1,
            next_cursor="canonical_shape_but_inconsistent_page",
        )


def test_invoice_list_service_fails_closed_on_inconsistent_repository_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_context = MagicMock()
    session_context.__enter__.return_value = Mock(spec=Session)
    factory = Mock(return_value=session_context)
    repository = Mock()
    repository.read_invoice_page.return_value = ((_read_view(),), True)
    monkeypatch.setattr(
        "app.services.invoice_query.FinancialReadRepository",
        Mock(return_value=repository),
    )
    service = InvoiceQueryService(cast(sessionmaker[Session], factory))

    with pytest.raises(ValidationError):
        service.list_page(ORGANIZATION_ID, None, 2)


@pytest.mark.parametrize(
    "cursor",
    [
        "not+base64url",
        "abc=",
        "a" * 257,
        "e30",
        "eyJpZCI6IjYyMDAwMDAwLTAwMDAtNDAwMC04MDAwLTAwMDAwMDAwMDAwMSIsImludm9pY2VfZGF0ZSI6bnVsbCwidiI6MX1",
        "eyJ2IjoyLCJpbnZvaWNlX2RhdGUiOm51bGwsImlkIjoiNjIwMDAwMDAtMDAwMC00MDAwLTgwMDAtMDAwMDAwMDAwMDAxIn0",
        "eyJpZCI6IjYyMDAwMDAwLTAwMDAtNDAwMC04MDAwLTAwMDAwMDAwMDAwMSIsImlkIjoiNjIwMDAwMDAtMDAwMC00MDAwLTgwMDAtMDAwMDAwMDAwMDAxIiwiaW52b2ljZV9kYXRlIjpudWxsLCJ2IjoxfQ",
        "eyJleHRyYSI6MCwiaWQiOiI2MjAwMDAwMC0wMDAwLTQwMDAtODAwMC0wMDAwMDAwMDAwMDEiLCJpbnZvaWNlX2RhdGUiOm51bGwsInYiOjF9",
        "eyJ2IjoxLCJpbnZvaWNlX2RhdGUiOm51bGwsImlkIjoiNjIwMDAwMDAtMDAwMC00MDAwLTgwMDAtMDAwMDAwMDAwMDAxIn0",
        "eyJpZCI6ICI2MjAwMDAwMC0wMDAwLTQwMDAtODAwMC0wMDAwMDAwMDAwMDEiLCAiaW52b2ljZV9kYXRlIjogbnVsbCwgInYiOiAxfQ",
    ],
)
def test_invoice_list_service_rejects_untrusted_cursor(cursor: str) -> None:
    service = InvoiceQueryService(cast(sessionmaker[Session], Mock()))

    with pytest.raises(AppError) as captured:
        service.list_page(ORGANIZATION_ID, cursor, 20)

    assert captured.value.status_code == 422
    assert captured.value.code == "VALIDATION_ERROR"
    assert captured.value.details == [{"field": "query.cursor", "reason": "invalid"}]
