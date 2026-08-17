"""auth-mvp-v1 的密码哈希与 JWT 密码学边界。"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final
from uuid import UUID

import jwt
from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import ARGON2_VERSION, Type
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

PASSWORD_MEMORY_COST_KIB: Final = 65_536
PASSWORD_TIME_COST: Final = 3
PASSWORD_PARALLELISM: Final = 1
PASSWORD_SALT_LENGTH: Final = 16
PASSWORD_HASH_LENGTH: Final = 32

TOKEN_ALGORITHM: Final = "EdDSA"
TOKEN_ISSUER: Final = "finaudit-agent"
ACCESS_TOKEN_AUDIENCE: Final = "finaudit-api"
ACCESS_TOKEN_TYPE: Final = "at+jwt"
ACCESS_TOKEN_PURPOSE: Final = "access"
ACCESS_TOKEN_TTL: Final = timedelta(minutes=15)
PASSWORD_CHANGE_TOKEN_AUDIENCE: Final = "finaudit-password-change"
PASSWORD_CHANGE_TOKEN_TYPE: Final = "pwd+jwt"
PASSWORD_CHANGE_TOKEN_PURPOSE: Final = "password:change"
PASSWORD_CHANGE_TOKEN_TTL: Final = timedelta(minutes=5)
TOKEN_LEEWAY: Final = timedelta(seconds=30)

_JSON_SAFE_INTEGER_MAX: Final = 9_007_199_254_740_991
_KID_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_BASE64URL_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]+$")
_JWT_HEADER_KEYS: Final = frozenset({"alg", "kid", "typ"})
_ACCESS_CLAIM_KEYS: Final = frozenset(
    {"iss", "aud", "sub", "sid", "jti", "purpose", "iat", "nbf", "exp", "auth_epoch_us"}
)
_PASSWORD_CHANGE_CLAIM_KEYS: Final = frozenset(
    {"iss", "aud", "sub", "jti", "purpose", "iat", "nbf", "exp", "auth_epoch_us"}
)
_PASSWORD_HASHER: Final = PasswordHasher(
    time_cost=PASSWORD_TIME_COST,
    memory_cost=PASSWORD_MEMORY_COST_KIB,
    parallelism=PASSWORD_PARALLELISM,
    salt_len=PASSWORD_SALT_LENGTH,
    hash_len=PASSWORD_HASH_LENGTH,
    type=Type.ID,
)


class TokenValidationError(ValueError):
    """JWT 不满足 auth-mvp-v1 时使用的无敏感信息异常。"""


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    subject_id: UUID
    session_id: UUID
    token_id: UUID
    auth_epoch_us: int
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PasswordChangeTokenClaims:
    subject_id: UUID
    token_id: UUID
    auth_epoch_us: int
    issued_at: datetime
    expires_at: datetime


def hash_password(password: str) -> str:
    """使用批准的 Argon2id Profile 生成 PHC；密码策略由调用方先执行。"""

    _require_password_text(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """验证 Argon2 支持的 PHC；错误密码返回 False，损坏 hash 失败关闭。"""

    _require_password_text(password)
    if type(password_hash) is not str or not password_hash:
        raise ValueError("password_hash must be a non-empty exact str")
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError) as exc:
        raise ValueError("password hash verification failed") from exc


def password_hash_needs_rehash(password_hash: str) -> bool:
    """判断 PHC 是否逐项匹配批准的 Argon2id Profile。"""

    if type(password_hash) is not str or not password_hash:
        return True
    try:
        parameters = extract_parameters(password_hash)
    except InvalidHashError:
        return True
    return not (
        parameters.type is Type.ID
        and parameters.version == ARGON2_VERSION
        and parameters.memory_cost == PASSWORD_MEMORY_COST_KIB
        and parameters.time_cost == PASSWORD_TIME_COST
        and parameters.parallelism == PASSWORD_PARALLELISM
        and parameters.salt_len == PASSWORD_SALT_LENGTH
        and parameters.hash_len == PASSWORD_HASH_LENGTH
        and not _PASSWORD_HASHER.check_needs_rehash(password_hash)
    )


def issue_access_token(
    *,
    private_key: Ed25519PrivateKey,
    kid: str,
    subject_id: UUID,
    session_id: UUID,
    token_id: UUID,
    auth_epoch_us: int,
    issued_at: datetime,
) -> str:
    """签发固定 15 分钟、固定 claims 的 Access JWT。"""

    claims = _base_claims(
        audience=ACCESS_TOKEN_AUDIENCE,
        purpose=ACCESS_TOKEN_PURPOSE,
        subject_id=subject_id,
        token_id=token_id,
        auth_epoch_us=auth_epoch_us,
        issued_at=issued_at,
        ttl=ACCESS_TOKEN_TTL,
    )
    claims["sid"] = _canonical_uuid(session_id, "session_id")
    return _issue_token(
        private_key=private_key,
        kid=kid,
        token_type=ACCESS_TOKEN_TYPE,
        claims=claims,
    )


def issue_password_change_token(
    *,
    private_key: Ed25519PrivateKey,
    kid: str,
    subject_id: UUID,
    token_id: UUID,
    auth_epoch_us: int,
    issued_at: datetime,
) -> str:
    """签发固定 5 分钟且不能替代 Access 的强制换密 JWT。"""

    claims = _base_claims(
        audience=PASSWORD_CHANGE_TOKEN_AUDIENCE,
        purpose=PASSWORD_CHANGE_TOKEN_PURPOSE,
        subject_id=subject_id,
        token_id=token_id,
        auth_epoch_us=auth_epoch_us,
        issued_at=issued_at,
        ttl=PASSWORD_CHANGE_TOKEN_TTL,
    )
    return _issue_token(
        private_key=private_key,
        kid=kid,
        token_type=PASSWORD_CHANGE_TOKEN_TYPE,
        claims=claims,
    )


def verify_access_token(
    token: str,
    *,
    public_keys: Mapping[str, Ed25519PublicKey],
    now: datetime,
) -> AccessTokenClaims:
    """按 Access 专用的互斥规则验签并解析 claims。"""

    payload = _verify_token(
        token,
        public_keys=public_keys,
        now=now,
        token_type=ACCESS_TOKEN_TYPE,
        audience=ACCESS_TOKEN_AUDIENCE,
        purpose=ACCESS_TOKEN_PURPOSE,
        ttl=ACCESS_TOKEN_TTL,
        claim_keys=_ACCESS_CLAIM_KEYS,
    )
    return AccessTokenClaims(
        subject_id=_parse_uuid(payload["sub"], "sub"),
        session_id=_parse_uuid(payload["sid"], "sid"),
        token_id=_parse_uuid(payload["jti"], "jti"),
        auth_epoch_us=_parse_auth_epoch(payload["auth_epoch_us"]),
        issued_at=_numeric_date(payload["iat"], "iat"),
        expires_at=_numeric_date(payload["exp"], "exp"),
    )


def verify_password_change_token(
    token: str,
    *,
    public_keys: Mapping[str, Ed25519PublicKey],
    now: datetime,
) -> PasswordChangeTokenClaims:
    """按 password-change 专用的互斥规则验签并解析 claims。"""

    payload = _verify_token(
        token,
        public_keys=public_keys,
        now=now,
        token_type=PASSWORD_CHANGE_TOKEN_TYPE,
        audience=PASSWORD_CHANGE_TOKEN_AUDIENCE,
        purpose=PASSWORD_CHANGE_TOKEN_PURPOSE,
        ttl=PASSWORD_CHANGE_TOKEN_TTL,
        claim_keys=_PASSWORD_CHANGE_CLAIM_KEYS,
    )
    return PasswordChangeTokenClaims(
        subject_id=_parse_uuid(payload["sub"], "sub"),
        token_id=_parse_uuid(payload["jti"], "jti"),
        auth_epoch_us=_parse_auth_epoch(payload["auth_epoch_us"]),
        issued_at=_numeric_date(payload["iat"], "iat"),
        expires_at=_numeric_date(payload["exp"], "exp"),
    )


def _require_password_text(password: str) -> None:
    if type(password) is not str:
        raise ValueError("password must be an exact str")


def _canonical_uuid(value: UUID, field: str) -> str:
    if type(value) is not UUID:
        raise ValueError(f"{field} must be an exact UUID")
    return str(value)


def _parse_uuid(value: object, field: str) -> UUID:
    if type(value) is not str:
        raise TokenValidationError(f"{field} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError) as exc:
        raise TokenValidationError(f"{field} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise TokenValidationError(f"{field} must be a canonical UUID")
    return parsed


def _require_auth_epoch(value: int) -> int:
    if type(value) is not int or not 0 <= value <= _JSON_SAFE_INTEGER_MAX:
        raise ValueError("auth_epoch_us must be a non-negative JSON-safe integer")
    return value


def _parse_auth_epoch(value: object) -> int:
    if type(value) is not int or not 0 <= value <= _JSON_SAFE_INTEGER_MAX:
        raise TokenValidationError("auth_epoch_us must be a non-negative JSON-safe integer")
    return value


def _utc_numeric_date(value: datetime, field: str) -> int:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be an exact UTC datetime")
    return int(value.timestamp())


def _numeric_date(value: object, field: str) -> datetime:
    if type(value) is not int or not 0 <= value <= _JSON_SAFE_INTEGER_MAX:
        raise TokenValidationError(f"{field} must be a non-negative JSON-safe integer")
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OSError, OverflowError, ValueError) as exc:
        raise TokenValidationError(f"{field} is outside the supported time range") from exc


def _base_claims(
    *,
    audience: str,
    purpose: str,
    subject_id: UUID,
    token_id: UUID,
    auth_epoch_us: int,
    issued_at: datetime,
    ttl: timedelta,
) -> dict[str, object]:
    issued_at_seconds = _utc_numeric_date(issued_at, "issued_at")
    return {
        "iss": TOKEN_ISSUER,
        "aud": audience,
        "sub": _canonical_uuid(subject_id, "subject_id"),
        "jti": _canonical_uuid(token_id, "token_id"),
        "purpose": purpose,
        "iat": issued_at_seconds,
        "nbf": issued_at_seconds,
        "exp": issued_at_seconds + int(ttl.total_seconds()),
        "auth_epoch_us": _require_auth_epoch(auth_epoch_us),
    }


def _validate_kid(kid: str) -> str:
    if type(kid) is not str or _KID_PATTERN.fullmatch(kid) is None:
        raise ValueError("kid does not match auth-mvp-v1")
    return kid


def _issue_token(
    *,
    private_key: Ed25519PrivateKey,
    kid: str,
    token_type: str,
    claims: dict[str, object],
) -> str:
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("private_key must be an Ed25519 private key")
    return jwt.encode(
        claims,
        private_key,
        algorithm=TOKEN_ALGORITHM,
        headers={"kid": _validate_kid(kid), "typ": token_type},
    )


def _decode_segment(segment: str) -> bytes:
    if _BASE64URL_PATTERN.fullmatch(segment) is None:
        raise TokenValidationError("token is not canonical compact JWT")
    try:
        decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (ValueError, binascii.Error) as exc:
        raise TokenValidationError("token is not canonical compact JWT") from exc
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != segment:
        raise TokenValidationError("token is not canonical compact JWT")
    return decoded


def _strict_json_object(raw: bytes) -> dict[str, object]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise TokenValidationError("token contains duplicate JSON members")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenValidationError("token contains invalid JSON") from exc
    if type(value) is not dict:
        raise TokenValidationError("token JSON must be an object")
    return value


def _preflight_token(token: str) -> tuple[dict[str, object], dict[str, object]]:
    if type(token) is not str:
        raise TokenValidationError("token must be an exact str")
    segments = token.split(".")
    if len(segments) != 3 or any(not segment for segment in segments):
        raise TokenValidationError("token is not canonical compact JWT")
    header = _strict_json_object(_decode_segment(segments[0]))
    payload = _strict_json_object(_decode_segment(segments[1]))
    if len(_decode_segment(segments[2])) != 64:
        raise TokenValidationError("token signature has an invalid length")
    return header, payload


def _verify_token(
    token: str,
    *,
    public_keys: Mapping[str, Ed25519PublicKey],
    now: datetime,
    token_type: str,
    audience: str,
    purpose: str,
    ttl: timedelta,
    claim_keys: frozenset[str],
) -> dict[str, object]:
    now_seconds = _utc_numeric_date(now, "now")
    header, payload = _preflight_token(token)
    if frozenset(header) != _JWT_HEADER_KEYS:
        raise TokenValidationError("token header does not match auth-mvp-v1")
    if header.get("alg") != TOKEN_ALGORITHM or header.get("typ") != token_type:
        raise TokenValidationError("token type does not match the expected purpose")
    kid = header.get("kid")
    if type(kid) is not str or _KID_PATTERN.fullmatch(kid) is None:
        raise TokenValidationError("token kid is invalid")
    key = public_keys.get(kid)
    if not isinstance(key, Ed25519PublicKey):
        raise TokenValidationError("token kid is not trusted")
    if frozenset(payload) != claim_keys:
        raise TokenValidationError("token claims do not match the expected purpose")
    if payload.get("iss") != TOKEN_ISSUER:
        raise TokenValidationError("token issuer is invalid")
    if payload.get("aud") != audience or payload.get("purpose") != purpose:
        raise TokenValidationError("token purpose is invalid")
    _parse_uuid(payload.get("sub"), "sub")
    _parse_uuid(payload.get("jti"), "jti")
    if "sid" in claim_keys:
        _parse_uuid(payload.get("sid"), "sid")
    _parse_auth_epoch(payload.get("auth_epoch_us"))
    iat = payload.get("iat")
    nbf = payload.get("nbf")
    exp = payload.get("exp")
    for field, value in (("iat", iat), ("nbf", nbf), ("exp", exp)):
        _numeric_date(value, field)
    if iat != nbf or type(iat) is not int or type(exp) is not int:
        raise TokenValidationError("token time claims are invalid")
    if exp != iat + int(ttl.total_seconds()):
        raise TokenValidationError("token lifetime is invalid")
    leeway_seconds = int(TOKEN_LEEWAY.total_seconds())
    if iat > now_seconds + leeway_seconds or now_seconds >= exp + leeway_seconds:
        raise TokenValidationError("token is outside its validity window")
    try:
        decoded = jwt.decode_complete(
            token,
            key,
            algorithms=[TOKEN_ALGORITHM],
            audience=audience,
            issuer=TOKEN_ISSUER,
            options={
                "require": sorted(claim_keys),
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
                "strict_aud": True,
            },
        )
    except jwt.PyJWTError as exc:
        raise TokenValidationError("token signature or registered claims are invalid") from exc
    if decoded.get("header") != header or decoded.get("payload") != payload:
        raise TokenValidationError("token parser results are inconsistent")
    return payload
