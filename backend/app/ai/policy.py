"""CR-002-R4 contract/offline 范围的不可变 AI Provider Policy v1。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    ModelWrapValidatorHandler,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic.config import ExtraValues
from typing_extensions import Self

from app.core.validation import redact_validation_error

_LOWER_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_POLICY_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_SECRET_SLOT_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
    )

    @staticmethod
    def _validate_entry_options(
        *,
        strict: bool | None,
        extra: ExtraValues | None,
    ) -> None:
        if strict not in (None, True) or extra not in (None, "forbid"):
            raise ValueError("Policy validation options cannot relax strict or extra rules")

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        extra: ExtraValues | None = None,
        from_attributes: bool | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        """只允许 strict + extra-forbid 的 Policy Python 输入边界。"""

        cls._validate_entry_options(strict=strict, extra=extra)
        try:
            return super().model_validate(
                obj,
                strict=True,
                extra="forbid",
                from_attributes=from_attributes,
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
    ) -> Self:
        """拒绝重复 JSON key，并统一移除校验错误中的原始输入。"""

        cls._validate_entry_options(strict=strict, extra=extra)

        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON object key")
                result[key] = value
            return result

        try:
            json.loads(json_data, object_pairs_hook=reject_duplicate_keys)
        except ValueError as error:
            if str(error) == "duplicate JSON object key":
                raise ValueError("duplicate JSON object key") from None

        try:
            return super().model_validate_json(
                json_data,
                strict=True,
                extra="forbid",
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

    @classmethod
    def model_validate_strings(
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        extra: ExtraValues | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        """Policy 不接受会主动把字符串转换为其他 JSON 类型的入口。"""

        raise TypeError("Policy does not support model_validate_strings")

    @model_validator(mode="wrap")
    @classmethod
    def redact_model_validation_errors(
        cls,
        value: Any,
        handler: ModelWrapValidatorHandler[Self],
    ) -> Self:
        try:
            return handler(value)
        except ValidationError as error:
            safe_error = redact_validation_error(
                error,
                allowed_field_names=cls.model_fields,
            )
        raise safe_error


def _require_non_empty(name: str, value: str) -> str:
    if not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _serialize_jcs_number(value: int | float) -> str:
    if isinstance(value, bool):
        raise ValueError("booleans are not JSON numbers")
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ValueError("integers outside the interoperable IEEE-754 range are not supported")
        return str(value)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON numbers are not supported")
    if value == 0:
        return "0"

    rendered = repr(value).lower()
    if "e" not in rendered:
        return rendered[:-2] if rendered.endswith(".0") else rendered

    mantissa, exponent_text = rendered.split("e", 1)
    exponent = int(exponent_text)
    sign = ""
    if mantissa.startswith("-"):
        sign, mantissa = "-", mantissa[1:]
    digits = mantissa.replace(".", "")
    decimal_position = (mantissa.index(".") if "." in mantissa else len(mantissa)) + exponent

    if 1e-6 <= abs(value) < 1e21:
        if decimal_position <= 0:
            return f"{sign}0.{('0' * -decimal_position)}{digits}"
        if decimal_position >= len(digits):
            return f"{sign}{digits}{'0' * (decimal_position - len(digits))}"
        return f"{sign}{digits[:decimal_position]}.{digits[decimal_position:]}"

    normalized_mantissa = mantissa[:-2] if mantissa.endswith(".0") else mantissa
    exponent_sign = "+" if exponent >= 0 else "-"
    return f"{sign}{normalized_mantissa}e{exponent_sign}{abs(exponent)}"


def canonicalize_jcs(value: object) -> bytes:
    """Canonicalize the strict Policy JSON domain using RFC 8785 ordering/number rules."""

    def serialize(item: object) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if isinstance(item, (int, float)):
            return _serialize_jcs_number(item)
        if isinstance(item, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in item):
                raise ValueError("lone Unicode surrogates are not valid I-JSON strings")
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if isinstance(item, Mapping):
            if not all(isinstance(key, str) for key in item):
                raise ValueError("JSON object keys must be strings")
            entries = (
                f"{serialize(key)}:{serialize(item[key])}"
                for key in sorted(item, key=lambda key: key.encode("utf-16-be"))
            )
            return "{" + ",".join(entries) + "}"
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray, memoryview)):
            return "[" + ",".join(serialize(child) for child in item) + "]"
        raise ValueError(f"unsupported JSON value type: {type(item).__name__}")

    return serialize(value).encode("utf-8")


class ProviderProfileV1(_StrictFrozenModel):
    profile_type: Literal["openai-chat-completions-v1", "openai-embeddings-v1"]
    base_url: str
    model_id: str
    allowed_response_model_ids: tuple[str, ...]
    auth_scheme: Literal["bearer"]
    secret_slot: str
    context_window_tokens: int
    tokenizer_id: str
    tokenizer_hash: str
    embedding_dimension: int | None
    pricing_version: str
    billing_mode: Literal["external_usd", "internal_unmetered"]
    input_price_micro_usd_per_million: int
    output_price_micro_usd_per_million: int
    redis_unavailable_mode: Literal["fail_closed", "process_local_restricted"]

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        _require_non_empty("base_url", value)
        if "%" in value or any(character.isspace() for character in value):
            raise ValueError("base_url must be an unambiguous fixed /v1 root")
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            raise ValueError("base_url must be an unambiguous fixed /v1 root") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or port == 0
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path != "/v1"
        ):
            raise ValueError("base_url must be an unambiguous fixed /v1 root")
        return value

    @field_validator("model_id", "tokenizer_id", "pricing_version")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(info.field_name, value)

    @field_validator("allowed_response_model_ids", mode="before")
    @classmethod
    def validate_allowed_models(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("allowed_response_model_ids must be a JSON array")
        normalized = tuple(value)
        if not normalized or any(
            not isinstance(model_id, str) or not model_id.strip() for model_id in normalized
        ):
            raise ValueError("allowed_response_model_ids must contain non-empty strings")
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed_response_model_ids must be unique")
        return normalized

    @field_validator("secret_slot")
    @classmethod
    def validate_secret_slot(cls, value: str) -> str:
        if not _SECRET_SLOT_PATTERN.fullmatch(value):
            raise ValueError("secret_slot must be an environment secret reference")
        return value

    @field_validator("tokenizer_hash")
    @classmethod
    def validate_tokenizer_hash(cls, value: str) -> str:
        if not _LOWER_SHA256_PATTERN.fullmatch(value):
            raise ValueError("tokenizer_hash must be a lowercase SHA-256 hex digest")
        return value

    @field_validator(
        "context_window_tokens",
        "input_price_micro_usd_per_million",
        "output_price_micro_usd_per_million",
    )
    @classmethod
    def validate_non_negative_integer(cls, value: int, info: Any) -> int:
        if value < 0 or value > _MAX_SAFE_INTEGER:
            raise ValueError(f"{info.field_name} must be an interoperable non-negative integer")
        if info.field_name == "context_window_tokens" and value == 0:
            raise ValueError("context_window_tokens must be positive")
        return value

    @field_validator("embedding_dimension")
    @classmethod
    def validate_embedding_dimension(cls, value: int | None) -> int | None:
        if value is not None and (value <= 0 or value > _MAX_SAFE_INTEGER):
            raise ValueError("embedding_dimension must be a positive interoperable integer")
        return value

    @model_validator(mode="after")
    def validate_profile_contract(self) -> ProviderProfileV1:
        is_embedding = self.profile_type == "openai-embeddings-v1"
        if is_embedding != (self.embedding_dimension is not None):
            raise ValueError("embedding_dimension is required only for embedding profiles")
        if self.billing_mode == "internal_unmetered" and (
            self.input_price_micro_usd_per_million != 0
            or self.output_price_micro_usd_per_million != 0
        ):
            raise ValueError("internal_unmetered prices must both be zero")
        if self.billing_mode == "external_usd" and self.redis_unavailable_mode != "fail_closed":
            raise ValueError("external_usd profiles must fail closed when Redis is unavailable")
        if self.billing_mode == "external_usd" and urlsplit(self.base_url).scheme != "https":
            raise ValueError("external_usd profiles must use HTTPS")
        return self


class OperationPolicyV1(_StrictFrozenModel):
    connect_timeout_seconds: int
    deadline_seconds: int
    max_attempts: int
    max_same_target_attempts: int
    max_provider_attempts_per_business_operation: int
    max_model_repairs: int
    max_input_tokens_per_request: int
    max_output_tokens_per_request: int
    max_total_tokens: int
    max_cost_micro_usd: int
    report_use_fallback: bool

    @field_validator("*")
    @classmethod
    def validate_integers(cls, value: Any, info: Any) -> Any:
        if info.field_name == "report_use_fallback":
            return value
        if value < 0 or value > _MAX_SAFE_INTEGER:
            raise ValueError(f"{info.field_name} must be an interoperable non-negative integer")
        return value


class RetryPolicyV1(_StrictFrozenModel):
    backoff_base_seconds: Literal[1]
    backoff_multiplier: Literal[2]
    backoff_max_seconds: Literal[30]
    jitter_ratio: float

    @field_validator(
        "backoff_base_seconds",
        "backoff_multiplier",
        "backoff_max_seconds",
        mode="before",
    )
    @classmethod
    def validate_literal_integer_types(cls, value: object, info: Any) -> object:
        if type(value) is not int:
            raise ValueError(f"{info.field_name} must be a JSON integer")
        return value

    @field_validator("jitter_ratio")
    @classmethod
    def validate_jitter_ratio(cls, value: float) -> float:
        if type(value) is not float or value != 0.2:
            raise ValueError("jitter_ratio must equal the approved Policy v1 value")
        return value


class BreakerPolicyV1(_StrictFrozenModel):
    failures: Literal[5]
    window_seconds: Literal[60]
    open_seconds: Literal[30]
    half_open_probes: Literal[1]

    @field_validator("*", mode="before")
    @classmethod
    def validate_literal_integer_types(cls, value: object, info: Any) -> object:
        if type(value) is not int:
            raise ValueError(f"{info.field_name} must be a JSON integer")
        return value


class RateLimitPoolV1(_StrictFrozenModel):
    concurrency: int
    rpm: int
    tpm: int
    burst: int

    @field_validator("*")
    @classmethod
    def validate_positive_integer(cls, value: int, info: Any) -> int:
        if value <= 0 or value > _MAX_SAFE_INTEGER:
            raise ValueError(f"{info.field_name} must be an interoperable positive integer")
        return value


class RateLimitsV1(_StrictFrozenModel):
    rag: RateLimitPoolV1
    async_generation: RateLimitPoolV1
    embedding: RateLimitPoolV1


class OutboundLimitsV1(_StrictFrozenModel):
    max_request_bytes: Literal[4_194_304]
    max_response_header_bytes: Literal[65_536]
    max_chat_decompressed_bytes: Literal[2_097_152]
    max_embedding_decompressed_bytes: Literal[4_194_304]

    @field_validator("*", mode="before")
    @classmethod
    def validate_literal_integer_types(cls, value: object, info: Any) -> object:
        if type(value) is not int:
            raise ValueError(f"{info.field_name} must be a JSON integer")
        return value


_EXPECTED_OPERATIONS: Mapping[str, Mapping[str, int | bool]] = MappingProxyType(
    {
        "contract_field_extraction": {
            "connect_timeout_seconds": 5,
            "deadline_seconds": 120,
            "max_attempts": 3,
            "max_same_target_attempts": 2,
            "max_provider_attempts_per_business_operation": 6,
            "max_model_repairs": 2,
            "max_input_tokens_per_request": 32_768,
            "max_output_tokens_per_request": 2_500,
            "max_total_tokens": 212_000,
            "max_cost_micro_usd": 500_000,
            "report_use_fallback": False,
        },
        "invoice_field_extraction": {
            "connect_timeout_seconds": 5,
            "deadline_seconds": 60,
            "max_attempts": 3,
            "max_same_target_attempts": 2,
            "max_provider_attempts_per_business_operation": 6,
            "max_model_repairs": 2,
            "max_input_tokens_per_request": 16_384,
            "max_output_tokens_per_request": 2_500,
            "max_total_tokens": 114_000,
            "max_cost_micro_usd": 250_000,
            "report_use_fallback": False,
        },
        "risk_explanation": {
            "connect_timeout_seconds": 5,
            "deadline_seconds": 60,
            "max_attempts": 3,
            "max_same_target_attempts": 2,
            "max_provider_attempts_per_business_operation": 6,
            "max_model_repairs": 2,
            "max_input_tokens_per_request": 16_384,
            "max_output_tokens_per_request": 1_600,
            "max_total_tokens": 108_000,
            "max_cost_micro_usd": 250_000,
            "report_use_fallback": False,
        },
        "rag_answer": {
            "connect_timeout_seconds": 5,
            "deadline_seconds": 90,
            "max_attempts": 3,
            "max_same_target_attempts": 2,
            "max_provider_attempts_per_business_operation": 6,
            "max_model_repairs": 2,
            "max_input_tokens_per_request": 16_384,
            "max_output_tokens_per_request": 1_800,
            "max_total_tokens": 110_000,
            "max_cost_micro_usd": 250_000,
            "report_use_fallback": False,
        },
        "report_draft": {
            "connect_timeout_seconds": 5,
            "deadline_seconds": 90,
            "max_attempts": 2,
            "max_same_target_attempts": 2,
            "max_provider_attempts_per_business_operation": 6,
            "max_model_repairs": 2,
            "max_input_tokens_per_request": 16_384,
            "max_output_tokens_per_request": 3_000,
            "max_total_tokens": 117_000,
            "max_cost_micro_usd": 250_000,
            "report_use_fallback": False,
        },
        "embedding": {
            "connect_timeout_seconds": 5,
            "deadline_seconds": 30,
            "max_attempts": 3,
            "max_same_target_attempts": 3,
            "max_provider_attempts_per_business_operation": 3,
            "max_model_repairs": 0,
            "max_input_tokens_per_request": 16_384,
            "max_output_tokens_per_request": 0,
            "max_total_tokens": 50_000,
            "max_cost_micro_usd": 50_000,
            "report_use_fallback": False,
        },
    }
)


class AiPolicyPayloadV1(_StrictFrozenModel):
    """已冻结字段的 pre-hash payload；最终 policy_hash 投影仍待合同澄清。"""

    policy_version: Literal[1]
    provider_calls_enabled: Literal[False]
    profiles: Mapping[str, ProviderProfileV1]
    operations: Mapping[str, OperationPolicyV1]
    retry: RetryPolicyV1
    breaker: BreakerPolicyV1
    rate_limits: RateLimitsV1
    outbound_limits: OutboundLimitsV1

    @field_validator("policy_version", mode="before")
    @classmethod
    def validate_policy_version_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("policy_version must be a JSON integer")
        return value

    @field_validator("provider_calls_enabled", mode="before")
    @classmethod
    def validate_provider_calls_enabled_type(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("provider_calls_enabled must be a JSON boolean")
        return value

    @field_validator("profiles", "operations")
    @classmethod
    def freeze_mapping(cls, value: Mapping[str, Any], info: Any) -> Mapping[str, Any]:
        if not value:
            raise ValueError(f"{info.field_name} must not be empty")
        if any(not _POLICY_KEY_PATTERN.fullmatch(key) for key in value):
            raise ValueError(f"{info.field_name} keys must be stable lowercase identifiers")
        return MappingProxyType(dict(value))

    @field_serializer("profiles", "operations")
    def serialize_mapping(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return dict(value)

    @model_validator(mode="after")
    def validate_contract_values(self) -> AiPolicyPayloadV1:
        profile_types = {profile.profile_type for profile in self.profiles.values()}
        if profile_types != {"openai-chat-completions-v1", "openai-embeddings-v1"}:
            raise ValueError("profiles must include both approved P0 profile types")
        if set(self.operations) != set(_EXPECTED_OPERATIONS):
            raise ValueError("operations must contain exactly the six approved P0 operations")
        for operation_id, expected in _EXPECTED_OPERATIONS.items():
            actual = self.operations[operation_id].model_dump(mode="json")
            if operation_id == "report_draft" and actual["report_use_fallback"] is True:
                expected = dict(expected) | {"max_attempts": 3, "report_use_fallback": True}
            if actual != expected:
                raise ValueError(f"{operation_id} does not match the approved Policy v1 values")
        expected_limits = {
            "rag": {"concurrency": 2, "rpm": 12, "tpm": 100_000, "burst": 2},
            "async_generation": {
                "concurrency": 4,
                "rpm": 30,
                "tpm": 250_000,
                "burst": 4,
            },
            "embedding": {"concurrency": 2, "rpm": 30, "tpm": 500_000, "burst": 2},
        }
        if self.rate_limits.model_dump(mode="json") != expected_limits:
            raise ValueError("rate_limits do not match the approved Policy v1 values")
        return self

    def canonical_payload(self) -> bytes:
        return canonicalize_jcs(self.model_dump(mode="json"))

    def payload_sha256(self) -> str:
        """用于确定性测试；在自引用投影获批前不得作为最终 policy_hash。"""

        return hashlib.sha256(self.canonical_payload()).hexdigest()
