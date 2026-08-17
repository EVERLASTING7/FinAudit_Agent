from __future__ import annotations

from app.evaluation.ai_extraction_metrics import (
    AiExtractionEvaluationInput,
    evaluate_ai_extraction,
)
from app.schemas.contracts import CONTRACT_CORE_FIELD_CODES
from app.schemas.invoices import INVOICE_CORE_FIELD_CODES


def _facts(field_codes: tuple[str, ...], prefix: str) -> dict[str, str | bool | None]:
    return {field: f"{prefix}-{field}" for field in field_codes}


def _input(
    *,
    contract_actual: dict[str, str | bool | None] | None,
    invoice_actual: dict[str, str | bool | None] | None,
    valid_attempts: int,
    attempt_count: int,
) -> AiExtractionEvaluationInput:
    contract_expected = _facts(tuple(CONTRACT_CORE_FIELD_CODES), "contract")
    invoice_expected = _facts(tuple(INVOICE_CORE_FIELD_CODES), "invoice")
    return AiExtractionEvaluationInput.model_validate(
        {
            "schema_version": "ai-extraction-evaluation-v1",
            "dataset_id": "approved-representative-v1",
            "dataset_version": "1.0.0",
            "approval_ref": "UAT-APPROVAL-001",
            "representative": True,
            "contract_cases": [
                {
                    "case_id": "contract-001",
                    "output_valid": contract_actual is not None,
                    "expected": contract_expected,
                    "actual": contract_actual,
                }
            ],
            "invoice_cases": [
                {
                    "case_id": "invoice-001",
                    "output_valid": invoice_actual is not None,
                    "expected": invoice_expected,
                    "actual": invoice_actual,
                }
            ],
            "structured_output_attempts": [
                {
                    "attempt_id": f"attempt-{index:03d}",
                    "operation_id": "contract_field_extraction",
                    "output_valid": index < valid_attempts,
                }
                for index in range(attempt_count)
            ],
        }
    )


def test_exact_metrics_pass_thresholds_without_claiming_formal_acceptance() -> None:
    contract = _facts(tuple(CONTRACT_CORE_FIELD_CODES), "contract")
    invoice = _facts(tuple(INVOICE_CORE_FIELD_CODES), "invoice")

    result = evaluate_ai_extraction(
        _input(
            contract_actual=contract,
            invoice_actual=invoice,
            valid_attempts=99,
            attempt_count=100,
        )
    )

    assert result.contract_field_accuracy.passed is True
    assert result.invoice_field_accuracy.passed is True
    assert result.structured_output_validity.passed is True
    assert result.threshold_status == "PASSED"
    assert result.formal_acceptance_status == "NOT_DETERMINED"


def test_invalid_output_counts_every_core_field_as_incorrect() -> None:
    invoice = _facts(tuple(INVOICE_CORE_FIELD_CODES), "invoice")

    result = evaluate_ai_extraction(
        _input(
            contract_actual=None,
            invoice_actual=invoice,
            valid_attempts=98,
            attempt_count=100,
        )
    )

    assert result.contract_field_accuracy.matched_count == 0
    assert result.contract_field_accuracy.total_count == len(CONTRACT_CORE_FIELD_CODES)
    assert result.structured_output_validity.passed is False
    assert result.threshold_status == "FAILED"


def test_one_invoice_field_miss_fails_the_95_percent_threshold() -> None:
    contract = _facts(tuple(CONTRACT_CORE_FIELD_CODES), "contract")
    invoice = _facts(tuple(INVOICE_CORE_FIELD_CODES), "invoice")
    invoice["invoice_number"] = "wrong"

    result = evaluate_ai_extraction(
        _input(
            contract_actual=contract,
            invoice_actual=invoice,
            valid_attempts=100,
            attempt_count=100,
        )
    )

    assert result.invoice_field_accuracy.matched_count == len(INVOICE_CORE_FIELD_CODES) - 1
    assert result.invoice_field_accuracy.passed is False
    assert result.threshold_status == "FAILED"
