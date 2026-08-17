"""MVP-VS-05 的确定性报告负载和安全表格行。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from app.audit.offline_preview import AiPreviewStatus, OfflineAuditPreview, RulePreviewDisposition
from app.audit.risk_summary import RiskSummary
from app.reports.spreadsheet_safety import neutralize_spreadsheet_formula_text

RULE_TABLE_COLUMNS = (
    "rule_id",
    "status",
    "disposition",
    "actual_value",
    "expected_value",
    "risk_id",
    "risk_level",
    "reference_ids",
)
RISK_TABLE_COLUMNS = (
    "risk_id",
    "rule_id",
    "original_level",
    "effective_level",
    "review_status",
    "actual_value",
    "expected_value",
    "reference_ids",
)

ReportCell = str | int | bool | None
ReportCellInput = ReportCell | Decimal


def _safe_text(value: str) -> str:
    return neutralize_spreadsheet_formula_text(value)


def _safe_cell(value: ReportCellInput) -> ReportCell:
    if value is None:
        return None
    if type(value) is bool:
        return bool(value)
    if type(value) is int:
        return int(value)
    if type(value) is str:
        return _safe_text(value)
    if type(value) is Decimal and value.is_finite():
        return _safe_text(str(value))
    raise ValueError("report cells must be str, finite Decimal, exact int, exact bool, or None")


@dataclass(frozen=True, slots=True)
class ReportMetadata:
    """由调用方提供的稳定报告版本与降级事实。"""

    report_version_id: UUID
    audit_version_id: UUID
    generated_at: datetime
    is_outdated: bool
    is_degraded: bool
    degraded_reasons: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.report_version_id) is not UUID:
            raise ValueError("report_version_id must be an exact UUID")
        if type(self.audit_version_id) is not UUID:
            raise ValueError("audit_version_id must be an exact UUID")
        if type(self.generated_at) is not datetime:
            raise ValueError("generated_at must be an exact datetime")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() != timedelta(0):
            raise ValueError("generated_at must be timezone-aware UTC")
        if type(self.is_outdated) is not bool:
            raise ValueError("is_outdated must be an exact bool")
        if type(self.is_degraded) is not bool:
            raise ValueError("is_degraded must be an exact bool")
        if type(self.degraded_reasons) is not tuple or any(
            type(reason) is not str or not reason.strip() for reason in self.degraded_reasons
        ):
            raise ValueError("degraded_reasons must be a tuple of non-blank exact str")

        safe_reasons = tuple(sorted({_safe_text(reason) for reason in self.degraded_reasons}))
        if self.is_degraded is not bool(safe_reasons):
            raise ValueError("is_degraded must match degraded_reasons")
        object.__setattr__(self, "degraded_reasons", safe_reasons)


@dataclass(frozen=True, slots=True)
class ReportSummary:
    """报告中按固定字段输出的风险汇总。"""

    overall_level: str
    active_risk_count: int
    dismissed_risk_count: int
    has_effective_high: bool
    has_unreviewed_high: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "overall_level", _safe_text(self.overall_level))


@dataclass(frozen=True, slots=True)
class ReportTable:
    """冻结、定宽且已做公式前缀保护的表格。"""

    columns: tuple[str, ...]
    rows: tuple[tuple[ReportCellInput, ...], ...] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.columns) is not tuple or any(
            type(column) is not str for column in self.columns
        ):
            raise ValueError("columns must be a tuple of exact str")
        safe_columns = tuple(_safe_text(column) for column in self.columns)
        if len(safe_columns) != len(set(safe_columns)):
            raise ValueError("columns must be unique after formula protection")
        if type(self.rows) is not tuple or any(type(row) is not tuple for row in self.rows):
            raise ValueError("rows must be a tuple of tuples")
        if any(len(row) != len(safe_columns) for row in self.rows):
            raise ValueError("each row must match the fixed column count")
        safe_rows = tuple(tuple(_safe_cell(cell) for cell in row) for row in self.rows)
        object.__setattr__(self, "columns", safe_columns)
        object.__setattr__(self, "rows", safe_rows)


@dataclass(frozen=True, slots=True)
class ReportPayload:
    """后续 PDF/XLSX Writer 可直接消费的冻结输入边界。"""

    metadata: ReportMetadata = field(repr=False)
    preview_id: UUID
    ai_status: str
    summary: ReportSummary = field(repr=False)
    rules: ReportTable = field(repr=False)
    risks: ReportTable = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.metadata) is not ReportMetadata:
            raise ValueError("metadata must be a ReportMetadata")
        if type(self.preview_id) is not UUID:
            raise ValueError("preview_id must be an exact UUID")
        if type(self.ai_status) is not str:
            raise ValueError("ai_status must be an exact str")
        if type(self.summary) is not ReportSummary:
            raise ValueError("summary must be a ReportSummary")
        if type(self.rules) is not ReportTable or self.rules.columns != RULE_TABLE_COLUMNS:
            raise ValueError("rules must use the fixed rule columns")
        if type(self.risks) is not ReportTable or self.risks.columns != RISK_TABLE_COLUMNS:
            raise ValueError("risks must use the fixed risk columns")
        object.__setattr__(self, "ai_status", _safe_text(self.ai_status))


def _uuid_text(value: UUID) -> str:
    return _safe_text(str(value))


def _reference_text(reference_ids: tuple[UUID, ...]) -> str:
    canonical_ids = sorted(set(reference_ids), key=lambda reference_id: reference_id.bytes)
    return _safe_text(";".join(_uuid_text(reference_id) for reference_id in canonical_ids))


def _summary_payload(summary: RiskSummary) -> ReportSummary:
    return ReportSummary(
        overall_level=_safe_text(summary.overall_level.value),
        active_risk_count=summary.active_risk_count,
        dismissed_risk_count=summary.dismissed_risk_count,
        has_effective_high=summary.has_effective_high,
        has_unreviewed_high=summary.has_unreviewed_high,
    )


def build_report_payload(
    preview: OfflineAuditPreview,
    metadata: ReportMetadata,
) -> ReportPayload:
    """把离线审核预览转换为固定顺序的安全报告负载。"""

    if type(preview) is not OfflineAuditPreview:
        raise ValueError("preview must be an OfflineAuditPreview")
    if type(metadata) is not ReportMetadata:
        raise ValueError("metadata must be a ReportMetadata")
    if preview.ai_status is AiPreviewStatus.DISABLED and not metadata.is_degraded:
        raise ValueError("disabled AI preview requires degraded report metadata")

    rule_rows: list[tuple[ReportCellInput, ...]] = []
    hit_rules_by_risk_id = {}
    for rule in preview.rules:
        references = _reference_text(rule.reference_ids)
        rule_rows.append(
            (
                _safe_text(rule.rule_id),
                _safe_text(rule.status.value),
                _safe_text(rule.disposition.value),
                None if rule.actual_value is None else _safe_text(rule.actual_value),
                None if rule.expected_value is None else _safe_text(rule.expected_value),
                None if rule.risk_id is None else _uuid_text(rule.risk_id),
                None if rule.risk_level is None else _safe_text(rule.risk_level.value),
                references,
            )
        )
        if rule.disposition is RulePreviewDisposition.HIT:
            if rule.risk_id is None:
                raise ValueError("hit rule must contain a risk_id")
            hit_rules_by_risk_id[rule.risk_id] = rule

    risk_rows: list[tuple[ReportCellInput, ...]] = []
    risks_with_rules = sorted(
        ((risk, hit_rules_by_risk_id[risk.risk_id]) for risk in preview.risks),
        key=lambda item: (item[1].rule_id, item[0].risk_id.bytes),
    )
    for risk, rule in risks_with_rules:
        risk_rows.append(
            (
                _uuid_text(risk.risk_id),
                _safe_text(rule.rule_id),
                _safe_text(risk.original_level.value),
                _safe_text(risk.effective_level.value),
                _safe_text(risk.review_status.value),
                None if rule.actual_value is None else _safe_text(rule.actual_value),
                None if rule.expected_value is None else _safe_text(rule.expected_value),
                _reference_text(rule.reference_ids),
            )
        )

    return ReportPayload(
        metadata=metadata,
        preview_id=preview.preview_id,
        ai_status=_safe_text(preview.ai_status.value),
        summary=_summary_payload(preview.summary),
        rules=ReportTable(columns=RULE_TABLE_COLUMNS, rows=tuple(rule_rows)),
        risks=ReportTable(columns=RISK_TABLE_COLUMNS, rows=tuple(risk_rows)),
    )


def _metadata_document(metadata: ReportMetadata) -> dict[str, object]:
    generated_at = metadata.generated_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return {
        "report_version_id": _uuid_text(metadata.report_version_id),
        "audit_version_id": _uuid_text(metadata.audit_version_id),
        "generated_at": _safe_text(generated_at.replace("+00:00", "Z")),
        "is_outdated": metadata.is_outdated,
        "is_degraded": metadata.is_degraded,
        "degraded_reasons": list(metadata.degraded_reasons),
    }


def _table_document(table: ReportTable) -> dict[str, object]:
    return {
        "columns": list(table.columns),
        "rows": [list(row) for row in table.rows],
    }


def report_payload_json_bytes(payload: ReportPayload) -> bytes:
    """按固定字段顺序输出确定性 UTF-8 JSON 字节。"""

    if type(payload) is not ReportPayload:
        raise ValueError("payload must be a ReportPayload")
    document = {
        "metadata": _metadata_document(payload.metadata),
        "preview_id": _uuid_text(payload.preview_id),
        "ai_status": _safe_text(payload.ai_status),
        "summary": {
            "overall_level": _safe_text(payload.summary.overall_level),
            "active_risk_count": payload.summary.active_risk_count,
            "dismissed_risk_count": payload.summary.dismissed_risk_count,
            "has_effective_high": payload.summary.has_effective_high,
            "has_unreviewed_high": payload.summary.has_unreviewed_high,
        },
        "rules": _table_document(payload.rules),
        "risks": _table_document(payload.risks),
    }
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
