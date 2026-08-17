import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError

from app.ai.policy_loader import PolicyStartupError
from app.api.dependencies.settings import get_settings
from app.bootstrap import create_app
from app.core.config import AppEnvironment, Settings
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401 - imported fixture registration
    build_startup_settings,
    install_startup_environment,
)

_EXPECTED_POLICY_HASH = "db946ad109baf5ec84455a2d0a09ce5e29602c0d9f9ce8404901f5c63683443d"
_EXPECTED_RAW_SHA256 = "da229cdb14bc40df8f6a0731498b0f947ab1f4f28b97a69f28e0f88af27119bb"


@pytest.fixture
def settings(exact_policy_file: Path) -> Settings:
    return build_startup_settings(exact_policy_file)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.mark.parametrize("environment", [AppEnvironment.LOCAL, AppEnvironment.TEST])
def test_factory_adopts_the_exact_immutable_policy_snapshot(
    exact_policy_file: Path,
    environment: AppEnvironment,
) -> None:
    active_settings = build_startup_settings(exact_policy_file, environment=environment)

    application = create_app(active_settings)

    assert application.state.settings is active_settings
    snapshot = application.state.ai_policy_snapshot
    assert snapshot.policy_version == 1
    assert snapshot.policy_hash == _EXPECTED_POLICY_HASH
    assert snapshot.raw_sha256 == _EXPECTED_RAW_SHA256


@pytest.mark.parametrize("environment", [AppEnvironment.LOCAL, AppEnvironment.TEST])
def test_deployment_module_exposes_only_a_validated_app(
    exact_policy_file: Path,
    environment: AppEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_startup_environment(
        monkeypatch,
        exact_policy_file,
        environment=environment,
    )
    module_name = "app.main"
    sys.modules.pop(module_name, None)
    try:
        module = importlib.import_module(module_name)

        assert module.app.state.settings.app_env is environment
        assert module.app.state.ai_policy_snapshot.raw_sha256 == _EXPECTED_RAW_SHA256
        assert not hasattr(module, "create_app")
    finally:
        sys.modules.pop(module_name, None)


def test_health_uses_success_envelope_without_dependency_details(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == "OK"
    assert payload["data"]["status"] == "ok"
    assert payload["data"]["service"] == "backend"
    assert payload["trace_id"] == response.headers["X-Trace-ID"]
    assert "dependencies" not in payload["data"]
    assert "model" not in response.text.lower()


def test_valid_traceparent_is_continued(client: TestClient) -> None:
    response = client.get(
        "/health",
        headers={"traceparent": "00-11111111111111111111111111111111-2222222222222222-01"},
    )

    assert response.headers["X-Trace-ID"] == "11111111-1111-1111-1111-111111111111"
    assert response.json()["trace_id"] == response.headers["X-Trace-ID"]


def test_invalid_traceparent_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"traceparent": "invalid"})

    assert str(UUID(response.headers["X-Trace-ID"])) == response.headers["X-Trace-ID"]


def test_not_found_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/missing")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    assert response.json()["trace_id"] == response.headers["X-Trace-ID"]


def test_unknown_exception_is_redacted(settings: Settings) -> None:
    application: FastAPI = create_app(settings)

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError(
            "password=top-secret; SELECT * FROM users; C:\\private\\file; system prompt"
        )

    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.json()["trace_id"] == response.headers["X-Trace-ID"]
    for forbidden in ("top-secret", "SELECT", "private", "system prompt", "Traceback"):
        assert forbidden not in response.text


def test_openapi_is_available(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]


def test_production_disables_openapi_and_interactive_docs(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_snapshot = create_app(settings).state.ai_policy_snapshot
    production_settings = settings.model_copy(
        update={
            "app_env": AppEnvironment.PROD,
            "auth_public_origin": "https://audit.example",
        }
    )
    monkeypatch.setattr(
        "app.bootstrap.load_validated_policy",
        lambda _: policy_snapshot,
    )

    application = create_app(production_settings)
    assert application.openapi_url is None
    assert application.docs_url is None
    assert application.redoc_url is None

    with TestClient(application) as test_client:
        assert test_client.get("/health").status_code == 200
        for path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
            assert test_client.get(path).status_code == 404


def test_health_openapi_uses_chinese_description_and_example(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/health"]["get"]

    assert any("\u4e00" <= character <= "\u9fff" for character in operation["summary"])
    assert any("\u4e00" <= character <= "\u9fff" for character in operation["description"])

    example = operation["responses"]["200"]["content"]["application/json"]["example"]
    assert set(example) == {"code", "message", "data", "trace_id", "timestamp"}
    assert example["data"]["status"] == "ok"
    assert example["data"]["service"] == "backend"


def test_validation_error_openapi_matches_runtime(settings: Settings) -> None:
    application = create_app(settings)

    @application.get("/api/v1/probe")
    async def probe(limit: Annotated[int, Query(ge=1)]) -> dict[str, int]:
        return {"limit": limit}

    with TestClient(application) as test_client:
        runtime_response = test_client.get("/api/v1/probe", params={"limit": 0})
        openapi_response = test_client.get("/openapi.json")

    assert runtime_response.status_code == 422
    assert set(runtime_response.json()) == {
        "code",
        "message",
        "details",
        "trace_id",
        "timestamp",
    }
    assert runtime_response.json()["code"] == "VALIDATION_ERROR"

    openapi = openapi_response.json()
    validation_schema = openapi["paths"]["/api/v1/probe"]["get"]["responses"]["422"]["content"][
        "application/json"
    ]["schema"]
    assert validation_schema == {"$ref": "#/components/schemas/ErrorResponse"}
    assert "ErrorResponse" in openapi["components"]["schemas"]


@pytest.mark.parametrize(
    "malicious_key",
    [
        "password=synthetic-sensitive-value",
        "SENSITIVE_TOKEN_VALUE",
        "合成密钥值",
        "line\nbreak",
    ],
)
def test_validation_error_masks_attacker_controlled_location_tokens(
    settings: Settings,
    malicious_key: str,
) -> None:
    application = create_app(settings)

    @application.post("/api/v1/validation-location-probe")
    async def validation_location_probe(payload: dict[int, list[dict[int, int]]]) -> None:
        return None

    with TestClient(application) as test_client:
        response = test_client.post(
            "/api/v1/validation-location-probe",
            json={"1": [{malicious_key: "not-an-integer"}]},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["trace_id"] == response.headers["X-Trace-ID"]
    assert body["details"]
    rendered = repr(body)
    assert malicious_key not in rendered
    assert repr(malicious_key)[1:-1] not in rendered
    for detail in body["details"]:
        field = detail["field"]
        assert isinstance(field, str)
        tokens = field.split(".")
        assert tokens[0] in {"body", "cookie", "header", "path", "query"}
        assert all(token == "*" or token.isdecimal() for token in tokens[1:])


def test_validation_error_masks_dynamic_custom_error_type(settings: Settings) -> None:
    malicious_reason = "password=synthetic-sensitive-value\n合成密钥值"

    class DynamicErrorModel(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def reject_with_dynamic_type(cls, value: str) -> str:
            raise PydanticCustomError(value, "fixed safe message")

    application = create_app(settings)

    @application.post("/api/v1/validation-reason-probe")
    async def validation_reason_probe(payload: DynamicErrorModel) -> None:
        return None

    with TestClient(application) as test_client:
        response = test_client.post(
            "/api/v1/validation-reason-probe",
            json={"value": malicious_reason},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["details"] == [{"field": "body.*", "reason": "invalid"}]
    assert malicious_reason not in response.text


def test_production_is_rejected_before_fastapi_application_construction(
    exact_policy_file: Path, monkeypatch: pytest.MonkeyPatch
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

    def forbidden_fastapi_constructor(*args: object, **kwargs: object) -> None:
        nonlocal constructor_attempts
        del args, kwargs
        constructor_attempts += 1
        raise AssertionError("FastAPI constructor must not run for prod")

    monkeypatch.setattr("fastapi.FastAPI", forbidden_fastapi_constructor)

    with pytest.raises(PolicyStartupError) as exc_info:
        create_app(production_settings)

    assert exc_info.value.stage == "environment_authorization"
    assert constructor_attempts == 0


def test_lifespan_disposes_auth_engine_when_service_construction_fails(
    exact_policy_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_settings = build_startup_settings(
        exact_policy_file,
        auth_jwt_active_kid="authkey01",
        auth_jwt_private_key_file="C:\\synthetic\\auth-private.pem",
        auth_jwt_public_keyring_file="C:\\synthetic\\auth-public.json",
    )
    engine = Mock()
    monkeypatch.setattr(
        "app.api.dependencies.auth.load_auth_keyring",
        Mock(return_value=Mock()),
    )
    monkeypatch.setattr(
        "app.db.session.create_application_engine",
        Mock(return_value=engine),
    )
    monkeypatch.setattr(
        "app.db.session.create_session_factory",
        Mock(return_value=Mock()),
    )
    monkeypatch.setattr(
        "app.core.auth_security.hash_password",
        Mock(return_value="synthetic-password-hash"),
    )
    monkeypatch.setattr(
        "app.services.auth.AuthService",
        Mock(side_effect=RuntimeError("synthetic service construction failure")),
    )

    application = create_app(active_settings)

    with pytest.raises(RuntimeError, match="synthetic service construction failure"):
        with TestClient(application):
            pass

    engine.dispose.assert_called_once_with()


def test_health_settings_can_be_overridden_through_dependency_injection(
    settings: Settings,
    exact_policy_file: Path,
) -> None:
    application = create_app(settings)
    overridden_settings = build_startup_settings(
        exact_policy_file,
        app_version="9.9.9-test",
    )
    application.dependency_overrides[get_settings] = lambda: overridden_settings

    with TestClient(application) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json()["data"]["version"] == "9.9.9-test"
