"""FastAPI Auth Service、Bearer Actor 与 permission 依赖。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Annotated
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from fastapi import Depends, Request

from app.core.errors import AppError
from app.core.permissions import PermissionCode
from app.services.auth import AuthenticatedActor, AuthKeyring, AuthService

_KID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def get_auth_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if not isinstance(service, AuthService):
        raise AppError(
            status_code=503,
            code="AUTH_NOT_CONFIGURED",
            message="认证服务尚未配置",
        )
    return service


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme != "Bearer" or not token or " " in token:
        raise AppError(
            status_code=401,
            code="AUTH_ACCESS_EXPIRED",
            message="认证已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def get_current_actor(
    request: Request,
    service: AuthServiceDependency,
) -> AuthenticatedActor:
    actor, current_user = service.authenticate(_bearer_token(request))
    request.state.current_user = current_user
    return actor


CurrentActorDependency = Annotated[AuthenticatedActor, Depends(get_current_actor)]


def require_permission(
    permission: PermissionCode,
) -> Callable[..., AuthenticatedActor]:
    def dependency(
        request: Request,
        actor: CurrentActorDependency,
        service: AuthServiceDependency,
    ) -> AuthenticatedActor:
        if permission not in actor.permissions:
            service.record_authorization_denied(
                actor,
                permission,
                UUID(request.state.trace_id),
            )
            actor.require(permission)
        return actor

    return dependency


def require_any_permission(
    permissions: tuple[PermissionCode, ...],
) -> Callable[..., AuthenticatedActor]:
    if not permissions:
        raise ValueError("permissions cannot be empty")

    def dependency(
        request: Request,
        actor: CurrentActorDependency,
        service: AuthServiceDependency,
    ) -> AuthenticatedActor:
        if not set(permissions).intersection(actor.permissions):
            service.record_authorization_denied(
                actor,
                permissions[0],
                UUID(request.state.trace_id),
            )
            actor.require(permissions[0])
        return actor

    return dependency


def load_auth_keyring(
    active_kid: str,
    private_key_path: str,
    public_keyring_path: str,
) -> AuthKeyring:
    """从受控本地挂载加载 Ed25519 signer 与 verify-only keyring。"""

    private_raw = Path(private_key_path).read_bytes()
    private_key = serialization.load_pem_private_key(private_raw, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Auth signing key must be Ed25519")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        parsed: dict[str, object] = {}
        for key, value in pairs:
            if key in parsed:
                raise ValueError("Auth public keyring contains a duplicate kid")
            parsed[key] = value
        return parsed

    try:
        public_values = json.loads(
            Path(public_keyring_path).read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Auth public keyring is not valid JSON") from exc
    if type(public_values) is not dict or not public_values:
        raise ValueError("Auth public keyring must be a non-empty object")
    public_keys: dict[str, Ed25519PublicKey] = {}
    for kid, pem in public_values.items():
        if type(kid) is not str or _KID_PATTERN.fullmatch(kid) is None or type(pem) is not str:
            raise ValueError("Auth public keyring contains an invalid entry")
        loaded = serialization.load_pem_public_key(pem.encode("ascii"))
        if not isinstance(loaded, Ed25519PublicKey):
            raise ValueError("Auth verification key must be Ed25519")
        public_keys[kid] = loaded
    if active_kid not in public_keys:
        raise ValueError("Auth active kid is absent from the public keyring")
    signer_public = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    verifier_public = public_keys[active_kid].public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    if signer_public != verifier_public:
        raise ValueError("Auth active signer and verifier do not match")
    return AuthKeyring(
        active_kid=active_kid,
        private_key=private_key,
        public_keys=public_keys,
    )


__all__ = [
    "AuthServiceDependency",
    "CurrentActorDependency",
    "get_auth_service",
    "get_current_actor",
    "load_auth_keyring",
    "require_any_permission",
    "require_permission",
]
