import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.ai.policy_loader import PolicyStartupError
from app.core.config import AppEnvironment, Settings
from app.workers.bootstrap import create_celery_app
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401 - imported fixture registration
    build_startup_settings,
    install_startup_environment,
)

_EXPECTED_RAW_SHA256 = "da229cdb14bc40df8f6a0731498b0f947ab1f4f28b97a69f28e0f88af27119bb"


def build_settings(policy_file: Path, **overrides: object) -> Settings:
    return build_startup_settings(policy_file, **overrides)


def import_celery_app_module(
    monkeypatch: pytest.MonkeyPatch,
    policy_file: Path,
    *,
    environment: AppEnvironment,
) -> ModuleType:
    install_startup_environment(
        monkeypatch,
        policy_file,
        environment=environment,
    )
    module_name = "app.workers.celery_app"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


@pytest.mark.parametrize("environment", [AppEnvironment.LOCAL, AppEnvironment.TEST])
def test_module_exposes_the_validated_deployment_app(
    monkeypatch: pytest.MonkeyPatch,
    exact_policy_file: Path,
    environment: AppEnvironment,
) -> None:
    module_name = "app.workers.celery_app"
    try:
        module = import_celery_app_module(
            monkeypatch,
            exact_policy_file,
            environment=environment,
        )

        assert module.app is module.celery_app
        assert module.app._finaudit_policy_snapshot.raw_sha256 == _EXPECTED_RAW_SHA256
        assert not hasattr(module, "create_celery_app")
    finally:
        sys.modules.pop(module_name, None)


def test_celery_app_declares_exactly_seven_deterministic_routes(
    exact_policy_file: Path,
) -> None:
    settings = build_settings(
        exact_policy_file,
        celery_queue_document="queue-document",
        celery_queue_extraction="queue-extraction",
        celery_queue_knowledge="queue-knowledge",
        celery_queue_evaluation="queue-evaluation",
        celery_queue_audit="queue-audit",
        celery_queue_report="queue-report",
        celery_queue_maintenance="queue-maintenance",
    )

    application = create_celery_app(settings)
    logical_queues = (
        "document",
        "extraction",
        "knowledge",
        "evaluation",
        "audit",
        "report",
        "maintenance",
    )
    expected_task_names = {
        f"app.workers.tasks.{logical_queue}.execute_job" for logical_queue in logical_queues
    }

    assert set(application.conf.task_queues) == {
        "queue-document",
        "queue-extraction",
        "queue-knowledge",
        "queue-evaluation",
        "queue-audit",
        "queue-report",
        "queue-maintenance",
    }
    assert {
        name for name in application.tasks if name.startswith("app.workers.tasks.")
    } == expected_task_names
    for logical_queue in logical_queues:
        route = application.amqp.router.route(
            {},
            f"app.workers.tasks.{logical_queue}.execute_job",
        )
        assert route["queue"].name == f"queue-{logical_queue}"
        assert route["routing_key"] == f"queue-{logical_queue}"
    assert application.conf.task_create_missing_queues is False


@pytest.mark.parametrize(
    "unknown_task",
    [
        "app.workers.tasks.unapproved.execute_job",
        "app.workers.tasks.document.unapproved",
        "totally.unrelated.task",
    ],
)
def test_celery_app_rejects_unknown_task_routes(
    exact_policy_file: Path,
    unknown_task: str,
) -> None:
    application = create_celery_app(build_settings(exact_policy_file))

    with pytest.raises(ValueError, match="未进入批准的精确路由"):
        application.amqp.router.route({}, unknown_task)


def test_celery_app_uses_safe_serialization_delivery_and_timeout_settings(
    exact_policy_file: Path,
) -> None:
    settings = build_settings(
        exact_policy_file,
        celery_task_soft_time_limit_seconds=41,
        celery_task_time_limit_seconds=47,
    )

    application = create_celery_app(settings)

    assert set(application.conf.accept_content) == {"json"}
    assert application.conf.task_serializer == "json"
    assert application.conf.result_serializer == "json"
    assert application.conf.enable_utc is True
    assert application.conf.timezone == "UTC"
    assert application.conf.task_protocol == 2
    assert application.conf.task_soft_time_limit == 41
    assert application.conf.task_time_limit == 47
    assert application.conf.task_acks_late is True
    assert application.conf.task_reject_on_worker_lost is True
    assert application.conf.task_ignore_result is True
    assert application.conf.task_store_errors_even_if_ignored is False
    assert application.conf.task_publish_retry is False
    assert application.conf.broker_connection_retry_on_startup is True


def test_production_is_rejected_before_celery_application_construction(
    exact_policy_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production_settings = build_startup_settings(
        exact_policy_file,
        environment=AppEnvironment.PROD,
        auth_jwt_active_kid="authkey01",
        auth_jwt_private_key_file="C:\\synthetic\\auth-private.pem",
        auth_jwt_public_keyring_file="C:\\synthetic\\auth-public.json",
        auth_public_origin="https://audit.example",
    )
    constructor_attempts = 0

    def forbidden_celery_constructor(*args: object, **kwargs: object) -> None:
        nonlocal constructor_attempts
        del args, kwargs
        constructor_attempts += 1
        raise AssertionError("Celery constructor must not run for prod")

    monkeypatch.setattr("celery.Celery", forbidden_celery_constructor)

    with pytest.raises(PolicyStartupError) as exc_info:
        create_celery_app(production_settings)

    assert exc_info.value.stage == "environment_authorization"
    assert constructor_attempts == 0
