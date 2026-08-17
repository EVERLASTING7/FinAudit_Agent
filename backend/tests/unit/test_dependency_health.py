from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.health import get_dependency_health_service
from app.bootstrap import create_app
from app.schemas.health import DependencyCheckData, DependencyName
from app.services.dependency_health import DependencyHealthService, DependencyHealthSnapshot
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401 - imported fixture registration
    build_startup_settings,
)
from tests.unit.test_config import build_settings

_REQUIRED_NAMES: tuple[DependencyName, ...] = (
    "postgresql",
    "redis",
    "minio",
    "qdrant",
    "worker",
)


def _probes(failing: DependencyName | None = None) -> dict[DependencyName, Callable[[], bool]]:
    return {name: (lambda value=name: value != failing) for name in _REQUIRED_NAMES}


def test_all_required_dependencies_ready_and_disabled_profiles_are_explicit() -> None:
    service = DependencyHealthService(build_settings(), probes=_probes())

    snapshot = service.check()

    assert snapshot.status == "ok"
    assert [(item.name, item.required, item.status) for item in snapshot.dependencies] == [
        ("postgresql", True, "ok"),
        ("redis", True, "ok"),
        ("minio", True, "ok"),
        ("qdrant", True, "ok"),
        ("worker", True, "ok"),
        ("scanner", False, "disabled"),
        ("ai_provider", False, "disabled"),
    ]


@pytest.mark.parametrize("failing", _REQUIRED_NAMES)
def test_each_required_dependency_failure_makes_snapshot_unavailable(
    failing: DependencyName,
) -> None:
    service = DependencyHealthService(build_settings(), probes=_probes(failing))

    snapshot = service.check()

    assert snapshot.status == "unavailable"
    failed = next(item for item in snapshot.dependencies if item.name == failing)
    assert failed.required is True
    assert failed.status == "unavailable"


def test_probe_timeout_is_redacted_to_unavailable() -> None:
    probes = _probes()

    def timeout() -> bool:
        raise TimeoutError

    probes["redis"] = timeout
    service = DependencyHealthService(build_settings(), probes=probes)

    snapshot = service.check()

    assert snapshot.status == "unavailable"
    assert "TimeoutError" not in repr(snapshot)


def test_dependency_endpoint_uses_503_with_the_same_redacted_projection(
    exact_policy_file: Path,
) -> None:
    application = create_app(build_startup_settings(exact_policy_file))
    snapshot = DependencyHealthSnapshot(
        status="unavailable",
        dependencies=(
            DependencyCheckData(name="postgresql", required=True, status="unavailable"),
            DependencyCheckData(name="scanner", required=False, status="disabled"),
        ),
    )

    class FakeDependencyHealthService:
        def check(self) -> DependencyHealthSnapshot:
            return snapshot

    application.dependency_overrides[get_dependency_health_service] = FakeDependencyHealthService

    with TestClient(application) as client:
        response = client.get("/health/dependencies")

    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == "DEPENDENCY_UNAVAILABLE"
    assert payload["data"]["status"] == "unavailable"
    assert payload["data"]["dependencies"] == [
        {"name": "postgresql", "required": True, "status": "unavailable"},
        {"name": "scanner", "required": False, "status": "disabled"},
    ]
    assert set(payload) == {"code", "message", "data", "trace_id", "timestamp"}
