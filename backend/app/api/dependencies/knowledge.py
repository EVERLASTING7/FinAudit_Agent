"""知识索引、检索评测与 RAG 服务依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError
from app.services.knowledge_index_management import KnowledgeIndexManagementService
from app.services.rag_query import RagQueryService


def get_knowledge_index_management_service(
    request: Request,
) -> KnowledgeIndexManagementService:
    service = getattr(request.app.state, "knowledge_index_management_service", None)
    if not isinstance(service, KnowledgeIndexManagementService):
        raise AppError(
            status_code=503,
            code="KNOWLEDGE_INDEX_NOT_CONFIGURED",
            message="知识索引运行时尚未配置",
        )
    return service


KnowledgeIndexManagementServiceDependency = Annotated[
    KnowledgeIndexManagementService,
    Depends(get_knowledge_index_management_service),
]


def get_rag_query_service(request: Request) -> RagQueryService:
    service = getattr(request.app.state, "rag_query_service", None)
    if not isinstance(service, RagQueryService):
        raise AppError(
            status_code=503,
            code="RAG_NOT_CONFIGURED",
            message="知识问答运行时尚未配置",
        )
    return service


RagQueryServiceDependency = Annotated[
    RagQueryService,
    Depends(get_rag_query_service),
]

__all__ = [
    "KnowledgeIndexManagementServiceDependency",
    "RagQueryServiceDependency",
    "get_knowledge_index_management_service",
    "get_rag_query_service",
]
