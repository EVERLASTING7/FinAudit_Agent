from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import cast
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from redis import Redis

from app.ai.contracts import ModelTarget
from app.ai.redis_runtime_control import (
    AiBreakerProfile,
    AiRateLimitProfile,
    AiRuntimeControlError,
    AiRuntimePermit,
    RedisAiRuntimeControl,
)
from app.ai.routing import P0RateLimitPool

pytestmark = pytest.mark.integration

_CONFIRMATION = "ALLOW_LOCAL_REDIS_RUNTIME_CONTROL_TEST"


def _local_redis_url() -> str:
    url = os.environ.get("FINAUDIT_TEST_REDIS_URL")
    confirmation = os.environ.get("FINAUDIT_TEST_REDIS_CONFIRMATION")
    if url is None and confirmation is None:
        pytest.skip("real local Redis runtime-control integration is explicitly opt-in")
    if url is None or confirmation != _CONFIRMATION:
        pytest.fail("local Redis runtime-control confirmation is invalid", pytrace=False)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "redis"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port is None
        or parsed.query
        or parsed.fragment
    ):
        pytest.fail("local Redis runtime-control profile is unsafe", pytrace=False)
    return url


def _limits(
    **overrides: AiRateLimitProfile,
) -> Mapping[P0RateLimitPool, AiRateLimitProfile]:
    values = {
        P0RateLimitPool.RAG: AiRateLimitProfile(4, 600, 10_000, 10),
        P0RateLimitPool.ASYNC_GENERATION: AiRateLimitProfile(4, 600, 10_000, 10),
        P0RateLimitPool.EMBEDDING: AiRateLimitProfile(4, 600, 10_000, 10),
    }
    values.update({P0RateLimitPool(name): value for name, value in overrides.items()})
    return values


@contextmanager
def _runtime(
    *,
    limits: Mapping[P0RateLimitPool, AiRateLimitProfile],
    breaker: AiBreakerProfile | None = None,
) -> Iterator[tuple[RedisAiRuntimeControl, Redis, str]]:
    client: Redis = Redis.from_url(
        _local_redis_url(),
        socket_connect_timeout=2,
        socket_timeout=2,
        retry_on_timeout=False,
    )
    namespace = f"finaudit:test:runtime:{uuid4().hex}"
    controller = RedisAiRuntimeControl(
        client,
        namespace=namespace,
        pool_limits=limits,
        breaker=breaker or AiBreakerProfile(5, 60, 30, 1),
    )
    try:
        assert client.ping() is True
        yield controller, client, namespace
    finally:
        keys = list(client.scan_iter(match=f"{{{namespace}}}:*", count=100))
        if keys:
            client.delete(*keys)
        controller.close()


@contextmanager
def _shared_runtimes(
    *,
    limits: Mapping[P0RateLimitPool, AiRateLimitProfile],
) -> Iterator[tuple[RedisAiRuntimeControl, RedisAiRuntimeControl]]:
    url = _local_redis_url()
    clients: tuple[Redis, Redis] = (
        Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, retry_on_timeout=False),
        Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, retry_on_timeout=False),
    )
    namespace = f"finaudit:test:runtime:{uuid4().hex}"
    controllers = (
        RedisAiRuntimeControl(
            clients[0],
            namespace=namespace,
            pool_limits=limits,
            breaker=AiBreakerProfile(5, 60, 30, 1),
        ),
        RedisAiRuntimeControl(
            clients[1],
            namespace=namespace,
            pool_limits=limits,
            breaker=AiBreakerProfile(5, 60, 30, 1),
        ),
    )
    try:
        assert all(client.ping() is True for client in clients)
        yield controllers
    finally:
        keys = list(clients[0].scan_iter(match=f"{{{namespace}}}:*", count=100))
        if keys:
            clients[0].delete(*keys)
        for controller in controllers:
            controller.close()


def _acquire(
    controller: RedisAiRuntimeControl,
    *,
    pool: P0RateLimitPool,
    target: ModelTarget | None = None,
    tokens: int = 1,
    lease_seconds: float = 10,
) -> AiRuntimePermit:
    return controller.acquire(
        pool=pool,
        target=target or ModelTarget("integration-adapter", "integration-model"),
        estimated_tokens=tokens,
        lease_seconds=lease_seconds,
    )


def test_redis_enforces_concurrency_request_and_token_buckets_atomically() -> None:
    limits = _limits(
        embedding=AiRateLimitProfile(1, 600, 10_000, 10),
        rag=AiRateLimitProfile(4, 1, 100, 1),
        async_generation=AiRateLimitProfile(4, 600, 10, 10),
    )
    with _runtime(limits=limits) as (controller, _, _):
        concurrency = _acquire(controller, pool=P0RateLimitPool.EMBEDDING)
        with pytest.raises(AiRuntimeControlError) as concurrency_error:
            _acquire(controller, pool=P0RateLimitPool.EMBEDDING)
        assert concurrency_error.value.code == "AI_CONCURRENCY_LIMITED"
        concurrency.finish("neutral")

        request = _acquire(controller, pool=P0RateLimitPool.RAG)
        request.finish("neutral")
        with pytest.raises(AiRuntimeControlError) as request_error:
            _acquire(controller, pool=P0RateLimitPool.RAG)
        assert request_error.value.code == "AI_RATE_LIMITED"

        token = _acquire(
            controller,
            pool=P0RateLimitPool.ASYNC_GENERATION,
            tokens=10,
        )
        token.finish("neutral")
        with pytest.raises(AiRuntimeControlError) as token_error:
            _acquire(controller, pool=P0RateLimitPool.ASYNC_GENERATION)
        assert token_error.value.code == "AI_RATE_LIMITED"


def test_two_independent_clients_share_the_same_concurrency_gate() -> None:
    limits = _limits(embedding=AiRateLimitProfile(1, 600, 10_000, 10))
    with _shared_runtimes(limits=limits) as (first, second):
        first_permit = _acquire(first, pool=P0RateLimitPool.EMBEDDING)
        with pytest.raises(AiRuntimeControlError) as second_error:
            _acquire(second, pool=P0RateLimitPool.EMBEDDING)
        assert second_error.value.code == "AI_CONCURRENCY_LIMITED"

        first_permit.finish("neutral")
        second_permit = _acquire(second, pool=P0RateLimitPool.EMBEDDING)
        second_permit.finish("success")


def test_redis_breaker_opens_allows_one_half_open_probe_and_recovers() -> None:
    target = ModelTarget("integration-adapter", "breaker-model")
    with _runtime(
        limits=_limits(),
        breaker=AiBreakerProfile(2, 10, 1, 1),
    ) as (controller, client, namespace):
        older_success = _acquire(
            controller,
            pool=P0RateLimitPool.EMBEDDING,
            target=target,
        )
        for _ in range(2):
            permit = _acquire(
                controller,
                pool=P0RateLimitPool.EMBEDDING,
                target=target,
            )
            permit.finish("transient_failure")

        with pytest.raises(AiRuntimeControlError) as open_error:
            _acquire(controller, pool=P0RateLimitPool.EMBEDDING, target=target)
        assert open_error.value.code == "AI_BREAKER_OPEN"

        older_success.finish("success")
        with pytest.raises(AiRuntimeControlError) as still_open_error:
            _acquire(controller, pool=P0RateLimitPool.EMBEDDING, target=target)
        assert still_open_error.value.code == "AI_BREAKER_OPEN"

        time.sleep(1.1)
        half_open = _acquire(
            controller,
            pool=P0RateLimitPool.EMBEDDING,
            target=target,
            lease_seconds=90,
        )
        target_hash = hashlib.sha256(
            f"{target.adapter_id}\0{target.model_id}".encode()
        ).hexdigest()[:24]
        open_key = f"{{{namespace}}}:target:{target_hash}:open_until"
        assert cast(int, client.pttl(open_key)) >= 140_000
        with pytest.raises(AiRuntimeControlError) as second_probe_error:
            _acquire(controller, pool=P0RateLimitPool.EMBEDDING, target=target)
        assert second_probe_error.value.code == "AI_BREAKER_OPEN"

        half_open.finish("success")
        recovered = _acquire(
            controller,
            pool=P0RateLimitPool.EMBEDDING,
            target=target,
        )
        recovered.finish("success")
