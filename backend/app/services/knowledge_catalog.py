"""知识库目录读取用例。"""

from __future__ import annotations

import base64
import binascii
import json
import re
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.models.documents import KnowledgeBase
from app.repositories.knowledge_catalog import KnowledgeCatalogRepository
from app.schemas.knowledge_bases import (
    KnowledgeBaseData,
    KnowledgeBaseListData,
    KnowledgeBaseStatus,
)


def _not_found() -> AppError:
    return AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )


def _invalid_cursor() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=[{"field": "query.cursor", "reason": "invalid"}],
    )


def _encode_cursor(knowledge_base_id: UUID) -> str:
    payload = json.dumps(
        {"id": str(knowledge_base_id), "v": 1},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor(value: str) -> UUID:
    if not value or len(value) > 256 or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise _invalid_cursor()
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
        if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
            raise ValueError("noncanonical base64url")
        payload = json.loads(decoded.decode("utf-8"))
        if type(payload) is not dict or set(payload) != {"id", "v"} or payload["v"] != 1:
            raise ValueError("invalid cursor object")
        raw_id = payload["id"]
        if type(raw_id) is not str:
            raise ValueError("invalid cursor id")
        knowledge_base_id = UUID(raw_id)
        if str(knowledge_base_id) != raw_id or _encode_cursor(knowledge_base_id) != value:
            raise ValueError("noncanonical cursor id")
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None
    return knowledge_base_id


def _project(row: KnowledgeBase) -> KnowledgeBaseData:
    return KnowledgeBaseData(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        status=KnowledgeBaseStatus(row.status),
        default_top_k=5,
        row_version=str(row.row_version),
    )


class KnowledgeCatalogService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_page(
        self,
        organization_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> KnowledgeBaseListData:
        cursor_id = _decode_cursor(cursor) if cursor is not None else None
        with self._session_factory() as session:
            rows = KnowledgeCatalogRepository(session).list_knowledge_bases(
                organization_id,
                cursor_id,
                page_size + 1,
            )
        has_more = len(rows) > page_size
        page = rows[:page_size]
        return KnowledgeBaseListData(
            items=tuple(_project(row) for row in page),
            page_size=page_size,
            next_cursor=_encode_cursor(page[-1].id) if has_more else None,
        )

    def get_detail(
        self,
        organization_id: UUID,
        knowledge_base_id: UUID,
    ) -> KnowledgeBaseData:
        with self._session_factory() as session:
            row = KnowledgeCatalogRepository(session).get_knowledge_base(
                organization_id,
                knowledge_base_id,
            )
            if row is None:
                raise _not_found()
            return _project(row)


__all__ = ["KnowledgeCatalogService"]
