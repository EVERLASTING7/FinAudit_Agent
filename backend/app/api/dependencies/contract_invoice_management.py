"""合同发票关系管理服务依赖边界。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.contract_invoice_management import ContractInvoiceManagementService


def get_contract_invoice_management_service(
    request: Request,
) -> ContractInvoiceManagementService:
    service = getattr(request.app.state, "contract_invoice_management_service", None)
    if not isinstance(service, ContractInvoiceManagementService):
        raise AppError(
            status_code=503,
            code="FINANCIAL_WRITE_NOT_CONFIGURED",
            message="财务写入服务尚未配置",
        )
    return service


ContractInvoiceManagementServiceDependency = Annotated[
    ContractInvoiceManagementService,
    Depends(get_contract_invoice_management_service),
]

__all__ = [
    "ContractInvoiceManagementServiceDependency",
    "get_contract_invoice_management_service",
]
