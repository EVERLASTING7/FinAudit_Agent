"""Outbox Dispatcher 常驻进程入口。"""

from __future__ import annotations

import logging
import signal
import threading
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.services.job_dispatcher import (
    CeleryJobMessagePublisher,
    DispatchResult,
    OutboxDispatcher,
)
from app.workers.bootstrap import create_celery_app

_IDLE_WAIT_SECONDS = 0.25
_ERROR_WAIT_SECONDS = 1.0
_LOG = logging.getLogger("finaudit.dispatcher")


@dataclass(slots=True)
class DispatcherProcessRuntime:
    engine: Engine
    dispatcher: OutboxDispatcher

    def close(self) -> None:
        self.engine.dispose()


def create_dispatcher_runtime(settings: Settings | None = None) -> DispatcherProcessRuntime:
    active_settings = settings or Settings()
    application = create_celery_app(active_settings)
    engine = create_application_engine(active_settings)
    try:
        dispatcher = OutboxDispatcher(
            create_session_factory(engine),
            CeleryJobMessagePublisher(application),
            active_settings,
        )
    except Exception:
        engine.dispose()
        raise
    return DispatcherProcessRuntime(engine=engine, dispatcher=dispatcher)


def run_dispatcher_iteration(runtime: DispatcherProcessRuntime) -> DispatchResult:
    reaped = runtime.dispatcher.reap_expired_once()
    if reaped.outcome != "idle":
        return reaped
    return runtime.dispatcher.dispatch_once()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    stop = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    try:
        runtime = create_dispatcher_runtime()
    except Exception:
        _LOG.error("DISPATCHER_STARTUP_FAILED")
        return 1
    try:
        while not stop.is_set():
            try:
                result = run_dispatcher_iteration(runtime)
            except Exception:
                _LOG.error("DISPATCHER_ITERATION_FAILED")
                stop.wait(_ERROR_WAIT_SECONDS)
                continue
            if result.outcome == "idle":
                stop.wait(_IDLE_WAIT_SECONDS)
            else:
                _LOG.info(
                    "DISPATCHER_OUTCOME outcome=%s outbox_id=%s job_id=%s",
                    result.outcome,
                    result.outbox_id,
                    result.job_id,
                )
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DispatcherProcessRuntime",
    "create_dispatcher_runtime",
    "main",
    "run_dispatcher_iteration",
]
