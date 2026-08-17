"""供应商候选运行时服务依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.supplier_management import SupplierManagementService


def get_supplier_management_service(request: Request) -> SupplierManagementService:
    service = getattr(request.app.state, "supplier_management_service", None)
    if not isinstance(service, SupplierManagementService):
        raise AppError(
            status_code=503,
            code="FINANCIAL_WRITE_NOT_CONFIGURED",
            message="供应商运行时尚未配置",
        )
    return service


SupplierManagementServiceDependency = Annotated[
    SupplierManagementService,
    Depends(get_supplier_management_service),
]

__all__ = ["SupplierManagementServiceDependency", "get_supplier_management_service"]
