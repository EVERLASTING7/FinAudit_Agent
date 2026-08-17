"""Markdown 候选生成、来源映射与原子激活 Repository。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.markdown.converter import BlockType, SourceBlock, convert_blocks
from app.markdown.quality_metrics import calculate_markdown_quality_metrics
from app.models.document_processing import (
    DocumentAsset,
    DocumentBlock,
    DocumentContentExclusion,
    DocumentPage,
    DocumentParseVersion,
)
from app.models.documents import FileRecord
from app.models.knowledge import (
    DocumentMarkdownVersion,
    MarkdownSourceMapping,
    MarkdownValidationResult,
)

MARKDOWN_CONVERTER_NAME = "markdown-it-py"
MARKDOWN_CONVERTER_VERSION = "commonmark-gfm-table-v1"
MARKDOWN_SCHEMA_VERSION = "markdown-ast-v1"
MARKDOWN_CODE_VERSION = "document-markdown-v1"


@dataclass(frozen=True, slots=True)
class MarkdownWriteResult:
    outcome: Literal["active", "reused", "review_required"]
    parse_version_id: UUID
    markdown_version_id: UUID | None
    version_no: int | None
    content_sha256: str | None
    char_count: int | None
    source_mapping_count: int


class MarkdownWriteRepository:
    """调用方持有事务；该 Repository 不执行外部 I/O。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def generate_and_activate(
        self,
        *,
        organization_id: UUID,
        file_id: UUID,
        parse_version_id: UUID,
        trace_id: UUID,
        actor_id: UUID | None,
    ) -> MarkdownWriteResult:
        file_record = self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        parse_version = self._session.execute(
            select(DocumentParseVersion)
            .where(
                DocumentParseVersion.id == parse_version_id,
                DocumentParseVersion.file_id == file_id,
                DocumentParseVersion.archived_at.is_(None),
            )
            .with_for_update(of=DocumentParseVersion)
        ).scalar_one_or_none()
        if (
            file_record is None
            or parse_version is None
            or file_record.status != "stored"
            or file_record.security_scan_status != "clean"
        ):
            raise ValueError("MARKDOWN_PRECONDITION_FAILED")
        if parse_version.status == "manual_review_required":
            return MarkdownWriteResult(
                outcome="review_required",
                parse_version_id=parse_version_id,
                markdown_version_id=None,
                version_no=None,
                content_sha256=None,
                char_count=None,
                source_mapping_count=0,
            )
        if parse_version.status not in {"succeeded", "active"}:
            raise ValueError("MARKDOWN_PARSE_VERSION_NOT_READY")

        existing = self._session.execute(
            select(DocumentMarkdownVersion).where(
                DocumentMarkdownVersion.parse_version_id == parse_version_id,
                DocumentMarkdownVersion.converter_version == MARKDOWN_CONVERTER_VERSION,
                DocumentMarkdownVersion.schema_version == MARKDOWN_SCHEMA_VERSION,
                DocumentMarkdownVersion.status == "active",
            )
        ).scalar_one_or_none()
        if existing is not None:
            mapping_count = self._session.scalar(
                select(func.count(MarkdownSourceMapping.id)).where(
                    MarkdownSourceMapping.markdown_version_id == existing.id
                )
            )
            if mapping_count is None or mapping_count <= 0:
                raise ValueError("MARKDOWN_ACTIVE_MAPPING_MISSING")
            return MarkdownWriteResult(
                outcome="reused",
                parse_version_id=parse_version_id,
                markdown_version_id=existing.id,
                version_no=existing.version_no,
                content_sha256=existing.content_sha256,
                char_count=existing.char_count,
                source_mapping_count=mapping_count,
            )

        rows = self._session.execute(
            select(DocumentBlock, DocumentPage, DocumentAsset)
            .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
            .outerjoin(DocumentAsset, DocumentAsset.id == DocumentBlock.asset_id)
            .where(
                DocumentBlock.parse_version_id == parse_version_id,
                DocumentBlock.is_effective_content.is_(True),
            )
            .order_by(DocumentBlock.block_index)
        ).all()
        if not rows:
            raise ValueError("MARKDOWN_SOURCE_EMPTY")
        approved_exclusions = set(
            self._session.scalars(
                select(DocumentContentExclusion.block_id).where(
                    DocumentContentExclusion.parse_version_id == parse_version_id,
                    DocumentContentExclusion.review_status == "approved",
                    DocumentContentExclusion.archived_at.is_(None),
                )
            ).all()
        )
        source_blocks: list[SourceBlock] = []
        valid_block_ids: list[str] = []
        for block, page, asset in rows:
            valid_block_ids.append(str(block.id))
            if block.id in approved_exclusions:
                continue
            source_blocks.append(
                SourceBlock(
                    block_id=block.id,
                    page_id=page.id,
                    page_no=page.page_no,
                    block_index=block.block_index,
                    block_type=cast(BlockType, block.block_type),
                    text=(
                        block.text_content if block.text_content is not None else "complex table"
                    ),
                    bbox=block.bbox_json,
                    coordinate_unavailable_reason=block.coordinate_unavailable_reason,
                    asset_id=block.asset_id,
                    asset_type=None if asset is None else asset.asset_type,
                )
            )
        if not source_blocks:
            raise ValueError("MARKDOWN_EFFECTIVE_SOURCE_EMPTY")

        document = convert_blocks(tuple(source_blocks))
        node_ids = tuple(node.node_id for node in document.nodes)
        represented_ids = tuple(str(node.source_block_id) for node in document.nodes)
        metrics = calculate_markdown_quality_metrics(
            evidence_node_ids=node_ids,
            mapped_evidence_node_ids=node_ids,
            valid_block_ids=tuple(valid_block_ids),
            approved_excluded_block_ids=tuple(
                str(block_id)
                for block_id in valid_block_ids
                if UUID(block_id) in approved_exclusions
            ),
            represented_block_ids=represented_ids,
        )
        if not metrics.activation_coverage_gate_passed:
            raise ValueError("MARKDOWN_QUALITY_GATE_FAILED")

        now = self._session.scalar(select(func.clock_timestamp()))
        if now is None:
            raise ValueError("DATABASE_CLOCK_UNAVAILABLE")
        if parse_version.status == "succeeded":
            previous_parse = self._session.execute(
                select(DocumentParseVersion)
                .where(
                    DocumentParseVersion.file_id == file_id,
                    DocumentParseVersion.status == "active",
                    DocumentParseVersion.id != parse_version_id,
                )
                .with_for_update(of=DocumentParseVersion)
            ).scalar_one_or_none()
            if previous_parse is not None:
                previous_parse.status = "superseded"
                previous_parse.superseded_at = now
                self._session.flush()
            parse_version.status = "active"
            parse_version.activated_at = now
            self._session.flush()

        previous_markdown = self._session.execute(
            select(DocumentMarkdownVersion)
            .where(
                DocumentMarkdownVersion.file_id == file_id,
                DocumentMarkdownVersion.status == "active",
            )
            .with_for_update(of=DocumentMarkdownVersion)
        ).scalar_one_or_none()
        if previous_markdown is not None:
            previous_markdown.status = "superseded"
            previous_markdown.superseded_at = now
            self._session.flush()

        version_no = (
            self._session.scalar(
                select(func.coalesce(func.max(DocumentMarkdownVersion.version_no), 0)).where(
                    DocumentMarkdownVersion.file_id == file_id
                )
            )
            or 0
        ) + 1
        markdown_version_id = uuid4()
        quality_summary: dict[str, object] = {
            "evidence_source_mapping": {
                "covered": metrics.evidence_source_mapping.covered_count,
                "total": metrics.evidence_source_mapping.total_count,
            },
            "valid_structure_block": {
                "covered": metrics.valid_structure_block.covered_count,
                "total": metrics.valid_structure_block.total_count,
            },
        }
        self._session.add(
            DocumentMarkdownVersion(
                id=markdown_version_id,
                organization_id=organization_id,
                file_id=file_id,
                parse_version_id=parse_version_id,
                version_no=version_no,
                converter_name=MARKDOWN_CONVERTER_NAME,
                converter_version=MARKDOWN_CONVERTER_VERSION,
                schema_version=MARKDOWN_SCHEMA_VERSION,
                code_version=MARKDOWN_CODE_VERSION,
                status="active",
                markdown_text=document.markdown_text,
                content_sha256=document.content_sha256,
                char_count=len(document.markdown_text),
                token_count=None,
                document_metadata_json={
                    "parser_token_types": list(document.parser_token_types),
                },
                quality_summary_json=quality_summary,
                warning_count=0,
                blocking_issue_count=0,
                failure_reason=None,
                activated_at=now,
                superseded_at=None,
                created_by=actor_id,
                trace_id=trace_id,
            )
        )
        self._session.flush()
        for node in document.nodes:
            self._session.add(
                MarkdownSourceMapping(
                    id=uuid4(),
                    markdown_version_id=markdown_version_id,
                    ast_node_id=node.node_id,
                    mapping_type="source",
                    md_char_start=node.md_char_start,
                    md_char_end=node.md_char_end,
                    md_line_start=node.md_line_start,
                    md_line_end=node.md_line_end,
                    page_id=node.page_id,
                    block_id=node.source_block_id,
                    bbox_json=node.bbox,
                    coverage_status="full",
                    coordinate_unavailable_reason=node.coordinate_unavailable_reason,
                )
            )
        self._session.add(
            MarkdownValidationResult(
                id=uuid4(),
                markdown_version_id=markdown_version_id,
                validator_code="safe-commonmark-gfm-table",
                validator_version="1",
                severity="info",
                issue_code="PASS",
                message="deterministic parser and source mapping gates passed",
                ast_node_id=None,
                md_char_start=None,
                md_char_end=None,
                source_block_id=None,
                is_blocking=False,
                details_json={"raw_html": False, "external_resources": False},
            )
        )
        self._session.flush()
        return MarkdownWriteResult(
            outcome="active",
            parse_version_id=parse_version_id,
            markdown_version_id=markdown_version_id,
            version_no=version_no,
            content_sha256=document.content_sha256,
            char_count=len(document.markdown_text),
            source_mapping_count=len(document.nodes),
        )


__all__ = [
    "MARKDOWN_CODE_VERSION",
    "MARKDOWN_CONVERTER_NAME",
    "MARKDOWN_CONVERTER_VERSION",
    "MARKDOWN_SCHEMA_VERSION",
    "MarkdownWriteRepository",
    "MarkdownWriteResult",
]
