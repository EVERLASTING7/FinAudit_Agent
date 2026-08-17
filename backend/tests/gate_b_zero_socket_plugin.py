from __future__ import annotations

import _socket
import socket
import sys
from collections.abc import Callable
from typing import NoReturn

import pytest

_BLOCKED_MESSAGE = "CR-011 Gate B Stage1 forbids every socket operation"
_SOCKET_API_NAMES = (
    "create_connection",
    "create_server",
    "fromfd",
    "fromshare",
    "getaddrinfo",
    "gethostbyaddr",
    "gethostbyname",
    "gethostbyname_ex",
    "getnameinfo",
    "socketpair",
)
_ORIGINAL_SOCKET = socket.socket
_ORIGINAL_SOCKET_TYPE = socket.SocketType
_ORIGINAL_LOW_LEVEL_SOCKET = _socket.socket
_ORIGINAL_APIS = {
    name: getattr(socket, name) for name in _SOCKET_API_NAMES if hasattr(socket, name)
}
_attempts: list[str] = []
_skipped: list[str] = []
_called: set[str] = set()
_passed: set[str] = set()
_deselected: list[str] = []
_collected = 0


def _deny(api_name: str) -> NoReturn:
    _attempts.append(api_name)
    raise RuntimeError(_BLOCKED_MESSAGE)


def _audit_hook(event: str, args: tuple[object, ...]) -> None:
    del args
    if event.startswith("socket."):
        _deny(f"audit:{event}")


class _BlockedSocket(_ORIGINAL_SOCKET):
    def __new__(cls, *args: object, **kwargs: object) -> _BlockedSocket:
        del cls, args, kwargs
        _deny("socket.socket")


def _blocked_api(api_name: str) -> Callable[..., NoReturn]:
    def blocked(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        _deny(f"socket.{api_name}")

    return blocked


def _install_guard() -> None:
    socket.socket = _BlockedSocket
    socket.SocketType = _BlockedSocket
    for name in _ORIGINAL_APIS:
        setattr(socket, name, _blocked_api(name))


def _verify_probes(probes: tuple[tuple[str, Callable[[], object]], ...]) -> None:
    for expected_name, probe in probes:
        before = len(_attempts)
        try:
            probe()
        except RuntimeError as error:
            if str(error) != _BLOCKED_MESSAGE:
                raise RuntimeError(
                    "zero-socket self-test returned an unexpected error for "
                    f"{expected_name}; observed={_attempts[before:]}; "
                    f"error_type={type(error).__name__}"
                ) from None
        else:
            raise RuntimeError("zero-socket self-test unexpectedly opened a socket")
        if len(_attempts) != before + 1 or _attempts[-1] != expected_name:
            raise RuntimeError("zero-socket self-test did not identify the attempted API")
    _attempts.clear()


def _verify_audit_guard() -> None:
    _verify_probes(
        (
            ("audit:socket.__new__", lambda: _ORIGINAL_SOCKET()),
            ("audit:socket.__new__", lambda: _ORIGINAL_SOCKET_TYPE()),
            ("audit:socket.__new__", lambda: _ORIGINAL_LOW_LEVEL_SOCKET()),
            (
                "audit:socket.getaddrinfo",
                lambda: _ORIGINAL_APIS["getaddrinfo"]("localhost", 80),
            ),
        )
    )


def _verify_guard() -> None:
    _verify_probes(
        (
            ("socket.socket", lambda: socket.socket()),
            ("socket.socket", lambda: socket.SocketType()),
            ("audit:socket.__new__", lambda: _socket.socket()),
            ("audit:socket.__new__", lambda: _ORIGINAL_SOCKET()),
            ("audit:socket.__new__", lambda: _ORIGINAL_SOCKET_TYPE()),
            ("audit:socket.__new__", lambda: _ORIGINAL_LOW_LEVEL_SOCKET()),
            (
                "socket.create_connection",
                lambda: socket.create_connection(("127.0.0.1", 9)),
            ),
            ("socket.getaddrinfo", lambda: socket.getaddrinfo("localhost", 80)),
            ("socket.gethostbyname", lambda: socket.gethostbyname("localhost")),
            ("socket.socketpair", lambda: socket.socketpair()),
        )
    )


sys.addaudithook(_audit_hook)
_verify_audit_guard()
_install_guard()
_verify_guard()


def pytest_collection_finish(session: pytest.Session) -> None:
    global _collected
    _collected = len(session.items)


def pytest_deselected(items: list[pytest.Item]) -> None:
    _deselected.extend(item.nodeid for item in items)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped:
        _skipped.append(report.nodeid)
    if report.when == "call":
        _called.add(report.nodeid)
        if report.passed and not hasattr(report, "wasxfail"):
            _passed.add(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    if (
        _collected == 0
        or len(_called) != _collected
        or len(_passed) != _collected
        or _attempts
        or _skipped
        or _deselected
    ):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    del config
    if (
        exitstatus == pytest.ExitCode.OK
        and _collected > 0
        and len(_called) == _collected
        and len(_passed) == _collected
        and not _attempts
        and not _skipped
        and not _deselected
    ):
        terminalreporter.write_line("CR011_ZERO_SOCKET_GUARD=PASS")
        terminalreporter.write_line("CR011_ZERO_SOCKET_ATTEMPTS=0")
        terminalreporter.write_line(f"CR011_GATE_B_STAGE1_COLLECTED={_collected}")
        terminalreporter.write_line(f"CR011_GATE_B_STAGE1_EXECUTED={len(_called)}")
    else:
        terminalreporter.write_line("CR011_ZERO_SOCKET_GUARD=FAIL")


def pytest_unconfigure(config: pytest.Config) -> None:
    del config
    socket.socket = _ORIGINAL_SOCKET
    socket.SocketType = _ORIGINAL_SOCKET_TYPE
    for name, original in _ORIGINAL_APIS.items():
        setattr(socket, name, original)
