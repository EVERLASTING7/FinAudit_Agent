import base64
from datetime import date
from decimal import Decimal
from typing import cast
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.financial_read import ContractReadView
from app.schemas.contracts import ContractListData
from app.services.contract_query import (
    ContractQueryService,
    _decode_cursor,
    _encode_cursor_values,
    _project_detail,
)

ORGANIZATION_ID = UUID("63000000-0000-4000-8000-000000000001")
CONTRACT_ID = UUID("63000000-0000-4000-8000-000000000002")


def _view(*, currency: str | None = "CNY", status: str = "active") -> ContractReadView:
    return ContractReadView(
        id=CONTRACT_ID,
        organization_id=ORGANIZATION_ID,
        contract_no="HT-001",
        name="采购合同",
        party_a_name="甲方",
        party_a_tax_no="A-TAX",
        party_b_name="乙方",
        party_b_tax_no="B-TAX",
        supplier_id=UUID("63000000-0000-4000-8000-000000000003"),
        amount=Decimal("1E+3"),
        currency=currency,
        signed_date=date(2026, 1, 1),
        effective_date=date(2026, 2, 1),
        expiry_date=date(2026, 12, 31),
        payment_method="bank",
        payment_terms="30 days",
        confirmation_status="confirmed",
        status=status,
        confirmed_by=UUID("63000000-0000-4000-8000-000000000004"),
        confirmed_at=None,
        critical_fact_hash="a" * 64,
        row_version=2,
    )


def _service(repository: Mock, monkeypatch: pytest.MonkeyPatch) -> ContractQueryService:
    context = MagicMock()
    context.__enter__.return_value = Mock(spec=Session)
    monkeypatch.setattr(
        "app.services.contract_query.FinancialReadRepository",
        Mock(return_value=repository),
    )
    return ContractQueryService(cast(sessionmaker[Session], Mock(return_value=context)))


def _raw_cursor(payload: str) -> str:
    return base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()


def test_contract_detail_projection_is_exact_and_plain_decimal() -> None:
    payload = _project_detail(_view()).model_dump(mode="json")

    assert payload["amount"] == "1000"
    assert payload["row_version"] == "2"
    assert set(payload).isdisjoint(
        {"organization_id", "supplier_id", "critical_fact_hash", "confirmed_by"}
    )


@pytest.mark.parametrize(("currency", "status"), [("cny", "active"), ("CNY", "bad")])
def test_contract_detail_projection_rejects_invalid_persisted_public_values(
    currency: str,
    status: str,
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        _project_detail(_view(currency=currency, status=status))


def test_contract_service_maps_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = Mock()
    repository.read_contract.return_value = None
    service = _service(repository, monkeypatch)

    with pytest.raises(AppError) as captured:
        service.get_detail(ORGANIZATION_ID, CONTRACT_ID)

    assert captured.value.status_code == 404
    assert captured.value.code == "RESOURCE_NOT_FOUND"


def test_contract_list_projects_cursor_and_rejects_partial_cursor_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock()
    repository.read_contract_page.return_value = ((_view(),), True)
    service = _service(repository, monkeypatch)

    result = service.list_page(ORGANIZATION_ID, None, 1)

    assert result.next_cursor is not None
    assert _decode_cursor(result.next_cursor) == (date(2026, 2, 1), CONTRACT_ID)
    assert result.items[0].amount == "1000"
    repository.read_contract_page.return_value = ((_view(),), True)
    with pytest.raises(ValidationError):
        service.list_page(ORGANIZATION_ID, None, 2)


@pytest.mark.parametrize(
    "cursor",
    [
        "not+url",
        "abc=",
        "a" * 257,
        "e30",
        _raw_cursor(
            '{"effective_date":"2026-02-01","id":'
            '"63000000-0000-4000-8000-000000000002","v":1,"v":1}'
        ),
        _raw_cursor(
            '{"effective_date":"2026-02-01","extra":null,"id":'
            '"63000000-0000-4000-8000-000000000002","v":1}'
        ),
        _raw_cursor(
            '{"effective_date":"2026-02-01","id":"63000000-0000-4000-8000-000000000002","v":true}'
        ),
        _raw_cursor(
            '{"effective_date":"2026-02-01","id":"63000000-0000-4000-8000-000000000002","v":2}'
        ),
        _raw_cursor(
            '{"effective_date":"2026-02-01","id":"63000000-0000-4000-8000-00000000000A","v":1}'
        ),
        _raw_cursor(
            '{"effective_date":"2026-02-30","id":"63000000-0000-4000-8000-000000000002","v":1}'
        ),
        _raw_cursor(
            '{"effective_date":"2026-2-1","id":"63000000-0000-4000-8000-000000000002","v":1}'
        ),
        _raw_cursor(
            '{ "v": 1, "id": "63000000-0000-4000-8000-000000000002", '
            '"effective_date": "2026-02-01" }'
        ),
    ],
)
def test_contract_cursor_rejects_untrusted_values(
    cursor: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(Mock(), monkeypatch)
    with pytest.raises(AppError) as captured:
        service.list_page(ORGANIZATION_ID, cursor, 20)
    assert captured.value.code == "VALIDATION_ERROR"


@pytest.mark.parametrize("effective_date", [date(2026, 2, 1), None])
def test_contract_cursor_round_trips_canonical_date_and_null(
    effective_date: date | None,
) -> None:
    cursor = _encode_cursor_values(effective_date, CONTRACT_ID)

    assert "=" not in cursor
    assert _decode_cursor(cursor) == (effective_date, CONTRACT_ID)


def test_contract_list_schema_enforces_full_page_cursor_invariant() -> None:
    with pytest.raises(ValidationError):
        ContractListData(items=(), page_size=1, next_cursor="cursor")
