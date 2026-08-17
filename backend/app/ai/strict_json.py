"""Strict, side-effect-free JSON source parsing for approved AI policy bytes."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TypeAlias, cast

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class StrictJsonError(ValueError):
    """A fixed-detail error that never reflects untrusted source content."""

    def __init__(self) -> None:
        super().__init__("strict JSON source is invalid")


class _StrictJsonViolation(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _ParsedNumber:
    lexeme: str
    value: int | float


@dataclass(frozen=True, slots=True)
class JsonNumberToken:
    """A JSON number token paired with its RFC 6901 instance pointer."""

    pointer: str
    lexeme: str
    value: int | float


@dataclass(frozen=True, slots=True)
class StrictJsonDocument:
    """The parsed value plus the original number-token spellings."""

    value: JsonValue
    number_tokens: tuple[JsonNumberToken, ...]


def _normalize_surrogates(value: str) -> str:
    normalized: list[str] = []
    index = 0
    while index < len(value):
        codepoint = ord(value[index])
        if 0xD800 <= codepoint <= 0xDBFF:
            if index + 1 >= len(value):
                raise _StrictJsonViolation
            low = ord(value[index + 1])
            if not 0xDC00 <= low <= 0xDFFF:
                raise _StrictJsonViolation
            scalar = 0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00)
            normalized.append(chr(scalar))
            index += 2
            continue
        if 0xDC00 <= codepoint <= 0xDFFF:
            raise _StrictJsonViolation
        normalized.append(value[index])
        index += 1
    return "".join(normalized)


def _parse_integer(lexeme: str) -> _ParsedNumber:
    negative = lexeme.startswith("-")
    digits = lexeme[1:] if negative else lexeme
    if not digits or any(character < "0" or character > "9" for character in digits):
        raise _StrictJsonViolation

    # Python 3.11+ limits direct decimal-string-to-int conversion by default.
    # Convert bounded chunks so a valid JSON token reaches POL-VAL-002 on every
    # supported interpreter instead of being misclassified as a raw-parse error.
    chunk_width = 9
    first_width = len(digits) % chunk_width or chunk_width
    value = int(digits[:first_width])
    for offset in range(first_width, len(digits), chunk_width):
        value = value * 1_000_000_000 + int(digits[offset : offset + chunk_width])
    return _ParsedNumber(lexeme=lexeme, value=-value if negative else value)


def _parse_float(lexeme: str) -> _ParsedNumber:
    value = float(lexeme)
    if not math.isfinite(value):
        raise _StrictJsonViolation
    return _ParsedNumber(lexeme=lexeme, value=value)


def _reject_constant(_lexeme: str) -> object:
    raise _StrictJsonViolation


def _decode_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    decoded: dict[str, object] = {}
    for raw_key, value in pairs:
        key = _normalize_surrogates(raw_key)
        if key in decoded:
            raise _StrictJsonViolation
        decoded[key] = value
    return decoded


def _pointer_child(pointer: str, segment: str) -> str:
    escaped = segment.replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{escaped}"


def _unwrap(
    value: object,
    *,
    pointer: str,
    tokens: list[JsonNumberToken],
) -> JsonValue:
    if isinstance(value, _ParsedNumber):
        tokens.append(JsonNumberToken(pointer=pointer, lexeme=value.lexeme, value=value.value))
        return value.value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _normalize_surrogates(value)
    if isinstance(value, list):
        children = cast(list[object], value)
        return [
            _unwrap(child, pointer=_pointer_child(pointer, str(index)), tokens=tokens)
            for index, child in enumerate(children)
        ]
    if isinstance(value, dict):
        members = cast(dict[str, object], value)
        return {
            key: _unwrap(child, pointer=_pointer_child(pointer, key), tokens=tokens)
            for key, child in members.items()
        }
    raise _StrictJsonViolation


def parse_strict_json(raw: bytes) -> StrictJsonDocument:
    """Parse UTF-8 JSON bytes without BOM, duplicate keys, or non-I-JSON values."""

    if type(raw) is not bytes:
        raise TypeError("raw must be bytes")

    try:
        if raw.startswith(b"\xef\xbb\xbf"):
            raise _StrictJsonViolation
        text = raw.decode("utf-8", errors="strict")
        if text.startswith("\ufeff"):
            raise _StrictJsonViolation
        decoded = cast(
            object,
            json.loads(
                text,
                parse_int=_parse_integer,
                parse_float=_parse_float,
                parse_constant=_reject_constant,
                object_pairs_hook=_decode_object,
            ),
        )
        tokens: list[JsonNumberToken] = []
        value = _unwrap(decoded, pointer="", tokens=tokens)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _StrictJsonViolation,
        RecursionError,
    ):
        raise StrictJsonError from None

    return StrictJsonDocument(value=value, number_tokens=tuple(tokens))
