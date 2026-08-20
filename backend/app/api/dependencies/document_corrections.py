"""CR-005-R2 文档纠错应用服务依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.document_correction import DocumentCorrectionService


def get_document_correction_service(request: Request) -> DocumentCorrectionService:
    service = getattr(request.app.state, "document_correction_service", None)
    if not isinstance(service, DocumentCorrectionService):
        raise AppError(
            status_code=503,
            code="DOCUMENT_CORRECTION_NOT_CONFIGURED",
            message="文档纠错服务尚未配置",
        )
    return service


DocumentCorrectionServiceDependency = Annotated[
    DocumentCorrectionService,
    Depends(get_document_correction_service),
]

__all__ = [
    "DocumentCorrectionServiceDependency",
    "get_document_correction_service",
]
