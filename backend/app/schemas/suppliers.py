"""供应商候选读取、来源解析与人工处理的严格公共合同。"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.business_statuses import ConfirmationStatus

PositiveIntegerString = Annotated[str, Field(pattern=r"^[1-9]\d*$")]
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class SupplierStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    INACTIVE = "inactive"


class SupplierSourceType(str, Enum):
    CONTRACT = "contract"
    INVOICE = "invoice"
    MANUAL = "manual"


class SupplierData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    standard_name: str
    tax_number: str | None
    source_type: SupplierSourceType
    source_contract_id: UUID | None
    source_invoice_id: UUID | None
    confirmation_status: ConfirmationStatus
    status: SupplierStatus
    confirmed_by: UUID | None
    confirmed_at: datetime | None
    row_version: PositiveIntegerString

    @model_validator(mode="after")
    def validate_state_and_source(self) -> SupplierData:
        expected_reference = {
            SupplierSourceType.CONTRACT: (True, False),
            SupplierSourceType.INVOICE: (False, True),
            SupplierSourceType.MANUAL: (False, False),
        }[self.source_type]
        observed_reference = (
            self.source_contract_id is not None,
            self.source_invoice_id is not None,
        )
        if observed_reference != expected_reference:
            raise ValueError("supplier source reference is invalid")
        expected_state = {
            ConfirmationStatus.UNCONFIRMED: SupplierStatus.CANDIDATE,
            ConfirmationStatus.CONFIRMED: SupplierStatus.ACTIVE,
            ConfirmationStatus.REJECTED: SupplierStatus.INACTIVE,
        }[self.confirmation_status]
        if self.status is not expected_state:
            raise ValueError("supplier state matrix is invalid")
        confirmed = self.confirmed_by is not None and self.confirmed_at is not None
        if (self.confirmation_status is ConfirmationStatus.UNCONFIRMED) == confirmed:
            raise ValueError("supplier confirmation metadata is invalid")
        return self


class SupplierListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    page_size: int = Field(default=20, ge=1, le=100)


class SupplierListData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    items: tuple[SupplierData, ...]
    page_size: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def validate_page_shape(self) -> SupplierListData:
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size")
        if self.next_cursor is not None and len(self.items) != self.page_size:
            raise ValueError("next_cursor requires a full page")
        return self


class SupplierSourceResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_type: Literal["contract", "invoice"]
    source_id: UUID
    row_version: PositiveIntegerString

    @field_validator("source_id", mode="before")
    @classmethod
    def parse_source_id(cls, value: object) -> object:
        if type(value) is UUID:
            return value
        if type(value) is not str:
            raise ValueError("source_id must be a canonical UUID")
        try:
            parsed = UUID(value)
        except ValueError:
            raise ValueError("source_id must be a canonical UUID") from None
        if str(parsed) != value:
            raise ValueError("source_id must be a canonical UUID")
        return parsed


class SupplierResolveData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    supplier: SupplierData
    source_row_version: PositiveIntegerString
    created: bool
    reused: bool


class SupplierCandidateUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    row_version: PositiveIntegerString
    reason: str = Field(min_length=1, max_length=1000)
    standard_name: str | None = Field(default=None, min_length=1, max_length=300)
    tax_number: str | None = Field(default=None, min_length=1, max_length=32)
    decision: Literal["confirmed", "rejected"] | None = None

    @field_validator("reason", "standard_name", "tax_number")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip() or _CONTROL_CHARACTER_PATTERN.search(value) is not None:
            raise ValueError("text is not normalized")
        return value

    @model_validator(mode="after")
    def validate_change(self) -> SupplierCandidateUpdateRequest:
        for field in ("standard_name", "tax_number"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if not {"standard_name", "tax_number", "decision"}.intersection(self.model_fields_set):
            raise ValueError("at least one supplier change is required")
        if "decision" in self.model_fields_set and self.decision is None:
            raise ValueError("decision cannot be null")
        return self


class SupplierMutationData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    supplier: SupplierData
    candidate_id: UUID
    candidate_row_version: PositiveIntegerString
    source_row_version: PositiveIntegerString
    correction_id: UUID
    reused: bool


class SupplierReadQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


__all__ = [
    "SupplierCandidateUpdateRequest",
    "SupplierData",
    "SupplierListData",
    "SupplierListQuery",
    "SupplierMutationData",
    "SupplierReadQuery",
    "SupplierResolveData",
    "SupplierSourceResolveRequest",
    "SupplierSourceType",
    "SupplierStatus",
]
