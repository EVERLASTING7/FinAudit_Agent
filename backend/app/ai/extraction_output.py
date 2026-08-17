"""合同与发票模型输出的严格 DTO、证据白名单和候选采用边界。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from typing_extensions import Self

from app.ai.extraction_prompts import ExtractionPromptBlock
from app.ai.strict_json import StrictJsonError, parse_strict_json
from app.schemas.contracts import (
    CONTRACT_CORE_FIELD_CODES,
    ContractEvidenceData,
    ContractFactsWriteData,
    ContractFieldEvidenceData,
)
from app.schemas.invoices import (
    INVOICE_CORE_FIELD_CODES,
    InvoiceEvidenceData,
    InvoiceFactsWriteData,
    InvoiceFieldEvidenceData,
    InvoiceItemWriteData,
)

CONTRACT_EXTRACTION_SCHEMA_VERSION = "contract-extraction-output-v1"
INVOICE_EXTRACTION_SCHEMA_VERSION = "invoice-extraction-output-v1"
_INVOICE_ITEM_VALUE_FIELDS = (
    "item_name",
    "specification",
    "unit",
    "quantity",
    "unit_price",
    "amount_excluding_tax",
    "tax_rate",
    "tax_amount",
    "total_amount",
)


class ExtractionOutputError(ValueError):
    """固定错误文本，不反射模型输出或文档正文。"""

    def __init__(self) -> None:
        super().__init__("AI extraction output is invalid")


class _StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)


class ContractExtractionOutput(_StrictOutput):
    facts: ContractFactsWriteData
    field_evidence: tuple[ContractFieldEvidenceData, ...] = Field(max_length=13)

    @field_validator("field_evidence", mode="before")
    @classmethod
    def parse_field_evidence(cls, value: object) -> object:
        return tuple(value) if type(value) is list else value

    @model_validator(mode="before")
    @classmethod
    def require_exact_fact_keys(cls, value: object) -> object:
        if type(value) is not dict:
            raise ValueError("contract output shape is invalid")
        output = cast(dict[object, object], value)
        facts = output.get("facts")
        if type(facts) is not dict:
            raise ValueError("contract output shape is invalid")
        if set(facts) != set(CONTRACT_CORE_FIELD_CODES):
            raise ValueError("contract facts must contain every field exactly once")
        return value

    @model_validator(mode="after")
    def validate_evidence_matrix(self) -> Self:
        codes = tuple(item.field_code for item in self.field_evidence)
        non_null_codes = {
            field_code
            for field_code in CONTRACT_CORE_FIELD_CODES
            if getattr(self.facts, field_code) is not None
        }
        if len(codes) != len(set(codes)) or set(codes) != non_null_codes:
            raise ValueError("contract field evidence does not match non-null facts")
        return self


class InvoiceExtractionOutput(_StrictOutput):
    facts: InvoiceFactsWriteData
    field_evidence: tuple[InvoiceFieldEvidenceData, ...] = Field(max_length=13)
    items: tuple[InvoiceItemWriteData, ...] = Field(max_length=1000)

    @field_validator("field_evidence", "items", mode="before")
    @classmethod
    def parse_arrays(cls, value: object) -> object:
        return tuple(value) if type(value) is list else value

    @model_validator(mode="before")
    @classmethod
    def require_exact_fact_keys(cls, value: object) -> object:
        if type(value) is not dict:
            raise ValueError("invoice output shape is invalid")
        output = cast(dict[object, object], value)
        facts = output.get("facts")
        if type(facts) is not dict:
            raise ValueError("invoice output shape is invalid")
        if set(facts) != set(INVOICE_CORE_FIELD_CODES):
            raise ValueError("invoice facts must contain every field exactly once")
        return value

    @model_validator(mode="after")
    def validate_candidate_shape(self) -> Self:
        codes = tuple(item.field_code for item in self.field_evidence)
        non_null_codes = {
            field_code
            for field_code in INVOICE_CORE_FIELD_CODES
            if getattr(self.facts, field_code) is not None
        }
        if len(codes) != len(set(codes)) or set(codes) != non_null_codes:
            raise ValueError("invoice field evidence does not match non-null facts")
        if tuple(item.line_no for item in self.items) != tuple(range(1, len(self.items) + 1)):
            raise ValueError("invoice item line numbers must be continuous and ordered")
        for item in self.items:
            values = tuple(getattr(item, name) for name in _INVOICE_ITEM_VALUE_FIELDS)
            if not any(value is not None for value in values) or not item.evidence:
                raise ValueError("invoice items require a value and evidence")
            for value in values[:3]:
                if value is not None and (not value.strip() or value != value.strip()):
                    raise ValueError("invoice item text must be trimmed and non-empty")
            evidence_ids = tuple(evidence.block_id for evidence in item.evidence)
            if len(evidence_ids) != len(set(evidence_ids)):
                raise ValueError("invoice item evidence must be unique")
        return self


def _source_blocks(
    blocks: tuple[ExtractionPromptBlock, ...],
) -> Mapping[UUID, ExtractionPromptBlock]:
    if (
        type(blocks) is not tuple
        or not blocks
        or any(not isinstance(block, ExtractionPromptBlock) for block in blocks)
        or len({block.parse_version_id for block in blocks}) != 1
        or len({block.block_id for block in blocks}) != len(blocks)
    ):
        raise ExtractionOutputError
    return {block.block_id: block for block in blocks}


def _evidence_matches(
    evidence: ContractEvidenceData | InvoiceEvidenceData,
    source_by_id: Mapping[UUID, ExtractionPromptBlock],
) -> bool:
    block = source_by_id.get(evidence.block_id)
    if block is None:
        return False
    expected_confidence = None if block.confidence is None else format(block.confidence, "f")
    expected_bbox = None if block.bbox is None else dict(block.bbox)
    return (
        evidence.parse_version_id == block.parse_version_id
        and evidence.page_no == block.page_no
        and evidence.quote_text == block.text
        and evidence.bbox == expected_bbox
        and evidence.confidence == expected_confidence
    )


def _parse_output(output_text: str) -> object:
    if not isinstance(output_text, str) or not output_text.strip():
        raise ExtractionOutputError
    try:
        raw = output_text.encode("utf-8", errors="strict")
        return parse_strict_json(raw).value
    except (UnicodeError, StrictJsonError):
        raise ExtractionOutputError from None


def validate_contract_extraction_output(
    output_text: str,
    *,
    blocks: tuple[ExtractionPromptBlock, ...],
) -> ContractExtractionOutput:
    source_by_id = _source_blocks(blocks)
    try:
        output = ContractExtractionOutput.model_validate(_parse_output(output_text))
        if not all(
            _evidence_matches(item.evidence, source_by_id) for item in output.field_evidence
        ):
            raise ExtractionOutputError
        return output
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise ExtractionOutputError from None


def validate_invoice_extraction_output(
    output_text: str,
    *,
    blocks: tuple[ExtractionPromptBlock, ...],
) -> InvoiceExtractionOutput:
    source_by_id = _source_blocks(blocks)
    try:
        output = InvoiceExtractionOutput.model_validate(_parse_output(output_text))
        field_evidence = tuple(item.evidence for item in output.field_evidence)
        item_evidence: tuple[InvoiceEvidenceData, ...] = tuple(
            evidence for item in output.items for evidence in item.evidence
        )
        if not all(
            _evidence_matches(evidence, source_by_id) for evidence in field_evidence + item_evidence
        ):
            raise ExtractionOutputError
        return output
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise ExtractionOutputError from None


__all__ = [
    "CONTRACT_EXTRACTION_SCHEMA_VERSION",
    "INVOICE_EXTRACTION_SCHEMA_VERSION",
    "ContractExtractionOutput",
    "ExtractionOutputError",
    "InvoiceExtractionOutput",
    "validate_contract_extraction_output",
    "validate_invoice_extraction_output",
]
