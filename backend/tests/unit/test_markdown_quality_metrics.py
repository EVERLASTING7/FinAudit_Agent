from dataclasses import FrozenInstanceError
from fractions import Fraction
from typing import cast

import pytest

from app.markdown.quality_metrics import (
    CoverageMetric,
    MarkdownQualityMetrics,
    calculate_markdown_quality_metrics,
    is_markdown_activation_eligible,
)
from app.schemas.files import MarkdownVersionStatus


def calculate_complete_metrics() -> MarkdownQualityMetrics:
    return calculate_markdown_quality_metrics(
        evidence_node_ids=("node-1", "node-2"),
        mapped_evidence_node_ids=("node-1", "node-2"),
        valid_block_ids=("block-1", "block-2", "block-excluded"),
        approved_excluded_block_ids=("block-excluded",),
        represented_block_ids=("block-1", "block-2"),
    )


def test_complete_quality_metrics_pass_only_the_two_coverage_gates() -> None:
    metrics = calculate_complete_metrics()

    assert metrics.evidence_source_mapping == CoverageMetric(2, 2, ())
    assert metrics.valid_structure_block == CoverageMetric(2, 2, ())
    assert metrics.evidence_source_mapping.ratio == Fraction(1, 1)
    assert metrics.valid_structure_block.ratio == Fraction(1, 1)
    assert metrics.activation_coverage_gate_passed is True


def test_markdown_activation_requires_ready_zero_blockers_and_complete_coverage() -> None:
    assert (
        is_markdown_activation_eligible(
            status=MarkdownVersionStatus.READY,
            blocking_issue_count=0,
            metrics=calculate_complete_metrics(),
        )
        is True
    )


@pytest.mark.parametrize(
    "status",
    [
        *(status for status in MarkdownVersionStatus if status is not MarkdownVersionStatus.READY),
        "ready",
        "unknown",
        None,
    ],
)
def test_markdown_activation_rejects_non_ready_or_non_enum_status(status: object) -> None:
    assert (
        is_markdown_activation_eligible(
            status=cast(MarkdownVersionStatus, status),
            blocking_issue_count=0,
            metrics=calculate_complete_metrics(),
        )
        is False
    )


@pytest.mark.parametrize("blocking_issue_count", [1, -1, True, 0.0, "0", None])
def test_markdown_activation_rejects_blockers_or_invalid_counts(
    blocking_issue_count: object,
) -> None:
    assert (
        is_markdown_activation_eligible(
            status=MarkdownVersionStatus.READY,
            blocking_issue_count=cast(int, blocking_issue_count),
            metrics=calculate_complete_metrics(),
        )
        is False
    )


def test_markdown_activation_requires_both_coverage_metrics_to_be_complete() -> None:
    mapping_incomplete = calculate_markdown_quality_metrics(
        evidence_node_ids=("node-1", "node-2"),
        mapped_evidence_node_ids=("node-1",),
        valid_block_ids=("block-1",),
        approved_excluded_block_ids=(),
        represented_block_ids=("block-1",),
    )
    structure_incomplete = calculate_markdown_quality_metrics(
        evidence_node_ids=("node-1",),
        mapped_evidence_node_ids=("node-1",),
        valid_block_ids=("block-1", "block-2"),
        approved_excluded_block_ids=(),
        represented_block_ids=("block-1",),
    )

    for metrics in (mapping_incomplete, structure_incomplete):
        assert (
            is_markdown_activation_eligible(
                status=MarkdownVersionStatus.READY,
                blocking_issue_count=0,
                metrics=metrics,
            )
            is False
        )


@pytest.mark.parametrize(
    "metrics",
    [
        object(),
        MarkdownQualityMetrics(
            evidence_source_mapping=cast(CoverageMetric, object()),
            valid_structure_block=CoverageMetric(1, 1, ()),
        ),
    ],
)
def test_markdown_activation_rejects_invalid_metric_contracts(metrics: object) -> None:
    assert (
        is_markdown_activation_eligible(
            status=MarkdownVersionStatus.READY,
            blocking_issue_count=0,
            metrics=cast(MarkdownQualityMetrics, metrics),
        )
        is False
    )


def test_partial_metrics_preserve_exact_ratios_and_stable_missing_ids() -> None:
    metrics = calculate_markdown_quality_metrics(
        evidence_node_ids=("node-1", "node-2", "node-3"),
        mapped_evidence_node_ids=("node-2",),
        valid_block_ids=("block-1", "block-2", "block-3"),
        approved_excluded_block_ids=(),
        represented_block_ids=("block-2",),
    )

    assert metrics.evidence_source_mapping == CoverageMetric(
        covered_count=1,
        total_count=3,
        missing_ids=("node-1", "node-3"),
    )
    assert metrics.evidence_source_mapping.ratio == Fraction(1, 3)
    assert metrics.valid_structure_block == CoverageMetric(
        covered_count=1,
        total_count=3,
        missing_ids=("block-1", "block-3"),
    )
    assert metrics.valid_structure_block.ratio == Fraction(1, 3)
    assert metrics.activation_coverage_gate_passed is False


def test_approved_exclusions_are_removed_from_the_structure_denominator() -> None:
    metrics = calculate_markdown_quality_metrics(
        evidence_node_ids=("node-1",),
        mapped_evidence_node_ids=("node-1",),
        valid_block_ids=("block-1", "block-2"),
        approved_excluded_block_ids=("block-2",),
        represented_block_ids=("block-1",),
    )

    assert metrics.valid_structure_block == CoverageMetric(1, 1, ())


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"evidence_node_ids": ()}, "evidence_node_ids must not be empty"),
        (
            {"mapped_evidence_node_ids": ("unknown",)},
            "mapped evidence nodes must belong",
        ),
        (
            {"approved_excluded_block_ids": ("unknown",)},
            "approved excluded blocks must belong",
        ),
        ({"represented_block_ids": ("unknown",)}, "represented blocks must belong"),
        (
            {
                "valid_block_ids": ("included", "excluded"),
                "approved_excluded_block_ids": ("excluded",),
                "represented_block_ids": ("included", "excluded"),
            },
            "must not include approved excluded blocks",
        ),
        (
            {
                "valid_block_ids": ("only",),
                "approved_excluded_block_ids": ("only",),
                "represented_block_ids": (),
            },
            "denominator must not be zero",
        ),
    ],
)
def test_invalid_or_unprovable_coverage_inputs_fail_closed(
    overrides: dict[str, tuple[str, ...]],
    message: str,
) -> None:
    inputs = {
        "evidence_node_ids": ("node-1",),
        "mapped_evidence_node_ids": ("node-1",),
        "valid_block_ids": ("block-1",),
        "approved_excluded_block_ids": (),
        "represented_block_ids": ("block-1",),
    }
    inputs.update(overrides)

    with pytest.raises(ValueError, match=message):
        calculate_markdown_quality_metrics(**inputs)


@pytest.mark.parametrize(
    "invalid",
    [
        ["node-1"],
        ("node-1", "node-1"),
        ("",),
        (" ",),
        (1,),
    ],
)
def test_identifier_collections_are_exact_unique_non_empty_string_tuples(
    invalid: object,
) -> None:
    with pytest.raises(ValueError):
        calculate_markdown_quality_metrics(
            evidence_node_ids=cast(tuple[str, ...], invalid),
            mapped_evidence_node_ids=(),
            valid_block_ids=("block-1",),
            approved_excluded_block_ids=(),
            represented_block_ids=("block-1",),
        )


def test_identifier_collections_reject_tuple_subclasses() -> None:
    class MutableTuple(tuple[str, ...]):
        pass

    with pytest.raises(ValueError, match="must be a tuple"):
        calculate_markdown_quality_metrics(
            evidence_node_ids=cast(tuple[str, ...], MutableTuple(("node-1",))),
            mapped_evidence_node_ids=("node-1",),
            valid_block_ids=("block-1",),
            approved_excluded_block_ids=(),
            represented_block_ids=("block-1",),
        )


def test_quality_metric_contracts_are_immutable() -> None:
    metrics = calculate_complete_metrics()

    with pytest.raises(FrozenInstanceError):
        CoverageMetric.__setattr__(metrics.evidence_source_mapping, "covered_count", 0)
    with pytest.raises(FrozenInstanceError):
        MarkdownQualityMetrics.__setattr__(
            metrics,
            "valid_structure_block",
            metrics.evidence_source_mapping,
        )


@pytest.mark.parametrize(
    ("covered_count", "total_count", "missing_ids"),
    [
        (-1, 1, ("missing",)),
        (True, 1, ()),
        (0, 0, ()),
        (2, 1, ()),
        (1, 2, ()),
        (0, 2, ("duplicate", "duplicate")),
    ],
)
def test_invalid_coverage_metric_contracts_fail_closed(
    covered_count: int,
    total_count: int,
    missing_ids: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        CoverageMetric(covered_count, total_count, missing_ids)
