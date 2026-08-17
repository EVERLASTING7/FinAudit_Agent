"""受限 PDF/DOCX/图片解析，输出不可变页与块候选。"""

from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ElementTree
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import pypdf
from pypdf import PdfReader

from app.adapters.ocr import OcrEngine, OcrError, PdfPageRenderer

_DOCX_DOCUMENT_PART = "word/document.xml"
_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MAX_PAGES = 2000
_MAX_TEXT_CHARS = 20_000_000
_MAX_DOCX_XML_BYTES = 32 * 1024 * 1024


class DocumentParseError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    block_index: int
    page_no: int
    block_type: Literal["title", "paragraph", "list", "table", "quote", "other"]
    text: str
    bbox: dict[str, int] | None
    confidence: Decimal | None


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page_no: int
    width: Decimal | None
    height: Decimal | None
    unit: Literal["pixel", "point", "unknown"]
    text: str
    confidence: Decimal | None
    blocks: tuple[ParsedBlock, ...]


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source_type: Literal["parser", "ocr"]
    parser_name: str
    parser_version: str
    ocr_name: str | None
    ocr_version: str | None
    pages: tuple[ParsedPage, ...]

    @property
    def raw_text(self) -> str:
        return "\n\f\n".join(page.text for page in self.pages)

    @property
    def raw_text_sha256(self) -> str:
        return hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()

    @property
    def average_confidence(self) -> Decimal | None:
        values = [page.confidence for page in self.pages if page.confidence is not None]
        return None if not values else sum(values, Decimal(0)) / len(values)


class DocumentParser:
    def __init__(
        self,
        *,
        ocr_engine: OcrEngine,
        pdf_renderer: PdfPageRenderer | None,
    ) -> None:
        self._ocr = ocr_engine
        self._pdf_renderer = pdf_renderer

    def parse(self, payload: bytes, *, mime_type: str) -> ParsedDocument:
        if type(payload) is not bytes or not payload:
            raise DocumentParseError("PARSE_INPUT_INVALID", retryable=False)
        if mime_type == "application/pdf":
            return self._parse_pdf(payload)
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return self._parse_docx(payload)
        if mime_type in {"image/png", "image/jpeg"}:
            return self._parse_image(payload, mime_type=mime_type)
        raise DocumentParseError("PARSE_FORMAT_UNSUPPORTED", retryable=False)

    def _parse_pdf(self, payload: bytes) -> ParsedDocument:
        try:
            reader = PdfReader(io.BytesIO(payload), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= _MAX_PAGES:
                raise ValueError
        except Exception:
            raise DocumentParseError("PDF_PARSE_INVALID", retryable=False) from None

        pages: list[ParsedPage] = []
        used_ocr = False
        ocr_identity: tuple[str, str] | None = None
        block_index = 0
        total_chars = 0
        for page_no, page in enumerate(reader.pages, start=1):
            try:
                width = Decimal(str(float(page.mediabox.width)))
                height = Decimal(str(float(page.mediabox.height)))
            except Exception:
                raise DocumentParseError("PDF_PARSE_INVALID", retryable=False) from None
            try:
                text = (page.extract_text(extraction_mode="layout") or "").strip()
            except KeyError as error:
                if error.args != ("/Contents",):
                    raise DocumentParseError("PDF_PARSE_INVALID", retryable=False) from None
                text = ""
            except Exception:
                raise DocumentParseError("PDF_PARSE_INVALID", retryable=False) from None
            if text:
                page_blocks, block_index = _text_blocks(
                    text,
                    page_no=page_no,
                    block_index=block_index,
                )
                parsed_page = ParsedPage(
                    page_no=page_no,
                    width=width,
                    height=height,
                    unit="point",
                    text=text,
                    confidence=None,
                    blocks=page_blocks,
                )
            else:
                if self._pdf_renderer is None:
                    raise DocumentParseError("PDF_OCR_RENDERER_NOT_CONFIGURED", retryable=False)
                try:
                    rendered = self._pdf_renderer.render_page(payload, page_no=page_no)
                    recognized = self._ocr.recognize_image(rendered, mime_type="image/png")
                except OcrError as error:
                    raise DocumentParseError(error.code, retryable=error.retryable) from None
                used_ocr = True
                if not recognized.text:
                    raise DocumentParseError("OCR_TEXT_EMPTY", retryable=False)
                current_ocr_identity = (recognized.engine_name, recognized.engine_version)
                if ocr_identity is not None and current_ocr_identity != ocr_identity:
                    raise DocumentParseError("OCR_IDENTITY_CHANGED", retryable=False)
                ocr_identity = current_ocr_identity
                recognized_blocks: list[ParsedBlock] = []
                for line in recognized.lines:
                    recognized_blocks.append(
                        ParsedBlock(
                            block_index=block_index,
                            page_no=page_no,
                            block_type="paragraph",
                            text=line.text,
                            bbox=line.bbox,
                            confidence=_confidence(line.confidence),
                        )
                    )
                    block_index += 1
                parsed_page = ParsedPage(
                    page_no=page_no,
                    width=Decimal(recognized.width),
                    height=Decimal(recognized.height),
                    unit="pixel",
                    text=recognized.text,
                    confidence=_confidence(recognized.confidence),
                    blocks=tuple(recognized_blocks),
                )
            total_chars += len(parsed_page.text)
            if total_chars > _MAX_TEXT_CHARS:
                raise DocumentParseError("PARSE_TEXT_LIMIT_EXCEEDED", retryable=False)
            pages.append(parsed_page)
        return ParsedDocument(
            source_type="ocr" if used_ocr else "parser",
            parser_name="pypdf",
            parser_version=pypdf.__version__,
            ocr_name=(None if ocr_identity is None else ocr_identity[0]),
            ocr_version=(None if ocr_identity is None else ocr_identity[1]),
            pages=tuple(pages),
        )

    def _parse_docx(self, payload: bytes) -> ParsedDocument:
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                info = archive.getinfo(_DOCX_DOCUMENT_PART)
                if (
                    info.file_size <= 0
                    or info.file_size > _MAX_DOCX_XML_BYTES
                    or info.compress_size <= 0
                    or info.file_size > info.compress_size * 100
                ):
                    raise ValueError
                raw_xml = archive.read(info)
            root = ElementTree.fromstring(raw_xml)
        except (ElementTree.ParseError, KeyError, OSError, ValueError, zipfile.BadZipFile):
            raise DocumentParseError("DOCX_PARSE_INVALID", retryable=False) from None

        paragraphs: list[tuple[str, str]] = []
        for paragraph in root.iter(f"{{{_WORD_NAMESPACE}}}p"):
            text = "".join(
                node.text or "" for node in paragraph.iter(f"{{{_WORD_NAMESPACE}}}t")
            ).strip()
            if not text:
                continue
            style = paragraph.find(f"{{{_WORD_NAMESPACE}}}pPr/{{{_WORD_NAMESPACE}}}pStyle")
            style_value = None if style is None else style.get(f"{{{_WORD_NAMESPACE}}}val")
            block_type = (
                "title"
                if style_value and style_value.lower().startswith("heading")
                else "paragraph"
            )
            paragraphs.append((block_type, text))
        full_text = "\n".join(text for _, text in paragraphs)
        if not full_text or len(full_text) > _MAX_TEXT_CHARS:
            raise DocumentParseError("DOCX_TEXT_EMPTY_OR_TOO_LARGE", retryable=False)
        blocks = tuple(
            ParsedBlock(
                block_index=index,
                page_no=1,
                block_type=block_type,  # type: ignore[arg-type]
                text=text,
                bbox=None,
                confidence=None,
            )
            for index, (block_type, text) in enumerate(paragraphs)
        )
        return ParsedDocument(
            source_type="parser",
            parser_name="docx-stdlib-xml",
            parser_version="1",
            ocr_name=None,
            ocr_version=None,
            pages=(
                ParsedPage(
                    page_no=1,
                    width=None,
                    height=None,
                    unit="unknown",
                    text=full_text,
                    confidence=None,
                    blocks=blocks,
                ),
            ),
        )

    def _parse_image(self, payload: bytes, *, mime_type: str) -> ParsedDocument:
        try:
            recognized = self._ocr.recognize_image(payload, mime_type=mime_type)
        except OcrError as error:
            raise DocumentParseError(error.code, retryable=error.retryable) from None
        blocks = tuple(
            ParsedBlock(
                block_index=index,
                page_no=1,
                block_type="paragraph",
                text=line.text,
                bbox=line.bbox,
                confidence=_confidence(line.confidence),
            )
            for index, line in enumerate(recognized.lines)
        )
        if not recognized.text:
            raise DocumentParseError("OCR_TEXT_EMPTY", retryable=False)
        return ParsedDocument(
            source_type="ocr",
            parser_name="image-ocr-adapter",
            parser_version="1",
            ocr_name=recognized.engine_name,
            ocr_version=recognized.engine_version,
            pages=(
                ParsedPage(
                    page_no=1,
                    width=Decimal(recognized.width),
                    height=Decimal(recognized.height),
                    unit="pixel",
                    text=recognized.text,
                    confidence=_confidence(recognized.confidence),
                    blocks=blocks,
                ),
            ),
        )


def _confidence(value: float | None) -> Decimal | None:
    if value is None:
        return None
    if value < 0 or value > 1:
        raise DocumentParseError("OCR_OUTPUT_INVALID", retryable=False)
    return Decimal(str(value)).quantize(Decimal("0.00001"))


def _text_blocks(
    text: str,
    *,
    page_no: int,
    block_index: int,
) -> tuple[tuple[ParsedBlock, ...], int]:
    blocks: list[ParsedBlock] = []
    for paragraph in (part.strip() for part in text.splitlines()):
        if not paragraph:
            continue
        blocks.append(
            ParsedBlock(
                block_index=block_index,
                page_no=page_no,
                block_type="paragraph",
                text=paragraph,
                bbox=None,
                confidence=None,
            )
        )
        block_index += 1
    if not blocks:
        raise DocumentParseError("PARSE_TEXT_EMPTY", retryable=False)
    return tuple(blocks), block_index


__all__ = [
    "DocumentParseError",
    "DocumentParser",
    "ParsedBlock",
    "ParsedDocument",
    "ParsedPage",
]
