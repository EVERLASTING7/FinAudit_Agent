"""合同与发票候选关系的纯离线匹配依据。

文本规范化属于上游事实生产边界；本模块只做逐字比较，不选择或执行
尚未获批的 Unicode、税号或名称规范化规则。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from uuid import UUID


class MatchEvidenceStatus(str, Enum):
    """单项匹配依据的三态结果。"""

    MATCHED = "matched"
    MISMATCHED = "mismatched"
    UNAVAILABLE = "unavailable"


class ContractInvoiceReasonCode(str, Enum):
    """合同发票候选的稳定、可解释原因代码。"""

    TAX_NO_MATCHED = "tax_no_matched"
    TAX_NO_MISMATCHED = "tax_no_mismatched"
    TAX_NO_UNAVAILABLE = "tax_no_unavailable"
    NAME_MATCHED = "name_matched"
    NAME_MISMATCHED = "name_mismatched"
    NAME_UNAVAILABLE = "name_unavailable"
    DATE_IN_RANGE = "date_in_range"
    DATE_OUT_OF_RANGE = "date_out_of_range"
    DATE_UNAVAILABLE = "date_unavailable"


_REASON_STATUS = {
    ContractInvoiceReasonCode.TAX_NO_MATCHED: MatchEvidenceStatus.MATCHED,
    ContractInvoiceReasonCode.TAX_NO_MISMATCHED: MatchEvidenceStatus.MISMATCHED,
    ContractInvoiceReasonCode.TAX_NO_UNAVAILABLE: MatchEvidenceStatus.UNAVAILABLE,
    ContractInvoiceReasonCode.NAME_MATCHED: MatchEvidenceStatus.MATCHED,
    ContractInvoiceReasonCode.NAME_MISMATCHED: MatchEvidenceStatus.MISMATCHED,
    ContractInvoiceReasonCode.NAME_UNAVAILABLE: MatchEvidenceStatus.UNAVAILABLE,
    ContractInvoiceReasonCode.DATE_IN_RANGE: MatchEvidenceStatus.MATCHED,
    ContractInvoiceReasonCode.DATE_OUT_OF_RANGE: MatchEvidenceStatus.MISMATCHED,
    ContractInvoiceReasonCode.DATE_UNAVAILABLE: MatchEvidenceStatus.UNAVAILABLE,
}

_STATUS_SORT_ORDER = {
    MatchEvidenceStatus.MATCHED: 0,
    MatchEvidenceStatus.MISMATCHED: 1,
    MatchEvidenceStatus.UNAVAILABLE: 2,
}


@dataclass(frozen=True, slots=True)
class ContractInvoiceMatchReason:
    """一个比较维度的结果与稳定原因代码。"""

    status: MatchEvidenceStatus
    code: ContractInvoiceReasonCode

    def __post_init__(self) -> None:
        if type(self.status) is not MatchEvidenceStatus:
            raise ValueError("status must be a MatchEvidenceStatus")
        if type(self.code) is not ContractInvoiceReasonCode:
            raise ValueError("code must be a ContractInvoiceReasonCode")
        if _REASON_STATUS[self.code] is not self.status:
            raise ValueError("reason code must match its evidence status")


@dataclass(frozen=True, slots=True)
class InvoiceMatchFacts:
    """上游已规范化的单张发票匹配事实；本模块不改写文本。"""

    invoice_id: UUID
    seller_tax_no: str | None = field(repr=False)
    seller_name: str | None = field(repr=False)
    invoice_date: date | None

    def __post_init__(self) -> None:
        _validate_exact_uuid(self.invoice_id, name="invoice_id")
        _validate_optional_non_blank_text(self.seller_tax_no, name="seller_tax_no")
        _validate_optional_non_blank_text(self.seller_name, name="seller_name")
        _validate_optional_exact_date(self.invoice_date, name="invoice_date")


@dataclass(frozen=True, slots=True)
class ContractMatchFacts:
    """上游已规范化的一份合同候选匹配事实。"""

    contract_id: UUID
    party_b_tax_no: str | None = field(repr=False)
    party_b_name: str | None = field(repr=False)
    effective_date: date | None
    expiry_date: date | None

    def __post_init__(self) -> None:
        _validate_exact_uuid(self.contract_id, name="contract_id")
        _validate_optional_non_blank_text(self.party_b_tax_no, name="party_b_tax_no")
        _validate_optional_non_blank_text(self.party_b_name, name="party_b_name")
        _validate_optional_exact_date(self.effective_date, name="effective_date")
        _validate_optional_exact_date(self.expiry_date, name="expiry_date")
        if (
            self.effective_date is not None
            and self.expiry_date is not None
            and self.effective_date > self.expiry_date
        ):
            raise ValueError("contract effective date must not be after expiry date")


@dataclass(frozen=True, slots=True)
class ContractInvoiceCandidate:
    """不含总分或确认行为的只读、可解释候选。"""

    invoice_id: UUID
    contract_id: UUID
    tax_no_reason: ContractInvoiceMatchReason
    name_reason: ContractInvoiceMatchReason
    date_reason: ContractInvoiceMatchReason
    contract_party_b_tax_no: str | None = field(repr=False)
    invoice_seller_tax_no: str | None = field(repr=False)
    contract_party_b_name: str | None = field(repr=False)
    invoice_seller_name: str | None = field(repr=False)
    invoice_date: date | None
    contract_effective_date: date | None
    contract_expiry_date: date | None

    def __post_init__(self) -> None:
        _validate_exact_uuid(self.invoice_id, name="invoice_id")
        _validate_exact_uuid(self.contract_id, name="contract_id")
        reasons = (self.tax_no_reason, self.name_reason, self.date_reason)
        if any(type(reason) is not ContractInvoiceMatchReason for reason in reasons):
            raise ValueError("candidate reasons must be ContractInvoiceMatchReason values")
        _validate_optional_non_blank_text(
            self.contract_party_b_tax_no,
            name="contract_party_b_tax_no",
        )
        _validate_optional_non_blank_text(
            self.invoice_seller_tax_no,
            name="invoice_seller_tax_no",
        )
        _validate_optional_non_blank_text(
            self.contract_party_b_name,
            name="contract_party_b_name",
        )
        _validate_optional_non_blank_text(
            self.invoice_seller_name,
            name="invoice_seller_name",
        )
        _validate_optional_exact_date(self.invoice_date, name="invoice_date")
        _validate_optional_exact_date(
            self.contract_effective_date,
            name="contract_effective_date",
        )
        _validate_optional_exact_date(
            self.contract_expiry_date,
            name="contract_expiry_date",
        )


@dataclass(frozen=True, slots=True)
class ContractInvoiceMatchReasons:
    """合同与发票之间三个相互独立的可解释匹配依据。"""

    tax_no_match: bool
    name_match: bool
    date_in_range: bool

    def __post_init__(self) -> None:
        values = (self.tax_no_match, self.name_match, self.date_in_range)
        if any(type(value) is not bool for value in values):
            raise ValueError("match reasons must be exact bool values")


def _validate_non_blank_text(value: object, *, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-blank exact str")


def _validate_optional_non_blank_text(value: object, *, name: str) -> None:
    if value is not None and (type(value) is not str or not value.strip()):
        raise ValueError(f"{name} must be a non-blank exact str or None")


def _validate_exact_date(value: object, *, name: str) -> None:
    if type(value) is not date:
        raise ValueError(f"{name} must be an exact datetime.date")


def _validate_optional_exact_date(value: object, *, name: str) -> None:
    if value is not None and type(value) is not date:
        raise ValueError(f"{name} must be an exact datetime.date or None")


def _validate_exact_uuid(value: object, *, name: str) -> None:
    if type(value) is not UUID:
        raise ValueError(f"{name} must be an exact UUID")


def _reason(code: ContractInvoiceReasonCode) -> ContractInvoiceMatchReason:
    return ContractInvoiceMatchReason(status=_REASON_STATUS[code], code=code)


def _derive_text_reason(
    contract_value: str | None,
    invoice_value: str | None,
    *,
    matched: ContractInvoiceReasonCode,
    mismatched: ContractInvoiceReasonCode,
    unavailable: ContractInvoiceReasonCode,
) -> ContractInvoiceMatchReason:
    if contract_value is None or invoice_value is None:
        return _reason(unavailable)
    return _reason(matched if contract_value == invoice_value else mismatched)


def _derive_date_reason(
    invoice_date: date | None,
    contract_effective_date: date | None,
    contract_expiry_date: date | None,
) -> ContractInvoiceMatchReason:
    if invoice_date is None or contract_effective_date is None or contract_expiry_date is None:
        return _reason(ContractInvoiceReasonCode.DATE_UNAVAILABLE)
    code = (
        ContractInvoiceReasonCode.DATE_IN_RANGE
        if contract_effective_date <= invoice_date <= contract_expiry_date
        else ContractInvoiceReasonCode.DATE_OUT_OF_RANGE
    )
    return _reason(code)


def derive_contract_invoice_candidates(
    invoice: InvoiceMatchFacts,
    contracts: tuple[ContractMatchFacts, ...],
) -> tuple[ContractInvoiceCandidate, ...]:
    """生成不改变主合同事实的稳定候选集合。

    排序按税号、名称、日期依次比较；每一维均为 matched、mismatched、
    unavailable，最后以合同 UUID 原始字节打破平局，因此与输入顺序无关。
    """

    if type(invoice) is not InvoiceMatchFacts:
        raise ValueError("invoice must be an InvoiceMatchFacts")
    if type(contracts) is not tuple or any(
        type(contract) is not ContractMatchFacts for contract in contracts
    ):
        raise ValueError("contracts must be a tuple of ContractMatchFacts")
    contract_ids = tuple(contract.contract_id for contract in contracts)
    if len(contract_ids) != len(set(contract_ids)):
        raise ValueError("contract_id must be unique within candidate input")

    candidates = tuple(
        ContractInvoiceCandidate(
            invoice_id=invoice.invoice_id,
            contract_id=contract.contract_id,
            tax_no_reason=_derive_text_reason(
                contract.party_b_tax_no,
                invoice.seller_tax_no,
                matched=ContractInvoiceReasonCode.TAX_NO_MATCHED,
                mismatched=ContractInvoiceReasonCode.TAX_NO_MISMATCHED,
                unavailable=ContractInvoiceReasonCode.TAX_NO_UNAVAILABLE,
            ),
            name_reason=_derive_text_reason(
                contract.party_b_name,
                invoice.seller_name,
                matched=ContractInvoiceReasonCode.NAME_MATCHED,
                mismatched=ContractInvoiceReasonCode.NAME_MISMATCHED,
                unavailable=ContractInvoiceReasonCode.NAME_UNAVAILABLE,
            ),
            date_reason=_derive_date_reason(
                invoice.invoice_date,
                contract.effective_date,
                contract.expiry_date,
            ),
            contract_party_b_tax_no=contract.party_b_tax_no,
            invoice_seller_tax_no=invoice.seller_tax_no,
            contract_party_b_name=contract.party_b_name,
            invoice_seller_name=invoice.seller_name,
            invoice_date=invoice.invoice_date,
            contract_effective_date=contract.effective_date,
            contract_expiry_date=contract.expiry_date,
        )
        for contract in contracts
    )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                _STATUS_SORT_ORDER[candidate.tax_no_reason.status],
                _STATUS_SORT_ORDER[candidate.name_reason.status],
                _STATUS_SORT_ORDER[candidate.date_reason.status],
                candidate.contract_id.bytes,
            ),
        )
    )


def derive_contract_invoice_match_reasons(
    contract_party_b_tax_no: str,
    invoice_seller_tax_no: str,
    contract_party_b_name: str,
    invoice_seller_name: str,
    invoice_date: date,
    contract_effective_date: date,
    contract_expiry_date: date,
) -> ContractInvoiceMatchReasons:
    """根据调用方提供的完整事实生成三个逐字、独立的匹配依据。"""

    text_fields = (
        ("contract_party_b_tax_no", contract_party_b_tax_no),
        ("invoice_seller_tax_no", invoice_seller_tax_no),
        ("contract_party_b_name", contract_party_b_name),
        ("invoice_seller_name", invoice_seller_name),
    )
    for field_name, text_value in text_fields:
        _validate_non_blank_text(text_value, name=field_name)

    date_fields = (
        ("invoice_date", invoice_date),
        ("contract_effective_date", contract_effective_date),
        ("contract_expiry_date", contract_expiry_date),
    )
    for field_name, date_value in date_fields:
        _validate_exact_date(date_value, name=field_name)

    if contract_effective_date > contract_expiry_date:
        raise ValueError("contract effective date must not be after expiry date")

    return ContractInvoiceMatchReasons(
        tax_no_match=contract_party_b_tax_no == invoice_seller_tax_no,
        name_match=contract_party_b_name == invoice_seller_name,
        date_in_range=contract_effective_date <= invoice_date <= contract_expiry_date,
    )
