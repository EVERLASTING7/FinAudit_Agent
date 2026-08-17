"""operation-log-read-v1 的严格 cursor 与投影用例。"""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime, timezone
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.operation_log_read import (
    OperationLogReadRepository,
    OperationLogReadView,
)
from app.schemas.operation_logs import OperationLogItemData, OperationLogListData

_UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def _invalid_cursor() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=[{"field": "query.cursor", "reason": "invalid"}],
    )


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise RuntimeError("operation log timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _encode_cursor(created_at: datetime, identity: UUID) -> str:
    payload = json.dumps(
        {"v": 1, "created_at": _utc_text(created_at), "id": str(identity)},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor(value: str) -> tuple[datetime, UUID]:
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
            result: dict[str, object] = {}
            for key, child in pairs:
                if key in result:
                    raise ValueError("duplicate cursor key")
                result[key] = child
            return result

        payload = json.loads(decoded.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
        if type(payload) is not dict or set(payload) != {"v", "created_at", "id"}:
            raise ValueError("invalid cursor object")
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError("invalid cursor version")
        raw_time = payload["created_at"]
        raw_id = payload["id"]
        if (
            type(raw_time) is not str
            or _UTC_TIMESTAMP_PATTERN.fullmatch(raw_time) is None
            or type(raw_id) is not str
        ):
            raise ValueError("invalid cursor fields")
        created_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        identity = UUID(raw_id)
        if str(identity) != raw_id or _encode_cursor(created_at, identity) != value:
            raise ValueError("noncanonical cursor")
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None
    return created_at, identity


def _project(row: OperationLogReadView) -> OperationLogItemData:
    return OperationLogItemData(
        id=row.id,
        actor_kind=cast(Literal["anonymous", "user", "system"], row.actor_kind),
        actor_id=row.actor_id,
        action_code=row.action_code,
        outcome=cast(Literal["succeeded", "denied", "failed"], row.outcome),
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        trace_id=row.trace_id,
        change_summary=row.change_summary,
        created_at=row.created_at,
    )


class OperationLogQueryService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_page(
        self,
        organization_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> OperationLogListData:
        cursor_created_at: datetime | None = None
        cursor_id: UUID | None = None
        if cursor is not None:
            cursor_created_at, cursor_id = _decode_cursor(cursor)
        with self._session_factory() as session:
            rows, has_more = OperationLogReadRepository(session).read_page(
                organization_id,
                page_size,
                cursor_created_at,
                cursor_id,
            )
        return OperationLogListData(
            items=tuple(_project(row) for row in rows),
            page_size=page_size,
            next_cursor=(_encode_cursor(rows[-1].created_at, rows[-1].id) if has_more else None),
        )


__all__ = ["OperationLogQueryService"]
