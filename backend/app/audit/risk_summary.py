"""AUD-005 的离线风险汇总纯函数。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class RiskLevel(str, Enum):
    """风险原始等级和有效等级的冻结枚举。"""

    NONE = "none"
    NOTICE = "notice"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskReviewStatus(str, Enum):
    """风险人工复核状态的冻结枚举。"""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    ADJUSTED = "adjusted"


@dataclass(frozen=True, slots=True)
class RiskSummaryInput:
    """一条风险汇总所需的最小冻结事实。"""

    risk_id: UUID
    original_level: RiskLevel
    effective_level: RiskLevel
    review_status: RiskReviewStatus

    def __post_init__(self) -> None:
        if type(self.risk_id) is not UUID:
            raise ValueError("risk_id must be a UUID")
        if type(self.original_level) is not RiskLevel:
            raise ValueError("original_level must be a RiskLevel")
        if type(self.effective_level) is not RiskLevel:
            raise ValueError("effective_level must be a RiskLevel")
        if type(self.review_status) is not RiskReviewStatus:
            raise ValueError("review_status must be a RiskReviewStatus")


@dataclass(frozen=True, slots=True)
class RiskSummary:
    """仅由当前风险集合直接证明的冻结汇总事实。"""

    overall_level: RiskLevel
    active_risk_count: int
    dismissed_risk_count: int
    has_effective_high: bool
    has_unreviewed_high: bool


_RISK_LEVEL_ORDER = {
    RiskLevel.NONE: 0,
    RiskLevel.NOTICE: 1,
    RiskLevel.LOW: 2,
    RiskLevel.MEDIUM: 3,
    RiskLevel.HIGH: 4,
}


def calculate_risk_summary(risks: tuple[RiskSummaryInput, ...]) -> RiskSummary:
    """按未驳回风险的最高有效等级计算当前风险汇总。"""

    if type(risks) is not tuple or any(type(risk) is not RiskSummaryInput for risk in risks):
        raise ValueError("risks must be a tuple of RiskSummaryInput")

    risk_ids = tuple(risk.risk_id for risk in risks)
    if len(risk_ids) != len(set(risk_ids)):
        raise ValueError("risk_id must be unique within a risk summary")

    active_risks = tuple(
        risk for risk in risks if risk.review_status is not RiskReviewStatus.DISMISSED
    )
    overall_level = max(
        (risk.effective_level for risk in active_risks),
        key=_RISK_LEVEL_ORDER.__getitem__,
        default=RiskLevel.NONE,
    )
    has_effective_high = any(risk.effective_level is RiskLevel.HIGH for risk in active_risks)

    return RiskSummary(
        overall_level=overall_level,
        active_risk_count=len(active_risks),
        dismissed_risk_count=len(risks) - len(active_risks),
        has_effective_high=has_effective_high,
        has_unreviewed_high=any(
            risk.effective_level is RiskLevel.HIGH
            and risk.review_status is RiskReviewStatus.PENDING
            for risk in active_risks
        ),
    )
