import hashlib
import unicodedata

import pytest

from app.core.password_policy import (
    PASSWORD_BLOCKLIST_SHA256,
    PASSWORD_MIN_CODE_POINTS,
    PASSWORD_POLICY_VERSION,
    normalize_password_input,
    validate_new_password,
)


def test_new_password_normalizes_nfc_without_trimming() -> None:
    password = "  strong-cafe\u0301-password  "

    assert validate_new_password(password) == unicodedata.normalize("NFC", password)


def test_global_password_minimum_accepts_six_code_points() -> None:
    assert PASSWORD_POLICY_VERSION == "auth-password-v2"
    assert PASSWORD_MIN_CODE_POINTS == 6
    assert validate_new_password("s4fe!?") == "s4fe!?"


@pytest.mark.parametrize(
    "password",
    (
        "short",
        "x" * 129,
        "123456",
        "letmein",
        "password123456",
        "qwerty",
        "safe-password-\x00-value",
        "界" * 128 + "a",
    ),
)
def test_new_password_rejects_policy_violations(password: str) -> None:
    with pytest.raises(ValueError):
        validate_new_password(password)


def test_login_input_enforces_the_approved_length_and_bounds_resource_use() -> None:
    with pytest.raises(ValueError, match="approved range"):
        normalize_password_input("short")
    assert normalize_password_input("legacy") == "legacy"
    with pytest.raises(ValueError, match="byte limit"):
        normalize_password_input("界" * 171)


def test_blocklist_artifact_has_reviewable_version_digest() -> None:
    canonical = (
        b"123456\n"
        b"123456789012345\n"
        b"admin123456789\n"
        b"finaudit-agent\n"
        b"letmein\n"
        b"letmein123456789\n"
        b"password\n"
        b"password123456\n"
        b"qwerty\n"
        b"qwertyuiop12345\n"
    )

    assert hashlib.sha256(canonical).hexdigest() == PASSWORD_BLOCKLIST_SHA256
