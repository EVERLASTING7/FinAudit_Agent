"""Organization-scoped invoice primary-contract read use case."""

from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.financial_read import FinancialReadRepository
from app.schemas.invoices import InvoicePrimaryContractData
from app.services.contract_query import project_contract_list_item


class InvoicePrimaryContractQueryService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(
        self,
        organization_id: UUID,
        invoice_id: UUID,
    ) -> InvoicePrimaryContractData:
        with self._session_factory() as session:
            result = FinancialReadRepository(session).read_invoice_primary_contract(
                organization_id,
                invoice_id,
            )
        if result is None:
            raise AppError(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                message="目标资源不存在或不可见",
            )
        return InvoicePrimaryContractData(
            primary_contract=(
                project_contract_list_item(result.primary_contract)
                if result.primary_contract is not None
                else None
            )
        )


__all__ = ["InvoicePrimaryContractQueryService"]
