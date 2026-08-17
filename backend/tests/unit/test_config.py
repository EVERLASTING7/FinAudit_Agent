from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.bootstrap import create_app
from app.core.config import (
    DEFAULT_REPOSITORY_ENV_FILE,
    EXACT_INTEGER_SETTINGS,
    AppEnvironment,
    Settings,
)

VALID_SETTINGS: dict[str, object] = {
    "app_env": "test",
    "secret_key": "test-signing-key-with-at-least-32-characters",
    "database_url": "postgresql+psycopg://test:test-password@postgresql:5432/test",
    "redis_url": "redis://:test-password@redis:6379/0",
    "celery_broker_url": "redis://:test-password@redis:6379/0",
    "celery_result_backend": "redis://:test-password@redis:6379/1",
    "minio_access_key": "test-minio-access",
    "minio_secret_key": "test-minio-secret",
    "qdrant_collection": "finaudit_policy_chunks_test_e1024_v1",
    "ai_policy_file": "D:\\synthetic\\ai-policy-v1.json",
    "llm_api_key": "test-llm-key",
    "llm_extraction_model": "test-extraction-model",
    "llm_generation_model": "test-generation-model",
    "embedding_base_url": "http://embedding:8000/v1",
    "embedding_api_key": "test-embedding-key",
    "embedding_model": "test-embedding-model",
    "metrics_internal_token": "test-metrics-token",
}

RUNTIME_IDENTIFIER_FIELDS = (
    "celery_queue_document",
    "celery_queue_extraction",
    "celery_queue_knowledge",
    "celery_queue_evaluation",
    "celery_queue_audit",
    "celery_queue_report",
    "celery_queue_maintenance",
    "minio_bucket_quarantine",
    "minio_bucket_originals",
    "minio_bucket_assets",
    "minio_bucket_previews",
    "minio_bucket_reports",
    "minio_bucket_exports",
    "minio_bucket_temp",
)
LEGACY_CHUNKING_FIELDS = (
    "chunk_target_min_chars",
    "chunk_target_max_chars",
    "chunk_max_chars",
    "chunk_overlap_chars",
    "chunk_short_threshold_chars",
)


def build_settings(**overrides: object) -> Settings:
    values = VALID_SETTINGS | overrides
    return Settings(_env_file=None, **values)


def build_settings_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    **overrides: object,
) -> Settings:
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    for field, value in (VALID_SETTINGS | overrides).items():
        monkeypatch.setenv(field.upper(), str(value))
    return Settings(_env_file=None)


def test_repository_dotenv_is_configured_as_the_default() -> None:
    expected = Path(__file__).resolve().parents[3] / "infra" / "env" / ".env"

    assert DEFAULT_REPOSITORY_ENV_FILE == expected
    assert Settings.model_config["env_file"] == expected
    assert Settings.model_config["env_file_encoding"] == "utf-8"


def test_environment_and_runtime_secrets_override_default_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    for field, value in VALID_SETTINGS.items():
        if field != "secret_key":
            monkeypatch.setenv(field.upper(), str(value))
    monkeypatch.setenv("APP_NAME", "process-environment-name")

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "APP_NAME=repository-dotenv-name\n"
        "SECRET_KEY=dotenv-signing-key-with-at-least-32-characters\n",
        encoding="utf-8",
    )
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "secret_key").write_text(
        "runtime-secret-signing-key-with-at-least-32-characters",
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "env_file", dotenv_path)

    settings = Settings(_secrets_dir=secrets_dir)

    assert settings.app_name == "process-environment-name"
    assert (
        settings.secret_key.get_secret_value()
        == "runtime-secret-signing-key-with-at-least-32-characters"
    )


def test_runtime_secret_directory_can_supply_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    for field, value in VALID_SETTINGS.items():
        (tmp_path / field).write_text(str(value), encoding="utf-8")

    settings = Settings(_secrets_dir=tmp_path, _env_file=None)

    assert settings.database_url.get_secret_value() == VALID_SETTINGS["database_url"]
    assert settings.secret_key.get_secret_value() == VALID_SETTINGS["secret_key"]


@pytest.mark.parametrize("environment", ["local", "test"])
def test_environment_layers_are_supported(environment: str) -> None:
    settings = build_settings(app_env=environment)

    assert settings.app_env is AppEnvironment(environment)


def test_production_requires_complete_auth_key_profile() -> None:
    with pytest.raises(ValidationError):
        build_settings(app_env="prod")

    with pytest.raises(ValidationError):
        build_settings(
            app_env="prod",
            auth_jwt_active_kid="authkey01",
            auth_jwt_private_key_file="C:\\run\\secrets\\auth-private.pem",
            auth_jwt_public_keyring_file="C:\\run\\secrets\\auth-public.json",
        )

    configured = build_settings(
        app_env="prod",
        auth_jwt_active_kid="authkey01",
        auth_jwt_private_key_file="C:\\run\\secrets\\auth-private.pem",
        auth_jwt_public_keyring_file="C:\\run\\secrets\\auth-public.json",
        auth_public_origin="https://audit.example",
        minio_endpoint="https://minio.example:9000",
        minio_secure=True,
        scanner_provider="clamav_instream",
        scanner_host="scanner.internal",
    )

    assert configured.app_env is AppEnvironment.PROD
    assert configured.auth_public_origin == "https://audit.example"


def test_clamav_scanner_requires_a_valid_host() -> None:
    with pytest.raises(ValidationError):
        build_settings(scanner_provider="clamav_instream")

    settings = build_settings(
        scanner_provider="clamav_instream",
        scanner_host="scanner.internal",
    )
    assert settings.scanner_host == "scanner.internal"


def test_minio_worker_credentials_are_optional_but_atomic() -> None:
    settings = build_settings()
    assert settings.minio_worker_access_key is None
    assert settings.minio_worker_secret_key is None

    with pytest.raises(ValidationError):
        build_settings(minio_worker_access_key="test-worker-access")
    with pytest.raises(ValidationError):
        build_settings(minio_worker_secret_key="test-worker-secret")

    configured = build_settings(
        minio_worker_access_key="test-worker-access",
        minio_worker_secret_key="test-worker-secret",
    )
    assert configured.minio_worker_access_key is not None
    assert configured.minio_worker_secret_key is not None


def test_tesseract_ocr_profile_is_explicit_and_atomic() -> None:
    settings = build_settings()
    assert settings.ocr_provider == "not_configured"

    with pytest.raises(ValidationError):
        build_settings(ocr_provider="tesseract_cli")
    with pytest.raises(ValidationError):
        build_settings(
            ocr_tesseract_executable="C:\\approved\\tesseract.exe",
            ocr_tesseract_version="5.5.0",
        )
    with pytest.raises(ValidationError):
        build_settings(ocr_base_url="https://ocr.example", ocr_api_key="test-ocr-key")

    configured = build_settings(
        ocr_provider="tesseract_cli",
        ocr_tesseract_executable="C:\\approved\\tesseract.exe",
        ocr_tesseract_version="5.5.0",
    )
    assert configured.ocr_tesseract_version == "5.5.0"


@pytest.mark.parametrize(
    "origin",
    [
        "https://user@audit.example",
        "https://audit.example/",
        "https://audit.example/path",
        "https://audit.example?query=1",
        "https://audit.example#fragment",
        "ftp://audit.example",
    ],
)
def test_auth_public_origin_rejects_non_origin_urls(origin: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(auth_public_origin=origin)


def test_auth_public_origin_normalizes_default_ports() -> None:
    settings = build_settings(auth_public_origin="HTTPS://AUDIT.EXAMPLE:443")

    assert settings.auth_public_origin == "https://audit.example"


def test_production_auth_public_origin_requires_https() -> None:
    with pytest.raises(ValidationError):
        build_settings(
            app_env="prod",
            auth_jwt_active_kid="authkey01",
            auth_jwt_private_key_file="C:\\run\\secrets\\auth-private.pem",
            auth_jwt_public_keyring_file="C:\\run\\secrets\\auth-public.json",
            auth_public_origin="http://audit.example",
        )


def test_partial_auth_key_profile_is_rejected_in_every_environment() -> None:
    with pytest.raises(ValidationError):
        build_settings(auth_jwt_active_kid="authkey01")


def test_ai_provider_calls_are_disabled_by_default() -> None:
    settings = build_settings()

    assert settings.ai_policy_version == 1
    assert settings.ai_provider_policy_schema_version == 1
    assert settings.ai_provider_calls_enabled is False


def test_exact_policy_versions_parse_from_environment_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = build_settings_from_environment(
        monkeypatch,
        ai_policy_version="1",
        ai_provider_policy_schema_version="1",
    )

    assert type(settings.ai_policy_version) is int
    assert settings.ai_policy_version == 1
    assert type(settings.ai_provider_policy_schema_version) is int
    assert settings.ai_provider_policy_schema_version == 1


def test_exact_runtime_integer_settings_parse_from_environment_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = build_settings_from_environment(
        monkeypatch,
        **{name: str(value) for name, value in EXACT_INTEGER_SETTINGS.items()},
    )

    for name, expected in EXACT_INTEGER_SETTINGS.items():
        value = getattr(settings, name)
        assert type(value) is int
        assert value == expected


@pytest.mark.parametrize("invalid_value", ["05", "+5", "5.0", "true"])
def test_exact_runtime_integer_settings_reject_noncanonical_strings(
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: str,
) -> None:
    with pytest.raises(ValidationError):
        build_settings_from_environment(
            monkeypatch,
            llm_connect_timeout_seconds=invalid_value,
        )


@pytest.mark.parametrize("invalid_version", ["01", "+1", "1.0", "true"])
def test_policy_versions_reject_noncanonical_environment_strings(
    monkeypatch: pytest.MonkeyPatch,
    invalid_version: str,
) -> None:
    with pytest.raises(ValidationError):
        build_settings_from_environment(
            monkeypatch,
            ai_policy_version=invalid_version,
            ai_provider_policy_schema_version="1",
        )


def test_ai_policy_file_is_explicit_and_hidden_from_repr() -> None:
    settings = build_settings()

    assert settings.ai_policy_file == "D:\\synthetic\\ai-policy-v1.json"
    assert settings.ai_policy_file not in repr(settings)


def test_live_ai_provider_calls_require_the_exact_local_profile() -> None:
    settings = build_settings(
        ai_provider_calls_enabled=True,
        llm_base_url="https://api.minimaxi.com/v1",
        llm_extraction_model="MiniMax-M3",
        llm_generation_model="MiniMax-M3",
        llm_fallback_model="MiniMax-M3",
        embedding_base_url=None,
        embedding_api_key=None,
        embedding_model="deterministic-hash-v1",
    )

    assert settings.ai_provider_calls_enabled is True


def test_live_ai_provider_calls_reject_unapproved_target() -> None:
    with pytest.raises(ValidationError):
        build_settings(ai_provider_calls_enabled=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("embedding_base_url", "https://embedding.example/v1"),
        ("embedding_api_key", "test-live-embedding-key"),
        ("embedding_model", "provider-looking-model"),
    ],
)
def test_live_ai_provider_calls_reject_unapproved_embedding_profile(
    field: str,
    value: object,
) -> None:
    profile: dict[str, object] = {
        "ai_provider_calls_enabled": True,
        "llm_base_url": "https://api.minimaxi.com/v1",
        "llm_extraction_model": "MiniMax-M3",
        "llm_generation_model": "MiniMax-M3",
        "llm_fallback_model": "MiniMax-M3",
        "embedding_base_url": None,
        "embedding_api_key": None,
        "embedding_model": "deterministic-hash-v1",
    }
    with pytest.raises(ValidationError):
        build_settings(**(profile | {field: value}))


@pytest.mark.parametrize(
    "field",
    [
        "llm_request_timeout_seconds",
        "llm_max_retries",
        "llm_max_concurrency",
        "embedding_request_timeout_seconds",
    ],
)
def test_legacy_ai_transport_settings_are_recognized_without_conversion(field: str) -> None:
    settings = build_settings(**{field: 7})

    assert getattr(settings, field) == 7
    assert settings.llm_max_attempts_per_generation == 3
    assert settings.llm_max_same_target_attempts == 2
    assert settings.ai_max_provider_attempts_per_operation == 6
    assert field not in settings.model_dump()


def test_legacy_ai_transport_settings_cannot_enable_provider_calls() -> None:
    with pytest.raises(ValidationError):
        build_settings(ai_provider_calls_enabled=True, llm_max_retries=7)


def test_policy_v1_transport_values_are_exact() -> None:
    settings = build_settings()

    assert settings.llm_connect_timeout_seconds == 5
    assert settings.llm_max_attempts_per_generation == 3
    assert settings.llm_max_same_target_attempts == 2
    assert settings.ai_max_provider_attempts_per_operation == 6
    assert settings.ai_max_model_repairs == 2
    assert settings.ai_rag_limits == "2/12/100000/2"
    assert settings.ai_async_generation_limits == "4/30/250000/4"
    assert settings.ai_embedding_limits == "2/30/500000/2"


def test_secret_values_are_masked_in_repr_and_json() -> None:
    settings = build_settings()
    rendered = f"{settings!r}\n{settings.model_dump_json()}"

    for secret in (
        "test-signing-key-with-at-least-32-characters",
        "test-password",
        "test-minio-secret",
        "test-llm-key",
        "test-embedding-key",
        "test-metrics-token",
    ):
        assert secret not in rendered
    assert "**********" in rendered


def test_invalid_secret_error_hides_input() -> None:
    leaked_value = "leaky-secret-value"

    with pytest.raises(ValidationError) as exc_info:
        build_settings(secret_key=leaked_value)

    assert leaked_value not in str(exc_info.value)
    assert leaked_value not in repr(exc_info.value.errors())
    assert leaked_value not in exc_info.value.json()
    assert "secret_key" in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_settings_class_validation_entrypoints_hide_pre_init_input() -> None:
    sentinel = "synthetic-wrong-root-sentinel"
    validators = (
        lambda: Settings.model_validate(sentinel),
        lambda: Settings.model_validate_strings(sentinel),
    )

    for validate in validators:
        with pytest.raises(ValidationError) as exc_info:
            validate()
        rendered = str(exc_info.value) + repr(exc_info.value.errors()) + exc_info.value.json()
        assert sentinel not in rendered


def test_model_validate_json_hides_invalid_document_input() -> None:
    sentinel = "synthetic-json-parse-sentinel"

    with pytest.raises(ValidationError) as exc_info:
        Settings.model_validate_json(f'{{"secret_key":"{sentinel}",')

    rendered = str(exc_info.value) + repr(exc_info.value.errors()) + exc_info.value.json()
    assert sentinel not in rendered


def test_missing_required_configuration_blocks_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    required_environment_names = (
        "SECRET_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "QDRANT_COLLECTION",
        "AI_POLICY_FILE",
        "LLM_API_KEY",
        "LLM_EXTRACTION_MODEL",
        "LLM_GENERATION_MODEL",
        "EMBEDDING_BASE_URL",
        "EMBEDDING_API_KEY",
        "EMBEDDING_MODEL",
        "METRICS_INTERNAL_TOKEN",
    )
    for name in required_environment_names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)

    with pytest.raises(ValidationError):
        create_app()


def test_placeholder_secret_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(llm_api_key="CHANGE_ME")


@pytest.mark.parametrize(
    "field",
    [
        "qdrant_api_key",
        "ocr_api_key",
        "minio_worker_access_key",
        "minio_worker_secret_key",
    ],
)
def test_optional_placeholder_secret_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(**{field: "CHANGE_ME"})


def test_unresolved_qdrant_collection_placeholder_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(qdrant_collection="REPLACE_AFTER_CR_GAP_008")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "not-a-url"),
        ("redis_url", "not-a-url"),
        ("celery_broker_url", "not-a-url"),
        ("celery_result_backend", "not-a-url"),
        ("minio_endpoint", "not-a-url"),
        ("qdrant_url", "not-a-url"),
        ("llm_base_url", "not-a-url"),
        ("embedding_base_url", "not-a-url"),
        ("ocr_base_url", "not-a-url"),
    ],
)
def test_service_urls_require_an_absolute_supported_url(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "postgresql://user:password@postgresql:5432/test"),
        ("redis_url", "http://redis:6379/0"),
        ("minio_endpoint", "ftp://minio:9000"),
    ],
)
def test_service_urls_reject_unsupported_schemes(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(**{field: value})


def test_supported_secure_service_urls_and_encoded_password_are_accepted() -> None:
    database_url = "postgresql+psycopg://test:test%40password@postgresql.example.test:5432/test"
    settings = build_settings(
        database_url=database_url,
        redis_url="rediss://:test%40password@redis.example.test:6379/0",
        celery_broker_url="rediss://:test%40password@redis.example.test:6379/0",
        celery_result_backend="rediss://:test%40password@redis.example.test:6379/1",
        minio_endpoint="https://minio.example.test:9000",
        minio_secure=True,
        qdrant_url="https://qdrant.example.test:6333",
        llm_base_url="https://llm.example.test/v1",
        embedding_base_url="https://embedding.example.test/v1",
    )

    assert settings.database_url.get_secret_value() == database_url
    assert settings.embedding_base_url == "https://embedding.example.test/v1"


@pytest.mark.parametrize(
    "query",
    [
        "host=override-db",
        "hostaddr=127.0.0.2",
        "port=6543",
        "dbname=other_db",
        "service=other_service",
        "servicefile=other_service.conf",
    ],
)
def test_database_url_rejects_query_parameters_that_override_the_target(query: str) -> None:
    database_url = "postgresql+psycopg://test:test-password@validated-db:5432/test?" + query

    with pytest.raises(ValidationError):
        build_settings(database_url=database_url)


def test_database_url_allows_non_target_application_name_query() -> None:
    database_url = (
        "postgresql+psycopg://test:test-password@validated-db:5432/test"
        "?application_name=finaudit-test"
    )

    assert build_settings(database_url=database_url).database_url.get_secret_value() == database_url


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "postgresql+psycopg:///test"),
        ("database_url", "postgresql+psycopg://postgresql:5432"),
        ("redis_url", "redis:///0"),
        ("qdrant_url", "http:///collections"),
        ("llm_base_url", " http://vllm:8000/v1"),
        ("embedding_base_url", "http://embedding:not-a-port/v1"),
        ("embedding_base_url", "http://embed\x07ding:8000/v1"),
        ("embedding_base_url", "http://invalid_host:8000/v1"),
        ("qdrant_url", "http://qdrant.local..:6333"),
        ("qdrant_url", "http://qdrant:0"),
        ("redis_url", "redis://redis:0/0"),
        ("database_url", "postgresql+psycopg://postgresql:0/test"),
        (
            "database_url",
            "postgresql+psycopg://user:first@second@postgresql:5432/test",
        ),
        ("redis_url", "redis://user:first@second@redis:6379/0"),
    ],
)
def test_service_urls_reject_missing_components_or_invalid_syntax(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "database_url",
            "postgresql+psycopg://user:leaky-password@postgresql:not-a-port/test",
        ),
        ("embedding_base_url", "http://leaky-endpoint.invalid:not-a-port/v1"),
    ],
)
def test_invalid_service_url_error_hides_input(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        build_settings(**{field: value})

    assert value not in str(exc_info.value)
    assert value not in repr(exc_info.value.errors())
    assert value not in exc_info.value.json()
    assert field in str(exc_info.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "embedding_base_url",
            "http://operator:synthetic-credential-sentinel@embedding:8000/v1",
        ),
        (
            "qdrant_url",
            "http://qdrant:6333/collections?api_key=synthetic-credential-sentinel",
        ),
        (
            "llm_base_url",
            "http://vllm:8000/v1#synthetic-credential-sentinel",
        ),
    ],
)
def test_http_service_urls_reject_embedded_credentials(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        build_settings(**{field: value})

    assert "synthetic-credential-sentinel" not in str(exc_info.value)
    assert "synthetic-credential-sentinel" not in repr(exc_info.value.errors())
    assert "synthetic-credential-sentinel" not in exc_info.value.json()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://minio:9000/",
        "http://minio:9000/quarantine",
        "http://minio:9000?region=local",
        "http://minio:9000#console",
        "http://operator@minio:9000",
    ],
)
def test_minio_endpoint_must_be_an_origin_without_credentials(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(minio_endpoint=endpoint)


@pytest.mark.parametrize(
    ("endpoint", "secure"),
    [
        ("http://minio:9000", True),
        ("https://minio:9000", False),
    ],
)
def test_minio_secure_must_match_endpoint_scheme(endpoint: str, secure: bool) -> None:
    with pytest.raises(ValidationError):
        build_settings(minio_endpoint=endpoint, minio_secure=secure)


def test_production_minio_requires_https() -> None:
    with pytest.raises(ValidationError):
        build_settings(
            app_env="prod",
            auth_jwt_active_kid="authkey01",
            auth_jwt_private_key_file="C:\\run\\secrets\\auth-private.pem",
            auth_jwt_public_keyring_file="C:\\run\\secrets\\auth-public.json",
            auth_public_origin="https://audit.example",
            minio_endpoint="http://minio:9000",
            minio_secure=False,
        )


def test_connection_urls_remain_secret_values() -> None:
    settings = build_settings()

    for field in (
        "database_url",
        "redis_url",
        "celery_broker_url",
        "celery_result_backend",
    ):
        value = getattr(settings, field)
        assert isinstance(value, SecretStr)
        assert value.get_secret_value() == VALID_SETTINGS[field]


def test_qdrant_vector_size_must_match_embedding_vector_size() -> None:
    with pytest.raises(ValidationError):
        build_settings(qdrant_vector_size=768, embedding_vector_size=1024)


@pytest.mark.parametrize("field", LEGACY_CHUNKING_FIELDS)
@pytest.mark.parametrize("uppercase_input", [False, True])
def test_legacy_chunking_settings_are_rejected_without_value_disclosure(
    field: str,
    uppercase_input: bool,
) -> None:
    sentinel = 987_654_321
    input_name = field.upper() if uppercase_input else field

    with pytest.raises(ValidationError) as exc_info:
        build_settings(**{input_name: sentinel})

    assert str(sentinel) not in str(exc_info.value)
    assert str(sentinel) not in repr(exc_info.value.errors())
    assert str(sentinel) not in exc_info.value.json()


@pytest.mark.parametrize("field", LEGACY_CHUNKING_FIELDS)
def test_legacy_chunking_aliases_cannot_shadow_each_other(field: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(**{field.upper(): None, field: 1})


@pytest.mark.parametrize("field", LEGACY_CHUNKING_FIELDS)
def test_legacy_chunking_environment_variables_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    with pytest.raises(ValidationError):
        build_settings_from_environment(monkeypatch, **{field: 987_654_321})


def test_legacy_chunking_settings_are_excluded_from_serialization() -> None:
    settings = build_settings()

    assert set(LEGACY_CHUNKING_FIELDS).isdisjoint(settings.model_dump())


@pytest.mark.parametrize("field", RUNTIME_IDENTIFIER_FIELDS)
def test_runtime_identifiers_reject_blank_values(field: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(**{field: " "})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("celery_queue_document", " document"),
        ("celery_queue_document", "document "),
        ("celery_queue_document", "doc\x00ument"),
        ("celery_queue_document", "doc\u200bument"),
        ("minio_bucket_originals", " originals"),
        ("minio_bucket_originals", "originals "),
        ("minio_bucket_originals", "orig\x00inals"),
        ("minio_bucket_originals", "orig\u200binals"),
    ],
)
def test_runtime_identifiers_reject_ambiguous_characters(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(**{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"celery_queue_document": " document"},
        {"minio_bucket_originals": " originals"},
        {"celery_queue_document": "shared", "celery_queue_report": "shared"},
        {"minio_bucket_quarantine": "shared", "minio_bucket_originals": "shared"},
    ],
)
def test_invalid_runtime_identifiers_block_environment_startup(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        build_settings_from_environment(monkeypatch, **overrides)


def test_celery_queue_names_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        build_settings(celery_queue_document="shared", celery_queue_report="shared")


@pytest.mark.parametrize(
    ("soft_limit", "hard_limit"),
    [
        (1800, 1800),
        (1801, 1800),
    ],
)
def test_celery_soft_time_limit_must_be_less_than_hard_limit(
    soft_limit: int,
    hard_limit: int,
) -> None:
    with pytest.raises(ValidationError):
        build_settings(
            celery_task_soft_time_limit_seconds=soft_limit,
            celery_task_time_limit_seconds=hard_limit,
        )


def test_minio_bucket_names_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        build_settings(minio_bucket_quarantine="shared", minio_bucket_originals="shared")


@pytest.mark.parametrize(
    "bucket_name",
    [
        "ab",
        "a" * 64,
        "Invalid",
        "invalid_name",
        "-invalid",
        "invalid-",
        "invalid..name",
        "invalid.-name",
        "invalid-.name",
        "192.168.5.4",
        "xn--invalid",
        "sthree-invalid",
        "amzn-s3-demo-invalid",
        "invalid-s3alias",
        "invalid--ol-s3",
        "invalid.mrap",
        "invalid--x-s3",
        "invalid--table-s3",
        "invalid-an",
    ],
)
def test_minio_bucket_names_follow_s3_compatible_rules(bucket_name: str) -> None:
    with pytest.raises(ValidationError):
        build_settings(minio_bucket_quarantine=bucket_name)


def test_minio_bucket_defaults_match_local_profile() -> None:
    settings = build_settings()

    assert tuple(getattr(settings, field) for field in RUNTIME_IDENTIFIER_FIELDS[7:]) == (
        "quarantine",
        "originals",
        "assets",
        "previews",
        "reports",
        "exports",
        "temp",
    )


def test_queue_and_bucket_names_use_independent_namespaces() -> None:
    settings = build_settings(
        celery_queue_document="shared",
        minio_bucket_quarantine="shared",
    )

    assert settings.celery_queue_document == settings.minio_bucket_quarantine == "shared"
