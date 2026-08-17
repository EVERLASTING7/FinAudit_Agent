from uuid import UUID

from app.chunking.config import P0_CHUNK_PROFILE
from app.chunking.structural import build_structural_chunks
from app.markdown.converter import SourceBlock, convert_blocks


def _block(index: int, block_type: str, text: str) -> SourceBlock:
    return SourceBlock(
        block_id=UUID(f"82000000-0000-4000-8000-{index + 1:012d}"),
        page_id=UUID("82000000-0000-4000-8000-000000000100"),
        page_no=1,
        block_index=index,
        block_type=block_type,  # type: ignore[arg-type]
        text=text,
        bbox=None,
        coordinate_unavailable_reason="source_not_paginated",
    )


def test_chunks_are_bounded_nonempty_and_traceable() -> None:
    document = convert_blocks(
        (
            _block(0, "title", "采购制度"),
            _block(1, "paragraph", "甲" * 680),
            _block(2, "quote", "乙" * 680),
        )
    )
    chunks = build_structural_chunks(document)

    assert len(chunks) >= 2
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(0 < len(chunk.content_text) <= P0_CHUNK_PROFILE.max_length for chunk in chunks)
    assert all(chunk.sources and chunk.ast_node_ids for chunk in chunks)
    assert all(chunk.title_path == ("采购制度",) for chunk in chunks)


def test_oversized_pipe_table_repeats_header_without_oversized_chunk() -> None:
    rows = ["列一\t列二"] + [f"第{i}行\t{'值' * 80}" for i in range(30)]
    chunks = build_structural_chunks(convert_blocks((_block(0, "table", "\n".join(rows)),)))

    assert len(chunks) > 1
    assert all(chunk.content_text.startswith("| 列一 | 列二 |\n| --- | --- |") for chunk in chunks)
    assert all(len(chunk.content_text) <= P0_CHUNK_PROFILE.max_length for chunk in chunks)
    assert all(len(chunk.sources) == 1 for chunk in chunks)
