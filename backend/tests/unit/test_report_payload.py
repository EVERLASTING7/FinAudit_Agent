from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

import app.reports.report_payload as report_payload_module
from app.audit.offline_preview import (
    AiPreviewStatus,
    OfflineAuditPreview,
    RulePreviewDisposition,
    RulePreviewResult,
)
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
    ReportMetadata,
    ReportPayload,
    ReportTable,
    build_report_payload,
    report_payload_json_bytes,
)

_EXPECTED_PATH = Path(__file__).parents[1] / "fixtures" / "report_payload_expected.json"
_GENERATED_AT = datetime(2026, 8, 12, 3, 4, 5, 6, tzinfo=timezone.utc)
_PREVIEW_ID = UUID(int=500)


def _preview(
    *,
    preview_id: UUID = _PREVIEW_ID,
    actual_002: str = "91310000MA1234567X",
    expected_002: str = "91310000MA7654321Y",
    actual_003: str = "110000.00",
    expected_003: str = "100000.00",
    include_hits: bool = True,
) -> OfflineAuditPreview:
    hit_specs = {
        "RULE-002": (
            UUID(int=202),
            RiskLevel.MEDIUM,
            actual_002,
            expected_002,
            (UUID(int=12), UUID(int=13)),
        ),
        "RULE-003": (
            UUID(int=203),
            RiskLevel.HIGH,
            actual_003,
            expected_003,
            (UUID(int=2), UUID(int=3)),
        ),
    }
    rules: list[RulePreviewResult] = []
    risks: list[RiskSummaryInput] = []
    for number in range(1, 16):
        rule_id = f"RULE-{number:03d}"
        if include_hits and rule_id in hit_specs:
            risk_id, level, actual, expected, reference_ids = hit_specs[rule_id]
            rules.append(
                RulePreviewResult(
                    rule_id=rule_id,
                    status=RuleExecutionStatus.FAILED,
                    disposition=RulePreviewDisposition.HIT,
                    actual_value=actual,
                    expected_value=expected,
                    risk_id=risk_id,
                    risk_level=level,
                    reference_ids=reference_ids,
                )
            )
            risks.append(
                RiskSummaryInput(
                    risk_id=risk_id,
                    original_level=level,
                    effective_level=level,
                    review_status=RiskReviewStatus.PENDING,
                )
            )
        else:
            rules.append(
                RulePreviewResult(
                    rule_id=rule_id,
                    status=RuleExecutionStatus.PASSED,
                    disposition=RulePreviewDisposition.NOT_HIT,
                    actual_value=None,
                    expected_value=None,
                    risk_id=None,
                    risk_level=None,
                    reference_ids=(),
                )
            )
    frozen_risks = tuple(risks)
    return OfflineAuditPreview(
        preview_id=preview_id,
        rules=tuple(rules),
        risks=frozen_risks,
        summary=calculate_risk_summary(frozen_risks),
    )


def _metadata(
    *,
    reasons: tuple[str, ...] = ("AI disabled", "policy retrieval unavailable"),
    is_outdated: bool = True,
) -> ReportMetadata:
    return ReportMetadata(
        report_version_id=UUID(int=900),
        audit_version_id=UUID(int=800),
        generated_at=_GENERATED_AT,
        is_outdated=is_outdated,
        is_degraded=bool(reasons),
        degraded_reasons=reasons,
    )


def _all_string_values(value: object) -> list[str]:
    if type(value) is str:
        return [value]
    if type(value) is list:
        return [text for item in value for text in _all_string_values(item)]
    if type(value) is dict:
        return [text for item in value.values() for text in _all_string_values(item)]
    return []


def test_report_payload_matches_byte_exact_json_fixture() -> None:
    payload = build_report_payload(_preview(), _metadata())

    actual = report_payload_json_bytes(payload)

    assert actual == _EXPECTED_PATH.read_bytes()
    assert actual == report_payload_json_bytes(payload)
    assert actual.decode("utf-8").endswith("\n")


def test_payload_has_fixed_field_and_table_column_order() -> None:
    payload = build_report_payload(_preview(), _metadata())
    document = json.loads(report_payload_json_bytes(payload))

    assert list(document) == ["metadata", "preview_id", "ai_status", "summary", "rules", "risks"]
    assert list(document["metadata"]) == [
        "report_version_id",
        "audit_version_id",
        "generated_at",
        "is_outdated",
        "is_degraded",
        "degraded_reasons",
    ]
    assert tuple(document["rules"]["columns"]) == RULE_TABLE_COLUMNS
    assert tuple(document["risks"]["columns"]) == RISK_TABLE_COLUMNS
    assert [row[0] for row in document["rules"]["rows"]] == [
        f"RULE-{number:03d}" for number in range(1, 16)
    ]


def test_each_formula_prefix_is_neutralized_across_nested_report_text() -> None:
    prefixes = ("=", "+", "-", "@", "\t", "\r", "\n")
    preview = _preview(actual_002="+actual", expected_002="-expected")
    metadata = _metadata(reasons=tuple(f"{prefix}reason" for prefix in prefixes))

    payload = build_report_payload(preview, metadata)
    document = json.loads(report_payload_json_bytes(payload))

    values = _all_string_values(document)
    assert all(value[:1] not in prefixes for value in values)
    assert set(document["metadata"]["degraded_reasons"]) == {
        f"'{prefix}reason" for prefix in prefixes
    }
    rule_002 = document["rules"]["rows"][1]
    risk_002 = document["risks"]["rows"][0]
    assert rule_002[3:5] == ["'+actual", "'-expected"]
    assert risk_002[5:7] == ["'+actual", "'-expected"]


def test_reference_text_is_sorted_deduplicated_and_passes_the_safety_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = report_payload_module.neutralize_spreadsheet_formula_text

    def recording_neutralizer(value: str) -> str:
        calls.append(value)
        return original(value)

    monkeypatch.setattr(
        report_payload_module,
        "neutralize_spreadsheet_formula_text",
        recording_neutralizer,
    )

    payload = build_report_payload(_preview(), _metadata())
    rule_003 = payload.rules.rows[2]

    expected = f"{UUID(int=2)};{UUID(int=3)}"
    assert rule_003[7] == expected
    assert str(UUID(int=2)) in calls
    assert str(UUID(int=3)) in calls
    assert expected in calls


def test_multiple_risks_are_stably_ordered_and_preserve_review_facts() -> None:
    payload = build_report_payload(_preview(), _metadata())

    assert [row[1] for row in payload.risks.rows] == ["RULE-002", "RULE-003"]
    assert payload.risks.rows[0][2:5] == (
        RiskLevel.MEDIUM.value,
        RiskLevel.MEDIUM.value,
        RiskReviewStatus.PENDING.value,
    )
    assert payload.risks.rows[1][2:5] == (
        RiskLevel.HIGH.value,
        RiskLevel.HIGH.value,
        RiskReviewStatus.PENDING.value,
    )


def test_metadata_reason_reordering_and_duplicates_do_not_change_payload_bytes() -> None:
    preview = _preview()
    first = _metadata(reasons=("second", "first", "second"))
    second = _metadata(reasons=("first", "second"))

    assert build_report_payload(preview, first) == build_report_payload(preview, second)
    assert report_payload_json_bytes(build_report_payload(preview, first)) == (
        report_payload_json_bytes(build_report_payload(preview, second))
    )


def test_ai_disabled_degraded_and_outdated_are_explicit() -> None:
    payload = build_report_payload(_preview(), _metadata(is_outdated=True))
    document = json.loads(report_payload_json_bytes(payload))

    assert payload.ai_status == AiPreviewStatus.DISABLED.value
    assert document["metadata"]["is_degraded"] is True
    assert document["metadata"]["degraded_reasons"]
    assert document["metadata"]["is_outdated"] is True


def test_empty_risks_references_and_nullable_values_are_stable() -> None:
    payload = build_report_payload(_preview(include_hits=False), _metadata())
    document = json.loads(report_payload_json_bytes(payload))

    assert payload.risks.rows == ()
    assert document["risks"]["rows"] == []
    assert document["rules"]["rows"][0][3:7] == [None, None, None, None]
    assert document["rules"]["rows"][0][7] == ""
    assert document["metadata"]["is_degraded"] is True
    assert document["metadata"]["degraded_reasons"]


def test_disabled_ai_preview_requires_explicit_degraded_metadata() -> None:
    with pytest.raises(ValueError, match="disabled AI"):
        build_report_payload(_preview(), _metadata(reasons=()))


def test_decimal_cells_become_exact_strings_without_float_conversion() -> None:
    amount = Decimal("1000000000000000000.1000")

    table = ReportTable(columns=("amount",), rows=((amount,),))
    payload = build_report_payload(_preview(), _metadata())
    document = json.loads(report_payload_json_bytes(payload))

    assert table.rows == (("1000000000000000000.1000",),)
    assert type(table.rows[0][0]) is str
    assert document["rules"]["rows"][2][3:5] == ["110000.00", "100000.00"]
    assert not any(type(value) is float for row in document["rules"]["rows"] for value in row)


def test_builder_does_not_mutate_frozen_inputs() -> None:
    preview = _preview()
    metadata = _metadata()
    before = (preview, metadata)

    payload = build_report_payload(preview, metadata)

    assert (preview, metadata) == before
    with pytest.raises(FrozenInstanceError):
        ReportPayload.__setattr__(payload, "ai_status", "enabled")
    with pytest.raises(FrozenInstanceError):
        ReportMetadata.__setattr__(metadata, "is_outdated", False)


def test_sensitive_report_text_is_hidden_from_nested_reprs() -> None:
    sensitive_tax_number = "SENSITIVE-TAX-91310000"
    sensitive_amount = "999999999999.99"
    sensitive_degraded_reason = "SENSITIVE-PROVIDER-DETAIL"
    metadata = _metadata(reasons=(sensitive_degraded_reason,))
    payload = build_report_payload(
        _preview(
            actual_002=sensitive_tax_number,
            actual_003=sensitive_amount,
        ),
        metadata,
    )

    representations = (
        repr(metadata),
        repr(payload.rules),
        repr(payload.risks),
        repr(payload),
    )
    for representation in representations:
        assert sensitive_tax_number not in representation
        assert sensitive_amount not in representation
        assert sensitive_degraded_reason not in representation
    assert str(payload.preview_id) in repr(payload)
    assert AiPreviewStatus.DISABLED.value in repr(payload)


class UuidSubclass(UUID):
    pass


class DatetimeSubclass(datetime):
    pass


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"report_version_id": UuidSubclass(int=1)}, "report_version_id"),
        ({"audit_version_id": UuidSubclass(int=1)}, "audit_version_id"),
        ({"generated_at": datetime(2026, 8, 12)}, "timezone-aware UTC"),
        (
            {"generated_at": datetime(2026, 8, 12, tzinfo=timezone(timedelta(hours=8)))},
            "timezone-aware UTC",
        ),
        (
            {"generated_at": DatetimeSubclass(2026, 8, 12, tzinfo=timezone.utc)},
            "exact datetime",
        ),
        ({"is_outdated": 1}, "is_outdated"),
        ({"is_degraded": 1}, "is_degraded"),
    ),
)
def test_metadata_rejects_invalid_uuid_datetime_and_bool_types(
    changes: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "report_version_id": UUID(int=900),
        "audit_version_id": UUID(int=800),
        "generated_at": _GENERATED_AT,
        "is_outdated": False,
        "is_degraded": False,
        "degraded_reasons": (),
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        ReportMetadata(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("is_degraded", "reasons"),
    (
        (False, ("reason",)),
        (True, ()),
        (True, ["reason"]),
        (True, ("",)),
        (True, (1,)),
    ),
)
def test_metadata_rejects_inconsistent_or_invalid_degradation(
    is_degraded: object,
    reasons: object,
) -> None:
    with pytest.raises(ValueError, match="degraded"):
        ReportMetadata(
            report_version_id=UUID(int=900),
            audit_version_id=UUID(int=800),
            generated_at=_GENERATED_AT,
            is_outdated=False,
            is_degraded=cast(bool, is_degraded),
            degraded_reasons=cast(tuple[str, ...], reasons),
        )


def test_report_table_rejects_float_and_wrong_width() -> None:
    with pytest.raises(ValueError, match="report cells"):
        ReportTable(columns=("amount",), rows=((1.5,),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="column count"):
        ReportTable(columns=("first", "second"), rows=(("only one",),))


def test_builder_and_serializer_require_exact_contracts() -> None:
    with pytest.raises(ValueError, match="OfflineAuditPreview"):
        build_report_payload("preview", _metadata())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ReportMetadata"):
        build_report_payload(_preview(), "metadata")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ReportPayload"):
        report_payload_json_bytes("payload")  # type: ignore[arg-type]


def test_report_payload_stays_equal_after_metadata_replace_with_same_values() -> None:
    metadata = _metadata()

    first = build_report_payload(_preview(), metadata)
    second = build_report_payload(_preview(), replace(metadata))

    assert first == second
