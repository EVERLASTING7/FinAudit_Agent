from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.core.errors import AppError
from app.core.responses import error_response
from app.core.tracing import get_trace_id

_VALIDATION_LOCATION_ROOTS = frozenset({"body", "cookie", "header", "path", "query"})
_MAX_VALIDATION_LOCATION_DEPTH = 16
_VALIDATION_ERROR_REASON = "invalid"


def _safe_validation_field(location: tuple[object, ...]) -> str | None:
    if not location or location[0] not in _VALIDATION_LOCATION_ROOTS:
        return None

    projected = [str(location[0])]
    for part in location[1 : _MAX_VALIDATION_LOCATION_DEPTH - 1]:
        projected.append(str(part) if type(part) is int and part >= 0 else "*")
    if len(location) >= _MAX_VALIDATION_LOCATION_DEPTH:
        projected.append("*")
    return ".".join(projected)


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    app_error = cast(AppError, exc)
    return error_response(
        status_code=app_error.status_code,
        code=app_error.code,
        message=app_error.message,
        details=app_error.details,
        trace_id=get_trace_id(request),
        data=app_error.data,
        headers=app_error.headers,
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    validation_error = cast(RequestValidationError, exc)
    details: list[dict[str, Any]] = []
    for error in validation_error.errors():
        field = _safe_validation_field(tuple(error["loc"]))
        details.append({"field": field, "reason": _VALIDATION_ERROR_REASON})

    return error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=details,
        trace_id=get_trace_id(request),
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    http_error = cast(HTTPException, exc)
    if http_error.status_code == 404:
        code = "RESOURCE_NOT_FOUND"
        message = "目标资源不存在或不可见"
    elif http_error.status_code == 405:
        code = "METHOD_NOT_ALLOWED"
        message = "请求方法不支持"
    else:
        code = "HTTP_ERROR"
        message = "请求无法处理"

    return error_response(
        status_code=http_error.status_code,
        code=code,
        message=message,
        details=[],
        trace_id=get_trace_id(request),
        headers=http_error.headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
