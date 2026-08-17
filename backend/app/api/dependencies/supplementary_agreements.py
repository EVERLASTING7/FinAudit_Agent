"""Supplementary-agreement query dependency boundary."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.supplementary_agreement_query import SupplementaryAgreementQueryService


def get_supplementary_agreement_query_service(
    request: Request,
) -> SupplementaryAgreementQueryService:
    service = getattr(request.app.state, "supplementary_agreement_query_service", None)
    if not isinstance(service, SupplementaryAgreementQueryService):
        raise AppError(
            status_code=503,
            code="FINANCIAL_NOT_CONFIGURED",
            message="财务查询服务尚未配置",
        )
    return service


SupplementaryAgreementQueryServiceDependency = Annotated[
    SupplementaryAgreementQueryService,
    Depends(get_supplementary_agreement_query_service),
]

__all__ = [
    "SupplementaryAgreementQueryServiceDependency",
    "get_supplementary_agreement_query_service",
]
