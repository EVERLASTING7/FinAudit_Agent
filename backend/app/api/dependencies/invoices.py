"""Invoice query dependency boundary."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.invoice_query import InvoiceQueryService


def get_invoice_query_service(request: Request) -> InvoiceQueryService:
    service = getattr(request.app.state, "invoice_query_service", None)
    if not isinstance(service, InvoiceQueryService):
        raise AppError(
            status_code=503,
            code="FINANCIAL_NOT_CONFIGURED",
            message="财务查询服务尚未配置",
        )
    return service


InvoiceQueryServiceDependency = Annotated[
    InvoiceQueryService,
    Depends(get_invoice_query_service),
]

__all__ = ["InvoiceQueryServiceDependency", "get_invoice_query_service"]
