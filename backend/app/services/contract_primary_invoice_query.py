"""Organization-scoped contract confirmed-primary invoice list query."""

from __future__ import annotations

import base64
import binascii
import json
import re
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.financial_read import FinancialReadRepository
from app.schemas.invoices import ContractPrimaryInvoiceListData
from app.services.invoice_query import project_invoice_list_item


def _invalid_cursor() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=[{"field": "query.cursor", "reason": "invalid"}],
    )


def _encode_cursor_values(invoice_id: UUID) -> str:
    payload = json.dumps(
        {"id": str(invoice_id), "v": 1},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor(value: str) -> UUID:
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

        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            parsed: dict[str, object] = {}
            for key, child in pairs:
                if key in parsed:
                    raise ValueError("duplicate cursor key")
                parsed[key] = child
            return parsed

        payload = json.loads(decoded.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
        if type(payload) is not dict or set(payload) != {"v", "id"}:
            raise ValueError("invalid cursor object")
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError("unsupported cursor version")
        raw_id = payload["id"]
        if type(raw_id) is not str:
            raise ValueError("invalid cursor id")
        invoice_id = UUID(raw_id)
        if str(invoice_id) != raw_id or _encode_cursor_values(invoice_id) != value:
            raise ValueError("noncanonical cursor")
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None
    return invoice_id


class ContractPrimaryInvoiceQueryService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_page(
        self,
        organization_id: UUID,
        contract_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> ContractPrimaryInvoiceListData:
        cursor_id = _decode_cursor(cursor) if cursor is not None else None
        with self._session_factory() as session:
            result = FinancialReadRepository(session).read_contract_primary_invoice_page(
                organization_id,
                contract_id,
                page_size,
                cursor_id,
            )
        if result is None:
            raise AppError(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                message="目标资源不存在或不可见",
            )
        invoices, has_more = result
        return ContractPrimaryInvoiceListData(
            items=tuple(project_invoice_list_item(invoice) for invoice in invoices),
            page_size=page_size,
            next_cursor=_encode_cursor_values(invoices[-1].id) if has_more else None,
        )


__all__ = ["ContractPrimaryInvoiceQueryService"]
