"""DOC-008 的离线 Markdown 来源与结构覆盖率纯计算。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from app.schemas.files import MarkdownVersionStatus


def _validate_identifiers(name: str, values: object) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise ValueError(f"{name} must be a tuple")
    if any(type(value) is not str or not value.strip() for value in values):
        raise ValueError(f"{name} must contain exact non-empty strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must not contain duplicates")
    return values


@dataclass(frozen=True, slots=True)
class CoverageMetric:
    """保留分子、分母和缺失身份，避免浮点舍入掩盖 100% 门禁。"""

    covered_count: int
    total_count: int
    missing_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.covered_count) is not int or self.covered_count < 0:
            raise ValueError("covered_count must be a non-negative exact integer")
        if type(self.total_count) is not int or self.total_count <= 0:
            raise ValueError("total_count must be a positive exact integer")
        if self.covered_count > self.total_count:
            raise ValueError("covered_count must not exceed total_count")
        missing_ids = _validate_identifiers("missing_ids", self.missing_ids)
        if len(missing_ids) != self.total_count - self.covered_count:
            raise ValueError("missing_ids count must match uncovered items")

    @property
    def ratio(self) -> Fraction:
        return Fraction(self.covered_count, self.total_count)

    @property
    def is_complete(self) -> bool:
        return self.covered_count == self.total_count


@dataclass(frozen=True, slots=True)
class MarkdownQualityMetrics:
    evidence_source_mapping: CoverageMetric
    valid_structure_block: CoverageMetric

    @property
    def activation_coverage_gate_passed(self) -> bool:
        """只表示两项覆盖率均为 100%，不代表其他激活门禁通过。"""

        return self.evidence_source_mapping.is_complete and self.valid_structure_block.is_complete


def is_markdown_activation_eligible(
    *,
    status: MarkdownVersionStatus,
    blocking_issue_count: int,
    metrics: MarkdownQualityMetrics,
) -> bool:
    """仅允许已完成全部质量门禁的 ready 版本激活。"""

    if type(status) is not MarkdownVersionStatus:
        return False
    if type(blocking_issue_count) is not int or blocking_issue_count < 0:
        return False
    if type(metrics) is not MarkdownQualityMetrics:
        return False
    if (
        type(metrics.evidence_source_mapping) is not CoverageMetric
        or type(metrics.valid_structure_block) is not CoverageMetric
    ):
        return False
    return (
        status is MarkdownVersionStatus.READY
        and blocking_issue_count == 0
        and metrics.activation_coverage_gate_passed
    )


def calculate_markdown_quality_metrics(
    *,
    evidence_node_ids: tuple[str, ...],
    mapped_evidence_node_ids: tuple[str, ...],
    valid_block_ids: tuple[str, ...],
    approved_excluded_block_ids: tuple[str, ...],
    represented_block_ids: tuple[str, ...],
) -> MarkdownQualityMetrics:
    """计算证据正文来源映射率与有效结构块覆盖率。

    输入只接受上游已分类的稳定身份；本函数不解析 Markdown、不批准排除项，也不
    执行激活。零分母失败关闭，避免把“不可计算”伪装成 100%。
    """

    evidence_nodes = _validate_identifiers("evidence_node_ids", evidence_node_ids)
    mapped_evidence_nodes = _validate_identifiers(
        "mapped_evidence_node_ids", mapped_evidence_node_ids
    )
    valid_blocks = _validate_identifiers("valid_block_ids", valid_block_ids)
    approved_excluded_blocks = _validate_identifiers(
        "approved_excluded_block_ids", approved_excluded_block_ids
    )
    represented_blocks = _validate_identifiers("represented_block_ids", represented_block_ids)

    evidence_set = set(evidence_nodes)
    mapped_set = set(mapped_evidence_nodes)
    valid_block_set = set(valid_blocks)
    excluded_set = set(approved_excluded_blocks)
    represented_set = set(represented_blocks)

    if not evidence_nodes:
        raise ValueError("evidence_node_ids must not be empty")
    if not mapped_set.issubset(evidence_set):
        raise ValueError("mapped evidence nodes must belong to evidence_node_ids")
    if not excluded_set.issubset(valid_block_set):
        raise ValueError("approved excluded blocks must belong to valid_block_ids")
    if not represented_set.issubset(valid_block_set):
        raise ValueError("represented blocks must belong to valid_block_ids")
    if represented_set & excluded_set:
        raise ValueError("represented blocks must not include approved excluded blocks")

    eligible_blocks = valid_block_set - excluded_set
    if not eligible_blocks:
        raise ValueError("valid block coverage denominator must not be zero")

    missing_evidence = tuple(node_id for node_id in evidence_nodes if node_id not in mapped_set)
    missing_blocks = tuple(
        block_id
        for block_id in valid_blocks
        if block_id in eligible_blocks and block_id not in represented_set
    )
    return MarkdownQualityMetrics(
        evidence_source_mapping=CoverageMetric(
            covered_count=len(evidence_nodes) - len(missing_evidence),
            total_count=len(evidence_nodes),
            missing_ids=missing_evidence,
        ),
        valid_structure_block=CoverageMetric(
            covered_count=len(eligible_blocks) - len(missing_blocks),
            total_count=len(eligible_blocks),
            missing_ids=missing_blocks,
        ),
    )
