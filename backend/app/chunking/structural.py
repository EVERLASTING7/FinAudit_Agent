"""`chunk-profile-v1` 的确定性结构分块器。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.chunking.config import P0_CHUNK_PROFILE, P0InitialChunkingConfig
from app.markdown.converter import MarkdownDocument, MarkdownNode


class StructuralChunkingError(ValueError):
    """输入或结果违反 P0 分块边界。"""


@dataclass(frozen=True, slots=True)
class ChunkSource:
    markdown_node_id: str
    block_id: str
    page_id: str
    page_no: int
    bbox: dict[str, object] | None
    coordinate_unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class StructuralChunk:
    chunk_index: int
    title_path: tuple[str, ...]
    content_text: str
    content_sha256: str
    ast_node_ids: tuple[str, ...]
    md_char_start: int
    md_char_end: int
    start_page_no: int
    end_page_no: int
    sources: tuple[ChunkSource, ...]
    quality_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str
    node: MarkdownNode


def _split_text(text: str, *, max_length: int) -> tuple[str, ...]:
    parts: list[str] = []
    remaining = text
    while len(remaining) > max_length:
        cut = remaining.rfind(" ", 1, max_length + 1)
        if cut < max_length // 2:
            cut = remaining.rfind("\n", 1, max_length + 1)
        if cut < max_length // 2:
            cut = max_length
        part = remaining[:cut].strip()
        if not part:
            raise StructuralChunkingError("CHUNK_SPLIT_FAILED")
        parts.append(part)
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return tuple(parts)


def _table_units(node: MarkdownNode, *, max_length: int) -> tuple[_Unit, ...]:
    lines = node.markdown.splitlines()
    if len(lines) < 3:
        raise StructuralChunkingError("CHUNK_TABLE_INVALID")
    header = "\n".join(lines[:2])
    units: list[_Unit] = []
    current = header
    for row in lines[2:]:
        candidate = f"{current}\n{row}"
        if len(candidate) <= max_length:
            current = candidate
            continue
        if current == header:
            raise StructuralChunkingError("CHUNK_TABLE_ROW_OVERSIZED")
        units.append(_Unit(current, node))
        current = f"{header}\n{row}"
        if len(current) > max_length:
            raise StructuralChunkingError("CHUNK_TABLE_ROW_OVERSIZED")
    units.append(_Unit(current, node))
    return tuple(units)


def _units(document: MarkdownDocument, config: P0InitialChunkingConfig) -> tuple[_Unit, ...]:
    result: list[_Unit] = []
    for node in document.nodes:
        if len(node.markdown) <= config.max_length:
            result.append(_Unit(node.markdown, node))
        elif node.node_type == "table" and config.table_handling.repeat_header_on_split:
            result.extend(_table_units(node, max_length=config.max_length))
        else:
            result.extend(
                _Unit(part, node)
                for part in _split_text(node.markdown, max_length=config.max_length)
            )
    if not result:
        raise StructuralChunkingError("CHUNK_SOURCE_EMPTY")
    return tuple(result)


def _joined_length(units: list[_Unit], extra: _Unit | None = None) -> int:
    values = [unit.text for unit in units]
    if extra is not None:
        values.append(extra.text)
    return len("\n\n".join(values))


def _overlap(units: list[_Unit], config: P0InitialChunkingConfig) -> list[_Unit]:
    carried: list[_Unit] = []
    length = 0
    for unit in reversed(units):
        separator = 2 if carried else 0
        if length + separator + len(unit.text) > config.overlap_length:
            break
        carried.insert(0, unit)
        length += separator + len(unit.text)
    if carried:
        return carried
    last = units[-1]
    if last.node.node_type == "table":
        return []
    suffix = last.text[-config.overlap_length :].lstrip()
    return [] if not suffix else [_Unit(suffix, last.node)]


def _materialize(
    index: int,
    units: list[_Unit],
    config: P0InitialChunkingConfig,
) -> StructuralChunk:
    content = "\n\n".join(unit.text for unit in units).strip()
    if not content or len(content) > config.max_length:
        raise StructuralChunkingError("CHUNK_LENGTH_INVALID")
    unique_nodes = tuple(dict.fromkeys(unit.node.node_id for unit in units))
    sources_by_node: dict[str, ChunkSource] = {}
    for unit in units:
        node = unit.node
        sources_by_node.setdefault(
            node.node_id,
            ChunkSource(
                markdown_node_id=node.node_id,
                block_id=str(node.source_block_id),
                page_id=str(node.page_id),
                page_no=node.page_no,
                bbox=node.bbox,
                coordinate_unavailable_reason=node.coordinate_unavailable_reason,
            ),
        )
    pages = tuple(source.page_no for source in sources_by_node.values())
    flags = ("below_min_structural_tail",) if len(content) < config.min_length else ()
    return StructuralChunk(
        chunk_index=index,
        title_path=units[0].node.title_path,
        content_text=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        ast_node_ids=unique_nodes,
        md_char_start=min(unit.node.md_char_start for unit in units),
        md_char_end=max(unit.node.md_char_end for unit in units),
        start_page_no=min(pages),
        end_page_no=max(pages),
        sources=tuple(sources_by_node.values()),
        quality_flags=flags,
    )


def build_structural_chunks(
    document: MarkdownDocument,
    config: P0InitialChunkingConfig = P0_CHUNK_PROFILE,
) -> tuple[StructuralChunk, ...]:
    """按结构节点聚合，并对超长文本或表格做有界拆分。"""

    units = _units(document, config)
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    for unit in units:
        projected = _joined_length(current, unit)
        should_flush = bool(current) and (
            projected > config.max_length
            or (_joined_length(current) >= config.min_length and projected > config.target_length)
        )
        if should_flush:
            groups.append(current)
            current = _overlap(current, config)
            if _joined_length(current, unit) > config.max_length:
                current = []
        current.append(unit)
    if current:
        groups.append(current)

    chunks = tuple(_materialize(index, group, config) for index, group in enumerate(groups))
    if not chunks or any(not chunk.sources for chunk in chunks):
        raise StructuralChunkingError("CHUNK_TRACEABILITY_INVALID")
    return chunks


__all__ = [
    "ChunkSource",
    "StructuralChunk",
    "StructuralChunkingError",
    "build_structural_chunks",
]
