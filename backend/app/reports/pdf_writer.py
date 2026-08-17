"""从冻结报告负载生成有界、无主动内容的中文 PDF 字节。"""

from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from importlib import resources
from io import BytesIO
from threading import Lock
from typing import Protocol
from unicodedata import category

from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfbase.ttfonts import TTFError, TTFont  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

from app.ai.report_draft import FrozenReportFacts, ReportDraftOutput, validate_report_draft
from app.reports.artifact_payload import (
    validate_formal_report_payload,
    validate_report_payload,
)
from app.reports.formal_payload import FormalReportContext
from app.reports.report_payload import ReportCellInput, ReportPayload

MAX_PDF_PAGES = 128
MAX_PDF_BYTES = 8 * 1024 * 1024

_MONO_FONT_NAME = "FinAuditDroidSansMono"
_FALLBACK_FONT_NAME = "FinAuditDroidSansFallback"
_FONT_FILES = {
    _MONO_FONT_NAME: (
        "DroidSansMono.ttf",
        "db19a1fdaba41cc4a2fec0330e5c15e71c6dd68a3ef074f4f28268828b45c862",
    ),
    _FALLBACK_FONT_NAME: (
        "DroidSansFallback.ttf",
        "21b96a0377f067833a93af3082eb28d4ffab7a8cd46bfd513286f1d64b7b0949",
    ),
}

_PAGE_WIDTH, _PAGE_HEIGHT = A4
_MARGIN = 36.0
_BODY_TOP = _PAGE_HEIGHT - 64.0
_BODY_BOTTOM = 32.0
_BODY_FONT_SIZE = 8.2
_BODY_LEADING = 10.6
_PDF_LOCK = Lock()


class _TextObject(Protocol):
    def setFont(self, font_name: str, font_size: float) -> None: ...

    def textOut(self, text: str) -> None: ...


def _font_bytes(filename: str, expected_sha256: str) -> bytes:
    resource = resources.files("app.reports").joinpath("assets/fonts").joinpath(filename)
    try:
        content = resource.read_bytes()
    except (FileNotFoundError, OSError) as exc:
        raise RuntimeError("bundled PDF font is unavailable") from exc
    if sha256(content).hexdigest() != expected_sha256:
        raise RuntimeError("bundled PDF font hash mismatch")
    return content


def _register_fonts() -> dict[str, frozenset[int]]:
    glyphs: dict[str, frozenset[int]] = {}
    for font_name, (filename, expected_sha256) in _FONT_FILES.items():
        try:
            font = TTFont(
                font_name,
                BytesIO(_font_bytes(filename, expected_sha256)),
                validate=1,
            )
        except (KeyError, OSError, TTFError, TypeError, ValueError) as exc:
            raise RuntimeError("bundled PDF font is invalid") from exc
        pdfmetrics.registerFont(font)
        glyphs[font_name] = frozenset(font.face.charToGlyph)
    return glyphs


def _display_cell(value: ReportCellInput) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        serialized = json.dumps(value, ensure_ascii=False)
        visible: list[str] = []
        for character in serialized:
            if category(character) in {"Cc", "Cf", "Zl", "Zp"}:
                codepoint = ord(character)
                visible.append(
                    f"\\u{codepoint:04x}" if codepoint <= 0xFFFF else f"\\U{codepoint:08x}"
                )
            else:
                visible.append(character)
        return "".join(visible)
    if type(value) is Decimal and value.is_finite():
        return str(value)
    raise ValueError("PDF cells must be exact str, int, bool, or None")


class _PdfRenderer:
    def __init__(
        self,
        payload: ReportPayload,
        joined_degraded_reasons: str,
        glyphs: dict[str, frozenset[int]],
        formal_context: FormalReportContext | None = None,
        report_draft: ReportDraftOutput | None = None,
    ) -> None:
        self.payload = payload
        self.joined_degraded_reasons = joined_degraded_reasons
        self.glyphs = glyphs
        self.formal_context = formal_context
        self.report_draft = report_draft
        self.output = BytesIO()
        self.pdf = canvas.Canvas(
            self.output,
            pagesize=A4,
            pageCompression=1,
            invariant=1,
            initialFontName=_MONO_FONT_NAME,
            initialFontSize=_BODY_FONT_SIZE,
            initialLeading=_BODY_LEADING,
        )
        self.pdf.setTitle(
            "FinAudit formal audit report"
            if formal_context is not None
            else "FinAudit internal offline preview"
        )
        self.pdf.setAuthor("FinAudit Agent")
        self.pdf.setSubject(
            "Frozen completed audit execution report"
            if formal_context is not None
            else "Frozen ReportPayload; not a formal audit report"
        )
        self.pdf.setCreator(
            "FinAudit Agent formal-report-pdf-writer-v1"
            if formal_context is not None
            else "FinAudit Agent report-pdf-writer-v1"
        )
        generated_at = payload.metadata.generated_at
        pdf_date = generated_at.strftime("D:%Y%m%d%H%M%S+00'00'")
        self.pdf.setDateFormatter(lambda _year, _month, _day, _hour, _minute, _second: pdf_date)
        self.page_number = 0
        self.y = _BODY_TOP
        self.width_cache: dict[tuple[str, float, str], float] = {}
        self._new_page()

    def _font_for_character(self, character: str) -> str:
        codepoint = ord(character)
        if codepoint in self.glyphs[_MONO_FONT_NAME]:
            return _MONO_FONT_NAME
        if codepoint in self.glyphs[_FALLBACK_FONT_NAME]:
            return _FALLBACK_FONT_NAME
        raise ValueError(f"PDF text contains an unsupported glyph: U+{codepoint:04X}")

    def _character_width(self, character: str, font_size: float) -> float:
        font_name = self._font_for_character(character)
        key = (font_name, font_size, character)
        width = self.width_cache.get(key)
        if width is None:
            width = float(pdfmetrics.stringWidth(character, font_name, font_size))
            self.width_cache[key] = width
        return width

    def _runs(self, text: str) -> tuple[tuple[str, str], ...]:
        runs: list[tuple[str, str]] = []
        for character in text:
            font_name = self._font_for_character(character)
            if runs and runs[-1][0] == font_name:
                previous_font, previous_text = runs[-1]
                runs[-1] = (previous_font, previous_text + character)
            else:
                runs.append((font_name, character))
        return tuple(runs)

    def _draw_line(self, text: str, *, x: float, y: float, font_size: float) -> None:
        if not text:
            return
        text_object: _TextObject = self.pdf.beginText(x, y)
        for font_name, run in self._runs(text):
            text_object.setFont(font_name, font_size)
            text_object.textOut(run)
        self.pdf.drawText(text_object)

    def _draw_page_header(self) -> float:
        self._draw_line(
            (
                "FinAudit 正式审核报告"
                if self.formal_context is not None
                else "内部离线预览（非正式审核报告）"
            ),
            x=_MARGIN,
            y=_PAGE_HEIGHT - 28.0,
            font_size=10.0,
        )
        status = (
            f"outdated={str(self.payload.metadata.is_outdated).lower()} | "
            f"degraded={str(self.payload.metadata.is_degraded).lower()} | "
            f"degraded_reason_count={len(self.payload.metadata.degraded_reasons)} | "
            f"ai_status={self.payload.ai_status} | reference_ids=未解析 ID"
        )
        y = _PAGE_HEIGHT - 42.0
        for line in self._wrapped_lines(
            status,
            width=_PAGE_WIDTH - 2 * _MARGIN,
            font_size=7.2,
        ):
            self._draw_line(line, x=_MARGIN, y=y, font_size=7.2)
            y -= 9.0
        self.pdf.line(_MARGIN, y + 2.0, _PAGE_WIDTH - _MARGIN, y + 2.0)
        return float(y - 8.0)

    def _draw_page_footer(self) -> None:
        self.pdf.line(_MARGIN, 26.0, _PAGE_WIDTH - _MARGIN, 26.0)
        self._draw_line(
            (
                "FinAudit formal-report-pdf-writer-v1"
                if self.formal_context is not None
                else "FinAudit report-pdf-writer-v1"
            )
            + f" | 第 {self.page_number} 页",
            x=_MARGIN,
            y=15.0,
            font_size=7.0,
        )

    def _new_page(self) -> None:
        if self.page_number >= MAX_PDF_PAGES:
            raise ValueError("PDF output exceeds the page limit")
        if self.page_number:
            self._draw_page_footer()
            self.pdf.showPage()
        self.page_number += 1
        self.y = self._draw_page_header()

    def _ensure_lines(self, count: int, leading: float = _BODY_LEADING) -> None:
        if self.y - count * leading < _BODY_BOTTOM:
            self._new_page()

    def _wrapped_lines(self, text: str, *, width: float, font_size: float) -> tuple[str, ...]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
        wrapped: list[str] = []
        for source_line in normalized.split("\n"):
            if not source_line:
                wrapped.append("")
                continue
            current: list[str] = []
            current_width = 0.0
            for character in source_line:
                character_width = self._character_width(character, font_size)
                if current and current_width + character_width > width:
                    wrapped.append("".join(current))
                    current = []
                    current_width = 0.0
                if character_width > width:
                    raise ValueError("PDF glyph exceeds the fixed line width")
                current.append(character)
                current_width += character_width
            wrapped.append("".join(current))
        return tuple(wrapped)

    def write_text(
        self,
        text: str,
        *,
        indent: float = 0.0,
        font_size: float = _BODY_FONT_SIZE,
        leading: float = _BODY_LEADING,
    ) -> None:
        width = _PAGE_WIDTH - 2 * _MARGIN - indent
        for line in self._wrapped_lines(text, width=width, font_size=font_size):
            self._ensure_lines(1, leading)
            self._draw_line(line, x=_MARGIN + indent, y=self.y, font_size=font_size)
            self.y -= leading

    def write_section(self, title: str) -> None:
        self._ensure_lines(2, 13.0)
        self.y -= 3.0
        self.write_text(title, font_size=11.0, leading=14.0)

    def write_field(self, name: str, value: ReportCellInput, *, indent: float = 10.0) -> None:
        label = f"{name}（ID，未解析）" if name == "reference_ids" else name
        self.write_text(f"{label}: {_display_cell(value)}", indent=indent)

    def render(self) -> bytes:
        metadata = self.payload.metadata
        generated_at = metadata.generated_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )

        if self.formal_context is None:
            self.write_text("FinAudit 审核报告负载预览", font_size=15.0, leading=19.0)
            self.write_text("本文件仅用于离线技术验证，不构成正式审核报告或审核结论。")
            self.write_text(
                "reference_ids 仅按原始 ID 展示；本 writer 不解析、检索或补充引用内容。"
            )
        else:
            self.write_text("FinAudit 正式审核报告", font_size=15.0, leading=19.0)
            self.write_text("本报告由已完成且冻结的审核执行版本生成；历史版本不可覆盖。")
            self.write_text("引用内容来自该执行已持久化的授权证据链。")

        self.write_section("Summary")
        summary_fields: tuple[tuple[str, ReportCellInput], ...] = (
            ("report_version_id", str(metadata.report_version_id)),
            ("audit_version_id", str(metadata.audit_version_id)),
            ("preview_id", str(self.payload.preview_id)),
            ("generated_at", generated_at),
            ("ai_status", self.payload.ai_status),
            ("overall_level", self.payload.summary.overall_level),
            ("active_risk_count", self.payload.summary.active_risk_count),
            ("dismissed_risk_count", self.payload.summary.dismissed_risk_count),
            ("has_effective_high", self.payload.summary.has_effective_high),
            ("has_unreviewed_high", self.payload.summary.has_unreviewed_high),
            ("is_outdated", metadata.is_outdated),
            ("is_degraded", metadata.is_degraded),
            ("degraded_reasons", self.joined_degraded_reasons),
        )
        for name, value in summary_fields:
            self.write_field(name, value)
        if self.formal_context is not None:
            context = self.formal_context
            context_fields: tuple[tuple[str, ReportCellInput], ...] = (
                ("task_id", str(context.task_id)),
                ("task_no", context.task_no),
                ("task_name", context.task_name),
                ("execution_version", context.execution_version),
                ("baseline_date", context.baseline_date.isoformat()),
                ("finance_reviewer_id", str(context.finance_reviewer_id)),
                (
                    "finance_reviewed_at",
                    context.finance_reviewed_at.isoformat().replace("+00:00", "Z"),
                ),
                (
                    "audit_reviewer_id",
                    None if context.audit_reviewer_id is None else str(context.audit_reviewer_id),
                ),
                (
                    "audit_reviewed_at",
                    None
                    if context.audit_reviewed_at is None
                    else context.audit_reviewed_at.isoformat().replace("+00:00", "Z"),
                ),
            )
            for name, value in context_fields:
                self.write_field(name, value)

        self.write_section("Rules")
        for row_number, row in enumerate(self.payload.rules.rows, start=1):
            self._ensure_lines(2)
            self.write_text(f"Rule {row_number:02d}/15", font_size=9.2, leading=12.0)
            for column_name, cell_value in zip(self.payload.rules.columns, row, strict=True):
                self.write_field(column_name, cell_value)

        self.write_section("Risks")
        if not self.payload.risks.rows:
            self.write_text("无风险记录", indent=10.0)
        for row_number, row in enumerate(self.payload.risks.rows, start=1):
            self._ensure_lines(2)
            self.write_text(
                f"Risk {row_number:02d}/{len(self.payload.risks.rows):02d}",
                font_size=9.2,
                leading=12.0,
            )
            for column_name, cell_value in zip(self.payload.risks.columns, row, strict=True):
                self.write_field(column_name, cell_value)

        if self.formal_context is not None:
            self.write_section("Review Decisions")
            for number, risk in enumerate(self.formal_context.risks, start=1):
                self.write_text(f"Decision {number:02d}", font_size=9.2, leading=12.0)
                for name, value in (
                    ("risk_id", str(risk.risk_id)),
                    ("review_status", risk.review_status.value),
                    ("reviewed_by", str(risk.reviewed_by)),
                    ("reviewed_at", risk.reviewed_at.isoformat().replace("+00:00", "Z")),
                    ("review_reason", risk.review_reason),
                ):
                    self.write_field(name, value)

            self.write_section("Policy Evidence")
            if not self.formal_context.citations:
                self.write_text("本执行未持久化制度引用。", indent=10.0)
            for number, citation in enumerate(self.formal_context.citations, start=1):
                self.write_text(f"Citation {number:02d}", font_size=9.2, leading=12.0)
                for name, value in (
                    ("risk_id", str(citation.risk_id)),
                    ("policy_document_id", str(citation.policy_document_id)),
                    ("markdown_version_id", str(citation.markdown_version_id)),
                    ("chunk_id", str(citation.chunk_id)),
                    ("index_version_id", str(citation.index_version_id)),
                    (
                        "page_range",
                        f"{citation.start_page_no}-{citation.end_page_no}",
                    ),
                    ("title_path", " / ".join(citation.title_path)),
                    ("quote", citation.quote),
                    ("content_sha256", citation.content_sha256),
                ):
                    self.write_field(name, value)

            if self.report_draft is not None:
                self.write_section("AI Draft (Unapproved)")
                self.write_text("以下文字由 AI 生成，仅作草稿，不替代规则结果与人工复核。")
                for name, value in (
                    ("executive_summary", self.report_draft.executive_summary),
                    ("scope_summary", self.report_draft.scope_summary),
                    ("risk_summary", self.report_draft.risk_summary),
                    ("recommendations", " | ".join(self.report_draft.recommendations)),
                    ("warnings", " | ".join(self.report_draft.warnings)),
                ):
                    self.write_field(name, value)

        self._draw_page_footer()
        self.pdf.save()
        result = self.output.getvalue()
        if len(result) > MAX_PDF_BYTES:
            raise ValueError("PDF output exceeds the byte limit")
        return result


def report_payload_pdf_bytes(payload: ReportPayload) -> bytes:
    """生成固定 A4 布局、可移植且确定性的内部离线预览 PDF。"""

    joined_degraded_reasons = validate_report_payload(payload)
    with _PDF_LOCK:
        glyphs = _register_fonts()
        return _PdfRenderer(payload, joined_degraded_reasons, glyphs).render()


def formal_report_pdf_bytes(
    payload: ReportPayload,
    context: FormalReportContext,
    report_draft: ReportDraftOutput | None = None,
) -> bytes:
    """生成带复核人与制度证据的不可变正式审核 PDF。"""

    joined_degraded_reasons = validate_formal_report_payload(payload)
    if type(context) is not FormalReportContext or context.execution_id != payload.preview_id:
        raise ValueError("formal report context does not match the payload")
    if report_draft is not None:
        validate_report_draft(
            report_draft,
            frozen=FrozenReportFacts(
                report_id=str(payload.metadata.report_version_id),
                execution_id=str(payload.preview_id),
                overall_level=payload.summary.overall_level,
                active_risk_count=payload.summary.active_risk_count,
                dismissed_risk_count=payload.summary.dismissed_risk_count,
                has_effective_high=payload.summary.has_effective_high,
                has_unreviewed_high=payload.summary.has_unreviewed_high,
            ),
        )
    with _PDF_LOCK:
        glyphs = _register_fonts()
        return _PdfRenderer(
            payload,
            joined_degraded_reasons,
            glyphs,
            context,
            report_draft,
        ).render()
