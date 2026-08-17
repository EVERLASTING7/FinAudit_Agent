"""结构化 AI 输出的离线确定性清理与 Schema 校验。"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

_OUTER_FENCE = re.compile(
    r"\A```(?:json)?[ \t]*\r?\n(?P<body>.*)\r?\n```[ \t]*\Z",
    flags=re.DOTALL,
)
_FENCE_DELIMITER_LINE = re.compile(r"^[ \t]*```[^\r\n]*$", flags=re.MULTILINE)
_MAX_JSON_INTEGER_DIGITS = 4_300
_MAX_SAFE_ISSUES = 32
_MAX_SAFE_POINTER_DEPTH = 16
_SAFE_POINTER_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


class StructuredOutputIssueCategory(str, Enum):
    """允许进入后续 repair 输入的固定安全错误类别。"""

    JSON = "json"
    REQUIRED = "required"
    TYPE = "type"
    ENUM = "enum"
    SCHEMA = "schema"


@dataclass(frozen=True, slots=True)
class StructuredOutputIssue:
    """不携带原始响应、失败值或自由文本的结构化问题。"""

    pointer: str
    category: StructuredOutputIssueCategory


class StructuredOutputValidationError(Exception):
    """结构化输出无法通过确定性清理或 Schema 校验。"""

    code = "AI_SCHEMA_VALIDATION_FAILED"

    def __init__(self, issues: tuple[StructuredOutputIssue, ...]) -> None:
        if not issues:
            raise ValueError("issues must not be empty")
        self.issues = issues
        super().__init__(self.code)


class _DuplicateKeyError(ValueError):
    pass


class _NonFiniteNumberError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_non_finite_number(_: str) -> object:
    raise _NonFiniteNumberError


def _parse_bounded_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > _MAX_JSON_INTEGER_DIGITS:
        raise _NonFiniteNumberError
    try:
        return int(value)
    except ValueError:
        raise _NonFiniteNumberError from None


def _parse_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise _NonFiniteNumberError from None
    if not math.isfinite(parsed):
        raise _NonFiniteNumberError
    return parsed


_DECODER = json.JSONDecoder(
    object_pairs_hook=_reject_duplicate_keys,
    parse_float=_parse_finite_float,
    parse_int=_parse_bounded_integer,
    parse_constant=_reject_non_finite_number,
)


def _json_issue() -> StructuredOutputValidationError:
    return StructuredOutputValidationError(
        (StructuredOutputIssue("", StructuredOutputIssueCategory.JSON),)
    )


def _schema_issue() -> StructuredOutputValidationError:
    return StructuredOutputValidationError(
        (StructuredOutputIssue("", StructuredOutputIssueCategory.SCHEMA),)
    )


def _strip_single_outer_fence(raw_output: str) -> str:
    text = raw_output.strip()
    match = _OUTER_FENCE.fullmatch(text)
    if match is None:
        if _FENCE_DELIMITER_LINE.search(text):
            raise _json_issue()
        return text

    body = match.group("body").strip()
    if _FENCE_DELIMITER_LINE.search(body):
        raise _json_issue()
    return body


def _unique_json_object_text(text: str) -> str:
    parse_failed_safely = False
    object_span: tuple[int, int] | None = None
    start = 0
    try:
        parsed, end = _DECODER.raw_decode(text)
    except json.JSONDecodeError:
        parsed = None
        end = -1
    except (RecursionError, ValueError):
        parsed = None
        end = -1
        parse_failed_safely = True
    else:
        if not text[end:].strip():
            if not isinstance(parsed, dict):
                raise _json_issue()
            return text[:end]
        if isinstance(parsed, dict):
            object_span = (0, end)
            start = end

    if parse_failed_safely:
        raise _json_issue()

    if text.startswith(("{", "[")) and object_span is None:
        raise _json_issue()

    while start < len(text):
        if text[start] not in "{[":
            start += 1
            continue
        candidate_failed_safely = False
        try:
            candidate, candidate_end = _DECODER.raw_decode(text, start)
        except json.JSONDecodeError:
            candidate = None
            candidate_end = -1
            candidate_failed_safely = True
        except (RecursionError, ValueError):
            candidate = None
            candidate_end = -1
            candidate_failed_safely = True
        if candidate_failed_safely:
            raise _json_issue()
        if isinstance(candidate, list):
            if _list_contains_object(candidate):
                raise _json_issue()
            start = candidate_end
            continue
        if not isinstance(candidate, dict):
            start += 1
            continue
        if object_span is not None:
            raise _json_issue()
        object_span = (start, candidate_end)
        start = candidate_end

    if object_span is None:
        raise _json_issue()
    start, end = object_span
    return text[start:end]


def _list_contains_object(value: list[object]) -> bool:
    pending: list[object] = list(value)
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            return True
        if isinstance(item, list):
            pending.extend(item)
    return False


def _safe_root_fields(model_type: type[BaseModel]) -> frozenset[str]:
    names = set(model_type.model_fields)
    names.update(
        field.alias for field in model_type.model_fields.values() if isinstance(field.alias, str)
    )
    return frozenset(name for name in names if _SAFE_POINTER_TOKEN.fullmatch(name))


def _pointer(
    location: tuple[int | str, ...],
    *,
    safe_root_fields: frozenset[str],
) -> str:
    if not location:
        return ""
    tokens: list[str] = []
    for index, item in enumerate(location[:_MAX_SAFE_POINTER_DEPTH]):
        if index == 0 and isinstance(item, str) and item in safe_root_fields:
            tokens.append(item)
        elif isinstance(item, int) and item >= 0:
            tokens.append(str(item))
        else:
            tokens.append("*")
    if len(location) > _MAX_SAFE_POINTER_DEPTH:
        tokens.append("*")
    return "/" + "/".join(tokens)


def _issue_category(error_type: str) -> StructuredOutputIssueCategory:
    if error_type == "json_invalid":
        return StructuredOutputIssueCategory.JSON
    if error_type == "missing":
        return StructuredOutputIssueCategory.REQUIRED
    if error_type in {"enum", "literal_error"}:
        return StructuredOutputIssueCategory.ENUM
    if error_type == "extra_forbidden":
        return StructuredOutputIssueCategory.SCHEMA
    return StructuredOutputIssueCategory.TYPE


def _safe_schema_issues(
    error: ValidationError,
    model_type: type[BaseModel],
) -> tuple[StructuredOutputIssue, ...]:
    safe_root_fields = _safe_root_fields(model_type)
    issues = {
        StructuredOutputIssue(
            pointer=_pointer(tuple(detail["loc"]), safe_root_fields=safe_root_fields),
            category=_issue_category(str(detail["type"])),
        )
        for detail in error.errors(include_url=False, include_context=False, include_input=False)
    }
    return tuple(sorted(issues, key=lambda issue: (issue.pointer, issue.category.value)))[
        :_MAX_SAFE_ISSUES
    ]


def validate_structured_output(raw_output: str, model_type: type[ModelT]) -> ModelT:
    """清理唯一 JSON object，并以严格 JSON 模式执行调用方提供的 Pydantic Schema。"""

    if not isinstance(raw_output, str):
        raise TypeError("raw_output must be a string")
    if (
        not isinstance(model_type, type)
        or model_type is BaseModel
        or not issubclass(model_type, BaseModel)
    ):
        raise TypeError("model_type must be a BaseModel subclass")

    object_text = _unique_json_object_text(_strip_single_outer_fence(raw_output))
    safe_error: StructuredOutputValidationError | None = None
    try:
        return model_type.model_validate_json(object_text, strict=True)
    except ValidationError as error:
        safe_error = StructuredOutputValidationError(_safe_schema_issues(error, model_type))
    except Exception:
        safe_error = _schema_issue()

    assert safe_error is not None
    raise safe_error
