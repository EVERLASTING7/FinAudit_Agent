"""有效合同字段查询服务依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.effective_contract_query import EffectiveContractQueryService


def get_effective_contract_query_service(request: Request) -> EffectiveContractQueryService:
    service = getattr(request.app.state, "effective_contract_query_service", None)
    if not isinstance(service, EffectiveContractQueryService):
        raise AppError(
            status_code=503,
            code="FINANCIAL_QUERY_NOT_CONFIGURED",
            message="财务查询服务尚未配置",
        )
    return service


EffectiveContractQueryServiceDependency = Annotated[
    EffectiveContractQueryService,
    Depends(get_effective_contract_query_service),
]

__all__ = [
    "EffectiveContractQueryServiceDependency",
    "get_effective_contract_query_service",
]
