"""auth-mvp-v1 opaque Refresh Token 生成、解析与摘要。"""

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass, field
from uuid import UUID

_SECRET_BYTES = 32
_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


@dataclass(frozen=True, slots=True)
class RefreshToken:
    session_id: UUID
    wire_value: str = field(repr=False)
    digest: str = field(repr=False)


def _digest(wire_value: str) -> str:
    return hashlib.sha256(wire_value.encode("ascii")).hexdigest()


def issue_refresh_token(session_id: UUID) -> RefreshToken:
    if type(session_id) is not UUID:
        raise ValueError("session_id must be an exact UUID")
    encoded_secret = base64.urlsafe_b64encode(secrets.token_bytes(_SECRET_BYTES)).rstrip(b"=")
    wire_value = f"{session_id}.{encoded_secret.decode('ascii')}"
    return RefreshToken(session_id=session_id, wire_value=wire_value, digest=_digest(wire_value))


def parse_refresh_token(wire_value: str) -> RefreshToken:
    if type(wire_value) is not str or len(wire_value) != 80:
        raise ValueError("refresh token format is invalid")
    session_text, separator, encoded_secret = wire_value.partition(".")
    if separator != "." or not _SECRET_PATTERN.fullmatch(encoded_secret):
        raise ValueError("refresh token format is invalid")
    try:
        session_id = UUID(session_text)
        secret = base64.urlsafe_b64decode(encoded_secret + "=")
    except (ValueError, TypeError):
        raise ValueError("refresh token format is invalid") from None
    if str(session_id) != session_text or len(secret) != _SECRET_BYTES:
        raise ValueError("refresh token format is invalid")
    return RefreshToken(session_id=session_id, wire_value=wire_value, digest=_digest(wire_value))


__all__ = ["RefreshToken", "issue_refresh_token", "parse_refresh_token"]
