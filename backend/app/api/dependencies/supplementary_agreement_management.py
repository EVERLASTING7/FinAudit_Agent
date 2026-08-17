"""补充协议字段变更管理服务依赖边界。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.supplementary_agreement_management import (
    SupplementaryAgreementManagementService,
)


def get_supplementary_agreement_management_service(
    request: Request,
) -> SupplementaryAgreementManagementService:
    service = getattr(request.app.state, "supplementary_agreement_management_service", None)
    if not isinstance(service, SupplementaryAgreementManagementService):
        raise AppError(
            status_code=503,
            code="FINANCIAL_WRITE_NOT_CONFIGURED",
            message="财务写入服务尚未配置",
        )
    return service


SupplementaryAgreementManagementServiceDependency = Annotated[
    SupplementaryAgreementManagementService,
    Depends(get_supplementary_agreement_management_service),
]

__all__ = [
    "SupplementaryAgreementManagementServiceDependency",
    "get_supplementary_agreement_management_service",
]
