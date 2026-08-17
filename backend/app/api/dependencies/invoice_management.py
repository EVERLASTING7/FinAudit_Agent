"""发票事实写与证据/历史读取服务依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.invoice_management import InvoiceManagementService


def get_invoice_management_service(request: Request) -> InvoiceManagementService:
    service = getattr(request.app.state, "invoice_management_service", None)
    if not isinstance(service, InvoiceManagementService):
        raise AppError(
            status_code=503,
            code="FINANCIAL_WRITE_NOT_CONFIGURED",
            message="发票写服务尚未配置",
        )
    return service


InvoiceManagementServiceDependency = Annotated[
    InvoiceManagementService,
    Depends(get_invoice_management_service),
]

__all__ = [
    "InvoiceManagementServiceDependency",
    "get_invoice_management_service",
]
