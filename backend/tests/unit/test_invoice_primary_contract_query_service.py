from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from typing import cast
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.financial_read import (
    ContractReadView,
    FinancialReadRepository,
    InvoicePrimaryContractReadView,
)
from app.schemas.invoices import InvoicePrimaryContractData
from app.services.invoice_primary_contract_query import InvoicePrimaryContractQueryService

ORGANIZATION_ID = UUID("65000000-0000-4000-8000-000000000001")
INVOICE_ID = UUID("65000000-0000-4000-8000-000000000002")
CONTRACT_ID = UUID("65000000-0000-4000-8000-000000000003")


def _contract(*, currency: str | None = "CNY", status: str = "active") -> ContractReadView:
    return ContractReadView(
        id=CONTRACT_ID,
        organization_id=ORGANIZATION_ID,
        contract_no="HT-001",
        name="采购合同",
        party_a_name="甲方",
        party_a_tax_no="A-TAX",
        party_b_name="乙方",
        party_b_tax_no="B-TAX",
        supplier_id=UUID("65000000-0000-4000-8000-000000000004"),
        amount=Decimal("1E+3"),
        currency=currency,
        signed_date=date(2026, 1, 1),
        effective_date=date(2026, 2, 1),
        expiry_date=date(2026, 12, 31),
        payment_method="bank",
        payment_terms="30 days",
        confirmation_status="confirmed",
        status=status,
        confirmed_by=UUID("65000000-0000-4000-8000-000000000005"),
        confirmed_at=None,
        critical_fact_hash="a" * 64,
        row_version=7,
    )


def _service(
    repository: Mock, monkeypatch: pytest.MonkeyPatch
) -> InvoicePrimaryContractQueryService:
    context = MagicMock()
    context.__enter__.return_value = Mock(spec=Session)
    monkeypatch.setattr(
        "app.services.invoice_primary_contract_query.FinancialReadRepository",
        Mock(return_value=repository),
    )
    return InvoicePrimaryContractQueryService(
        cast(sessionmaker[Session], Mock(return_value=context))
    )


def test_primary_contract_projects_only_existing_contract_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock()
    repository.read_invoice_primary_contract.return_value = InvoicePrimaryContractReadView(
        primary_contract=_contract()
    )
    service = _service(repository, monkeypatch)

    result = service.get(ORGANIZATION_ID, INVOICE_ID)

    repository.read_invoice_primary_contract.assert_called_once_with(ORGANIZATION_ID, INVOICE_ID)
    assert result.model_dump(mode="json") == {
        "primary_contract": {
            "id": str(CONTRACT_ID),
            "contract_no": "HT-001",
            "name": "采购合同",
            "party_b_name": "乙方",
            "amount": "1000",
            "currency": "CNY",
            "effective_date": "2026-02-01",
            "expiry_date": "2026-12-31",
            "confirmation_status": "confirmed",
            "status": "active",
        }
    }
    assert "organization_id" not in result.model_dump_json()
    assert "row_version" not in result.model_dump_json()


def test_primary_contract_returns_null_for_visible_unlinked_invoice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock()
    repository.read_invoice_primary_contract.return_value = InvoicePrimaryContractReadView(
        primary_contract=None
    )

    result = _service(repository, monkeypatch).get(ORGANIZATION_ID, INVOICE_ID)

    assert result == InvoicePrimaryContractData(primary_contract=None)


def test_primary_contract_maps_invisible_invoice_to_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock()
    repository.read_invoice_primary_contract.return_value = None

    with pytest.raises(AppError) as captured:
        _service(repository, monkeypatch).get(ORGANIZATION_ID, INVOICE_ID)

    assert captured.value.status_code == 404
    assert captured.value.code == "RESOURCE_NOT_FOUND"


@pytest.mark.parametrize(
    ("currency", "status"),
    [("cny", "active"), ("CNY", "invalid")],
)
def test_primary_contract_fails_closed_on_invalid_persisted_public_values(
    currency: str,
    status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock()
    repository.read_invoice_primary_contract.return_value = InvoicePrimaryContractReadView(
        primary_contract=_contract(currency=currency, status=status)
    )

    with pytest.raises((ValidationError, ValueError)):
        _service(repository, monkeypatch).get(ORGANIZATION_ID, INVOICE_ID)


def test_primary_contract_schema_is_strict_and_frozen() -> None:
    data = InvoicePrimaryContractData(primary_contract=None)
    with pytest.raises(ValidationError):
        InvoicePrimaryContractData(primary_contract=None, extra="forbidden")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        data.primary_contract = None
    with pytest.raises(FrozenInstanceError):
        InvoicePrimaryContractReadView(primary_contract=None).primary_contract = _contract()


def test_primary_contract_repository_statement_enforces_both_organization_boundaries() -> None:
    session = Mock(spec=Session)
    session.scalar.return_value = INVOICE_ID
    session.execute.return_value.scalar_one_or_none.return_value = None
    repository = FinancialReadRepository(session)

    result = repository.read_invoice_primary_contract(ORGANIZATION_ID, INVOICE_ID)

    assert result == InvoicePrimaryContractReadView(primary_contract=None)
    anchor_sql = str(session.scalar.call_args.args[0])
    primary_statement = session.execute.call_args.args[0]
    primary_sql = str(
        primary_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "invoices.organization_id" in anchor_sql
    assert "invoices.deleted_at IS NULL" in anchor_sql
    assert "contract_invoices.invoice_id" in primary_sql
    assert "contract_invoices.status = 'confirmed_primary'" in primary_sql
    assert "contract_invoices.deleted_at IS NULL" in primary_sql
    assert "contracts.organization_id" in primary_sql
    assert "contracts.deleted_at IS NULL" in primary_sql
    assert "invoices.organization_id" in primary_sql
    assert "invoices.deleted_at IS NULL" in primary_sql
