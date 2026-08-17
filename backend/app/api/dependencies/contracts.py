"""Contract query dependency boundary."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.contract_query import ContractQueryService


def get_contract_query_service(request: Request) -> ContractQueryService:
    service = getattr(request.app.state, "contract_query_service", None)
    if not isinstance(service, ContractQueryService):
        raise AppError(
            status_code=503,
            code="FINANCIAL_NOT_CONFIGURED",
            message="财务查询服务尚未配置",
        )
    return service


ContractQueryServiceDependency = Annotated[
    ContractQueryService,
    Depends(get_contract_query_service),
]

__all__ = ["ContractQueryServiceDependency", "get_contract_query_service"]
