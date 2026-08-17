"""Pure wire-byte boundaries for the approved CR-011 response contract."""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Literal

from app.ai.policy import canonicalize_jcs
from app.ai.strict_json import JsonValue, StrictJsonError, parse_strict_json

_INVALID_RESPONSE = "AI response wire boundary is invalid"


class ResponseBoundaryError(ValueError):
    """Fixed-detail rejection that never renders provider bytes."""

    def __init__(self) -> None:
        super().__init__(_INVALID_RESPONSE)


@dataclass(frozen=True, slots=True)
class ResponseWireResult:
    """Validated success bytes or an unavailable non-success diagnostic body."""

    status_code: int
    header_bytes: int | None
    body: bytes | None
    diagnostic_available: bool


def _require_positive_limit(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("byte limit must be a positive integer")


def encode_request_body(payload: JsonValue, *, max_bytes: int) -> bytes:
    """Return BOM-free JCS bytes and enforce the final request-body limit."""

    _require_positive_limit(max_bytes)
    try:
        encoded = canonicalize_jcs(payload)
    except (TypeError, ValueError):
        raise ResponseBoundaryError from None
    if len(encoded) > max_bytes:
        raise ResponseBoundaryError
    return encoded


def parse_response_json(raw: bytes) -> JsonValue:
    """Reject duplicate keys and invalid I-JSON before adapter field selection."""

    try:
        return parse_strict_json(raw).value
    except (StrictJsonError, TypeError):
        raise ResponseBoundaryError from None


def count_raw_header_bytes(
    fields: tuple[tuple[bytes, bytes], ...],
    *,
    max_bytes: int = 65_536,
) -> int:
    """Count ordered raw fields as ``name + ': ' + value + CRLF``, plus final CRLF."""

    _require_positive_limit(max_bytes)
    if type(fields) is not tuple:
        raise TypeError("fields must be a tuple")

    total = 2
    for field in fields:
        if type(field) is not tuple or len(field) != 2:
            raise ResponseBoundaryError
        name, value = field
        if type(name) is not bytes or type(value) is not bytes or not name:
            raise ResponseBoundaryError
        try:
            name.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            raise ResponseBoundaryError from None
        if name.startswith(b":"):
            continue
        total += len(name) + 2 + len(value) + 2
        if total > max_bytes:
            raise ResponseBoundaryError
    return total


def decode_response_body(
    raw: bytes,
    *,
    content_encoding: Literal["identity", "gzip"],
    max_bytes: int,
) -> bytes:
    """Validate both wire and decoded byte limits and accept at most one gzip member."""

    _require_positive_limit(max_bytes)
    if type(raw) is not bytes:
        raise TypeError("raw must be bytes")
    if len(raw) > max_bytes:
        raise ResponseBoundaryError
    if content_encoding == "identity":
        return raw
    if content_encoding != "gzip":
        raise ResponseBoundaryError

    decompressor = zlib.decompressobj(wbits=zlib.MAX_WBITS | 16)
    try:
        decoded = decompressor.decompress(raw, max_bytes + 1)
    except zlib.error:
        raise ResponseBoundaryError from None
    if (
        len(decoded) > max_bytes
        or decompressor.unconsumed_tail
        or not decompressor.eof
        or decompressor.unused_data
    ):
        raise ResponseBoundaryError
    try:
        flushed = decompressor.flush()
    except zlib.error:
        raise ResponseBoundaryError from None
    if len(decoded) + len(flushed) > max_bytes:
        raise ResponseBoundaryError
    return decoded + flushed


def inspect_response_wire(
    *,
    status_code: int,
    raw_headers: tuple[tuple[bytes, bytes], ...],
    raw_body: bytes,
    content_encoding: Literal["identity", "gzip"],
    max_header_bytes: int = 65_536,
    max_body_bytes: int,
) -> ResponseWireResult:
    """Keep non-200 status authoritative when diagnostics violate byte boundaries."""

    if type(status_code) is not int or not 100 <= status_code <= 599:
        raise ValueError("status_code must be an HTTP status integer")
    try:
        header_bytes = count_raw_header_bytes(raw_headers, max_bytes=max_header_bytes)
        body = decode_response_body(
            raw_body,
            content_encoding=content_encoding,
            max_bytes=max_body_bytes,
        )
    except ResponseBoundaryError:
        if status_code == 200:
            raise
        return ResponseWireResult(
            status_code=status_code,
            header_bytes=None,
            body=None,
            diagnostic_available=False,
        )
    return ResponseWireResult(
        status_code=status_code,
        header_bytes=header_bytes,
        body=body,
        diagnostic_available=True,
    )
