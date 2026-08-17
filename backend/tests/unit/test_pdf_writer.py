from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pytest
from pypdf import PdfReader
from pypdf.generic import DictionaryObject, IndirectObject

import app.reports.pdf_writer as pdf_writer_module
from app.reports.pdf_writer import MAX_PDF_BYTES, MAX_PDF_PAGES, report_payload_pdf_bytes
from app.reports.report_payload import (
    RISK_TABLE_COLUMNS,
    RULE_TABLE_COLUMNS,
    ReportMetadata,
    ReportPayload,
    ReportSummary,
    ReportTable,
)

_RISK_ID = UUID(int=101)
_REFERENCE_IDS = (UUID(int=11), UUID(int=12))
_REFERENCE_TEXT = ";".join(str(reference_id) for reference_id in _REFERENCE_IDS)


def _rule_rows(
    *,
    actual: str = "含税金额=100.00",
    expected: str = "预期金额=90.00",
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            f"RULE-{number:03d}",
            "failed" if number == 1 else "passed",
            "hit" if number == 1 else "not_hit",
            actual if number == 1 else None,
            expected if number == 1 else None,
            str(_RISK_ID) if number == 1 else None,
            "high" if number == 1 else None,
            _REFERENCE_TEXT if number == 1 else "",
        )
        for number in range(1, 16)
    )


def _risk_rows(
    *,
    actual: str = "含税金额=100.00",
    expected: str = "预期金额=90.00",
) -> tuple[tuple[object, ...], ...]:
    return (
        (
            str(_RISK_ID),
            "RULE-001",
            "high",
            "high",
            "pending",
            actual,
            expected,
            _REFERENCE_TEXT,
        ),
    )


def _payload(
    *,
    actual: str = "含税金额=100.00",
    expected: str = "预期金额=90.00",
) -> ReportPayload:
    return ReportPayload(
        metadata=ReportMetadata(
            report_version_id=UUID(int=900),
            audit_version_id=UUID(int=800),
            generated_at=datetime(2026, 8, 13, 1, 2, 3, 4, tzinfo=timezone.utc),
            is_outdated=True,
            is_degraded=True,
            degraded_reasons=("AI 已禁用",),
        ),
        preview_id=UUID(int=700),
        ai_status="disabled",
        summary=ReportSummary(
            overall_level="high",
            active_risk_count=1,
            dismissed_risk_count=0,
            has_effective_high=True,
            has_unreviewed_high=True,
        ),
        rules=ReportTable(
            columns=RULE_TABLE_COLUMNS,
            rows=_rule_rows(actual=actual, expected=expected),  # type: ignore[arg-type]
        ),
        risks=ReportTable(
            columns=RISK_TABLE_COLUMNS,
            rows=_risk_rows(actual=actual, expected=expected),  # type: ignore[arg-type]
        ),
    )


def _resolved(value: object) -> object:
    return value.get_object() if isinstance(value, IndirectObject) else value


def _walk(value: object, seen: set[tuple[int, int]] | None = None) -> tuple[object, ...]:
    if seen is None:
        seen = set()
    if isinstance(value, IndirectObject):
        identity = (value.idnum, value.generation)
        if identity in seen:
            return ()
        seen.add(identity)
    resolved = _resolved(value)
    values = [resolved]
    if isinstance(resolved, DictionaryObject):
        for child in resolved.values():
            values.extend(_walk(child, seen))
    elif isinstance(resolved, list):
        for child in resolved:
            values.extend(_walk(child, seen))
    return tuple(values)


def test_pdf_is_byte_stable_extractable_and_preserves_original_text() -> None:
    payload = _payload(actual="'=1+1 中文金额 <script> https://example.invalid")

    first = report_payload_pdf_bytes(payload)
    second = report_payload_pdf_bytes(payload)

    assert first == second
    assert first.startswith(b"%PDF-")
    assert len(first) <= MAX_PDF_BYTES

    reader = PdfReader(BytesIO(first), strict=True)
    assert 1 <= len(reader.pages) <= MAX_PDF_PAGES
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "内部离线预览（非正式审核报告）" in text
    assert "本文件仅用于离线技术验证，不构成正式审核报告或审核结论。" in text
    assert "outdated=true | degraded=true | degraded_reason_count=1" in text
    assert 'degraded_reasons: "AI 已禁用"' in text
    assert "'=1+1 中文金额 <script> https://example.invalid" in text
    assert _REFERENCE_TEXT in text
    assert "reference_ids（ID，未解析）" in text
    assert str(payload.metadata.report_version_id) in text
    for number in range(1, 16):
        assert text.count(f"Rule {number:02d}/15") == 1
        expected_count = 2 if number == 1 else 1
        assert text.count(f'rule_id: "RULE-{number:03d}"') == expected_count
    assert text.count("Risk 01/01") == 1
    assert text.count(_REFERENCE_TEXT) == 2
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text()
        assert page_text.count("内部离线预览（非正式审核报告）") == 1
        assert page_text.count(f"FinAudit report-pdf-writer-v1 | 第 {page_number} 页") == 1
    assert reader.metadata.creation_date == payload.metadata.generated_at.replace(microsecond=0)
    assert reader.metadata.modification_date == payload.metadata.generated_at.replace(microsecond=0)


def test_pdf_escapes_multiline_field_values_as_one_unambiguous_literal() -> None:
    content = report_payload_pdf_bytes(
        _payload(actual="value\nrisk_id: forged\tend\u202ereversed\u2066isolated\u2028line")
    )
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)

    assert (
        'actual_value: "value\\nrisk_id: forged\\tend\\u202ereversed\\u2066isolated\\u2028line"'
        in text
    )
    assert "\nrisk_id: forged" not in text
    assert "\u202e" not in text
    assert "\u2066" not in text
    assert "\u2028" not in text


def test_pdf_uses_only_embedded_truetype_fonts_with_tounicode_and_no_active_objects() -> None:
    reader = PdfReader(BytesIO(report_payload_pdf_bytes(_payload())), strict=True)
    forbidden = {
        "/AA",
        "/AcroForm",
        "/Action",
        "/Annots",
        "/EmbeddedFile",
        "/EmbeddedFiles",
        "/AF",
        "/JavaScript",
        "/JS",
        "/Launch",
        "/Metadata",
        "/Names",
        "/OpenAction",
        "/RichMedia",
        "/URI",
        "/XObject",
    }
    assert not forbidden.intersection(
        key
        for value in _walk(reader.trailer)
        if isinstance(value, DictionaryObject)
        for key in value
    )
    dictionaries = tuple(
        value for value in _walk(reader.trailer) if isinstance(value, DictionaryObject)
    )
    assert all(value.get("/Type") != "/Filespec" for value in dictionaries)
    assert all(value.get("/Subtype") != "/XML" for value in dictionaries)

    for page in reader.pages:
        resources = _resolved(page["/Resources"])
        assert isinstance(resources, DictionaryObject)
        fonts = _resolved(resources["/Font"])
        assert isinstance(fonts, DictionaryObject)
        assert fonts
        for font_reference in fonts.values():
            font = _resolved(font_reference)
            assert isinstance(font, DictionaryObject)
            assert font["/Subtype"] == "/TrueType"
            assert "/ToUnicode" in font
            descriptor = _resolved(font["/FontDescriptor"])
            assert isinstance(descriptor, DictionaryObject)
            assert "/FontFile2" in descriptor


def test_pdf_rejects_exact_payload_mutation_before_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    object.__setattr__(payload.rules, "rows", payload.rules.rows[:-1])
    called = False

    def fail_if_called() -> dict[str, frozenset[int]]:
        nonlocal called
        called = True
        raise AssertionError("fonts must not load before payload validation")

    monkeypatch.setattr(pdf_writer_module, "_register_fonts", fail_if_called)
    with pytest.raises(ValueError, match="exactly 15"):
        report_payload_pdf_bytes(payload)
    assert called is False


@pytest.mark.parametrize("invalid", ("\x00", "\ud800", "\uffff"))
def test_pdf_rejects_invalid_text_and_missing_glyph(invalid: str) -> None:
    with pytest.raises(ValueError, match="invalid XML/PDF"):
        report_payload_pdf_bytes(_payload(actual=f"unsafe{invalid}"))

    with pytest.raises(ValueError, match="unsupported glyph"):
        report_payload_pdf_bytes(_payload(actual="emoji 😀"))


def test_pdf_enforces_font_hash_page_output_and_bounded_multiline_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_files = pdf_writer_module._FONT_FILES
    corrupted = dict(original_files)
    corrupted[pdf_writer_module._MONO_FONT_NAME] = ("DroidSansMono.ttf", "0" * 64)
    monkeypatch.setattr(pdf_writer_module, "_FONT_FILES", corrupted)
    with pytest.raises(RuntimeError, match="font hash mismatch"):
        report_payload_pdf_bytes(_payload())

    monkeypatch.setattr(pdf_writer_module, "_FONT_FILES", original_files)
    monkeypatch.setattr(pdf_writer_module, "MAX_PDF_PAGES", 1)
    with pytest.raises(ValueError, match="page limit"):
        report_payload_pdf_bytes(_payload(actual="界" * 4_096))

    monkeypatch.setattr(pdf_writer_module, "MAX_PDF_PAGES", 128)
    monkeypatch.setattr(pdf_writer_module, "MAX_PDF_BYTES", 1)
    with pytest.raises(ValueError, match="byte limit"):
        report_payload_pdf_bytes(_payload())

    monkeypatch.setattr(pdf_writer_module, "MAX_PDF_BYTES", MAX_PDF_BYTES)
    newline_reason = _payload()
    object.__setattr__(newline_reason.metadata, "degraded_reasons", (("x\n" * 20),))
    content = report_payload_pdf_bytes(newline_reason)
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)
    assert "degraded_reason_count=1" in text
    assert 'degraded_reasons: "x\\nx\\n' in text
    assert len(content) <= MAX_PDF_BYTES


def test_bundled_fonts_and_license_files_are_exact_and_packaged() -> None:
    expected = {
        "DroidSansMono.ttf": (
            108_128,
            "db19a1fdaba41cc4a2fec0330e5c15e71c6dd68a3ef074f4f28268828b45c862",
        ),
        "DroidSansFallback.ttf": (
            3_451_900,
            "21b96a0377f067833a93af3082eb28d4ffab7a8cd46bfd513286f1d64b7b0949",
        ),
        "NOTICE": (
            10_695,
            "38751245389e1e23f73e6f5384b5cbe7fa972cc4410c5adc9c04b082a0b9561a",
        ),
        "README.txt": (
            692,
            "c8b88077052fed912b3f724c0ed230c501cf4e18833af7ca44338d3cd0b093e2",
        ),
    }
    base = pdf_writer_module.resources.files("app.reports").joinpath("assets", "fonts")
    for filename, (size, digest) in expected.items():
        content = base.joinpath(filename).read_bytes()
        assert len(content) == size
        assert sha256(content).hexdigest() == digest
    source = base.joinpath("SOURCE.txt").read_text(encoding="utf-8")
    assert "refs/tags/android-15.0.0_r25" in source
    assert "https://android.googlesource.com/platform/frameworks/base" in source
    for filename in expected:
        assert filename in source
        assert expected[filename][1] in source
