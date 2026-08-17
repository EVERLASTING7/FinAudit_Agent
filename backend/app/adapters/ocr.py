"""可替换 OCR Port 与无 shell 的 Tesseract/Poppler 本地 Adapter。"""

from __future__ import annotations

import csv
import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from app.core.config import Settings

_MAX_TSV_BYTES = 20 * 1024 * 1024
_MAX_RENDERED_PAGE_BYTES = 50 * 1024 * 1024
_SUPPORTED_IMAGE_MIME = {"image/jpeg": ".jpg", "image/png": ".png"}
_TSV_COLUMNS = (
    "level",
    "page_num",
    "block_num",
    "par_num",
    "line_num",
    "word_num",
    "left",
    "top",
    "width",
    "height",
    "conf",
    "text",
)


class OcrError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class OcrLine:
    text: str
    confidence: float
    bbox: dict[str, int]


@dataclass(frozen=True, slots=True)
class OcrPage:
    engine_name: str
    engine_version: str
    width: int
    height: int
    text: str
    confidence: float | None
    lines: tuple[OcrLine, ...]


class OcrEngine(Protocol):
    def recognize_image(self, payload: bytes, *, mime_type: str) -> OcrPage: ...


class PdfPageRenderer(Protocol):
    def render_page(self, payload: bytes, *, page_no: int) -> bytes: ...


class NotConfiguredOcrEngine:
    def recognize_image(self, payload: bytes, *, mime_type: str) -> OcrPage:
        del payload, mime_type
        raise OcrError("OCR_NOT_CONFIGURED", retryable=False)


def _safe_environment() -> dict[str, str]:
    allowed = ("PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "TESSDATA_PREFIX")
    return {name: os.environ[name] for name in allowed if name in os.environ}


def _run(command: list[str], *, cwd: Path, timeout: float) -> None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=_safe_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        raise OcrError("OCR_TIMEOUT", retryable=True) from None
    except OSError:
        raise OcrError("OCR_DEPENDENCY_UNAVAILABLE", retryable=True) from None
    if result.returncode != 0:
        raise OcrError("OCR_EXECUTION_FAILED", retryable=True)


class TesseractCliOcrEngine:
    """Tesseract TSV 边界：固定文件名、有界输出、严格数字和列验证。"""

    def __init__(
        self,
        *,
        executable: str,
        languages: str,
        timeout_seconds: float,
        engine_version: str,
    ) -> None:
        if not executable or not languages or not engine_version:
            raise ValueError("complete tesseract profile is required")
        self._executable = executable
        self._languages = languages
        self._timeout = timeout_seconds
        self._version = engine_version

    def recognize_image(self, payload: bytes, *, mime_type: str) -> OcrPage:
        extension = _SUPPORTED_IMAGE_MIME.get(mime_type)
        if extension is None or type(payload) is not bytes or not payload:
            raise OcrError("OCR_INPUT_UNSUPPORTED", retryable=False)
        with TemporaryDirectory(prefix="finaudit-ocr-") as directory:
            workdir = Path(directory)
            input_path = workdir / f"input{extension}"
            output_base = workdir / "result"
            input_path.write_bytes(payload)
            _run(
                [
                    self._executable,
                    str(input_path),
                    str(output_base),
                    "-l",
                    self._languages,
                    "tsv",
                ],
                cwd=workdir,
                timeout=self._timeout,
            )
            output_path = workdir / "result.tsv"
            try:
                size = output_path.stat().st_size
                if size <= 0 or size > _MAX_TSV_BYTES:
                    raise ValueError
                raw = output_path.read_bytes()
            except (OSError, ValueError):
                raise OcrError("OCR_OUTPUT_INVALID", retryable=False) from None
        return _parse_tesseract_tsv(raw, engine_version=self._version)


class PdftoppmRenderer:
    def __init__(self, *, executable: str, timeout_seconds: float) -> None:
        if not executable:
            raise ValueError("pdftoppm executable is required")
        self._executable = executable
        self._timeout = timeout_seconds

    def render_page(self, payload: bytes, *, page_no: int) -> bytes:
        if type(payload) is not bytes or not payload or type(page_no) is not int or page_no < 1:
            raise OcrError("OCR_INPUT_UNSUPPORTED", retryable=False)
        with TemporaryDirectory(prefix="finaudit-pdf-render-") as directory:
            workdir = Path(directory)
            input_path = workdir / "input.pdf"
            output_base = workdir / "page"
            input_path.write_bytes(payload)
            _run(
                [
                    self._executable,
                    "-f",
                    str(page_no),
                    "-l",
                    str(page_no),
                    "-singlefile",
                    "-r",
                    "200",
                    "-png",
                    str(input_path),
                    str(output_base),
                ],
                cwd=workdir,
                timeout=self._timeout,
            )
            output_path = workdir / "page.png"
            try:
                size = output_path.stat().st_size
                if size <= 0 or size > _MAX_RENDERED_PAGE_BYTES:
                    raise ValueError
                return output_path.read_bytes()
            except (OSError, ValueError):
                raise OcrError("OCR_RENDER_INVALID", retryable=False) from None


def _parse_int(value: str, *, minimum: int = 0) -> int:
    if not value or value.startswith("+") or not value.isascii() or not value.isdigit():
        raise ValueError
    parsed = int(value)
    if parsed < minimum or parsed > 1_000_000_000:
        raise ValueError
    return parsed


def _parse_confidence(value: str) -> float:
    parsed = float(value)
    if not value or parsed < -1 or parsed > 100 or not parsed.is_integer():
        raise ValueError
    return parsed


def _parse_tesseract_tsv(raw: bytes, *, engine_version: str) -> OcrPage:
    try:
        text = raw.decode("utf-8", errors="strict")
        reader = csv.DictReader(text.splitlines(), delimiter="\t")
        if tuple(reader.fieldnames or ()) != _TSV_COLUMNS:
            raise ValueError
        width = height = 0
        grouped: dict[tuple[int, int, int], list[tuple[str, float, int, int, int, int]]] = (
            defaultdict(list)
        )
        for row in reader:
            if None in row or any(row[column] is None for column in _TSV_COLUMNS):
                raise ValueError
            level = _parse_int(row["level"], minimum=1)
            left = _parse_int(row["left"])
            top = _parse_int(row["top"])
            word_width = _parse_int(row["width"])
            word_height = _parse_int(row["height"])
            confidence = _parse_confidence(row["conf"])
            if level == 1:
                width, height = word_width, word_height
            if level != 5:
                continue
            word = row["text"].strip()
            if not word or confidence < 0:
                continue
            key = (
                _parse_int(row["block_num"]),
                _parse_int(row["par_num"]),
                _parse_int(row["line_num"]),
            )
            grouped[key].append((word, confidence, left, top, word_width, word_height))
        if width <= 0 or height <= 0:
            raise ValueError
    except (KeyError, TypeError, UnicodeDecodeError, ValueError):
        raise OcrError("OCR_OUTPUT_INVALID", retryable=False) from None

    lines: list[OcrLine] = []
    all_confidences: list[float] = []
    for key in sorted(grouped):
        words = grouped[key]
        left = min(word[2] for word in words)
        top = min(word[3] for word in words)
        right = max(word[2] + word[4] for word in words)
        bottom = max(word[3] + word[5] for word in words)
        confidences = [word[1] for word in words]
        all_confidences.extend(confidences)
        lines.append(
            OcrLine(
                text=" ".join(word[0] for word in words),
                confidence=sum(confidences) / len(confidences) / 100,
                bbox={"left": left, "top": top, "width": right - left, "height": bottom - top},
            )
        )
    page_text = "\n".join(line.text for line in lines)
    page_confidence = (
        None if not all_confidences else sum(all_confidences) / len(all_confidences) / 100
    )
    return OcrPage(
        engine_name="tesseract",
        engine_version=engine_version,
        width=width,
        height=height,
        text=page_text,
        confidence=page_confidence,
        lines=tuple(lines),
    )


def create_ocr_engine(settings: Settings) -> OcrEngine:
    if settings.ocr_provider != "tesseract_cli":
        return NotConfiguredOcrEngine()
    executable = settings.ocr_tesseract_executable
    engine_version = settings.ocr_tesseract_version
    if executable is None or engine_version is None:
        raise ValueError("validated tesseract profile is incomplete")
    return TesseractCliOcrEngine(
        executable=executable,
        languages=settings.ocr_languages,
        timeout_seconds=settings.ocr_request_timeout_seconds,
        engine_version=engine_version,
    )


def create_pdf_renderer(settings: Settings) -> PdfPageRenderer | None:
    executable = settings.ocr_pdftoppm_executable
    if executable is None:
        return None
    return PdftoppmRenderer(
        executable=executable,
        timeout_seconds=settings.ocr_request_timeout_seconds,
    )


__all__ = [
    "NotConfiguredOcrEngine",
    "OcrEngine",
    "OcrError",
    "OcrLine",
    "OcrPage",
    "PdfPageRenderer",
    "PdftoppmRenderer",
    "TesseractCliOcrEngine",
    "create_ocr_engine",
    "create_pdf_renderer",
]
