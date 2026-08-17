from dataclasses import FrozenInstanceError
from enum import Enum
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from app.audit.risk_summary import (
    RiskLevel,
    RiskReviewStatus,
    RiskSummary,
    RiskSummaryInput,
    calculate_risk_summary,
)


def risk(
    risk_id: str,
    *,
    original_level: RiskLevel = RiskLevel.MEDIUM,
    effective_level: RiskLevel = RiskLevel.MEDIUM,
    review_status: RiskReviewStatus = RiskReviewStatus.PENDING,
) -> RiskSummaryInput:
    return RiskSummaryInput(
        risk_id=uuid5(NAMESPACE_URL, risk_id),
        original_level=original_level,
        effective_level=effective_level,
        review_status=review_status,
    )


@pytest.mark.parametrize("level", list(RiskLevel))
def test_each_effective_level_can_be_the_overall_level(level: RiskLevel) -> None:
    summary = calculate_risk_summary((risk("risk-1", effective_level=level),))

    assert summary.overall_level is level
    assert summary.active_risk_count == 1
    assert summary.dismissed_risk_count == 0


def test_highest_non_dismissed_effective_level_wins() -> None:
    summary = calculate_risk_summary(
        (
            risk("notice", effective_level=RiskLevel.NOTICE),
            risk("low", effective_level=RiskLevel.LOW),
            risk("medium", effective_level=RiskLevel.MEDIUM),
            risk("none", effective_level=RiskLevel.NONE),
        )
    )

    assert summary.overall_level is RiskLevel.MEDIUM
    assert summary.active_risk_count == 4


def test_dismissed_risks_are_excluded_from_overall_and_high_flags() -> None:
    summary = calculate_risk_summary(
        (
            risk(
                "dismissed-high",
                effective_level=RiskLevel.HIGH,
                review_status=RiskReviewStatus.DISMISSED,
            ),
            risk("active-medium", effective_level=RiskLevel.MEDIUM),
        )
    )

    assert summary == RiskSummary(
        overall_level=RiskLevel.MEDIUM,
        active_risk_count=1,
        dismissed_risk_count=1,
        has_effective_high=False,
        has_unreviewed_high=False,
    )


def test_empty_and_all_dismissed_sets_have_no_overall_risk() -> None:
    empty_summary = calculate_risk_summary(())
    dismissed_summary = calculate_risk_summary(
        (
            risk(
                "dismissed",
                effective_level=RiskLevel.HIGH,
                review_status=RiskReviewStatus.DISMISSED,
            ),
        )
    )

    assert empty_summary.overall_level is RiskLevel.NONE
    assert empty_summary.active_risk_count == 0
    assert empty_summary.dismissed_risk_count == 0
    assert dismissed_summary.overall_level is RiskLevel.NONE
    assert dismissed_summary.active_risk_count == 0
    assert dismissed_summary.dismissed_risk_count == 1


def test_adjusted_risks_use_effective_not_original_level() -> None:
    adjusted_up = calculate_risk_summary(
        (
            risk(
                "adjusted-up",
                original_level=RiskLevel.MEDIUM,
                effective_level=RiskLevel.HIGH,
                review_status=RiskReviewStatus.ADJUSTED,
            ),
        )
    )
    adjusted_down = calculate_risk_summary(
        (
            risk(
                "adjusted-down",
                original_level=RiskLevel.HIGH,
                effective_level=RiskLevel.MEDIUM,
                review_status=RiskReviewStatus.ADJUSTED,
            ),
        )
    )

    assert adjusted_up.overall_level is RiskLevel.HIGH
    assert adjusted_up.has_effective_high is True
    assert adjusted_up.has_unreviewed_high is False
    assert adjusted_down.overall_level is RiskLevel.MEDIUM
    assert adjusted_down.has_effective_high is False


def test_pending_high_is_effective_and_unreviewed() -> None:
    summary = calculate_risk_summary((risk("pending-high", effective_level=RiskLevel.HIGH),))

    assert summary.has_effective_high is True
    assert summary.has_unreviewed_high is True


def test_confirmed_high_is_effective_but_not_unreviewed() -> None:
    summary = calculate_risk_summary(
        (
            risk(
                "confirmed-high",
                effective_level=RiskLevel.HIGH,
                review_status=RiskReviewStatus.CONFIRMED,
            ),
        )
    )

    assert summary.has_effective_high is True
    assert summary.has_unreviewed_high is False


def test_rejects_duplicate_risk_ids() -> None:
    with pytest.raises(ValueError, match="risk_id must be unique"):
        calculate_risk_summary((risk("duplicate"), risk("duplicate")))


@pytest.mark.parametrize("invalid", [[], "risk", {"risk": "value"}, 1, None])
def test_rejects_non_tuple_risk_collections(invalid: object) -> None:
    with pytest.raises(ValueError, match="tuple of RiskSummaryInput"):
        calculate_risk_summary(cast(tuple[RiskSummaryInput, ...], invalid))


def test_rejects_non_risk_tuple_members() -> None:
    with pytest.raises(ValueError, match="tuple of RiskSummaryInput"):
        calculate_risk_summary(cast(tuple[RiskSummaryInput, ...], ("risk",)))


@pytest.mark.parametrize("invalid", ["risk-1", "", 1, True, None])
def test_rejects_invalid_risk_ids(invalid: object) -> None:
    with pytest.raises(ValueError, match="risk_id must be a UUID"):
        RiskSummaryInput(
            risk_id=cast(UUID, invalid),
            original_level=RiskLevel.HIGH,
            effective_level=RiskLevel.HIGH,
            review_status=RiskReviewStatus.PENDING,
        )


def test_rejects_uuid_subclass_risk_id() -> None:
    class LyingUuid(UUID):
        pass

    with pytest.raises(ValueError, match="risk_id must be a UUID"):
        RiskSummaryInput(
            risk_id=cast(UUID, LyingUuid(int=1)),
            original_level=RiskLevel.HIGH,
            effective_level=RiskLevel.HIGH,
            review_status=RiskReviewStatus.PENDING,
        )


class UnrelatedLevel(str, Enum):
    HIGH = "high"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("original_level", "high", "original_level must be a RiskLevel"),
        ("original_level", UnrelatedLevel.HIGH, "original_level must be a RiskLevel"),
        ("effective_level", "high", "effective_level must be a RiskLevel"),
        ("effective_level", UnrelatedLevel.HIGH, "effective_level must be a RiskLevel"),
        ("review_status", "pending", "review_status must be a RiskReviewStatus"),
    ],
)
def test_rejects_non_exact_enum_instances(field: str, value: object, error: str) -> None:
    values: dict[str, object] = {
        "risk_id": UUID(int=1),
        "original_level": RiskLevel.HIGH,
        "effective_level": RiskLevel.HIGH,
        "review_status": RiskReviewStatus.PENDING,
    }
    values[field] = value

    with pytest.raises(ValueError, match=error):
        RiskSummaryInput(
            risk_id=cast(UUID, values["risk_id"]),
            original_level=cast(RiskLevel, values["original_level"]),
            effective_level=cast(RiskLevel, values["effective_level"]),
            review_status=cast(RiskReviewStatus, values["review_status"]),
        )


def test_contracts_are_immutable() -> None:
    input_risk = risk("immutable")
    summary = calculate_risk_summary((input_risk,))

    with pytest.raises(FrozenInstanceError):
        RiskSummaryInput.__setattr__(input_risk, "risk_id", UUID(int=2))
    with pytest.raises(FrozenInstanceError):
        RiskSummary.__setattr__(summary, "active_risk_count", 0)
