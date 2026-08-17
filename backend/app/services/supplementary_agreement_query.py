"""Organization-scoped supplementary-agreement raw header list query."""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.financial_read import (
    FinancialReadRepository,
    SupplementaryAgreementReadView,
)
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import (
    SupplementaryAgreementHeaderData,
    SupplementaryAgreementHeaderListData,
    SupplementaryAgreementStatus,
)


def _invalid_cursor() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=[{"field": "query.cursor", "reason": "invalid"}],
    )


def _encode_cursor_values(effective_date: date, agreement_id: UUID) -> str:
    payload = json.dumps(
        {"effective_date": effective_date.isoformat(), "id": str(agreement_id), "v": 1},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor(value: str) -> tuple[date, UUID]:
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
        raw_id = payload["id"]
        if type(raw_date) is not str or type(raw_id) is not str:
            raise ValueError("invalid cursor fields")
        effective_date = date.fromisoformat(raw_date)
        agreement_id = UUID(raw_id)
        if effective_date.isoformat() != raw_date or str(agreement_id) != raw_id:
            raise ValueError("noncanonical cursor fields")
        if _encode_cursor_values(effective_date, agreement_id) != value:
            raise ValueError("noncanonical cursor json")
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None
    return effective_date, agreement_id


def _project_header(
    agreement: SupplementaryAgreementReadView,
) -> SupplementaryAgreementHeaderData:
    return SupplementaryAgreementHeaderData(
        id=agreement.id,
        agreement_no=agreement.agreement_no,
        name=agreement.name,
        signed_date=agreement.signed_date,
        effective_date=agreement.effective_date,
        status=SupplementaryAgreementStatus(agreement.status),
        confirmation_status=ConfirmationStatus(agreement.confirmation_status),
    )


class SupplementaryAgreementQueryService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_headers(
        self,
        organization_id: UUID,
        contract_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> SupplementaryAgreementHeaderListData:
        cursor_date: date | None = None
        cursor_id: UUID | None = None
        if cursor is not None:
            cursor_date, cursor_id = _decode_cursor(cursor)
        with self._session_factory() as session:
            result = FinancialReadRepository(session).read_supplementary_agreement_header_page(
                organization_id,
                contract_id,
                page_size,
                cursor_date,
                cursor_id,
            )
        if result is None:
            raise AppError(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                message="目标资源不存在或不可见",
            )
        agreements, has_more = result
        return SupplementaryAgreementHeaderListData(
            items=tuple(_project_header(agreement) for agreement in agreements),
            page_size=page_size,
            next_cursor=(
                _encode_cursor_values(agreements[-1].effective_date, agreements[-1].id)
                if has_more
                else None
            ),
        )


__all__ = ["SupplementaryAgreementQueryService"]
