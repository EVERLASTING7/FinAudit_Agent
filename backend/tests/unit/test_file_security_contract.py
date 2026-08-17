from enum import Enum

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.files import SecurityScanStatus
from app.services.file_service import is_parsing_allowed

EXPECTED_SECURITY_SCAN_STATUSES = (
    "pending",
    "clean",
    "infected",
    "scan_failed",
    "unsupported",
    "not_configured",
)


class UnrelatedStatus(str, Enum):
    CLEAN = "clean"


def test_security_scan_status_contract_is_exact_and_pydantic_serializable() -> None:
    adapter = TypeAdapter(SecurityScanStatus)

    assert tuple(status.value for status in SecurityScanStatus) == EXPECTED_SECURITY_SCAN_STATUSES
    schema = adapter.json_schema()
    assert schema["enum"] == list(EXPECTED_SECURITY_SCAN_STATUSES)
    assert schema["title"] == "SecurityScanStatus"
    assert schema["type"] == "string"
    assert [
        adapter.dump_python(adapter.validate_python(value), mode="json")
        for value in EXPECTED_SECURITY_SCAN_STATUSES
    ] == list(EXPECTED_SECURITY_SCAN_STATUSES)


@pytest.mark.parametrize(
    "invalid_value",
    ["error", "unknown", "", None, True, 1, {}, []],
)
def test_security_scan_status_rejects_unknown_or_wrong_typed_values(
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(SecurityScanStatus).validate_python(invalid_value)


def test_only_clean_enum_instance_allows_parsing() -> None:
    assert is_parsing_allowed(SecurityScanStatus.CLEAN) is True
    assert all(
        not is_parsing_allowed(status)
        for status in SecurityScanStatus
        if status is not SecurityScanStatus.CLEAN
    )


@pytest.mark.parametrize(
    "untrusted_status",
    [
        *EXPECTED_SECURITY_SCAN_STATUSES,
        "error",
        "unknown",
        UnrelatedStatus.CLEAN,
        None,
        True,
        1,
        {},
        [],
    ],
)
def test_unvalidated_or_wrong_typed_statuses_fail_closed(untrusted_status: object) -> None:
    assert is_parsing_allowed(untrusted_status) is False
