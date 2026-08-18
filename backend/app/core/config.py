import ipaddress
import os
import re
import unicodedata
import weakref
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    Field,
    ModelWrapValidatorHandler,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.config import ExtraValues
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from app.core.validation import redact_validation_error


def _resolve_repository_env_file() -> Path | None:
    """仅在源码仓库布局中返回默认 dotenv 路径。"""

    config_file = Path(__file__).resolve()
    repository_root = config_file.parents[3]
    expected_config_file = repository_root / "backend" / "app" / "core" / "config.py"
    if config_file != expected_config_file.resolve():
        return None
    return repository_root / "infra" / "env" / ".env"


DEFAULT_REPOSITORY_ENV_FILE = _resolve_repository_env_file()


class AppEnvironment(str, Enum):
    LOCAL = "local"
    TEST = "test"
    PROD = "prod"


DATABASE_TARGET_OVERRIDE_QUERY_KEYS = frozenset(
    {"host", "hostaddr", "port", "dbname", "service", "servicefile"}
)
CELERY_QUEUE_FIELDS = (
    "celery_queue_document",
    "celery_queue_extraction",
    "celery_queue_knowledge",
    "celery_queue_evaluation",
    "celery_queue_audit",
    "celery_queue_report",
    "celery_queue_maintenance",
)
MINIO_BUCKET_FIELDS = (
    "minio_bucket_quarantine",
    "minio_bucket_originals",
    "minio_bucket_assets",
    "minio_bucket_previews",
    "minio_bucket_reports",
    "minio_bucket_exports",
    "minio_bucket_temp",
)
RUNTIME_IDENTIFIER_FIELDS = CELERY_QUEUE_FIELDS + MINIO_BUCKET_FIELDS
MINIO_BUCKET_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z")
MINIO_IPV4_NAME_PATTERN = re.compile(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}\Z")
MINIO_RESERVED_PREFIXES = ("xn--", "sthree-", "amzn-s3-demo-")
MINIO_RESERVED_SUFFIXES = (
    "-s3alias",
    "--ol-s3",
    ".mrap",
    "--x-s3",
    "--table-s3",
    "-an",
)
LEGACY_CHUNKING_INPUT_NAMES = frozenset(
    {
        "chunk_target_min_chars",
        "chunk_target_max_chars",
        "chunk_max_chars",
        "chunk_overlap_chars",
        "chunk_short_threshold_chars",
    }
)
EXACT_INTEGER_SETTINGS = {
    "jwt_access_expire_minutes": 15,
    "jwt_refresh_expire_days": 7,
    "jwt_refresh_remember_expire_days": 30,
    "llm_connect_timeout_seconds": 5,
    "llm_max_attempts_per_generation": 3,
    "llm_max_same_target_attempts": 2,
    "ai_max_provider_attempts_per_operation": 6,
    "ai_max_model_repairs": 2,
    "ai_contract_extraction_deadline_seconds": 120,
    "ai_invoice_extraction_deadline_seconds": 60,
    "ai_risk_explanation_deadline_seconds": 60,
    "ai_rag_answer_deadline_seconds": 90,
    "ai_report_draft_deadline_seconds": 90,
    "ai_embedding_deadline_seconds": 30,
    "ai_retry_backoff_base_seconds": 1,
    "ai_retry_backoff_multiplier": 2,
    "ai_retry_backoff_max_seconds": 30,
    "ai_breaker_failures": 5,
    "ai_breaker_window_seconds": 60,
    "ai_breaker_open_seconds": 30,
    "ai_breaker_half_open_probes": 1,
    "ai_max_request_bytes": 4_194_304,
    "ai_max_response_header_bytes": 65_536,
    "ai_max_chat_decompressed_bytes": 2_097_152,
    "ai_max_embedding_decompressed_bytes": 4_194_304,
}


def _validate_url_text(value: str) -> None:
    if (
        not value
        or "\\" in value
        or any(
            character.isspace() or unicodedata.category(character).startswith("C")
            for character in value
        )
    ):
        raise ValueError("服务地址格式无效")


def _validate_runtime_identifier(value: str) -> str:
    if not value or any(
        character.isspace() or unicodedata.category(character).startswith("C")
        for character in value
    ):
        raise ValueError("运行标识符格式无效")
    return value


def _validate_minio_bucket_name(value: str) -> str:
    if (
        MINIO_BUCKET_NAME_PATTERN.fullmatch(value) is None
        or MINIO_IPV4_NAME_PATTERN.fullmatch(value) is not None
        or any(sequence in value for sequence in ("..", ".-", "-."))
        or value.startswith(MINIO_RESERVED_PREFIXES)
        or value.endswith(MINIO_RESERVED_SUFFIXES)
    ):
        raise ValueError("MinIO Bucket 名称不符合 S3 兼容规则")
    return value


def _validate_hostname(hostname: str | None) -> None:
    if not hostname:
        raise ValueError("服务地址格式无效")
    try:
        hostname.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("服务地址格式无效") from None

    try:
        ipaddress.ip_address(hostname)
        return
    except ValueError:
        if ":" in hostname or all(
            character.isdigit() or character == "." for character in hostname
        ):
            raise ValueError("服务地址格式无效") from None

    normalized = hostname[:-1] if hostname.endswith(".") else hostname
    labels = normalized.split(".")
    if not normalized or len(normalized) > 253:
        raise ValueError("服务地址格式无效")
    for label in labels:
        if (
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or any(not (character.isalnum() or character == "-") for character in label)
        ):
            raise ValueError("服务地址格式无效")


def _validate_service_url(
    value: str,
    allowed_schemes: set[str],
    *,
    allow_userinfo: bool = True,
    allow_query: bool = True,
) -> None:
    _validate_url_text(value)
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("服务地址格式无效") from None
    if parsed.scheme.lower() not in allowed_schemes:
        raise ValueError("服务地址格式无效")
    _validate_hostname(hostname)
    if port == 0:
        raise ValueError("服务地址格式无效")
    if parsed.netloc.count("@") > 1:
        raise ValueError("服务地址格式无效")
    if not allow_userinfo and (parsed.username is not None or parsed.password is not None):
        raise ValueError("服务地址格式无效")
    if not allow_query and "?" in value:
        raise ValueError("服务地址格式无效")
    if "#" in value:
        raise ValueError("服务地址格式无效")


def canonicalize_http_origin(value: str) -> str:
    """Validate and return an HTTP(S) origin without its default port."""

    _validate_service_url(
        value,
        {"http", "https"},
        allow_userinfo=False,
        allow_query=False,
    )
    parsed = urlsplit(value)
    if parsed.path:
        raise ValueError("AUTH_PUBLIC_ORIGIN must not contain a path")
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if hostname is None:  # pragma: no cover - guarded by _validate_service_url
        raise ValueError("AUTH_PUBLIC_ORIGIN is invalid")
    host = f"[{hostname.lower()}]" if ":" in hostname else hostname.lower()
    port = parsed.port
    authority = (
        host
        if port is None or (scheme, port) in {("http", 80), ("https", 443)}
        else f"{host}:{port}"
    )
    return f"{scheme}://{authority}"


def parse_database_url(value: str) -> URL:
    """解析 PostgreSQL URL，并禁止查询参数覆盖已校验的连接目标。"""

    _validate_url_text(value)
    if "#" in value:
        raise ValueError("服务地址格式无效")
    try:
        parsed = make_url(value)
        port = parsed.port
    except (ArgumentError, ValueError):
        raise ValueError("服务地址格式无效") from None

    authority = value.split("://", 1)[-1].split("/", 1)[0]
    if parsed.drivername != "postgresql+psycopg" or authority.count("@") > 1 or not parsed.database:
        raise ValueError("服务地址格式无效")
    if DATABASE_TARGET_OVERRIDE_QUERY_KEYS.intersection(key.casefold() for key in parsed.query):
        raise ValueError("服务地址格式无效")
    _validate_hostname(parsed.host)
    if port == 0:
        raise ValueError("服务地址格式无效")
    return parsed


_SettingsFingerprint = tuple[tuple[str, type[object], object], ...]
_ValidatedSettingsRecord = tuple[weakref.ReferenceType[object], _SettingsFingerprint]
_VALIDATED_SETTINGS_INSTANCES: dict[int, _ValidatedSettingsRecord] = {}


def _settings_fingerprint(value: object) -> _SettingsFingerprint | None:
    fields = getattr(type(value), "model_fields", None)
    if not isinstance(fields, dict):
        return None

    fingerprint: list[tuple[str, type[object], object]] = []
    for field_name in fields:
        try:
            field_value = object.__getattribute__(value, field_name)
        except AttributeError:
            return None
        if isinstance(field_value, SecretStr):
            fingerprint.append((field_name, SecretStr, id(field_value)))
        elif isinstance(field_value, Enum) or type(field_value) in {
            str,
            int,
            float,
            bool,
            type(None),
        }:
            fingerprint.append((field_name, type(field_value), field_value))
        else:
            return None
    return tuple(fingerprint)


def _register_validated_settings(value: object) -> None:
    fingerprint = _settings_fingerprint(value)
    if fingerprint is None:
        raise TypeError("Settings contain an unsupported field type")
    owner_id = id(value)

    def remove_if_owner(owner_ref: weakref.ReferenceType[object]) -> None:
        record = _VALIDATED_SETTINGS_INSTANCES.get(owner_id)
        if record is not None and record[0] is owner_ref:
            _VALIDATED_SETTINGS_INSTANCES.pop(owner_id, None)

    owner_ref = weakref.ref(value, remove_if_owner)
    _VALIDATED_SETTINGS_INSTANCES[owner_id] = (owner_ref, fingerprint)


def _is_validated_settings_instance(value: object) -> bool:
    record = _VALIDATED_SETTINGS_INSTANCES.get(id(value))
    if record is None or record[0]() is not value:
        return False
    try:
        return _settings_fingerprint(value) == record[1]
    except (AttributeError, TypeError, ValueError):
        return False


class Settings(BaseSettings):
    """Backend/Worker 共享配置 Schema；源码运行时默认读取仓库 dotenv。"""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=DEFAULT_REPOSITORY_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        env_prefix="",
        extra="ignore",
        hide_input_in_errors=True,
        revalidate_instances="always",
        secrets_dir=os.environ.get("FINAUDIT_SECRETS_DIR") or None,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """让进程环境与运行时 Secret 始终优先于仓库 dotenv。"""

        return init_settings, env_settings, file_secret_settings, dotenv_settings

    @classmethod
    def model_validate_json(
        cls,
        json_data: str | bytes | bytearray,
        *,
        strict: bool | None = None,
        extra: ExtraValues | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> "Settings":
        """通过可脱敏边界解析 JSON；调用方不得改用 TypeAdapter.validate_json。"""

        try:
            return super().model_validate_json(
                json_data,
                strict=strict,
                extra=extra,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            )
        except ValidationError as error:
            safe_error = redact_validation_error(
                error,
                allowed_field_names=cls.model_fields,
            )
        raise safe_error

    app_name: str = "FinAudit Agent"
    app_env: AppEnvironment = AppEnvironment.LOCAL
    app_version: str = "0.1.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    timezone: Literal["UTC"] = "UTC"
    secret_key: SecretStr
    jwt_access_expire_minutes: Literal[15] = 15
    jwt_refresh_expire_days: Literal[7] = 7
    jwt_refresh_remember_expire_days: Literal[30] = 30
    auth_jwt_active_kid: str | None = None
    auth_jwt_private_key_file: str | None = Field(default=None, repr=False)
    auth_jwt_public_keyring_file: str | None = Field(default=None, repr=False)
    auth_public_origin: str | None = None

    api_prefix: Literal["/api/v1"] = "/api/v1"
    cors_allowed_origins: str = "http://localhost"
    max_upload_size_mb: int = Field(default=50, gt=0)
    max_batch_file_count: int = Field(default=20, gt=0, le=100)

    database_url: SecretStr
    db_pool_size: int = Field(default=10, gt=0)
    db_max_overflow: int = Field(default=20, ge=0)

    redis_url: SecretStr
    celery_broker_url: SecretStr
    celery_result_backend: SecretStr
    celery_task_time_limit_seconds: int = Field(default=1800, gt=0)
    celery_task_soft_time_limit_seconds: int = Field(default=1700, gt=0)
    celery_queue_document: str = "document"
    celery_queue_extraction: str = "extraction"
    celery_queue_knowledge: str = "knowledge"
    celery_queue_evaluation: str = "evaluation"
    celery_queue_audit: str = "audit"
    celery_queue_report: str = "report"
    celery_queue_maintenance: str = "maintenance"

    minio_endpoint: str = "http://minio:9000"
    minio_access_key: SecretStr
    minio_secret_key: SecretStr
    minio_worker_access_key: SecretStr | None = None
    minio_worker_secret_key: SecretStr | None = None
    minio_secure: bool = False
    minio_bucket_quarantine: str = "quarantine"
    minio_bucket_originals: str = "originals"
    minio_bucket_assets: str = "assets"
    minio_bucket_previews: str = "previews"
    minio_bucket_reports: str = "reports"
    minio_bucket_exports: str = "exports"
    minio_bucket_temp: str = "temp"
    signed_url_expire_seconds: int = Field(default=300, gt=0)

    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str
    qdrant_vector_size: int = Field(default=1024, gt=0)
    qdrant_distance: Literal["Cosine", "Dot", "Euclid", "Manhattan"] = "Cosine"

    ai_policy_version: Literal[1] = 1
    ai_provider_calls_enabled: bool = False
    ai_provider_policy_schema_version: Literal[1] = 1
    ai_policy_file: str = Field(repr=False)

    llm_base_url: str = "http://vllm:8000/v1"
    llm_api_key: SecretStr
    llm_extraction_model: str
    llm_generation_model: str
    llm_fallback_model: str | None = None
    llm_connect_timeout_seconds: Literal[5] = 5
    llm_max_attempts_per_generation: Literal[3] = 3
    llm_max_same_target_attempts: Literal[2] = 2
    ai_max_provider_attempts_per_operation: Literal[6] = 6
    ai_max_model_repairs: Literal[2] = 2
    llm_report_draft_use_fallback: bool = False

    ai_contract_extraction_deadline_seconds: Literal[120] = 120
    ai_invoice_extraction_deadline_seconds: Literal[60] = 60
    ai_risk_explanation_deadline_seconds: Literal[60] = 60
    ai_rag_answer_deadline_seconds: Literal[90] = 90
    ai_report_draft_deadline_seconds: Literal[90] = 90
    ai_embedding_deadline_seconds: Literal[30] = 30

    ai_retry_backoff_base_seconds: Literal[1] = 1
    ai_retry_backoff_multiplier: Literal[2] = 2
    ai_retry_backoff_max_seconds: Literal[30] = 30
    ai_retry_jitter_ratio: float = 0.2
    ai_breaker_failures: Literal[5] = 5
    ai_breaker_window_seconds: Literal[60] = 60
    ai_breaker_open_seconds: Literal[30] = 30
    ai_breaker_half_open_probes: Literal[1] = 1

    ai_rag_limits: Literal["2/12/100000/2"] = "2/12/100000/2"
    ai_async_generation_limits: Literal["4/30/250000/4"] = "4/30/250000/4"
    ai_embedding_limits: Literal["2/30/500000/2"] = "2/30/500000/2"

    ai_max_request_bytes: Literal[4_194_304] = 4_194_304
    ai_max_response_header_bytes: Literal[65_536] = 65_536
    ai_max_chat_decompressed_bytes: Literal[2_097_152] = 2_097_152
    ai_max_embedding_decompressed_bytes: Literal[4_194_304] = 4_194_304

    # 只识别旧配置以阻止真实调用迁移；不得映射、记录或序列化为逐调用 Policy。
    llm_request_timeout_seconds: float | None = Field(default=None, exclude=True, repr=False)
    llm_max_retries: int | None = Field(default=None, exclude=True, repr=False)
    llm_max_concurrency: int | None = Field(default=None, exclude=True, repr=False)

    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_model: str = "deterministic-hash-v1"
    embedding_vector_size: int = Field(default=1024, gt=0)
    embedding_batch_size: int = Field(default=32, gt=0)
    embedding_request_timeout_seconds: float | None = Field(
        default=None,
        exclude=True,
        repr=False,
    )

    ocr_provider: Literal["not_configured", "tesseract_cli"] = "not_configured"
    ocr_base_url: str | None = None
    ocr_api_key: SecretStr | None = None
    ocr_tesseract_executable: str | None = None
    ocr_tesseract_version: str | None = None
    ocr_pdftoppm_executable: str | None = None
    ocr_languages: str = "chi_sim+eng"
    ocr_request_timeout_seconds: float = Field(default=120, gt=0)
    ocr_max_retries: int = Field(default=1, ge=0)

    scanner_provider: Literal["not_configured", "clamav_instream"] = "not_configured"
    scanner_host: str | None = None
    scanner_port: int = Field(default=3310, gt=0, le=65535)
    scanner_connect_timeout_seconds: float = Field(default=5, gt=0)
    scanner_read_timeout_seconds: float = Field(default=120, gt=0)
    scanner_max_stream_bytes: int = Field(default=50 * 1024 * 1024, gt=0)

    rag_top_k: int = Field(default=5, gt=0)
    rag_score_threshold: float | None = Field(default=None, ge=0, le=1)
    rag_max_context_chunks: int = Field(default=5, gt=0)
    # 仅识别旧环境变量并在启动时拒绝；组织级分块配置只能由 KB-004 发布。
    chunk_target_min_chars: int | None = Field(default=None, exclude=True, repr=False)
    chunk_target_max_chars: int | None = Field(default=None, exclude=True, repr=False)
    chunk_max_chars: int | None = Field(default=None, exclude=True, repr=False)
    chunk_overlap_chars: int | None = Field(default=None, exclude=True, repr=False)
    chunk_short_threshold_chars: int | None = Field(default=None, exclude=True, repr=False)

    metrics_enabled: bool = True
    metrics_internal_token: SecretStr
    enable_local_vllm: bool = False
    enable_neo4j: bool = False
    enable_langfuse: bool = False
    enable_prometheus_stack: bool = False
    vllm_image_tag: str | None = None
    vllm_model_path_or_id: str | None = None
    vllm_max_model_len: int | None = Field(default=None, gt=0)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_chunking_inputs(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and any(
            isinstance(key, str)
            and key.casefold() in LEGACY_CHUNKING_INPUT_NAMES
            and candidate is not None
            for key, candidate in value.items()
        ):
            raise ValueError("CHUNK_* 环境变量不得定义组织级分块配置")
        return value

    @model_validator(mode="wrap")
    @classmethod
    def redact_model_validation_errors(
        cls,
        value: Any,
        handler: ModelWrapValidatorHandler["Settings"],
    ) -> "Settings":
        try:
            return handler(value)
        except ValidationError as error:
            safe_error = redact_validation_error(
                error,
                allowed_field_names=cls.model_fields,
            )
        raise safe_error

    @field_validator(
        "secret_key",
        "database_url",
        "redis_url",
        "celery_broker_url",
        "celery_result_backend",
        "minio_access_key",
        "minio_secret_key",
        "minio_worker_access_key",
        "minio_worker_secret_key",
        "qdrant_api_key",
        "llm_api_key",
        "embedding_api_key",
        "ocr_api_key",
        "metrics_internal_token",
    )
    @classmethod
    def reject_placeholder_secrets(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw_value = value.get_secret_value().strip()
        if (
            not raw_value
            or "CHANGE_ME" in raw_value.upper()
            or raw_value.upper().startswith("REPLACE_")
        ):
            raise ValueError("敏感配置不能为空或使用占位符")
        return value

    @field_validator(
        "ai_policy_version",
        "ai_provider_policy_schema_version",
        mode="before",
    )
    @classmethod
    def parse_exact_policy_version(cls, value: object) -> int:
        if type(value) is str and value == "1":
            return 1
        if type(value) is not int or value != 1:
            raise ValueError("AI Policy version must equal the approved integer value")
        return value

    @field_validator(*EXACT_INTEGER_SETTINGS, mode="before")
    @classmethod
    def parse_exact_integer_setting(cls, value: object, info: ValidationInfo) -> int:
        field_name = info.field_name
        if field_name is None or field_name not in EXACT_INTEGER_SETTINGS:
            raise ValueError("runtime integer setting is not registered")
        expected = EXACT_INTEGER_SETTINGS[field_name]
        if type(value) is str and value == str(expected):
            return expected
        if type(value) is int and value == expected:
            return expected
        raise ValueError("runtime integer setting does not match the approved value")

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key_length(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("SECRET_KEY 至少需要 32 个字符")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        parse_database_url(value.get_secret_value())
        return value

    @field_validator("redis_url", "celery_broker_url", "celery_result_backend")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        _validate_service_url(value.get_secret_value(), {"redis", "rediss"})
        return value

    @field_validator(
        "qdrant_url",
        "llm_base_url",
        "embedding_base_url",
        "ocr_base_url",
    )
    @classmethod
    def validate_http_url(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_service_url(
                value,
                {"http", "https"},
                allow_userinfo=False,
                allow_query=False,
            )
        return value

    @field_validator("embedding_base_url", "embedding_model", mode="before")
    @classmethod
    def normalize_disabled_embedding_placeholders(cls, value: object) -> object:
        if isinstance(value, str) and value.upper().startswith("REPLACE_"):
            return (
                None
                if "URL" in value.upper() or "ENDPOINT" in value.upper()
                else ("deterministic-hash-v1")
            )
        return value

    @field_validator("minio_endpoint")
    @classmethod
    def validate_minio_endpoint(cls, value: str) -> str:
        _validate_service_url(
            value,
            {"http", "https"},
            allow_userinfo=False,
            allow_query=False,
        )
        if urlsplit(value).path:
            raise ValueError("MINIO_ENDPOINT 不得包含路径")
        return value

    @field_validator("scanner_host")
    @classmethod
    def validate_scanner_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _validate_hostname(value)
        return value

    @field_validator("ocr_tesseract_executable", "ocr_pdftoppm_executable")
    @classmethod
    def validate_ocr_executable(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not value
            or value != value.strip()
            or len(value) > 1000
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("OCR executable 路径无效")
        return value

    @field_validator("ocr_languages")
    @classmethod
    def validate_ocr_languages(cls, value: str) -> str:
        parts = value.split("+")
        if not parts or any(
            not part
            or len(part) > 32
            or any(
                not (character.isascii() and (character.isalnum() or character == "_"))
                for character in part
            )
            for part in parts
        ):
            raise ValueError("OCR language 列表无效")
        return value

    @field_validator("ocr_tesseract_version")
    @classmethod
    def validate_ocr_tesseract_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not 1 <= len(value) <= 100
            or value != value.strip()
            or any(
                not (character.isascii() and (character.isalnum() or character in ".-_"))
                for character in value
            )
        ):
            raise ValueError("OCR Tesseract version 无效")
        return value

    @field_validator(*CELERY_QUEUE_FIELDS)
    @classmethod
    def validate_runtime_identifier(cls, value: str) -> str:
        return _validate_runtime_identifier(value)

    @field_validator(*MINIO_BUCKET_FIELDS)
    @classmethod
    def validate_minio_bucket_name(cls, value: str) -> str:
        return _validate_minio_bucket_name(value)

    @field_validator("auth_jwt_active_kid")
    @classmethod
    def validate_auth_jwt_kid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not 8 <= len(value) <= 64 or any(
            not (character.isascii() and (character.isalnum() or character in "_-"))
            for character in value
        ):
            raise ValueError("AUTH_JWT_ACTIVE_KID 格式无效")
        return value

    @field_validator("auth_public_origin")
    @classmethod
    def validate_auth_public_origin(cls, value: str | None) -> str | None:
        return None if value is None else canonicalize_http_origin(value)

    @field_validator(
        "llm_extraction_model",
        "llm_generation_model",
        "qdrant_collection",
    )
    @classmethod
    def reject_required_placeholders(cls, value: str) -> str:
        if not value.strip() or value.upper().startswith("REPLACE_"):
            raise ValueError("必需配置不能为空或使用占位符")
        return value

    @model_validator(mode="after")
    def validate_cross_field_constraints(self) -> "Settings":
        auth_key_values = (
            self.auth_jwt_active_kid,
            self.auth_jwt_private_key_file,
            self.auth_jwt_public_keyring_file,
        )
        if any(value is not None for value in auth_key_values) and any(
            value is None for value in auth_key_values
        ):
            raise ValueError("Auth JWT key Profile 必须完整配置")
        if self.app_env is AppEnvironment.PROD and any(value is None for value in auth_key_values):
            raise ValueError("production 必须配置完整 Auth JWT key Profile")
        if self.app_env is AppEnvironment.PROD and self.auth_public_origin is None:
            raise ValueError("production 必须配置 AUTH_PUBLIC_ORIGIN")
        minio_scheme = urlsplit(self.minio_endpoint).scheme.lower()
        if self.minio_secure != (minio_scheme == "https"):
            raise ValueError("MINIO_SECURE 必须与 MINIO_ENDPOINT scheme 一致")
        if self.app_env is AppEnvironment.PROD and minio_scheme != "https":
            raise ValueError("production MinIO 必须使用 HTTPS")
        worker_minio_credentials = (
            self.minio_worker_access_key,
            self.minio_worker_secret_key,
        )
        if any(value is not None for value in worker_minio_credentials) and any(
            value is None for value in worker_minio_credentials
        ):
            raise ValueError("MinIO Worker 身份必须同时配置 access key 和 secret key")
        legacy_ai_transport_configured = any(
            value is not None
            for value in (
                self.llm_request_timeout_seconds,
                self.llm_max_retries,
                self.llm_max_concurrency,
                self.embedding_request_timeout_seconds,
            )
        )
        if self.ai_provider_calls_enabled:
            if legacy_ai_transport_configured:
                raise ValueError(
                    "legacy AI timeout/retry/concurrency settings cannot enable Provider calls"
                )
            if self.app_env not in {AppEnvironment.LOCAL, AppEnvironment.TEST}:
                raise ValueError("AI Provider calls are only approved for local or test")
            if (
                self.llm_base_url != "https://api.minimaxi.com/v1"
                or self.llm_extraction_model != "MiniMax-M3"
                or self.llm_generation_model != "MiniMax-M3"
                or self.llm_fallback_model not in {None, "MiniMax-M3"}
            ):
                raise ValueError("AI Provider settings do not match the approved live profile")
            if (
                self.embedding_base_url != "https://dashscope.aliyuncs.com/compatible-mode/v1"
                or self.embedding_api_key is None
                or self.embedding_model != "qwen3.7-text-embedding"
                or self.embedding_vector_size != 1_024
                or self.embedding_batch_size != 20
            ):
                raise ValueError("AI Embedding settings do not match the approved live profile")
        if self.ai_retry_jitter_ratio != 0.2:
            raise ValueError("AI retry jitter ratio must equal the approved Policy v1 value")
        legacy_chunking_configured = any(
            value is not None
            for value in (
                self.chunk_target_min_chars,
                self.chunk_target_max_chars,
                self.chunk_max_chars,
                self.chunk_overlap_chars,
                self.chunk_short_threshold_chars,
            )
        )
        if legacy_chunking_configured:
            raise ValueError("CHUNK_* 环境变量不得定义组织级分块配置")
        if self.celery_task_soft_time_limit_seconds >= self.celery_task_time_limit_seconds:
            raise ValueError("Celery 软超时必须小于硬超时")
        queue_names = tuple(getattr(self, field) for field in CELERY_QUEUE_FIELDS)
        if len(set(queue_names)) != len(queue_names):
            raise ValueError("Celery 队列名称不得重复")
        bucket_names = tuple(getattr(self, field) for field in MINIO_BUCKET_FIELDS)
        if len(set(bucket_names)) != len(bucket_names):
            raise ValueError("MinIO Bucket 名称不得重复")
        if self.qdrant_vector_size != self.embedding_vector_size:
            raise ValueError("Qdrant 向量维度必须与 Embedding 向量维度一致")
        tesseract_profile = (
            self.ocr_tesseract_executable,
            self.ocr_tesseract_version,
        )
        if any(value is not None for value in tesseract_profile) and any(
            value is None for value in tesseract_profile
        ):
            raise ValueError("Tesseract OCR Profile 必须同时配置 executable 和 version")
        if self.ocr_provider == "tesseract_cli" and any(
            value is None for value in tesseract_profile
        ):
            raise ValueError("tesseract_cli 必须配置完整 Tesseract OCR Profile")
        if self.ocr_provider == "not_configured" and any(
            value is not None for value in tesseract_profile
        ):
            raise ValueError("OCR 未启用时不得配置 Tesseract OCR Profile")
        if self.ocr_base_url is not None or self.ocr_api_key is not None:
            raise ValueError("HTTP OCR Provider 协议尚未批准，不得配置端点或密钥")
        if self.scanner_provider == "clamav_instream" and not self.scanner_host:
            raise ValueError("ClamAV INSTREAM 必须配置 SCANNER_HOST")
        if self.scanner_provider == "not_configured" and self.app_env is AppEnvironment.PROD:
            raise ValueError("production 必须配置已批准的恶意文件 Scanner")
        if self.enable_local_vllm and (
            not self.vllm_image_tag
            or not self.vllm_model_path_or_id
            or self.vllm_max_model_len is None
            or self.vllm_image_tag.upper().startswith("REPLACE_")
            or self.vllm_model_path_or_id.upper().startswith("REPLACE_")
        ):
            raise ValueError("启用本地 vLLM 时必须配置 vLLM Profile 参数")
        _register_validated_settings(self)
        return self
