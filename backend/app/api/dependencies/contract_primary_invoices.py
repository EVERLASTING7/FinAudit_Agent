"""Contract primary-invoice list query dependency boundary."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.contract_primary_invoice_query import ContractPrimaryInvoiceQueryService


def get_contract_primary_invoice_query_service(
    request: Request,
) -> ContractPrimaryInvoiceQueryService:
    service = getattr(request.app.state, "contract_primary_invoice_query_service", None)
    if not isinstance(service, ContractPrimaryInvoiceQueryService):
        raise AppError(
            status_code=503,
            code="FINANCIAL_NOT_CONFIGURED",
            message="财务查询服务尚未配置",
        )
    return service


ContractPrimaryInvoiceQueryServiceDependency = Annotated[
    ContractPrimaryInvoiceQueryService,
    Depends(get_contract_primary_invoice_query_service),
]

__all__ = [
    "ContractPrimaryInvoiceQueryServiceDependency",
    "get_contract_primary_invoice_query_service",
]
