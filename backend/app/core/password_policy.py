"""auth-password-v1 输入规范化与本地弱密码拒绝。"""

import hashlib
import unicodedata

PASSWORD_POLICY_VERSION = "auth-password-v1"
PASSWORD_MIN_CODE_POINTS = 15
PASSWORD_MAX_CODE_POINTS = 128
PASSWORD_MAX_UTF8_BYTES = 512
PASSWORD_BLOCKLIST_SHA256 = "d38b66348d40b91a43d706d3ff42bab41284305c79306c2c4deb2009d8e2a358"

_PUBLIC_WEAK_PASSWORDS = (
    "123456789012345",
    "admin123456789",
    "finaudit-agent",
    "letmein123456789",
    "password",
    "password123456",
    "qwertyuiop12345",
)
_BLOCKLIST_CANONICAL_BYTES = ("\n".join(_PUBLIC_WEAK_PASSWORDS) + "\n").encode("utf-8")
if hashlib.sha256(_BLOCKLIST_CANONICAL_BYTES).hexdigest() != PASSWORD_BLOCKLIST_SHA256:
    raise RuntimeError("auth password blocklist does not match its reviewed digest")
_BLOCKED_DIGESTS = frozenset(
    hashlib.sha256(unicodedata.normalize("NFC", password).casefold().encode("utf-8")).digest()
    for password in _PUBLIC_WEAK_PASSWORDS
)


def normalize_password_input(password: str) -> str:
    """规范登录密码；只限制危险或可放大输入，不改变合法空白。"""

    if type(password) is not str:
        raise ValueError("password must be a string")
    if "\x00" in password:
        raise ValueError("password contains a forbidden code point")
    normalized = unicodedata.normalize("NFC", password)
    if len(normalized.encode("utf-8")) > PASSWORD_MAX_UTF8_BYTES:
        raise ValueError("password exceeds the byte limit")
    if not PASSWORD_MIN_CODE_POINTS <= len(normalized) <= PASSWORD_MAX_CODE_POINTS:
        raise ValueError("password length is outside the approved range")
    return normalized


def validate_new_password(password: str) -> str:
    """返回可哈希的 NFC 密码，弱密码和越界输入固定失败。"""

    normalized = normalize_password_input(password)
    digest = hashlib.sha256(normalized.casefold().encode("utf-8")).digest()
    if digest in _BLOCKED_DIGESTS:
        raise ValueError("password is blocked by the local policy")
    return normalized


__all__ = [
    "PASSWORD_MAX_CODE_POINTS",
    "PASSWORD_MAX_UTF8_BYTES",
    "PASSWORD_MIN_CODE_POINTS",
    "PASSWORD_BLOCKLIST_SHA256",
    "PASSWORD_POLICY_VERSION",
    "normalize_password_input",
    "validate_new_password",
]
