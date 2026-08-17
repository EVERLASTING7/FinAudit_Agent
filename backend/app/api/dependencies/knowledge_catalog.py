"""知识库目录读取服务依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.knowledge_catalog import KnowledgeCatalogService


def get_knowledge_catalog_service(request: Request) -> KnowledgeCatalogService:
    service = getattr(request.app.state, "knowledge_catalog_service", None)
    if not isinstance(service, KnowledgeCatalogService):
        raise AppError(
            status_code=503,
            code="KNOWLEDGE_CATALOG_NOT_CONFIGURED",
            message="知识库目录服务尚未配置",
        )
    return service


KnowledgeCatalogServiceDependency = Annotated[
    KnowledgeCatalogService,
    Depends(get_knowledge_catalog_service),
]

__all__ = ["KnowledgeCatalogServiceDependency", "get_knowledge_catalog_service"]
