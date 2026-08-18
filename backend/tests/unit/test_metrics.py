from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.bootstrap import create_app
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401 - imported fixture registration
    build_startup_settings,
)


def test_metrics_requires_the_dedicated_bearer_header_and_never_echoes_it(
    exact_policy_file: Path,
) -> None:
    token = "test-metrics-token"
    application = create_app(
        build_startup_settings(exact_policy_file, metrics_internal_token=token)
    )

    with TestClient(application) as client:
        missing = client.get("/metrics")
        query_only = client.get(f"/metrics?token={token}")
        wrong = client.get("/metrics", headers={"Authorization": "Bearer wrong-token"})
        response = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})

    for denied in (missing, query_only, wrong):
        assert denied.status_code == 401
        assert denied.json()["code"] == "METRICS_AUTH_REQUIRED"
        assert denied.headers["WWW-Authenticate"] == 'Bearer realm="metrics"'
        assert denied.json()["trace_id"] == denied.headers["X-Trace-ID"]
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Type"].startswith("text/plain; version=0.0.4")
    assert token not in response.text


def test_metrics_exposes_only_bounded_request_groups_without_business_identifiers(
    exact_policy_file: Path,
) -> None:
    token = "test-metrics-token"
    application = create_app(
        build_startup_settings(
            exact_policy_file,
            app_version="metrics-test-v1",
            metrics_internal_token=token,
        )
    )
    secret_path_id = "a1111111-1111-4111-8111-111111111111"

    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert client.get(f"/api/v1/missing/{secret_path_id}").status_code == 404
        assert client.get("/customer-controlled-path").status_code == 404
        response = client.get("/metrics", headers={"Authorization": f"bearer {token}"})

    assert response.status_code == 200
    content = response.text
    assert 'finaudit_build_info{service="backend",version="metrics-test-v1"} 1' in content
    assert (
        'finaudit_http_requests_total{method="GET",request_group="health",status_class="2xx"} 1'
    ) in content
    assert 'request_group="api_v1"' in content
    assert 'request_group="other"' in content
    assert "finaudit_http_request_duration_seconds_bucket" in content
    assert 'le="+Inf"' in content
    assert secret_path_id not in content
    assert "customer-controlled-path" not in content
    assert content.endswith("# EOF\n")


def test_disabled_metrics_has_no_route_or_registry(exact_policy_file: Path) -> None:
    application = create_app(build_startup_settings(exact_policy_file, metrics_enabled=False))

    with TestClient(application) as client:
        response = client.get("/metrics", headers={"Authorization": "Bearer test-metrics-token"})
        openapi = client.get("/openapi.json").json()

    assert response.status_code == 404
    assert "/metrics" not in openapi["paths"]
    assert not hasattr(application.state, "metrics_registry")


def test_local_nginx_proxies_only_the_exact_metrics_path_and_forwards_authorization() -> None:
    project_root = Path(__file__).resolve().parents[3]
    nginx = (project_root / "frontend" / "docker" / "nginx.conf").read_text(encoding="utf-8")
    marker = "location = /metrics {"
    assert nginx.count(marker) == 1
    block = nginx.split(marker, 1)[1].split("\n        }", 1)[0]
    assert "proxy_pass http://backend:8000/metrics;" in block
    assert "proxy_hide_header X-Content-Type-Options;" in block
    assert "proxy_set_header Authorization $http_authorization;" in block


def test_local_compose_bounds_logs_and_restarts_all_long_running_services() -> None:
    project_root = Path(__file__).resolve().parents[3]
    compose = (project_root / "infra" / "compose" / "compose.local.yml").read_text(encoding="utf-8")
    backend_defaults = compose.split("x-backend-service: &backend-service", 1)[1].split(
        "\nservices:", 1
    )[0]

    assert 'driver: local\n  options:\n    max-size: "10m"\n    max-file: "5"' in compose
    assert "logging: *local-logging" in backend_defaults
    assert "restart: unless-stopped" in backend_defaults

    for service in ("postgresql", "redis", "minio", "qdrant", "clamav", "frontend"):
        tail = compose.split(f"\n  {service}:\n", 1)[1]
        next_service = re.search(r"\n  [a-z][a-z0-9-]*:\n", tail)
        block = tail if next_service is None else tail[: next_service.start()]
        assert "logging: *local-logging" in block
        assert "restart: unless-stopped" in block


def test_local_metrics_runbook_uses_the_current_loopback_http_profile() -> None:
    project_root = Path(__file__).resolve().parents[3]
    runbook = (project_root / "docs" / "runbooks" / "internal-metrics.md").read_text(
        encoding="utf-8"
    )

    assert "http://127.0.0.1:8443/metrics" in runbook
    assert "https://127.0.0.1:8443/metrics" not in runbook


def test_local_stack_metrics_gate_tracks_the_registry_metric_names() -> None:
    project_root = Path(__file__).resolve().parents[3]
    verifier = (project_root / "scripts" / "verify-local-stack.ps1").read_text(encoding="utf-8")

    assert "'finaudit_process_uptime_seconds'" in verifier
    assert "'finaudit_http_requests_in_flight'" in verifier
    assert "'finaudit_uptime_seconds'" not in verifier
    assert "'finaudit_http_inflight_requests'" not in verifier
