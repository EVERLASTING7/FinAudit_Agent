"""业务对象可复用的固定状态合同。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class ConfirmationStatus(str, Enum):
    """业务对象与字段的固定确认状态。"""

    UNCONFIRMED = "unconfirmed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class InvoiceStatus(str, Enum):
    """发票业务生命周期的固定状态。"""

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    VOIDED = "voided"
    ARCHIVED = "archived"


class InvoiceDuplicateStatus(str, Enum):
    """发票重复检测与人工处理的固定状态。"""

    NOT_CHECKED = "not_checked"
    UNIQUE = "unique"
    SUSPECTED = "suspected"
    CONFIRMED_DUPLICATE = "confirmed_duplicate"
    EXCEPTION_APPROVED = "exception_approved"


class InvoiceStatuses(BaseModel):
    """分别表达发票确认、业务生命周期和重复处理状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirmation_status: ConfirmationStatus
    status: InvoiceStatus
    duplicate_status: InvoiceDuplicateStatus
