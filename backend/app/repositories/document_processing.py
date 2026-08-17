"""文档解析版本的追加写 Repository。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document_processing import DocumentBlock, DocumentPage, DocumentParseVersion
from app.models.documents import FileRecord


@dataclass(frozen=True, slots=True)
class ParseBlockWrite:
    block_index: int
    block_type: str
    text: str
    bbox: dict[str, int] | None
    confidence: Decimal | None


@dataclass(frozen=True, slots=True)
class ParsePageWrite:
    page_no: int
    width: Decimal | None
    height: Decimal | None
    unit: str
    text: str
    confidence: Decimal | None
    blocks: tuple[ParseBlockWrite, ...]


@dataclass(frozen=True, slots=True)
class ParseVersionWrite:
    source_type: Literal["parser", "ocr"]
    parser_name: str
    parser_version: str
    ocr_name: str | None
    ocr_version: str | None
    average_confidence: Decimal | None
    pages: tuple[ParsePageWrite, ...]


@dataclass(frozen=True, slots=True)
class PersistedParseResult:
    parse_version_id: UUID
    page_count: int
    parser_name: str
    parser_version: str
    ocr_name: str | None
    ocr_version: str | None


class DocumentProcessingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def completed_result_for_trace(
        self,
        *,
        organization_id: UUID,
        file_id: UUID,
        trace_id: UUID,
    ) -> PersistedParseResult | None:
        """恢复 attempt 只复用同一 Job Trace 已提交的不可变解析结果。"""

        file_record = self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        if (
            file_record is None
            or file_record.status != "stored"
            or file_record.security_scan_status != "clean"
        ):
            return None
        result = self._session.execute(
            select(DocumentParseVersion)
            .where(
                DocumentParseVersion.file_id == file_id,
                DocumentParseVersion.trace_id == trace_id,
                DocumentParseVersion.status.in_(("succeeded", "manual_review_required", "active")),
                DocumentParseVersion.archived_at.is_(None),
            )
            .order_by(DocumentParseVersion.version_no.desc())
            .limit(1)
        ).scalar_one_or_none()
        if result is None:
            return None
        return PersistedParseResult(
            parse_version_id=result.id,
            page_count=result.page_count,
            parser_name=result.parser_name,
            parser_version=result.parser_version,
            ocr_name=result.ocr_name,
            ocr_version=result.ocr_version,
        )

    def append_result(
        self,
        *,
        organization_id: UUID,
        file_id: UUID,
        trace_id: UUID,
        result: ParseVersionWrite,
    ) -> UUID:
        """锁文件后分配版本号；调用方在同一事务内终结 Job。"""

        file_record = self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        if (
            file_record is None
            or file_record.status != "stored"
            or file_record.security_scan_status != "clean"
            or file_record.original_minio_bucket is None
            or file_record.original_minio_object_key is None
            or not result.pages
        ):
            raise ValueError("FILE_PARSE_PRECONDITION_FAILED")
        page_numbers = tuple(page.page_no for page in result.pages)
        if page_numbers != tuple(range(1, len(result.pages) + 1)):
            raise ValueError("PARSE_PAGE_SEQUENCE_INVALID")
        block_indexes = tuple(block.block_index for page in result.pages for block in page.blocks)
        if not block_indexes or block_indexes != tuple(range(len(block_indexes))):
            raise ValueError("PARSE_BLOCK_SEQUENCE_INVALID")
        if any(not page.text or not page.blocks for page in result.pages):
            raise ValueError("PARSE_PAGE_CONTENT_INVALID")

        version_no = (
            self._session.execute(
                select(func.coalesce(func.max(DocumentParseVersion.version_no), 0)).where(
                    DocumentParseVersion.file_id == file_id
                )
            ).scalar_one()
            + 1
        )
        parse_version_id = uuid4()
        terminal_status = "manual_review_required" if result.source_type == "ocr" else "succeeded"
        parse_version = DocumentParseVersion(
            id=parse_version_id,
            file_id=file_id,
            version_no=version_no,
            parent_version_id=None,
            source_type=result.source_type,
            parser_name=result.parser_name,
            parser_version=result.parser_version,
            ocr_name=result.ocr_name,
            ocr_version=result.ocr_version,
            code_version="document-parser-v1",
            status="running",
            page_count=0,
            raw_text_object_key=None,
            raw_text_sha256=None,
            average_confidence=None,
            error_code=None,
            error_message=None,
            activated_at=None,
            superseded_at=None,
            created_by=None,
            trace_id=trace_id,
            archived_at=None,
        )
        self._session.add(parse_version)
        self._session.flush()
        for page in result.pages:
            page_id = uuid4()
            self._session.add(
                DocumentPage(
                    id=page_id,
                    parse_version_id=parse_version_id,
                    page_no=page.page_no,
                    width=page.width,
                    height=page.height,
                    unit=page.unit,
                    page_text=page.text,
                    text_sha256=hashlib.sha256(page.text.encode("utf-8")).hexdigest(),
                    preview_object_key=None,
                    confidence=page.confidence,
                    metadata_json={},
                )
            )
            # 模型刻意不维护 ORM relationship；先写入页面，供数据库跨版本触发器校验子块。
            self._session.flush()
            for block in page.blocks:
                if not block.text:
                    raise ValueError("PARSE_BLOCK_TEXT_EMPTY")
                self._session.add(
                    DocumentBlock(
                        id=uuid4(),
                        parse_version_id=parse_version_id,
                        page_id=page_id,
                        block_index=block.block_index,
                        block_type=block.block_type,
                        text_content=block.text,
                        text_sha256=hashlib.sha256(block.text.encode("utf-8")).hexdigest(),
                        bbox_json=block.bbox,
                        coordinate_unavailable_reason=(
                            None
                            if block.bbox is not None
                            else (
                                "source_not_paginated"
                                if page.unit == "unknown"
                                else "extractor_not_available"
                            )
                        ),
                        reading_order=block.block_index,
                        confidence=block.confidence,
                        asset_id=None,
                        is_effective_content=True,
                        metadata_json={},
                    )
                )
        self._session.flush()
        parse_version.status = terminal_status
        parse_version.page_count = len(result.pages)
        parse_version.average_confidence = result.average_confidence
        self._session.flush()
        return parse_version_id

    def append_failure(
        self,
        *,
        organization_id: UUID,
        file_id: UUID,
        trace_id: UUID,
        error_code: str,
    ) -> UUID:
        file_record = self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        if (
            file_record is None
            or file_record.status != "stored"
            or file_record.security_scan_status != "clean"
        ):
            raise ValueError("FILE_PARSE_PRECONDITION_FAILED")
        version_no = (
            self._session.execute(
                select(func.coalesce(func.max(DocumentParseVersion.version_no), 0)).where(
                    DocumentParseVersion.file_id == file_id
                )
            ).scalar_one()
            + 1
        )
        parse_version_id = uuid4()
        self._session.add(
            DocumentParseVersion(
                id=parse_version_id,
                file_id=file_id,
                version_no=version_no,
                parent_version_id=None,
                source_type="parser",
                parser_name="document-parser",
                parser_version="1",
                ocr_name=None,
                ocr_version=None,
                code_version="document-parser-v1",
                status="failed",
                page_count=0,
                raw_text_object_key=None,
                raw_text_sha256=None,
                average_confidence=None,
                error_code=error_code,
                error_message=None,
                activated_at=None,
                superseded_at=None,
                created_by=None,
                trace_id=trace_id,
                archived_at=None,
            )
        )
        self._session.flush()
        return parse_version_id


__all__ = [
    "DocumentProcessingRepository",
    "ParseBlockWrite",
    "ParsePageWrite",
    "PersistedParseResult",
    "ParseVersionWrite",
]
