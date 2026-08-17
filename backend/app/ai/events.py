"""CR-011-R4 contract/offline 范围的不可变 ``AiCallEventV1`` DTO。"""

from __future__ import annotations

import hashlib
import json
import math
import weakref
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Final, Literal, NoReturn, TypeAlias, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    ValidationInfo,
    model_validator,
)
from pydantic.config import ExtraValues
from pydantic_core import InitErrorDetails
from typing_extensions import Self

from app.ai.policy import canonicalize_jcs

_MAX_SAFE_INTEGER: Final = 9_007_199_254_740_991
_DUPLICATE_KEY_ERROR: Final = "duplicate JSON object key"
_INVALID_JSON_ERROR: Final = "invalid AiCallEventV1 JSON"
_VALIDATION_ERROR: Final = "AiCallEventV1 validation failed"
_JSON_BOMS: Final = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff")
_VALIDATION_CONTEXT_KEY: Final = "finaudit_ai_call_event_v1"
_VALIDATION_CONTEXT_TOKEN: Final = object()
_VALIDATION_CONTEXT: Final = {_VALIDATION_CONTEXT_KEY: _VALIDATION_CONTEXT_TOKEN}
_INTEGER_FIELD_NAMES: Final = frozenset(
    {
        "event_version",
        "event_sequence",
        "logical_generation_no",
        "provider_attempt_no",
        "policy_version",
        "reserved_input_tokens",
        "reserved_output_tokens",
        "reserved_cost_micro_usd",
        "attempt_count",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "vector_count",
        "http_status",
    }
)
_BOOLEAN_FIELD_NAMES: Final = frozenset({"is_fallback"})
_TRUSTED_FIELDS_BY_EVENT_ID: Final[
    dict[int, tuple[weakref.ReferenceType[object], frozenset[str]]]
] = {}


def _remember_trusted_fields_set(event: object, fields_set: frozenset[str]) -> None:
    event_id = id(event)

    def forget(owner: weakref.ReferenceType[object]) -> None:
        current = _TRUSTED_FIELDS_BY_EVENT_ID.get(event_id)
        if current is not None and current[0] is owner:
            _TRUSTED_FIELDS_BY_EVENT_ID.pop(event_id, None)

    owner = weakref.ref(event, forget)
    _TRUSTED_FIELDS_BY_EVENT_ID[event_id] = owner, fields_set


def _trusted_fields_set_for(event: object) -> frozenset[str] | None:
    record = _TRUSTED_FIELDS_BY_EVENT_ID.get(id(event))
    if record is None or record[0]() is not event:
        return None
    return record[1]


class AiCallEventConflictError(ValueError):
    """相同事件身份出现不同事实，且错误不携带业务原值。"""

    code = "AI_CALL_EVENT_CONFLICT"

    def __init__(self) -> None:
        super().__init__(self.code)


def _fixed_event_validation_error(error_count: int = 1) -> ValidationError:
    line_errors = [
        InitErrorDetails(
            type="value_error",
            loc=("event",),
            input=None,
            ctx={"error": ValueError(_VALIDATION_ERROR)},
        )
        for _ in range(max(error_count, 1))
    ]
    return ValidationError.from_exception_data(
        "AiCallEventV1",
        line_errors,
        hide_input=True,
    )


def _redact_event_validation_error(error: ValidationError) -> ValidationError:
    """用固定投影替换可能携带 discriminator、未知 key 或业务值的错误细节。"""

    return _fixed_event_validation_error(len(error.errors(include_url=False, include_input=False)))


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(_DUPLICATE_KEY_ERROR)
        result[key] = value
    return result


def _reject_non_finite_json_number(_: str) -> NoReturn:
    raise ValueError(_INVALID_JSON_ERROR)


def _load_event_json(json_data: str | bytes | bytearray) -> object:
    try:
        if isinstance(json_data, str):
            text = json_data
        else:
            raw = bytes(json_data)
            if raw.startswith(_JSON_BOMS):
                raise ValueError(_INVALID_JSON_ERROR)
            text = raw.decode("utf-8", errors="strict")
        if text.startswith("\ufeff"):
            raise ValueError(_INVALID_JSON_ERROR)
        return cast(
            object,
            json.loads(
                text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_float=Decimal,
                parse_constant=_reject_non_finite_json_number,
            ),
        )
    except ValueError as error:
        if str(error) == _DUPLICATE_KEY_ERROR:
            raise ValueError(_DUPLICATE_KEY_ERROR) from None
        raise ValueError(_INVALID_JSON_ERROR) from None
    except UnicodeError:
        raise ValueError(_INVALID_JSON_ERROR) from None


def _normalize_mathematical_integer(value: object) -> int:
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError("event integer must be a JSON mathematical integer")
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise ValueError("event integer must be a JSON mathematical integer")
        normalized = int(value)
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError("event integer must be a JSON mathematical integer")
        normalized = int(value)
    else:
        raise ValueError("event integer must be a JSON mathematical integer")
    if not 0 <= normalized <= _MAX_SAFE_INTEGER:
        raise ValueError("event integer is outside the I-JSON safe range")
    return normalized


def _normalize_positive_integer(value: object) -> int:
    normalized = _normalize_mathematical_integer(value)
    if normalized == 0:
        raise ValueError("event integer must be positive")
    return normalized


def _normalize_http_status(value: object) -> int:
    normalized = _normalize_mathematical_integer(value)
    if not 100 <= normalized <= 599:
        raise ValueError("HTTP status is outside the approved range")
    return normalized


def _validate_timestamp(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise ValueError("timestamp must be valid UTC RFC3339 microseconds") from None
    return value


UuidText = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        ),
    ),
]
Sha256Text = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
TimestampUtcMicroseconds = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=(
            r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
            r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z$"
        ),
    ),
    AfterValidator(_validate_timestamp),
]
SafeNonNegativeInteger = Annotated[int, BeforeValidator(_normalize_mathematical_integer)]
SafePositiveInteger = Annotated[int, BeforeValidator(_normalize_positive_integer)]
HttpStatus = Annotated[int, BeforeValidator(_normalize_http_status)]
EventVersionOne = Annotated[Literal[1], BeforeValidator(_normalize_positive_integer)]
EventSequenceOne = Annotated[Literal[1], BeforeValidator(_normalize_positive_integer)]
EventSequenceTwo = Annotated[Literal[2], BeforeValidator(_normalize_positive_integer)]
EventSequenceThree = Annotated[Literal[3], BeforeValidator(_normalize_positive_integer)]
SafeText = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]
ResourceType = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=60, pattern=r"^[!-~]+$"),
]
EndpointId = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
PricingVersion = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
ModelId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=200)]
SafeErrorCode = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    ),
]
CitationValidationStatus = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=30,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]
CallType: TypeAlias = Literal[
    "contract_field_extraction",
    "embedding",
    "invoice_field_extraction",
    "rag_answer",
    "report_draft",
    "risk_explanation",
]
ErrorCategory: TypeAlias = Literal[
    "client_error",
    "content_rejected",
    "context_limit",
    "invalid_response",
    "output_truncated",
    "provider_configuration_error",
    "rate_limited",
    "server_error",
    "transient",
]


class _StrictFrozenEventV1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    event_id: UuidText
    event_version: EventVersionOne
    event_sequence: SafePositiveInteger
    event_type: Literal["ai.call.started", "ai.call.completed", "ai.call.late_completion"]
    aggregate_type: Literal["ai_call"]
    aggregate_id: UuidText

    @property
    def model_fields_set(self) -> set[str]:
        """返回只读快照，避免 Pydantic 内部可变 set 改写 Event 投影。"""

        fields_set = _trusted_fields_set_for(self)
        if fields_set is None:
            raise TypeError("AiCallEventV1 trusted projection is unavailable")
        return cast(set[str], fields_set)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_trusted_fields_set":
            raise TypeError("AiCallEventV1 trusted projection is immutable")
        try:
            super().__setattr__(name, value)
        except ValidationError as error:
            raise _redact_event_validation_error(error) from None

    def __delattr__(self, name: str) -> None:
        if name == "_trusted_fields_set":
            raise TypeError("AiCallEventV1 trusted projection is immutable")
        try:
            super().__delattr__(name)
        except ValidationError as error:
            raise _redact_event_validation_error(error) from None

    def __copy__(self) -> Self:
        raise TypeError("AiCallEventV1 copy is forbidden")

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        del memo
        raise TypeError("AiCallEventV1 copy is forbidden")

    def __replace__(self, **changes: Any) -> Self:
        del changes
        raise TypeError("AiCallEventV1 copy is forbidden")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """禁止 Pydantic 不校验 ``update`` 的复制逃生口。"""

        del update, deep
        raise TypeError("AiCallEventV1 model_copy is forbidden")

    def copy(
        self,
        *,
        include: Any = None,
        exclude: Any = None,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """同时关闭 Pydantic v1 兼容复制入口。"""

        del include, exclude, update, deep
        raise TypeError("AiCallEventV1 copy is forbidden")

    @staticmethod
    def _validate_entry_options(
        *,
        strict: bool | None,
        extra: ExtraValues | None,
        from_attributes: bool | None,
    ) -> None:
        if (
            strict not in (None, True)
            or extra not in (None, "forbid")
            or from_attributes not in (None, False)
        ):
            raise ValueError(
                "Event validation options cannot relax strict, extra, or attribute rules"
            )

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
        """只允许 strict + extra-forbid 的 Event Python 输入边界。"""

        if context is not None:
            raise ValueError("Event validation context is reserved")
        cls._validate_entry_options(
            strict=strict,
            extra=extra,
            from_attributes=from_attributes,
        )
        try:
            return super().model_validate(
                obj,
                strict=True,
                extra="forbid",
                from_attributes=False,
                context=_VALIDATION_CONTEXT,
                by_alias=by_alias,
                by_name=by_name,
            )
        except ValidationError as error:
            raise _redact_event_validation_error(error) from None

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
        """拒绝重复 key，同时保留 Event mathematical-integer 值语义。"""

        cls._validate_entry_options(strict=strict, extra=extra, from_attributes=None)
        return cls.model_validate(
            _load_event_json(json_data),
            context=context,
            by_alias=by_alias,
            by_name=by_name,
        )

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
        """Event 不接受会把数字字符串转换为整数的入口。"""

        raise TypeError("Event does not support model_validate_strings")

    @model_validator(mode="before")
    @classmethod
    def enforce_approved_validation_entry(
        cls,
        value: Any,
        info: ValidationInfo,
    ) -> Any:
        context = info.context
        if (
            info.mode != "python"
            or type(context) is not dict
            or context.get(_VALIDATION_CONTEXT_KEY) is not _VALIDATION_CONTEXT_TOKEN
            or type(value) is not dict
        ):
            raise ValueError(_VALIDATION_ERROR)

        unknown_fields = set(value).difference(cls.model_fields)
        if unknown_fields or any(type(name) is not str for name in value):
            raise ValueError(_VALIDATION_ERROR)
        for name, raw_value in value.items():
            if name in _INTEGER_FIELD_NAMES:
                continue
            if name in _BOOLEAN_FIELD_NAMES:
                if type(raw_value) is not bool:
                    raise ValueError(_VALIDATION_ERROR)
                continue
            if raw_value is not None and type(raw_value) is not str:
                raise ValueError(_VALIDATION_ERROR)
        return value

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
            raise _redact_event_validation_error(error) from None

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.aggregate_id != self.event_id:
            raise ValueError("aggregate_id must equal event_id")
        fields_set = frozenset(object.__getattribute__(self, "__pydantic_fields_set__"))
        canonicalize_jcs(
            BaseModel.model_dump(
                self,
                mode="json",
                include=set(fields_set),
                warnings="error",
            )
        )
        _remember_trusted_fields_set(self, fields_set)
        return self

    def canonical_payload(self) -> bytes:
        """返回保留 late 省略/null 差异的 RFC 8785 JCS bytes。"""

        return _strict_event_view(self)[1]

    def payload_sha256(self) -> str:
        return hashlib.sha256(self.canonical_payload()).hexdigest()

    @property
    def replay_key(self) -> tuple[str, str]:
        validated, _ = _strict_event_view(self)
        return validated.event_id, validated.event_type


class AiCallStartedV1(_StrictFrozenEventV1):
    event_sequence: EventSequenceOne
    event_type: Literal["ai.call.started"]
    organization_id: UuidText
    business_operation_id: UuidText
    job_id: UuidText | None
    request_id: UuidText | None
    resource_type: ResourceType | None
    resource_id: UuidText | None
    trace_id: UuidText
    call_type: CallType
    logical_generation_no: SafePositiveInteger
    provider_attempt_no: SafePositiveInteger
    adapter_id: Literal["openai_chat_completions_v1", "openai_embeddings_v1"]
    endpoint_id: EndpointId
    model_id: ModelId
    model_version: SafeText | None
    prompt_id: SafeText | None
    prompt_version: SafeText | None
    prompt_hash: Sha256Text | None
    schema_version: SafeText | None
    policy_version: SafePositiveInteger
    policy_hash: Sha256Text
    pricing_version: PricingVersion
    input_hash: Sha256Text
    reserved_input_tokens: SafeNonNegativeInteger
    reserved_output_tokens: SafeNonNegativeInteger
    reserved_cost_micro_usd: SafeNonNegativeInteger
    attempt_count: SafePositiveInteger
    is_fallback: bool
    breaker_state: Literal["closed", "half_open", "open"] | None
    status: Literal["pending"]
    started_at: TimestampUtcMicroseconds

    @model_validator(mode="after")
    def validate_started_contract(self) -> Self:
        if self.attempt_count != self.provider_attempt_no:
            raise ValueError("attempt_count must equal provider_attempt_no")
        if self.call_type == "embedding":
            if self.adapter_id != "openai_embeddings_v1" or any(
                value is not None
                for value in (
                    self.prompt_id,
                    self.prompt_version,
                    self.prompt_hash,
                    self.schema_version,
                )
            ):
                raise ValueError("embedding started fields do not match Event v1")
        elif self.adapter_id != "openai_chat_completions_v1" or any(
            value is None for value in (self.prompt_id, self.prompt_version, self.prompt_hash)
        ):
            raise ValueError("LLM started fields do not match Event v1")
        return self


class AiCallCompletedV1(_StrictFrozenEventV1):
    event_sequence: EventSequenceTwo
    event_type: Literal["ai.call.completed"]
    organization_id: UuidText
    business_operation_id: UuidText
    job_id: UuidText | None
    request_id: UuidText | None
    trace_id: UuidText
    policy_version: SafePositiveInteger
    policy_hash: Sha256Text
    status: Literal["succeeded", "failed", "degraded", "rejected", "outcome_unknown"]
    completed_at: TimestampUtcMicroseconds
    duration_ms: SafeNonNegativeInteger
    output_hash: Sha256Text | None
    input_tokens: SafeNonNegativeInteger | None
    output_tokens: SafeNonNegativeInteger | None
    vector_count: SafeNonNegativeInteger | None
    http_status: HttpStatus | None
    error_category: ErrorCategory | None
    safe_error_code: SafeErrorCode | None
    citation_validation_status: CitationValidationStatus | None

    @model_validator(mode="after")
    def validate_status_matrix(self) -> Self:
        if self.status == "succeeded":
            if (
                self.output_hash is None
                or self.input_tokens is None
                or self.output_tokens is None
                or self.http_status != 200
                or self.error_category is not None
                or self.safe_error_code is not None
            ):
                raise ValueError("succeeded fields do not match Event v1")
        elif self.status == "outcome_unknown":
            if (
                any(
                    value is not None
                    for value in (
                        self.output_hash,
                        self.input_tokens,
                        self.output_tokens,
                        self.vector_count,
                        self.http_status,
                        self.error_category,
                        self.citation_validation_status,
                    )
                )
                or self.safe_error_code != "AI_OUTCOME_UNKNOWN"
            ):
                raise ValueError("outcome_unknown fields do not match Event v1")
        elif self.error_category is None or self.safe_error_code is None:
            raise ValueError("terminal error fields do not match Event v1")
        elif self.status == "failed" and self.citation_validation_status is not None:
            raise ValueError("failed citation status must be null")
        return self


class AiCallLateCompletionV1(_StrictFrozenEventV1):
    event_sequence: EventSequenceThree
    event_type: Literal["ai.call.late_completion"]
    organization_id: UuidText
    business_operation_id: UuidText
    job_id: UuidText | None
    request_id: UuidText | None
    trace_id: UuidText
    policy_version: SafePositiveInteger
    policy_hash: Sha256Text
    observed_status: Literal["succeeded", "failed", "degraded", "rejected"]
    provider_completed_at: TimestampUtcMicroseconds
    duration_ms: SafeNonNegativeInteger | None = None
    output_hash: Sha256Text | None = None
    input_tokens: SafeNonNegativeInteger | None = None
    output_tokens: SafeNonNegativeInteger | None = None
    vector_count: SafeNonNegativeInteger | None = None
    http_status: HttpStatus | None = None
    error_category: ErrorCategory | None = None
    safe_error_code: SafeErrorCode | None = None


AiCallEventV1: TypeAlias = AiCallStartedV1 | AiCallCompletedV1 | AiCallLateCompletionV1
_DiscriminatedAiCallEventV1: TypeAlias = Annotated[
    AiCallEventV1,
    Field(discriminator="event_type"),
]
_AI_CALL_EVENT_ADAPTER: TypeAdapter[_DiscriminatedAiCallEventV1] = TypeAdapter(
    _DiscriminatedAiCallEventV1
)
_CONCRETE_EVENT_TYPES: Final = (
    AiCallStartedV1,
    AiCallCompletedV1,
    AiCallLateCompletionV1,
)


def _strict_event_view(value: object) -> tuple[AiCallEventV1, bytes]:
    """从封闭字段和不可变 fields-set 重建并严格验证可信 Event 投影。"""

    try:
        event_type = type(value)
        if event_type not in _CONCRETE_EVENT_TYPES:
            raise TypeError(_VALIDATION_ERROR)
        model_type = cast(type[_StrictFrozenEventV1], event_type)
        event = cast(_StrictFrozenEventV1, value)
        model_fields = model_type.model_fields
        allowed_fields = frozenset(model_fields)
        required_fields = frozenset(
            name for name, field in model_fields.items() if field.is_required()
        )
        raw_values = object.__getattribute__(event, "__dict__")
        fields_set = object.__getattribute__(event, "__pydantic_fields_set__")
        trusted_fields_set = _trusted_fields_set_for(event)
        extra = object.__getattribute__(event, "__pydantic_extra__")
        if (
            type(raw_values) is not dict
            or set(raw_values) != set(allowed_fields)
            or type(fields_set) is not set
            or type(trusted_fields_set) is not frozenset
            or frozenset(fields_set) != trusted_fields_set
            or not required_fields.issubset(trusted_fields_set)
            or not trusted_fields_set.issubset(allowed_fields)
            or extra is not None
        ):
            raise TypeError(_VALIDATION_ERROR)

        projection = {name: raw_values[name] for name in trusted_fields_set}
        validated = model_type.__pydantic_validator__.validate_python(
            projection,
            strict=True,
            extra="forbid",
            from_attributes=False,
            context=_VALIDATION_CONTEXT,
        )
        if type(validated) is not event_type:
            raise TypeError(_VALIDATION_ERROR)
        validated_fields_set = object.__getattribute__(validated, "__pydantic_fields_set__")
        validated_trusted_fields_set = _trusted_fields_set_for(validated)
        if (
            frozenset(validated_fields_set) != trusted_fields_set
            or validated_trusted_fields_set != trusted_fields_set
        ):
            raise TypeError(_VALIDATION_ERROR)
        payload = BaseModel.model_dump(
            validated,
            mode="json",
            include=set(trusted_fields_set),
            warnings="error",
        )
        if set(payload) != set(trusted_fields_set):
            raise TypeError(_VALIDATION_ERROR)
        return validated, canonicalize_jcs(payload)
    except ValidationError as error:
        raise _redact_event_validation_error(error) from None
    except (AttributeError, KeyError, TypeError, UnicodeError, ValueError):
        raise _fixed_event_validation_error() from None


def validate_ai_call_event_v1(value: object) -> AiCallEventV1:
    """验证已解析对象，且不允许调用方放松 strict/closed 规则。"""

    try:
        if type(value) in _CONCRETE_EVENT_TYPES:
            return _strict_event_view(value)[0]
        validated = _AI_CALL_EVENT_ADAPTER.validate_python(
            value,
            strict=True,
            extra="forbid",
            from_attributes=False,
            context=_VALIDATION_CONTEXT,
        )
        return _strict_event_view(validated)[0]
    except ValidationError as error:
        raise _redact_event_validation_error(error) from None


def parse_ai_call_event_v1(json_data: str | bytes | bytearray) -> AiCallEventV1:
    """解析拒绝重复 key 的 Event v1 JSON，并移除错误中的原始输入。"""

    return validate_ai_call_event_v1(_load_event_json(json_data))


ReplayDisposition: TypeAlias = Literal["replayed_same", "conflict"]


def classify_ai_call_event_replay(
    existing: AiCallEventV1,
    candidate: AiCallEventV1,
) -> ReplayDisposition:
    """纯比较相同 replay key；不读取或写入任何 Sink。"""

    validated_existing, existing_payload = _strict_event_view(existing)
    validated_candidate, candidate_payload = _strict_event_view(candidate)
    existing_key = validated_existing.event_id, validated_existing.event_type
    candidate_key = validated_candidate.event_id, validated_candidate.event_type
    if existing_key != candidate_key:
        raise ValueError("events do not share a replay key")
    if existing_payload == candidate_payload:
        return "replayed_same"
    return "conflict"


def validate_ai_call_event_chain(
    started: AiCallStartedV1,
    completed: AiCallCompletedV1,
    late: AiCallLateCompletionV1 | None = None,
) -> None:
    """验证事件间不变量；只做纯合同校验，不代表 Sink 状态机证据。"""

    try:
        validated_started, _ = _strict_event_view(started)
        validated_completed, _ = _strict_event_view(completed)
        if (
            type(validated_started) is not AiCallStartedV1
            or type(validated_completed) is not AiCallCompletedV1
        ):
            raise TypeError(_VALIDATION_ERROR)
        started = validated_started
        completed = validated_completed
        if late is not None:
            validated_late, _ = _strict_event_view(late)
            if type(validated_late) is not AiCallLateCompletionV1:
                raise TypeError(_VALIDATION_ERROR)
            late = validated_late
    except (AttributeError, TypeError, ValueError):
        raise AiCallEventConflictError from None

    correlation_fields = (
        "event_id",
        "organization_id",
        "business_operation_id",
        "job_id",
        "request_id",
        "trace_id",
        "policy_version",
        "policy_hash",
    )
    if any(getattr(started, field) != getattr(completed, field) for field in correlation_fields):
        raise AiCallEventConflictError
    if completed.completed_at < started.started_at:
        raise AiCallEventConflictError
    if started.call_type == "embedding":
        if completed.status == "succeeded" and (
            completed.output_tokens != 0
            or completed.vector_count is None
            or completed.vector_count == 0
        ):
            raise AiCallEventConflictError
    elif completed.vector_count is not None:
        raise AiCallEventConflictError

    if late is None:
        return
    if completed.status != "outcome_unknown" or any(
        getattr(started, field) != getattr(late, field) for field in correlation_fields
    ):
        raise AiCallEventConflictError
