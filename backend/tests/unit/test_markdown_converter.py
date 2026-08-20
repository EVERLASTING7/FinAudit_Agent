import hashlib
from uuid import UUID

import pytest

from app.markdown.converter import (
    MarkdownConversionError,
    SourceBlock,
    convert_blocks,
)


def _block(
    index: int,
    block_type: str,
    text: str,
    *,
    bbox: dict[str, object] | None = None,
    reason: str | None = "extractor_not_available",
    asset_id: UUID | None = None,
    asset_type: str | None = None,
) -> SourceBlock:
    return SourceBlock(
        block_id=UUID(f"81000000-0000-4000-8000-{index + 1:012d}"),
        page_id=UUID("81000000-0000-4000-8000-000000000100"),
        page_no=1,
        block_index=index,
        block_type=block_type,  # type: ignore[arg-type]
        text=text,
        bbox=bbox,
        coordinate_unavailable_reason=reason,
        asset_id=asset_id,
        asset_type=asset_type,
    )


def test_converts_quote_table_and_untrusted_url_without_active_content() -> None:
    document = convert_blocks(
        (
            _block(0, "title", "制度 <标题>"),
            _block(1, "quote", "不得访问 <https://evil.example/x>"),
            _block(2, "table", "项目\t金额\n甲\t100"),
        )
    )

    assert document.markdown_text.startswith("# 制度 \\<标题\\>")
    assert "> 不得访问 \\<https://evil\\.example/x\\>" in document.markdown_text
    assert "| 项目 | 金额 |" in document.markdown_text
    assert "table_open" in document.parser_token_types
    assert not any(
        token.startswith(("html_", "link_", "image")) for token in document.parser_token_types
    )
    assert [node.md_char_start for node in document.nodes] == sorted(
        node.md_char_start for node in document.nodes
    )


def test_source_mapping_spans_match_the_generated_document_exactly() -> None:
    document = convert_blocks(
        (
            _block(0, "title", "制度标题"),
            _block(1, "table", "项目\t金额\n甲\t100"),
            _block(2, "quote", "保留原始引用"),
        )
    )

    assert (
        document.content_sha256
        == hashlib.sha256(document.markdown_text.encode("utf-8")).hexdigest()
    )
    for index, node in enumerate(document.nodes):
        assert document.markdown_text[node.md_char_start : node.md_char_end] == node.markdown
        assert node.md_line_start == document.markdown_text[: node.md_char_start].count("\n") + 1
        assert node.md_line_end == node.md_line_start + node.markdown.count("\n")
        if index:
            previous = document.nodes[index - 1]
            assert document.markdown_text[previous.md_char_end : node.md_char_start] == "\n\n"

    assert document.markdown_text[document.nodes[-1].md_char_end :] == "\n"


def test_complex_table_requires_an_opaque_asset_reference() -> None:
    with pytest.raises(MarkdownConversionError, match="COMPLEX_TABLE_ASSET_REQUIRED"):
        convert_blocks((_block(0, "table", "merged table without rows"),))

    asset_id = UUID("81000000-0000-4000-8000-000000000999")
    document = convert_blocks(
        (
            _block(
                0,
                "asset",
                "complex table",
                asset_id=asset_id,
                asset_type="complex_table",
            ),
        )
    )
    assert str(asset_id) in document.markdown_text
    assert document.nodes[0].asset_id == asset_id
    assert "object_key" not in document.markdown_text


@pytest.mark.parametrize(
    ("bbox", "reason"),
    [
        (None, None),
        ({"left": 1}, "extractor_not_available"),
        (None, "legacy_reason"),
    ],
)
def test_coordinate_matrix_fails_closed(
    bbox: dict[str, object] | None,
    reason: str | None,
) -> None:
    with pytest.raises(MarkdownConversionError):
        _block(0, "paragraph", "body", bbox=bbox, reason=reason)
