"""财务只读视图到合同发票候选的最小应用服务。"""

from uuid import UUID

from app.repositories.financial_read import FinancialReadView
from app.rules.contract_invoice_matching import (
    ContractInvoiceCandidate,
    ContractMatchFacts,
    InvoiceMatchFacts,
    derive_contract_invoice_candidates,
)


def derive_contract_invoice_candidates_from_view(
    view: FinancialReadView,
    invoice_id: UUID,
) -> tuple[ContractInvoiceCandidate, ...]:
    """把已读取的财务事实逐字映射到候选规则，不改变或补全上游事实。"""

    if type(view) is not FinancialReadView:
        raise ValueError("view must be a FinancialReadView")
    if type(invoice_id) is not UUID:
        raise ValueError("invoice_id must be an exact UUID")

    invoices = tuple(invoice for invoice in view.invoices if invoice.id == invoice_id)
    if len(invoices) != 1:
        raise ValueError("invoice_id must identify exactly one invoice in view")
    if view.supplementary_agreements:
        raise ValueError("candidates require effective supplementary agreement field projection")
    invoice = invoices[0]

    return derive_contract_invoice_candidates(
        InvoiceMatchFacts(
            invoice_id=invoice.id,
            seller_tax_no=invoice.seller_tax_no,
            seller_name=invoice.seller_name,
            invoice_date=invoice.invoice_date,
        ),
        tuple(
            ContractMatchFacts(
                contract_id=contract.id,
                party_b_tax_no=contract.party_b_tax_no,
                party_b_name=contract.party_b_name,
                effective_date=contract.effective_date,
                expiry_date=contract.expiry_date,
            )
            for contract in view.contracts
        ),
    )


__all__ = ["derive_contract_invoice_candidates_from_view"]
