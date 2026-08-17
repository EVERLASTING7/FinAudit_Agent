"""AI 详设 8/10/12 的内部离线输出边界；这些 DTO 不是 ``/api/v1`` 合同。"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

_UUID_TEXT_PATTERN: Final = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
UuidText = Annotated[str, StringConstraints(strict=True, pattern=_UUID_TEXT_PATTERN)]
Sha256Text = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
ConfidenceText = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(?:0(?:\.\d+)?|1(?:\.0+)?)$"),
]
RagReasonCode = Literal[
    "NO_RELEVANT_EVIDENCE",
    "EVIDENCE_CONFLICT",
    "UNAUTHORIZED_EVIDENCE",
    "CITATION_VALIDATION_FAILED",
    "MODEL_UNAVAILABLE",
    "PROMPT_INJECTION_DETECTED",
    "INDEX_DRIFT_DETECTED",
    "INDEX_NOT_ACTIVE",
    "RETRIEVAL_UNAVAILABLE",
]


class _StrictFrozenDto(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
    )


class FrozenRuleResult(_StrictFrozenDto):
    """由确定性规则调用方注入、模型不得改写的四个冻结字段。"""

    rule_code: str
    rule_version: str
    rule_status: str
    original_risk_level: str


class RiskCitation(_StrictFrozenDto):
    candidate_id: UuidText
    policy_document_id: UuidText
    chunk_id: UuidText
    quote: str


class RiskExplanationOutput(_StrictFrozenDto):
    rule_code: str
    rule_version: str
    rule_status: str
    original_risk_level: str
    summary: str
    reasoning_summary: str
    business_impact: str | None
    recommended_action: str
    citations: tuple[RiskCitation, ...]
    evidence_sufficient: bool
    warnings: tuple[str, ...]


class RagCitation(_StrictFrozenDto):
    candidate_id: UuidText
    policy_document_id: UuidText
    policy_version: str
    markdown_version_id: UuidText
    chunk_id: UuidText
    block_ids: tuple[UuidText, ...]
    index_version_id: UuidText
    page_range: str
    title_path: tuple[str, ...]
    quote: str
    content_sha256: Sha256Text


class RagAnswerOutput(_StrictFrozenDto):
    answer_status: Literal["answered", "refused", "service_degraded"]
    answer: str | None
    reason_code: RagReasonCode | None
    citations: tuple[RagCitation, ...]
    confidence: ConfidenceText | None
    warnings: tuple[str, ...]

    @model_validator(mode="after")
    def validate_status_matrix(self) -> RagAnswerOutput:
        if self.answer_status == "answered":
            if self.answer is None or not self.answer.strip():
                raise ValueError("answered output requires a non-empty answer")
            if self.reason_code is not None:
                raise ValueError("answered output must not contain a reason code")
            if not self.citations:
                raise ValueError("answered output requires at least one citation")
        elif self.answer_status == "refused":
            if self.answer is not None or self.reason_code is None:
                raise ValueError("refused output requires only a reason code")
            if self.citations or self.confidence is not None:
                raise ValueError("refused output must not contain citations or confidence")
        else:
            if (
                self.answer is not None
                or self.reason_code not in {"MODEL_UNAVAILABLE", "RETRIEVAL_UNAVAILABLE"}
                or self.citations
                or self.confidence is not None
            ):
                raise ValueError("service_degraded output must be a model-unavailable result")
        return self


class RiskExplanationValidationError(Exception):
    """风险解释改写冻结规则事实；错误不携带模型原值。"""

    code = "AI_SCHEMA_VALIDATION_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class CitationValidationError(Exception):
    """引用不属于本次候选；错误不携带答案、引用或候选原值。"""

    code = "CITATION_VALIDATION_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


def _risk_candidates_by_id(
    candidates: tuple[RiskCitation, ...],
) -> dict[str, RiskCitation]:
    indexed = {candidate.candidate_id: candidate for candidate in candidates}
    if len(indexed) != len(candidates):
        raise CitationValidationError
    return indexed


def _rag_candidates_by_id(
    candidates: tuple[RagCitation, ...],
) -> dict[str, RagCitation]:
    indexed = {candidate.candidate_id: candidate for candidate in candidates}
    if len(indexed) != len(candidates):
        raise CitationValidationError
    return indexed


def validate_risk_explanation(
    output: RiskExplanationOutput,
    *,
    frozen_rule: FrozenRuleResult,
    candidates: tuple[RiskCitation, ...],
) -> RiskExplanationOutput:
    """验证模型未改写规则事实，且每个引用逐字段等于本次候选。"""

    frozen_fields = (
        frozen_rule.rule_code,
        frozen_rule.rule_version,
        frozen_rule.rule_status,
        frozen_rule.original_risk_level,
    )
    output_fields = (
        output.rule_code,
        output.rule_version,
        output.rule_status,
        output.original_risk_level,
    )
    if output_fields != frozen_fields:
        raise RiskExplanationValidationError

    indexed = _risk_candidates_by_id(candidates)
    if any(indexed.get(citation.candidate_id) != citation for citation in output.citations):
        raise CitationValidationError
    if output.evidence_sufficient and not output.citations:
        raise RiskExplanationValidationError
    return output


def make_no_relevant_evidence_refusal() -> RagAnswerOutput:
    """为已完成权限/有效期过滤后的空候选集生成固定、安全的内部拒答。"""

    return RagAnswerOutput(
        answer_status="refused",
        answer=None,
        reason_code="NO_RELEVANT_EVIDENCE",
        citations=(),
        confidence=None,
        warnings=(),
    )


def validate_rag_answer(
    output: RagAnswerOutput,
    *,
    candidates: tuple[RagCitation, ...],
) -> RagAnswerOutput:
    """逐字校验模型引用的全部 AI 详设候选身份字段。"""

    if not candidates:
        if output != make_no_relevant_evidence_refusal():
            raise CitationValidationError
        return output

    indexed = _rag_candidates_by_id(candidates)
    if any(indexed.get(citation.candidate_id) != citation for citation in output.citations):
        raise CitationValidationError
    return output
