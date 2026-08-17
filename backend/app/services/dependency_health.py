"""有界、脱敏的 Backend 依赖就绪探针。"""

from __future__ import annotations

import socket
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx
from minio import Minio
from minio.error import S3Error
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from urllib3 import PoolManager, Retry, Timeout

from app.adapters.qdrant_vector import QdrantVectorAdapter
from app.core.config import Settings, parse_database_url
from app.schemas.health import DependencyCheckData, DependencyName
from app.workers.bootstrap import create_celery_app

DependencyAggregateStatus = Literal["ok", "unavailable"]
Probe = Callable[[], bool]

_DEPENDENCY_ORDER: tuple[DependencyName, ...] = (
    "postgresql",
    "redis",
    "minio",
    "qdrant",
    "worker",
    "scanner",
    "ai_provider",
)
_BASE_REQUIRED_DEPENDENCIES = frozenset({"postgresql", "redis", "minio", "qdrant", "worker"})
_CONNECT_TIMEOUT_SECONDS = 3
_READ_TIMEOUT_SECONDS = 3
_WORKER_PING_TIMEOUT_SECONDS = 2


@dataclass(frozen=True, slots=True)
class DependencyHealthSnapshot:
    status: DependencyAggregateStatus
    dependencies: tuple[DependencyCheckData, ...]


class DependencyHealthService:
    """只返回稳定状态；底层地址、异常和耗时均不得进入结果。"""

    def __init__(
        self,
        settings: Settings,
        *,
        probes: Mapping[DependencyName, Probe] | None = None,
    ) -> None:
        active_settings = Settings.model_validate(settings)
        self._required = set(_BASE_REQUIRED_DEPENDENCIES)
        if active_settings.scanner_provider == "clamav_instream":
            self._required.add("scanner")
        if active_settings.ai_provider_calls_enabled:
            self._required.add("ai_provider")
        self._close_callbacks: list[Callable[[], object]] = []
        if probes is not None:
            if set(probes) != self._required:
                raise ValueError("dependency probe set does not match the active profile")
            self._probes = dict(probes)
            return
        self._probes = self._build_runtime_probes(active_settings)

    def close(self) -> None:
        for close in reversed(self._close_callbacks):
            try:
                close()
            except Exception:
                pass

    def check(self) -> DependencyHealthSnapshot:
        statuses: dict[DependencyName, bool] = {}
        with ThreadPoolExecutor(max_workers=len(self._probes)) as executor:
            futures = {name: executor.submit(probe) for name, probe in self._probes.items()}
            for name, future in futures.items():
                try:
                    statuses[name] = future.result() is True
                except Exception:
                    statuses[name] = False

        dependencies = tuple(
            DependencyCheckData(
                name=name,
                required=name in self._required,
                status=("ok" if statuses.get(name) else "unavailable")
                if name in self._required
                else "disabled",
            )
            for name in _DEPENDENCY_ORDER
        )
        aggregate: DependencyAggregateStatus = (
            "ok"
            if all(check.status == "ok" for check in dependencies if check.required)
            else "unavailable"
        )
        return DependencyHealthSnapshot(status=aggregate, dependencies=dependencies)

    def _build_runtime_probes(self, settings: Settings) -> dict[DependencyName, Probe]:
        engine = self._create_health_engine(settings)
        self._close_callbacks.append(engine.dispose)

        redis_client = Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=_READ_TIMEOUT_SECONDS,
            retry_on_timeout=False,
        )
        self._close_callbacks.append(redis_client.close)

        parsed_minio = urlsplit(settings.minio_endpoint)
        minio_http = PoolManager(
            timeout=Timeout(
                connect=_CONNECT_TIMEOUT_SECONDS,
                read=_READ_TIMEOUT_SECONDS,
            ),
            retries=Retry(total=0),
            cert_reqs="CERT_REQUIRED",
        )
        self._close_callbacks.append(minio_http.clear)
        minio_client = Minio(
            parsed_minio.netloc,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
            http_client=minio_http,
        )
        qdrant_client = httpx.Client(
            timeout=httpx.Timeout(
                _READ_TIMEOUT_SECONDS,
                connect=_CONNECT_TIMEOUT_SECONDS,
            ),
            follow_redirects=False,
            trust_env=False,
        )
        self._close_callbacks.append(qdrant_client.close)
        qdrant = QdrantVectorAdapter(
            settings,
            client=qdrant_client,
        )

        celery = create_celery_app(settings)
        self._close_callbacks.append(celery.close)

        def postgresql_probe() -> bool:
            with engine.connect() as connection:
                return cast(int, connection.execute(text("SELECT 1")).scalar_one()) == 1

        def redis_probe() -> bool:
            return cast(bool, redis_client.ping())

        def minio_probe() -> bool:
            try:
                minio_client.stat_object(
                    settings.minio_bucket_reports,
                    "organizations/00000000000000000000000000000000/health/dependency-probe-v1",
                )
            except S3Error as error:
                return error.code in {"NoSuchKey", "NoSuchObject"}
            return True

        def qdrant_probe() -> bool:
            qdrant.verify_collection()
            return True

        def worker_probe() -> bool:
            replies = celery.control.inspect(timeout=_WORKER_PING_TIMEOUT_SECONDS).ping()
            return bool(replies) and any(
                isinstance(value, dict) and value.get("ok") == "pong" for value in replies.values()
            )

        probes: dict[DependencyName, Probe] = {
            "postgresql": postgresql_probe,
            "redis": redis_probe,
            "minio": minio_probe,
            "qdrant": qdrant_probe,
            "worker": worker_probe,
        }
        if settings.scanner_provider == "clamav_instream":
            assert settings.scanner_host is not None

            def scanner_probe() -> bool:
                with socket.create_connection(
                    (settings.scanner_host, settings.scanner_port),
                    timeout=settings.scanner_connect_timeout_seconds,
                ) as connection:
                    connection.settimeout(min(settings.scanner_read_timeout_seconds, 3))
                    connection.sendall(b"zPING\0")
                    return connection.recv(16).rstrip(b"\0\r\n") == b"PONG"

            probes["scanner"] = scanner_probe
        if settings.ai_provider_calls_enabled:
            probes["ai_provider"] = lambda: False
        return probes

    @staticmethod
    def _create_health_engine(settings: Settings) -> Engine:
        return create_engine(
            parse_database_url(settings.database_url.get_secret_value()),
            connect_args={
                "connect_timeout": _CONNECT_TIMEOUT_SECONDS,
                "client_encoding": "UTF8",
                "options": "-c timezone=UTC",
            },
            hide_parameters=True,
            max_overflow=0,
            pool_pre_ping=True,
            pool_size=1,
            pool_timeout=_CONNECT_TIMEOUT_SECONDS,
        )


__all__ = ["DependencyHealthService", "DependencyHealthSnapshot"]
