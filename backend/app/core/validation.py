"""共享的 Pydantic 校验错误脱敏边界。"""

from collections.abc import Collection

from pydantic import ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

_REDACTED_ERROR_TITLE = "FinAuditValidation"


def redact_validation_error(
    error: ValidationError,
    *,
    allowed_field_names: Collection[str] = (),
) -> ValidationError:
    """仅保留代码定义的顶层字段位置，并固定其余错误内容。"""

    safe_field_names = frozenset(allowed_field_names)
    line_errors: list[InitErrorDetails] = []
    for detail in error.errors(include_url=False, include_input=False):
        raw_location = detail["loc"]
        safe_location: tuple[str, ...] = ("input",)
        if raw_location and type(raw_location[0]) is str and raw_location[0] in safe_field_names:
            safe_location = (raw_location[0],)
        line_errors.append(
            InitErrorDetails(
                type=PydanticCustomError(
                    "finaudit_validation_error",
                    "Validation failed",
                ),
                loc=safe_location,
                input=None,
            )
        )
    return ValidationError.from_exception_data(
        _REDACTED_ERROR_TITLE,
        line_errors,
        hide_input=True,
    )
