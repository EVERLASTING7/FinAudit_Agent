"""Organization-scoped invoice detail query use case."""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.financial_read import (
    FinancialReadRepository,
    InvoiceDuplicateCandidateReadView,
    InvoiceReadView,
)
from app.schemas.business_statuses import (
    ConfirmationStatus,
    InvoiceDuplicateStatus,
    InvoiceStatus,
)
from app.schemas.invoices import (
    InvoiceDetailData,
    InvoiceDuplicateCandidateListData,
    InvoiceExactDuplicatePairData,
    InvoiceExactIdentityData,
    InvoiceItemData,
    InvoiceListData,
    InvoiceListItemData,
)


def _decimal_string(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _project_invoice(invoice: InvoiceReadView) -> InvoiceDetailData:
    return InvoiceDetailData(
        id=invoice.id,
        invoice_code=invoice.invoice_code,
        invoice_number=invoice.invoice_number,
        invoice_type=invoice.invoice_type,
        is_red_invoice=invoice.is_red_invoice,
        invoice_date=invoice.invoice_date,
        buyer_name=invoice.buyer_name,
        buyer_tax_no=invoice.buyer_tax_no,
        seller_name=invoice.seller_name,
        seller_tax_no=invoice.seller_tax_no,
        amount_excluding_tax=_decimal_string(invoice.amount_excluding_tax),
        tax_amount=_decimal_string(invoice.tax_amount),
        total_amount=_decimal_string(invoice.total_amount),
        currency=invoice.currency,
        confirmation_status=ConfirmationStatus(invoice.confirmation_status),
        duplicate_status=InvoiceDuplicateStatus(invoice.duplicate_status),
        status=InvoiceStatus(invoice.status),
        row_version=str(invoice.row_version),
        items=tuple(
            InvoiceItemData(
                id=item.id,
                line_no=item.line_no,
                item_name=item.item_name,
                specification=item.specification,
                unit=item.unit,
                quantity=_decimal_string(item.quantity),
                unit_price=_decimal_string(item.unit_price),
                amount_excluding_tax=_decimal_string(item.amount_excluding_tax),
                tax_rate=_decimal_string(item.tax_rate),
                tax_amount=_decimal_string(item.tax_amount),
                total_amount=_decimal_string(item.total_amount),
                row_version=str(item.row_version),
            )
            for item in invoice.items
        ),
    )


def project_invoice_list_item(
    invoice: InvoiceReadView | InvoiceDuplicateCandidateReadView,
) -> InvoiceListItemData:
    return InvoiceListItemData(
        id=invoice.id,
        invoice_code=invoice.invoice_code,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        seller_name=invoice.seller_name,
        total_amount=_decimal_string(invoice.total_amount),
        currency=invoice.currency,
        confirmation_status=ConfirmationStatus(invoice.confirmation_status),
        duplicate_status=InvoiceDuplicateStatus(invoice.duplicate_status),
        status=InvoiceStatus(invoice.status),
    )


def _invalid_cursor() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=[{"field": "query.cursor", "reason": "invalid"}],
    )


def _decode_cursor(value: str) -> tuple[date | None, UUID]:
    if not value or len(value) > 256 or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise _invalid_cursor()
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
        if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
            raise ValueError("noncanonical base64url")
        raw = decoded.decode("utf-8")

        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            parsed: dict[str, object] = {}
            for key, child in pairs:
                if key in parsed:
                    raise ValueError("duplicate cursor key")
                parsed[key] = child
            return parsed

        payload = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
        if type(payload) is not dict or set(payload) != {"v", "invoice_date", "id"}:
            raise ValueError("invalid cursor object")
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError("unsupported cursor version")
        raw_date = payload["invoice_date"]
        if raw_date is None:
            invoice_date = None
        elif type(raw_date) is str:
            invoice_date = date.fromisoformat(raw_date)
            if invoice_date.isoformat() != raw_date:
                raise ValueError("noncanonical cursor date")
        else:
            raise ValueError("invalid cursor date")
        raw_id = payload["id"]
        if type(raw_id) is not str:
            raise ValueError("invalid cursor id")
        invoice_id = UUID(raw_id)
        if str(invoice_id) != raw_id:
            raise ValueError("noncanonical cursor id")
        if _encode_cursor_values(invoice_date, invoice_id) != value:
            raise ValueError("noncanonical cursor json")
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None
    return invoice_date, invoice_id


def _encode_cursor_values(invoice_date: date | None, invoice_id: UUID) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "invoice_date": invoice_date.isoformat() if invoice_date else None,
            "id": str(invoice_id),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _encode_cursor(invoice: InvoiceReadView) -> str:
    return _encode_cursor_values(invoice.invoice_date, invoice.id)


def _decode_duplicate_cursor(value: str) -> UUID:
    if not value or len(value) > 256 or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise _invalid_cursor()
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
        if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
            raise ValueError("noncanonical base64url")
        raw = decoded.decode("utf-8")

        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            parsed: dict[str, object] = {}
            for key, child in pairs:
                if key in parsed:
                    raise ValueError("duplicate cursor key")
                parsed[key] = child
            return parsed

        payload = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
        if type(payload) is not dict or set(payload) != {"v", "id"}:
            raise ValueError("invalid cursor object")
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError("unsupported cursor version")
        raw_id = payload["id"]
        if type(raw_id) is not str:
            raise ValueError("invalid cursor id")
        invoice_id = UUID(raw_id)
        if str(invoice_id) != raw_id:
            raise ValueError("noncanonical cursor id")
        if _encode_duplicate_cursor_values(invoice_id) != value:
            raise ValueError("noncanonical cursor json")
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None
    return invoice_id


def _encode_duplicate_cursor_values(invoice_id: UUID) -> str:
    payload = json.dumps(
        {"v": 1, "id": str(invoice_id)},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


class InvoiceQueryService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_detail(self, organization_id: UUID, invoice_id: UUID) -> InvoiceDetailData:
        with self._session_factory() as session:
            invoice = FinancialReadRepository(session).read_invoice(
                organization_id,
                invoice_id,
            )
        if invoice is None:
            raise AppError(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                message="目标资源不存在或不可见",
            )
        return _project_invoice(invoice)

    def list_page(
        self,
        organization_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> InvoiceListData:
        cursor_date: date | None = None
        cursor_id: UUID | None = None
        if cursor is not None:
            cursor_date, cursor_id = _decode_cursor(cursor)
        with self._session_factory() as session:
            invoices, has_more = FinancialReadRepository(session).read_invoice_page(
                organization_id,
                page_size,
                cursor_date,
                cursor_id,
            )
        return InvoiceListData(
            items=tuple(project_invoice_list_item(invoice) for invoice in invoices),
            page_size=page_size,
            next_cursor=_encode_cursor(invoices[-1]) if has_more else None,
        )

    def list_duplicate_candidates(
        self,
        organization_id: UUID,
        invoice_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> InvoiceDuplicateCandidateListData:
        cursor_id = _decode_duplicate_cursor(cursor) if cursor is not None else None
        with self._session_factory() as session:
            result = FinancialReadRepository(session).read_invoice_duplicate_candidate_page(
                organization_id,
                invoice_id,
                page_size,
                cursor_id,
            )
        if result is None:
            raise AppError(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                message="目标资源不存在或不可见",
            )
        basis_status, candidates, has_more = result
        return InvoiceDuplicateCandidateListData(
            basis_status=basis_status,
            items=tuple(project_invoice_list_item(candidate) for candidate in candidates),
            page_size=page_size,
            next_cursor=(_encode_duplicate_cursor_values(candidates[-1].id) if has_more else None),
        )

    def get_exact_duplicate_pair(
        self,
        organization_id: UUID,
        invoice_id: UUID,
        candidate_id: UUID,
    ) -> InvoiceExactDuplicatePairData:
        with self._session_factory() as session:
            pair = FinancialReadRepository(session).read_invoice_exact_duplicate_pair(
                organization_id,
                invoice_id,
                candidate_id,
            )
        if pair is None or invoice_id == candidate_id:
            raise AppError(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                message="目标资源不存在或不可见",
            )
        if pair.source.id != invoice_id or pair.candidate.id != candidate_id:
            raise ValueError("invalid exact duplicate pair repository projection")
        return InvoiceExactDuplicatePairData(
            source=project_invoice_list_item(pair.source),
            candidate=project_invoice_list_item(pair.candidate),
            exact_identity=InvoiceExactIdentityData(
                invoice_code=pair.invoice_code,
                invoice_number=pair.invoice_number,
                seller_tax_no=pair.seller_tax_no,
            ),
        )


__all__ = ["InvoiceQueryService", "project_invoice_list_item"]
