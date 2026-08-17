"""Invoice primary-contract query dependency boundary."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.invoice_primary_contract_query import InvoicePrimaryContractQueryService


def get_invoice_primary_contract_query_service(
    request: Request,
) -> InvoicePrimaryContractQueryService:
    service = getattr(request.app.state, "invoice_primary_contract_query_service", None)
    if not isinstance(service, InvoicePrimaryContractQueryService):
        raise AppError(
            status_code=503,
            code="FINANCIAL_NOT_CONFIGURED",
            message="财务查询服务尚未配置",
        )
    return service


InvoicePrimaryContractQueryServiceDependency = Annotated[
    InvoicePrimaryContractQueryService,
    Depends(get_invoice_primary_contract_query_service),
]

__all__ = [
    "InvoicePrimaryContractQueryServiceDependency",
    "get_invoice_primary_contract_query_service",
]
