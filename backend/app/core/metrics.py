"""低基数、无业务标识的进程内 Prometheus 指标。"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from starlette.types import Message, Receive, Scope, Send

_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_KNOWN_METHODS = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"})
MetricKey = tuple[str, str, str]
AsgiApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def _request_group(path: str) -> str:
    if path == "/health":
        return "health"
    if path == "/health/dependencies":
        return "dependencies"
    if path == "/metrics":
        return "metrics"
    if path == "/api/v1" or path.startswith("/api/v1/"):
        return "api_v1"
    return "other"


def _method(value: object) -> str:
    candidate = value if type(value) is str else ""
    return candidate if candidate in _KNOWN_METHODS else "OTHER"


def _status_class(status_code: int) -> str:
    return f"{status_code // 100}xx" if 100 <= status_code <= 599 else "other"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _number(value: float) -> str:
    if math.isinf(value):
        return "+Inf"
    return format(value, ".9g")


@dataclass(frozen=True, slots=True)
class HttpMetricSnapshot:
    in_flight: int
    requests: tuple[tuple[MetricKey, int, float, tuple[int, ...]], ...]
    uptime_seconds: float


class MetricsRegistry:
    """线程安全的有界内存指标；标签集合只能来自本模块固定映射。"""

    def __init__(
        self,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = monotonic_clock
        self._started_at = monotonic_clock()
        self._lock = threading.Lock()
        self._in_flight = 0
        self._counts: defaultdict[MetricKey, int] = defaultdict(int)
        self._duration_sums: defaultdict[MetricKey, float] = defaultdict(float)
        self._bucket_counts: dict[MetricKey, list[int]] = {}

    def request_started(self) -> None:
        with self._lock:
            self._in_flight += 1

    def request_finished(
        self,
        *,
        method: object,
        path: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        key = (_method(method), _request_group(path), _status_class(status_code))
        bounded_duration = max(0.0, duration_seconds)
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._counts[key] += 1
            self._duration_sums[key] += bounded_duration
            buckets = self._bucket_counts.setdefault(key, [0] * len(_BUCKETS))
            for index, upper_bound in enumerate(_BUCKETS):
                if bounded_duration <= upper_bound:
                    buckets[index] += 1

    def snapshot(self) -> HttpMetricSnapshot:
        with self._lock:
            rows = tuple(
                (
                    key,
                    count,
                    self._duration_sums[key],
                    tuple(self._bucket_counts[key]),
                )
                for key, count in sorted(self._counts.items())
            )
            in_flight = self._in_flight
        return HttpMetricSnapshot(
            in_flight=in_flight,
            requests=rows,
            uptime_seconds=max(0.0, self._clock() - self._started_at),
        )

    def render_prometheus(self, *, service: str, version: str) -> bytes:
        snapshot = self.snapshot()
        lines = [
            "# HELP finaudit_build_info Static backend build information.",
            "# TYPE finaudit_build_info gauge",
            'finaudit_build_info{service="'
            f'{_escape_label(service)}",version="{_escape_label(version)}"'
            "} 1",
            "# HELP finaudit_process_uptime_seconds Backend process uptime.",
            "# TYPE finaudit_process_uptime_seconds gauge",
            f"finaudit_process_uptime_seconds {_number(snapshot.uptime_seconds)}",
            "# HELP finaudit_http_requests_in_flight Requests currently being handled.",
            "# TYPE finaudit_http_requests_in_flight gauge",
            f"finaudit_http_requests_in_flight {snapshot.in_flight}",
            "# HELP finaudit_http_requests_total Completed HTTP requests.",
            "# TYPE finaudit_http_requests_total counter",
        ]
        for key, count, _duration_sum, _buckets in snapshot.requests:
            method, request_group, status_class = key
            labels = (
                f'method="{method}",request_group="{request_group}",status_class="{status_class}"'
            )
            lines.append(f"finaudit_http_requests_total{{{labels}}} {count}")
        lines.extend(
            (
                "# HELP finaudit_http_request_duration_seconds HTTP request duration.",
                "# TYPE finaudit_http_request_duration_seconds histogram",
            )
        )
        for key, count, duration_sum, bucket_counts in snapshot.requests:
            method, request_group, status_class = key
            labels = (
                f'method="{method}",request_group="{request_group}",status_class="{status_class}"'
            )
            for upper_bound, bucket_count in zip(_BUCKETS, bucket_counts, strict=True):
                lines.append(
                    "finaudit_http_request_duration_seconds_bucket"
                    f'{{{labels},le="{_number(upper_bound)}"}} {bucket_count}'
                )
            lines.append(
                f'finaudit_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {count}'
            )
            lines.append(
                f"finaudit_http_request_duration_seconds_sum{{{labels}}} {_number(duration_sum)}"
            )
            lines.append(f"finaudit_http_request_duration_seconds_count{{{labels}}} {count}")
        lines.append("# EOF")
        return ("\n".join(lines) + "\n").encode("utf-8")


class HttpMetricsMiddleware:
    def __init__(self, app: AsgiApp, *, registry: MetricsRegistry) -> None:
        self._app = app
        self._registry = registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        started_at = time.perf_counter()
        status_code = 500
        self._registry.request_started()

        async def observe_start(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, observe_start)
        finally:
            path = scope.get("path")
            self._registry.request_finished(
                method=scope.get("method"),
                path=path if type(path) is str else "",
                status_code=status_code,
                duration_seconds=time.perf_counter() - started_at,
            )


__all__ = ["HttpMetricSnapshot", "HttpMetricsMiddleware", "MetricsRegistry"]
