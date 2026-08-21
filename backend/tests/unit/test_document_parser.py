from __future__ import annotations

import io
import warnings
import zipfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

import app.services.document_parser as document_parser_module
from app.adapters.ocr import NotConfiguredOcrEngine, OcrError, OcrLine, OcrPage
from app.services.document_parser import DocumentParseError, DocumentParser

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


class _Ocr:
    def recognize_image(self, payload: bytes, *, mime_type: str) -> OcrPage:
        assert payload
        assert mime_type in {"image/png", "image/jpeg"}
        return OcrPage(
            engine_name="synthetic-ocr",
            engine_version="1.2.3",
            width=800,
            height=600,
            text="发票号码 123",
            confidence=0.91,
            lines=(
                OcrLine(
                    text="发票号码 123",
                    confidence=0.91,
                    bbox={"left": 10, "top": 20, "width": 200, "height": 30},
                ),
            ),
        )


class _Renderer:
    def render_page(self, payload: bytes, *, page_no: int) -> bytes:
        assert payload.startswith(b"%PDF")
        assert page_no == 1
        return b"\x89PNG\r\n\x1a\nsynthetic"


class _PageOcr:
    def __init__(self, page: OcrPage) -> None:
        self._page = page

    def recognize_image(self, payload: bytes, *, mime_type: str) -> OcrPage:
        assert payload
        assert mime_type in {"image/png", "image/jpeg"}
        return self._page


def _text_pdf() -> bytes:
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=(300, 300), invariant=1)
    document.drawString(20, 250, "Contract Number C-001")
    document.drawString(20, 230, "Amount 1000")
    document.save()
    return output.getvalue()


def _blank_pdf() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(output)
    return output.getvalue()


def _docx() -> bytes:
    output = io.BytesIO()
    document = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body>"
        b'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Title</w:t></w:r></w:p>'
        b"<w:p><w:r><w:t>Body text</w:t></w:r></w:p>"
        b"</w:body></w:document>"
    )
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def _docx_with_parts(*documents: bytes) -> bytes:
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for document in documents:
                archive.writestr("word/document.xml", document)
    return output.getvalue()


def _docx_without_main_part() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types />")
    return output.getvalue()


def _patch_docx_headers(
    payload: bytes,
    *,
    encrypted: bool = False,
    compression: int | None = None,
) -> bytes:
    patched = bytearray(payload)
    for signature, flag_offset, compression_offset in (
        (b"PK\x03\x04", 6, 8),
        (b"PK\x01\x02", 8, 10),
    ):
        start = patched.find(signature)
        assert start >= 0
        if encrypted:
            current = int.from_bytes(
                patched[start + flag_offset : start + flag_offset + 2], "little"
            )
            patched[start + flag_offset : start + flag_offset + 2] = (current | 0x1).to_bytes(
                2, "little"
            )
        if compression is not None:
            patched[start + compression_offset : start + compression_offset + 2] = (
                compression.to_bytes(2, "little")
            )
    return bytes(patched)


def test_text_pdf_produces_pages_and_blocks_without_ocr() -> None:
    parsed = DocumentParser(
        ocr_engine=NotConfiguredOcrEngine(),
        pdf_renderer=None,
    ).parse(_text_pdf(), mime_type="application/pdf")

    assert parsed.source_type == "parser"
    assert parsed.parser_name == "pypdf"
    assert parsed.ocr_name is None
    assert len(parsed.pages) == 1
    assert "Contract Number C-001" in parsed.pages[0].text
    assert [block.block_index for block in parsed.pages[0].blocks] == list(
        range(len(parsed.pages[0].blocks))
    )


def test_pdf_uses_default_text_when_layout_extraction_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    def extract_text(**kwargs: object) -> str:
        mode = kwargs.get("extraction_mode")
        assert mode is None or type(mode) is str
        calls.append(mode)
        return "" if mode == "layout" else "Recovered contract body"

    page = SimpleNamespace(
        mediabox=SimpleNamespace(width=300, height=300),
        extract_text=extract_text,
    )
    reader = SimpleNamespace(is_encrypted=False, pages=(page,))
    monkeypatch.setattr(document_parser_module, "PdfReader", lambda *_args, **_kwargs: reader)

    parsed = DocumentParser(ocr_engine=NotConfiguredOcrEngine(), pdf_renderer=None).parse(
        b"%PDF-synthetic",
        mime_type="application/pdf",
    )

    assert parsed.source_type == "parser"
    assert parsed.pages[0].text == "Recovered contract body"
    assert calls == ["layout", None]


@pytest.mark.parametrize("dimension", [float("nan"), float("inf"), 0, -1])
def test_pdf_rejects_non_finite_or_non_positive_page_dimensions(
    monkeypatch: pytest.MonkeyPatch,
    dimension: float,
) -> None:
    page = SimpleNamespace(
        mediabox=SimpleNamespace(width=dimension, height=300),
        extract_text=lambda **_kwargs: "Contract body",
    )
    reader = SimpleNamespace(is_encrypted=False, pages=(page,))
    monkeypatch.setattr(document_parser_module, "PdfReader", lambda *_args, **_kwargs: reader)

    with pytest.raises(DocumentParseError, match="PDF_PARSE_INVALID") as exc_info:
        DocumentParser(ocr_engine=NotConfiguredOcrEngine(), pdf_renderer=None).parse(
            b"%PDF-synthetic",
            mime_type="application/pdf",
        )

    assert exc_info.value.retryable is False


@pytest.mark.parametrize("text", ["invalid\x00text", "invalid" + chr(0xD800)])
def test_pdf_rejects_text_that_cannot_be_persisted_as_utf8(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
) -> None:
    page = SimpleNamespace(
        mediabox=SimpleNamespace(width=300, height=300),
        extract_text=lambda **_kwargs: text,
    )
    reader = SimpleNamespace(is_encrypted=False, pages=(page,))
    monkeypatch.setattr(document_parser_module, "PdfReader", lambda *_args, **_kwargs: reader)

    with pytest.raises(DocumentParseError, match="PDF_PARSE_INVALID") as exc_info:
        DocumentParser(ocr_engine=NotConfiguredOcrEngine(), pdf_renderer=None).parse(
            b"%PDF-synthetic",
            mime_type="application/pdf",
        )

    assert exc_info.value.retryable is False


def test_docx_preserves_heading_and_paragraph_order() -> None:
    parsed = DocumentParser(
        ocr_engine=NotConfiguredOcrEngine(),
        pdf_renderer=None,
    ).parse(_docx(), mime_type=DOCX_MIME)

    assert parsed.parser_name == "docx-stdlib-xml"
    assert parsed.pages[0].text == "Title\nBody text"
    assert [block.block_type for block in parsed.pages[0].blocks] == ["title", "paragraph"]


def test_docx_rejects_non_document_root_and_duplicate_main_parts() -> None:
    namespace = b'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    fake_root = b"<root " + namespace + b"><w:p><w:r><w:t>Text</w:t></w:r></w:p></root>"
    valid_root = (
        b"<w:document "
        + namespace
        + b"><w:body><w:p><w:r><w:t>Text</w:t></w:r></w:p></w:body></w:document>"
    )
    parser = DocumentParser(ocr_engine=NotConfiguredOcrEngine(), pdf_renderer=None)

    with pytest.raises(DocumentParseError, match="DOCX_PARSE_INVALID"):
        parser.parse(_docx_with_parts(fake_root), mime_type=DOCX_MIME)
    with pytest.raises(DocumentParseError, match="DOCX_PARSE_INVALID"):
        parser.parse(_docx_with_parts(valid_root, valid_root), mime_type=DOCX_MIME)


@pytest.mark.parametrize(
    "payload",
    [
        b"PK\x03\x04truncated",
        _docx_without_main_part(),
        _docx_with_parts(b"<w:document"),
        _patch_docx_headers(_docx(), encrypted=True),
        _patch_docx_headers(_docx(), compression=99),
        _docx_with_parts(
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b"<w:body><w:p><w:r><w:t>"
            + b"A" * 200_000
            + b"</w:t></w:r></w:p></w:body></w:document>"
        ),
    ],
    ids=(
        "truncated-zip",
        "missing-main-part",
        "malformed-xml",
        "encrypted-main-part",
        "unsupported-compression",
        "compression-ratio-limit",
    ),
)
def test_malformed_docx_archive_variants_fail_closed(payload: bytes) -> None:
    with pytest.raises(DocumentParseError, match="DOCX_PARSE_INVALID") as exc_info:
        DocumentParser(ocr_engine=NotConfiguredOcrEngine(), pdf_renderer=None).parse(
            payload,
            mime_type=DOCX_MIME,
        )

    assert exc_info.value.retryable is False


def test_image_ocr_captures_engine_bbox_and_confidence() -> None:
    parsed = DocumentParser(ocr_engine=_Ocr(), pdf_renderer=None).parse(
        b"synthetic-image",
        mime_type="image/png",
    )

    assert parsed.source_type == "ocr"
    assert (parsed.ocr_name, parsed.ocr_version) == ("synthetic-ocr", "1.2.3")
    assert parsed.pages[0].blocks[0].bbox == {
        "left": 10,
        "top": 20,
        "width": 200,
        "height": 30,
    }
    assert str(parsed.average_confidence) == "0.91000"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda page: replace(page, confidence=float("nan")),
        lambda page: replace(
            page,
            lines=(replace(page.lines[0], confidence=float("inf")),),
        ),
        lambda page: replace(page, width=0),
        lambda page: replace(page, engine_name=" "),
        lambda page: replace(
            page,
            lines=(replace(page.lines[0], text=" "),),
        ),
        lambda page: replace(
            page,
            lines=(
                replace(
                    page.lines[0],
                    bbox={"left": -1, "top": 20, "width": 200, "height": 30},
                ),
            ),
        ),
        lambda page: replace(
            page,
            lines=(
                replace(
                    page.lines[0],
                    bbox={"left": 700, "top": 20, "width": 200, "height": 30},
                ),
            ),
        ),
    ],
    ids=(
        "nan-page-confidence",
        "infinite-line-confidence",
        "zero-width",
        "blank-engine-name",
        "blank-line-text",
        "negative-bbox",
        "bbox-outside-page",
    ),
)
def test_untrusted_ocr_page_structure_fails_closed(
    mutate: Callable[[OcrPage], OcrPage],
) -> None:
    page = _Ocr().recognize_image(b"image", mime_type="image/png")
    invalid = mutate(page)
    parser = DocumentParser(ocr_engine=_PageOcr(invalid), pdf_renderer=_Renderer())

    with pytest.raises(DocumentParseError, match="OCR_OUTPUT_INVALID") as image_error:
        parser.parse(b"image", mime_type="image/png")
    with pytest.raises(DocumentParseError, match="OCR_OUTPUT_INVALID") as pdf_error:
        parser.parse(_blank_pdf(), mime_type="application/pdf")

    assert image_error.value.retryable is False
    assert pdf_error.value.retryable is False


def test_blank_pdf_requires_both_renderer_and_real_ocr() -> None:
    with pytest.raises(DocumentParseError, match="PDF_OCR_RENDERER_NOT_CONFIGURED"):
        DocumentParser(
            ocr_engine=NotConfiguredOcrEngine(),
            pdf_renderer=None,
        ).parse(_blank_pdf(), mime_type="application/pdf")

    with pytest.raises(DocumentParseError, match="OCR_NOT_CONFIGURED"):
        DocumentParser(
            ocr_engine=NotConfiguredOcrEngine(),
            pdf_renderer=_Renderer(),
        ).parse(_blank_pdf(), mime_type="application/pdf")


def test_invalid_or_unsupported_document_never_produces_success() -> None:
    parser = DocumentParser(ocr_engine=_Ocr(), pdf_renderer=_Renderer())
    with pytest.raises(DocumentParseError, match="PDF_PARSE_INVALID"):
        parser.parse(b"%PDF-broken", mime_type="application/pdf")
    with pytest.raises(DocumentParseError, match="PARSE_FORMAT_UNSUPPORTED"):
        parser.parse(b"payload", mime_type="application/octet-stream")


@pytest.mark.parametrize("fixture_name", ["pdf-damaged.pdf", "pdf-encrypted.pdf"])
def test_catalogued_malformed_pdf_fixtures_fail_closed(fixture_name: str) -> None:
    with pytest.raises(DocumentParseError, match="PDF_PARSE_INVALID") as exc_info:
        DocumentParser(ocr_engine=_Ocr(), pdf_renderer=_Renderer()).parse(
            (FIXTURES / fixture_name).read_bytes(),
            mime_type="application/pdf",
        )

    assert exc_info.value.retryable is False


def test_ocr_port_error_is_redacted_and_classified() -> None:
    error = OcrError("OCR_TIMEOUT", retryable=True)
    assert str(error) == "OCR_TIMEOUT"
    assert error.retryable is True
