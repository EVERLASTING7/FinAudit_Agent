from __future__ import annotations

import io
import zipfile

import pytest
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from app.adapters.ocr import NotConfiguredOcrEngine, OcrError, OcrLine, OcrPage
from app.services.document_parser import DocumentParseError, DocumentParser

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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


def test_docx_preserves_heading_and_paragraph_order() -> None:
    parsed = DocumentParser(
        ocr_engine=NotConfiguredOcrEngine(),
        pdf_renderer=None,
    ).parse(_docx(), mime_type=DOCX_MIME)

    assert parsed.parser_name == "docx-stdlib-xml"
    assert parsed.pages[0].text == "Title\nBody text"
    assert [block.block_type for block in parsed.pages[0].blocks] == ["title", "paragraph"]


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


def test_ocr_port_error_is_redacted_and_classified() -> None:
    error = OcrError("OCR_TIMEOUT", retryable=True)
    assert str(error) == "OCR_TIMEOUT"
    assert error.retryable is True
