"""真实 AI 调用的 Redis 跨进程限流与熔断。"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import uuid4

from redis.exceptions import RedisError

from app.ai.contracts import ModelTarget
from app.ai.routing import P0RateLimitPool

RuntimeOutcome = Literal["success", "transient_failure", "neutral"]

_ACQUIRE_SCRIPT = r"""
local now_parts = redis.call('TIME')
local now_ms = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)
local lease_id = ARGV[1]
local token_cost = tonumber(ARGV[2])
local concurrency_limit = tonumber(ARGV[3])
local request_rate = tonumber(ARGV[4])
local token_rate = tonumber(ARGV[5])
local burst_capacity = tonumber(ARGV[6])
local lease_ms = tonumber(ARGV[7])

local half_open = 0
local open_until_raw = redis.call('GET', KEYS[5])
if open_until_raw then
    local open_until = tonumber(open_until_raw)
    if now_ms < open_until then
        return {0, 'breaker_open', open_until - now_ms}
    end
    local half_owner = redis.call('GET', KEYS[6])
    if half_owner then
        local ttl = redis.call('PTTL', KEYS[6])
        return {0, 'breaker_open', math.max(ttl, 1)}
    end
    local claimed = redis.call('SET', KEYS[6], lease_id, 'PX', lease_ms, 'NX')
    if not claimed then
        return {0, 'breaker_open', 1000}
    end
    local open_ttl = redis.call('PTTL', KEYS[5])
    if open_ttl < lease_ms + 60000 then
        redis.call('PEXPIRE', KEYS[5], lease_ms + 60000)
    end
    half_open = 1
else
    redis.call('DEL', KEYS[6])
end

local function release_half_open()
    if half_open == 1 and redis.call('GET', KEYS[6]) == lease_id then
        redis.call('DEL', KEYS[6])
    end
end

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
if redis.call('ZCARD', KEYS[1]) >= concurrency_limit then
    local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry_ms = 1000
    if first[2] then
        retry_ms = math.max(tonumber(first[2]) - now_ms, 1)
    end
    release_half_open()
    return {0, 'concurrency', retry_ms}
end

local function refill_bucket(key, capacity, rate_per_minute, cost)
    local tokens = tonumber(redis.call('HGET', key, 'tokens'))
    local updated_at = tonumber(redis.call('HGET', key, 'updated_at_ms'))
    if not tokens or not updated_at then
        tokens = capacity
        updated_at = now_ms
    else
        local elapsed = math.max(now_ms - updated_at, 0)
        tokens = math.min(capacity, tokens + elapsed * rate_per_minute / 60000)
    end
    if tokens + 0.0000001 < cost then
        local retry_ms = math.ceil((cost - tokens) * 60000 / rate_per_minute)
        return {0, tokens, math.max(retry_ms, 1)}
    end
    return {1, tokens - cost, 0}
end

local request_bucket = refill_bucket(KEYS[2], burst_capacity, request_rate, 1)
if request_bucket[1] == 0 then
    release_half_open()
    return {0, 'request_rate', request_bucket[3]}
end

local token_bucket = refill_bucket(KEYS[3], token_rate, token_rate, token_cost)
if token_bucket[1] == 0 then
    release_half_open()
    return {0, 'token_rate', token_bucket[3]}
end

redis.call('HSET', KEYS[2], 'tokens', request_bucket[2], 'updated_at_ms', now_ms)
redis.call('PEXPIRE', KEYS[2], 120000)
redis.call('HSET', KEYS[3], 'tokens', token_bucket[2], 'updated_at_ms', now_ms)
redis.call('PEXPIRE', KEYS[3], 120000)
redis.call('ZADD', KEYS[1], now_ms + lease_ms, lease_id)
redis.call('PEXPIRE', KEYS[1], math.max(lease_ms * 2, 120000))
return {1, half_open, 0}
"""

_FINISH_SCRIPT = r"""
local now_parts = redis.call('TIME')
local now_ms = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)
local lease_id = ARGV[1]
local outcome = ARGV[2]
local failure_limit = tonumber(ARGV[3])
local window_ms = tonumber(ARGV[4])
local open_ms = tonumber(ARGV[5])

redis.call('ZREM', KEYS[1], lease_id)
local half_owner = redis.call('GET', KEYS[4])
local is_half_open = half_owner == lease_id
if is_half_open then
    redis.call('DEL', KEYS[4])
end

if is_half_open and (outcome == 'success' or outcome == 'neutral') then
    redis.call('DEL', KEYS[2], KEYS[3], KEYS[4])
    return 1
end
if outcome == 'success' or outcome == 'neutral' then
    return 1
end

redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now_ms - window_ms)
redis.call('ZADD', KEYS[2], now_ms, tostring(now_ms) .. ':' .. lease_id)
redis.call('PEXPIRE', KEYS[2], window_ms + open_ms + 60000)
local failure_count = redis.call('ZCARD', KEYS[2])
if is_half_open or failure_count >= failure_limit then
    redis.call('SET', KEYS[3], now_ms + open_ms, 'PX', open_ms * 2 + 60000)
end
return 1
"""


class RedisScriptClient(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object: ...

    def close(self) -> None: ...


class AiRuntimeController(Protocol):
    def acquire(
        self,
        *,
        pool: P0RateLimitPool,
        target: ModelTarget,
        estimated_tokens: int,
        lease_seconds: float,
    ) -> AiRuntimePermit: ...


class AiRuntimeControlError(RuntimeError):
    """不携带 Redis 地址、Provider 目标或业务输入的稳定失败。"""

    def __init__(self, code: str, *, retry_after_seconds: int | None = None) -> None:
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AiRateLimitProfile:
    concurrency: int
    rpm: int
    tpm: int
    burst: int

    def __post_init__(self) -> None:
        for name, value in (
            ("concurrency", self.concurrency),
            ("rpm", self.rpm),
            ("tpm", self.tpm),
            ("burst", self.burst),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class AiBreakerProfile:
    failures: int
    window_seconds: int
    open_seconds: int
    half_open_probes: int

    def __post_init__(self) -> None:
        for name, value in (
            ("failures", self.failures),
            ("window_seconds", self.window_seconds),
            ("open_seconds", self.open_seconds),
            ("half_open_probes", self.half_open_probes),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.half_open_probes != 1:
            raise ValueError("only one half-open probe is supported by the approved profile")


@dataclass(slots=True)
class AiRuntimePermit:
    breaker_state: Literal["closed", "half_open"]
    _controller: RedisAiRuntimeControl
    _keys: tuple[str, str, str, str]
    _lease_id: str
    _finished: bool = False

    def finish(self, outcome: RuntimeOutcome) -> None:
        if self._finished:
            raise AiRuntimeControlError("AI_RUNTIME_CONTROL_PERMIT_ALREADY_FINISHED")
        self._controller._finish(self._keys, self._lease_id, outcome)
        self._finished = True


class RedisAiRuntimeControl:
    """使用 Redis server time 和 Lua 原子维护三类共享调用门禁。"""

    def __init__(
        self,
        client: RedisScriptClient,
        *,
        namespace: str,
        pool_limits: Mapping[P0RateLimitPool, AiRateLimitProfile],
        breaker: AiBreakerProfile,
    ) -> None:
        if re.fullmatch(r"[a-z0-9:_-]{1,96}", namespace) is None:
            raise ValueError("namespace must be a bounded lowercase identifier")
        limits = dict(pool_limits)
        if set(limits) != set(P0RateLimitPool) or not all(
            isinstance(value, AiRateLimitProfile) for value in limits.values()
        ):
            raise ValueError("all approved rate-limit pools must be configured exactly once")
        if not isinstance(breaker, AiBreakerProfile):
            raise TypeError("breaker must be an AiBreakerProfile")
        self._client = client
        self._prefix = f"{{{namespace}}}"
        self._limits = limits
        self._breaker = breaker

    def acquire(
        self,
        *,
        pool: P0RateLimitPool,
        target: ModelTarget,
        estimated_tokens: int,
        lease_seconds: float,
    ) -> AiRuntimePermit:
        if not isinstance(pool, P0RateLimitPool) or pool not in self._limits:
            raise AiRuntimeControlError("AI_RUNTIME_CONTROL_POOL_INVALID")
        if not isinstance(target, ModelTarget):
            raise AiRuntimeControlError("AI_RUNTIME_CONTROL_TARGET_INVALID")
        if type(estimated_tokens) is not int or estimated_tokens <= 0:
            raise AiRuntimeControlError("AI_RUNTIME_CONTROL_TOKEN_ESTIMATE_INVALID")
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, (int, float))
            or not math.isfinite(float(lease_seconds))
            or lease_seconds < 1
            or lease_seconds > 600
        ):
            raise AiRuntimeControlError("AI_RUNTIME_CONTROL_LEASE_INVALID")

        limits = self._limits[pool]
        if estimated_tokens > limits.tpm:
            raise AiRuntimeControlError("AI_RATE_LIMITED", retry_after_seconds=60)
        lease_id = uuid4().hex
        target_hash = hashlib.sha256(
            f"{target.adapter_id}\0{target.model_id}".encode()
        ).hexdigest()[:24]
        pool_prefix = f"{self._prefix}:pool:{pool.value}"
        target_prefix = f"{self._prefix}:target:{target_hash}"
        keys = (
            f"{pool_prefix}:concurrency",
            f"{pool_prefix}:request_bucket",
            f"{pool_prefix}:token_bucket",
            f"{target_prefix}:failures",
            f"{target_prefix}:open_until",
            f"{target_prefix}:half_open",
        )
        try:
            raw = self._client.eval(
                _ACQUIRE_SCRIPT,
                len(keys),
                *keys,
                lease_id,
                str(estimated_tokens),
                str(limits.concurrency),
                str(limits.rpm),
                str(limits.tpm),
                str(limits.burst),
                str(math.ceil(float(lease_seconds) * 1_000)),
            )
        except (RedisError, OSError, ValueError, TypeError):
            raise AiRuntimeControlError("AI_RUNTIME_CONTROL_UNAVAILABLE") from None
        result = _result_tuple(raw, expected=3)
        if _result_int(result[0]) == 1:
            half_open = _result_int(result[1])
            if half_open not in {0, 1}:
                raise AiRuntimeControlError("AI_RUNTIME_CONTROL_UNAVAILABLE")
            return AiRuntimePermit(
                breaker_state="half_open" if half_open == 1 else "closed",
                _controller=self,
                _keys=(keys[0], keys[3], keys[4], keys[5]),
                _lease_id=lease_id,
            )

        reason = _result_text(result[1])
        retry_after_seconds = max(1, math.ceil(_result_int(result[2]) / 1_000))
        code = {
            "breaker_open": "AI_BREAKER_OPEN",
            "concurrency": "AI_CONCURRENCY_LIMITED",
            "request_rate": "AI_RATE_LIMITED",
            "token_rate": "AI_RATE_LIMITED",
        }.get(reason)
        if code is None:
            raise AiRuntimeControlError("AI_RUNTIME_CONTROL_UNAVAILABLE")
        raise AiRuntimeControlError(code, retry_after_seconds=retry_after_seconds)

    def _finish(
        self,
        keys: tuple[str, str, str, str],
        lease_id: str,
        outcome: RuntimeOutcome,
    ) -> None:
        if outcome not in {"success", "transient_failure", "neutral"}:
            raise AiRuntimeControlError("AI_RUNTIME_CONTROL_OUTCOME_INVALID")
        try:
            raw = self._client.eval(
                _FINISH_SCRIPT,
                len(keys),
                *keys,
                lease_id,
                outcome,
                str(self._breaker.failures),
                str(self._breaker.window_seconds * 1_000),
                str(self._breaker.open_seconds * 1_000),
            )
        except (RedisError, OSError, ValueError, TypeError):
            raise AiRuntimeControlError("AI_RUNTIME_CONTROL_UNAVAILABLE") from None
        if _result_int(raw) != 1:
            raise AiRuntimeControlError("AI_RUNTIME_CONTROL_UNAVAILABLE")

    def close(self) -> None:
        self._client.close()


def _result_tuple(value: object, *, expected: int) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != expected:
        raise AiRuntimeControlError("AI_RUNTIME_CONTROL_UNAVAILABLE")
    return tuple(value)


def _result_int(value: object) -> int:
    if isinstance(value, bool):
        raise AiRuntimeControlError("AI_RUNTIME_CONTROL_UNAVAILABLE")
    if isinstance(value, int):
        return value
    if isinstance(value, bytes):
        try:
            return int(value.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            pass
    raise AiRuntimeControlError("AI_RUNTIME_CONTROL_UNAVAILABLE")


def _result_text(value: object) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("ascii")
        except UnicodeDecodeError:
            pass
    if isinstance(value, str) and value.isascii():
        return value
    raise AiRuntimeControlError("AI_RUNTIME_CONTROL_UNAVAILABLE")


__all__ = [
    "AiBreakerProfile",
    "AiRateLimitProfile",
    "AiRuntimeControlError",
    "AiRuntimeController",
    "AiRuntimePermit",
    "RedisAiRuntimeControl",
    "RuntimeOutcome",
]
