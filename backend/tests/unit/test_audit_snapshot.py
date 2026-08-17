from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.audit.risk_summary import RiskLevel
from app.audit.rule_catalog import BUILTIN_AUDIT_RULES, RULE_CATALOG_CODES
from app.audit.snapshot import (
    AuditSnapshotFacts,
    SnapshotInvoiceFacts,
    build_aggregate_audit_preview,
    snapshot_json_document,
    snapshot_sha256,
)

_RULE_LEVELS = {rule.rule_code: rule.default_risk_level for rule in BUILTIN_AUDIT_RULES}


def _invoice(invoice_id: int, *, total_amount: str) -> SnapshotInvoiceFacts:
    return SnapshotInvoiceFacts(
        invoice_id=UUID(int=invoice_id),
        critical_fact_hash="1" * 64,
        invoice_code=f"CODE-{invoice_id}",
        invoice_number=f"NUMBER-{invoice_id}",
        invoice_type="vat_special",
        invoice_date=date(2026, 6, invoice_id),
        buyer_name="测试企业",
        buyer_tax_no="BUYER-TAX",
        seller_name="供应商",
        seller_tax_no="SELLER-TAX",
        amount_excluding_tax=Decimal(total_amount),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal(total_amount),
        line_net_amount=Decimal(total_amount),
        currency="CNY",
        duplicate_status="unique",
        has_existing_exact_invoice_identity=False,
        is_red_invoice=False,
        included_in_cumulative_total=True,
        cumulative_exclusion_reason=None,
        row_version=1,
    )


def _snapshot() -> AuditSnapshotFacts:
    invoices = (_invoice(10, total_amount="60.00"), _invoice(20, total_amount="60.00"))
    return AuditSnapshotFacts(
        schema_version=1,
        organization_id=UUID(int=1),
        task_id=UUID(int=2),
        execution_id=UUID(int=3),
        baseline_date=date(2026, 6, 30),
        organization_tax_number="BUYER-TAX",
        contract_id=UUID(int=4),
        contract_critical_fact_hash="2" * 64,
        contract_no="CONTRACT-001",
        contract_party_a_name="测试企业",
        contract_party_a_tax_no="BUYER-TAX",
        contract_party_b_name="供应商",
        contract_party_b_tax_no="SELLER-TAX",
        effective_contract_amount=Decimal("100.00"),
        contract_currency="CNY",
        contract_effective_date=date(2026, 1, 1),
        contract_expiry_date=date(2026, 12, 31),
        contract_subjects_present=True,
        has_effective_unconfirmed_supplementary_agreement=False,
        cumulative_invoice_total=Decimal("120.00"),
        requires_policy_citation=False,
        retrieval_completed_successfully=False,
        has_applicable_policy_citation=False,
        invoices=invoices,
    )


def test_snapshot_json_round_trip_and_hash_are_canonical() -> None:
    snapshot = _snapshot()

    document = snapshot_json_document(snapshot)
    restored = AuditSnapshotFacts.model_validate(document)

    assert restored == snapshot
    assert snapshot_sha256(restored) == snapshot_sha256(snapshot)
    assert len(snapshot_sha256(snapshot)) == 64
    assert document["effective_contract_amount"] == "100.00"


def test_multi_invoice_preview_has_fixed_rules_and_one_aggregate_risk_per_rule() -> None:
    snapshot = _snapshot()

    preview = build_aggregate_audit_preview(snapshot, _RULE_LEVELS)

    assert tuple(rule.rule_id for rule in preview.rules) == RULE_CATALOG_CODES
    overage = next(rule for rule in preview.rules if rule.rule_id == "RULE-003")
    assert overage.actual_value == "affected_invoice_count=2"
    assert overage.expected_value == "100.00"
    assert overage.risk_level is RiskLevel.HIGH
    assert overage.reference_ids == (UUID(int=4), UUID(int=10), UUID(int=20))
    assert sum(risk.risk_id == overage.risk_id for risk in preview.risks) == 1


@pytest.mark.parametrize(
    "mutation",
    (
        {"effective_contract_amount": 100.0},
        {"cumulative_invoice_total": "119.99"},
        {"invoices": [_invoice(20, total_amount="60.00"), _invoice(10, total_amount="60.00")]},
        {"unexpected": "field"},
    ),
)
def test_snapshot_rejects_noncanonical_or_inconsistent_facts(
    mutation: dict[str, object],
) -> None:
    document = snapshot_json_document(_snapshot())
    document.update(mutation)

    with pytest.raises(ValidationError):
        AuditSnapshotFacts.model_validate(document)
