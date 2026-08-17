"""已完成审核执行到正式报告负载的确定性投影。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID

from app.audit.offline_preview import AiPreviewStatus, RulePreviewDisposition
from app.audit.risk_summary import (
    RiskLevel,
    RiskReviewStatus,
    RiskSummaryInput,
    calculate_risk_summary,
)
from app.audit.rule_catalog import RULE_CATALOG_CODES
from app.audit.rule_predicates import RuleExecutionStatus
from app.reports.artifact_payload import safe_artifact_text, validate_formal_report_payload
from app.reports.report_payload import (
    RISK_TABLE_COLUMNS,
    RULE_TABLE_COLUMNS,
    ReportCellInput,
    ReportMetadata,
    ReportPayload,
    ReportSummary,
    ReportTable,
    report_payload_json_bytes,
)


def _utc(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")
    return value


def _safe_optional(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be non-blank")
    return safe_artifact_text(value)


def _sorted_ids(values: tuple[UUID, ...]) -> tuple[UUID, ...]:
    if type(values) is not tuple or any(type(value) is not UUID for value in values):
        raise ValueError("references must be UUID tuples")
    return tuple(sorted(set(values), key=lambda value: value.bytes))


@dataclass(frozen=True, slots=True)
class FormalRuleFact:
    rule_code: str
    status: RuleExecutionStatus
    disposition: RulePreviewDisposition
    actual_value: str | None = field(repr=False)
    expected_value: str | None = field(repr=False)
    included_item_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if self.rule_code not in RULE_CATALOG_CODES:
            raise ValueError("formal rule code is invalid")
        if type(self.status) is not RuleExecutionStatus:
            raise ValueError("formal rule status is invalid")
        if type(self.disposition) is not RulePreviewDisposition:
            raise ValueError("formal rule disposition is invalid")
        expected_status = {
            RulePreviewDisposition.HIT: RuleExecutionStatus.FAILED,
            RulePreviewDisposition.NOT_HIT: RuleExecutionStatus.PASSED,
            RulePreviewDisposition.NOT_APPLICABLE: RuleExecutionStatus.NOT_APPLICABLE,
            RulePreviewDisposition.MISSING: RuleExecutionStatus.NOT_APPLICABLE,
        }[self.disposition]
        if self.status is not expected_status:
            raise ValueError("formal rule status and disposition differ")
        for name, value in (
            ("actual_value", self.actual_value),
            ("expected_value", self.expected_value),
        ):
            object.__setattr__(self, name, _safe_optional(value, name))
        if self.disposition is RulePreviewDisposition.HIT and (
            self.actual_value is None or self.expected_value is None
        ):
            raise ValueError("hit rule requires actual and expected values")
        object.__setattr__(self, "included_item_ids", _sorted_ids(self.included_item_ids))


@dataclass(frozen=True, slots=True)
class FormalRiskFact:
    risk_id: UUID
    rule_code: str
    original_level: RiskLevel
    effective_level: RiskLevel
    review_status: RiskReviewStatus
    actual_value: str = field(repr=False)
    expected_value: str = field(repr=False)
    reviewed_by: UUID
    reviewed_at: datetime
    review_reason: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.risk_id) is not UUID or self.rule_code not in RULE_CATALOG_CODES:
            raise ValueError("formal risk identity is invalid")
        if (
            type(self.original_level) is not RiskLevel
            or type(self.effective_level) is not RiskLevel
        ):
            raise ValueError("formal risk level is invalid")
        if (
            type(self.review_status) is not RiskReviewStatus
            or self.review_status is RiskReviewStatus.PENDING
        ):
            raise ValueError("formal risk must be reviewed")
        if type(self.reviewed_by) is not UUID:
            raise ValueError("formal risk reviewer is invalid")
        object.__setattr__(self, "reviewed_at", _utc(self.reviewed_at, "reviewed_at"))
        for name in ("actual_value", "expected_value", "review_reason"):
            value = getattr(self, name)
            safe = _safe_optional(value, name)
            if safe is None:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, safe)


@dataclass(frozen=True, slots=True)
class FormalCitation:
    risk_id: UUID
    policy_document_id: UUID
    markdown_version_id: UUID
    chunk_id: UUID
    index_version_id: UUID
    start_page_no: int
    end_page_no: int
    title_path: tuple[str, ...]
    quote: str = field(repr=False)
    content_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "risk_id",
            "policy_document_id",
            "markdown_version_id",
            "chunk_id",
            "index_version_id",
        ):
            if type(getattr(self, name)) is not UUID:
                raise ValueError(f"{name} is invalid")
        if (
            type(self.start_page_no) is not int
            or type(self.end_page_no) is not int
            or self.start_page_no <= 0
            or self.end_page_no < self.start_page_no
        ):
            raise ValueError("formal citation page range is invalid")
        if type(self.title_path) is not tuple or any(
            type(value) is not str or not value.strip() for value in self.title_path
        ):
            raise ValueError("formal citation title path is invalid")
        object.__setattr__(
            self,
            "title_path",
            tuple(safe_artifact_text(value) for value in self.title_path),
        )
        safe_quote = _safe_optional(self.quote, "quote")
        if safe_quote is None:
            raise ValueError("formal citation quote is required")
        object.__setattr__(self, "quote", safe_quote)
        if (
            type(self.content_sha256) is not str
            or len(self.content_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.content_sha256)
        ):
            raise ValueError("formal citation content hash is invalid")


@dataclass(frozen=True, slots=True)
class FormalReportContext:
    task_id: UUID
    task_no: str
    task_name: str
    execution_id: UUID
    execution_version: int
    baseline_date: date
    finance_reviewer_id: UUID
    finance_reviewed_at: datetime
    audit_reviewer_id: UUID | None
    audit_reviewed_at: datetime | None
    risks: tuple[FormalRiskFact, ...] = field(repr=False)
    citations: tuple[FormalCitation, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.task_id) is not UUID or type(self.execution_id) is not UUID:
            raise ValueError("formal report parent identity is invalid")
        for name in ("task_no", "task_name"):
            safe = _safe_optional(getattr(self, name), name)
            if safe is None:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, safe)
        if type(self.execution_version) is not int or self.execution_version <= 0:
            raise ValueError("formal report execution version is invalid")
        if type(self.baseline_date) is not date:
            raise ValueError("formal report baseline date is invalid")
        if type(self.finance_reviewer_id) is not UUID:
            raise ValueError("formal report finance reviewer is required")
        object.__setattr__(
            self,
            "finance_reviewed_at",
            _utc(self.finance_reviewed_at, "finance_reviewed_at"),
        )
        if (self.audit_reviewer_id is None) != (self.audit_reviewed_at is None):
            raise ValueError("formal report audit reviewer pair is invalid")
        if self.audit_reviewer_id is not None:
            if type(self.audit_reviewer_id) is not UUID:
                raise ValueError("formal report audit reviewer is invalid")
            assert self.audit_reviewed_at is not None
            object.__setattr__(
                self,
                "audit_reviewed_at",
                _utc(self.audit_reviewed_at, "audit_reviewed_at"),
            )
        if type(self.risks) is not tuple or any(
            type(value) is not FormalRiskFact for value in self.risks
        ):
            raise ValueError("formal report risks are invalid")
        if type(self.citations) is not tuple or any(
            type(value) is not FormalCitation for value in self.citations
        ):
            raise ValueError("formal report citations are invalid")
        risk_ids = tuple(value.risk_id for value in self.risks)
        if len(risk_ids) != len(set(risk_ids)):
            raise ValueError("formal report risk identities must be unique")
        if any(value.risk_id not in set(risk_ids) for value in self.citations):
            raise ValueError("formal report citation risk is unknown")


def _reference_text(values: tuple[UUID, ...]) -> str:
    return ";".join(str(value) for value in _sorted_ids(values))


def build_formal_report_payload(
    metadata: ReportMetadata,
    context: FormalReportContext,
    rules: tuple[FormalRuleFact, ...],
) -> ReportPayload:
    """从已持久化且已复核的规则/风险/引用构造固定三表负载。"""

    if type(metadata) is not ReportMetadata or type(context) is not FormalReportContext:
        raise ValueError("formal report metadata or context is invalid")
    if tuple(rule.rule_code for rule in rules) != RULE_CATALOG_CODES:
        raise ValueError("formal report requires the complete ordered rule catalog")
    risk_by_rule = {risk.rule_code: risk for risk in context.risks}
    if len(risk_by_rule) != len(context.risks):
        raise ValueError("formal report permits at most one risk per rule")
    citations_by_risk: dict[UUID, tuple[FormalCitation, ...]] = {}
    for review in context.risks:
        citations_by_risk[review.risk_id] = tuple(
            citation for citation in context.citations if citation.risk_id == review.risk_id
        )
    rule_rows: list[tuple[ReportCellInput, ...]] = []
    risk_rows: list[tuple[ReportCellInput, ...]] = []
    summary_inputs: list[RiskSummaryInput] = []
    for rule in rules:
        matching_risk = risk_by_rule.get(rule.rule_code)
        if (rule.disposition is RulePreviewDisposition.HIT) != (matching_risk is not None):
            raise ValueError("formal report rule and risk facts differ")
        references = rule.included_item_ids
        if matching_risk is not None:
            citations = citations_by_risk[matching_risk.risk_id]
            references = _sorted_ids(
                references
                + tuple(
                    identity
                    for citation in citations
                    for identity in (
                        citation.policy_document_id,
                        citation.markdown_version_id,
                        citation.chunk_id,
                        citation.index_version_id,
                    )
                )
            )
            summary_inputs.append(
                RiskSummaryInput(
                    risk_id=matching_risk.risk_id,
                    original_level=matching_risk.original_level,
                    effective_level=matching_risk.effective_level,
                    review_status=matching_risk.review_status,
                )
            )
            risk_rows.append(
                (
                    str(matching_risk.risk_id),
                    rule.rule_code,
                    matching_risk.original_level.value,
                    matching_risk.effective_level.value,
                    matching_risk.review_status.value,
                    matching_risk.actual_value,
                    matching_risk.expected_value,
                    _reference_text(references),
                )
            )
        rule_rows.append(
            (
                rule.rule_code,
                rule.status.value,
                rule.disposition.value,
                rule.actual_value,
                rule.expected_value,
                None if matching_risk is None else str(matching_risk.risk_id),
                None if matching_risk is None else matching_risk.original_level.value,
                _reference_text(references),
            )
        )
    calculated = calculate_risk_summary(tuple(summary_inputs))
    payload = ReportPayload(
        metadata=metadata,
        preview_id=context.execution_id,
        ai_status=AiPreviewStatus.DISABLED.value,
        summary=ReportSummary(
            overall_level=calculated.overall_level.value,
            active_risk_count=calculated.active_risk_count,
            dismissed_risk_count=calculated.dismissed_risk_count,
            has_effective_high=calculated.has_effective_high,
            has_unreviewed_high=calculated.has_unreviewed_high,
        ),
        rules=ReportTable(columns=RULE_TABLE_COLUMNS, rows=tuple(rule_rows)),
        risks=ReportTable(columns=RISK_TABLE_COLUMNS, rows=tuple(risk_rows)),
    )
    validate_formal_report_payload(payload)
    return payload


def formal_report_payload_json_bytes(
    payload: ReportPayload,
    context: FormalReportContext,
) -> bytes:
    """序列化正式负载与复核/证据上下文，作为不可变 payload hash 输入。"""

    validate_formal_report_payload(payload)
    if type(context) is not FormalReportContext or context.execution_id != payload.preview_id:
        raise ValueError("formal report context does not match the payload")
    payload_document = json.loads(report_payload_json_bytes(payload))
    document = {
        "profile": "formal-report-runtime-v1",
        "payload": payload_document,
        "context": {
            "task_id": str(context.task_id),
            "task_no": context.task_no,
            "task_name": context.task_name,
            "execution_id": str(context.execution_id),
            "execution_version": context.execution_version,
            "baseline_date": context.baseline_date.isoformat(),
            "finance_reviewer_id": str(context.finance_reviewer_id),
            "finance_reviewed_at": context.finance_reviewed_at.isoformat().replace("+00:00", "Z"),
            "audit_reviewer_id": (
                None if context.audit_reviewer_id is None else str(context.audit_reviewer_id)
            ),
            "audit_reviewed_at": (
                None
                if context.audit_reviewed_at is None
                else context.audit_reviewed_at.isoformat().replace("+00:00", "Z")
            ),
            "risk_reviews": [
                {
                    "risk_id": str(risk.risk_id),
                    "reviewed_by": str(risk.reviewed_by),
                    "reviewed_at": risk.reviewed_at.isoformat().replace("+00:00", "Z"),
                    "review_status": risk.review_status.value,
                    "review_reason": risk.review_reason,
                }
                for risk in context.risks
            ],
            "citations": [
                {
                    "risk_id": str(citation.risk_id),
                    "policy_document_id": str(citation.policy_document_id),
                    "markdown_version_id": str(citation.markdown_version_id),
                    "chunk_id": str(citation.chunk_id),
                    "index_version_id": str(citation.index_version_id),
                    "start_page_no": citation.start_page_no,
                    "end_page_no": citation.end_page_no,
                    "title_path": list(citation.title_path),
                    "quote": citation.quote,
                    "content_sha256": citation.content_sha256,
                }
                for citation in context.citations
            ],
        },
    }
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "FormalCitation",
    "FormalReportContext",
    "FormalRiskFact",
    "FormalRuleFact",
    "build_formal_report_payload",
    "formal_report_payload_json_bytes",
]
