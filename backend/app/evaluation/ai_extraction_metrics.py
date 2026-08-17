"""真实 AI 提取质量门槛的确定性、可复算计算边界。"""

from __future__ import annotations

from fractions import Fraction
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from app.schemas.contracts import CONTRACT_CORE_FIELD_CODES
from app.schemas.invoices import INVOICE_CORE_FIELD_CODES

NormalizedFactValue = str | bool | None
AiOperationId = Literal[
    "contract_field_extraction",
    "invoice_field_extraction",
    "rag_answer",
    "risk_explanation",
    "report_draft",
]

CONTRACT_ACCURACY_THRESHOLD = Fraction(85, 100)
INVOICE_ACCURACY_THRESHOLD = Fraction(95, 100)
STRUCTURED_OUTPUT_VALIDITY_THRESHOLD = Fraction(99, 100)


def _validate_fact_map(
    value: object,
    *,
    field_codes: tuple[str, ...],
) -> dict[str, NormalizedFactValue]:
    if type(value) is not dict or set(value) != set(field_codes):
        raise ValueError("facts must contain every frozen core field exactly once")
    if any(type(key) is not str for key in value):
        raise ValueError("fact keys must be strings")
    if any(item is not None and type(item) not in {str, bool} for item in value.values()):
        raise ValueError("facts must use normalized string, boolean, or null values")
    return value


class _ExtractionCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    field_codes: ClassVar[tuple[str, ...]]

    case_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    output_valid: bool
    expected: dict[str, NormalizedFactValue]
    actual: dict[str, NormalizedFactValue] | None

    @field_validator("expected", mode="before")
    @classmethod
    def validate_expected(cls, value: object) -> object:
        return _validate_fact_map(value, field_codes=cls.field_codes)

    @field_validator("actual", mode="before")
    @classmethod
    def validate_actual(cls, value: object) -> object:
        if value is None:
            return None
        return _validate_fact_map(value, field_codes=cls.field_codes)

    @model_validator(mode="after")
    def validate_output_state(self) -> Self:
        if self.output_valid != (self.actual is not None):
            raise ValueError("valid output requires facts and invalid output forbids facts")
        return self


class ContractExtractionEvaluationCase(_ExtractionCase):
    field_codes = tuple(CONTRACT_CORE_FIELD_CODES)


class InvoiceExtractionEvaluationCase(_ExtractionCase):
    field_codes = tuple(INVOICE_CORE_FIELD_CODES)


class StructuredOutputAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    attempt_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    operation_id: AiOperationId
    output_valid: bool


class AiExtractionEvaluationInput(BaseModel):
    """评测计算输入；approval_ref 仅作追踪，不验证外部审批真实性。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["ai-extraction-evaluation-v1"]
    dataset_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    dataset_version: str = Field(min_length=1, max_length=100)
    approval_ref: str = Field(min_length=1, max_length=500)
    representative: Literal[True]
    contract_cases: tuple[ContractExtractionEvaluationCase, ...] = Field(min_length=1)
    invoice_cases: tuple[InvoiceExtractionEvaluationCase, ...] = Field(min_length=1)
    structured_output_attempts: tuple[StructuredOutputAttempt, ...] = Field(min_length=1)

    @field_validator(
        "contract_cases",
        "invoice_cases",
        "structured_output_attempts",
        mode="before",
    )
    @classmethod
    def parse_arrays(cls, value: object) -> object:
        return tuple(value) if type(value) is list else value

    @model_validator(mode="after")
    def validate_unique_identities(self) -> Self:
        case_ids = tuple(case.case_id for case in self.contract_cases + self.invoice_cases)
        attempt_ids = tuple(item.attempt_id for item in self.structured_output_attempts)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id must be unique")
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("attempt_id must be unique")
        return self


class RatioMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    matched_count: int = Field(ge=0)
    total_count: int = Field(gt=0)
    numerator: int = Field(ge=0)
    denominator: int = Field(gt=0)
    threshold_numerator: int = Field(ge=0)
    threshold_denominator: int = Field(gt=0)
    passed: bool


class AiExtractionEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["ai-extraction-evaluation-result-v1"]
    dataset_id: str
    dataset_version: str
    approval_ref: str
    contract_field_accuracy: RatioMetric
    invoice_field_accuracy: RatioMetric
    structured_output_validity: RatioMetric
    threshold_status: Literal["PASSED", "FAILED"]
    formal_acceptance_status: Literal["NOT_DETERMINED"] = "NOT_DETERMINED"


def _field_accuracy(cases: tuple[_ExtractionCase, ...], threshold: Fraction) -> RatioMetric:
    total = sum(len(case.field_codes) for case in cases)
    matched = sum(
        sum(case.actual[field] == case.expected[field] for field in case.field_codes)
        for case in cases
        if case.actual is not None
    )
    rate = Fraction(matched, total)
    return RatioMetric(
        matched_count=matched,
        total_count=total,
        numerator=rate.numerator,
        denominator=rate.denominator,
        threshold_numerator=threshold.numerator,
        threshold_denominator=threshold.denominator,
        passed=rate >= threshold,
    )


def evaluate_ai_extraction(
    evaluation: AiExtractionEvaluationInput,
) -> AiExtractionEvaluationResult:
    """计算三个 READY 阈值；不把计算通过升级为正式 AC/UAT 通过。"""

    contract = _field_accuracy(evaluation.contract_cases, CONTRACT_ACCURACY_THRESHOLD)
    invoice = _field_accuracy(evaluation.invoice_cases, INVOICE_ACCURACY_THRESHOLD)
    valid_count = sum(item.output_valid for item in evaluation.structured_output_attempts)
    attempt_count = len(evaluation.structured_output_attempts)
    validity_rate = Fraction(valid_count, attempt_count)
    validity = RatioMetric(
        matched_count=valid_count,
        total_count=attempt_count,
        numerator=validity_rate.numerator,
        denominator=validity_rate.denominator,
        threshold_numerator=STRUCTURED_OUTPUT_VALIDITY_THRESHOLD.numerator,
        threshold_denominator=STRUCTURED_OUTPUT_VALIDITY_THRESHOLD.denominator,
        passed=validity_rate >= STRUCTURED_OUTPUT_VALIDITY_THRESHOLD,
    )
    passed = contract.passed and invoice.passed and validity.passed
    return AiExtractionEvaluationResult(
        schema_version="ai-extraction-evaluation-result-v1",
        dataset_id=evaluation.dataset_id,
        dataset_version=evaluation.dataset_version,
        approval_ref=evaluation.approval_ref,
        contract_field_accuracy=contract,
        invoice_field_accuracy=invoice,
        structured_output_validity=validity,
        threshold_status="PASSED" if passed else "FAILED",
    )


__all__ = [
    "AiExtractionEvaluationInput",
    "AiExtractionEvaluationResult",
    "ContractExtractionEvaluationCase",
    "InvoiceExtractionEvaluationCase",
    "RatioMetric",
    "StructuredOutputAttempt",
    "evaluate_ai_extraction",
]
