from __future__ import annotations

import gzip

import pytest

from app.ai.response_boundary import (
    ResponseBoundaryError,
    count_raw_header_bytes,
    decode_response_body,
    encode_request_body,
    inspect_response_wire,
    parse_response_json,
)


def test_request_jcs_uses_the_final_bytes_for_the_limit() -> None:
    encoded = encode_request_body({"z": 1, "a": "x"}, max_bytes=15)
    assert encoded == b'{"a":"x","z":1}'
    assert encode_request_body({"a": "x"}, max_bytes=9) == b'{"a":"x"}'
    with pytest.raises(ResponseBoundaryError):
        encode_request_body({"a": "x"}, max_bytes=8)


def test_request_and_response_errors_never_render_source_values() -> None:
    sentinel = "SYNTHETIC_PROVIDER_VALUE_MUST_NOT_LEAK"
    with pytest.raises(ResponseBoundaryError) as request_error:
        encode_request_body({"value": float("nan"), "secret": sentinel}, max_bytes=1_024)
    with pytest.raises(ResponseBoundaryError) as response_error:
        parse_response_json(f'{{"secret":"{sentinel}",'.encode())
    assert sentinel not in str(request_error.value)
    assert sentinel not in str(response_error.value)


def test_response_json_rejects_duplicate_keys_but_preserves_unknown_fields() -> None:
    assert parse_response_json(b'{"known":1,"future":{"field":true}}') == {
        "known": 1,
        "future": {"field": True},
    }
    with pytest.raises(ResponseBoundaryError):
        parse_response_json(b'{"known":1,"known":2}')


def test_raw_header_formula_allows_exact_limit_and_rejects_one_more_byte() -> None:
    exact_value = b"v" * (65_536 - 7)
    assert count_raw_header_bytes(((b"x", exact_value),)) == 65_536
    with pytest.raises(ResponseBoundaryError):
        count_raw_header_bytes(((b"x", exact_value + b"v"),))


def test_http2_pseudo_headers_are_excluded_from_the_wire_header_count() -> None:
    fields = ((b":status", b"200"), (b"x", b"v"))
    assert count_raw_header_bytes(fields, max_bytes=8) == 8


@pytest.mark.parametrize(
    "fields",
    [
        (("x", b"value"),),
        ((b"\xff", b"value"),),
        ((b"", b"value"),),
    ],
)
def test_raw_headers_require_ordered_ascii_names_and_original_bytes(
    fields: object,
) -> None:
    with pytest.raises((ResponseBoundaryError, TypeError)):
        count_raw_header_bytes(fields)  # type: ignore[arg-type]


def test_identity_body_allows_exact_limit_and_rejects_one_more_byte() -> None:
    assert decode_response_body(b"1234", content_encoding="identity", max_bytes=4) == b"1234"
    with pytest.raises(ResponseBoundaryError):
        decode_response_body(b"12345", content_encoding="identity", max_bytes=4)


def test_gzip_requires_one_complete_member_with_two_independent_limits() -> None:
    payload = b"response" * 32
    member = gzip.compress(payload, mtime=0)
    assert decode_response_body(member, content_encoding="gzip", max_bytes=len(payload)) == payload

    with pytest.raises(ResponseBoundaryError):
        decode_response_body(member, content_encoding="gzip", max_bytes=len(member) - 1)
    with pytest.raises(ResponseBoundaryError):
        decode_response_body(member, content_encoding="gzip", max_bytes=len(payload) - 1)
    with pytest.raises(ResponseBoundaryError):
        decode_response_body(
            member + gzip.compress(b"second", mtime=0), content_encoding="gzip", max_bytes=1_024
        )
    with pytest.raises(ResponseBoundaryError):
        decode_response_body(member + b"trailing", content_encoding="gzip", max_bytes=1_024)
    with pytest.raises(ResponseBoundaryError):
        decode_response_body(member[:-1], content_encoding="gzip", max_bytes=1_024)

    corrupt_crc = bytearray(member)
    corrupt_crc[-8] ^= 1
    with pytest.raises(ResponseBoundaryError):
        decode_response_body(bytes(corrupt_crc), content_encoding="gzip", max_bytes=1_024)

    corrupt_isize = bytearray(member)
    corrupt_isize[-1] ^= 1
    with pytest.raises(ResponseBoundaryError):
        decode_response_body(bytes(corrupt_isize), content_encoding="gzip", max_bytes=1_024)


@pytest.mark.parametrize("status_code", [400, 429, 500, 502, 503, 504, 599])
def test_non_200_status_remains_authoritative_when_diagnostics_are_invalid(
    status_code: int,
) -> None:
    result = inspect_response_wire(
        status_code=status_code,
        raw_headers=((b"x", b"v" * 100),),
        raw_body=b"diagnostic",
        content_encoding="identity",
        max_header_bytes=10,
        max_body_bytes=1_024,
    )
    assert result.status_code == status_code
    assert result.header_bytes is None
    assert result.body is None
    assert result.diagnostic_available is False


def test_http_200_maps_the_same_boundary_failure_to_invalid_response() -> None:
    with pytest.raises(ResponseBoundaryError, match="AI response wire boundary is invalid"):
        inspect_response_wire(
            status_code=200,
            raw_headers=((b"x", b"v" * 100),),
            raw_body=b"response",
            content_encoding="identity",
            max_header_bytes=10,
            max_body_bytes=1_024,
        )


def test_success_keeps_ordered_header_count_and_exact_decoded_body() -> None:
    body = b'{"result":"ok"}'
    compressed = gzip.compress(body, mtime=0)
    result = inspect_response_wire(
        status_code=200,
        raw_headers=((b"content-type", b"application/json"), (b"x-test", b"one")),
        raw_body=compressed,
        content_encoding="gzip",
        max_body_bytes=1_024,
    )
    assert result.header_bytes == 47
    assert result.body == body
    assert result.diagnostic_available is True
