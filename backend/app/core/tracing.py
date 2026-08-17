import logging
import re
from contextvars import ContextVar, Token
from uuid import UUID, uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.responses import error_response

TRACE_ID_HEADER = "X-Trace-ID"
_TRACEPARENT_PATTERN = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$",
    re.IGNORECASE,
)
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
logger = logging.getLogger(__name__)


def new_trace_id(traceparent: str | None = None) -> str:
    if traceparent:
        match = _TRACEPARENT_PATTERN.fullmatch(traceparent.strip())
        if match and match.group(1) != "0" * 32 and match.group(2) != "0" * 16:
            return str(UUID(hex=match.group(1)))
    return str(uuid4())


def get_trace_id(request: Request | None = None) -> str:
    if request is not None:
        request_trace_id = getattr(request.state, "trace_id", None)
        if isinstance(request_trace_id, str):
            return request_trace_id
    return _trace_id.get() or str(uuid4())


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = new_trace_id(request.headers.get("traceparent"))
        request.state.trace_id = trace_id
        token: Token[str | None] = _trace_id.set(trace_id)
        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                logger.error(
                    "Unhandled request exception",
                    extra={"trace_id": trace_id, "exception_type": type(exc).__name__},
                )
                response = error_response(
                    status_code=500,
                    code="INTERNAL_ERROR",
                    message="服务内部错误，请使用 trace_id 联系管理员",
                    details=[],
                    trace_id=trace_id,
                )
            response.headers[TRACE_ID_HEADER] = trace_id
            return response
        finally:
            _trace_id.reset(token)
