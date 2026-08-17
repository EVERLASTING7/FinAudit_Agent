from __future__ import annotations

import builtins
import math
import os
import socket
import time
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest

from app.ai.retry_policy import (
    calculate_retry_wait_seconds,
    can_retry_before_deadline,
    can_start_connection,
    parse_retry_after_seconds,
)

_IMF_DATE = b"Sun, 06 Nov 1994 08:49:37 GMT"
_IMF_DATE_EPOCH_SECONDS = 784_111_777


def test_connection_requires_strictly_more_than_timeout_and_margin() -> None:
    boundary = 6.0

    assert not can_start_connection(
        remaining_deadline_seconds=boundary,
        connect_timeout_seconds=5.0,
        min_processing_margin_seconds=1.0,
    )
    assert not can_start_connection(
        remaining_deadline_seconds=math.nextafter(boundary, -math.inf),
        connect_timeout_seconds=5.0,
        min_processing_margin_seconds=1.0,
    )
    assert can_start_connection(
        remaining_deadline_seconds=math.nextafter(boundary, math.inf),
        connect_timeout_seconds=5.0,
        min_processing_margin_seconds=1.0,
    )


def test_retry_formula_matches_every_ordinal_and_jitter_edge() -> None:
    random_values = (0.0, 0.25, 0.5, math.nextafter(1.0, 0.0))

    for retry_ordinal in range(1, 50):
        base = min(30.0, float(2 ** (retry_ordinal - 1)))
        for random_value in random_values:
            expected = min(30.0, base * (0.8 + 0.4 * random_value))
            assert calculate_retry_wait_seconds(
                retry_ordinal=retry_ordinal,
                random_unit_interval=random_value,
            ) == pytest.approx(expected)

    assert calculate_retry_wait_seconds(
        retry_ordinal=10**9,
        random_unit_interval=0.0,
    ) == pytest.approx(24.0)


def test_retry_after_never_gets_shortened_by_local_jitter() -> None:
    assert (
        calculate_retry_wait_seconds(
            retry_ordinal=1,
            random_unit_interval=0.0,
            parsed_retry_after_seconds=2,
        )
        == 2
    )
    assert calculate_retry_wait_seconds(
        retry_ordinal=2,
        random_unit_interval=0.0,
        parsed_retry_after_seconds=1,
    ) == pytest.approx(1.6)
    assert (
        calculate_retry_wait_seconds(
            retry_ordinal=1,
            random_unit_interval=0.0,
            parsed_retry_after_seconds=31,
        )
        == 31
    )


@pytest.mark.parametrize(
    ("retry_ordinal", "random_value"),
    [
        (0, 0.0),
        (-1, 0.0),
        (True, 0.0),
        (1, -math.ulp(1.0)),
        (1, 1.0),
        (1, math.inf),
        (1, math.nan),
        (1, True),
    ],
)
def test_retry_ordinal_and_random_source_fail_closed(
    retry_ordinal: Any,
    random_value: Any,
) -> None:
    with pytest.raises(ValueError):
        calculate_retry_wait_seconds(
            retry_ordinal=retry_ordinal,
            random_unit_interval=random_value,
        )


@pytest.mark.parametrize("invalid", [-1, True, 1.5, "1"])
def test_parsed_retry_after_must_be_a_non_negative_integer(invalid: Any) -> None:
    with pytest.raises(ValueError, match="parsed_retry_after_seconds"):
        calculate_retry_wait_seconds(
            retry_ordinal=1,
            random_unit_interval=0.0,
            parsed_retry_after_seconds=invalid,
        )


def test_retry_after_integer_seconds_accept_only_one_429_header() -> None:
    assert (
        parse_retry_after_seconds(
            status_code=429,
            header_values=(b"\t 0005 \t",),
            wall_clock_epoch_seconds=math.nan,
        )
        == 5
    )
    assert (
        parse_retry_after_seconds(
            status_code=500,
            header_values=(b"7",),
            wall_clock_epoch_seconds=math.nan,
        )
        is None
    )

    invalid_headers: tuple[SequenceForTest, ...] = (
        (),
        (b"1", b"2"),
        (b" \t ",),
        (b"1, 2",),
        (b"+1",),
        (b"1.0",),
        ("1".encode("utf-16"),),
        cast(SequenceForTest, b"1"),
    )
    for header_values in invalid_headers:
        assert (
            parse_retry_after_seconds(
                status_code=429,
                header_values=cast(Any, header_values),
                wall_clock_epoch_seconds=0.0,
            )
            is None
        )


def test_retry_after_long_digits_saturate_without_unbounded_integer_parse() -> None:
    assert (
        parse_retry_after_seconds(
            status_code=429,
            header_values=(b"9" * 16,),
            wall_clock_epoch_seconds=0.0,
        )
        == 9_999_999_999_999_999
    )
    assert (
        parse_retry_after_seconds(
            status_code=429,
            header_values=(b"0" * 17,),
            wall_clock_epoch_seconds=0.0,
        )
        == 31
    )
    assert (
        parse_retry_after_seconds(
            status_code=429,
            header_values=(b"9" * 10_000,),
            wall_clock_epoch_seconds=0.0,
        )
        == 31
    )
    assert (
        parse_retry_after_seconds(
            status_code=429,
            header_values=(b"9" * 17 + b"x",),
            wall_clock_epoch_seconds=0.0,
        )
        is None
    )


def test_retry_after_strict_imf_fixdate_uses_only_injected_wall_clock() -> None:
    assert (
        parse_retry_after_seconds(
            status_code=429,
            header_values=(b"\t" + _IMF_DATE + b" ",),
            wall_clock_epoch_seconds=_IMF_DATE_EPOCH_SECONDS,
        )
        == 0
    )
    assert (
        parse_retry_after_seconds(
            status_code=429,
            header_values=(_IMF_DATE,),
            wall_clock_epoch_seconds=_IMF_DATE_EPOCH_SECONDS - 0.1,
        )
        == 1
    )
    assert (
        parse_retry_after_seconds(
            status_code=429,
            header_values=(_IMF_DATE,),
            wall_clock_epoch_seconds=_IMF_DATE_EPOCH_SECONDS - 2,
        )
        == 2
    )
    assert (
        parse_retry_after_seconds(
            status_code=429,
            header_values=(_IMF_DATE,),
            wall_clock_epoch_seconds=_IMF_DATE_EPOCH_SECONDS + 1,
        )
        == 0
    )


@pytest.mark.parametrize(
    "value",
    [
        b"Mon, 06 Nov 1994 08:49:37 GMT",
        b"Sun, 31 Feb 1994 08:49:37 GMT",
        b"Sunday, 06-Nov-94 08:49:37 GMT",
        b"Sun Nov  6 08:49:37 1994",
        b"sun, 06 Nov 1994 08:49:37 GMT",
        b"Sun, 6 Nov 1994 08:49:37 GMT",
        b"Sun, 06 nov 1994 08:49:37 GMT",
        b"Sun, 06 Nov 1994 08:49:37 UTC",
        b"Sun, 06 Nov 1994 08:49 GMT",
        _IMF_DATE + b", 120",
    ],
)
def test_retry_after_rejects_non_strict_or_inconsistent_dates(value: bytes) -> None:
    assert (
        parse_retry_after_seconds(
            status_code=429,
            header_values=(value,),
            wall_clock_epoch_seconds=0.0,
        )
        is None
    )


def test_retry_after_date_requires_a_finite_injected_wall_clock() -> None:
    for wall_clock in (math.nan, math.inf, -math.inf, True, "synthetic-wall-secret"):
        with pytest.raises(ValueError, match="wall_clock_epoch_seconds") as exc_info:
            parse_retry_after_seconds(
                status_code=429,
                header_values=(_IMF_DATE,),
                wall_clock_epoch_seconds=cast(Any, wall_clock),
            )
        assert "synthetic-wall-secret" not in str(exc_info.value)


def test_retry_deadline_rejects_cap_and_exact_boundary() -> None:
    assert can_retry_before_deadline(
        monotonic_now=100.0,
        effective_wait_seconds=30.0,
        min_processing_margin_seconds=1.0,
        deadline_monotonic=132.0,
    )
    assert not can_retry_before_deadline(
        monotonic_now=100.0,
        effective_wait_seconds=31.0,
        min_processing_margin_seconds=1.0,
        deadline_monotonic=1_000.0,
    )
    boundary = 111.0
    assert not can_retry_before_deadline(
        monotonic_now=100.0,
        effective_wait_seconds=10.0,
        min_processing_margin_seconds=1.0,
        deadline_monotonic=boundary,
    )
    assert can_retry_before_deadline(
        monotonic_now=100.0,
        effective_wait_seconds=10.0,
        min_processing_margin_seconds=1.0,
        deadline_monotonic=math.nextafter(boundary, math.inf),
    )


@pytest.mark.parametrize(
    ("function_name", "kwargs"),
    [
        (
            "connect",
            {
                "remaining_deadline_seconds": math.nan,
                "connect_timeout_seconds": 5.0,
                "min_processing_margin_seconds": 1.0,
            },
        ),
        (
            "connect",
            {
                "remaining_deadline_seconds": 10.0,
                "connect_timeout_seconds": 0.0,
                "min_processing_margin_seconds": 1.0,
            },
        ),
        (
            "retry",
            {
                "monotonic_now": 100.0,
                "effective_wait_seconds": -1.0,
                "min_processing_margin_seconds": 1.0,
                "deadline_monotonic": 200.0,
            },
        ),
        (
            "retry",
            {
                "monotonic_now": 100.0,
                "effective_wait_seconds": 1.0,
                "min_processing_margin_seconds": 1.0,
                "deadline_monotonic": math.inf,
            },
        ),
    ],
)
def test_deadline_inputs_fail_closed(function_name: str, kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        if function_name == "connect":
            can_start_connection(**kwargs)
        else:
            can_retry_before_deadline(**kwargs)


def test_retry_policy_uses_only_injected_values(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_call(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise AssertionError("retry policy must not perform runtime I/O")

    monkeypatch.setattr(builtins, "open", unexpected_call)
    monkeypatch.setattr(os, "getenv", unexpected_call)
    monkeypatch.setattr(Path, "read_bytes", unexpected_call)
    monkeypatch.setattr(socket, "socket", unexpected_call)
    monkeypatch.setattr(socket, "create_connection", unexpected_call)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected_call)
    monkeypatch.setattr(time, "monotonic", unexpected_call)
    monkeypatch.setattr(time, "time", unexpected_call)
    monkeypatch.setattr(time, "sleep", unexpected_call)

    retry_after = parse_retry_after_seconds(
        status_code=429,
        header_values=(_IMF_DATE,),
        wall_clock_epoch_seconds=_IMF_DATE_EPOCH_SECONDS - 1,
    )
    wait = calculate_retry_wait_seconds(
        retry_ordinal=1,
        random_unit_interval=0.0,
        parsed_retry_after_seconds=retry_after,
    )
    assert can_start_connection(
        remaining_deadline_seconds=7.0,
        connect_timeout_seconds=5.0,
        min_processing_margin_seconds=1.0,
    )
    assert can_retry_before_deadline(
        monotonic_now=100.0,
        effective_wait_seconds=wait,
        min_processing_margin_seconds=1.0,
        deadline_monotonic=103.0,
    )


SequenceForTest = tuple[bytes, ...] | bytes
