from __future__ import annotations

import ipaddress
import socket

import pytest

_BLOCKED_NETWORK_MESSAGE = "network access outside the offline test allowlist is disabled"
_NETWORK_FAMILIES = {socket.AF_INET, socket.AF_INET6}
_LOCAL_FAMILIES = {socket.AF_UNIX} if hasattr(socket, "AF_UNIX") else set()

_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_ORIGINAL_GETHOSTBYNAME = socket.gethostbyname
_ORIGINAL_GETHOSTBYNAME_EX = socket.gethostbyname_ex
_ORIGINAL_GETHOSTBYADDR = socket.gethostbyaddr
_ORIGINAL_GETNAMEINFO = socket.getnameinfo
_ORIGINAL_CREATE_CONNECTION = socket.create_connection
_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_SENDTO = socket.socket.sendto
_ORIGINAL_SENDMSG = getattr(socket.socket, "sendmsg", None)


def _is_literal_loopback(address_or_host: object) -> bool:
    if isinstance(address_or_host, tuple):
        if not address_or_host:
            return False
        host = address_or_host[0]
    else:
        host = address_or_host
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(host, str):
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _require_literal_loopback(address_or_host: object) -> None:
    if not _is_literal_loopback(address_or_host):
        raise RuntimeError(_BLOCKED_NETWORK_MESSAGE)


def _require_socket_destination(family: int, address: object) -> None:
    if family in _LOCAL_FAMILIES:
        return
    if family in _NETWORK_FAMILIES:
        _require_literal_loopback(address)
        return
    raise RuntimeError(_BLOCKED_NETWORK_MESSAGE)


def _guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
    _require_literal_loopback(host)
    return _ORIGINAL_GETADDRINFO(host, *args, **kwargs)


def _guarded_gethostbyname(host: object) -> str:
    _require_literal_loopback(host)
    return _ORIGINAL_GETHOSTBYNAME(host)


def _guarded_gethostbyname_ex(host: object) -> tuple[str, list[str], list[str]]:
    _require_literal_loopback(host)
    return _ORIGINAL_GETHOSTBYNAME_EX(host)


def _guarded_gethostbyaddr(host: object) -> tuple[str, list[str], list[str]]:
    del host
    raise RuntimeError(_BLOCKED_NETWORK_MESSAGE)


def _guarded_getnameinfo(address: object, flags: int) -> tuple[str, str]:
    _require_literal_loopback(address)
    if not flags & socket.NI_NUMERICHOST:
        raise RuntimeError(_BLOCKED_NETWORK_MESSAGE)
    return _ORIGINAL_GETNAMEINFO(address, flags)


def _guarded_create_connection(
    address: object,
    *args: object,
    **kwargs: object,
) -> socket.socket:
    _require_literal_loopback(address)
    return _ORIGINAL_CREATE_CONNECTION(address, *args, **kwargs)


def _guarded_connect(instance: socket.socket, address: object) -> None:
    _require_socket_destination(instance.family, address)
    return _ORIGINAL_CONNECT(instance, address)


def _guarded_connect_ex(instance: socket.socket, address: object) -> int:
    _require_socket_destination(instance.family, address)
    return _ORIGINAL_CONNECT_EX(instance, address)


def _guarded_sendto(instance: socket.socket, data: object, *args: object) -> int:
    if args:
        _require_socket_destination(instance.family, args[-1])
    return _ORIGINAL_SENDTO(instance, data, *args)


def _guarded_sendmsg(instance: socket.socket, buffers: object, *args: object) -> int:
    if len(args) >= 3 and args[2] is not None:
        _require_socket_destination(instance.family, args[2])
    if _ORIGINAL_SENDMSG is None:
        raise RuntimeError(_BLOCKED_NETWORK_MESSAGE)
    return _ORIGINAL_SENDMSG(instance, buffers, *args)


def _install_network_guard() -> None:
    socket.getaddrinfo = _guarded_getaddrinfo
    socket.gethostbyname = _guarded_gethostbyname
    socket.gethostbyname_ex = _guarded_gethostbyname_ex
    socket.gethostbyaddr = _guarded_gethostbyaddr
    socket.getnameinfo = _guarded_getnameinfo
    socket.create_connection = _guarded_create_connection
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.socket.sendto = _guarded_sendto
    if _ORIGINAL_SENDMSG is not None:
        socket.socket.sendmsg = _guarded_sendmsg


def _restore_network_functions() -> None:
    replacements = (
        (socket, "getaddrinfo", _guarded_getaddrinfo, _ORIGINAL_GETADDRINFO),
        (socket, "gethostbyname", _guarded_gethostbyname, _ORIGINAL_GETHOSTBYNAME),
        (socket, "gethostbyname_ex", _guarded_gethostbyname_ex, _ORIGINAL_GETHOSTBYNAME_EX),
        (socket, "gethostbyaddr", _guarded_gethostbyaddr, _ORIGINAL_GETHOSTBYADDR),
        (socket, "getnameinfo", _guarded_getnameinfo, _ORIGINAL_GETNAMEINFO),
        (socket, "create_connection", _guarded_create_connection, _ORIGINAL_CREATE_CONNECTION),
        (socket.socket, "connect", _guarded_connect, _ORIGINAL_CONNECT),
        (socket.socket, "connect_ex", _guarded_connect_ex, _ORIGINAL_CONNECT_EX),
        (socket.socket, "sendto", _guarded_sendto, _ORIGINAL_SENDTO),
    )
    for owner, name, guarded, original in replacements:
        if getattr(owner, name) is guarded:
            setattr(owner, name, original)
    if _ORIGINAL_SENDMSG is not None and socket.socket.sendmsg is _guarded_sendmsg:
        socket.socket.sendmsg = _ORIGINAL_SENDMSG


_install_network_guard()


def pytest_unconfigure(config: pytest.Config) -> None:
    del config
    _restore_network_functions()
