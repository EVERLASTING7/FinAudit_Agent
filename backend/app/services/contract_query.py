"""Organization-scoped contract current-row query use cases."""

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
from app.repositories.financial_read import ContractReadView, FinancialReadRepository
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import (
    ContractDetailData,
    ContractListData,
    ContractListItemData,
    ContractStatus,
)


def _decimal_string(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _project_detail(contract: ContractReadView) -> ContractDetailData:
    return ContractDetailData(
        id=contract.id,
        contract_no=contract.contract_no,
        name=contract.name,
        party_a_name=contract.party_a_name,
        party_a_tax_no=contract.party_a_tax_no,
        party_b_name=contract.party_b_name,
        party_b_tax_no=contract.party_b_tax_no,
        amount=_decimal_string(contract.amount),
        currency=contract.currency,
        signed_date=contract.signed_date,
        effective_date=contract.effective_date,
        expiry_date=contract.expiry_date,
        payment_method=contract.payment_method,
        payment_terms=contract.payment_terms,
        confirmation_status=ConfirmationStatus(contract.confirmation_status),
        status=ContractStatus(contract.status),
        row_version=str(contract.row_version),
    )


def project_contract_list_item(contract: ContractReadView) -> ContractListItemData:
    return ContractListItemData(
        id=contract.id,
        contract_no=contract.contract_no,
        name=contract.name,
        party_b_name=contract.party_b_name,
        amount=_decimal_string(contract.amount),
        currency=contract.currency,
        effective_date=contract.effective_date,
        expiry_date=contract.expiry_date,
        confirmation_status=ConfirmationStatus(contract.confirmation_status),
        status=ContractStatus(contract.status),
    )


def _invalid_cursor() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=[{"field": "query.cursor", "reason": "invalid"}],
    )


def _encode_cursor_values(effective_date: date | None, contract_id: UUID) -> str:
    payload = json.dumps(
        {
            "effective_date": effective_date.isoformat() if effective_date else None,
            "id": str(contract_id),
            "v": 1,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


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

        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            parsed: dict[str, object] = {}
            for key, child in pairs:
                if key in parsed:
                    raise ValueError("duplicate cursor key")
                parsed[key] = child
            return parsed

        payload = json.loads(decoded.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
        if type(payload) is not dict or set(payload) != {"v", "effective_date", "id"}:
            raise ValueError("invalid cursor object")
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError("unsupported cursor version")
        raw_date = payload["effective_date"]
        if raw_date is None:
            effective_date = None
        elif type(raw_date) is str:
            effective_date = date.fromisoformat(raw_date)
            if effective_date.isoformat() != raw_date:
                raise ValueError("noncanonical cursor date")
        else:
            raise ValueError("invalid cursor date")
        raw_id = payload["id"]
        if type(raw_id) is not str:
            raise ValueError("invalid cursor id")
        contract_id = UUID(raw_id)
        if str(contract_id) != raw_id:
            raise ValueError("noncanonical cursor id")
        if _encode_cursor_values(effective_date, contract_id) != value:
            raise ValueError("noncanonical cursor json")
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None
    return effective_date, contract_id


class ContractQueryService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_detail(self, organization_id: UUID, contract_id: UUID) -> ContractDetailData:
        with self._session_factory() as session:
            contract = FinancialReadRepository(session).read_contract(
                organization_id,
                contract_id,
            )
        if contract is None:
            raise AppError(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                message="目标资源不存在或不可见",
            )
        return _project_detail(contract)

    def list_page(
        self,
        organization_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> ContractListData:
        cursor_date: date | None = None
        cursor_id: UUID | None = None
        if cursor is not None:
            cursor_date, cursor_id = _decode_cursor(cursor)
        with self._session_factory() as session:
            contracts, has_more = FinancialReadRepository(session).read_contract_page(
                organization_id,
                page_size,
                cursor_date,
                cursor_id,
            )
        return ContractListData(
            items=tuple(project_contract_list_item(contract) for contract in contracts),
            page_size=page_size,
            next_cursor=(
                _encode_cursor_values(contracts[-1].effective_date, contracts[-1].id)
                if has_more
                else None
            ),
        )


__all__ = ["ContractQueryService", "project_contract_list_item"]
