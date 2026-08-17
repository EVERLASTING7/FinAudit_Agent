"""KB-011 的离线检索指标纯函数。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction


class RetrievalCaseLabel(str, Enum):
    """检索评测用例的业务分类。"""

    ANSWERABLE = "answerable"
    NO_ANSWER = "no_answer"
    UNAUTHORIZED = "unauthorized"


def _require_positive_integer(name: str, value: object) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_identifiers(name: str, values: object) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be a tuple")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{name} must contain only non-empty strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must not contain duplicates")


def _require_finite_decimal(name: str, value: object) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")


@dataclass(frozen=True, slots=True)
class EvidenceIdentity:
    """证据锚点的最小复合身份，禁止跨制度版本误命中。"""

    document_version: str
    anchor_id: str

    def __post_init__(self) -> None:
        _validate_identifiers("document_version", (self.document_version,))
        _validate_identifiers("anchor_id", (self.anchor_id,))


@dataclass(frozen=True, slots=True)
class RankedRetrievalHit:
    """已按制度版本和证据锚点分类的单条检索结果。"""

    rank: int
    document_version: str
    evidence_anchor_ids: tuple[str, ...]
    permission_allowed: bool
    score: Decimal | None = None

    def __post_init__(self) -> None:
        _require_positive_integer("rank", self.rank)
        if not isinstance(self.document_version, str) or not self.document_version.strip():
            raise ValueError("document_version must be a non-empty string")
        _validate_identifiers("evidence_anchor_ids", self.evidence_anchor_ids)
        if type(self.permission_allowed) is not bool:
            raise ValueError("permission_allowed must be a boolean")
        if self.score is not None:
            _require_finite_decimal("score", self.score)


@dataclass(frozen=True, slots=True)
class RetrievalCaseResult:
    """一个已分类评测用例的标准答案与实际排名结果。"""

    case_id: str
    label: RetrievalCaseLabel
    expected_document_versions: tuple[str, ...]
    expected_evidence: tuple[EvidenceIdentity, ...]
    hits: tuple[RankedRetrievalHit, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ValueError("case_id must be a non-empty string")
        if not isinstance(self.label, RetrievalCaseLabel):
            raise ValueError("label must be a RetrievalCaseLabel")
        _validate_identifiers(
            "expected_document_versions",
            self.expected_document_versions,
        )
        if not isinstance(self.expected_evidence, tuple) or any(
            not isinstance(evidence, EvidenceIdentity) for evidence in self.expected_evidence
        ):
            raise ValueError("expected_evidence must be a tuple of EvidenceIdentity")
        if len(self.expected_evidence) != len(set(self.expected_evidence)):
            raise ValueError("expected_evidence must not contain duplicates")
        if self.label is RetrievalCaseLabel.ANSWERABLE:
            if not self.expected_document_versions:
                raise ValueError("answerable cases require expected_document_versions")
            if not self.expected_evidence:
                raise ValueError("answerable cases require expected_evidence")
            if any(
                evidence.document_version not in self.expected_document_versions
                for evidence in self.expected_evidence
            ):
                raise ValueError("expected evidence must belong to an expected document version")
        elif self.expected_document_versions or self.expected_evidence:
            raise ValueError("non-answerable cases must not contain expected ground truth")

        if not isinstance(self.hits, tuple) or any(
            not isinstance(hit, RankedRetrievalHit) for hit in self.hits
        ):
            raise ValueError("hits must be a tuple of RankedRetrievalHit")
        if any(not hit.permission_allowed for hit in self.hits):
            raise ValueError("relevance metrics require permission-filtered hits")
        ranks = tuple(hit.rank for hit in self.hits)
        if len(ranks) != len(set(ranks)) or ranks != tuple(sorted(ranks)):
            raise ValueError("hit ranks must be unique and strictly increasing")


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    """可复算的检索指标汇总。"""

    k: int
    answerable_case_count: int
    document_hit_at_k: float
    evidence_hit_at_k: float
    recall_at_k: float
    precision_at_k: float
    mrr: float


@dataclass(frozen=True, slots=True)
class NoAnswerFalsePositiveMetrics:
    """无答案用例中超过冻结答案阈值的误召回汇总。"""

    no_answer_case_count: int
    false_positive_case_count: int
    rate: Fraction
    false_positive_case_ids: tuple[str, ...]


def calculate_retrieval_metrics(
    cases: tuple[RetrievalCaseResult, ...],
    *,
    k: int,
) -> RetrievalMetrics:
    """计算文档/证据 Hit@K、证据 Recall@K 和证据 MRR。

    Hit@K、Recall@K、Precision@K 与 MRR 都只以可回答用例为分母；未命中用例
    贡献 0。Precision@K 逐题以实际 Top-K 返回结果为分母，再做宏平均。调用方必须
    传入本次冻结 K 内已保存的实际排名；无可回答用例时失败关闭，避免把不可计算
    伪装成 0%。
    """

    _require_positive_integer("k", k)
    if not isinstance(cases, tuple) or any(
        not isinstance(case, RetrievalCaseResult) for case in cases
    ):
        raise ValueError("cases must be a tuple of RetrievalCaseResult")
    case_ids = tuple(case.case_id for case in cases)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case_id must be unique within a metric calculation")
    if any(hit.rank > k for case in cases for hit in case.hits):
        raise ValueError("hit rank must not exceed the metric k")

    answerable_cases = tuple(case for case in cases if case.label is RetrievalCaseLabel.ANSWERABLE)
    denominator = len(answerable_cases)
    if denominator == 0:
        raise ValueError("at least one answerable case is required")

    document_hits = 0
    evidence_hits = 0
    recall_total = 0.0
    precision_total = 0.0
    reciprocal_rank_total = 0.0

    for case in answerable_cases:
        expected_documents = set(case.expected_document_versions)
        expected_evidence = set(case.expected_evidence)
        top_k_hits = case.hits

        if any(hit.document_version in expected_documents for hit in top_k_hits):
            document_hits += 1

        found_evidence = {
            EvidenceIdentity(hit.document_version, anchor_id)
            for hit in top_k_hits
            for anchor_id in hit.evidence_anchor_ids
            if EvidenceIdentity(hit.document_version, anchor_id) in expected_evidence
        }
        if found_evidence:
            evidence_hits += 1
        recall_total += len(found_evidence) / len(expected_evidence)
        correct_result_count = sum(
            any(
                EvidenceIdentity(hit.document_version, anchor_id) in expected_evidence
                for anchor_id in hit.evidence_anchor_ids
            )
            for hit in top_k_hits
        )
        precision_total += correct_result_count / len(top_k_hits) if top_k_hits else 0.0

        first_correct_rank = next(
            (
                hit.rank
                for hit in case.hits
                if any(
                    EvidenceIdentity(hit.document_version, anchor_id) in expected_evidence
                    for anchor_id in hit.evidence_anchor_ids
                )
            ),
            None,
        )
        if first_correct_rank is not None:
            reciprocal_rank_total += 1 / first_correct_rank

    return RetrievalMetrics(
        k=k,
        answerable_case_count=denominator,
        document_hit_at_k=document_hits / denominator,
        evidence_hit_at_k=evidence_hits / denominator,
        recall_at_k=recall_total / denominator,
        precision_at_k=precision_total / denominator,
        mrr=reciprocal_rank_total / denominator,
    )


def calculate_no_answer_false_positive_rate(
    cases: tuple[RetrievalCaseResult, ...],
    *,
    threshold: Decimal,
) -> NoAnswerFalsePositiveMetrics:
    """计算无答案用例中存在分数严格超过冻结阈值的用例比例。"""

    _require_finite_decimal("threshold", threshold)
    if not isinstance(cases, tuple) or any(
        not isinstance(case, RetrievalCaseResult) for case in cases
    ):
        raise ValueError("cases must be a tuple of RetrievalCaseResult")
    case_ids = tuple(case.case_id for case in cases)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case_id must be unique within a metric calculation")

    no_answer_cases = tuple(case for case in cases if case.label is RetrievalCaseLabel.NO_ANSWER)
    if not no_answer_cases:
        raise ValueError("at least one no_answer case is required")
    if any(hit.score is None for case in no_answer_cases for hit in case.hits):
        raise ValueError("no_answer hits require a score")

    false_positive_case_ids = tuple(
        case.case_id
        for case in no_answer_cases
        if any(hit.score > threshold for hit in case.hits if hit.score is not None)
    )
    false_positive_case_count = len(false_positive_case_ids)
    no_answer_case_count = len(no_answer_cases)
    return NoAnswerFalsePositiveMetrics(
        no_answer_case_count=no_answer_case_count,
        false_positive_case_count=false_positive_case_count,
        rate=Fraction(false_positive_case_count, no_answer_case_count),
        false_positive_case_ids=false_positive_case_ids,
    )
