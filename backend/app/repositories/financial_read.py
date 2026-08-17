"""MVP-VS-02 财务对象的组织隔离只读 Repository。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from math import isfinite
from types import MappingProxyType
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.financial import (
    Contract,
    ContractField,
    ContractInvoice,
    Invoice,
    InvoiceItem,
    SupplementaryAgreement,
    SupplementaryAgreementChange,
)


class FinancialReadIntegrityError(RuntimeError):
    """持久化财务事实无法安全投影为内部只读视图。"""


@dataclass(frozen=True, slots=True)
class ContractReadView:
    """合同当前持久化事实；不包含未落库的补充协议字段变更。"""

    id: UUID
    organization_id: UUID
    contract_no: str | None = field(repr=False)
    name: str = field(repr=False)
    party_a_name: str | None = field(repr=False)
    party_a_tax_no: str | None = field(repr=False)
    party_b_name: str | None = field(repr=False)
    party_b_tax_no: str | None = field(repr=False)
    supplier_id: UUID | None = field(repr=False)
    amount: Decimal | None = field(repr=False)
    currency: str | None = field(repr=False)
    signed_date: date | None = field(repr=False)
    effective_date: date | None = field(repr=False)
    expiry_date: date | None = field(repr=False)
    payment_method: str | None = field(repr=False)
    payment_terms: str | None = field(repr=False)
    confirmation_status: str
    status: str
    confirmed_by: UUID | None = field(repr=False)
    confirmed_at: datetime | None = field(repr=False)
    critical_fact_hash: str = field(repr=False)
    row_version: int


@dataclass(frozen=True, slots=True)
class SupplementaryAgreementReadView:
    """补充协议 header；accepted Schema 尚无字段级 change 载体。"""

    id: UUID
    organization_id: UUID
    contract_id: UUID
    agreement_no: str | None = field(repr=False)
    name: str = field(repr=False)
    signed_date: date | None = field(repr=False)
    effective_date: date = field(repr=False)
    status: str
    confirmation_status: str
    confirmed_by: UUID | None = field(repr=False)
    confirmed_at: datetime | None = field(repr=False)
    confirmation_reason: str | None = field(repr=False)
    critical_fact_hash: str = field(repr=False)
    row_version: int


@dataclass(frozen=True, slots=True)
class ContractFieldReadView:
    """合同扩展字段中可参与投影的原值。"""

    field_code: str
    value_type: str
    value: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class SupplementaryChangeReadView:
    """一个补充协议字段变更及其生效资格事实。"""

    agreement_id: UUID
    field_code: str
    value_type: str
    new_value: object = field(repr=False)
    agreement_status: str
    agreement_confirmation_status: str
    change_confirmation_status: str
    effective_date: date


@dataclass(frozen=True, slots=True)
class EffectiveContractReadView:
    """合同、扩展原值与全部当前补充协议变更。"""

    contract: ContractReadView
    extended_fields: tuple[ContractFieldReadView, ...]
    changes: tuple[SupplementaryChangeReadView, ...]


@dataclass(frozen=True, slots=True)
class InvoiceItemReadView:
    """发票明细的精确金额与只读证据。"""

    id: UUID
    invoice_id: UUID
    line_no: int = field(repr=False)
    item_name: str | None = field(repr=False)
    specification: str | None = field(repr=False)
    unit: str | None = field(repr=False)
    quantity: Decimal | None = field(repr=False)
    unit_price: Decimal | None = field(repr=False)
    amount_excluding_tax: Decimal | None = field(repr=False)
    tax_rate: Decimal | None = field(repr=False)
    tax_amount: Decimal | None = field(repr=False)
    total_amount: Decimal | None = field(repr=False)
    evidence: Mapping[str, object] = field(repr=False)
    row_version: int


@dataclass(frozen=True, slots=True)
class InvoiceReadView:
    """发票当前持久化事实及其稳定排序明细。"""

    id: UUID
    organization_id: UUID
    invoice_code: str | None = field(repr=False)
    invoice_number: str | None = field(repr=False)
    invoice_type: str | None = field(repr=False)
    invoice_date: date | None = field(repr=False)
    buyer_name: str | None = field(repr=False)
    buyer_tax_no: str | None = field(repr=False)
    seller_name: str | None = field(repr=False)
    seller_tax_no: str | None = field(repr=False)
    supplier_id: UUID | None = field(repr=False)
    amount_excluding_tax: Decimal | None = field(repr=False)
    tax_amount: Decimal | None = field(repr=False)
    total_amount: Decimal | None = field(repr=False)
    currency: str | None = field(repr=False)
    confirmation_status: str
    duplicate_status: str
    status: str
    field_evidence: Mapping[str, object] = field(repr=False)
    confirmed_by: UUID | None = field(repr=False)
    confirmed_at: datetime | None = field(repr=False)
    critical_fact_hash: str = field(repr=False)
    row_version: int
    items: tuple[InvoiceItemReadView, ...] = field(repr=False)
    is_red_invoice: bool | None = field(default=None, repr=False)


InvoiceDuplicateBasisStatus = Literal[
    "ready",
    "incomplete_identity",
    "source_voided",
]


@dataclass(frozen=True, slots=True)
class InvoiceDuplicateCandidateReadView:
    """Exact-duplicate candidate fields allowed by the public list projection."""

    id: UUID
    invoice_code: str | None = field(repr=False)
    invoice_number: str | None = field(repr=False)
    invoice_date: date | None = field(repr=False)
    seller_name: str | None = field(repr=False)
    total_amount: Decimal | None = field(repr=False)
    currency: str | None = field(repr=False)
    confirmation_status: str
    duplicate_status: str
    status: str


@dataclass(frozen=True, slots=True)
class InvoiceExactDuplicatePairReadView:
    """Two visible invoice summaries that share one raw, non-NULL identity."""

    source: InvoiceDuplicateCandidateReadView
    candidate: InvoiceDuplicateCandidateReadView
    invoice_code: str = field(repr=False)
    invoice_number: str = field(repr=False)
    seller_tax_no: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ContractInvoiceReadView:
    """未软删除且两端均可见的合同发票关系。"""

    id: UUID
    contract_id: UUID
    invoice_id: UUID
    status: str
    match_reasons: Mapping[str, object] = field(repr=False)
    suggested_by: str | None = field(repr=False)
    confirmed_by: UUID | None = field(repr=False)
    confirmed_at: datetime | None = field(repr=False)
    cancelled_by: UUID | None = field(repr=False)
    cancelled_at: datetime | None = field(repr=False)
    cancel_reason: str | None = field(repr=False)
    row_version: int
    created_at: datetime = field(repr=False)
    created_by: UUID = field(repr=False)


@dataclass(frozen=True, slots=True)
class InvoicePrimaryContractReadView:
    """Visible invoice anchor and its optional current confirmed primary contract."""

    primary_contract: ContractReadView | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class FinancialReadView:
    """一个组织的稳定、与 SQLAlchemy Session 生命周期隔离的财务视图。"""

    organization_id: UUID
    baseline_date: date = field(repr=False)
    contracts: tuple[ContractReadView, ...] = field(repr=False)
    supplementary_agreements: tuple[SupplementaryAgreementReadView, ...] = field(repr=False)
    invoices: tuple[InvoiceReadView, ...] = field(repr=False)
    contract_invoices: tuple[ContractInvoiceReadView, ...] = field(repr=False)


def _invalid_persisted_value(path: str) -> FinancialReadIntegrityError:
    return FinancialReadIntegrityError(f"invalid persisted financial value at {path}")


def _finite_decimal(value: Decimal | None, *, path: str) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not Decimal or not value.is_finite():
        raise _invalid_persisted_value(path)
    return value


def _freeze_json_value(value: object, *, path: str) -> object:
    value_type = type(value)
    if value is None or value_type in (bool, int, str):
        return value
    if value_type is float:
        if not isfinite(cast(float, value)):
            raise _invalid_persisted_value(path)
        return value
    if value_type is Decimal:
        return _finite_decimal(cast(Decimal, value), path=path)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        items: list[tuple[str, object]] = []
        for raw_key, child in mapping.items():
            if type(raw_key) is not str:
                raise _invalid_persisted_value(path)
            items.append((raw_key, child))
        return MappingProxyType(
            {
                key: _freeze_json_value(child, path=f"{path}.*")
                for key, child in sorted(items, key=lambda item: item[0])
            }
        )
    if value_type in (list, tuple):
        sequence = cast(list[object] | tuple[object, ...], value)
        return tuple(_freeze_json_value(child, path=f"{path}[]") for child in sequence)
    raise _invalid_persisted_value(path)


def _freeze_json_mapping(value: Mapping[str, object], *, path: str) -> Mapping[str, object]:
    frozen = _freeze_json_value(value, path=path)
    if not isinstance(frozen, Mapping):
        raise _invalid_persisted_value(path)
    return cast(Mapping[str, object], frozen)


def _contract_view(contract: Contract) -> ContractReadView:
    return ContractReadView(
        id=contract.id,
        organization_id=contract.organization_id,
        contract_no=contract.contract_no,
        name=contract.name,
        party_a_name=contract.party_a_name,
        party_a_tax_no=contract.party_a_tax_no,
        party_b_name=contract.party_b_name,
        party_b_tax_no=contract.party_b_tax_no,
        supplier_id=contract.supplier_id,
        amount=_finite_decimal(contract.amount, path="contracts.amount"),
        currency=contract.currency,
        signed_date=contract.signed_date,
        effective_date=contract.effective_date,
        expiry_date=contract.expiry_date,
        payment_method=contract.payment_method,
        payment_terms=contract.payment_terms,
        confirmation_status=contract.confirmation_status,
        status=contract.status,
        confirmed_by=contract.confirmed_by,
        confirmed_at=contract.confirmed_at,
        critical_fact_hash=contract.critical_fact_hash,
        row_version=contract.row_version,
    )


def _supplementary_agreement_view(
    agreement: SupplementaryAgreement,
) -> SupplementaryAgreementReadView:
    return SupplementaryAgreementReadView(
        id=agreement.id,
        organization_id=agreement.organization_id,
        contract_id=agreement.contract_id,
        agreement_no=agreement.agreement_no,
        name=agreement.name,
        signed_date=agreement.signed_date,
        effective_date=agreement.effective_date,
        status=agreement.status,
        confirmation_status=agreement.confirmation_status,
        confirmed_by=agreement.confirmed_by,
        confirmed_at=agreement.confirmed_at,
        confirmation_reason=agreement.confirmation_reason,
        critical_fact_hash=agreement.critical_fact_hash,
        row_version=agreement.row_version,
    )


def _invoice_item_view(item: InvoiceItem) -> InvoiceItemReadView:
    return InvoiceItemReadView(
        id=item.id,
        invoice_id=item.invoice_id,
        line_no=item.line_no,
        item_name=item.item_name,
        specification=item.specification,
        unit=item.unit,
        quantity=_finite_decimal(item.quantity, path="invoice_items.quantity"),
        unit_price=_finite_decimal(item.unit_price, path="invoice_items.unit_price"),
        amount_excluding_tax=_finite_decimal(
            item.amount_excluding_tax,
            path="invoice_items.amount_excluding_tax",
        ),
        tax_rate=_finite_decimal(item.tax_rate, path="invoice_items.tax_rate"),
        tax_amount=_finite_decimal(item.tax_amount, path="invoice_items.tax_amount"),
        total_amount=_finite_decimal(item.total_amount, path="invoice_items.total_amount"),
        evidence=_freeze_json_mapping(item.evidence_json, path="invoice_items.evidence_json"),
        row_version=item.row_version,
    )


def _invoice_view(
    invoice: Invoice,
    items: tuple[InvoiceItemReadView, ...],
) -> InvoiceReadView:
    return InvoiceReadView(
        id=invoice.id,
        organization_id=invoice.organization_id,
        invoice_code=invoice.invoice_code,
        invoice_number=invoice.invoice_number,
        invoice_type=invoice.invoice_type,
        is_red_invoice=invoice.is_red_invoice,
        invoice_date=invoice.invoice_date,
        buyer_name=invoice.buyer_name,
        buyer_tax_no=invoice.buyer_tax_no,
        seller_name=invoice.seller_name,
        seller_tax_no=invoice.seller_tax_no,
        supplier_id=invoice.supplier_id,
        amount_excluding_tax=_finite_decimal(
            invoice.amount_excluding_tax,
            path="invoices.amount_excluding_tax",
        ),
        tax_amount=_finite_decimal(invoice.tax_amount, path="invoices.tax_amount"),
        total_amount=_finite_decimal(invoice.total_amount, path="invoices.total_amount"),
        currency=invoice.currency,
        confirmation_status=invoice.confirmation_status,
        duplicate_status=invoice.duplicate_status,
        status=invoice.status,
        field_evidence=_freeze_json_mapping(
            invoice.field_evidence_json,
            path="invoices.field_evidence_json",
        ),
        confirmed_by=invoice.confirmed_by,
        confirmed_at=invoice.confirmed_at,
        critical_fact_hash=invoice.critical_fact_hash,
        row_version=invoice.row_version,
        items=items,
    )


def _contract_invoice_view(relation: ContractInvoice) -> ContractInvoiceReadView:
    return ContractInvoiceReadView(
        id=relation.id,
        contract_id=relation.contract_id,
        invoice_id=relation.invoice_id,
        status=relation.status,
        match_reasons=_freeze_json_mapping(
            relation.match_reasons_json,
            path="contract_invoices.match_reasons_json",
        ),
        suggested_by=relation.suggested_by,
        confirmed_by=relation.confirmed_by,
        confirmed_at=relation.confirmed_at,
        cancelled_by=relation.cancelled_by,
        cancelled_at=relation.cancelled_at,
        cancel_reason=relation.cancel_reason,
        row_version=relation.row_version,
        created_at=relation.created_at,
        created_by=relation.created_by,
    )


def _optional_text_key(value: str | None) -> tuple[bool, str]:
    return value is None, value or ""


class FinancialReadRepository:
    """只执行查询；事务提交与回滚由调用方 Application Service 控制。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def read_contract(
        self,
        organization_id: UUID,
        contract_id: UUID,
    ) -> ContractReadView | None:
        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(contract_id) is not UUID:
            raise ValueError("contract_id must be an exact uuid.UUID")
        contract = self._session.scalar(
            select(Contract).where(
                Contract.id == contract_id,
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
            )
        )
        return None if contract is None else _contract_view(contract)

    def read_effective_contract(
        self,
        organization_id: UUID,
        contract_id: UUID,
    ) -> EffectiveContractReadView | None:
        """读取有效字段投影所需的同组织 PostgreSQL 事实。"""

        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(contract_id) is not UUID:
            raise ValueError("contract_id must be an exact uuid.UUID")
        contract = self._session.scalar(
            select(Contract).where(
                Contract.id == contract_id,
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
            )
        )
        if contract is None:
            return None
        field_models = self._session.scalars(
            select(ContractField)
            .where(ContractField.contract_id == contract_id)
            .order_by(ContractField.field_code)
        ).all()
        change_rows = self._session.execute(
            select(SupplementaryAgreementChange, SupplementaryAgreement)
            .join(
                SupplementaryAgreement,
                SupplementaryAgreementChange.supplementary_agreement_id
                == SupplementaryAgreement.id,
            )
            .where(
                SupplementaryAgreement.contract_id == contract_id,
                SupplementaryAgreement.organization_id == organization_id,
                SupplementaryAgreement.deleted_at.is_(None),
            )
            .order_by(
                SupplementaryAgreement.effective_date,
                SupplementaryAgreement.id,
                SupplementaryAgreementChange.field_code,
            )
        ).all()
        extended_fields: list[ContractFieldReadView] = []
        for model in field_models:
            if model.confirmation_status == "confirmed" and model.confirmed_value_json is not None:
                extended_fields.append(
                    ContractFieldReadView(
                        field_code=model.field_code,
                        value_type=model.value_type,
                        value=model.confirmed_value_json,
                    )
                )
        return EffectiveContractReadView(
            contract=_contract_view(contract),
            extended_fields=tuple(extended_fields),
            changes=tuple(
                SupplementaryChangeReadView(
                    agreement_id=agreement.id,
                    field_code=change.field_code,
                    value_type=change.value_type,
                    new_value=change.new_value_json,
                    agreement_status=agreement.status,
                    agreement_confirmation_status=agreement.confirmation_status,
                    change_confirmation_status=change.confirmation_status,
                    effective_date=agreement.effective_date,
                )
                for change, agreement in change_rows
            ),
        )

    def read_contract_page(
        self,
        organization_id: UUID,
        page_size: int,
        cursor_date: date | None = None,
        cursor_id: UUID | None = None,
    ) -> tuple[tuple[ContractReadView, ...], bool]:
        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be an integer between 1 and 100")
        if cursor_id is not None and type(cursor_id) is not UUID:
            raise ValueError("cursor_id must be an exact uuid.UUID")
        if cursor_date is not None and type(cursor_date) is not date:
            raise ValueError("cursor_date must be an exact datetime.date")
        if cursor_date is not None and cursor_id is None:
            raise ValueError("cursor_id is required when cursor_date is provided")

        statement = select(Contract).where(
            Contract.organization_id == organization_id,
            Contract.deleted_at.is_(None),
        )
        if cursor_id is not None:
            if cursor_date is None:
                statement = statement.where(
                    Contract.effective_date.is_(None),
                    Contract.id < cursor_id,
                )
            else:
                statement = statement.where(
                    or_(
                        Contract.effective_date < cursor_date,
                        and_(
                            Contract.effective_date == cursor_date,
                            Contract.id < cursor_id,
                        ),
                        Contract.effective_date.is_(None),
                    )
                )
        contract_models = self._session.scalars(
            statement.order_by(
                Contract.effective_date.desc().nulls_last(),
                Contract.id.desc(),
            ).limit(page_size + 1)
        ).all()
        has_more = len(contract_models) > page_size
        return tuple(_contract_view(contract) for contract in contract_models[:page_size]), has_more

    def read_supplementary_agreement_header_page(
        self,
        organization_id: UUID,
        contract_id: UUID,
        page_size: int,
        cursor_date: date | None = None,
        cursor_id: UUID | None = None,
    ) -> tuple[tuple[SupplementaryAgreementReadView, ...], bool] | None:
        """Read one bounded page of current raw headers under a visible contract."""

        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(contract_id) is not UUID:
            raise ValueError("contract_id must be an exact uuid.UUID")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be an integer between 1 and 100")
        if cursor_date is not None and type(cursor_date) is not date:
            raise ValueError("cursor_date must be an exact datetime.date")
        if cursor_id is not None and type(cursor_id) is not UUID:
            raise ValueError("cursor_id must be an exact uuid.UUID")
        if (cursor_date is None) != (cursor_id is None):
            raise ValueError("cursor date and id must be provided together")

        visible_contract_id = self._session.scalar(
            select(Contract.id).where(
                Contract.id == contract_id,
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
            )
        )
        if visible_contract_id is None:
            return None

        statement = (
            select(SupplementaryAgreement)
            .join(Contract, SupplementaryAgreement.contract_id == Contract.id)
            .where(
                SupplementaryAgreement.organization_id == organization_id,
                SupplementaryAgreement.contract_id == contract_id,
                SupplementaryAgreement.deleted_at.is_(None),
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
            )
        )
        if cursor_date is not None and cursor_id is not None:
            statement = statement.where(
                or_(
                    SupplementaryAgreement.effective_date < cursor_date,
                    and_(
                        SupplementaryAgreement.effective_date == cursor_date,
                        SupplementaryAgreement.id < cursor_id,
                    ),
                )
            )
        agreement_models = self._session.scalars(
            statement.order_by(
                SupplementaryAgreement.effective_date.desc(),
                SupplementaryAgreement.id.desc(),
            ).limit(page_size + 1)
        ).all()
        has_more = len(agreement_models) > page_size
        return (
            tuple(
                _supplementary_agreement_view(agreement)
                for agreement in agreement_models[:page_size]
            ),
            has_more,
        )

    def read_invoice(
        self,
        organization_id: UUID,
        invoice_id: UUID,
    ) -> InvoiceReadView | None:
        """Read one visible invoice within the caller's organization boundary."""

        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(invoice_id) is not UUID:
            raise ValueError("invoice_id must be an exact uuid.UUID")

        invoice = self._session.scalar(
            select(Invoice).where(
                Invoice.id == invoice_id,
                Invoice.organization_id == organization_id,
                Invoice.deleted_at.is_(None),
            )
        )
        if invoice is None:
            return None
        items = self._session.scalars(
            select(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id)
        ).all()
        item_views = sorted(
            (_invoice_item_view(item) for item in items),
            key=lambda item: (item.line_no, item.id.bytes),
        )
        return _invoice_view(invoice, tuple(item_views))

    def read_invoice_page(
        self,
        organization_id: UUID,
        page_size: int,
        cursor_date: date | None = None,
        cursor_id: UUID | None = None,
    ) -> tuple[tuple[InvoiceReadView, ...], bool]:
        """Read one stable, bounded page of visible invoice headers."""

        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be an integer between 1 and 100")
        if cursor_id is not None and type(cursor_id) is not UUID:
            raise ValueError("cursor_id must be an exact uuid.UUID")
        if cursor_date is not None and type(cursor_date) is not date:
            raise ValueError("cursor_date must be an exact datetime.date")
        if cursor_date is not None and cursor_id is None:
            raise ValueError("cursor_id is required when cursor_date is provided")

        statement = select(Invoice).where(
            Invoice.organization_id == organization_id,
            Invoice.deleted_at.is_(None),
        )
        if cursor_id is not None:
            if cursor_date is None:
                statement = statement.where(
                    Invoice.invoice_date.is_(None),
                    Invoice.id < cursor_id,
                )
            else:
                statement = statement.where(
                    or_(
                        Invoice.invoice_date < cursor_date,
                        and_(
                            Invoice.invoice_date == cursor_date,
                            Invoice.id < cursor_id,
                        ),
                        Invoice.invoice_date.is_(None),
                    )
                )
        invoice_models = self._session.scalars(
            statement.order_by(
                Invoice.invoice_date.desc().nulls_last(),
                Invoice.id.desc(),
            ).limit(page_size + 1)
        ).all()
        has_more = len(invoice_models) > page_size
        invoices = tuple(_invoice_view(invoice, ()) for invoice in invoice_models[:page_size])
        return invoices, has_more

    def read_invoice_duplicate_candidate_page(
        self,
        organization_id: UUID,
        invoice_id: UUID,
        page_size: int,
        cursor_id: UUID | None = None,
    ) -> (
        tuple[
            InvoiceDuplicateBasisStatus,
            tuple[InvoiceDuplicateCandidateReadView, ...],
            bool,
        ]
        | None
    ):
        """Read a source anchor and one bounded page of exact duplicate candidates."""

        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(invoice_id) is not UUID:
            raise ValueError("invoice_id must be an exact uuid.UUID")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be an integer between 1 and 100")
        if cursor_id is not None and type(cursor_id) is not UUID:
            raise ValueError("cursor_id must be an exact uuid.UUID")

        source = self._session.execute(
            select(
                Invoice.invoice_code,
                Invoice.invoice_number,
                Invoice.seller_tax_no,
                Invoice.status,
            ).where(
                Invoice.id == invoice_id,
                Invoice.organization_id == organization_id,
                Invoice.deleted_at.is_(None),
            )
        ).one_or_none()
        if source is None:
            return None
        if source.status == "voided":
            return "source_voided", (), False
        if None in (source.invoice_code, source.invoice_number, source.seller_tax_no):
            return "incomplete_identity", (), False

        statement = select(
            Invoice.id,
            Invoice.invoice_code,
            Invoice.invoice_number,
            Invoice.invoice_date,
            Invoice.seller_name,
            Invoice.total_amount,
            Invoice.currency,
            Invoice.confirmation_status,
            Invoice.duplicate_status,
            Invoice.status,
        ).where(
            Invoice.organization_id == organization_id,
            Invoice.id != invoice_id,
            Invoice.deleted_at.is_(None),
            Invoice.status != "voided",
            Invoice.invoice_code == source.invoice_code,
            Invoice.invoice_number == source.invoice_number,
            Invoice.seller_tax_no == source.seller_tax_no,
        )
        if cursor_id is not None:
            statement = statement.where(Invoice.id > cursor_id)
        rows = self._session.execute(
            statement.order_by(Invoice.id.asc()).limit(page_size + 1)
        ).all()
        has_more = len(rows) > page_size
        return (
            "ready",
            tuple(
                InvoiceDuplicateCandidateReadView(
                    id=row.id,
                    invoice_code=row.invoice_code,
                    invoice_number=row.invoice_number,
                    invoice_date=row.invoice_date,
                    seller_name=row.seller_name,
                    total_amount=_finite_decimal(
                        row.total_amount,
                        path="invoices.total_amount",
                    ),
                    currency=row.currency,
                    confirmation_status=row.confirmation_status,
                    duplicate_status=row.duplicate_status,
                    status=row.status,
                )
                for row in rows[:page_size]
            ),
            has_more,
        )

    def read_invoice_exact_duplicate_pair(
        self,
        organization_id: UUID,
        invoice_id: UUID,
        candidate_id: UUID,
    ) -> InvoiceExactDuplicatePairReadView | None:
        """Point-read two visible invoices that still share the exact raw identity."""

        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(invoice_id) is not UUID:
            raise ValueError("invoice_id must be an exact uuid.UUID")
        if type(candidate_id) is not UUID:
            raise ValueError("candidate_id must be an exact uuid.UUID")

        source = aliased(Invoice, name="source_invoice")
        candidate = aliased(Invoice, name="candidate_invoice")
        row = self._session.execute(
            select(
                source.id.label("source_id"),
                source.invoice_code.label("source_invoice_code"),
                source.invoice_number.label("source_invoice_number"),
                source.invoice_date.label("source_invoice_date"),
                source.seller_name.label("source_seller_name"),
                source.total_amount.label("source_total_amount"),
                source.currency.label("source_currency"),
                source.confirmation_status.label("source_confirmation_status"),
                source.duplicate_status.label("source_duplicate_status"),
                source.status.label("source_status"),
                source.seller_tax_no.label("exact_seller_tax_no"),
                candidate.id.label("candidate_id"),
                candidate.invoice_code.label("candidate_invoice_code"),
                candidate.invoice_number.label("candidate_invoice_number"),
                candidate.invoice_date.label("candidate_invoice_date"),
                candidate.seller_name.label("candidate_seller_name"),
                candidate.total_amount.label("candidate_total_amount"),
                candidate.currency.label("candidate_currency"),
                candidate.confirmation_status.label("candidate_confirmation_status"),
                candidate.duplicate_status.label("candidate_duplicate_status"),
                candidate.status.label("candidate_status"),
            )
            .select_from(source)
            .join(
                candidate,
                and_(
                    candidate.id == candidate_id,
                    candidate.organization_id == organization_id,
                    candidate.deleted_at.is_(None),
                    candidate.status != "voided",
                    candidate.invoice_code == source.invoice_code,
                    candidate.invoice_number == source.invoice_number,
                    candidate.seller_tax_no == source.seller_tax_no,
                ),
            )
            .where(
                source.id == invoice_id,
                source.id != candidate.id,
                source.organization_id == organization_id,
                source.deleted_at.is_(None),
                source.status != "voided",
                source.invoice_code.is_not(None),
                source.invoice_number.is_not(None),
                source.seller_tax_no.is_not(None),
            )
        ).one_or_none()
        if row is None:
            return None
        return InvoiceExactDuplicatePairReadView(
            source=InvoiceDuplicateCandidateReadView(
                id=row.source_id,
                invoice_code=row.source_invoice_code,
                invoice_number=row.source_invoice_number,
                invoice_date=row.source_invoice_date,
                seller_name=row.source_seller_name,
                total_amount=_finite_decimal(
                    row.source_total_amount,
                    path="invoices.total_amount",
                ),
                currency=row.source_currency,
                confirmation_status=row.source_confirmation_status,
                duplicate_status=row.source_duplicate_status,
                status=row.source_status,
            ),
            candidate=InvoiceDuplicateCandidateReadView(
                id=row.candidate_id,
                invoice_code=row.candidate_invoice_code,
                invoice_number=row.candidate_invoice_number,
                invoice_date=row.candidate_invoice_date,
                seller_name=row.candidate_seller_name,
                total_amount=_finite_decimal(
                    row.candidate_total_amount,
                    path="invoices.total_amount",
                ),
                currency=row.candidate_currency,
                confirmation_status=row.candidate_confirmation_status,
                duplicate_status=row.candidate_duplicate_status,
                status=row.candidate_status,
            ),
            invoice_code=row.source_invoice_code,
            invoice_number=row.source_invoice_number,
            seller_tax_no=row.exact_seller_tax_no,
        )

    def read_invoice_primary_contract(
        self,
        organization_id: UUID,
        invoice_id: UUID,
    ) -> InvoicePrimaryContractReadView | None:
        """Read the optional confirmed primary contract for one visible invoice."""

        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(invoice_id) is not UUID:
            raise ValueError("invoice_id must be an exact uuid.UUID")
        visible_invoice_id = self._session.scalar(
            select(Invoice.id).where(
                Invoice.id == invoice_id,
                Invoice.organization_id == organization_id,
                Invoice.deleted_at.is_(None),
            )
        )
        if visible_invoice_id is None:
            return None

        primary_contract = self._session.execute(
            select(Contract)
            .select_from(ContractInvoice)
            .join(Contract, ContractInvoice.contract_id == Contract.id)
            .join(Invoice, ContractInvoice.invoice_id == Invoice.id)
            .where(
                ContractInvoice.invoice_id == invoice_id,
                ContractInvoice.deleted_at.is_(None),
                ContractInvoice.status == "confirmed_primary",
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
                Invoice.organization_id == organization_id,
                Invoice.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        return InvoicePrimaryContractReadView(
            primary_contract=(
                _contract_view(primary_contract) if primary_contract is not None else None
            )
        )

    def read_contract_primary_invoice_page(
        self,
        organization_id: UUID,
        contract_id: UUID,
        page_size: int,
        cursor_id: UUID | None = None,
    ) -> tuple[tuple[InvoiceReadView, ...], bool] | None:
        """Read a bounded page of confirmed-primary invoices under a visible contract."""

        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(contract_id) is not UUID:
            raise ValueError("contract_id must be an exact uuid.UUID")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be an integer between 1 and 100")
        if cursor_id is not None and type(cursor_id) is not UUID:
            raise ValueError("cursor_id must be an exact uuid.UUID")

        visible_contract_id = self._session.scalar(
            select(Contract.id).where(
                Contract.id == contract_id,
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
            )
        )
        if visible_contract_id is None:
            return None

        statement = (
            select(Invoice)
            .select_from(ContractInvoice)
            .join(Contract, ContractInvoice.contract_id == Contract.id)
            .join(Invoice, ContractInvoice.invoice_id == Invoice.id)
            .where(
                ContractInvoice.contract_id == contract_id,
                ContractInvoice.status == "confirmed_primary",
                ContractInvoice.deleted_at.is_(None),
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
                Invoice.organization_id == organization_id,
                Invoice.deleted_at.is_(None),
            )
        )
        if cursor_id is not None:
            statement = statement.where(ContractInvoice.invoice_id > cursor_id)
        invoice_models = self._session.scalars(
            statement.order_by(ContractInvoice.invoice_id.asc()).limit(page_size + 1)
        ).all()
        has_more = len(invoice_models) > page_size
        return (
            tuple(_invoice_view(invoice, ()) for invoice in invoice_models[:page_size]),
            has_more,
        )

    def read_for_organization(
        self,
        organization_id: UUID,
        baseline_date: date,
    ) -> FinancialReadView:
        """读取一个组织内所有当前可见的财务根对象与子对象。"""

        if type(organization_id) is not UUID:
            raise ValueError("organization_id must be an exact uuid.UUID")
        if type(baseline_date) is not date:
            raise ValueError("baseline_date must be an exact datetime.date")

        contract_models = self._session.scalars(
            select(Contract).where(
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
            )
        ).all()
        agreement_models = self._session.scalars(
            select(SupplementaryAgreement)
            .join(Contract, SupplementaryAgreement.contract_id == Contract.id)
            .where(
                SupplementaryAgreement.organization_id == organization_id,
                SupplementaryAgreement.deleted_at.is_(None),
                SupplementaryAgreement.status == "confirmed",
                SupplementaryAgreement.confirmation_status == "confirmed",
                SupplementaryAgreement.effective_date <= baseline_date,
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
            )
        ).all()
        invoice_models = self._session.scalars(
            select(Invoice).where(
                Invoice.organization_id == organization_id,
                Invoice.deleted_at.is_(None),
            )
        ).all()
        item_models = self._session.scalars(
            select(InvoiceItem)
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(
                Invoice.organization_id == organization_id,
                Invoice.deleted_at.is_(None),
            )
        ).all()
        relation_models = self._session.scalars(
            select(ContractInvoice)
            .join(Contract, ContractInvoice.contract_id == Contract.id)
            .join(Invoice, ContractInvoice.invoice_id == Invoice.id)
            .where(
                ContractInvoice.deleted_at.is_(None),
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
                Invoice.organization_id == organization_id,
                Invoice.deleted_at.is_(None),
            )
        ).all()

        contracts = tuple(
            sorted(
                (_contract_view(contract) for contract in contract_models),
                key=lambda contract: (*_optional_text_key(contract.contract_no), contract.id.bytes),
            )
        )
        agreements = tuple(
            sorted(
                (_supplementary_agreement_view(agreement) for agreement in agreement_models),
                key=lambda agreement: (
                    agreement.effective_date,
                    *_optional_text_key(agreement.agreement_no),
                    agreement.id.bytes,
                ),
            )
        )

        item_views_by_invoice: dict[UUID, list[InvoiceItemReadView]] = {}
        for item_model in item_models:
            item_views_by_invoice.setdefault(item_model.invoice_id, []).append(
                _invoice_item_view(item_model)
            )
        for item_views in item_views_by_invoice.values():
            item_views.sort(key=lambda item: (item.line_no, item.id.bytes))

        invoices = tuple(
            sorted(
                (
                    _invoice_view(
                        invoice,
                        tuple(item_views_by_invoice.get(invoice.id, ())),
                    )
                    for invoice in invoice_models
                ),
                key=lambda invoice: (
                    invoice.invoice_date is None,
                    invoice.invoice_date or date.max,
                    *_optional_text_key(invoice.invoice_code),
                    *_optional_text_key(invoice.invoice_number),
                    invoice.id.bytes,
                ),
            )
        )
        relations = tuple(
            sorted(
                (_contract_invoice_view(relation) for relation in relation_models),
                key=lambda relation: (
                    relation.invoice_id.bytes,
                    relation.contract_id.bytes,
                    relation.id.bytes,
                ),
            )
        )

        return FinancialReadView(
            organization_id=organization_id,
            baseline_date=baseline_date,
            contracts=contracts,
            supplementary_agreements=agreements,
            invoices=invoices,
            contract_invoices=relations,
        )


__all__ = [
    "ContractInvoiceReadView",
    "ContractFieldReadView",
    "ContractReadView",
    "EffectiveContractReadView",
    "FinancialReadIntegrityError",
    "FinancialReadRepository",
    "FinancialReadView",
    "InvoiceDuplicateBasisStatus",
    "InvoiceDuplicateCandidateReadView",
    "InvoiceExactDuplicatePairReadView",
    "InvoiceItemReadView",
    "InvoicePrimaryContractReadView",
    "InvoiceReadView",
    "SupplementaryAgreementReadView",
    "SupplementaryChangeReadView",
]
