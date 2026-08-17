from dataclasses import FrozenInstanceError
from decimal import Decimal
from fractions import Fraction
from typing import cast

import pytest

from app.evaluation.retrieval_metrics import (
    EvidenceIdentity,
    NoAnswerFalsePositiveMetrics,
    RankedRetrievalHit,
    RetrievalCaseLabel,
    RetrievalCaseResult,
    RetrievalMetrics,
    calculate_no_answer_false_positive_rate,
    calculate_retrieval_metrics,
)


def evidence(document: str = "DOC-V1", anchor: str = "anchor-1") -> EvidenceIdentity:
    return EvidenceIdentity(document_version=document, anchor_id=anchor)


def hit(
    rank: int,
    document: str = "DOC-V1",
    anchors: tuple[str, ...] = ("anchor-1",),
    *,
    permission_allowed: bool = True,
    score: Decimal | None = None,
) -> RankedRetrievalHit:
    return RankedRetrievalHit(
        rank=rank,
        document_version=document,
        evidence_anchor_ids=anchors,
        permission_allowed=permission_allowed,
        score=score,
    )


def answerable_case(
    case_id: str,
    *,
    expected_documents: tuple[str, ...] = ("DOC-V1",),
    expected_evidence: tuple[EvidenceIdentity, ...] | None = None,
    hits: tuple[RankedRetrievalHit, ...] = (),
) -> RetrievalCaseResult:
    return RetrievalCaseResult(
        case_id=case_id,
        label=RetrievalCaseLabel.ANSWERABLE,
        expected_document_versions=expected_documents,
        expected_evidence=(
            expected_evidence
            if expected_evidence is not None
            else (evidence(expected_documents[0]),)
        ),
        hits=hits,
    )


def no_answer_case(
    case_id: str,
    *,
    hits: tuple[RankedRetrievalHit, ...] = (),
) -> RetrievalCaseResult:
    return RetrievalCaseResult(
        case_id=case_id,
        label=RetrievalCaseLabel.NO_ANSWER,
        expected_document_versions=(),
        expected_evidence=(),
        hits=hits,
    )


def test_calculates_no_answer_high_confidence_false_positive_rate_once_per_case() -> None:
    cases = (
        no_answer_case(
            "false-positive-1",
            hits=(
                hit(1, score=Decimal("0.91")),
                hit(2, score=Decimal("0.99")),
            ),
        ),
        answerable_case("ignored-answerable", hits=(hit(1),)),
        no_answer_case("not-high-confidence", hits=(hit(1, score=Decimal("0.90")),)),
        no_answer_case("empty"),
        no_answer_case("false-positive-2", hits=(hit(1, score=Decimal("0.900001")),)),
    )

    metrics = calculate_no_answer_false_positive_rate(cases, threshold=Decimal("0.90"))

    assert metrics == NoAnswerFalsePositiveMetrics(
        no_answer_case_count=4,
        false_positive_case_count=2,
        rate=Fraction(1, 2),
        false_positive_case_ids=("false-positive-1", "false-positive-2"),
    )


def test_no_answer_score_equal_to_threshold_and_empty_hits_are_not_false_positives() -> None:
    cases = (
        no_answer_case("equal", hits=(hit(1, score=Decimal("0.650000")),)),
        no_answer_case("empty"),
    )

    metrics = calculate_no_answer_false_positive_rate(cases, threshold=Decimal("0.650000"))

    assert metrics.false_positive_case_count == 0
    assert metrics.rate == Fraction(0, 1)
    assert metrics.false_positive_case_ids == ()


def test_no_answer_hit_without_score_fails_closed() -> None:
    with pytest.raises(ValueError, match="no_answer hits require a score"):
        calculate_no_answer_false_positive_rate(
            (no_answer_case("missing-score", hits=(hit(1),)),),
            threshold=Decimal("0.65"),
        )


@pytest.mark.parametrize(
    "invalid",
    [None, 0, 0.65, "0.65", Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_no_answer_metric_rejects_non_exact_or_non_finite_decimal_threshold(
    invalid: object,
) -> None:
    with pytest.raises(ValueError, match="threshold must be a finite Decimal"):
        calculate_no_answer_false_positive_rate(
            (no_answer_case("case"),),
            threshold=cast(Decimal, invalid),
        )


@pytest.mark.parametrize(
    "invalid",
    [0, 0.65, "0.65", Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_rejects_non_exact_or_non_finite_decimal_hit_score(invalid: object) -> None:
    with pytest.raises(ValueError, match="score must be a finite Decimal"):
        hit(1, score=cast(Decimal, invalid))


def test_zero_no_answer_denominator_fails_closed() -> None:
    with pytest.raises(ValueError, match="at least one no_answer case"):
        calculate_no_answer_false_positive_rate(
            (answerable_case("answerable"),),
            threshold=Decimal("0.65"),
        )


def test_no_answer_metric_rejects_duplicate_case_ids() -> None:
    case = no_answer_case("duplicate")

    with pytest.raises(ValueError, match="case_id must be unique"):
        calculate_no_answer_false_positive_rate(
            (case, case),
            threshold=Decimal("0.65"),
        )


def test_calculates_document_evidence_recall_precision_and_mrr() -> None:
    cases = (
        answerable_case(
            "case-1",
            expected_evidence=(evidence(anchor="anchor-1"), evidence(anchor="anchor-2")),
            hits=(
                hit(1, anchors=("anchor-1",)),
                hit(2, anchors=("anchor-1",)),
                hit(3, anchors=("anchor-2",)),
            ),
        ),
        answerable_case(
            "case-2",
            expected_documents=("DOC-V2",),
            expected_evidence=(evidence("DOC-V2", "anchor-3"),),
            hits=(hit(1, "WRONG-DOC", ("anchor-3",)),),
        ),
        answerable_case(
            "case-3",
            expected_documents=("DOC-V3",),
            expected_evidence=(evidence("DOC-V3", "anchor-4"),),
            hits=(
                hit(1, "DOC-V3", ("wrong-anchor",)),
                hit(2, "DOC-V3", ("anchor-4",)),
            ),
        ),
        RetrievalCaseResult(
            case_id="case-no-answer",
            label=RetrievalCaseLabel.NO_ANSWER,
            expected_document_versions=(),
            expected_evidence=(),
            hits=(hit(1, "IRRELEVANT", ("irrelevant",)),),
        ),
    )

    metrics = calculate_retrieval_metrics(cases, k=3)

    assert metrics.k == 3
    assert metrics.answerable_case_count == 3
    assert metrics.document_hit_at_k == pytest.approx(2 / 3)
    assert metrics.evidence_hit_at_k == pytest.approx(2 / 3)
    assert metrics.recall_at_k == pytest.approx(2 / 3)
    assert metrics.precision_at_k == pytest.approx(0.5)
    assert metrics.mrr == pytest.approx(0.5)


def test_evidence_identity_prevents_cross_document_anchor_matches() -> None:
    case = answerable_case(
        "wrong-document",
        expected_documents=("DOC-V2",),
        expected_evidence=(evidence("DOC-V2", "shared-anchor"),),
        hits=(hit(1, "WRONG-DOC", ("shared-anchor",)),),
    )

    metrics = calculate_retrieval_metrics((case,), k=1)

    assert metrics.document_hit_at_k == 0.0
    assert metrics.evidence_hit_at_k == 0.0
    assert metrics.recall_at_k == 0.0
    assert metrics.precision_at_k == 0.0
    assert metrics.mrr == 0.0


def test_repeated_relevant_results_do_not_inflate_recall() -> None:
    case = answerable_case(
        "duplicate-hit",
        expected_evidence=(evidence(anchor="anchor-1"), evidence(anchor="anchor-2")),
        hits=(hit(1), hit(2)),
    )

    metrics = calculate_retrieval_metrics((case,), k=2)

    assert metrics.evidence_hit_at_k == 1.0
    assert metrics.recall_at_k == 0.5
    assert metrics.precision_at_k == 1.0


def test_document_hit_does_not_imply_evidence_hit() -> None:
    case = answerable_case(
        "document-only",
        hits=(hit(1, anchors=("wrong-anchor",)),),
    )

    metrics = calculate_retrieval_metrics((case,), k=1)

    assert metrics.document_hit_at_k == 1.0
    assert metrics.evidence_hit_at_k == 0.0


def test_precision_uses_actual_returned_results_when_fewer_than_k() -> None:
    case = answerable_case(
        "short-result",
        hits=(hit(1), hit(2, anchors=("wrong-anchor",))),
    )

    assert calculate_retrieval_metrics((case,), k=5).precision_at_k == 0.5


def test_plain_mrr_uses_the_saved_sparse_rank() -> None:
    case = answerable_case("sparse-rank", hits=(hit(2),))

    metrics = calculate_retrieval_metrics((case,), k=2)

    assert metrics.mrr == 0.5


def test_answerable_miss_is_a_real_zero_percent_result() -> None:
    metrics = calculate_retrieval_metrics((answerable_case("miss"),), k=5)

    assert metrics == RetrievalMetrics(
        k=5,
        answerable_case_count=1,
        document_hit_at_k=0.0,
        evidence_hit_at_k=0.0,
        recall_at_k=0.0,
        precision_at_k=0.0,
        mrr=0.0,
    )


@pytest.mark.parametrize(
    "cases",
    [
        (),
        (
            RetrievalCaseResult(
                case_id="no-answer",
                label=RetrievalCaseLabel.NO_ANSWER,
                expected_document_versions=(),
                expected_evidence=(),
                hits=(),
            ),
            RetrievalCaseResult(
                case_id="unauthorized",
                label=RetrievalCaseLabel.UNAUTHORIZED,
                expected_document_versions=(),
                expected_evidence=(),
                hits=(),
            ),
        ),
    ],
)
def test_zero_answerable_denominator_fails_closed(
    cases: tuple[RetrievalCaseResult, ...],
) -> None:
    with pytest.raises(ValueError, match="at least one answerable case"):
        calculate_retrieval_metrics(cases, k=5)


def test_relevance_metrics_reject_permission_filter_leaks() -> None:
    with pytest.raises(ValueError, match="permission-filtered hits"):
        RetrievalCaseResult(
            case_id="unauthorized-leak",
            label=RetrievalCaseLabel.UNAUTHORIZED,
            expected_document_versions=(),
            expected_evidence=(),
            hits=(hit(1, "SECRET-V1", (), permission_allowed=False),),
        )


def test_non_answerable_authorized_results_do_not_change_relevance_denominator() -> None:
    no_answer = RetrievalCaseResult(
        case_id="no-answer",
        label=RetrievalCaseLabel.NO_ANSWER,
        expected_document_versions=(),
        expected_evidence=(),
        hits=(hit(1, "PUBLIC-IRRELEVANT", ()),),
    )

    metrics = calculate_retrieval_metrics((answerable_case("answerable"), no_answer), k=1)

    assert metrics.answerable_case_count == 1
    assert metrics.document_hit_at_k == 0.0


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5, None])
def test_rejects_invalid_k(invalid: object) -> None:
    with pytest.raises(ValueError, match="k must be a positive integer"):
        calculate_retrieval_metrics((), k=cast(int, invalid))


def test_rejects_int_subclass_k() -> None:
    class LyingInt(int):
        pass

    with pytest.raises(ValueError, match="k must be a positive integer"):
        calculate_retrieval_metrics((), k=LyingInt(1))


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5])
def test_rejects_invalid_rank(invalid: object) -> None:
    with pytest.raises(ValueError, match="rank must be a positive integer"):
        RankedRetrievalHit(
            rank=cast(int, invalid),
            document_version="DOC-V1",
            evidence_anchor_ids=(),
            permission_allowed=True,
        )


@pytest.mark.parametrize(
    "hits",
    [
        (hit(1), hit(1)),
        (hit(2), hit(1)),
    ],
)
def test_rejects_duplicate_or_out_of_order_ranks(
    hits: tuple[RankedRetrievalHit, ...],
) -> None:
    with pytest.raises(ValueError, match="unique and strictly increasing"):
        answerable_case("bad-ranks", hits=hits)


def test_rejects_rank_above_the_frozen_k() -> None:
    with pytest.raises(ValueError, match="rank must not exceed"):
        calculate_retrieval_metrics((answerable_case("rank", hits=(hit(2),)),), k=1)


@pytest.mark.parametrize(
    ("expected_documents", "expected_evidence", "error"),
    [
        ((), (evidence(),), "expected_document_versions"),
        (("DOC-V1",), (), "expected_evidence"),
        (("DOC-V1", "DOC-V1"), (evidence(),), "must not contain duplicates"),
        (("DOC-V1",), (evidence(), evidence()), "must not contain duplicates"),
        (("DOC-V1",), (evidence("DOC-V2"),), "must belong"),
        (("",), (evidence(),), "non-empty strings"),
    ],
)
def test_rejects_invalid_answerable_ground_truth(
    expected_documents: tuple[str, ...],
    expected_evidence: tuple[EvidenceIdentity, ...],
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        answerable_case(
            "bad-ground-truth",
            expected_documents=expected_documents,
            expected_evidence=expected_evidence,
        )


@pytest.mark.parametrize(
    "label",
    [RetrievalCaseLabel.NO_ANSWER, RetrievalCaseLabel.UNAUTHORIZED],
)
def test_non_answerable_cases_reject_ground_truth(label: RetrievalCaseLabel) -> None:
    with pytest.raises(ValueError, match="must not contain expected ground truth"):
        RetrievalCaseResult(
            case_id="non-answerable",
            label=label,
            expected_document_versions=("DOC-V1",),
            expected_evidence=(),
            hits=(),
        )


def test_rejects_duplicate_case_ids() -> None:
    case = answerable_case("duplicate-case")

    with pytest.raises(ValueError, match="case_id must be unique"):
        calculate_retrieval_metrics((case, case), k=1)


def test_contracts_are_immutable() -> None:
    identity = evidence()
    ranked_hit = hit(1)
    case = answerable_case("immutable", hits=(ranked_hit,))
    metrics = calculate_retrieval_metrics((case,), k=1)
    no_answer_metrics = calculate_no_answer_false_positive_rate(
        (no_answer_case("no-answer"),),
        threshold=Decimal("0.65"),
    )

    with pytest.raises(FrozenInstanceError):
        EvidenceIdentity.__setattr__(identity, "anchor_id", "changed")
    with pytest.raises(FrozenInstanceError):
        RankedRetrievalHit.__setattr__(ranked_hit, "rank", 2)
    with pytest.raises(FrozenInstanceError):
        RetrievalCaseResult.__setattr__(case, "case_id", "changed")
    with pytest.raises(FrozenInstanceError):
        RetrievalMetrics.__setattr__(metrics, "mrr", 0.0)
    with pytest.raises(FrozenInstanceError):
        NoAnswerFalsePositiveMetrics.__setattr__(no_answer_metrics, "rate", Fraction(1, 1))
