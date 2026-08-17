"""AI Gateway 的 provider-neutral 内存契约。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable


def _require_non_empty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def _require_positive_finite(name: str, value: float) -> None:
    if not _is_finite_number(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")


def _require_non_negative_finite(name: str, value: float) -> None:
    if not _is_finite_number(value) or value < 0:
        raise ValueError(f"{name} must be a non-negative finite number")


def _validate_optional_usage(name: str, value: int | None) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError(f"{name} must be a non-negative integer or None")


def _validate_optional_sha256(name: str, value: str | None) -> None:
    if value is not None and (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest or None")


@dataclass(frozen=True, slots=True)
class TransportPolicy:
    """max_attempts 是调用方注入的总调用上限；GAP-022 关闭前不映射 max_retries。"""

    connect_timeout_seconds: float
    read_timeout_seconds: float
    total_timeout_seconds: float
    max_attempts: int

    def __post_init__(self) -> None:
        _require_positive_finite("connect_timeout_seconds", self.connect_timeout_seconds)
        _require_positive_finite("read_timeout_seconds", self.read_timeout_seconds)
        _require_positive_finite("total_timeout_seconds", self.total_timeout_seconds)
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts <= 0
        ):
            raise ValueError("max_attempts must be a positive integer")


@dataclass(frozen=True, slots=True)
class ModelTarget:
    adapter_id: str
    model_id: str

    def __post_init__(self) -> None:
        _require_non_empty("adapter_id", self.adapter_id)
        _require_non_empty("model_id", self.model_id)


@dataclass(frozen=True, slots=True)
class ModelRoute:
    purpose: str
    candidates: tuple[ModelTarget, ...]

    def __post_init__(self) -> None:
        # purpose 保持开放字符串，避免在基线裁决前冻结业务场景集合或 transport 策略。
        _require_non_empty("purpose", self.purpose)
        try:
            candidates = tuple(self.candidates)
        except TypeError:
            raise ValueError("candidates must be an iterable of ModelTarget") from None
        if not candidates:
            raise ValueError("candidates must not be empty")
        if not all(isinstance(candidate, ModelTarget) for candidate in candidates):
            raise ValueError("candidates must contain only ModelTarget")
        if len(set(candidates)) != len(candidates):
            raise ValueError("candidates must be unique")
        object.__setattr__(self, "candidates", candidates)


@dataclass(frozen=True, slots=True)
class LlmGenerationParameters:
    """一次非流式 Chat Completions 调用的显式采样参数。"""

    temperature: float
    top_p: float
    max_tokens: int

    def __post_init__(self) -> None:
        if not _is_finite_number(self.temperature) or not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be a finite number between 0 and 2")
        if not _is_finite_number(self.top_p) or not 0 < self.top_p <= 1:
            raise ValueError("top_p must be a finite number between 0 and 1")
        if (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens <= 0
        ):
            raise ValueError("max_tokens must be a positive integer")


@dataclass(frozen=True, slots=True)
class LlmRequest:
    trace_id: str
    system_instruction: str
    user_content: str
    parameters: LlmGenerationParameters | None = None

    def __post_init__(self) -> None:
        _require_non_empty("trace_id", self.trace_id)
        _require_non_empty("system_instruction", self.system_instruction)
        _require_non_empty("user_content", self.user_content)
        if self.parameters is not None and not isinstance(self.parameters, LlmGenerationParameters):
            raise ValueError("parameters must be LlmGenerationParameters")


@dataclass(frozen=True, slots=True)
class LlmResult:
    trace_id: str
    target: ModelTarget
    output_text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    response_body_sha256: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty("trace_id", self.trace_id)
        if not isinstance(self.target, ModelTarget):
            raise ValueError("target must be a ModelTarget")
        if not isinstance(self.output_text, str):
            raise ValueError("output_text must be a string")
        _validate_optional_usage("input_tokens", self.input_tokens)
        _validate_optional_usage("output_tokens", self.output_tokens)
        _validate_optional_sha256("response_body_sha256", self.response_body_sha256)


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    trace_id: str
    input_texts: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_non_empty("trace_id", self.trace_id)
        input_texts_value: object = self.input_texts
        if isinstance(input_texts_value, (str, bytes, bytearray, memoryview)) or not isinstance(
            input_texts_value, Sequence
        ):
            raise ValueError("input_texts must be an ordered non-empty string batch")
        input_texts = tuple(input_texts_value)
        if not input_texts or any(
            not isinstance(value, str) or not value.strip() for value in input_texts
        ):
            raise ValueError("input_texts must be an ordered non-empty string batch")
        object.__setattr__(self, "input_texts", input_texts)


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    trace_id: str
    target: ModelTarget
    vectors: tuple[tuple[float, ...], ...]
    input_tokens: int | None = None
    response_body_sha256: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty("trace_id", self.trace_id)
        if not isinstance(self.target, ModelTarget):
            raise ValueError("target must be a ModelTarget")
        vectors_value: object = self.vectors
        if isinstance(vectors_value, (str, bytes, bytearray, memoryview)) or not isinstance(
            vectors_value, Sequence
        ):
            raise ValueError("vectors must be an ordered non-empty finite-number batch")
        vectors = tuple(vectors_value)
        if not vectors:
            raise ValueError("vectors must be an ordered non-empty finite-number batch")

        normalized_vectors: list[tuple[float, ...]] = []
        for vector_value in vectors:
            if isinstance(vector_value, (str, bytes, bytearray, memoryview)) or not isinstance(
                vector_value, Sequence
            ):
                raise ValueError("vectors must be an ordered non-empty finite-number batch")
            vector = tuple(vector_value)
            if not vector or not all(_is_finite_number(value) for value in vector):
                raise ValueError("vectors must be an ordered non-empty finite-number batch")
            normalized_vectors.append(tuple(float(value) for value in vector))
        object.__setattr__(self, "vectors", tuple(normalized_vectors))
        _validate_optional_usage("input_tokens", self.input_tokens)
        _validate_optional_sha256("response_body_sha256", self.response_body_sha256)


class ErrorDisposition(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    CONDITIONAL = "conditional"
    UNRESOLVED = "unresolved"


class ExternalErrorCategory(str, Enum):
    CONNECTION_ERROR = "connection_error"
    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    CONTEXT_LIMIT = "context_limit"
    INVALID_RESPONSE = "invalid_response"
    CONTENT_REJECTED = "content_rejected"
    PROVIDER_CONFIGURATION_ERROR = "provider_configuration_error"
    OUTPUT_TRUNCATED = "output_truncated"


_ERROR_DISPOSITIONS: Final[Mapping[ExternalErrorCategory, ErrorDisposition]] = MappingProxyType(
    {
        ExternalErrorCategory.CONNECTION_ERROR: ErrorDisposition.TRANSIENT,
        ExternalErrorCategory.CONNECT_TIMEOUT: ErrorDisposition.TRANSIENT,
        ExternalErrorCategory.READ_TIMEOUT: ErrorDisposition.TRANSIENT,
        ExternalErrorCategory.RATE_LIMITED: ErrorDisposition.TRANSIENT,
        ExternalErrorCategory.CLIENT_ERROR: ErrorDisposition.PERMANENT,
        ExternalErrorCategory.CONTEXT_LIMIT: ErrorDisposition.PERMANENT,
        ExternalErrorCategory.INVALID_RESPONSE: ErrorDisposition.PERMANENT,
        ExternalErrorCategory.CONTENT_REJECTED: ErrorDisposition.PERMANENT,
        ExternalErrorCategory.PROVIDER_CONFIGURATION_ERROR: ErrorDisposition.PERMANENT,
        ExternalErrorCategory.OUTPUT_TRUNCATED: ErrorDisposition.PERMANENT,
    }
)


@dataclass(frozen=True, slots=True)
class ExternalError:
    """不携带 provider 原始请求、响应或异常文本的安全错误元数据。"""

    trace_id: str
    category: ExternalErrorCategory
    status_code: int | None = None
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        _require_non_empty("trace_id", self.trace_id)
        if not isinstance(self.category, ExternalErrorCategory):
            raise ValueError("category must be an ExternalErrorCategory")
        if self.status_code is not None and (
            isinstance(self.status_code, bool) or not isinstance(self.status_code, int)
        ):
            raise ValueError("status_code must be an integer")
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be a valid HTTP status")
        if self.category in (
            ExternalErrorCategory.CONNECTION_ERROR,
            ExternalErrorCategory.CONNECT_TIMEOUT,
            ExternalErrorCategory.READ_TIMEOUT,
        ):
            if self.status_code is not None:
                raise ValueError("network errors must not include status_code")
        elif self.category is ExternalErrorCategory.RATE_LIMITED:
            if self.status_code not in (None, 429):
                raise ValueError("rate-limited errors only allow status_code 429")
        elif self.category is ExternalErrorCategory.SERVER_ERROR:
            if self.status_code is not None and not 500 <= self.status_code <= 599:
                raise ValueError("server errors only allow 5xx status_code")
        elif (
            self.category
            in (
                ExternalErrorCategory.CLIENT_ERROR,
                ExternalErrorCategory.CONTEXT_LIMIT,
            )
            and self.status_code is not None
            and (not 400 <= self.status_code <= 499 or self.status_code == 429)
        ):
            raise ValueError("client and context errors only allow non-429 4xx status_code")
        elif (
            self.category is ExternalErrorCategory.INVALID_RESPONSE and self.status_code is not None
        ):
            if not 200 <= self.status_code <= 299:
                raise ValueError("invalid responses only allow 2xx status_code")
        elif (
            self.category is ExternalErrorCategory.CONTENT_REJECTED and self.status_code is not None
        ):
            if self.status_code not in (200, 400, 403):
                raise ValueError("content-rejected errors only allow status 200, 400, or 403")
        elif (
            self.category is ExternalErrorCategory.PROVIDER_CONFIGURATION_ERROR
            and self.status_code is not None
            and not 300 <= self.status_code <= 399
        ):
            raise ValueError("provider-configuration errors only allow 3xx status_code")
        elif self.category is ExternalErrorCategory.OUTPUT_TRUNCATED and self.status_code not in (
            None,
            200,
        ):
            raise ValueError("output-truncated errors only allow status 200")

        if self.retry_after_seconds is not None:
            _require_non_negative_finite("retry_after_seconds", self.retry_after_seconds)
            if self.category is not ExternalErrorCategory.RATE_LIMITED:
                raise ValueError("retry_after_seconds is only valid for rate-limited errors")

    @property
    def disposition(self) -> ErrorDisposition:
        if self.category is ExternalErrorCategory.SERVER_ERROR:
            return (
                ErrorDisposition.TRANSIENT
                if self.status_code in (500, 502, 503, 504)
                else ErrorDisposition.PERMANENT
            )
        return _ERROR_DISPOSITIONS[self.category]


LlmOutcome = LlmResult | ExternalError
EmbeddingOutcome = EmbeddingResult | ExternalError


@runtime_checkable
class LlmAdapter(Protocol):
    def generate(
        self,
        request: LlmRequest,
        target: ModelTarget,
        policy: TransportPolicy,
    ) -> LlmOutcome: ...


@runtime_checkable
class EmbeddingAdapter(Protocol):
    def embed(
        self,
        request: EmbeddingRequest,
        target: ModelTarget,
        policy: TransportPolicy,
    ) -> EmbeddingOutcome: ...
