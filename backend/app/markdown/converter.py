"""从活动结构块生成安全、确定性的 CommonMark/GFM-table 文本。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from markdown_it import MarkdownIt

BlockType = Literal["title", "paragraph", "list", "table", "quote", "asset", "other"]
_COORDINATE_REASONS = {"source_not_paginated", "extractor_not_available"}
_PROHIBITED_TOKEN_PREFIXES = ("html_", "link_", "image")
_MARKDOWN_META = re.compile(r"([\\`*{}\[\]()#+.!_|<>~-])")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


class MarkdownConversionError(ValueError):
    """转换输入或输出不满足安全与可追溯合同。"""


@dataclass(frozen=True, slots=True)
class SourceBlock:
    block_id: UUID
    page_id: UUID
    page_no: int
    block_index: int
    block_type: BlockType
    text: str
    bbox: dict[str, object] | None
    coordinate_unavailable_reason: str | None
    asset_id: UUID | None = None
    asset_type: str | None = None

    def __post_init__(self) -> None:
        if self.page_no <= 0 or self.block_index < 0 or not self.text.strip():
            raise MarkdownConversionError("MARKDOWN_SOURCE_BLOCK_INVALID")
        if (self.bbox is None) == (self.coordinate_unavailable_reason is None):
            raise MarkdownConversionError("MARKDOWN_SOURCE_COORDINATE_MATRIX_INVALID")
        if (
            self.coordinate_unavailable_reason is not None
            and self.coordinate_unavailable_reason not in _COORDINATE_REASONS
        ):
            raise MarkdownConversionError("MARKDOWN_SOURCE_COORDINATE_REASON_INVALID")
        if self.block_type == "asset":
            if self.asset_id is None:
                raise MarkdownConversionError("MARKDOWN_ASSET_ID_REQUIRED")
        elif self.asset_id is not None or self.asset_type is not None:
            raise MarkdownConversionError("MARKDOWN_ASSET_REFERENCE_INVALID")


@dataclass(frozen=True, slots=True)
class MarkdownNode:
    node_id: str
    node_type: BlockType
    markdown: str
    md_char_start: int
    md_char_end: int
    md_line_start: int
    md_line_end: int
    source_block_id: UUID
    page_id: UUID
    page_no: int
    bbox: dict[str, object] | None
    coordinate_unavailable_reason: str | None
    title_path: tuple[str, ...]
    asset_id: UUID | None


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    markdown_text: str
    content_sha256: str
    nodes: tuple[MarkdownNode, ...]
    parser_token_types: tuple[str, ...]


def _escape_inline(value: str) -> str:
    normalized = " ".join(value.replace("\r", "\n").splitlines()).strip()
    if not normalized or _CONTROL.search(normalized):
        raise MarkdownConversionError("MARKDOWN_SOURCE_TEXT_INVALID")
    return _MARKDOWN_META.sub(r"\\\1", normalized)


def _table_rows(value: str) -> tuple[tuple[str, ...], ...] | None:
    raw_lines = tuple(line.strip() for line in value.replace("\r", "\n").splitlines())
    if len(raw_lines) < 2 or any(not line for line in raw_lines):
        return None
    delimiter = "\t" if all("\t" in line for line in raw_lines) else "|"
    if delimiter == "|" and not all("|" in line for line in raw_lines):
        return None
    rows: list[tuple[str, ...]] = []
    for line in raw_lines:
        candidate = line.strip("|") if delimiter == "|" else line
        cells = tuple(cell.strip() for cell in candidate.split(delimiter))
        if len(cells) < 2 or any(not cell for cell in cells):
            return None
        rows.append(cells)
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        return None
    return tuple(rows)


def _pipe_table(rows: tuple[tuple[str, ...], ...]) -> str:
    escaped = tuple(tuple(_escape_inline(cell) for cell in row) for row in rows)
    header = "| " + " | ".join(escaped[0]) + " |"
    separator = "| " + " | ".join("---" for _ in escaped[0]) + " |"
    body = tuple("| " + " | ".join(row) + " |" for row in escaped[1:])
    return "\n".join((header, separator, *body))


def _render_block(block: SourceBlock) -> str:
    if block.block_type == "asset":
        label = "复杂表格资源" if block.asset_type == "complex_table" else "文档资源"
        return f"{label}：{block.asset_id}"
    if block.block_type == "table":
        rows = _table_rows(block.text)
        if rows is None:
            raise MarkdownConversionError("COMPLEX_TABLE_ASSET_REQUIRED")
        return _pipe_table(rows)
    escaped = _escape_inline(block.text)
    if block.block_type == "title":
        return f"# {escaped}"
    if block.block_type == "list":
        return f"- {escaped}"
    if block.block_type == "quote":
        return f"> {escaped}"
    return escaped


def _parser() -> MarkdownIt:
    parser = MarkdownIt(
        "commonmark",
        {"html": False, "linkify": False, "typographer": False},
    ).enable("table")
    parser.disable(["autolink", "image", "link"])
    return parser


def convert_blocks(blocks: tuple[SourceBlock, ...]) -> MarkdownDocument:
    """按 page/reading order 已排序的块生成不可变 Markdown 候选。"""

    if not blocks:
        raise MarkdownConversionError("MARKDOWN_SOURCE_EMPTY")
    if tuple(block.block_index for block in blocks) != tuple(
        sorted(block.block_index for block in blocks)
    ) or len({block.block_id for block in blocks}) != len(blocks):
        raise MarkdownConversionError("MARKDOWN_SOURCE_ORDER_INVALID")

    rendered: list[str] = []
    pending: list[tuple[SourceBlock, str, tuple[str, ...]]] = []
    title_path: tuple[str, ...] = ()
    for block in blocks:
        markdown = _render_block(block)
        if block.block_type == "title":
            title_path = (block.text.strip(),)
        rendered.append(markdown)
        pending.append((block, markdown, title_path))

    markdown_text = "\n\n".join(rendered) + "\n"
    nodes: list[MarkdownNode] = []
    char_offset = 0
    line_offset = 1
    for index, (block, markdown, node_title_path) in enumerate(pending):
        start = char_offset
        end = start + len(markdown)
        line_count = markdown.count("\n") + 1
        nodes.append(
            MarkdownNode(
                node_id=f"block-{block.block_id}",
                node_type=block.block_type,
                markdown=markdown,
                md_char_start=start,
                md_char_end=end,
                md_line_start=line_offset,
                md_line_end=line_offset + line_count - 1,
                source_block_id=block.block_id,
                page_id=block.page_id,
                page_no=block.page_no,
                bbox=block.bbox,
                coordinate_unavailable_reason=block.coordinate_unavailable_reason,
                title_path=node_title_path,
                asset_id=block.asset_id,
            )
        )
        separator = 1 if index == len(pending) - 1 else 2
        char_offset = end + separator
        line_offset += line_count + (1 if index < len(pending) - 1 else 0)

    tokens = _parser().parse(markdown_text)
    token_types = tuple(token.type for token in tokens)
    if any(token_type.startswith(_PROHIBITED_TOKEN_PREFIXES) for token_type in token_types):
        raise MarkdownConversionError("MARKDOWN_UNSAFE_AST")
    return MarkdownDocument(
        markdown_text=markdown_text,
        content_sha256=hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
        nodes=tuple(nodes),
        parser_token_types=token_types,
    )


__all__ = [
    "BlockType",
    "MarkdownConversionError",
    "MarkdownDocument",
    "MarkdownNode",
    "SourceBlock",
    "convert_blocks",
]
