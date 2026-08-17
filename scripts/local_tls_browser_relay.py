"""Loopback-only HTTP relay for browser tests against the local TLS Nginx stack."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
from collections.abc import Iterable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_GATE_TOKEN = "RUN_DISPOSABLE_LOCAL_TLS_BROWSER_RELAY_V1"
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_MAX_REQUEST_BYTES = 8 * 1024 * 1024
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024


def _relay_origin(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _upstream_origin(port: int) -> str:
    return f"https://localhost:{port}"


def _request_headers(
    source: Mapping[str, str],
    *,
    upstream_port: int,
    relay_port: int,
) -> dict[str, str]:
    relay_origin = _relay_origin(relay_port)
    upstream_origin = _upstream_origin(upstream_port)
    headers: dict[str, str] = {}
    for name, value in source.items():
        lowered = name.lower()
        if lowered in _HOP_BY_HOP_HEADERS or lowered == "host":
            continue
        if lowered == "origin" and value == relay_origin:
            value = upstream_origin
        elif lowered == "referer" and value.startswith(f"{relay_origin}/"):
            value = f"{upstream_origin}{value[len(relay_origin):]}"
        headers[name] = value
    headers["Host"] = f"localhost:{upstream_port}"
    return headers


def _response_headers(
    source: Iterable[tuple[str, str]],
    *,
    upstream_port: int,
    relay_port: int,
) -> list[tuple[str, str]]:
    upstream_origin = _upstream_origin(upstream_port)
    relay_origin = _relay_origin(relay_port)
    headers: list[tuple[str, str]] = []
    for name, value in source:
        lowered = name.lower()
        if lowered in _HOP_BY_HOP_HEADERS or lowered == "content-length":
            continue
        if lowered == "location" and value.startswith(upstream_origin):
            value = f"{relay_origin}{value[len(upstream_origin):]}"
        headers.append((name, value))
    return headers


class _RelayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, listen_port: int, upstream_port: int) -> None:
        super().__init__(("127.0.0.1", listen_port), _RelayHandler)
        self.listen_port = listen_port
        self.upstream_port = upstream_port
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.upstream_tls_context = context


class _RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _RelayServer

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/__finaudit_test__/relay-health":
            self._send_json(200, {"status": "ready"})
            return
        self._proxy()

    def do_HEAD(self) -> None:  # noqa: N802
        self._proxy()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._proxy()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy()

    def do_PATCH(self) -> None:  # noqa: N802
        self._proxy()

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy()

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _request_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            raise ValueError("request length is invalid") from None
        if length < 0 or length > _MAX_REQUEST_BYTES:
            raise ValueError("request length is outside the relay limit")
        return self.rfile.read(length) if length else b""

    def _proxy(self) -> None:
        connection: http.client.HTTPSConnection | None = None
        try:
            body = self._request_body()
            headers = _request_headers(
                dict(self.headers.items()),
                upstream_port=self.server.upstream_port,
                relay_port=self.server.listen_port,
            )
            connection = http.client.HTTPSConnection(
                "127.0.0.1",
                self.server.upstream_port,
                timeout=30,
                context=self.server.upstream_tls_context,
            )
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise ValueError("upstream response exceeded the relay limit")
            self.send_response(response.status, response.reason)
            for name, value in _response_headers(
                response.getheaders(),
                upstream_port=self.server.upstream_port,
                relay_port=self.server.listen_port,
            ):
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except (OSError, ValueError, http.client.HTTPException):
            self._send_json(502, {"status": "upstream_unavailable"})
        finally:
            if connection is not None:
                connection.close()

    def _send_json(self, status: int, value: dict[str, str]) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)


def _port(value: str) -> int:
    port = int(value)
    if port < 1024 or port > 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-port", type=_port, required=True)
    parser.add_argument("--upstream-port", type=_port, required=True)
    args = parser.parse_args()
    if os.environ.get("FINAUDIT_LOCAL_TLS_BROWSER_RELAY") != _GATE_TOKEN:
        parser.error("the disposable browser relay gate is not enabled")
    server = _RelayServer(args.listen_port, args.upstream_port)
    print(f"LOCAL_TLS_BROWSER_RELAY_URL={_relay_origin(args.listen_port)}", flush=True)
    print("LOCAL_TLS_BROWSER_RELAY=READY", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
