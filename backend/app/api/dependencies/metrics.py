from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, Request

from app.api.dependencies.settings import SettingsDependency
from app.core.errors import AppError
from app.core.metrics import MetricsRegistry


def get_metrics_registry(request: Request) -> MetricsRegistry:
    registry = getattr(request.app.state, "metrics_registry", None)
    if not isinstance(registry, MetricsRegistry):
        raise RuntimeError("metrics registry is not configured")
    return registry


MetricsRegistryDependency = Annotated[MetricsRegistry, Depends(get_metrics_registry)]


def require_metrics_token(
    settings: SettingsDependency,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> None:
    supplied = ""
    if authorization is not None and len(authorization) <= 4096:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].casefold() == "bearer" and parts[1] == parts[1].strip():
            supplied = parts[1]
    expected = settings.metrics_internal_token.get_secret_value()
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise AppError(
            status_code=401,
            code="METRICS_AUTH_REQUIRED",
            message="内部指标凭据无效",
            headers={"WWW-Authenticate": 'Bearer realm="metrics"'},
        )


MetricsTokenDependency = Annotated[None, Depends(require_metrics_token)]


__all__ = [
    "MetricsRegistryDependency",
    "MetricsTokenDependency",
    "get_metrics_registry",
    "require_metrics_token",
]
