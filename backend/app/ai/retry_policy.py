"""CR-011-R3 的纯值 timeout、retry 与 ``Retry-After`` 算法。"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import datetime

_MAX_RETRY_WAIT_SECONDS = 30.0
_SATURATED_RETRY_AFTER_SECONDS = 31
_UNIX_EPOCH = datetime(1970, 1, 1)
_WEEKDAYS = (b"Mon", b"Tue", b"Wed", b"Thu", b"Fri", b"Sat", b"Sun")
_MONTHS = {
    b"Jan": 1,
    b"Feb": 2,
    b"Mar": 3,
    b"Apr": 4,
    b"May": 5,
    b"Jun": 6,
    b"Jul": 7,
    b"Aug": 8,
    b"Sep": 9,
    b"Oct": 10,
    b"Nov": 11,
    b"Dec": 12,
}
_IMF_FIXDATE = re.compile(
    rb"(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun), "
    rb"(?P<day>[0-9]{2}) "
    rb"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    rb"(?P<year>[0-9]{4}) "
    rb"(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2}) GMT"
)


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except OverflowError:
        raise ValueError(f"{name} must be a finite number") from None
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def can_start_connection(
    *,
    remaining_deadline_seconds: float,
    connect_timeout_seconds: float,
    min_processing_margin_seconds: float,
) -> bool:
    """只在 remaining 严格大于 connect timeout 与处理余量之和时放行。"""

    remaining = _finite_number("remaining_deadline_seconds", remaining_deadline_seconds)
    connect_timeout = _finite_number("connect_timeout_seconds", connect_timeout_seconds)
    processing_margin = _finite_number(
        "min_processing_margin_seconds",
        min_processing_margin_seconds,
    )
    if connect_timeout <= 0:
        raise ValueError("connect_timeout_seconds must be positive")
    if processing_margin < 0:
        raise ValueError("min_processing_margin_seconds must be non-negative")
    return remaining > connect_timeout + processing_margin


def calculate_retry_wait_seconds(
    *,
    retry_ordinal: int,
    random_unit_interval: float,
    parsed_retry_after_seconds: int | None = None,
) -> float:
    """计算同一逻辑生成、同一目标中 ordinal 从 1 开始的 retry 等待。"""

    if isinstance(retry_ordinal, bool) or not isinstance(retry_ordinal, int):
        raise ValueError("retry_ordinal must be a positive integer")
    if retry_ordinal < 1:
        raise ValueError("retry_ordinal must be a positive integer")
    random_value = _finite_number("random_unit_interval", random_unit_interval)
    if not 0 <= random_value < 1:
        raise ValueError("random_unit_interval must satisfy 0 <= u < 1")
    if parsed_retry_after_seconds is None:
        retry_after = 0
    elif (
        isinstance(parsed_retry_after_seconds, bool)
        or not isinstance(parsed_retry_after_seconds, int)
        or parsed_retry_after_seconds < 0
    ):
        raise ValueError("parsed_retry_after_seconds must be a non-negative integer")
    else:
        retry_after = parsed_retry_after_seconds

    base = 30.0 if retry_ordinal >= 6 else float(1 << (retry_ordinal - 1))
    jittered_local = min(
        _MAX_RETRY_WAIT_SECONDS,
        base * (0.8 + 0.4 * random_value),
    )
    return max(jittered_local, retry_after)


def _parse_imf_fixdate(value: bytes, wall_clock_epoch_seconds: object) -> int | None:
    match = _IMF_FIXDATE.fullmatch(value)
    if match is None:
        return None
    try:
        parsed = datetime(
            int(match["year"]),
            _MONTHS[match["month"]],
            int(match["day"]),
            int(match["hour"]),
            int(match["minute"]),
            int(match["second"]),
        )
    except ValueError:
        return None
    if _WEEKDAYS[parsed.weekday()] != match["weekday"]:
        return None

    wall_clock = _finite_number("wall_clock_epoch_seconds", wall_clock_epoch_seconds)
    delta = parsed - _UNIX_EPOCH
    provider_epoch_seconds = delta.days * 86_400 + delta.seconds
    return max(0, math.ceil(provider_epoch_seconds - wall_clock))


def parse_retry_after_seconds(
    *,
    status_code: int,
    header_values: Sequence[bytes],
    wall_clock_epoch_seconds: float,
) -> int | None:
    """解析 HTTP 429 的单个 raw ``Retry-After``，非法输入一律忽略。"""

    if type(status_code) is not int or status_code != 429:
        return None
    if isinstance(header_values, (str, bytes, bytearray, memoryview)) or not isinstance(
        header_values,
        Sequence,
    ):
        return None
    if len(header_values) != 1 or type(header_values[0]) is not bytes:
        return None

    value = header_values[0].strip(b" \t")
    if not value:
        return None
    if value.isdigit():
        if len(value) > 16:
            return _SATURATED_RETRY_AFTER_SECONDS
        return int(value)
    return _parse_imf_fixdate(value, wall_clock_epoch_seconds)


def can_retry_before_deadline(
    *,
    monotonic_now: float,
    effective_wait_seconds: float,
    min_processing_margin_seconds: float,
    deadline_monotonic: float,
) -> bool:
    """按同一 monotonic 轴判断 cap 与严格 deadline 余量。"""

    now = _finite_number("monotonic_now", monotonic_now)
    wait = _finite_number("effective_wait_seconds", effective_wait_seconds)
    processing_margin = _finite_number(
        "min_processing_margin_seconds",
        min_processing_margin_seconds,
    )
    deadline = _finite_number("deadline_monotonic", deadline_monotonic)
    if wait < 0:
        raise ValueError("effective_wait_seconds must be non-negative")
    if processing_margin < 0:
        raise ValueError("min_processing_margin_seconds must be non-negative")
    if wait > _MAX_RETRY_WAIT_SECONDS:
        return False
    return now + wait + processing_margin < deadline
