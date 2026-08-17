"""Frozen public schemas for contract current-row read APIs."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.schemas.business_statuses import ConfirmationStatus

DecimalString = Annotated[str, Field(pattern=r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")]
PositiveIntegerString = Annotated[str, Field(pattern=r"^[1-9]\d*$")]


class ContractStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    ARCHIVED = "archived"


class SupplementaryAgreementStatus(str, Enum):
    DRAFT = "draft"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class ContractDetailData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    contract_no: str | None
    name: str
    party_a_name: str | None
    party_a_tax_no: str | None
    party_b_name: str | None
    party_b_tax_no: str | None
    amount: DecimalString | None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    signed_date: date | None
    effective_date: date | None
    expiry_date: date | None
    payment_method: str | None
    payment_terms: str | None
    confirmation_status: ConfirmationStatus
    status: ContractStatus
    row_version: PositiveIntegerString


class ContractListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=20, ge=1, le=100)


class ContractListItemData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    contract_no: str | None
    name: str
    party_b_name: str | None
    amount: DecimalString | None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    effective_date: date | None
    expiry_date: date | None
    confirmation_status: ConfirmationStatus
    status: ContractStatus


class ContractListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[ContractListItemData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_page_shape(self) -> ContractListData:
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size")
        if self.next_cursor is not None and len(self.items) != self.page_size:
            raise ValueError("next_cursor requires a full page")
        return self


class SupplementaryAgreementHeaderListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=20, ge=1, le=100)


class SupplementaryAgreementHeaderData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    agreement_no: str | None
    name: str
    signed_date: date | None
    effective_date: date
    status: SupplementaryAgreementStatus
    confirmation_status: ConfirmationStatus


class SupplementaryAgreementHeaderListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[SupplementaryAgreementHeaderData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_page_shape(self) -> SupplementaryAgreementHeaderListData:
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size")
        if self.next_cursor is not None and len(self.items) != self.page_size:
            raise ValueError("next_cursor requires a full page")
        return self


ContractFieldValueType = Literal["string", "number", "date", "json"]


class EffectiveContractQuery(BaseModel):
    # Query 参数到达 Pydantic 前必然是字符串；日期解析后仍由 date 类型和 OpenAPI 约束。
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_date: date


class EffectiveContractFieldData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    field_code: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,79}$")
    value_type: ContractFieldValueType
    original_value: JsonValue
    effective_value: JsonValue
    source_agreement_id: UUID | None
    source_effective_date: date | None

    @model_validator(mode="after")
    def validate_source_pair(self) -> EffectiveContractFieldData:
        if (self.source_agreement_id is None) != (self.source_effective_date is None):
            raise ValueError("source agreement and date must be paired")
        return self


class EffectiveContractData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    baseline_date: date
    confirmation_status: ConfirmationStatus
    fields: tuple[EffectiveContractFieldData, ...]
    applied_agreement_ids: tuple[UUID, ...]
    row_version: PositiveIntegerString

    @model_validator(mode="after")
    def validate_projection_shape(self) -> EffectiveContractData:
        field_codes = tuple(item.field_code for item in self.fields)
        if field_codes != tuple(sorted(set(field_codes))):
            raise ValueError("effective fields must be unique and sorted")
        if len(self.applied_agreement_ids) != len(set(self.applied_agreement_ids)):
            raise ValueError("applied agreement ids must be unique")
        return self


class SupplementaryChangeWriteData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    field_code: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,79}$")
    value_type: ContractFieldValueType
    new_value: JsonValue
    evidence_block_id: UUID | None
    page_no: int | None = Field(default=None, ge=1)
    quote_text: str | None = Field(default=None, min_length=1, max_length=4000)
    bbox: dict[str, JsonValue] | None = None

    @field_validator("evidence_block_id", mode="before")
    @classmethod
    def parse_canonical_evidence_block_id(cls, value: object) -> object:
        if value is None or type(value) is UUID:
            return value
        if type(value) is not str:
            raise ValueError("evidence_block_id must be a canonical UUID")
        try:
            parsed = UUID(value)
        except ValueError:
            raise ValueError("evidence_block_id must be a canonical UUID") from None
        if str(parsed) != value:
            raise ValueError("evidence_block_id must be a canonical UUID")
        return parsed

    @field_validator("new_value")
    @classmethod
    def validate_typed_value(cls, value: JsonValue) -> JsonValue:
        if type(value) is float and not (-float("inf") < value < float("inf")):
            raise ValueError("new_value must be finite")
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> SupplementaryChangeWriteData:
        if self.new_value is None:
            return self
        if self.value_type == "string" and type(self.new_value) is not str:
            raise ValueError("string field requires a string value")
        if self.value_type == "number":
            if (
                type(self.new_value) is not str
                or re.fullmatch(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$", self.new_value) is None
            ):
                raise ValueError("number field requires a canonical decimal string")
        if self.value_type == "date":
            if type(self.new_value) is not str:
                raise ValueError("date field requires a date string")
            try:
                parsed = date.fromisoformat(self.new_value)
            except ValueError:
                raise ValueError("date field requires a valid date string") from None
            if parsed.isoformat() != self.new_value:
                raise ValueError("date field requires a canonical date string")
        if self.value_type == "json" and type(self.new_value) not in (dict, list, bool):
            raise ValueError("json field requires object, array or boolean")
        evidence_values = (
            self.evidence_block_id,
            self.page_no,
            self.quote_text,
        )
        if any(value is not None for value in evidence_values) and not all(
            value is not None for value in evidence_values
        ):
            raise ValueError("evidence block, page and quote must be provided together")
        if self.bbox is not None and self.evidence_block_id is None:
            raise ValueError("bbox requires complete evidence")
        if self.quote_text is not None and self.quote_text != self.quote_text.strip():
            raise ValueError("quote_text must not contain outer whitespace")
        return self


class SupplementaryChangesReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    reason: str = Field(min_length=1, max_length=1000)
    changes: tuple[SupplementaryChangeWriteData, ...] = Field(min_length=1, max_length=100)

    @field_validator("changes", mode="before")
    @classmethod
    def require_json_array(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("changes must be an array")
        return tuple(value)

    @model_validator(mode="after")
    def validate_request(self) -> SupplementaryChangesReplaceRequest:
        codes = tuple(change.field_code for change in self.changes)
        if len(codes) != len(set(codes)):
            raise ValueError("changes must contain unique field codes")
        if self.reason != self.reason.strip():
            raise ValueError("reason must not contain outer whitespace")
        return self


class SupplementaryAgreementDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    decision: Literal["confirmed", "rejected"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("reason must not contain outer whitespace")
        return value


class SupplementaryAgreementChangeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    field_code: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,79}$")
    value_type: ContractFieldValueType
    old_value: JsonValue
    new_value: JsonValue
    evidence_block_id: UUID | None
    page_no: int | None = Field(default=None, ge=1)
    quote_text: str | None
    bbox: dict[str, JsonValue] | None
    confirmation_status: ConfirmationStatus


class SupplementaryAgreementDetailData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    contract_id: UUID
    agreement_no: str | None
    name: str
    signed_date: date | None
    effective_date: date
    status: SupplementaryAgreementStatus
    confirmation_status: ConfirmationStatus
    changes: tuple[SupplementaryAgreementChangeData, ...]
    row_version: PositiveIntegerString

    @model_validator(mode="after")
    def validate_changes(self) -> SupplementaryAgreementDetailData:
        codes = tuple(change.field_code for change in self.changes)
        if codes != tuple(sorted(set(codes))):
            raise ValueError("changes must be unique and sorted")
        return self


ContractFieldCode = Literal[
    "contract_no",
    "name",
    "party_a_name",
    "party_a_tax_no",
    "party_b_name",
    "party_b_tax_no",
    "amount",
    "currency",
    "signed_date",
    "effective_date",
    "expiry_date",
    "payment_method",
    "payment_terms",
]

CONTRACT_CORE_FIELD_CODES: tuple[ContractFieldCode, ...] = (
    "contract_no",
    "name",
    "party_a_name",
    "party_a_tax_no",
    "party_b_name",
    "party_b_tax_no",
    "amount",
    "currency",
    "signed_date",
    "effective_date",
    "expiry_date",
    "payment_method",
    "payment_terms",
)


class ContractEvidenceData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    block_id: UUID
    parse_version_id: UUID
    page_no: int = Field(ge=1)
    quote_text: str = Field(min_length=1, max_length=4000)
    bbox: dict[str, JsonValue] | None
    confidence: DecimalString | None

    @field_validator("block_id", "parse_version_id", mode="before")
    @classmethod
    def parse_evidence_uuid(cls, value: object) -> object:
        if type(value) is UUID:
            return value
        if type(value) is not str:
            return value
        try:
            parsed = UUID(value)
        except ValueError:
            return value
        return parsed if str(parsed) == value else value


class ContractFieldEvidenceData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    field_code: ContractFieldCode
    evidence: ContractEvidenceData


class ContractFactsWriteData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_no: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=300)
    party_a_name: str | None = Field(default=None, min_length=1, max_length=300)
    party_a_tax_no: str | None = Field(default=None, min_length=1, max_length=32)
    party_b_name: str | None = Field(default=None, min_length=1, max_length=300)
    party_b_tax_no: str | None = Field(default=None, min_length=1, max_length=32)
    amount: DecimalString | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    signed_date: date | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    payment_method: str | None = Field(default=None, min_length=1, max_length=100)
    payment_terms: str | None = Field(default=None, min_length=1, max_length=4000)

    @field_validator("signed_date", "effective_date", "expiry_date", mode="before")
    @classmethod
    def parse_contract_date(cls, value: object) -> object:
        if value is None or type(value) is date:
            return value
        if type(value) is not str:
            return value
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return value
        return parsed if parsed.isoformat() == value else value

    @model_validator(mode="after")
    def validate_fact_shape(self) -> ContractFactsWriteData:
        for field_name in (
            "contract_no",
            "name",
            "party_a_name",
            "party_a_tax_no",
            "party_b_name",
            "party_b_tax_no",
            "payment_method",
            "payment_terms",
        ):
            value = getattr(self, field_name)
            if value is not None and value != value.strip():
                raise ValueError(f"{field_name} must not contain outer whitespace")
        if (
            self.effective_date is not None
            and self.expiry_date is not None
            and self.expiry_date < self.effective_date
        ):
            raise ValueError("expiry_date must not precede effective_date")
        return self


class ContractFactsReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    reason: str = Field(min_length=1, max_length=1000)
    facts: ContractFactsWriteData
    field_evidence: tuple[ContractFieldEvidenceData, ...] = Field(max_length=13)

    @field_validator("field_evidence", mode="before")
    @classmethod
    def parse_evidence_array(cls, value: object) -> object:
        return tuple(value) if type(value) is list else value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("reason must not contain outer whitespace")
        return value

    @model_validator(mode="after")
    def validate_evidence_coverage(self) -> ContractFactsReplaceRequest:
        evidence_codes = tuple(item.field_code for item in self.field_evidence)
        if len(evidence_codes) != len(set(evidence_codes)):
            raise ValueError("field evidence must contain unique field codes")
        expected_codes = {
            field_code
            for field_code in CONTRACT_CORE_FIELD_CODES
            if getattr(self.facts, field_code) is not None
        }
        if set(evidence_codes) != expected_codes:
            raise ValueError("every non-null fact must have exactly one evidence item")
        return self


class ContractDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    decision: Literal["confirmed", "rejected"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("reason must not contain outer whitespace")
        return value


class ContractFieldCandidateData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    field_code: ContractFieldCode
    value_type: ContractFieldValueType
    candidate_value: JsonValue
    confirmed_value: JsonValue
    confirmation_status: ConfirmationStatus
    evidence: ContractEvidenceData | None


class ContractEvidenceResponseData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_id: UUID
    file_id: UUID
    row_version: PositiveIntegerString
    fields: tuple[ContractFieldCandidateData, ...]

    @model_validator(mode="after")
    def validate_fields(self) -> ContractEvidenceResponseData:
        codes = tuple(item.field_code for item in self.fields)
        if codes != CONTRACT_CORE_FIELD_CODES:
            raise ValueError("contract core fields must use the frozen order")
        return self


class ContractCorrectionHistoryItemData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    field_path: str
    before_value: dict[str, JsonValue] | None
    after_value: dict[str, JsonValue] | None
    reason: str
    actor_id: UUID
    actor_role_code: str
    created_at: datetime
    trace_id: UUID


class ContractCorrectionHistoryData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_id: UUID
    items: tuple[ContractCorrectionHistoryItemData, ...]


class ContractMutationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract: ContractDetailData


class FinancialWriteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


__all__ = [
    "CONTRACT_CORE_FIELD_CODES",
    "ContractCorrectionHistoryData",
    "ContractCorrectionHistoryItemData",
    "ContractDecisionRequest",
    "ContractDetailData",
    "ContractEvidenceData",
    "ContractEvidenceResponseData",
    "ContractFactsReplaceRequest",
    "ContractFactsWriteData",
    "ContractFieldCandidateData",
    "ContractFieldCode",
    "ContractFieldEvidenceData",
    "ContractListData",
    "ContractListItemData",
    "ContractListQuery",
    "ContractStatus",
    "ContractFieldValueType",
    "ContractMutationData",
    "EffectiveContractData",
    "EffectiveContractFieldData",
    "EffectiveContractQuery",
    "FinancialWriteQuery",
    "SupplementaryAgreementChangeData",
    "SupplementaryAgreementDecisionRequest",
    "SupplementaryAgreementDetailData",
    "SupplementaryChangesReplaceRequest",
    "SupplementaryChangeWriteData",
    "SupplementaryAgreementHeaderData",
    "SupplementaryAgreementHeaderListData",
    "SupplementaryAgreementHeaderListQuery",
    "SupplementaryAgreementStatus",
]
