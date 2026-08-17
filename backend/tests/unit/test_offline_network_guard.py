from __future__ import annotations

import socket
from collections.abc import Callable

import conftest as network_guard
import pytest

BLOCKED_NETWORK_MESSAGE = "network access outside the offline test allowlist is disabled"
TEST_NET_HOST = "192.0.2.1"
UNTRUSTED_VALUE = object()
CAPTURED_GETADDRINFO = socket.getaddrinfo


def _getaddrinfo() -> object:
    return socket.getaddrinfo(UNTRUSTED_VALUE, 443)


def _gethostbyname() -> object:
    return socket.gethostbyname(UNTRUSTED_VALUE)


def _gethostbyname_ex() -> object:
    return socket.gethostbyname_ex(UNTRUSTED_VALUE)


def _gethostbyaddr() -> object:
    return socket.gethostbyaddr(UNTRUSTED_VALUE)


def _getnameinfo() -> object:
    return socket.getnameinfo((UNTRUSTED_VALUE, 443), 0)


def _create_connection() -> object:
    return socket.create_connection((UNTRUSTED_VALUE, 443), timeout=0)


def _connect() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.connect((UNTRUSTED_VALUE, 443))


def _connect_ex() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.connect_ex((UNTRUSTED_VALUE, 443))


def _sendto() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.sendto(b"blocked", (UNTRUSTED_VALUE, 443))


def _sendto_with_flags() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.sendto(b"blocked", 0, (UNTRUSTED_VALUE, 443))


@pytest.mark.parametrize(
    "operation",
    [
        _getaddrinfo,
        _gethostbyname,
        _gethostbyname_ex,
        _gethostbyaddr,
        _getnameinfo,
        _create_connection,
        _connect,
        _connect_ex,
        _sendto,
        _sendto_with_flags,
    ],
    ids=[
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname-ex",
        "gethostbyaddr",
        "getnameinfo",
        "create-connection",
        "connect",
        "connect-ex",
        "sendto",
        "sendto-flags",
    ],
)
def test_non_loopback_network_is_rejected_without_reaching_the_os(
    operation: Callable[[], object],
) -> None:
    with pytest.raises(RuntimeError) as exc_info:
        operation()

    assert str(exc_info.value) == BLOCKED_NETWORK_MESSAGE


def test_alias_captured_during_collection_remains_guarded() -> None:
    with pytest.raises(RuntimeError, match=BLOCKED_NETWORK_MESSAGE):
        CAPTURED_GETADDRINFO(UNTRUSTED_VALUE, 443)


@pytest.mark.parametrize(
    "value",
    (TEST_NET_HOST, "2001:db8::1", "example.invalid", b"\xff", UNTRUSTED_VALUE),
)
def test_non_loopback_and_non_literal_targets_fail_classification(value: object) -> None:
    assert network_guard._is_literal_loopback(value) is False


@pytest.mark.parametrize("family", (socket.AF_BLUETOOTH, -1, 999_999))
def test_non_ip_non_local_address_families_fail_closed(family: int) -> None:
    with pytest.raises(RuntimeError, match=BLOCKED_NETWORK_MESSAGE):
        network_guard._require_socket_destination(family, UNTRUSTED_VALUE)


@pytest.mark.parametrize(
    ("host", "family"),
    (("127.255.255.254", socket.AF_INET), ("::1", socket.AF_INET6)),
)
def test_literal_loopback_ranges_are_allowed_for_resolution(host: str, family: int) -> None:
    addresses = socket.getaddrinfo(host, 0, family, socket.SOCK_STREAM)

    assert addresses


def test_loopback_connection_remains_available() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        with socket.create_connection(listener.getsockname(), timeout=1):
            connection, _ = listener.accept()
            connection.close()
