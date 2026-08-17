"""合同事实写服务依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.contract_management import ContractManagementService


def get_contract_management_service(request: Request) -> ContractManagementService:
    service = getattr(request.app.state, "contract_management_service", None)
    if not isinstance(service, ContractManagementService):
        raise AppError(
            status_code=503,
            code="FINANCIAL_WRITE_NOT_CONFIGURED",
            message="合同写服务尚未配置",
        )
    return service


ContractManagementServiceDependency = Annotated[
    ContractManagementService,
    Depends(get_contract_management_service),
]


__all__ = [
    "ContractManagementServiceDependency",
    "get_contract_management_service",
]
