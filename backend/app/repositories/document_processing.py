"""文档解析版本的追加写 Repository。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document_processing import (
    DocumentAsset,
    DocumentBlock,
    DocumentContentExclusion,
    DocumentPage,
    DocumentParseVersion,
)
from app.models.documents import FileRecord
from app.models.knowledge import DocumentBlockCorrection


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


@dataclass(frozen=True, slots=True)
class ManualCorrectionSnapshotResult:
    correction_id: UUID
    result_parse_version_id: UUID
    page_count: int
    block_count: int


class ManualCorrectionSnapshotError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class AssetRevalidationSource:
    asset_id: UUID
    object_key: str
    content_sha256: str
    mime_type: str


@dataclass(frozen=True, slots=True)
class AssetRevalidationWrite:
    source_asset_id: UUID
    target_asset_id: UUID
    target_object_key: str
    outcome: Literal["clean", "infected", "scan_failed", "unsupported"]
    error_code: str | None
    scanner_invoked: bool


@dataclass(frozen=True, slots=True)
class AssetRevalidationSnapshotResult:
    result_parse_version_id: UUID
    page_count: int
    block_count: int
    asset_count: int
    clean_count: int
    non_clean_count: int
    status: Literal["succeeded", "manual_review_required"]


class AssetRevalidationSnapshotError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _correction_value(block: DocumentBlock, field_name: str) -> object:
    return cast(
        object,
        {
            "text_content": block.text_content,
            "block_type": block.block_type,
            "reading_order": block.reading_order,
            "bbox": block.bbox_json,
        }[field_name],
    )


def _validate_correction_value(
    correction: DocumentBlockCorrection,
    page: DocumentPage,
) -> None:
    value = correction.after_value_json
    if correction.field_name == "text_content":
        if type(value) is not str or not 1 <= len(value) <= 1_000_000 or "\x00" in value:
            raise ManualCorrectionSnapshotError("CORRECTION_VALUE_INVALID")
    elif correction.field_name == "block_type":
        if value not in {"title", "paragraph", "list", "table", "quote", "other"}:
            raise ManualCorrectionSnapshotError("CORRECTION_VALUE_INVALID")
    elif correction.field_name == "reading_order":
        if type(value) is not int or not 0 <= value <= 2_147_483_647:
            raise ManualCorrectionSnapshotError("CORRECTION_VALUE_INVALID")
    elif correction.field_name == "bbox":
        if value is None:
            return
        if type(value) is not dict or set(value) != {"left", "top", "width", "height"}:
            raise ManualCorrectionSnapshotError("CORRECTION_VALUE_INVALID")
        left, top, width, height = (
            value["left"],
            value["top"],
            value["width"],
            value["height"],
        )
        if (
            any(type(item) is not int for item in (left, top, width, height))
            or left < 0
            or top < 0
            or width <= 0
            or height <= 0
            or (page.width is not None and left + width > page.width)
            or (page.height is not None and top + height > page.height)
        ):
            raise ManualCorrectionSnapshotError("CORRECTION_VALUE_INVALID")
    else:
        raise ManualCorrectionSnapshotError("CORRECTION_FIELD_INVALID")


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

    def rebuild_manual_correction_snapshot(
        self,
        *,
        organization_id: UUID,
        file_id: UUID,
        source_parse_version_id: UUID,
        result_parse_version_id: UUID,
        correction_id: UUID,
        trace_id: UUID,
    ) -> ManualCorrectionSnapshotResult:
        """从不可变来源版本重建候选快照；本事务不激活候选版本。"""

        file_record = self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        source = self._session.execute(
            select(DocumentParseVersion)
            .where(DocumentParseVersion.id == source_parse_version_id)
            .with_for_update(of=DocumentParseVersion)
        ).scalar_one_or_none()
        result = self._session.execute(
            select(DocumentParseVersion)
            .where(DocumentParseVersion.id == result_parse_version_id)
            .with_for_update(of=DocumentParseVersion)
        ).scalar_one_or_none()
        correction = self._session.execute(
            select(DocumentBlockCorrection)
            .where(DocumentBlockCorrection.id == correction_id)
            .with_for_update(of=DocumentBlockCorrection)
        ).scalar_one_or_none()
        if (
            file_record is None
            or source is None
            or result is None
            or correction is None
            or source.file_id != file_id
            or source.status not in {"active", "superseded"}
            or source.archived_at is not None
            or result.file_id != file_id
            or result.status != "running"
            or result.source_type != "manual_correction"
            or result.parent_version_id != source.id
            or result.code_version != "manual-correction-snapshot-v1"
            or result.trace_id != trace_id
            or correction.source_parse_version_id != source.id
            or correction.result_parse_version_id != result.id
            or correction.trace_id != trace_id
            or result.created_by != correction.corrected_by
        ):
            raise ManualCorrectionSnapshotError("CORRECTION_SNAPSHOT_IDENTITY_INVALID")

        pages = tuple(
            self._session.scalars(
                select(DocumentPage)
                .where(DocumentPage.parse_version_id == source.id)
                .order_by(DocumentPage.page_no)
            ).all()
        )
        blocks = tuple(
            self._session.scalars(
                select(DocumentBlock)
                .where(DocumentBlock.parse_version_id == source.id)
                .order_by(DocumentBlock.block_index)
            ).all()
        )
        if (
            not pages
            or not blocks
            or len(pages) > 2_000
            or len(blocks) > 1_000_000
            or source.page_count != len(pages)
            or tuple(page.page_no for page in pages) != tuple(range(1, len(pages) + 1))
            or tuple(block.block_index for block in blocks) != tuple(range(len(blocks)))
        ):
            raise ManualCorrectionSnapshotError("CORRECTION_SOURCE_SNAPSHOT_INVALID")
        if self._session.scalar(
            select(func.count())
            .select_from(DocumentAsset)
            .where(DocumentAsset.parse_version_id == source.id)
        ) or any(block.asset_id is not None or block.block_type == "asset" for block in blocks):
            # R2 没有授权复制或伪造 MinIO 资源；等待 CR-010 后走安全重评重建。
            raise ManualCorrectionSnapshotError("DOCUMENT_ASSET_SNAPSHOT_UNSUPPORTED")
        if self._session.scalar(
            select(func.count())
            .select_from(DocumentPage)
            .where(DocumentPage.parse_version_id == result.id)
        ) or self._session.scalar(
            select(func.count())
            .select_from(DocumentBlock)
            .where(DocumentBlock.parse_version_id == result.id)
        ):
            raise ManualCorrectionSnapshotError("CORRECTION_RESULT_NOT_EMPTY")

        page_by_id = {page.id: page for page in pages}
        blocks_by_page: dict[UUID, list[DocumentBlock]] = {page.id: [] for page in pages}
        for block in blocks:
            page_blocks = blocks_by_page.get(block.page_id)
            if page_blocks is None:
                raise ManualCorrectionSnapshotError("CORRECTION_SOURCE_SNAPSHOT_INVALID")
            page_blocks.append(block)
        if any(not page_blocks for page_blocks in blocks_by_page.values()):
            raise ManualCorrectionSnapshotError("CORRECTION_SOURCE_SNAPSHOT_INVALID")
        source_block = next(
            (block for block in blocks if block.id == correction.source_block_id),
            None,
        )
        if source_block is None or correction.before_value_json != _correction_value(
            source_block, correction.field_name
        ):
            raise ManualCorrectionSnapshotError("CORRECTION_SOURCE_VALUE_MISMATCH")
        source_page = page_by_id[source_block.page_id]
        _validate_correction_value(correction, source_page)

        page_id_map: dict[UUID, UUID] = {}
        for page in pages:
            page_id = uuid4()
            page_id_map[page.id] = page_id
            page_text = page.page_text
            if correction.field_name == "text_content" and page.id == source_block.page_id:
                page_text = "\n".join(
                    cast(str, correction.after_value_json)
                    if block.id == source_block.id
                    else block.text_content or ""
                    for block in blocks_by_page[page.id]
                )
            self._session.add(
                DocumentPage(
                    id=page_id,
                    parse_version_id=result.id,
                    page_no=page.page_no,
                    width=page.width,
                    height=page.height,
                    unit=page.unit,
                    page_text=page_text,
                    text_sha256=(
                        None
                        if page_text is None
                        else hashlib.sha256(page_text.encode("utf-8")).hexdigest()
                    ),
                    preview_object_key=page.preview_object_key,
                    confidence=page.confidence,
                    metadata_json=dict(page.metadata_json),
                )
            )
        self._session.flush()

        block_id_map: dict[UUID, UUID] = {}
        for block in blocks:
            block_id = uuid4()
            block_id_map[block.id] = block_id
            is_target = block.id == source_block.id
            text_content = (
                cast(str, correction.after_value_json)
                if is_target and correction.field_name == "text_content"
                else block.text_content
            )
            block_type = (
                cast(str, correction.after_value_json)
                if is_target and correction.field_name == "block_type"
                else block.block_type
            )
            reading_order = (
                cast(int, correction.after_value_json)
                if is_target and correction.field_name == "reading_order"
                else block.reading_order
            )
            bbox_json = (
                cast(dict[str, object] | None, correction.after_value_json)
                if is_target and correction.field_name == "bbox"
                else (None if block.bbox_json is None else dict(block.bbox_json))
            )
            coordinate_reason = block.coordinate_unavailable_reason
            if is_target and correction.field_name == "bbox":
                coordinate_reason = (
                    None
                    if bbox_json is not None
                    else (
                        "source_not_paginated"
                        if page_by_id[block.page_id].unit == "unknown"
                        else "extractor_not_available"
                    )
                )
            self._session.add(
                DocumentBlock(
                    id=block_id,
                    parse_version_id=result.id,
                    page_id=page_id_map[block.page_id],
                    block_index=block.block_index,
                    block_type=block_type,
                    text_content=text_content,
                    text_sha256=(
                        None
                        if text_content is None
                        else hashlib.sha256(text_content.encode("utf-8")).hexdigest()
                    ),
                    bbox_json=bbox_json,
                    coordinate_unavailable_reason=coordinate_reason,
                    reading_order=reading_order,
                    confidence=block.confidence,
                    asset_id=None,
                    is_effective_content=block.is_effective_content,
                    metadata_json=dict(block.metadata_json),
                )
            )
        self._session.flush()

        exclusions = self._session.scalars(
            select(DocumentContentExclusion)
            .where(DocumentContentExclusion.parse_version_id == source.id)
            .order_by(DocumentContentExclusion.created_at, DocumentContentExclusion.id)
        ).all()
        for exclusion in exclusions:
            mapped_block_id = block_id_map.get(exclusion.block_id)
            if mapped_block_id is None:
                raise ManualCorrectionSnapshotError("CORRECTION_SOURCE_SNAPSHOT_INVALID")
            self._session.add(
                DocumentContentExclusion(
                    id=uuid4(),
                    parse_version_id=result.id,
                    block_id=mapped_block_id,
                    exclusion_type=exclusion.exclusion_type,
                    reason=exclusion.reason,
                    rule_version=exclusion.rule_version,
                    review_status=exclusion.review_status,
                    submitted_by=exclusion.submitted_by,
                    approved_by=exclusion.approved_by,
                    approved_at=exclusion.approved_at,
                    created_at=exclusion.created_at,
                    created_by=exclusion.created_by,
                    trace_id=exclusion.trace_id,
                    archived_at=exclusion.archived_at,
                )
            )
        self._session.flush()
        result.status = "succeeded"
        result.page_count = len(pages)
        result.average_confidence = source.average_confidence
        self._session.flush()
        return ManualCorrectionSnapshotResult(
            correction_id=correction.id,
            result_parse_version_id=result.id,
            page_count=len(pages),
            block_count=len(blocks),
        )

    def asset_revalidation_sources(
        self,
        *,
        organization_id: UUID,
        file_id: UUID,
        source_parse_version_id: UUID,
        result_parse_version_id: UUID,
        trace_id: UUID,
    ) -> tuple[AssetRevalidationSource, ...]:
        file_record = self._session.get(FileRecord, file_id)
        source = self._session.get(DocumentParseVersion, source_parse_version_id)
        result = self._session.get(DocumentParseVersion, result_parse_version_id)
        if (
            file_record is None
            or file_record.organization_id != organization_id
            or source is None
            or result is None
            or source.file_id != file_id
            or source.status not in {"active", "superseded"}
            or source.archived_at is not None
            or result.file_id != file_id
            or result.status != "running"
            or result.source_type != "security_revalidation"
            or result.parent_version_id != source.id
            or result.code_version != "asset-security-revalidation-v1"
            or result.trace_id != trace_id
        ):
            raise AssetRevalidationSnapshotError("ASSET_REVALIDATION_IDENTITY_INVALID")
        rows = tuple(
            self._session.scalars(
                select(DocumentAsset)
                .where(DocumentAsset.parse_version_id == source.id)
                .order_by(DocumentAsset.id)
            ).all()
        )
        if not rows:
            raise AssetRevalidationSnapshotError("ASSET_REVALIDATION_SOURCE_INVALID")
        return tuple(
            AssetRevalidationSource(
                asset_id=row.id,
                object_key=row.minio_object_key,
                content_sha256=row.content_sha256,
                mime_type=row.mime_type,
            )
            for row in rows
        )

    def rebuild_asset_security_snapshot(
        self,
        *,
        organization_id: UUID,
        file_id: UUID,
        source_parse_version_id: UUID,
        result_parse_version_id: UUID,
        trace_id: UUID,
        writes: tuple[AssetRevalidationWrite, ...],
        scanner_profile_class: str,
        scanner_registry_version: str,
        scanner_registry_hash: str,
        scanner_adapter_code: str,
        scanner_version: str,
        scanner_definition_version: str,
    ) -> AssetRevalidationSnapshotResult:
        file_record = self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        source = self._session.execute(
            select(DocumentParseVersion)
            .where(DocumentParseVersion.id == source_parse_version_id)
            .with_for_update(of=DocumentParseVersion)
        ).scalar_one_or_none()
        result = self._session.execute(
            select(DocumentParseVersion)
            .where(DocumentParseVersion.id == result_parse_version_id)
            .with_for_update(of=DocumentParseVersion)
        ).scalar_one_or_none()
        if (
            file_record is None
            or source is None
            or result is None
            or source.file_id != file_id
            or source.status not in {"active", "superseded"}
            or source.archived_at is not None
            or result.file_id != file_id
            or result.status != "running"
            or result.source_type != "security_revalidation"
            or result.parent_version_id != source.id
            or result.code_version != "asset-security-revalidation-v1"
            or result.trace_id != trace_id
        ):
            raise AssetRevalidationSnapshotError("ASSET_REVALIDATION_IDENTITY_INVALID")
        pages = tuple(
            self._session.scalars(
                select(DocumentPage)
                .where(DocumentPage.parse_version_id == source.id)
                .order_by(DocumentPage.page_no)
            ).all()
        )
        blocks = tuple(
            self._session.scalars(
                select(DocumentBlock)
                .where(DocumentBlock.parse_version_id == source.id)
                .order_by(DocumentBlock.block_index)
            ).all()
        )
        assets = tuple(
            self._session.scalars(
                select(DocumentAsset)
                .where(DocumentAsset.parse_version_id == source.id)
                .order_by(DocumentAsset.id)
            ).all()
        )
        if (
            not pages
            or not blocks
            or not assets
            or source.page_count != len(pages)
            or tuple(page.page_no for page in pages) != tuple(range(1, len(pages) + 1))
            or tuple(block.block_index for block in blocks) != tuple(range(len(blocks)))
            or len(pages) > 2_000
            or len(blocks) > 1_000_000
            or len(assets) > 1_000_000
        ):
            raise AssetRevalidationSnapshotError("ASSET_REVALIDATION_SOURCE_INVALID")
        source_asset_ids = {asset.id for asset in assets}
        if (
            {write.source_asset_id for write in writes} != source_asset_ids
            or len(writes) != len(source_asset_ids)
            or len({write.target_asset_id for write in writes}) != len(writes)
            or len({write.target_object_key for write in writes}) != len(writes)
        ):
            raise AssetRevalidationSnapshotError("ASSET_REVALIDATION_RESULT_INVALID")
        write_by_source = {write.source_asset_id: write for write in writes}
        if any(
            write.outcome == "clean"
            and (write.error_code is not None or not write.scanner_invoked)
            or write.outcome == "infected"
            and (
                write.error_code not in {"ACTIVE_CONTENT_DETECTED", "MALWARE_DETECTED"}
                or not write.scanner_invoked
            )
            or write.outcome == "scan_failed"
            and (
                write.error_code not in {"SCANNER_TIMEOUT", "SCANNER_UNAVAILABLE"}
                or not write.scanner_invoked
            )
            or write.outcome == "unsupported"
            and (
                write.error_code
                not in {
                    "IMAGE_DECODE_INVALID",
                    "IMAGE_LIMIT_EXCEEDED",
                    "MAGIC_BYTES_MISMATCH",
                    "MEDIA_TYPE_UNSUPPORTED",
                }
                or write.scanner_invoked
            )
            for write in writes
        ):
            raise AssetRevalidationSnapshotError("ASSET_REVALIDATION_RESULT_INVALID")
        if (
            self._session.scalar(
                select(func.count())
                .select_from(DocumentPage)
                .where(DocumentPage.parse_version_id == result.id)
            )
            or self._session.scalar(
                select(func.count())
                .select_from(DocumentBlock)
                .where(DocumentBlock.parse_version_id == result.id)
            )
            or self._session.scalar(
                select(func.count())
                .select_from(DocumentAsset)
                .where(DocumentAsset.parse_version_id == result.id)
            )
        ):
            raise AssetRevalidationSnapshotError("ASSET_REVALIDATION_RESULT_NOT_EMPTY")

        page_id_map: dict[UUID, UUID] = {}
        for page in pages:
            target_page_id = uuid4()
            page_id_map[page.id] = target_page_id
            self._session.add(
                DocumentPage(
                    id=target_page_id,
                    parse_version_id=result.id,
                    page_no=page.page_no,
                    width=page.width,
                    height=page.height,
                    unit=page.unit,
                    page_text=page.page_text,
                    text_sha256=page.text_sha256,
                    preview_object_key=page.preview_object_key,
                    confidence=page.confidence,
                    metadata_json=dict(page.metadata_json),
                )
            )
        self._session.flush()

        target_assets: dict[UUID, DocumentAsset] = {}
        for source_asset in assets:
            write = write_by_source[source_asset.id]
            target_asset = DocumentAsset(
                id=write.target_asset_id,
                file_id=file_id,
                parse_version_id=result.id,
                page_no=source_asset.page_no,
                asset_type=source_asset.asset_type,
                bbox_json=(
                    None if source_asset.bbox_json is None else dict(source_asset.bbox_json)
                ),
                coordinate_unavailable_reason=source_asset.coordinate_unavailable_reason,
                mime_type=source_asset.mime_type,
                minio_object_key=write.target_object_key,
                content_sha256=source_asset.content_sha256,
                security_status="pending",
                security_policy_version="asset-security-v1",
                security_policy_hash="b074e9cb6af5e20b57cb14f042977417bcf6f9d9eb35c47abf6a13de3823efe0",
                security_checked_at=None,
                security_error_code=None,
                security_scanner_profile_class=None,
                security_scanner_registry_version=None,
                security_scanner_registry_hash=None,
                security_scanner_adapter_code=None,
                security_scanner_version=None,
                security_scanner_definition_version=None,
                security_scanner_invoked=None,
                source_asset_id=source_asset.id,
                metadata_json=dict(source_asset.metadata_json),
                created_by=result.created_by,
                trace_id=trace_id,
                archived_at=None,
            )
            target_assets[source_asset.id] = target_asset
            self._session.add(target_asset)
        self._session.flush()
        checked_at = cast(datetime, self._session.scalar(select(func.clock_timestamp())))
        for source_asset_id, target_asset in target_assets.items():
            write = write_by_source[source_asset_id]
            target_asset.security_status = write.outcome
            target_asset.security_checked_at = checked_at
            target_asset.security_error_code = write.error_code
            target_asset.security_scanner_invoked = write.scanner_invoked
            if write.scanner_invoked:
                target_asset.security_scanner_profile_class = scanner_profile_class
                target_asset.security_scanner_registry_version = scanner_registry_version
                target_asset.security_scanner_registry_hash = scanner_registry_hash
                target_asset.security_scanner_adapter_code = scanner_adapter_code
                target_asset.security_scanner_version = scanner_version
                target_asset.security_scanner_definition_version = scanner_definition_version
        self._session.flush()

        block_id_map: dict[UUID, UUID] = {}
        for block in blocks:
            target_block_id = uuid4()
            block_id_map[block.id] = target_block_id
            mapped_asset = None if block.asset_id is None else target_assets.get(block.asset_id)
            if block.asset_id is not None and mapped_asset is None:
                raise AssetRevalidationSnapshotError("ASSET_REVALIDATION_SOURCE_INVALID")
            self._session.add(
                DocumentBlock(
                    id=target_block_id,
                    parse_version_id=result.id,
                    page_id=page_id_map[block.page_id],
                    block_index=block.block_index,
                    block_type=block.block_type,
                    text_content=block.text_content,
                    text_sha256=block.text_sha256,
                    bbox_json=None if block.bbox_json is None else dict(block.bbox_json),
                    coordinate_unavailable_reason=block.coordinate_unavailable_reason,
                    reading_order=block.reading_order,
                    confidence=block.confidence,
                    asset_id=None if mapped_asset is None else mapped_asset.id,
                    is_effective_content=block.is_effective_content,
                    metadata_json=dict(block.metadata_json),
                )
            )
        self._session.flush()
        exclusions = self._session.scalars(
            select(DocumentContentExclusion)
            .where(DocumentContentExclusion.parse_version_id == source.id)
            .order_by(DocumentContentExclusion.created_at, DocumentContentExclusion.id)
        ).all()
        for exclusion in exclusions:
            mapped_block_id = block_id_map.get(exclusion.block_id)
            if mapped_block_id is None:
                raise AssetRevalidationSnapshotError("ASSET_REVALIDATION_SOURCE_INVALID")
            self._session.add(
                DocumentContentExclusion(
                    id=uuid4(),
                    parse_version_id=result.id,
                    block_id=mapped_block_id,
                    exclusion_type=exclusion.exclusion_type,
                    reason=exclusion.reason,
                    rule_version=exclusion.rule_version,
                    review_status=exclusion.review_status,
                    submitted_by=exclusion.submitted_by,
                    approved_by=exclusion.approved_by,
                    approved_at=exclusion.approved_at,
                    created_at=exclusion.created_at,
                    created_by=exclusion.created_by,
                    trace_id=exclusion.trace_id,
                    archived_at=exclusion.archived_at,
                )
            )
        clean_count = sum(write.outcome == "clean" for write in writes)
        status: Literal["succeeded", "manual_review_required"] = (
            "succeeded" if clean_count == len(writes) else "manual_review_required"
        )
        result.status = status
        result.page_count = len(pages)
        result.average_confidence = source.average_confidence
        self._session.flush()
        return AssetRevalidationSnapshotResult(
            result_parse_version_id=result.id,
            page_count=len(pages),
            block_count=len(blocks),
            asset_count=len(writes),
            clean_count=clean_count,
            non_clean_count=len(writes) - clean_count,
            status=status,
        )

    def mark_asset_revalidation_failed(
        self,
        *,
        organization_id: UUID,
        file_id: UUID,
        result_parse_version_id: UUID,
        trace_id: UUID,
        error_code: str,
    ) -> bool:
        if error_code not in {
            "ASSET_REVALIDATION_IDENTITY_INVALID",
            "ASSET_REVALIDATION_RESULT_INVALID",
            "ASSET_REVALIDATION_RESULT_NOT_EMPTY",
            "ASSET_REVALIDATION_SOURCE_INVALID",
            "ASSET_STORAGE_UNAVAILABLE",
            "SCANNER_CONFIGURATION_INVALID",
        }:
            raise ValueError("unsupported asset revalidation failure code")
        file_record = self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        result = self._session.execute(
            select(DocumentParseVersion)
            .where(DocumentParseVersion.id == result_parse_version_id)
            .with_for_update(of=DocumentParseVersion)
        ).scalar_one_or_none()
        if (
            file_record is None
            or result is None
            or result.file_id != file_id
            or result.status != "running"
            or result.source_type != "security_revalidation"
            or result.trace_id != trace_id
        ):
            return False
        if self._session.scalar(
            select(func.count())
            .select_from(DocumentPage)
            .where(DocumentPage.parse_version_id == result.id)
        ):
            return False
        result.status = "failed"
        result.error_code = error_code
        result.error_message = None
        self._session.flush()
        return True

    def mark_manual_correction_failed(
        self,
        *,
        organization_id: UUID,
        file_id: UUID,
        result_parse_version_id: UUID,
        trace_id: UUID,
        error_code: str,
    ) -> bool:
        """与 Job 终结共用调用方事务，把无产物的 running 候选收敛为 failed。"""

        if error_code not in {
            "CORRECTION_FIELD_INVALID",
            "CORRECTION_RESULT_NOT_EMPTY",
            "CORRECTION_SNAPSHOT_IDENTITY_INVALID",
            "CORRECTION_SOURCE_SNAPSHOT_INVALID",
            "CORRECTION_SOURCE_VALUE_MISMATCH",
            "CORRECTION_VALUE_INVALID",
            "DOCUMENT_ASSET_SNAPSHOT_UNSUPPORTED",
        }:
            raise ValueError("unsupported manual correction failure code")
        file_record = self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        result = self._session.execute(
            select(DocumentParseVersion)
            .where(DocumentParseVersion.id == result_parse_version_id)
            .with_for_update(of=DocumentParseVersion)
        ).scalar_one_or_none()
        if (
            file_record is None
            or result is None
            or result.file_id != file_id
            or result.status != "running"
            or result.source_type != "manual_correction"
            or result.trace_id != trace_id
        ):
            return False
        if self._session.scalar(
            select(func.count())
            .select_from(DocumentPage)
            .where(DocumentPage.parse_version_id == result.id)
        ):
            return False
        result.status = "failed"
        result.error_code = error_code
        result.error_message = None
        self._session.flush()
        return True

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
    "AssetRevalidationSnapshotError",
    "AssetRevalidationSnapshotResult",
    "AssetRevalidationSource",
    "AssetRevalidationWrite",
    "DocumentProcessingRepository",
    "ManualCorrectionSnapshotError",
    "ManualCorrectionSnapshotResult",
    "ParseBlockWrite",
    "ParsePageWrite",
    "PersistedParseResult",
    "ParseVersionWrite",
]
