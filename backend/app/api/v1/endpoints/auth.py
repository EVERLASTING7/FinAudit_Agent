"""auth-mvp-v1 的五个公开 HTTP 端点。"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Cookie, Header, Request, Response

from app.api.dependencies.auth import (
    AuthServiceDependency,
    CurrentActorDependency,
)
from app.core.config import AppEnvironment, canonicalize_http_origin
from app.core.errors import AppError
from app.core.responses import utc_timestamp
from app.schemas.auth import (
    AuthSessionData,
    CurrentUserData,
    LoginRequest,
    PasswordChangeRequest,
)
from app.schemas.common import SuccessResponse
from app.services.auth import AuthSessionResult, PasswordChangeRequired

router = APIRouter(prefix="/auth", tags=["认证"])
REFRESH_COOKIE_NAME = "finaudit_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _validate_origin(request: Request) -> None:
    origin = request.headers.get("Origin")
    if origin is None:
        raise AppError(status_code=403, code="AUTH_ORIGIN_FORBIDDEN", message="请求来源无效")
    configured_origin = request.app.state.settings.auth_public_origin
    direct_origin = f"{request.url.scheme}://{request.url.netloc}"
    try:
        actual = canonicalize_http_origin(origin)
        expected = configured_origin or canonicalize_http_origin(direct_origin)
    except ValueError:
        raise AppError(
            status_code=403,
            code="AUTH_ORIGIN_FORBIDDEN",
            message="请求来源无效",
        ) from None
    if actual != expected:
        raise AppError(status_code=403, code="AUTH_ORIGIN_FORBIDDEN", message="请求来源无效")


def _refresh_cookie_secure(request: Request) -> bool:
    environment = request.app.state.settings.app_env
    configured_origin = request.app.state.settings.auth_public_origin
    public_url = urlsplit(configured_origin) if configured_origin is not None else request.url
    if environment is AppEnvironment.PROD or public_url.scheme == "https":
        return True
    hostname = public_url.hostname
    try:
        is_loopback = hostname == "localhost" or (
            hostname is not None and ipaddress.ip_address(hostname).is_loopback
        )
    except ValueError:
        is_loopback = False
    return not (environment is AppEnvironment.LOCAL and public_url.scheme == "http" and is_loopback)


def _set_refresh_cookie(response: Response, result: AuthSessionResult, request: Request) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=result.refresh.wire_value,
        max_age=result.refresh_max_age_seconds,
        httponly=True,
        secure=_refresh_cookie_secure(request),
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=_refresh_cookie_secure(request),
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )


def _session_response(
    request: Request,
    response: Response,
    result: AuthSessionResult,
) -> SuccessResponse[AuthSessionData]:
    _set_refresh_cookie(response, result, request)
    response.headers.update(_NO_STORE_HEADERS)
    timestamp = utc_timestamp()
    return SuccessResponse[AuthSessionData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=timestamp,
    )


@router.post("/login", response_model=SuccessResponse[AuthSessionData])
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> SuccessResponse[AuthSessionData]:
    _validate_origin(request)
    result = service.login(
        payload.username,
        payload.password,
        remember_me=payload.remember_me,
        trace_id=UUID(request.state.trace_id),
    )
    if isinstance(result, PasswordChangeRequired):
        raise AppError(
            status_code=403,
            code="AUTH_PASSWORD_CHANGE_REQUIRED",
            message="首次登录必须修改密码",
            data={"password_change_token": result.token, "expires_in": 300},
            headers=_NO_STORE_HEADERS,
        )
    return _session_response(request, response, result)


@router.post("/refresh", response_model=SuccessResponse[AuthSessionData])
def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDependency,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> SuccessResponse[AuthSessionData]:
    _validate_origin(request)
    if refresh_token is None:
        raise AppError(
            status_code=401,
            code="AUTH_REFRESH_EXPIRED",
            message="会话已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _session_response(request, response, service.refresh(refresh_token))


@router.post("/logout", status_code=204, response_model=None)
def logout(
    request: Request,
    response: Response,
    service: AuthServiceDependency,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> None:
    _validate_origin(request)
    service.logout(refresh_token, trace_id=UUID(request.state.trace_id))
    _clear_refresh_cookie(response, request)


@router.get("/me", response_model=SuccessResponse[CurrentUserData])
def me(
    request: Request,
    actor: CurrentActorDependency,
) -> SuccessResponse[CurrentUserData]:
    del actor
    timestamp = utc_timestamp()
    return SuccessResponse[CurrentUserData](
        data=request.state.current_user,
        trace_id=request.state.trace_id,
        timestamp=timestamp,
    )


@router.post("/password/change", status_code=204, response_model=None)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    service: AuthServiceDependency,
    authorization: str | None = Header(default=None),
) -> None:
    _validate_origin(request)
    if authorization is None or not authorization.startswith("Bearer "):
        raise AppError(status_code=401, code="AUTH_TOKEN_REVOKED", message="受限认证已失效")
    token = authorization[7:]
    if not token or " " in token:
        raise AppError(status_code=401, code="AUTH_TOKEN_REVOKED", message="受限认证已失效")
    service.change_password(token, payload.new_password)
    _clear_refresh_cookie(response, request)


__all__ = ["router"]
