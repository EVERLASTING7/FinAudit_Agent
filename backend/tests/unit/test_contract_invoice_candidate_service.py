from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from app.repositories.financial_read import (
    ContractReadView,
    FinancialReadView,
    InvoiceReadView,
    SupplementaryAgreementReadView,
)
from app.rules.contract_invoice_matching import ContractInvoiceReasonCode
from app.services.contract_invoice_candidates import (
    derive_contract_invoice_candidates_from_view,
)

ORGANIZATION_ID = UUID("71000000-0000-4000-8000-000000000001")
INVOICE_ID = UUID("74000000-0000-4000-8000-000000000001")


def _contract(
    contract_id: UUID,
    *,
    party_b_tax_no: str = "TAX",
    party_b_name: str = "Café",
) -> ContractReadView:
    return ContractReadView(
        id=contract_id,
        organization_id=ORGANIZATION_ID,
        contract_no=None,
        name="合同",
        party_a_name=None,
        party_a_tax_no=None,
        party_b_name=party_b_name,
        party_b_tax_no=party_b_tax_no,
        supplier_id=None,
        amount=Decimal("100.00"),
        currency="CNY",
        signed_date=None,
        effective_date=date(2026, 1, 1),
        expiry_date=date(2026, 12, 31),
        payment_method=None,
        payment_terms=None,
        confirmation_status="confirmed",
        status="active",
        confirmed_by=None,
        confirmed_at=None,
        critical_fact_hash="0" * 64,
        row_version=1,
    )


def _invoice(invoice_id: UUID = INVOICE_ID) -> InvoiceReadView:
    return InvoiceReadView(
        id=invoice_id,
        organization_id=ORGANIZATION_ID,
        invoice_code=None,
        invoice_number=None,
        invoice_type=None,
        invoice_date=date(2026, 6, 1),
        buyer_name=None,
        buyer_tax_no=None,
        seller_name="Café",
        seller_tax_no="TAX",
        supplier_id=None,
        amount_excluding_tax=Decimal("90.00"),
        tax_amount=Decimal("10.00"),
        total_amount=Decimal("100.00"),
        currency="CNY",
        confirmation_status="confirmed",
        duplicate_status="unique",
        status="confirmed",
        field_evidence={},
        confirmed_by=None,
        confirmed_at=None,
        critical_fact_hash="1" * 64,
        row_version=1,
        items=(),
    )


def _view(
    *,
    contracts: tuple[ContractReadView, ...] = (),
    invoices: tuple[InvoiceReadView, ...] = (_invoice(),),
    supplementary_agreements: tuple[SupplementaryAgreementReadView, ...] = (),
) -> FinancialReadView:
    return FinancialReadView(
        organization_id=ORGANIZATION_ID,
        baseline_date=date(2026, 6, 1),
        contracts=contracts,
        supplementary_agreements=supplementary_agreements,
        invoices=invoices,
        contract_invoices=(),
    )


def test_maps_read_view_verbatim_and_reuses_candidate_sorting() -> None:
    mismatched = _contract(
        UUID(int=1),
        party_b_tax_no=" TAX ",
        party_b_name="Cafe\u0301",
    )
    matched = _contract(UUID(int=2))

    candidates = derive_contract_invoice_candidates_from_view(
        _view(contracts=(mismatched, matched)),
        INVOICE_ID,
    )

    assert tuple(candidate.contract_id for candidate in candidates) == (UUID(int=2), UUID(int=1))
    assert candidates[0].tax_no_reason.code is ContractInvoiceReasonCode.TAX_NO_MATCHED
    assert candidates[0].name_reason.code is ContractInvoiceReasonCode.NAME_MATCHED
    assert candidates[1].tax_no_reason.code is ContractInvoiceReasonCode.TAX_NO_MISMATCHED
    assert candidates[1].name_reason.code is ContractInvoiceReasonCode.NAME_MISMATCHED
    assert candidates[1].contract_party_b_tax_no == " TAX "
    assert candidates[1].contract_party_b_name == "Cafe\u0301"


def test_returns_no_candidate_when_the_read_view_has_no_contracts() -> None:
    assert derive_contract_invoice_candidates_from_view(_view(), INVOICE_ID) == ()


def test_fails_closed_when_effective_supplementary_fields_are_unavailable() -> None:
    contract = _contract(UUID(int=1))
    agreement = SupplementaryAgreementReadView(
        id=UUID(int=3),
        organization_id=ORGANIZATION_ID,
        contract_id=contract.id,
        agreement_no="S-001",
        name="补充协议",
        signed_date=date(2026, 5, 1),
        effective_date=date(2026, 6, 1),
        status="confirmed",
        confirmation_status="confirmed",
        confirmed_by=None,
        confirmed_at=None,
        confirmation_reason=None,
        critical_fact_hash="2" * 64,
        row_version=1,
    )

    with pytest.raises(ValueError, match="effective supplementary agreement field projection"):
        derive_contract_invoice_candidates_from_view(
            _view(contracts=(contract,), supplementary_agreements=(agreement,)),
            INVOICE_ID,
        )


@pytest.mark.parametrize(
    ("view", "invoice_id", "message"),
    (
        ("view", INVOICE_ID, "FinancialReadView"),
        (_view(), "invoice", "exact UUID"),
        (_view(invoices=()), INVOICE_ID, "exactly one invoice"),
        (
            _view(invoices=(_invoice(), _invoice())),
            INVOICE_ID,
            "exactly one invoice",
        ),
    ),
)
def test_fails_closed_for_invalid_or_ambiguous_view_selection(
    view: object,
    invoice_id: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        derive_contract_invoice_candidates_from_view(
            view,  # type: ignore[arg-type]
            invoice_id,  # type: ignore[arg-type]
        )
