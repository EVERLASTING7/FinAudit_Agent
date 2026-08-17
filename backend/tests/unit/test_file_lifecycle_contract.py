import pytest
from pydantic import ValidationError

from app.schemas.files import (
    FileLifecycleStatuses,
    FileStatus,
    MarkdownVersionStatus,
    ParseVersionStatus,
    SecurityScanStatus,
)

EXPECTED_FILE_STATUSES = (
    "uploaded",
    "validating",
    "stored",
    "rejected",
    "archived",
)
EXPECTED_SECURITY_SCAN_STATUSES = (
    "pending",
    "clean",
    "infected",
    "scan_failed",
    "unsupported",
    "not_configured",
)
EXPECTED_PARSE_STATUSES = (
    "queued",
    "running",
    "succeeded",
    "manual_review_required",
    "active",
    "failed",
    "superseded",
)
EXPECTED_MARKDOWN_STATUSES = (
    "queued",
    "converting",
    "validating",
    "review_required",
    "ready",
    "active",
    "failed",
    "superseded",
    "archived",
)
VALID_PAYLOAD: dict[str, object] = {
    "file_status": "stored",
    "security_scan_status": "clean",
    "parse_status": "active",
    "markdown_status": "failed",
}


def test_file_lifecycle_status_enums_are_exact() -> None:
    assert tuple(status.value for status in FileStatus) == EXPECTED_FILE_STATUSES
    assert tuple(status.value for status in SecurityScanStatus) == EXPECTED_SECURITY_SCAN_STATUSES
    assert tuple(status.value for status in ParseVersionStatus) == EXPECTED_PARSE_STATUSES
    assert tuple(status.value for status in MarkdownVersionStatus) == EXPECTED_MARKDOWN_STATUSES


def test_file_lifecycle_schema_requires_four_fields_and_forbids_extras() -> None:
    schema = FileLifecycleStatuses.model_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "file_status",
        "security_scan_status",
        "parse_status",
        "markdown_status",
    ]

    with pytest.raises(ValidationError):
        FileLifecycleStatuses.model_validate({**VALID_PAYLOAD, "status": "failed"})


def test_file_lifecycle_statuses_remain_independent() -> None:
    statuses = FileLifecycleStatuses.model_validate(VALID_PAYLOAD)

    assert statuses.model_dump(mode="json") == VALID_PAYLOAD


def test_parse_and_markdown_statuses_accept_explicit_null() -> None:
    payload = {**VALID_PAYLOAD, "parse_status": None, "markdown_status": None}

    assert FileLifecycleStatuses.model_validate(payload).model_dump(mode="json") == payload


@pytest.mark.parametrize("field", tuple(VALID_PAYLOAD))
def test_file_lifecycle_status_fields_are_required(field: str) -> None:
    payload = {key: value for key, value in VALID_PAYLOAD.items() if key != field}

    with pytest.raises(ValidationError):
        FileLifecycleStatuses.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("file_status", None),
        ("file_status", "STORED"),
        ("security_scan_status", None),
        ("security_scan_status", "error"),
        ("parse_status", "unknown"),
        ("markdown_status", "unknown"),
        ("file_status", True),
        ("security_scan_status", 1),
        ("parse_status", {}),
        ("markdown_status", []),
    ],
)
def test_file_lifecycle_statuses_reject_unknown_or_wrong_typed_values(
    field: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError):
        FileLifecycleStatuses.model_validate({**VALID_PAYLOAD, field: invalid_value})
