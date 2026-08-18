from __future__ import annotations

from collections.abc import Mapping

import pytest
from redis.exceptions import ConnectionError

from app.ai.contracts import ModelTarget
from app.ai.redis_runtime_control import (
    AiBreakerProfile,
    AiRateLimitProfile,
    AiRuntimeControlError,
    RedisAiRuntimeControl,
)
from app.ai.routing import P0RateLimitPool


class _ScriptClient:
    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, int, tuple[object, ...]]] = []
        self.closed = False

    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object:
        self.calls.append((script, numkeys, keys_and_args))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self) -> None:
        self.closed = True


def _limits(
    *,
    embedding: AiRateLimitProfile | None = None,
) -> Mapping[P0RateLimitPool, AiRateLimitProfile]:
    return {
        P0RateLimitPool.RAG: AiRateLimitProfile(2, 12, 100_000, 2),
        P0RateLimitPool.ASYNC_GENERATION: AiRateLimitProfile(4, 30, 250_000, 4),
        P0RateLimitPool.EMBEDDING: embedding or AiRateLimitProfile(2, 30, 500_000, 2),
    }


def _controller(client: _ScriptClient) -> RedisAiRuntimeControl:
    return RedisAiRuntimeControl(
        client,
        namespace="finaudit:test:runtime",
        pool_limits=_limits(),
        breaker=AiBreakerProfile(5, 60, 30, 1),
    )


def test_acquire_hashes_target_and_permit_can_finish_only_once() -> None:
    client = _ScriptClient([1, 0, 0], 1)
    controller = _controller(client)
    target = ModelTarget("private-adapter", "private-model")

    permit = controller.acquire(
        pool=P0RateLimitPool.EMBEDDING,
        target=target,
        estimated_tokens=20,
        lease_seconds=30,
    )
    assert permit.breaker_state == "closed"
    permit.finish("success")

    acquire_args = client.calls[0][2]
    redis_keys = acquire_args[: client.calls[0][1]]
    assert redis_keys
    assert all("private-adapter" not in str(key) for key in redis_keys)
    assert all("private-model" not in str(key) for key in redis_keys)
    assert all(str(key).startswith("{finaudit:test:runtime}") for key in redis_keys)
    assert client.calls[1][1] == 4
    with pytest.raises(AiRuntimeControlError, match="AI_RUNTIME_CONTROL_PERMIT_ALREADY_FINISHED"):
        permit.finish("success")


@pytest.mark.parametrize(
    ("result", "expected_code", "expected_retry"),
    [
        ([0, b"breaker_open", 1_001], "AI_BREAKER_OPEN", 2),
        ([0, b"concurrency", 1], "AI_CONCURRENCY_LIMITED", 1),
        ([0, b"request_rate", 60_000], "AI_RATE_LIMITED", 60),
        ([0, b"token_rate", 1_500], "AI_RATE_LIMITED", 2),
    ],
)
def test_acquire_maps_redis_denials_to_safe_errors(
    result: object,
    expected_code: str,
    expected_retry: int,
) -> None:
    controller = _controller(_ScriptClient(result))

    with pytest.raises(AiRuntimeControlError) as exc_info:
        controller.acquire(
            pool=P0RateLimitPool.RAG,
            target=ModelTarget("adapter", "model"),
            estimated_tokens=10,
            lease_seconds=10,
        )

    assert exc_info.value.code == expected_code
    assert exc_info.value.retry_after_seconds == expected_retry
    assert "adapter" not in repr(exc_info.value)


@pytest.mark.parametrize(
    "result",
    [ConnectionError("sensitive redis endpoint"), object(), [1, 0], [0, b"unknown", 1]],
)
def test_redis_failures_and_invalid_results_fail_closed_without_details(result: object) -> None:
    controller = _controller(_ScriptClient(result))

    with pytest.raises(AiRuntimeControlError) as exc_info:
        controller.acquire(
            pool=P0RateLimitPool.RAG,
            target=ModelTarget("adapter", "model"),
            estimated_tokens=10,
            lease_seconds=10,
        )

    assert exc_info.value.code == "AI_RUNTIME_CONTROL_UNAVAILABLE"
    assert "sensitive" not in repr(exc_info.value)


def test_oversized_token_estimate_is_rejected_before_redis() -> None:
    client = _ScriptClient()
    controller = _controller(client)

    with pytest.raises(AiRuntimeControlError) as exc_info:
        controller.acquire(
            pool=P0RateLimitPool.RAG,
            target=ModelTarget("adapter", "model"),
            estimated_tokens=100_001,
            lease_seconds=10,
        )

    assert exc_info.value.code == "AI_RATE_LIMITED"
    assert exc_info.value.retry_after_seconds == 60
    assert client.calls == []


def test_profiles_and_namespace_are_fail_closed() -> None:
    client = _ScriptClient()
    breaker = AiBreakerProfile(5, 60, 30, 1)

    with pytest.raises(ValueError, match="all approved"):
        RedisAiRuntimeControl(
            client,
            namespace="valid",
            pool_limits={P0RateLimitPool.RAG: AiRateLimitProfile(1, 1, 1, 1)},
            breaker=breaker,
        )
    with pytest.raises(ValueError, match="namespace"):
        RedisAiRuntimeControl(
            client,
            namespace="INVALID SPACE",
            pool_limits=_limits(),
            breaker=breaker,
        )
    with pytest.raises(ValueError, match="half-open"):
        AiBreakerProfile(5, 60, 30, 2)


def test_close_delegates_to_the_owned_client() -> None:
    client = _ScriptClient()
    _controller(client).close()
    assert client.closed is True
