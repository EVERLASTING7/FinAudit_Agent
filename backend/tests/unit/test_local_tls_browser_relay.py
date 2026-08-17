from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import local_tls_browser_relay as subject  # noqa: E402


def test_request_headers_are_rewritten_to_the_fixed_tls_origin() -> None:
    headers = subject._request_headers(
        {
            "Host": "127.0.0.1:18444",
            "Origin": "http://127.0.0.1:18444",
            "Referer": "http://127.0.0.1:18444/qa",
            "Connection": "keep-alive",
            "Authorization": "Bearer synthetic-token",
        },
        upstream_port=18443,
        relay_port=18444,
    )

    assert headers["Host"] == "localhost:18443"
    assert headers["Origin"] == "https://localhost:18443"
    assert headers["Referer"] == "https://localhost:18443/qa"
    assert headers["Authorization"] == "Bearer synthetic-token"
    assert "Connection" not in headers


def test_response_location_is_rewritten_without_weakening_secure_cookies() -> None:
    headers = subject._response_headers(
        [
            ("Location", "https://localhost:18443/qa"),
            ("Set-Cookie", "refresh=synthetic; Secure; HttpOnly; SameSite=Strict"),
            ("Transfer-Encoding", "chunked"),
        ],
        upstream_port=18443,
        relay_port=18444,
    )

    assert ("Location", "http://127.0.0.1:18444/qa") in headers
    assert (
        "Set-Cookie",
        "refresh=synthetic; Secure; HttpOnly; SameSite=Strict",
    ) in headers
    assert all(name.lower() != "transfer-encoding" for name, _value in headers)
