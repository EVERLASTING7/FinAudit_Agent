"""MVP-VS-04 的确定性离线审核预览组合服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid5

from app.audit.risk_summary import (
    RiskLevel,
    RiskReviewStatus,
    RiskSummary,
    RiskSummaryInput,
    calculate_risk_summary,
)
from app.audit.rule_predicates import (
    RuleExecutionStatus,
    evaluate_rule_001,
    evaluate_rule_002,
    evaluate_rule_003,
    evaluate_rule_004,
    evaluate_rule_005,
    evaluate_rule_006,
    evaluate_rule_007,
    evaluate_rule_008_currency_pair,
    evaluate_rule_009,
    evaluate_rule_010,
    evaluate_rule_011,
    evaluate_rule_012,
    evaluate_rule_013,
    evaluate_rule_014_identity_pair,
    evaluate_rule_015,
)

_RULE_IDS = tuple(f"RULE-{number:03d}" for number in range(1, 16))
_MISSING_VALUE = "<missing>"
_ALL_PRESENT = "all_present"


class RulePreviewDisposition(str, Enum):
    """离线预览对谓词结果补充的四态业务解释。"""

    HIT = "hit"
    NOT_HIT = "not_hit"
    NOT_APPLICABLE = "not_applicable"
    MISSING = "missing"


class AiPreviewStatus(str, Enum):
    """离线预览固定关闭 Provider 调用。"""

    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class RuleMetadata:
    """由调用方显式提供、仅供本次离线预览使用的规则元数据。"""

    rule_id: str
    risk_level: RiskLevel
    reference_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if type(self.rule_id) is not str or not self.rule_id.strip():
            raise ValueError("rule_id must be a non-blank exact str")
        if type(self.risk_level) is not RiskLevel:
            raise ValueError("risk_level must be a RiskLevel")
        if type(self.reference_ids) is not tuple or any(
            type(reference_id) is not UUID for reference_id in self.reference_ids
        ):
            raise ValueError("reference_ids must be a tuple of UUID")
        canonical_reference_ids = tuple(
            sorted(set(self.reference_ids), key=lambda reference_id: reference_id.bytes)
        )
        object.__setattr__(self, "reference_ids", canonical_reference_ids)


def _validate_exact_bool(value: object, *, name: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be an exact bool")


def _validate_optional_exact_bool(value: object, *, name: str) -> None:
    if value is not None and type(value) is not bool:
        raise ValueError(f"{name} must be an exact bool or None")


def _validate_non_blank_text(value: object, *, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-blank exact str")


def _validate_optional_non_blank_text(value: object, *, name: str) -> None:
    if value is not None and (type(value) is not str or not value.strip()):
        raise ValueError(f"{name} must be a non-blank exact str or None")


def _validate_optional_date(value: object, *, name: str) -> None:
    if value is not None and type(value) is not date:
        raise ValueError(f"{name} must be an exact datetime.date or None")


def _validate_optional_decimal(value: object, *, name: str) -> None:
    if value is not None and (type(value) is not Decimal or not value.is_finite()):
        raise ValueError(f"{name} must be a finite exact Decimal or None")


@dataclass(frozen=True, slots=True)
class OfflineAuditFacts:
    """现有十五条纯谓词所需的冻结、已规范化调用方事实。"""

    preview_id: UUID
    has_confirmed_primary_contract: bool = field(repr=False)
    contract_party_b_tax_no: str | None = field(repr=False)
    invoice_seller_tax_no: str | None = field(repr=False)
    organization_tax_number: str = field(repr=False)
    invoice_buyer_tax_no: str | None = field(repr=False)
    cumulative_invoice_total: Decimal | None = field(repr=False)
    effective_contract_amount: Decimal | None = field(repr=False)
    invoice_date: date | None = field(repr=False)
    contract_effective_date: date | None = field(repr=False)
    contract_expiry_date: date | None = field(repr=False)
    has_existing_exact_invoice_identity: bool | None = field(repr=False)
    contract_subjects_present: bool = field(repr=False)
    contract_amount_present: bool = field(repr=False)
    contract_currency_present: bool = field(repr=False)
    contract_effective_date_present: bool = field(repr=False)
    invoice_code: str | None = field(repr=False)
    invoice_number: str | None = field(repr=False)
    invoice_total_amount: Decimal | None = field(repr=False)
    contract_currency: str | None = field(repr=False)
    invoice_currency: str | None = field(repr=False)
    invoice_line_net_amount: Decimal | None = field(repr=False)
    invoice_tax_amount: Decimal | None = field(repr=False)
    contract_no: str | None = field(repr=False)
    has_effective_unconfirmed_supplementary_agreement: bool = field(repr=False)
    requires_policy_citation: bool = field(repr=False)
    retrieval_completed_successfully: bool = field(repr=False)
    has_applicable_policy_citation: bool = field(repr=False)
    standard_name_a: str | None = field(repr=False)
    standard_name_b: str | None = field(repr=False)
    tax_identity_a: str | None = field(repr=False)
    tax_identity_b: str | None = field(repr=False)
    is_red_invoice: bool | None = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.preview_id) is not UUID:
            raise ValueError("preview_id must be an exact UUID")
        for name, bool_value in (
            ("has_confirmed_primary_contract", self.has_confirmed_primary_contract),
            ("contract_subjects_present", self.contract_subjects_present),
            ("contract_amount_present", self.contract_amount_present),
            ("contract_currency_present", self.contract_currency_present),
            ("contract_effective_date_present", self.contract_effective_date_present),
            (
                "has_effective_unconfirmed_supplementary_agreement",
                self.has_effective_unconfirmed_supplementary_agreement,
            ),
            ("requires_policy_citation", self.requires_policy_citation),
            ("retrieval_completed_successfully", self.retrieval_completed_successfully),
            ("has_applicable_policy_citation", self.has_applicable_policy_citation),
        ):
            _validate_exact_bool(bool_value, name=name)
        _validate_optional_exact_bool(
            self.has_existing_exact_invoice_identity,
            name="has_existing_exact_invoice_identity",
        )
        _validate_optional_exact_bool(self.is_red_invoice, name="is_red_invoice")
        _validate_non_blank_text(
            self.organization_tax_number,
            name="organization_tax_number",
        )
        for name, text_value in (
            ("contract_party_b_tax_no", self.contract_party_b_tax_no),
            ("invoice_seller_tax_no", self.invoice_seller_tax_no),
            ("invoice_buyer_tax_no", self.invoice_buyer_tax_no),
            ("invoice_code", self.invoice_code),
            ("invoice_number", self.invoice_number),
            ("contract_currency", self.contract_currency),
            ("invoice_currency", self.invoice_currency),
            ("contract_no", self.contract_no),
            ("standard_name_a", self.standard_name_a),
            ("standard_name_b", self.standard_name_b),
            ("tax_identity_a", self.tax_identity_a),
            ("tax_identity_b", self.tax_identity_b),
        ):
            _validate_optional_non_blank_text(text_value, name=name)
        for name, date_value in (
            ("invoice_date", self.invoice_date),
            ("contract_effective_date", self.contract_effective_date),
            ("contract_expiry_date", self.contract_expiry_date),
        ):
            _validate_optional_date(date_value, name=name)
        if (
            self.contract_effective_date is not None
            and self.contract_expiry_date is not None
            and self.contract_effective_date > self.contract_expiry_date
        ):
            raise ValueError("contract effective date must not be after expiry date")
        for name, decimal_value in (
            ("cumulative_invoice_total", self.cumulative_invoice_total),
            ("effective_contract_amount", self.effective_contract_amount),
            ("invoice_total_amount", self.invoice_total_amount),
            ("invoice_line_net_amount", self.invoice_line_net_amount),
            ("invoice_tax_amount", self.invoice_tax_amount),
        ):
            _validate_optional_decimal(decimal_value, name=name)
        for presence_name, is_present, value_name, value in (
            (
                "contract_amount_present",
                self.contract_amount_present,
                "effective_contract_amount",
                self.effective_contract_amount,
            ),
            (
                "contract_currency_present",
                self.contract_currency_present,
                "contract_currency",
                self.contract_currency,
            ),
            (
                "contract_effective_date_present",
                self.contract_effective_date_present,
                "contract_effective_date",
                self.contract_effective_date,
            ),
        ):
            if is_present is not (value is not None):
                raise ValueError(f"{presence_name} must match whether {value_name} is present")


@dataclass(frozen=True, slots=True)
class RulePreviewResult:
    """单条规则的冻结预览结果。"""

    rule_id: str
    status: RuleExecutionStatus
    disposition: RulePreviewDisposition
    actual_value: str | None = field(repr=False)
    expected_value: str | None = field(repr=False)
    risk_id: UUID | None
    risk_level: RiskLevel | None
    reference_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if type(self.rule_id) is not str or not self.rule_id.strip():
            raise ValueError("rule_id must be a non-blank exact str")
        if type(self.status) is not RuleExecutionStatus:
            raise ValueError("status must be a RuleExecutionStatus")
        if type(self.disposition) is not RulePreviewDisposition:
            raise ValueError("disposition must be a RulePreviewDisposition")
        for name, value in (
            ("actual_value", self.actual_value),
            ("expected_value", self.expected_value),
        ):
            if value is not None and type(value) is not str:
                raise ValueError(f"{name} must be an exact str or None")
        if self.risk_id is not None and type(self.risk_id) is not UUID:
            raise ValueError("risk_id must be an exact UUID or None")
        if self.risk_level is not None and type(self.risk_level) is not RiskLevel:
            raise ValueError("risk_level must be a RiskLevel or None")
        if type(self.reference_ids) is not tuple or any(
            type(reference_id) is not UUID for reference_id in self.reference_ids
        ):
            raise ValueError("reference_ids must be a tuple of UUID")
        if self.reference_ids != tuple(
            sorted(set(self.reference_ids), key=lambda reference_id: reference_id.bytes)
        ):
            raise ValueError("reference_ids must be sorted and unique")

        expected_status = {
            RulePreviewDisposition.HIT: RuleExecutionStatus.FAILED,
            RulePreviewDisposition.NOT_HIT: RuleExecutionStatus.PASSED,
            RulePreviewDisposition.NOT_APPLICABLE: RuleExecutionStatus.NOT_APPLICABLE,
            RulePreviewDisposition.MISSING: RuleExecutionStatus.NOT_APPLICABLE,
        }[self.disposition]
        if self.status is not expected_status:
            raise ValueError("status must match disposition")
        if self.disposition is RulePreviewDisposition.HIT:
            if self.risk_id is None or self.risk_level is None:
                raise ValueError("hit results require risk identity and level")
            if self.actual_value is None or self.expected_value is None:
                raise ValueError("hit results require actual and expected values")
        elif self.risk_id is not None or self.risk_level is not None:
            raise ValueError("non-hit results must not contain risk identity or level")


@dataclass(frozen=True, slots=True)
class OfflineAuditPreview:
    """确定性规则、风险汇总与固定 AI 降级状态。"""

    preview_id: UUID
    rules: tuple[RulePreviewResult, ...]
    risks: tuple[RiskSummaryInput, ...]
    summary: RiskSummary
    ai_status: AiPreviewStatus = field(default=AiPreviewStatus.DISABLED, init=False)

    def __post_init__(self) -> None:
        if type(self.preview_id) is not UUID:
            raise ValueError("preview_id must be an exact UUID")
        if type(self.rules) is not tuple or any(
            type(rule) is not RulePreviewResult for rule in self.rules
        ):
            raise ValueError("rules must be a tuple of RulePreviewResult")
        if tuple(rule.rule_id for rule in self.rules) != _RULE_IDS:
            raise ValueError("rules must contain the stable RULE-001 through RULE-015 order")
        if type(self.risks) is not tuple or any(
            type(risk) is not RiskSummaryInput for risk in self.risks
        ):
            raise ValueError("risks must be a tuple of RiskSummaryInput")
        if type(self.summary) is not RiskSummary:
            raise ValueError("summary must be a RiskSummary")
        if calculate_risk_summary(self.risks) != self.summary:
            raise ValueError("summary must match risks")
        hit_rules = tuple(
            rule for rule in self.rules if rule.disposition is RulePreviewDisposition.HIT
        )
        if tuple(rule.risk_id for rule in hit_rules) != tuple(risk.risk_id for risk in self.risks):
            raise ValueError("risks must follow hit rule order")
        if any(
            risk.original_level is not rule.risk_level
            or risk.effective_level is not rule.risk_level
            or risk.review_status is not RiskReviewStatus.PENDING
            for rule, risk in zip(hit_rules, self.risks, strict=True)
        ):
            raise ValueError("risks must match hit rule levels and pending review status")


def _evaluate_rule_statuses(facts: OfflineAuditFacts) -> dict[str, RuleExecutionStatus]:
    rule_004_status = evaluate_rule_004(
        facts.invoice_date,
        facts.contract_effective_date,
        facts.contract_expiry_date,
    ).status
    if not facts.has_confirmed_primary_contract:
        rule_004_status = RuleExecutionStatus.NOT_APPLICABLE

    return {
        "RULE-001": evaluate_rule_001(
            facts.has_confirmed_primary_contract,
            facts.contract_party_b_tax_no,
            facts.invoice_seller_tax_no,
        ).status,
        "RULE-002": evaluate_rule_002(
            facts.organization_tax_number,
            facts.invoice_buyer_tax_no,
        ).status,
        "RULE-003": evaluate_rule_003(
            facts.has_confirmed_primary_contract,
            facts.cumulative_invoice_total,
            facts.effective_contract_amount,
        ).status,
        "RULE-004": rule_004_status,
        "RULE-005": evaluate_rule_005(facts.has_existing_exact_invoice_identity).status,
        "RULE-006": evaluate_rule_006(
            facts.has_confirmed_primary_contract,
            facts.contract_subjects_present,
            facts.contract_amount_present,
            facts.contract_currency_present,
            facts.contract_effective_date_present,
        ).status,
        "RULE-007": evaluate_rule_007(
            facts.invoice_code,
            facts.invoice_number,
            facts.invoice_buyer_tax_no,
            facts.invoice_seller_tax_no,
            facts.invoice_date,
            facts.invoice_total_amount,
        ).status,
        "RULE-008": evaluate_rule_008_currency_pair(
            facts.has_confirmed_primary_contract,
            facts.contract_currency,
            facts.invoice_currency,
        ).status,
        "RULE-009": evaluate_rule_009(
            facts.invoice_line_net_amount,
            facts.invoice_tax_amount,
            facts.invoice_total_amount,
        ).status,
        "RULE-010": evaluate_rule_010(facts.has_confirmed_primary_contract).status,
        "RULE-011": evaluate_rule_011(
            facts.has_confirmed_primary_contract,
            facts.contract_no,
        ).status,
        "RULE-012": evaluate_rule_012(
            facts.has_confirmed_primary_contract,
            facts.has_effective_unconfirmed_supplementary_agreement,
        ).status,
        "RULE-013": evaluate_rule_013(
            facts.requires_policy_citation,
            facts.retrieval_completed_successfully,
            facts.has_applicable_policy_citation,
        ).status,
        "RULE-014": evaluate_rule_014_identity_pair(
            facts.standard_name_a,
            facts.standard_name_b,
            facts.tax_identity_a,
            facts.tax_identity_b,
        ).status,
        "RULE-015": evaluate_rule_015(
            facts.invoice_total_amount,
            is_red_invoice=facts.is_red_invoice,
        ).status,
    }


def _is_missing(rule_id: str, facts: OfflineAuditFacts) -> bool:
    if rule_id == "RULE-001":
        return facts.has_confirmed_primary_contract and (
            facts.contract_party_b_tax_no is None or facts.invoice_seller_tax_no is None
        )
    if rule_id == "RULE-002":
        return facts.invoice_buyer_tax_no is None
    if rule_id == "RULE-003":
        return facts.has_confirmed_primary_contract and (
            facts.cumulative_invoice_total is None or facts.effective_contract_amount is None
        )
    if rule_id == "RULE-004":
        return facts.has_confirmed_primary_contract and (
            facts.invoice_date is None
            or facts.contract_effective_date is None
            or facts.contract_expiry_date is None
        )
    if rule_id == "RULE-005":
        return facts.has_existing_exact_invoice_identity is None
    if rule_id == "RULE-008":
        return facts.has_confirmed_primary_contract and (
            facts.contract_currency is None or facts.invoice_currency is None
        )
    if rule_id == "RULE-009":
        return (
            facts.invoice_line_net_amount is None
            or facts.invoice_tax_amount is None
            or facts.invoice_total_amount is None
        )
    if rule_id == "RULE-014":
        return any(
            value is None
            for value in (
                facts.standard_name_a,
                facts.standard_name_b,
                facts.tax_identity_a,
                facts.tax_identity_b,
            )
        )
    if rule_id == "RULE-015":
        return facts.invoice_total_amount is None or facts.is_red_invoice is None
    return False


def _disposition(
    rule_id: str,
    status: RuleExecutionStatus,
    facts: OfflineAuditFacts,
) -> RulePreviewDisposition:
    if _is_missing(rule_id, facts):
        return RulePreviewDisposition.MISSING
    if status is RuleExecutionStatus.FAILED:
        return RulePreviewDisposition.HIT
    if status is RuleExecutionStatus.PASSED:
        return RulePreviewDisposition.NOT_HIT
    return RulePreviewDisposition.NOT_APPLICABLE


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _date_text(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _bool_text(value: bool | None) -> str | None:
    if value is None:
        return None
    return "true" if value else "false"


def _presence_text(facts: tuple[tuple[str, object | None], ...]) -> str:
    missing = tuple(name for name, value in facts if value is None or value is False)
    return _ALL_PRESENT if not missing else f"missing:{','.join(missing)}"


def _contract_date_range_text(facts: OfflineAuditFacts) -> str | None:
    if facts.contract_effective_date is None or facts.contract_expiry_date is None:
        return None
    return f"{facts.contract_effective_date.isoformat()}..{facts.contract_expiry_date.isoformat()}"


def _invoice_amount_equation_text(facts: OfflineAuditFacts) -> str:
    amounts = (
        ("line_net_amount", facts.invoice_line_net_amount),
        ("tax_amount", facts.invoice_tax_amount),
        ("total_amount", facts.invoice_total_amount),
    )
    missing = tuple(name for name, value in amounts if value is None)
    if missing:
        return f"missing:{','.join(missing)}"
    return ";".join(f"{name}={value}" for name, value in amounts)


def _identity_comparison_text(facts: OfflineAuditFacts) -> str:
    values = (
        facts.standard_name_a,
        facts.standard_name_b,
        facts.tax_identity_a,
        facts.tax_identity_b,
    )
    if any(value is None for value in values):
        return _MISSING_VALUE
    return (
        f"name_equal={_bool_text(facts.standard_name_a == facts.standard_name_b)};"
        f"tax_identity_equal={_bool_text(facts.tax_identity_a == facts.tax_identity_b)}"
    )


def _actual_expected_values(
    facts: OfflineAuditFacts,
) -> dict[str, tuple[str | None, str | None]]:
    has_contract = facts.has_confirmed_primary_contract
    citation_check_applies = (
        facts.requires_policy_citation and facts.retrieval_completed_successfully
    )
    return {
        "RULE-001": (
            facts.invoice_seller_tax_no if has_contract else None,
            facts.contract_party_b_tax_no if has_contract else None,
        ),
        "RULE-002": (facts.invoice_buyer_tax_no, facts.organization_tax_number),
        "RULE-003": (
            _decimal_text(facts.cumulative_invoice_total) if has_contract else None,
            _decimal_text(facts.effective_contract_amount) if has_contract else None,
        ),
        "RULE-004": (
            _date_text(facts.invoice_date) if has_contract else None,
            _contract_date_range_text(facts) if has_contract else None,
        ),
        "RULE-005": (_bool_text(facts.has_existing_exact_invoice_identity), "false"),
        "RULE-006": (
            _presence_text(
                (
                    ("contract_subjects_present", facts.contract_subjects_present),
                    ("contract_amount_present", facts.contract_amount_present),
                    ("contract_currency_present", facts.contract_currency_present),
                    (
                        "contract_effective_date_present",
                        facts.contract_effective_date_present,
                    ),
                )
            )
            if has_contract
            else None,
            _ALL_PRESENT if has_contract else None,
        ),
        "RULE-007": (
            _presence_text(
                (
                    ("invoice_code", facts.invoice_code),
                    ("invoice_number", facts.invoice_number),
                    ("invoice_buyer_tax_no", facts.invoice_buyer_tax_no),
                    ("invoice_seller_tax_no", facts.invoice_seller_tax_no),
                    ("invoice_date", facts.invoice_date),
                    ("invoice_total_amount", facts.invoice_total_amount),
                )
            ),
            _ALL_PRESENT,
        ),
        "RULE-008": (
            facts.invoice_currency if has_contract else None,
            facts.contract_currency if has_contract else None,
        ),
        "RULE-009": (_invoice_amount_equation_text(facts), "absolute_difference<=0.01"),
        "RULE-010": (_bool_text(has_contract), "true"),
        "RULE-011": (
            (facts.contract_no or _MISSING_VALUE) if has_contract else None,
            "non_blank" if has_contract else None,
        ),
        "RULE-012": (
            _bool_text(facts.has_effective_unconfirmed_supplementary_agreement)
            if has_contract
            else None,
            "false" if has_contract else None,
        ),
        "RULE-013": (
            _bool_text(facts.has_applicable_policy_citation) if citation_check_applies else None,
            "true" if citation_check_applies else None,
        ),
        "RULE-014": (_identity_comparison_text(facts), "no_name_tax_identity_conflict"),
        "RULE-015": (
            _decimal_text(facts.invoice_total_amount) or _MISSING_VALUE,
            ">0" if facts.is_red_invoice is False else None,
        ),
    }


def _validate_metadata(metadata: tuple[RuleMetadata, ...]) -> dict[str, RuleMetadata]:
    if type(metadata) is not tuple or any(type(item) is not RuleMetadata for item in metadata):
        raise ValueError("metadata must be a tuple of RuleMetadata")
    rule_ids = tuple(item.rule_id for item in metadata)
    if len(rule_ids) != len(_RULE_IDS) or len(set(rule_ids)) != len(rule_ids):
        raise ValueError("metadata must contain each RULE-001 through RULE-015 exactly once")
    if set(rule_ids) != set(_RULE_IDS):
        raise ValueError("metadata must contain each RULE-001 through RULE-015 exactly once")
    return {item.rule_id: item for item in metadata}


def build_offline_audit_preview(
    facts: OfflineAuditFacts,
    metadata: tuple[RuleMetadata, ...],
) -> OfflineAuditPreview:
    """执行十五条确定性规则并生成固定 AI-disabled 的离线预览。"""

    if type(facts) is not OfflineAuditFacts:
        raise ValueError("facts must be an OfflineAuditFacts")
    metadata_by_rule_id = _validate_metadata(metadata)
    statuses = _evaluate_rule_statuses(facts)
    actual_expected = _actual_expected_values(facts)

    rules: list[RulePreviewResult] = []
    risks: list[RiskSummaryInput] = []
    for rule_id in _RULE_IDS:
        item_metadata = metadata_by_rule_id[rule_id]
        status = statuses[rule_id]
        disposition = _disposition(rule_id, status, facts)
        actual_value, expected_value = actual_expected[rule_id]
        risk_id = None
        risk_level = None
        if disposition is RulePreviewDisposition.HIT:
            risk_id = uuid5(facts.preview_id, rule_id)
            risk_level = item_metadata.risk_level
        rules.append(
            RulePreviewResult(
                rule_id=rule_id,
                status=status,
                disposition=disposition,
                actual_value=actual_value,
                expected_value=expected_value,
                risk_id=risk_id,
                risk_level=risk_level,
                reference_ids=item_metadata.reference_ids,
            )
        )
        if risk_id is not None and risk_level is not None:
            risks.append(
                RiskSummaryInput(
                    risk_id=risk_id,
                    original_level=risk_level,
                    effective_level=risk_level,
                    review_status=RiskReviewStatus.PENDING,
                )
            )

    frozen_risks = tuple(risks)
    return OfflineAuditPreview(
        preview_id=facts.preview_id,
        rules=tuple(rules),
        risks=frozen_risks,
        summary=calculate_risk_summary(frozen_risks),
    )
