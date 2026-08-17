import json

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

from app.core.validation import redact_validation_error


def _render_error(error: ValidationError) -> str:
    return "\n".join(
        (
            str(error),
            json.dumps(error.errors(), ensure_ascii=False, default=str),
            error.json(),
        )
    )


def test_redactor_removes_value_error_context_and_preserves_safe_field() -> None:
    sentinel = "SYNTHETIC_VALIDATION_SECRET_9f8a"

    class ValueErrorModel(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def reject_value(cls, value: str) -> str:
            raise ValueError(f"unsafe:{value}")

    with pytest.raises(ValidationError) as exc_info:
        ValueErrorModel(value=sentinel)

    redacted = redact_validation_error(
        exc_info.value,
        allowed_field_names=ValueErrorModel.model_fields,
    )

    assert sentinel not in _render_error(redacted)
    assert redacted.errors(include_url=False, include_input=False) == [
        {
            "type": "finaudit_validation_error",
            "loc": ("value",),
            "msg": "Validation failed",
        }
    ]


def test_redactor_handles_unknown_custom_error_without_leaking_context() -> None:
    sentinel = "SYNTHETIC_CUSTOM_ERROR_SECRET_4bc1"

    class CustomErrorModel(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def reject_value(cls, value: str) -> str:
            raise PydanticCustomError("unsafe", "unsafe:{value}", {"value": value})

    with pytest.raises(ValidationError) as exc_info:
        CustomErrorModel(value=sentinel)

    redacted = redact_validation_error(
        exc_info.value,
        allowed_field_names=CustomErrorModel.model_fields,
    )

    assert sentinel not in _render_error(redacted)
    assert redacted.errors(include_url=False, include_input=False)[0]["loc"] == ("value",)


def test_redactor_replaces_untrusted_extra_field_location() -> None:
    sentinel = "SYNTHETIC_LOCATION_SECRET_7ad3"

    class ExtraFieldModel(BaseModel):
        model_config = ConfigDict(extra="forbid")

        known: str

    with pytest.raises(ValidationError) as exc_info:
        ExtraFieldModel.model_validate({"known": "ok", sentinel: "value"})

    redacted = redact_validation_error(
        exc_info.value,
        allowed_field_names=ExtraFieldModel.model_fields,
    )

    assert sentinel not in _render_error(redacted)
    assert redacted.errors(include_url=False, include_input=False)[0]["loc"] == ("input",)


def test_redactor_replaces_untrusted_error_title() -> None:
    sentinel = "SYNTHETIC_TITLE_SECRET_5e21"
    source_error = ValidationError.from_exception_data(
        sentinel,
        [
            InitErrorDetails(
                type=PydanticCustomError("unsafe", "unsafe"),
                loc=("value",),
                input=None,
            )
        ],
    )

    redacted = redact_validation_error(
        source_error,
        allowed_field_names={"value"},
    )

    assert redacted.title == "FinAuditValidation"
    assert sentinel not in _render_error(redacted)
