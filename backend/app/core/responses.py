from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from fastapi.responses import JSONResponse


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]],
    trace_id: str,
    headers: Mapping[str, str] | None = None,
    data: dict[str, Any] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {
        "code": code,
        "message": message,
        "details": details,
        "trace_id": trace_id,
        "timestamp": utc_timestamp(),
    }
    if data is not None:
        content["data"] = data
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers=headers,
    )
