"""AI 详设内部输出 DTO 回归；本文件不测试或声明 ``/api/v1`` 合同。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from app.ai.output_validation import (
    CitationValidationError,
    FrozenRuleResult,
    RagAnswerOutput,
    RagCitation,
    RiskCitation,
    RiskExplanationOutput,
    RiskExplanationValidationError,
    make_no_relevant_evidence_refusal,
    validate_rag_answer,
    validate_risk_explanation,
)

CANDIDATE_ID_1 = "10000000-0000-0000-0000-000000000001"
CANDIDATE_ID_2 = "10000000-0000-0000-0000-000000000002"
POLICY_ID_1 = "20000000-0000-0000-0000-000000000001"
POLICY_ID_2 = "20000000-0000-0000-0000-000000000002"
MARKDOWN_ID_1 = "30000000-0000-0000-0000-000000000001"
MARKDOWN_ID_2 = "30000000-0000-0000-0000-000000000002"
CHUNK_ID_1 = "40000000-0000-0000-0000-000000000001"
CHUNK_ID_2 = "40000000-0000-0000-0000-000000000002"
INDEX_ID_1 = "50000000-0000-0000-0000-000000000001"
INDEX_ID_2 = "50000000-0000-0000-0000-000000000002"


def _frozen_rule() -> FrozenRuleResult:
    return FrozenRuleResult(
        rule_code="RULE-003",
        rule_version="1.0.0",
        rule_status="failed",
        original_risk_level="high",
    )


def _risk_candidate(
    candidate_id: str = CANDIDATE_ID_1,
    policy_document_id: str = POLICY_ID_1,
    chunk_id: str = CHUNK_ID_1,
    quote: str = "approved policy evidence",
) -> RiskCitation:
    return RiskCitation(
        candidate_id=candidate_id,
        policy_document_id=policy_document_id,
        chunk_id=chunk_id,
        quote=quote,
    )


def _risk_output(
    *,
    citations: tuple[RiskCitation, ...] | None = None,
    **updates: str,
) -> RiskExplanationOutput:
    payload: dict[str, object] = {
        **_frozen_rule().model_dump(),
        "summary": "The deterministic rule failed.",
        "reasoning_summary": "The observed value exceeded the frozen threshold.",
        "business_impact": None,
        "recommended_action": "Review the source documents.",
        "citations": citations if citations is not None else (_risk_candidate(),),
        "evidence_sufficient": True,
        "warnings": (),
        **updates,
    }
    return RiskExplanationOutput.model_validate(payload)


def _rag_candidate(
    candidate_id: str = CANDIDATE_ID_1,
    policy_document_id: str = POLICY_ID_1,
    policy_version: str = "1.0.0",
    markdown_version_id: str = MARKDOWN_ID_1,
    chunk_id: str = CHUNK_ID_1,
    index_version_id: str = INDEX_ID_1,
    page_range: str = "1-2",
    title_path: tuple[str, ...] = ("Payments", "Approval"),
    quote: str = "approved RAG evidence",
    block_ids: tuple[str, ...] = ("77777777-7777-4777-8777-777777777777",),
    content_sha256: str = "a" * 64,
) -> RagCitation:
    return RagCitation(
        candidate_id=candidate_id,
        policy_document_id=policy_document_id,
        policy_version=policy_version,
        markdown_version_id=markdown_version_id,
        chunk_id=chunk_id,
        block_ids=block_ids,
        index_version_id=index_version_id,
        page_range=page_range,
        title_path=title_path,
        quote=quote,
        content_sha256=content_sha256,
    )


def _rag_output(citation: RagCitation, answer: str = "Supported answer") -> RagAnswerOutput:
    return RagAnswerOutput(
        answer_status="answered",
        answer=answer,
        reason_code=None,
        citations=(citation,),
        confidence="0.91",
        warnings=(),
    )


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("rule_code", "RULE-999"),
        ("rule_version", "9.9.9"),
        ("rule_status", "passed"),
        ("original_risk_level", "low"),
    ],
)
def test_risk_explanation_rejects_any_frozen_rule_field_tampering(
    field: str,
    tampered: str,
) -> None:
    output = _risk_output().model_copy(update={field: tampered})

    with pytest.raises(RiskExplanationValidationError) as exc_info:
        validate_risk_explanation(
            output,
            frozen_rule=_frozen_rule(),
            candidates=(_risk_candidate(),),
        )

    assert exc_info.value.code == "AI_SCHEMA_VALIDATION_FAILED"
    assert exc_info.value.args == ("AI_SCHEMA_VALIDATION_FAILED",)


def test_risk_explanation_accepts_exact_frozen_fields_and_candidate() -> None:
    output = _risk_output()

    assert (
        validate_risk_explanation(
            output,
            frozen_rule=_frozen_rule(),
            candidates=(_risk_candidate(),),
        )
        is output
    )


def test_risk_explanation_rejects_cross_candidate_field_splicing() -> None:
    first = _risk_candidate()
    second = _risk_candidate(
        candidate_id=CANDIDATE_ID_2,
        policy_document_id=POLICY_ID_2,
        chunk_id=CHUNK_ID_2,
        quote="second evidence",
    )
    spliced = _risk_candidate(
        candidate_id=first.candidate_id,
        policy_document_id=second.policy_document_id,
        chunk_id=second.chunk_id,
        quote=second.quote,
    )

    with pytest.raises(CitationValidationError):
        validate_risk_explanation(
            _risk_output(citations=(spliced,)),
            frozen_rule=_frozen_rule(),
            candidates=(first, second),
        )


def test_risk_explanation_rejects_forged_candidate_id() -> None:
    forged = _risk_candidate(candidate_id=CANDIDATE_ID_2)

    with pytest.raises(CitationValidationError):
        validate_risk_explanation(
            _risk_output(citations=(forged,)),
            frozen_rule=_frozen_rule(),
            candidates=(_risk_candidate(),),
        )


def test_empty_candidate_factory_returns_fixed_no_evidence_refusal() -> None:
    refusal = make_no_relevant_evidence_refusal()

    assert refusal.model_dump(mode="json") == {
        "answer_status": "refused",
        "answer": None,
        "reason_code": "NO_RELEVANT_EVIDENCE",
        "citations": [],
        "confidence": None,
        "warnings": [],
    }
    assert validate_rag_answer(refusal, candidates=()) is refusal


def test_empty_candidates_cannot_accept_an_answer() -> None:
    with pytest.raises(ValidationError, match="requires at least one citation"):
        RagAnswerOutput(
            answer_status="answered",
            answer="unsupported answer",
            reason_code=None,
            citations=(),
            confidence="0.9",
            warnings=(),
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"answer": "leaked answer"},
        {"citations": (_rag_candidate(),)},
        {"confidence": "0.9"},
        {"reason_code": None},
    ],
)
def test_refused_status_cannot_carry_answer_evidence_or_confidence(
    updates: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "answer_status": "refused",
        "answer": None,
        "reason_code": "NO_RELEVANT_EVIDENCE",
        "citations": (),
        "confidence": None,
        "warnings": (),
        **updates,
    }

    with pytest.raises(ValidationError):
        RagAnswerOutput.model_validate(payload)


@pytest.mark.parametrize("confidence", ["not-a-decimal", "-0.1", "1.1", "NaN"])
def test_confidence_is_a_zero_to_one_decimal_string(confidence: str) -> None:
    payload = _rag_output(_rag_candidate()).model_dump()
    payload["confidence"] = confidence

    with pytest.raises(ValidationError):
        RagAnswerOutput.model_validate(payload)


def test_service_degraded_has_a_single_safe_state() -> None:
    output = RagAnswerOutput(
        answer_status="service_degraded",
        answer=None,
        reason_code="MODEL_UNAVAILABLE",
        citations=(),
        confidence=None,
        warnings=(),
    )

    assert output.reason_code == "MODEL_UNAVAILABLE"

    payload = output.model_dump()
    payload["answer"] = "unsupported"
    with pytest.raises(ValidationError):
        RagAnswerOutput.model_validate(payload)


def test_risk_explanation_cannot_claim_sufficient_evidence_without_citations() -> None:
    with pytest.raises(RiskExplanationValidationError):
        validate_risk_explanation(
            _risk_output(citations=()),
            frozen_rule=_frozen_rule(),
            candidates=(),
        )

    insufficient = _risk_output(citations=()).model_copy(update={"evidence_sufficient": False})
    assert (
        validate_risk_explanation(
            insufficient,
            frozen_rule=_frozen_rule(),
            candidates=(),
        )
        is insufficient
    )


def test_rag_answer_accepts_a_verbatim_candidate_citation() -> None:
    candidate = _rag_candidate()
    output = _rag_output(candidate)

    assert validate_rag_answer(output, candidates=(candidate,)) is output


@pytest.mark.parametrize("forged_id", [CANDIDATE_ID_2])
def test_rag_answer_rejects_forged_candidate_id(forged_id: str) -> None:
    candidate = _rag_candidate()
    forged = candidate.model_copy(update={"candidate_id": forged_id})

    with pytest.raises(CitationValidationError) as exc_info:
        validate_rag_answer(_rag_output(forged), candidates=(candidate,))

    assert exc_info.value.code == "CITATION_VALIDATION_FAILED"


def test_rag_answer_rejects_cross_candidate_identity_splicing() -> None:
    first = _rag_candidate()
    second = _rag_candidate(
        candidate_id=CANDIDATE_ID_2,
        policy_document_id=POLICY_ID_2,
        policy_version="2.0.0",
        markdown_version_id=MARKDOWN_ID_2,
        chunk_id=CHUNK_ID_2,
        index_version_id=INDEX_ID_2,
        page_range="7-8",
        title_path=("Expenses",),
        quote="second RAG evidence",
    )
    spliced = first.model_copy(
        update={
            "policy_document_id": second.policy_document_id,
            "policy_version": second.policy_version,
            "markdown_version_id": second.markdown_version_id,
            "chunk_id": second.chunk_id,
            "index_version_id": second.index_version_id,
            "page_range": second.page_range,
            "title_path": second.title_path,
            "quote": second.quote,
        }
    )

    with pytest.raises(CitationValidationError):
        validate_rag_answer(_rag_output(spliced), candidates=(first, second))


def test_citation_error_contains_only_fixed_code_not_raw_answer_or_quote() -> None:
    sentinel = "SENSITIVE_MODEL_VALUE_MUST_NOT_ESCAPE"
    candidate = _rag_candidate()
    mismatched = candidate.model_copy(update={"quote": sentinel})

    with pytest.raises(CitationValidationError) as exc_info:
        validate_rag_answer(_rag_output(mismatched, answer=sentinel), candidates=(candidate,))

    rendered = "\n".join((str(exc_info.value), repr(exc_info.value), repr(exc_info.value.args)))
    assert rendered.count("CITATION_VALIDATION_FAILED") == 3
    assert sentinel not in rendered


def test_dtos_are_frozen_strict_and_extra_forbid() -> None:
    output = _rag_output(_rag_candidate())

    with pytest.raises(ValidationError):
        output.answer = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        RagAnswerOutput.model_validate(
            {
                **output.model_dump(),
                "citations": list(output.citations),
            }
        )
    with pytest.raises(ValidationError):
        RagAnswerOutput.model_validate({**output.model_dump(), "unexpected": "field"})
    with pytest.raises(ValidationError):
        RiskCitation.model_validate(
            {
                **_risk_candidate().model_dump(),
                "candidate_id": 1,
            }
        )


def test_nested_dtos_cannot_be_mutated() -> None:
    citation = _rag_candidate()

    with pytest.raises(ValidationError):
        citation.quote = "changed"  # type: ignore[misc]
    with pytest.raises((AttributeError, FrozenInstanceError)):
        citation.title_path.append("changed")  # type: ignore[attr-defined]
