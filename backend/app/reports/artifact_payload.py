"""报告制品 writer 共用的冻结负载重验边界。"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import TypeVar
from uuid import UUID

from app.audit.offline_preview import AiPreviewStatus, RulePreviewDisposition, RulePreviewResult
from app.audit.risk_summary import (
    RiskLevel,
    RiskReviewStatus,
    RiskSummaryInput,
    calculate_risk_summary,
)
from app.audit.rule_predicates import RuleExecutionStatus
from app.reports.report_payload import (
    RISK_TABLE_COLUMNS,
    RULE_TABLE_COLUMNS,
    ReportCellInput,
    ReportMetadata,
    ReportPayload,
    ReportSummary,
    ReportTable,
)

MAX_ARTIFACT_CELL_CODEPOINTS = 4_096
MAX_ARTIFACT_TOTAL_TEXT_CODEPOINTS = 262_144
MAX_ARTIFACT_REFERENCE_IDS = 110
MAX_ARTIFACT_DEGRADED_REASONS = 1_024

_RULE_IDS = tuple(f"RULE-{number:03d}" for number in range(1, 16))
_EnumT = TypeVar("_EnumT", bound=Enum)


def safe_artifact_text(value: str) -> str:
    """校验可安全写入 XML/PDF 的有界 Unicode 文本，不改变原值。"""

    if type(value) is not str:
        raise ValueError("artifact text must be an exact str")
    if len(value) > MAX_ARTIFACT_CELL_CODEPOINTS:
        raise ValueError("artifact text exceeds the cell codepoint limit")
    for character in value:
        codepoint = ord(character)
        if not (
            codepoint in (0x09, 0x0A, 0x0D)
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ):
            raise ValueError("artifact text contains an invalid XML/PDF character")
    return value


class _TextBudget:
    __slots__ = ("total",)

    def __init__(self) -> None:
        self.total = 0

    def add(self, value: str) -> str:
        safe = safe_artifact_text(value)
        self.total += len(safe)
        if self.total > MAX_ARTIFACT_TOTAL_TEXT_CODEPOINTS:
            raise ValueError("artifact text exceeds the workbook codepoint limit")
        return safe


def _joined_degraded_reasons(reasons: tuple[str, ...], budget: _TextBudget) -> str:
    if type(reasons) is not tuple:
        raise ValueError("payload degraded_reasons must be an exact tuple")
    if len(reasons) > MAX_ARTIFACT_DEGRADED_REASONS:
        raise ValueError("payload degraded_reasons exceed the count limit")

    safe_reasons: list[str] = []
    joined_length = 0
    for reason in reasons:
        if type(reason) is not str or not reason.strip():
            raise ValueError("payload degraded_reasons must contain non-blank exact strings")
        safe = safe_artifact_text(reason)
        joined_length += len(safe) + (3 if safe_reasons else 0)
        if joined_length > MAX_ARTIFACT_CELL_CODEPOINTS:
            raise ValueError("payload degraded_reasons exceed the joined cell limit")
        budget.add(safe)
        safe_reasons.append(safe)
    return " | ".join(safe_reasons)


def _optional_text(value: ReportCellInput, *, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is str:
        return value
    raise ValueError(f"payload {name} must be an exact str or None")


def _optional_uuid(value: ReportCellInput, *, name: str) -> UUID | None:
    text = _optional_text(value, name=name)
    if text is None:
        return None
    try:
        parsed = UUID(text)
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"payload {name} must be a canonical UUID or None") from exc
    if text != str(parsed):
        raise ValueError(f"payload {name} must be a canonical UUID or None")
    return parsed


def _required_enum(value: ReportCellInput, enum_type: type[_EnumT], *, name: str) -> _EnumT:
    if type(value) is not str:
        raise ValueError(f"payload {name} must be an exact enum string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"payload {name} must be an exact enum string") from exc


def _optional_enum(value: ReportCellInput, enum_type: type[_EnumT], *, name: str) -> _EnumT | None:
    if value is None:
        return None
    return _required_enum(value, enum_type, name=name)


def _reference_ids(value: ReportCellInput) -> tuple[UUID, ...]:
    if type(value) is not str:
        raise ValueError("payload reference_ids must be an exact string")
    safe_artifact_text(value)
    if value == "":
        return ()
    if value.count(";") + 1 > MAX_ARTIFACT_REFERENCE_IDS:
        raise ValueError("payload reference_ids exceed the count limit")
    references = tuple(_optional_uuid(part, name="reference_id") for part in value.split(";"))
    if any(reference is None for reference in references):
        raise ValueError("payload reference_ids must contain canonical UUIDs")
    canonical = tuple(reference for reference in references if reference is not None)
    if canonical != tuple(sorted(set(canonical), key=lambda reference: reference.bytes)):
        raise ValueError("payload reference_ids must be sorted and unique")
    return canonical


def _rule_result_from_row(row: tuple[ReportCellInput, ...]) -> RulePreviewResult:
    if type(row[0]) is not str:
        raise ValueError("payload rule_id must be an exact string")
    return RulePreviewResult(
        rule_id=row[0],
        status=_required_enum(row[1], RuleExecutionStatus, name="rule status"),
        disposition=_required_enum(row[2], RulePreviewDisposition, name="rule disposition"),
        actual_value=_optional_text(row[3], name="actual_value"),
        expected_value=_optional_text(row[4], name="expected_value"),
        risk_id=_optional_uuid(row[5], name="rule risk_id"),
        risk_level=_optional_enum(row[6], RiskLevel, name="rule risk_level"),
        reference_ids=_reference_ids(row[7]),
    )


class _ParsedRiskRow:
    __slots__ = ("risk", "rule_id", "actual_value", "expected_value", "reference_ids")

    def __init__(
        self,
        *,
        risk: RiskSummaryInput,
        rule_id: str,
        actual_value: str | None,
        expected_value: str | None,
        reference_ids: tuple[UUID, ...],
    ) -> None:
        self.risk = risk
        self.rule_id = rule_id
        self.actual_value = actual_value
        self.expected_value = expected_value
        self.reference_ids = reference_ids


def _risk_row_from_row(row: tuple[ReportCellInput, ...]) -> _ParsedRiskRow:
    risk_id = _optional_uuid(row[0], name="risk_id")
    if risk_id is None:
        raise ValueError("payload risk_id must be a canonical UUID")
    if type(row[1]) is not str or row[1] not in _RULE_IDS:
        raise ValueError("payload risk rule_id must be a stable rule ID")
    return _ParsedRiskRow(
        risk=RiskSummaryInput(
            risk_id=risk_id,
            original_level=_required_enum(row[2], RiskLevel, name="original_level"),
            effective_level=_required_enum(row[3], RiskLevel, name="effective_level"),
            review_status=_required_enum(row[4], RiskReviewStatus, name="review_status"),
        ),
        rule_id=row[1],
        actual_value=_optional_text(row[5], name="risk actual_value"),
        expected_value=_optional_text(row[6], name="risk expected_value"),
        reference_ids=_reference_ids(row[7]),
    )


def _validate_report_payload(payload: ReportPayload, *, formal: bool) -> str:
    """重验冻结负载的精确类型、领域映射和制品资源上限。"""

    if type(payload) is not ReportPayload:
        raise ValueError("payload must be a ReportPayload")
    if type(payload.metadata) is not ReportMetadata:
        raise ValueError("payload metadata must be a ReportMetadata")
    if type(payload.summary) is not ReportSummary:
        raise ValueError("payload summary must be a ReportSummary")
    if type(payload.rules) is not ReportTable or payload.rules.columns != RULE_TABLE_COLUMNS:
        raise ValueError("payload rules must use the fixed rule columns")
    if type(payload.risks) is not ReportTable or payload.risks.columns != RISK_TABLE_COLUMNS:
        raise ValueError("payload risks must use the fixed risk columns")

    metadata = payload.metadata
    if type(metadata.report_version_id) is not UUID or type(metadata.audit_version_id) is not UUID:
        raise ValueError("payload metadata IDs must be exact UUIDs")
    if type(payload.preview_id) is not UUID:
        raise ValueError("payload preview_id must be an exact UUID")
    if type(metadata.generated_at) is not datetime:
        raise ValueError("payload generated_at must be an exact datetime")
    if metadata.generated_at.tzinfo is None or metadata.generated_at.utcoffset() != timedelta(0):
        raise ValueError("payload generated_at must be timezone-aware UTC")
    if type(metadata.is_outdated) is not bool or type(metadata.is_degraded) is not bool:
        raise ValueError("payload metadata flags must be exact bools")

    budget = _TextBudget()
    joined_degraded_reasons = _joined_degraded_reasons(metadata.degraded_reasons, budget)
    if metadata.is_degraded is not bool(metadata.degraded_reasons):
        raise ValueError("payload is_degraded must match degraded_reasons")

    summary = payload.summary
    if type(payload.ai_status) is not str or type(summary.overall_level) is not str:
        raise ValueError("payload summary text must be exact strings")
    if payload.ai_status != AiPreviewStatus.DISABLED.value or not metadata.is_degraded:
        raise ValueError("payload disabled AI status requires degraded metadata")
    if (
        type(summary.active_risk_count) is not int
        or summary.active_risk_count < 0
        or type(summary.dismissed_risk_count) is not int
        or summary.dismissed_risk_count < 0
    ):
        raise ValueError("payload risk counts must be non-negative exact ints")
    if (
        type(summary.has_effective_high) is not bool
        or type(summary.has_unreviewed_high) is not bool
    ):
        raise ValueError("payload high-risk flags must be exact bools")

    if type(payload.rules.rows) is not tuple or len(payload.rules.rows) != len(_RULE_IDS):
        raise ValueError("payload rules must contain exactly 15 rows")
    if any(
        type(row) is not tuple or len(row) != len(RULE_TABLE_COLUMNS) for row in payload.rules.rows
    ):
        raise ValueError("payload rule rows must match the fixed columns")
    if tuple(row[0] for row in payload.rules.rows) != _RULE_IDS:
        raise ValueError("payload rules must be ordered RULE-001 through RULE-015")

    if type(payload.risks.rows) is not tuple or len(payload.risks.rows) > 15:
        raise ValueError("payload risks must contain at most 15 rows")
    if any(
        type(row) is not tuple or len(row) != len(RISK_TABLE_COLUMNS) for row in payload.risks.rows
    ):
        raise ValueError("payload risk rows must match the fixed columns")

    dynamic_text = (
        str(metadata.report_version_id),
        str(metadata.audit_version_id),
        str(payload.preview_id),
        metadata.generated_at.isoformat(timespec="microseconds"),
        payload.ai_status,
        summary.overall_level,
    )
    for value in dynamic_text:
        budget.add(value)
    for table in (payload.rules, payload.risks):
        for row in table.rows:
            for cell in row:
                if type(cell) is str:
                    budget.add(cell)

    rule_results = tuple(_rule_result_from_row(row) for row in payload.rules.rows)
    parsed_risk_rows = tuple(_risk_row_from_row(row) for row in payload.risks.rows)
    risk_inputs = tuple(parsed.risk for parsed in parsed_risk_rows)
    hit_rules = tuple(
        rule for rule in rule_results if rule.disposition is RulePreviewDisposition.HIT
    )
    if tuple(rule.risk_id for rule in hit_rules) != tuple(risk.risk_id for risk in risk_inputs):
        raise ValueError("payload risks must follow hit rule order")
    if formal:
        invalid_risk_mapping = any(
            risk.original_level is not rule.risk_level
            or risk.review_status is RiskReviewStatus.PENDING
            or parsed.rule_id != rule.rule_id
            or parsed.actual_value != rule.actual_value
            or parsed.expected_value != rule.expected_value
            or parsed.reference_ids != rule.reference_ids
            for rule, risk, parsed in zip(
                hit_rules,
                risk_inputs,
                parsed_risk_rows,
                strict=True,
            )
        )
    else:
        invalid_risk_mapping = any(
            risk.original_level is not rule.risk_level
            or risk.effective_level is not rule.risk_level
            or risk.review_status is not RiskReviewStatus.PENDING
            or parsed.rule_id != rule.rule_id
            or parsed.actual_value != rule.actual_value
            or parsed.expected_value != rule.expected_value
            or parsed.reference_ids != rule.reference_ids
            for rule, risk, parsed in zip(
                hit_rules,
                risk_inputs,
                parsed_risk_rows,
                strict=True,
            )
        )
    if invalid_risk_mapping:
        raise ValueError(
            "formal payload risks must match reviewed hit rules"
            if formal
            else "payload risks must match hit rules and pending status"
        )

    calculated = calculate_risk_summary(risk_inputs)
    if (
        summary.overall_level != calculated.overall_level.value
        or summary.active_risk_count != calculated.active_risk_count
        or summary.dismissed_risk_count != calculated.dismissed_risk_count
        or summary.has_effective_high is not calculated.has_effective_high
        or summary.has_unreviewed_high is not calculated.has_unreviewed_high
    ):
        raise ValueError("payload summary must match risks")
    return joined_degraded_reasons


def validate_report_payload(payload: ReportPayload) -> str:
    """重验仅含 pending 风险的内部预览负载。"""

    return _validate_report_payload(payload, formal=False)


def validate_formal_report_payload(payload: ReportPayload) -> str:
    """重验已完成人工复核、可进入正式制品的负载。"""

    return _validate_report_payload(payload, formal=True)
