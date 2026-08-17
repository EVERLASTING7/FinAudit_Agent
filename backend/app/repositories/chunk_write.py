"""活动 Markdown 到不可变结构分块集合的原子持久化。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.policy import canonicalize_jcs
from app.chunking.config import (
    CHUNK_PROFILE_HASH,
    CHUNK_PROFILE_VERSION,
    P0_CHUNK_PROFILE,
    chunk_profile_payload,
)
from app.chunking.structural import StructuralChunk, build_structural_chunks
from app.markdown.converter import BlockType, MarkdownDocument, SourceBlock, convert_blocks
from app.models.document_processing import (
    DocumentAsset,
    DocumentBlock,
    DocumentPage,
    DocumentParseVersion,
)
from app.models.knowledge import (
    ChunkingConfig,
    DocumentChunk,
    DocumentChunkSet,
    DocumentChunkSource,
    DocumentMarkdownVersion,
    MarkdownSourceMapping,
    PolicyDocument,
)

CHUNK_CODE_VERSION = "structural-chunker-v1"


@dataclass(frozen=True, slots=True)
class ChunkWriteResult:
    outcome: Literal["active", "reused"]
    chunk_set_id: UUID
    markdown_version_id: UUID
    version_no: int
    chunk_count: int
    content_manifest_hash: str


class ChunkWriteRepository:
    """调用方持有事务；写入只依赖 PostgreSQL 中的已验证事实。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def generate_and_activate(
        self,
        *,
        organization_id: UUID,
        policy_document_id: UUID,
        trace_id: UUID,
        actor_id: UUID,
    ) -> ChunkWriteResult:
        policy = self._session.execute(
            select(PolicyDocument)
            .where(
                PolicyDocument.id == policy_document_id,
                PolicyDocument.organization_id == organization_id,
                PolicyDocument.deleted_at.is_(None),
            )
            .with_for_update(of=PolicyDocument)
        ).scalar_one_or_none()
        if policy is None:
            raise ValueError("POLICY_DOCUMENT_NOT_FOUND")
        if policy.status != "business_approved":
            raise ValueError("POLICY_NOT_BUSINESS_APPROVED")

        markdown = self._session.execute(
            select(DocumentMarkdownVersion).where(
                DocumentMarkdownVersion.organization_id == organization_id,
                DocumentMarkdownVersion.file_id == policy.source_file_id,
                DocumentMarkdownVersion.status == "active",
                DocumentMarkdownVersion.blocking_issue_count == 0,
            )
        ).scalar_one_or_none()
        if markdown is None:
            raise ValueError("ACTIVE_MARKDOWN_NOT_FOUND")

        parse_version = self._session.scalar(
            select(DocumentParseVersion).where(
                DocumentParseVersion.id == markdown.parse_version_id,
                DocumentParseVersion.file_id == policy.source_file_id,
                DocumentParseVersion.status == "active",
                DocumentParseVersion.archived_at.is_(None),
            )
        )
        if parse_version is None:
            raise ValueError("ACTIVE_MARKDOWN_PARSE_INVALID")

        existing = self._session.scalar(
            select(DocumentChunkSet).where(
                DocumentChunkSet.policy_document_id == policy_document_id,
                DocumentChunkSet.markdown_version_id == markdown.id,
                DocumentChunkSet.profile_hash == CHUNK_PROFILE_HASH,
            )
        )
        if existing is not None:
            if (
                existing.status != "active"
                or existing.content_manifest_hash is None
                or existing.chunk_count <= 0
            ):
                raise ValueError("CHUNK_INPUT_ALREADY_FINALIZED")
            return ChunkWriteResult(
                outcome="reused",
                chunk_set_id=existing.id,
                markdown_version_id=markdown.id,
                version_no=existing.version_no,
                chunk_count=existing.chunk_count,
                content_manifest_hash=existing.content_manifest_hash,
            )

        document, mappings = self._rebuild_verified_markdown(markdown)
        chunks = build_structural_chunks(document, P0_CHUNK_PROFILE)
        manifest_hash = _content_manifest_hash(chunks, document)
        now = self._session.scalar(select(func.clock_timestamp()))
        if now is None:
            raise ValueError("DATABASE_CLOCK_UNAVAILABLE")
        config = self._get_or_create_profile(organization_id)

        previous = self._session.execute(
            select(DocumentChunkSet)
            .where(
                DocumentChunkSet.policy_document_id == policy_document_id,
                DocumentChunkSet.status == "active",
            )
            .with_for_update(of=DocumentChunkSet)
        ).scalar_one_or_none()
        if previous is not None:
            previous.status = "superseded"
            previous.superseded_at = now
            self._session.flush()

        version_no = (
            self._session.scalar(
                select(func.coalesce(func.max(DocumentChunkSet.version_no), 0)).where(
                    DocumentChunkSet.policy_document_id == policy_document_id
                )
            )
            or 0
        ) + 1
        chunk_set_id = uuid4()
        profile = chunk_profile_payload()
        self._session.add(
            DocumentChunkSet(
                id=chunk_set_id,
                organization_id=organization_id,
                policy_document_id=policy_document_id,
                markdown_version_id=markdown.id,
                chunking_config_id=config.id,
                version_no=version_no,
                status="active",
                profile_version=CHUNK_PROFILE_VERSION,
                profile_hash=CHUNK_PROFILE_HASH,
                profile_json=profile,
                chunk_count=len(chunks),
                content_manifest_hash=manifest_hash,
                quality_summary_json={
                    "source_traceability": {
                        "covered": len(chunks),
                        "total": len(chunks),
                    },
                    "content_manifest_algorithm": "sha256-jcs-v1",
                },
                blocking_issue_count=0,
                failure_reason=None,
                activated_at=now,
                superseded_at=None,
                created_by=actor_id,
                trace_id=trace_id,
            )
        )
        self._session.flush()

        mapping_by_node = {mapping.ast_node_id: mapping for mapping in mappings}
        node_by_id = {node.node_id: node for node in document.nodes}
        for chunk in chunks:
            chunk_id = uuid4()
            self._session.add(
                DocumentChunk(
                    id=chunk_id,
                    chunk_set_id=chunk_set_id,
                    chunk_index=chunk.chunk_index,
                    title_path=list(chunk.title_path),
                    content_text=chunk.content_text,
                    content_sha256=chunk.content_sha256,
                    ast_node_ids=list(chunk.ast_node_ids),
                    md_char_start=chunk.md_char_start,
                    md_char_end=chunk.md_char_end,
                    start_page_no=chunk.start_page_no,
                    end_page_no=chunk.end_page_no,
                    char_count=len(chunk.content_text),
                    token_count=None,
                    quality_flags=list(chunk.quality_flags),
                )
            )
            for sequence, source in enumerate(chunk.sources, start=1):
                mapping = mapping_by_node.get(source.markdown_node_id)
                node = node_by_id.get(source.markdown_node_id)
                if mapping is None or node is None:
                    raise ValueError("CHUNK_SOURCE_MAPPING_MISSING")
                self._session.add(
                    DocumentChunkSource(
                        id=uuid4(),
                        chunk_id=chunk_id,
                        source_seq=sequence,
                        markdown_mapping_id=mapping.id,
                        parse_version_id=markdown.parse_version_id,
                        page_id=UUID(source.page_id),
                        block_id=UUID(source.block_id),
                        page_no=source.page_no,
                        bbox_json=source.bbox,
                        quoted_text_sha256=hashlib.sha256(
                            node.markdown.encode("utf-8")
                        ).hexdigest(),
                        coordinate_unavailable_reason=source.coordinate_unavailable_reason,
                    )
                )
        self._session.flush()
        return ChunkWriteResult(
            outcome="active",
            chunk_set_id=chunk_set_id,
            markdown_version_id=markdown.id,
            version_no=version_no,
            chunk_count=len(chunks),
            content_manifest_hash=manifest_hash,
        )

    def _get_or_create_profile(self, organization_id: UUID) -> ChunkingConfig:
        identity = f"finaudit:chunk-profile:{organization_id}:{CHUNK_PROFILE_HASH}"
        self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(identity, 0)))
        ).one()
        config = self._session.scalar(
            select(ChunkingConfig).where(
                ChunkingConfig.organization_id == organization_id,
                ChunkingConfig.profile_version == CHUNK_PROFILE_VERSION,
                ChunkingConfig.profile_hash == CHUNK_PROFILE_HASH,
            )
        )
        if config is not None:
            if config.parameters_json != chunk_profile_payload():
                raise ValueError("CHUNK_PROFILE_DRIFT")
            return config
        config = ChunkingConfig(
            id=uuid4(),
            organization_id=organization_id,
            profile_version=CHUNK_PROFILE_VERSION,
            profile_hash=CHUNK_PROFILE_HASH,
            parameters_json=chunk_profile_payload(),
            code_version=CHUNK_CODE_VERSION,
        )
        self._session.add(config)
        self._session.flush()
        return config

    def _rebuild_verified_markdown(
        self,
        markdown: DocumentMarkdownVersion,
    ) -> tuple[MarkdownDocument, tuple[MarkdownSourceMapping, ...]]:
        rows = self._session.execute(
            select(MarkdownSourceMapping, DocumentBlock, DocumentPage, DocumentAsset)
            .join(DocumentBlock, DocumentBlock.id == MarkdownSourceMapping.block_id)
            .join(DocumentPage, DocumentPage.id == MarkdownSourceMapping.page_id)
            .outerjoin(DocumentAsset, DocumentAsset.id == DocumentBlock.asset_id)
            .where(MarkdownSourceMapping.markdown_version_id == markdown.id)
            .order_by(MarkdownSourceMapping.md_char_start)
        ).all()
        if not rows:
            raise ValueError("MARKDOWN_SOURCE_MAPPING_MISSING")

        source_blocks: list[SourceBlock] = []
        mappings: list[MarkdownSourceMapping] = []
        for mapping, block, page, asset in rows:
            if (
                mapping.coverage_status != "full"
                or block.parse_version_id != markdown.parse_version_id
                or page.parse_version_id != markdown.parse_version_id
                or block.page_id != page.id
                or not block.is_effective_content
            ):
                raise ValueError("MARKDOWN_SOURCE_MAPPING_INVALID")
            source_blocks.append(
                SourceBlock(
                    block_id=block.id,
                    page_id=page.id,
                    page_no=page.page_no,
                    block_index=block.block_index,
                    block_type=cast(BlockType, block.block_type),
                    text=block.text_content if block.text_content is not None else "complex table",
                    bbox=block.bbox_json,
                    coordinate_unavailable_reason=block.coordinate_unavailable_reason,
                    asset_id=block.asset_id,
                    asset_type=None if asset is None else asset.asset_type,
                )
            )
            mappings.append(mapping)

        document = convert_blocks(tuple(source_blocks))
        if (
            document.markdown_text != markdown.markdown_text
            or document.content_sha256 != markdown.content_sha256
            or len(document.markdown_text) != markdown.char_count
            or len(document.nodes) != len(mappings)
        ):
            raise ValueError("ACTIVE_MARKDOWN_CONTENT_DRIFT")
        for node, mapping in zip(document.nodes, mappings, strict=True):
            if (
                mapping.ast_node_id != node.node_id
                or mapping.md_char_start != node.md_char_start
                or mapping.md_char_end != node.md_char_end
                or mapping.md_line_start != node.md_line_start
                or mapping.md_line_end != node.md_line_end
                or mapping.page_id != node.page_id
                or mapping.block_id != node.source_block_id
                or mapping.bbox_json != node.bbox
                or mapping.coordinate_unavailable_reason != node.coordinate_unavailable_reason
            ):
                raise ValueError("ACTIVE_MARKDOWN_MAPPING_DRIFT")
        return document, tuple(mappings)


def _content_manifest_hash(
    chunks: tuple[StructuralChunk, ...],
    document: MarkdownDocument,
) -> str:
    node_by_id = {node.node_id: node for node in document.nodes}
    manifest: dict[str, object] = {
        "profile_version": CHUNK_PROFILE_VERSION,
        "profile_hash": CHUNK_PROFILE_HASH,
        "markdown_content_sha256": document.content_sha256,
        "chunks": [
            {
                "chunk_index": chunk.chunk_index,
                "content_sha256": chunk.content_sha256,
                "ast_node_ids": list(chunk.ast_node_ids),
                "md_char_start": chunk.md_char_start,
                "md_char_end": chunk.md_char_end,
                "start_page_no": chunk.start_page_no,
                "end_page_no": chunk.end_page_no,
                "sources": [
                    {
                        "ast_node_id": source.markdown_node_id,
                        "block_id": source.block_id,
                        "page_id": source.page_id,
                        "page_no": source.page_no,
                        "quoted_text_sha256": hashlib.sha256(
                            node_by_id[source.markdown_node_id].markdown.encode("utf-8")
                        ).hexdigest(),
                    }
                    for source in chunk.sources
                ],
            }
            for chunk in chunks
        ],
    }
    return hashlib.sha256(canonicalize_jcs(manifest)).hexdigest()


__all__ = ["CHUNK_CODE_VERSION", "ChunkWriteRepository", "ChunkWriteResult"]
