"""审核执行快照的严格 JSON 边界和多发票规则聚合。"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.audit.offline_preview import (
    OfflineAuditFacts,
    OfflineAuditPreview,
    RuleMetadata,
    RulePreviewDisposition,
    RulePreviewResult,
    build_offline_audit_preview,
)
from app.audit.risk_summary import (
    RiskLevel,
    RiskReviewStatus,
    RiskSummaryInput,
    calculate_risk_summary,
)
from app.audit.rule_catalog import RULE_CATALOG_CODES
from app.audit.rule_predicates import RuleExecutionStatus

LowerHexSha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _parse_uuid(value: object) -> object:
    if type(value) is UUID:
        return value
    if type(value) is not str:
        raise ValueError("identifier must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("identifier must be a canonical UUID") from None
    if str(parsed) != value:
        raise ValueError("identifier must be a canonical UUID")
    return parsed


def _parse_date(value: object) -> object:
    if type(value) is date:
        return value
    if type(value) is not str:
        raise ValueError("date must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("date must use YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise ValueError("date must use YYYY-MM-DD")
    return parsed


def _parse_decimal(value: object) -> object:
    if value is None or type(value) is Decimal:
        return value
    if type(value) is not str:
        raise ValueError("decimal must use a finite canonical string")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError("decimal must use a finite canonical string") from None
    if not parsed.is_finite() or format(parsed, "f") != value:
        raise ValueError("decimal must use a finite canonical string")
    return parsed


class SnapshotInvoiceFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    invoice_id: UUID
    critical_fact_hash: LowerHexSha256
    invoice_code: str | None
    invoice_number: str | None
    invoice_type: str | None
    invoice_date: date | None
    buyer_name: str | None
    buyer_tax_no: str | None
    seller_name: str | None
    seller_tax_no: str | None
    amount_excluding_tax: Decimal | None
    tax_amount: Decimal | None
    total_amount: Decimal | None
    line_net_amount: Decimal | None
    currency: str
    duplicate_status: str
    has_existing_exact_invoice_identity: bool | None
    is_red_invoice: bool | None
    included_in_cumulative_total: bool
    cumulative_exclusion_reason: str | None
    row_version: int = Field(ge=1)

    @field_validator("invoice_id", mode="before")
    @classmethod
    def parse_uuid(cls, value: object) -> object:
        return _parse_uuid(value)

    @field_validator("invoice_date", mode="before")
    @classmethod
    def parse_date(cls, value: object) -> object:
        if value is None:
            return None
        return _parse_date(value)

    @field_validator(
        "amount_excluding_tax",
        "tax_amount",
        "total_amount",
        "line_net_amount",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        return _parse_decimal(value)

    @model_validator(mode="after")
    def validate_cumulative_reason(self) -> SnapshotInvoiceFacts:
        if self.included_in_cumulative_total == (self.cumulative_exclusion_reason is not None):
            raise ValueError("cumulative inclusion and exclusion reason are inconsistent")
        return self


class AuditSnapshotFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    organization_id: UUID
    task_id: UUID
    execution_id: UUID
    baseline_date: date
    organization_tax_number: str = Field(min_length=1, max_length=32)
    contract_id: UUID | None
    contract_critical_fact_hash: LowerHexSha256 | None
    contract_no: str | None
    contract_party_a_name: str | None
    contract_party_a_tax_no: str | None
    contract_party_b_name: str | None
    contract_party_b_tax_no: str | None
    effective_contract_amount: Decimal | None
    contract_currency: str | None
    contract_effective_date: date | None
    contract_expiry_date: date | None
    contract_subjects_present: bool
    has_effective_unconfirmed_supplementary_agreement: bool
    cumulative_invoice_total: Decimal | None
    requires_policy_citation: bool
    retrieval_completed_successfully: bool
    has_applicable_policy_citation: bool
    invoices: tuple[SnapshotInvoiceFacts, ...] = Field(min_length=1, max_length=100)

    @field_validator("organization_id", "task_id", "execution_id", "contract_id", mode="before")
    @classmethod
    def parse_uuid(cls, value: object) -> object:
        if value is None:
            return None
        return _parse_uuid(value)

    @field_validator(
        "baseline_date", "contract_effective_date", "contract_expiry_date", mode="before"
    )
    @classmethod
    def parse_date(cls, value: object) -> object:
        if value is None:
            return None
        return _parse_date(value)

    @field_validator("effective_contract_amount", "cumulative_invoice_total", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        return _parse_decimal(value)

    @field_validator("invoices", mode="before")
    @classmethod
    def parse_invoices(cls, value: object) -> object:
        return tuple(value) if type(value) is list else value

    @model_validator(mode="after")
    def validate_parent_and_contract_matrix(self) -> AuditSnapshotFacts:
        invoice_ids = tuple(invoice.invoice_id for invoice in self.invoices)
        if len(set(invoice_ids)) != len(invoice_ids) or invoice_ids != tuple(
            sorted(invoice_ids, key=lambda value: value.bytes)
        ):
            raise ValueError("snapshot invoices must be sorted and unique")
        contract_fields = (
            self.contract_critical_fact_hash,
            self.contract_no,
            self.contract_party_a_name,
            self.contract_party_a_tax_no,
            self.contract_party_b_name,
            self.contract_party_b_tax_no,
            self.effective_contract_amount,
            self.contract_currency,
            self.contract_effective_date,
            self.contract_expiry_date,
        )
        if self.contract_id is None and any(value is not None for value in contract_fields):
            raise ValueError("no-contract snapshot contains contract facts")
        if self.contract_id is not None and self.contract_critical_fact_hash is None:
            raise ValueError("contract snapshot requires a critical fact hash")
        if self.retrieval_completed_successfully is False and self.has_applicable_policy_citation:
            raise ValueError("failed retrieval cannot contain an applicable citation")
        included = tuple(
            invoice.total_amount
            for invoice in self.invoices
            if invoice.included_in_cumulative_total
        )
        if any(value is None for value in included):
            raise ValueError("included invoice total is missing")
        expected_total = sum((value for value in included if value is not None), Decimal("0"))
        if self.cumulative_invoice_total != expected_total:
            raise ValueError("cumulative invoice total does not match included invoices")
        return self


def snapshot_json_document(snapshot: AuditSnapshotFacts) -> dict[str, object]:
    return snapshot.model_dump(mode="json")


def snapshot_sha256(snapshot: AuditSnapshotFacts) -> str:
    payload = json.dumps(
        snapshot_json_document(snapshot),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def offline_facts_for_invoice(
    snapshot: AuditSnapshotFacts,
    invoice: SnapshotInvoiceFacts,
) -> OfflineAuditFacts:
    has_contract = snapshot.contract_id is not None
    return OfflineAuditFacts(
        preview_id=snapshot.execution_id,
        has_confirmed_primary_contract=has_contract,
        contract_party_b_tax_no=snapshot.contract_party_b_tax_no,
        invoice_seller_tax_no=invoice.seller_tax_no,
        organization_tax_number=snapshot.organization_tax_number,
        invoice_buyer_tax_no=invoice.buyer_tax_no,
        cumulative_invoice_total=snapshot.cumulative_invoice_total,
        effective_contract_amount=snapshot.effective_contract_amount,
        invoice_date=invoice.invoice_date,
        contract_effective_date=snapshot.contract_effective_date,
        contract_expiry_date=snapshot.contract_expiry_date,
        has_existing_exact_invoice_identity=invoice.has_existing_exact_invoice_identity,
        contract_subjects_present=snapshot.contract_subjects_present,
        contract_amount_present=snapshot.effective_contract_amount is not None,
        contract_currency_present=snapshot.contract_currency is not None,
        contract_effective_date_present=snapshot.contract_effective_date is not None,
        invoice_code=invoice.invoice_code,
        invoice_number=invoice.invoice_number,
        invoice_total_amount=invoice.total_amount,
        contract_currency=snapshot.contract_currency,
        invoice_currency=invoice.currency,
        invoice_line_net_amount=invoice.line_net_amount,
        invoice_tax_amount=invoice.tax_amount,
        contract_no=snapshot.contract_no,
        has_effective_unconfirmed_supplementary_agreement=(
            snapshot.has_effective_unconfirmed_supplementary_agreement
        ),
        requires_policy_citation=snapshot.requires_policy_citation,
        retrieval_completed_successfully=snapshot.retrieval_completed_successfully,
        has_applicable_policy_citation=snapshot.has_applicable_policy_citation,
        standard_name_a=snapshot.contract_party_b_name,
        standard_name_b=invoice.seller_name,
        tax_identity_a=snapshot.contract_party_b_tax_no,
        tax_identity_b=invoice.seller_tax_no,
        is_red_invoice=invoice.is_red_invoice,
    )


def _aggregate_text(
    selected: tuple[tuple[UUID, RulePreviewResult], ...],
    *,
    attribute: Literal["actual_value", "expected_value"],
) -> str | None:
    values = tuple(
        value
        for _, result in selected
        if (
            value := (result.actual_value if attribute == "actual_value" else result.expected_value)
        )
        is not None
    )
    if not values:
        return None
    unique_values = tuple(dict.fromkeys(values))
    if len(selected) == 1 and len(unique_values) == 1:
        return unique_values[0]
    if attribute == "actual_value":
        return f"affected_invoice_count={len(selected)}"
    return unique_values[0] if len(unique_values) == 1 else "multiple_expected_values"


def build_aggregate_audit_preview(
    snapshot: AuditSnapshotFacts,
    rule_levels: dict[str, RiskLevel],
) -> OfflineAuditPreview:
    """逐发票执行纯谓词，再按规则以 hit 优先聚合为固定 15 行。"""

    if set(rule_levels) != set(RULE_CATALOG_CODES):
        raise ValueError("rule levels must contain the complete builtin catalog")
    previews: list[tuple[UUID, OfflineAuditPreview]] = []
    for invoice in snapshot.invoices:
        references = tuple(
            sorted(
                (
                    {invoice.invoice_id}
                    if snapshot.contract_id is None
                    else {invoice.invoice_id, snapshot.contract_id}
                ),
                key=lambda value: value.bytes,
            )
        )
        metadata = tuple(
            RuleMetadata(rule_code, rule_levels[rule_code], references)
            for rule_code in RULE_CATALOG_CODES
        )
        previews.append(
            (
                invoice.invoice_id,
                build_offline_audit_preview(offline_facts_for_invoice(snapshot, invoice), metadata),
            )
        )

    rules: list[RulePreviewResult] = []
    risks: list[RiskSummaryInput] = []
    priority = (
        RulePreviewDisposition.HIT,
        RulePreviewDisposition.MISSING,
        RulePreviewDisposition.NOT_HIT,
        RulePreviewDisposition.NOT_APPLICABLE,
    )
    status_by_disposition = {
        RulePreviewDisposition.HIT: RuleExecutionStatus.FAILED,
        RulePreviewDisposition.MISSING: RuleExecutionStatus.NOT_APPLICABLE,
        RulePreviewDisposition.NOT_HIT: RuleExecutionStatus.PASSED,
        RulePreviewDisposition.NOT_APPLICABLE: RuleExecutionStatus.NOT_APPLICABLE,
    }
    for index, rule_code in enumerate(RULE_CATALOG_CODES):
        candidates = tuple((invoice_id, preview.rules[index]) for invoice_id, preview in previews)
        disposition = next(
            item for item in priority if any(rule.disposition is item for _, rule in candidates)
        )
        selected = tuple(
            (invoice_id, rule) for invoice_id, rule in candidates if rule.disposition is disposition
        )
        references = tuple(
            sorted(
                {reference for _, result in selected for reference in result.reference_ids},
                key=lambda value: value.bytes,
            )
        )
        risk_id = selected[0][1].risk_id if disposition is RulePreviewDisposition.HIT else None
        risk_level = rule_levels[rule_code] if risk_id is not None else None
        result = RulePreviewResult(
            rule_id=rule_code,
            status=status_by_disposition[disposition],
            disposition=disposition,
            actual_value=_aggregate_text(selected, attribute="actual_value"),
            expected_value=_aggregate_text(selected, attribute="expected_value"),
            risk_id=risk_id,
            risk_level=risk_level,
            reference_ids=references,
        )
        rules.append(result)
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
        preview_id=snapshot.execution_id,
        rules=tuple(rules),
        risks=frozen_risks,
        summary=calculate_risk_summary(frozen_risks),
    )


__all__ = [
    "AuditSnapshotFacts",
    "SnapshotInvoiceFacts",
    "build_aggregate_audit_preview",
    "offline_facts_for_invoice",
    "snapshot_json_document",
    "snapshot_sha256",
]
