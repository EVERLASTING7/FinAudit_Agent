"""Frozen public schemas for the invoice detail read API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.schemas.business_statuses import (
    ConfirmationStatus,
    InvoiceDuplicateStatus,
    InvoiceStatus,
)
from app.schemas.contracts import ContractListItemData

DecimalString = Annotated[str, Field(pattern=r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")]
PositiveIntegerString = Annotated[str, Field(pattern=r"^[1-9]\d*$")]


class InvoiceItemData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    line_no: int = Field(ge=1)
    item_name: str | None
    specification: str | None
    unit: str | None
    quantity: DecimalString | None
    unit_price: DecimalString | None
    amount_excluding_tax: DecimalString | None
    tax_rate: DecimalString | None
    tax_amount: DecimalString | None
    total_amount: DecimalString | None
    row_version: PositiveIntegerString


class InvoiceDetailData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    invoice_code: str | None
    invoice_number: str | None
    invoice_type: str | None
    is_red_invoice: bool | None
    invoice_date: date | None
    buyer_name: str | None
    buyer_tax_no: str | None
    seller_name: str | None
    seller_tax_no: str | None
    amount_excluding_tax: DecimalString | None
    tax_amount: DecimalString | None
    total_amount: DecimalString | None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    confirmation_status: ConfirmationStatus
    duplicate_status: InvoiceDuplicateStatus
    status: InvoiceStatus
    row_version: PositiveIntegerString
    items: tuple[InvoiceItemData, ...]


class InvoiceListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=20, ge=1, le=100)


class InvoiceListItemData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    invoice_code: str | None
    invoice_number: str | None
    invoice_date: date | None
    seller_name: str | None
    total_amount: DecimalString | None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    confirmation_status: ConfirmationStatus
    duplicate_status: InvoiceDuplicateStatus
    status: InvoiceStatus


class InvoiceListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[InvoiceListItemData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_page_shape(self) -> InvoiceListData:
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size")
        if self.next_cursor is not None and len(self.items) != self.page_size:
            raise ValueError("next_cursor requires a full page")
        return self


InvoiceDuplicateBasisStatus = Literal[
    "ready",
    "incomplete_identity",
    "source_voided",
]


class InvoiceDuplicateCandidateListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=20, ge=1, le=100)


class InvoiceDuplicateCandidateListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    basis_status: InvoiceDuplicateBasisStatus
    items: tuple[InvoiceListItemData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_page_shape(self) -> InvoiceDuplicateCandidateListData:
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size")
        if self.next_cursor is not None and len(self.items) != self.page_size:
            raise ValueError("next_cursor requires a full page")
        if any(
            previous.id.int >= current.id.int
            for previous, current in zip(self.items, self.items[1:], strict=False)
        ):
            raise ValueError("items must be strictly ordered by id")
        if any(item.status == InvoiceStatus.VOIDED for item in self.items):
            raise ValueError("voided invoices cannot be duplicate candidates")
        if self.basis_status != "ready" and (self.items or self.next_cursor is not None):
            raise ValueError("non-ready basis requires an empty page")
        return self


class InvoiceExactDuplicatePairQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InvoiceExactIdentityData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    invoice_code: str
    invoice_number: str
    seller_tax_no: str


class InvoiceExactDuplicatePairData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source: InvoiceListItemData
    candidate: InvoiceListItemData
    exact_identity: InvoiceExactIdentityData

    @model_validator(mode="after")
    def validate_pair(self) -> InvoiceExactDuplicatePairData:
        if self.source.id == self.candidate.id:
            raise ValueError("source and candidate must differ")
        if (
            self.source.status == InvoiceStatus.VOIDED
            or self.candidate.status == InvoiceStatus.VOIDED
        ):
            raise ValueError("voided invoices cannot form an exact duplicate pair")
        if (
            self.source.invoice_code != self.exact_identity.invoice_code
            or self.candidate.invoice_code != self.exact_identity.invoice_code
            or self.source.invoice_number != self.exact_identity.invoice_number
            or self.candidate.invoice_number != self.exact_identity.invoice_number
        ):
            raise ValueError("pair summaries must match exact_identity")
        return self


class InvoicePrimaryContractData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    primary_contract: ContractListItemData | None


class ContractPrimaryInvoiceListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=20, ge=1, le=100)


class ContractPrimaryInvoiceListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[InvoiceListItemData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_page_shape(self) -> ContractPrimaryInvoiceListData:
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size")
        if self.next_cursor is not None and len(self.items) != self.page_size:
            raise ValueError("next_cursor requires a full page")
        if any(
            previous.id.int >= current.id.int
            for previous, current in zip(self.items, self.items[1:], strict=False)
        ):
            raise ValueError("items must be strictly ordered by id")
        return self


ContractInvoiceLinkStatus = Literal[
    "candidate",
    "suggested",
    "confirmed_primary",
    "cancelled",
]
MatchEvidenceStatus = Literal["matched", "mismatched", "unavailable"]
ContractInvoiceReasonCode = Literal[
    "tax_no_matched",
    "tax_no_mismatched",
    "tax_no_unavailable",
    "name_matched",
    "name_mismatched",
    "name_unavailable",
    "date_in_range",
    "date_out_of_range",
    "date_unavailable",
]


class ContractInvoiceMatchReasonData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: MatchEvidenceStatus
    code: ContractInvoiceReasonCode


class ContractInvoiceMatchReasonsData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tax_no: ContractInvoiceMatchReasonData
    name: ContractInvoiceMatchReasonData
    date: ContractInvoiceMatchReasonData

    @model_validator(mode="after")
    def validate_dimensions(self) -> ContractInvoiceMatchReasonsData:
        expected_codes = {
            "tax_no": {
                "matched": "tax_no_matched",
                "mismatched": "tax_no_mismatched",
                "unavailable": "tax_no_unavailable",
            },
            "name": {
                "matched": "name_matched",
                "mismatched": "name_mismatched",
                "unavailable": "name_unavailable",
            },
            "date": {
                "matched": "date_in_range",
                "mismatched": "date_out_of_range",
                "unavailable": "date_unavailable",
            },
        }
        for dimension, reason in (
            ("tax_no", self.tax_no),
            ("name", self.name),
            ("date", self.date),
        ):
            if reason.code != expected_codes[dimension][reason.status]:
                raise ValueError("match reason code is incompatible with its dimension or status")
        return self


class ContractInvoiceCandidateData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract: ContractListItemData
    match_reasons: ContractInvoiceMatchReasonsData


class ContractInvoiceCandidateListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    invoice_id: UUID
    invoice_row_version: PositiveIntegerString
    items: tuple[ContractInvoiceCandidateData, ...]


def _parse_canonical_uuid(value: object, field_name: str) -> object:
    if type(value) is UUID:
        return value
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError(f"{field_name} must be a canonical UUID") from None
    if str(parsed) != value:
        raise ValueError(f"{field_name} must be a canonical UUID")
    return parsed


class ContractLinkSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_id: UUID
    invoice_row_version: PositiveIntegerString
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("contract_id", mode="before")
    @classmethod
    def parse_contract_id(cls, value: object) -> object:
        return _parse_canonical_uuid(value, "contract_id")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("reason must not contain outer whitespace")
        return value


class PrimaryContractSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    suggestion_id: UUID
    invoice_row_version: PositiveIntegerString
    relation_row_version: PositiveIntegerString
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("suggestion_id", mode="before")
    @classmethod
    def parse_suggestion_id(cls, value: object) -> object:
        return _parse_canonical_uuid(value, "suggestion_id")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("reason must not contain outer whitespace")
        return value


class PrimaryContractCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    invoice_row_version: PositiveIntegerString
    relation_row_version: PositiveIntegerString
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("reason must not contain outer whitespace")
        return value


class ContractInvoiceLinkData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    contract_id: UUID
    status: ContractInvoiceLinkStatus
    match_reasons: ContractInvoiceMatchReasonsData
    suggested_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    row_version: PositiveIntegerString

    @model_validator(mode="after")
    def validate_lifecycle(self) -> ContractInvoiceLinkData:
        if self.status == "confirmed_primary" and (
            self.confirmed_at is None
            or self.cancelled_at is not None
            or self.cancel_reason is not None
        ):
            raise ValueError("confirmed relation lifecycle is invalid")
        if self.status == "cancelled" and (self.cancelled_at is None or self.cancel_reason is None):
            raise ValueError("cancelled relation lifecycle is invalid")
        if self.status in {"candidate", "suggested"} and any(
            value is not None
            for value in (self.confirmed_at, self.cancelled_at, self.cancel_reason)
        ):
            raise ValueError("pending relation lifecycle is invalid")
        return self


class ContractInvoiceMutationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    invoice_id: UUID
    invoice_row_version: PositiveIntegerString
    relation: ContractInvoiceLinkData
    previous_primary_relation_id: UUID | None


class ContractInvoiceHistoryData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    invoice_id: UUID
    items: tuple[ContractInvoiceLinkData, ...]


class ContractInvoiceWriteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


InvoiceFieldCode = Literal[
    "invoice_code",
    "invoice_number",
    "invoice_type",
    "is_red_invoice",
    "invoice_date",
    "buyer_name",
    "buyer_tax_no",
    "seller_name",
    "seller_tax_no",
    "amount_excluding_tax",
    "tax_amount",
    "total_amount",
    "currency",
]

INVOICE_CORE_FIELD_CODES: tuple[InvoiceFieldCode, ...] = (
    "invoice_code",
    "invoice_number",
    "invoice_type",
    "is_red_invoice",
    "invoice_date",
    "buyer_name",
    "buyer_tax_no",
    "seller_name",
    "seller_tax_no",
    "amount_excluding_tax",
    "tax_amount",
    "total_amount",
    "currency",
)


class InvoiceEvidenceData(BaseModel):
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
        return _parse_canonical_uuid(value, "evidence UUID")


class InvoiceFieldEvidenceData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    field_code: InvoiceFieldCode
    evidence: InvoiceEvidenceData


class InvoiceItemWriteData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    line_no: int = Field(ge=1, le=1000)
    item_name: str | None = Field(default=None, max_length=500)
    specification: str | None = Field(default=None, max_length=300)
    unit: str | None = Field(default=None, max_length=50)
    quantity: DecimalString | None = None
    unit_price: DecimalString | None = None
    amount_excluding_tax: DecimalString | None = None
    tax_rate: DecimalString | None = None
    tax_amount: DecimalString | None = None
    total_amount: DecimalString | None = None
    evidence: tuple[InvoiceEvidenceData, ...] = Field(default=(), max_length=20)

    @field_validator("evidence", mode="before")
    @classmethod
    def parse_evidence_array(cls, value: object) -> object:
        return tuple(value) if type(value) is list else value


class InvoiceFactsWriteData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    invoice_code: str | None = Field(default=None, min_length=1, max_length=50)
    invoice_number: str | None = Field(default=None, min_length=1, max_length=50)
    invoice_type: str | None = Field(default=None, min_length=1, max_length=40)
    is_red_invoice: bool | None = None
    invoice_date: date | None = None
    buyer_name: str | None = Field(default=None, min_length=1, max_length=300)
    buyer_tax_no: str | None = Field(default=None, min_length=1, max_length=32)
    seller_name: str | None = Field(default=None, min_length=1, max_length=300)
    seller_tax_no: str | None = Field(default=None, min_length=1, max_length=32)
    amount_excluding_tax: DecimalString | None = None
    tax_amount: DecimalString | None = None
    total_amount: DecimalString | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @field_validator("invoice_date", mode="before")
    @classmethod
    def parse_invoice_date(cls, value: object) -> object:
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
    def validate_text_shape(self) -> InvoiceFactsWriteData:
        for field_name in (
            "invoice_code",
            "invoice_number",
            "invoice_type",
            "buyer_name",
            "buyer_tax_no",
            "seller_name",
            "seller_tax_no",
        ):
            value = getattr(self, field_name)
            if value is not None and value != value.strip():
                raise ValueError(f"{field_name} must not contain outer whitespace")
        return self


def _validate_reason(value: str) -> str:
    if value != value.strip():
        raise ValueError("reason must not contain outer whitespace")
    return value


class InvoiceFactsReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    reason: str = Field(min_length=1, max_length=1000)
    facts: InvoiceFactsWriteData
    field_evidence: tuple[InvoiceFieldEvidenceData, ...] = Field(max_length=13)
    items: tuple[InvoiceItemWriteData, ...] = Field(max_length=1000)

    @field_validator("field_evidence", "items", mode="before")
    @classmethod
    def parse_json_arrays(cls, value: object) -> object:
        return tuple(value) if type(value) is list else value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _validate_reason(value)

    @model_validator(mode="after")
    def validate_unique_fields_and_lines(self) -> InvoiceFactsReplaceRequest:
        fields = tuple(item.field_code for item in self.field_evidence)
        lines = tuple(item.line_no for item in self.items)
        if len(fields) != len(set(fields)) or len(lines) != len(set(lines)):
            raise ValueError("field evidence and item line numbers must be unique")
        if lines != tuple(sorted(lines)):
            raise ValueError("invoice item lines must be sorted")
        return self


class InvoiceDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    decision: Literal["confirmed", "rejected"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _validate_reason(value)


class InvoiceDuplicateCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _validate_reason(value)


class InvoiceDuplicateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    candidate_id: UUID
    decision: Literal["confirmed_duplicate", "exception_approved"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("candidate_id", mode="before")
    @classmethod
    def parse_candidate_id(cls, value: object) -> object:
        return _parse_canonical_uuid(value, "candidate_id")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _validate_reason(value)


class InvoiceMutationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    invoice: InvoiceDetailData
    duplicate_candidate_id: UUID | None


class InvoiceEvidenceResponseData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    invoice_id: UUID
    row_version: PositiveIntegerString
    field_evidence: tuple[InvoiceFieldEvidenceData, ...]
    item_evidence: dict[str, tuple[InvoiceEvidenceData, ...]]


class InvoiceCorrectionHistoryItemData(BaseModel):
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


class InvoiceCorrectionHistoryData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    invoice_id: UUID
    items: tuple[InvoiceCorrectionHistoryItemData, ...]


class InvoiceWriteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


__all__ = [
    "ContractInvoiceCandidateData",
    "ContractInvoiceCandidateListData",
    "ContractInvoiceHistoryData",
    "ContractInvoiceLinkData",
    "ContractInvoiceMatchReasonData",
    "ContractInvoiceMatchReasonsData",
    "ContractInvoiceMutationData",
    "ContractInvoiceWriteQuery",
    "ContractLinkSuggestionRequest",
    "ContractPrimaryInvoiceListData",
    "ContractPrimaryInvoiceListQuery",
    "DecimalString",
    "InvoiceDuplicateBasisStatus",
    "InvoiceDuplicateCandidateListData",
    "InvoiceDuplicateCandidateListQuery",
    "InvoiceExactDuplicatePairData",
    "InvoiceExactDuplicatePairQuery",
    "InvoiceExactIdentityData",
    "InvoicePrimaryContractData",
    "PrimaryContractCancelRequest",
    "PrimaryContractSetRequest",
    "InvoiceDetailData",
    "InvoiceDecisionRequest",
    "InvoiceDuplicateCheckRequest",
    "InvoiceDuplicateDecisionRequest",
    "InvoiceEvidenceData",
    "InvoiceEvidenceResponseData",
    "InvoiceFactsReplaceRequest",
    "InvoiceFactsWriteData",
    "InvoiceFieldEvidenceData",
    "InvoiceCorrectionHistoryData",
    "InvoiceCorrectionHistoryItemData",
    "INVOICE_CORE_FIELD_CODES",
    "InvoiceItemData",
    "InvoiceItemWriteData",
    "InvoiceListData",
    "InvoiceListItemData",
    "InvoiceListQuery",
    "InvoiceMutationData",
    "InvoiceWriteQuery",
    "PositiveIntegerString",
]
