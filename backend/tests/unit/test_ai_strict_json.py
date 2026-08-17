from __future__ import annotations

import pytest

from app.ai.strict_json import StrictJsonError, parse_strict_json


def test_parser_requires_exact_bytes_input() -> None:
    with pytest.raises(TypeError, match="raw must be bytes"):
        parse_strict_json("{}")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="raw must be bytes"):
        parse_strict_json(bytearray(b"{}"))  # type: ignore[arg-type]


def test_parser_retains_number_lexemes_and_rfc6901_pointers() -> None:
    document = parse_strict_json(b'{"a/b":{"~n":1},"values":[-0,1.0,1e0]}')

    assert document.value == {"a/b": {"~n": 1}, "values": [0, 1.0, 1.0]}
    assert [(token.pointer, token.lexeme) for token in document.number_tokens] == [
        ("/a~1b/~0n", "1"),
        ("/values/0", "-0"),
        ("/values/1", "1.0"),
        ("/values/2", "1e0"),
    ]


def test_parser_normalizes_a_valid_escaped_surrogate_pair() -> None:
    document = parse_strict_json(b'{"emoji":"\\ud83d\\ude00"}')

    assert document.value == {"emoji": "😀"}


def test_parser_retains_an_integer_beyond_the_python_311_digit_limit() -> None:
    lexeme = "9" * 5_000

    document = parse_strict_json(f'{{"value":{lexeme}}}'.encode())

    assert isinstance(document.value, dict)
    value = document.value["value"]
    assert isinstance(value, int)
    assert value.bit_length() > 16_000
    assert [(token.pointer, token.lexeme) for token in document.number_tokens] == [
        ("/value", lexeme)
    ]


@pytest.mark.parametrize(
    "raw",
    [
        b"\xef\xbb\xbf{}",
        b'"\xff"',
        b'{"duplicate":1,"duplicate":2}',
        b'{"\\ud83d\\ude00":1,"\xf0\x9f\x98\x80":2}',
        b'"\\ud800"',
        b'"\\udc00"',
        b"NaN",
        b"Infinity",
        b"-Infinity",
        b"1e9999",
    ],
)
def test_parser_rejects_non_strict_sources_with_fixed_safe_detail(raw: bytes) -> None:
    with pytest.raises(StrictJsonError) as caught:
        parse_strict_json(raw)

    assert str(caught.value) == "strict JSON source is invalid"
    assert raw.decode("utf-8", errors="ignore") not in str(caught.value)
