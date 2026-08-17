from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import UUID, uuid5

import pytest

import app.audit.offline_preview as offline_preview_module
from app.audit.offline_preview import (
    AiPreviewStatus,
    OfflineAuditFacts,
    OfflineAuditPreview,
    RuleMetadata,
    RulePreviewDisposition,
    RulePreviewResult,
    build_offline_audit_preview,
)
from app.audit.risk_summary import RiskLevel, RiskReviewStatus, calculate_risk_summary
from app.audit.rule_predicates import RuleExecutionStatus

_PROJECT_ROOT = Path(__file__).parents[3]
_CORE_BUSINESS_PATH = _PROJECT_ROOT / "tests" / "fixtures" / "core_business.json"
_DEFAULT_PREVIEW_ID = UUID(int=500)
_RULE_IDS = tuple(f"RULE-{number:03d}" for number in range(1, 16))
_RULE_LEVELS = {
    "RULE-001": RiskLevel.HIGH,
    "RULE-002": RiskLevel.HIGH,
    "RULE-003": RiskLevel.HIGH,
    "RULE-004": RiskLevel.MEDIUM,
    "RULE-005": RiskLevel.HIGH,
    "RULE-006": RiskLevel.MEDIUM,
    "RULE-007": RiskLevel.MEDIUM,
    "RULE-008": RiskLevel.MEDIUM,
    "RULE-009": RiskLevel.MEDIUM,
    "RULE-010": RiskLevel.MEDIUM,
    "RULE-011": RiskLevel.NOTICE,
    "RULE-012": RiskLevel.MEDIUM,
    "RULE-013": RiskLevel.NOTICE,
    "RULE-014": RiskLevel.HIGH,
    "RULE-015": RiskLevel.MEDIUM,
}


def _core_business_items() -> dict[str, dict[str, object]]:
    document = json.loads(_CORE_BUSINESS_PATH.read_text(encoding="utf-8"))
    assert document["synthetic"] is True
    return {item["id"]: item for item in document["items"]}


def _metadata(order: tuple[str, ...] = _RULE_IDS) -> tuple[RuleMetadata, ...]:
    return tuple(
        RuleMetadata(
            rule_id=rule_id,
            risk_level=_RULE_LEVELS[rule_id],
            reference_ids=(UUID(int=1000 + int(rule_id[-3:])),),
        )
        for rule_id in order
    )


def _base_facts(*, preview_id: UUID = _DEFAULT_PREVIEW_ID) -> OfflineAuditFacts:
    items = _core_business_items()
    contract = items["C-001"]
    invoice_1 = items["I-001"]
    invoice_2 = items["I-002"]
    cumulative_total = Decimal(str(invoice_1["total_amount"])) + Decimal(
        str(invoice_2["total_amount"])
    )
    return OfflineAuditFacts(
        preview_id=preview_id,
        has_confirmed_primary_contract=True,
        contract_party_b_tax_no=str(contract["party_b_tax_id"]),
        invoice_seller_tax_no=str(invoice_2["seller_tax_id"]),
        organization_tax_number=str(contract["party_a_tax_id"]),
        invoice_buyer_tax_no=str(invoice_2["buyer_tax_id"]),
        cumulative_invoice_total=cumulative_total,
        effective_contract_amount=Decimal(str(contract["amount"])),
        invoice_date=date.fromisoformat(str(invoice_2["issue_date"])),
        contract_effective_date=date.fromisoformat(str(contract["effective_date"])),
        contract_expiry_date=date.fromisoformat(str(contract["expiry_date"])),
        has_existing_exact_invoice_identity=False,
        contract_subjects_present=True,
        contract_amount_present=True,
        contract_currency_present=True,
        contract_effective_date_present=True,
        invoice_code=str(invoice_2["invoice_code"]),
        invoice_number=str(invoice_2["invoice_number"]),
        invoice_total_amount=Decimal(str(invoice_2["total_amount"])),
        contract_currency=str(contract["currency"]),
        invoice_currency=str(invoice_2["currency"]),
        invoice_line_net_amount=None,
        invoice_tax_amount=None,
        contract_no=str(contract["contract_number"]),
        has_effective_unconfirmed_supplementary_agreement=False,
        requires_policy_citation=True,
        retrieval_completed_successfully=False,
        has_applicable_policy_citation=False,
        standard_name_a=str(contract["party_b_name"]),
        standard_name_b=str(contract["party_b_name"]),
        tax_identity_a=str(contract["party_b_tax_id"]),
        tax_identity_b=str(contract["party_b_tax_id"]),
        is_red_invoice=False,
    )


def _rule(preview: OfflineAuditPreview, rule_id: str) -> RulePreviewResult:
    return next(rule for rule in preview.rules if rule.rule_id == rule_id)


def test_core_business_overage_builds_stable_high_risk_preview() -> None:
    facts = _base_facts()

    preview = build_offline_audit_preview(facts, _metadata())

    assert preview.preview_id == facts.preview_id
    assert tuple(rule.rule_id for rule in preview.rules) == _RULE_IDS
    overage = _rule(preview, "RULE-003")
    assert overage.status is RuleExecutionStatus.FAILED
    assert overage.disposition is RulePreviewDisposition.HIT
    assert overage.actual_value == "110000.00"
    assert overage.expected_value == "100000.00"
    assert overage.risk_id == uuid5(facts.preview_id, "RULE-003")
    assert overage.risk_level is RiskLevel.HIGH
    assert preview.summary.overall_level is RiskLevel.HIGH
    assert preview.summary.has_unreviewed_high is True
    assert all(risk.review_status is RiskReviewStatus.PENDING for risk in preview.risks)
    assert all(risk.original_level is risk.effective_level for risk in preview.risks)
    assert preview.ai_status is AiPreviewStatus.DISABLED


def test_core_business_date_and_duplicate_scenarios_hit_their_exact_rules() -> None:
    items = _core_business_items()
    date_facts = replace(
        _base_facts(preview_id=UUID(int=501)),
        invoice_date=date.fromisoformat(str(items["I-003"]["issue_date"])),
        cumulative_invoice_total=Decimal("60000.00"),
    )
    duplicate_facts = replace(
        _base_facts(preview_id=UUID(int=502)),
        cumulative_invoice_total=Decimal("60000.00"),
        has_existing_exact_invoice_identity=bool(
            items["I-001-DUP"]["expected_rule"]["triggered"]  # type: ignore[index]
        ),
    )

    date_preview = build_offline_audit_preview(date_facts, _metadata())
    duplicate_preview = build_offline_audit_preview(duplicate_facts, _metadata())

    assert _rule(date_preview, "RULE-004").disposition is RulePreviewDisposition.HIT
    assert _rule(date_preview, "RULE-004").risk_level is RiskLevel.MEDIUM
    assert _rule(duplicate_preview, "RULE-005").disposition is RulePreviewDisposition.HIT
    assert _rule(duplicate_preview, "RULE-005").risk_level is RiskLevel.HIGH


def test_no_contract_keeps_contract_rules_not_applicable_but_rule_010_hits() -> None:
    facts = replace(
        _base_facts(),
        has_confirmed_primary_contract=False,
        invoice_date=date(2030, 1, 1),
        cumulative_invoice_total=Decimal("999999.00"),
    )

    preview = build_offline_audit_preview(facts, _metadata())

    for rule_id in (
        "RULE-001",
        "RULE-003",
        "RULE-004",
        "RULE-006",
        "RULE-008",
        "RULE-011",
        "RULE-012",
    ):
        result = _rule(preview, rule_id)
        assert result.status is RuleExecutionStatus.NOT_APPLICABLE
        assert result.disposition is RulePreviewDisposition.NOT_APPLICABLE
    assert _rule(preview, "RULE-010").disposition is RulePreviewDisposition.HIT


@pytest.mark.parametrize(
    ("rule_id", "changes"),
    (
        ("RULE-001", {"contract_party_b_tax_no": None}),
        ("RULE-002", {"invoice_buyer_tax_no": None}),
        ("RULE-003", {"cumulative_invoice_total": None}),
        ("RULE-004", {"contract_expiry_date": None}),
        ("RULE-005", {"has_existing_exact_invoice_identity": None}),
        ("RULE-008", {"invoice_currency": None}),
        ("RULE-009", {"invoice_line_net_amount": None}),
        ("RULE-014", {"standard_name_b": None}),
        ("RULE-015", {"is_red_invoice": None}),
    ),
)
def test_missing_facts_are_not_reported_as_mismatches_or_hits(
    rule_id: str,
    changes: dict[str, object],
) -> None:
    complete_amounts: dict[str, object] = {
        "invoice_line_net_amount": Decimal("50000.00"),
        "invoice_tax_amount": Decimal("0.00"),
    }
    complete_amounts.update(changes)
    facts = replace(_base_facts(), **complete_amounts)

    result = _rule(build_offline_audit_preview(facts, _metadata()), rule_id)

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE
    assert result.disposition is RulePreviewDisposition.MISSING
    assert result.risk_id is None
    assert result.risk_level is None


def test_rules_006_and_007_use_their_predicate_missing_fact_semantics() -> None:
    facts = replace(
        _base_facts(),
        contract_amount_present=False,
        effective_contract_amount=None,
        invoice_code=None,
    )

    preview = build_offline_audit_preview(facts, _metadata())

    for rule_id in ("RULE-006", "RULE-007"):
        result = _rule(preview, rule_id)
        assert result.status is RuleExecutionStatus.FAILED
        assert result.disposition is RulePreviewDisposition.HIT


def test_retrieval_failure_is_not_misreported_as_missing_policy_evidence() -> None:
    degraded_facts = _base_facts()
    completed_facts = replace(degraded_facts, retrieval_completed_successfully=True)
    not_required_facts = replace(
        degraded_facts,
        requires_policy_citation=False,
        retrieval_completed_successfully=True,
    )

    degraded = _rule(
        build_offline_audit_preview(degraded_facts, _metadata()),
        "RULE-013",
    )
    completed = _rule(
        build_offline_audit_preview(completed_facts, _metadata()),
        "RULE-013",
    )
    not_required = _rule(
        build_offline_audit_preview(not_required_facts, _metadata()),
        "RULE-013",
    )

    assert degraded.status is RuleExecutionStatus.NOT_APPLICABLE
    assert degraded.disposition is RulePreviewDisposition.NOT_APPLICABLE
    assert degraded.actual_value is None
    assert degraded.expected_value is None
    assert completed.status is RuleExecutionStatus.FAILED
    assert completed.disposition is RulePreviewDisposition.HIT
    assert not_required.status is RuleExecutionStatus.NOT_APPLICABLE
    assert not_required.disposition is RulePreviewDisposition.NOT_APPLICABLE


def test_red_invoice_is_not_applicable_instead_of_missing_or_hit() -> None:
    facts = replace(_base_facts(), is_red_invoice=True)

    result = _rule(build_offline_audit_preview(facts, _metadata()), "RULE-015")

    assert result.status is RuleExecutionStatus.NOT_APPLICABLE
    assert result.disposition is RulePreviewDisposition.NOT_APPLICABLE


def test_build_calls_each_existing_predicate(monkeypatch: pytest.MonkeyPatch) -> None:
    function_names = (
        "evaluate_rule_001",
        "evaluate_rule_002",
        "evaluate_rule_003",
        "evaluate_rule_004",
        "evaluate_rule_005",
        "evaluate_rule_006",
        "evaluate_rule_007",
        "evaluate_rule_008_currency_pair",
        "evaluate_rule_009",
        "evaluate_rule_010",
        "evaluate_rule_011",
        "evaluate_rule_012",
        "evaluate_rule_013",
        "evaluate_rule_014_identity_pair",
        "evaluate_rule_015",
    )
    calls: list[str] = []
    for function_name in function_names:
        original = getattr(offline_preview_module, function_name)

        def recording_call(
            *args: object,
            _function_name: str = function_name,
            _original: object = original,
            **kwargs: object,
        ) -> object:
            calls.append(_function_name)
            return _original(*args, **kwargs)  # type: ignore[operator]

        monkeypatch.setattr(offline_preview_module, function_name, recording_call)

    facts = _base_facts()

    assert calls == []

    build_offline_audit_preview(facts, _metadata())

    assert len(calls) == len(function_names)
    assert set(calls) == set(function_names)


def test_metadata_reordering_does_not_change_rule_or_risk_output() -> None:
    facts = _base_facts()
    ordered = _metadata()

    first = build_offline_audit_preview(facts, ordered)
    second = build_offline_audit_preview(facts, tuple(reversed(ordered)))

    assert first == second


def test_reference_ids_are_canonicalized_and_preserved_on_results() -> None:
    earlier = UUID(int=1)
    later = UUID(int=2)
    metadata = list(_metadata())
    metadata[2] = RuleMetadata(
        rule_id="RULE-003",
        risk_level=RiskLevel.HIGH,
        reference_ids=(later, earlier, later),
    )

    preview = build_offline_audit_preview(_base_facts(), tuple(metadata))

    assert metadata[2].reference_ids == (earlier, later)
    assert _rule(preview, "RULE-003").reference_ids == (earlier, later)


def test_decimal_values_remain_exact_strings_under_a_small_decimal_context() -> None:
    facts = _base_facts()

    with localcontext() as context:
        context.prec = 2
        result = _rule(build_offline_audit_preview(facts, _metadata()), "RULE-003")

    assert result.actual_value == "110000.00"
    assert result.expected_value == "100000.00"
    assert type(result.actual_value) is str
    assert type(result.expected_value) is str


def test_composite_values_use_stable_reviewable_text() -> None:
    facts = replace(
        _base_facts(),
        invoice_line_net_amount=Decimal("50000.00"),
        invoice_tax_amount=Decimal("0.00"),
    )

    preview = build_offline_audit_preview(facts, _metadata())

    assert _rule(preview, "RULE-004").expected_value == "2026-01-01..2026-12-31"
    assert _rule(preview, "RULE-006").actual_value == "all_present"
    assert _rule(preview, "RULE-006").expected_value == "all_present"
    assert _rule(preview, "RULE-007").actual_value == "all_present"
    assert _rule(preview, "RULE-007").expected_value == "all_present"
    assert (
        _rule(preview, "RULE-009").actual_value
        == "line_net_amount=50000.00;tax_amount=0.00;total_amount=50000.00"
    )
    assert _rule(preview, "RULE-009").expected_value == "absolute_difference<=0.01"
    assert _rule(preview, "RULE-014").actual_value == "name_equal=true;tax_identity_equal=true"
    assert _rule(preview, "RULE-014").expected_value == "no_name_tax_identity_conflict"


@pytest.mark.parametrize(
    ("rule_id", "changes"),
    (
        ("RULE-001", {"contract_party_b_tax_no": "DIFFERENT-TAX-NO"}),
        ("RULE-002", {"invoice_buyer_tax_no": "DIFFERENT-TAX-NO"}),
        ("RULE-003", {}),
        ("RULE-004", {"invoice_date": date(2027, 1, 1)}),
        ("RULE-005", {"has_existing_exact_invoice_identity": True}),
        (
            "RULE-006",
            {
                "contract_amount_present": False,
                "effective_contract_amount": None,
            },
        ),
        ("RULE-007", {"invoice_code": None}),
        ("RULE-008", {"invoice_currency": "USD"}),
        (
            "RULE-009",
            {
                "invoice_line_net_amount": Decimal("49999.00"),
                "invoice_tax_amount": Decimal("0.00"),
            },
        ),
        ("RULE-010", {"has_confirmed_primary_contract": False}),
        ("RULE-011", {"contract_no": None}),
        (
            "RULE-012",
            {"has_effective_unconfirmed_supplementary_agreement": True},
        ),
        ("RULE-013", {"retrieval_completed_successfully": True}),
        ("RULE-014", {"tax_identity_b": "DIFFERENT-TAX-NO"}),
        ("RULE-015", {"invoice_total_amount": Decimal("0.00")}),
    ),
)
def test_every_rule_hit_has_reviewable_exact_text(
    rule_id: str,
    changes: dict[str, object],
) -> None:
    facts = replace(_base_facts(), **changes)

    result = _rule(build_offline_audit_preview(facts, _metadata()), rule_id)

    assert result.disposition is RulePreviewDisposition.HIT
    assert type(result.actual_value) is str
    assert type(result.expected_value) is str


def test_build_does_not_mutate_frozen_inputs_and_ai_status_cannot_change() -> None:
    facts = _base_facts()
    metadata = _metadata()
    metadata_before = tuple(metadata)

    preview = build_offline_audit_preview(facts, metadata)

    assert metadata == metadata_before
    with pytest.raises(FrozenInstanceError):
        OfflineAuditFacts.__setattr__(facts, "invoice_code", "changed")
    with pytest.raises(FrozenInstanceError):
        RuleMetadata.__setattr__(metadata[0], "rule_id", "RULE-999")
    with pytest.raises(FrozenInstanceError):
        type(preview).__setattr__(preview, "ai_status", AiPreviewStatus.DISABLED)


@pytest.mark.parametrize(
    ("changes", "presence_name"),
    (
        (
            {
                "has_confirmed_primary_contract": False,
                "contract_amount_present": False,
            },
            "contract_amount_present",
        ),
        ({"effective_contract_amount": None}, "contract_amount_present"),
        ({"contract_currency_present": False}, "contract_currency_present"),
        ({"contract_currency": None}, "contract_currency_present"),
        (
            {"contract_effective_date_present": False},
            "contract_effective_date_present",
        ),
        ({"contract_effective_date": None}, "contract_effective_date_present"),
    ),
)
def test_contract_presence_flags_must_match_frozen_values(
    changes: dict[str, object],
    presence_name: str,
) -> None:
    with pytest.raises(ValueError, match=presence_name):
        replace(_base_facts(), **changes)


@pytest.mark.parametrize(
    "risk_changes",
    (
        {"original_level": RiskLevel.LOW},
        {"effective_level": RiskLevel.LOW},
        {"review_status": RiskReviewStatus.CONFIRMED},
    ),
)
def test_preview_rejects_risks_that_do_not_match_hit_rules(
    risk_changes: dict[str, object],
) -> None:
    preview = build_offline_audit_preview(_base_facts(), _metadata())
    inconsistent_risks = (
        replace(preview.risks[0], **risk_changes),
        *preview.risks[1:],
    )

    with pytest.raises(ValueError, match="risks must match hit rule"):
        replace(
            preview,
            risks=inconsistent_risks,
            summary=calculate_risk_summary(inconsistent_risks),
        )


def test_sensitive_fact_and_actual_expected_strings_are_hidden_from_repr() -> None:
    facts = _base_facts()

    preview = build_offline_audit_preview(facts, _metadata())
    rule_001 = _rule(preview, "RULE-001")
    rule_002 = _rule(preview, "RULE-002")

    for sensitive in (
        facts.contract_party_b_tax_no,
        facts.invoice_seller_tax_no,
        facts.organization_tax_number,
        facts.invoice_buyer_tax_no,
        facts.standard_name_a,
    ):
        assert sensitive is not None
        assert sensitive not in repr(facts)
        assert sensitive not in repr(rule_001)
        assert sensitive not in repr(rule_002)


@pytest.mark.parametrize(
    "invalid_metadata",
    (
        [],
        tuple(_metadata()[:-1]),
        tuple((*_metadata()[:-1], _metadata()[0])),
        tuple((*_metadata()[:-1], RuleMetadata("RULE-016", RiskLevel.HIGH, ()))),
    ),
)
def test_metadata_must_cover_each_rule_exactly_once(invalid_metadata: object) -> None:
    with pytest.raises(ValueError, match="metadata"):
        build_offline_audit_preview(
            _base_facts(),
            invalid_metadata,  # type: ignore[arg-type]
        )


class StringSubclass(str):
    pass


class UuidSubclass(UUID):
    pass


@pytest.mark.parametrize("invalid_rule_id", ("", "   ", StringSubclass("RULE-001"), 1))
def test_rule_metadata_rejects_non_exact_or_blank_rule_ids(invalid_rule_id: object) -> None:
    with pytest.raises(ValueError, match="rule_id"):
        RuleMetadata(
            rule_id=invalid_rule_id,  # type: ignore[arg-type]
            risk_level=RiskLevel.HIGH,
            reference_ids=(),
        )


def test_rule_metadata_rejects_non_exact_levels_and_reference_ids() -> None:
    with pytest.raises(ValueError, match="risk_level"):
        RuleMetadata("RULE-001", "high", ())  # type: ignore[arg-type]
    for invalid_references in (
        [UUID(int=1)],
        ("reference",),
        (UuidSubclass(int=1),),
    ):
        with pytest.raises(ValueError, match="reference_ids"):
            RuleMetadata(
                "RULE-001",
                RiskLevel.HIGH,
                invalid_references,  # type: ignore[arg-type]
            )


def test_facts_reject_non_exact_uuid_and_predicate_inputs() -> None:
    facts = _base_facts()
    with pytest.raises(ValueError, match="preview_id"):
        replace(facts, preview_id=UuidSubclass(int=1))
    with pytest.raises(ValueError, match="exact bool"):
        replace(facts, has_confirmed_primary_contract=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite exact Decimal"):
        replace(facts, cumulative_invoice_total=1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="organization_tax_number"):
        replace(facts, organization_tax_number="")


def test_build_rejects_a_non_exact_facts_contract() -> None:
    with pytest.raises(ValueError, match="OfflineAuditFacts"):
        build_offline_audit_preview("facts", _metadata())  # type: ignore[arg-type]
