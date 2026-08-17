from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.adapters.ocr import (
    OcrError,
    TesseractCliOcrEngine,
    _parse_tesseract_tsv,
)

TSV = (
    b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    b"1\t1\t0\t0\t0\t0\t0\t0\t800\t600\t-1\t\n"
    b"5\t1\t1\t1\t1\t1\t10\t20\t50\t20\t90\tInvoice\n"
    b"5\t1\t1\t1\t1\t2\t65\t20\t40\t20\t80\t123\n"
)


def test_tsv_parser_builds_bounded_lines_and_confidence() -> None:
    page = _parse_tesseract_tsv(TSV, engine_version="5.5.0")
    assert (page.width, page.height) == (800, 600)
    assert page.text == "Invoice 123"
    assert page.confidence == 0.85
    assert page.lines[0].bbox == {"left": 10, "top": 20, "width": 95, "height": 20}


@pytest.mark.parametrize(
    "raw",
    [
        b"wrong\theader\n",
        TSV.replace(b"90", b"101"),
        TSV.replace(b"800", b"+800"),
        b"\xff",
    ],
)
def test_tsv_parser_rejects_malformed_untrusted_output(raw: bytes) -> None:
    with pytest.raises(OcrError, match="OCR_OUTPUT_INVALID"):
        _parse_tesseract_tsv(raw, engine_version="5.5.0")


def test_tesseract_command_is_argument_vector_with_shell_disabled(tmp_path: Path) -> None:
    del tmp_path
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> object:
        observed["command"] = command
        observed.update(kwargs)
        Path(command[2] + ".tsv").write_bytes(TSV)
        return SimpleNamespace(returncode=0)

    engine = TesseractCliOcrEngine(
        executable="C:\\approved\\tesseract.exe",
        languages="chi_sim+eng",
        timeout_seconds=12,
        engine_version="5.5.0",
    )
    with patch("app.adapters.ocr.subprocess.run", side_effect=fake_run):
        page = engine.recognize_image(b"image", mime_type="image/png")

    command = observed["command"]
    assert isinstance(command, list)
    assert command[0] == "C:\\approved\\tesseract.exe"
    assert command[-3:] == ["-l", "chi_sim+eng", "tsv"]
    assert observed["shell"] is False
    assert observed["timeout"] == 12
    assert page.engine_version == "5.5.0"
