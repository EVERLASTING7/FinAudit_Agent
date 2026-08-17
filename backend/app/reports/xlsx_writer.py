"""从冻结报告负载生成有界、无主动内容的 XLSX 字节。"""

from __future__ import annotations

from datetime import timezone
from io import BytesIO
from typing import Protocol

import xlsxwriter  # type: ignore[import-untyped]

from app.ai.report_draft import FrozenReportFacts, ReportDraftOutput, validate_report_draft
from app.reports.artifact_payload import (
    MAX_ARTIFACT_CELL_CODEPOINTS,
    MAX_ARTIFACT_DEGRADED_REASONS,
    MAX_ARTIFACT_REFERENCE_IDS,
    MAX_ARTIFACT_TOTAL_TEXT_CODEPOINTS,
    safe_artifact_text,
    validate_formal_report_payload,
    validate_report_payload,
)
from app.reports.report_payload import ReportCell, ReportPayload, ReportTable
from app.reports.spreadsheet_safety import neutralize_spreadsheet_formula_text

MAX_XLSX_CELL_CODEPOINTS = MAX_ARTIFACT_CELL_CODEPOINTS
MAX_XLSX_TOTAL_TEXT_CODEPOINTS = MAX_ARTIFACT_TOTAL_TEXT_CODEPOINTS
MAX_XLSX_BYTES = 2 * 1024 * 1024
MAX_XLSX_EXACT_INTEGER = 9_007_199_254_740_991
MAX_XLSX_REFERENCE_IDS = MAX_ARTIFACT_REFERENCE_IDS
MAX_XLSX_DEGRADED_REASONS = MAX_ARTIFACT_DEGRADED_REASONS

_SHEET_NAMES = ("Summary", "Rules", "Risks")


class _Worksheet(Protocol):
    def write_string(self, row: int, column: int, value: str) -> int: ...

    def write_boolean(self, row: int, column: int, value: bool) -> int: ...

    def write_number(self, row: int, column: int, value: int) -> int: ...

    def write_blank(self, row: int, column: int, value: None) -> int: ...


def _safe_xlsx_text(value: str) -> str:
    safe = safe_artifact_text(value)
    protected = neutralize_spreadsheet_formula_text(safe)
    if len(protected) > MAX_XLSX_CELL_CODEPOINTS:
        raise ValueError("XLSX protected text exceeds the cell codepoint limit")
    return protected


class _TextBudget:
    __slots__ = ("total",)

    def __init__(self) -> None:
        self.total = 0

    def add(self, value: str) -> str:
        protected = _safe_xlsx_text(value)
        self.total += len(protected)
        if self.total > MAX_XLSX_TOTAL_TEXT_CODEPOINTS:
            raise ValueError("XLSX text exceeds the workbook codepoint limit")
        return protected


def _prepared_cell(value: object, budget: _TextBudget) -> ReportCell:
    if value is None:
        return None
    if type(value) is bool:
        return bool(value)
    if type(value) is int:
        if abs(value) > MAX_XLSX_EXACT_INTEGER:
            raise ValueError("XLSX integer exceeds the exact numeric range")
        return int(value)
    if type(value) is str:
        return budget.add(value)
    raise ValueError("XLSX cells must be exact str, int, bool, or None")


def _summary_rows(
    payload: ReportPayload,
    joined_degraded_reasons: str,
    budget: _TextBudget,
) -> tuple[tuple[ReportCell, ...], ...]:
    generated_at = payload.metadata.generated_at.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    raw_rows: tuple[tuple[object, object], ...] = (
        ("field", "value"),
        ("report_version_id", str(payload.metadata.report_version_id)),
        ("audit_version_id", str(payload.metadata.audit_version_id)),
        ("preview_id", str(payload.preview_id)),
        ("generated_at", generated_at),
        ("ai_status", payload.ai_status),
        ("overall_level", payload.summary.overall_level),
        ("active_risk_count", payload.summary.active_risk_count),
        ("dismissed_risk_count", payload.summary.dismissed_risk_count),
        ("has_effective_high", payload.summary.has_effective_high),
        ("has_unreviewed_high", payload.summary.has_unreviewed_high),
        ("is_outdated", payload.metadata.is_outdated),
        ("is_degraded", payload.metadata.is_degraded),
        ("degraded_reasons", joined_degraded_reasons),
    )
    return tuple(tuple(_prepared_cell(cell, budget) for cell in row) for row in raw_rows)


def _table_rows(table: ReportTable, budget: _TextBudget) -> tuple[tuple[ReportCell, ...], ...]:
    raw_rows = (table.columns, *table.rows)
    return tuple(tuple(_prepared_cell(cell, budget) for cell in row) for row in raw_rows)


def _draft_rows(
    draft: ReportDraftOutput,
    budget: _TextBudget,
) -> tuple[tuple[ReportCell, ...], ...]:
    raw_rows: list[tuple[object, object]] = [
        ("field", "value"),
        ("notice", "AI 生成草稿，不替代规则结果与人工复核"),
        ("executive_summary", draft.executive_summary),
        ("scope_summary", draft.scope_summary),
        ("risk_summary", draft.risk_summary),
    ]
    raw_rows.extend(
        (f"recommendation_{index}", value)
        for index, value in enumerate(draft.recommendations, start=1)
    )
    raw_rows.extend(
        (f"warning_{index}", value) for index, value in enumerate(draft.warnings, start=1)
    )
    return tuple(tuple(_prepared_cell(cell, budget) for cell in row) for row in raw_rows)


def _write_cell(worksheet: _Worksheet, row: int, column: int, value: ReportCell) -> None:
    if type(value) is str:
        result = worksheet.write_string(row, column, value)
    elif type(value) is bool:
        result = worksheet.write_boolean(row, column, value)
    elif type(value) is int:
        result = worksheet.write_number(row, column, value)
    elif value is None:
        result = worksheet.write_blank(row, column, None)
    else:  # pragma: no cover - _prepared_cell closes this branch.
        raise ValueError("unsupported XLSX cell type")
    if result != 0:
        raise RuntimeError("XLSX cell write failed")


def _write_rows(worksheet: _Worksheet, rows: tuple[tuple[ReportCell, ...], ...]) -> None:
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            _write_cell(worksheet, row_index, column_index, value)


def _report_payload_xlsx_bytes(
    payload: ReportPayload,
    *,
    formal: bool,
    report_draft: ReportDraftOutput | None = None,
) -> bytes:
    joined_degraded_reasons = (
        validate_formal_report_payload(payload) if formal else validate_report_payload(payload)
    )
    budget = _TextBudget()
    sheet_names: tuple[str, ...] = _SHEET_NAMES
    rows_by_sheet: tuple[tuple[tuple[ReportCell, ...], ...], ...] = (
        _summary_rows(payload, joined_degraded_reasons, budget),
        _table_rows(payload.rules, budget),
        _table_rows(payload.risks, budget),
    )
    if report_draft is not None:
        if not formal:
            raise ValueError("AI report drafts are only valid for formal reports")
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
        sheet_names = (*sheet_names, "AI Draft")
        rows_by_sheet = (*rows_by_sheet, _draft_rows(report_draft, budget))

    output = BytesIO()
    workbook = xlsxwriter.Workbook(
        output,
        {
            "in_memory": True,
            "strings_to_formulas": False,
            "strings_to_urls": False,
            "strings_to_numbers": False,
        },
    )
    workbook.set_properties(
        {
            "title": "FinAudit formal risk details" if formal else "FinAudit risk details",
            "subject": (
                "Frozen completed audit execution report"
                if formal
                else "Frozen audit report payload"
            ),
            "author": "FinAudit Agent",
            "company": "FinAudit Agent",
            "category": "Audit report",
            "comments": "Generated from a frozen ReportPayload",
            "created": payload.metadata.generated_at.astimezone(timezone.utc).replace(tzinfo=None),
        }
    )
    for sheet_name, rows in zip(sheet_names, rows_by_sheet, strict=True):
        worksheet: _Worksheet = workbook.add_worksheet(sheet_name)
        _write_rows(worksheet, rows)
    workbook.close()

    result = output.getvalue()
    if len(result) > MAX_XLSX_BYTES:
        raise ValueError("XLSX output exceeds the byte limit")
    return result


def report_payload_xlsx_bytes(payload: ReportPayload) -> bytes:
    """生成固定 Summary/Rules/Risks 工作表的确定性内部 XLSX 字节。"""

    return _report_payload_xlsx_bytes(payload, formal=False)


def formal_report_xlsx_bytes(
    payload: ReportPayload,
    report_draft: ReportDraftOutput | None = None,
) -> bytes:
    """生成已完成人工复核的正式风险明细 XLSX。"""

    return _report_payload_xlsx_bytes(
        payload,
        formal=True,
        report_draft=report_draft,
    )
