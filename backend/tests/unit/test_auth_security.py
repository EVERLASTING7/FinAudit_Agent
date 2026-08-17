from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
import pytest
from argon2 import PasswordHasher, extract_parameters
from argon2.low_level import Type
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.auth_security import (
    ACCESS_TOKEN_AUDIENCE,
    ACCESS_TOKEN_PURPOSE,
    ACCESS_TOKEN_TTL,
    ACCESS_TOKEN_TYPE,
    PASSWORD_CHANGE_TOKEN_AUDIENCE,
    PASSWORD_CHANGE_TOKEN_PURPOSE,
    PASSWORD_CHANGE_TOKEN_TTL,
    PASSWORD_CHANGE_TOKEN_TYPE,
    PASSWORD_HASH_LENGTH,
    PASSWORD_MEMORY_COST_KIB,
    PASSWORD_PARALLELISM,
    PASSWORD_SALT_LENGTH,
    PASSWORD_TIME_COST,
    TOKEN_ALGORITHM,
    TOKEN_ISSUER,
    AccessTokenClaims,
    PasswordChangeTokenClaims,
    TokenValidationError,
    hash_password,
    issue_access_token,
    issue_password_change_token,
    password_hash_needs_rehash,
    verify_access_token,
    verify_password,
    verify_password_change_token,
)

_KID = "authkey01"
_ISSUED_AT = datetime(2026, 8, 12, 4, 5, 6, 789_000, tzinfo=timezone.utc)
_SUBJECT_ID = UUID("00000000-0000-0000-0000-000000000101")
_SESSION_ID = UUID("00000000-0000-0000-0000-000000000102")
_TOKEN_ID = UUID("00000000-0000-0000-0000-000000000103")
_AUTH_EPOCH_US = 1_786_508_706_123_456


@pytest.fixture
def private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _access_token(private_key: Ed25519PrivateKey) -> str:
    return issue_access_token(
        private_key=private_key,
        kid=_KID,
        subject_id=_SUBJECT_ID,
        session_id=_SESSION_ID,
        token_id=_TOKEN_ID,
        auth_epoch_us=_AUTH_EPOCH_US,
        issued_at=_ISSUED_AT,
    )


def _password_change_token(private_key: Ed25519PrivateKey) -> str:
    return issue_password_change_token(
        private_key=private_key,
        kid=_KID,
        subject_id=_SUBJECT_ID,
        token_id=_TOKEN_ID,
        auth_epoch_us=_AUTH_EPOCH_US,
        issued_at=_ISSUED_AT,
    )


def _signed_token(
    private_key: Ed25519PrivateKey,
    payload: dict[str, object],
    *,
    token_type: str = ACCESS_TOKEN_TYPE,
    kid: str = _KID,
    extra_header: dict[str, object] | None = None,
) -> str:
    headers: dict[str, object] = {"kid": kid, "typ": token_type}
    if extra_header:
        headers.update(extra_header)
    return jwt.encode(payload, private_key, algorithm=TOKEN_ALGORITHM, headers=headers)


def test_password_hash_uses_exact_argon2id_profile_and_random_salts() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    parameters = extract_parameters(first)

    assert first != second
    assert parameters.type is Type.ID
    assert parameters.memory_cost == PASSWORD_MEMORY_COST_KIB
    assert parameters.time_cost == PASSWORD_TIME_COST
    assert parameters.parallelism == PASSWORD_PARALLELISM
    assert parameters.salt_len == PASSWORD_SALT_LENGTH
    assert parameters.hash_len == PASSWORD_HASH_LENGTH
    assert password_hash_needs_rehash(first) is False
    assert verify_password("correct horse battery staple", first) is True
    assert verify_password("wrong password", first) is False


def test_old_password_hash_verifies_then_reports_rehash_need() -> None:
    drifted = PasswordHasher(
        memory_cost=19_456,
        time_cost=2,
        parallelism=1,
        salt_len=16,
        hash_len=32,
        type=Type.ID,
    ).hash("password")

    assert password_hash_needs_rehash(drifted) is True
    assert verify_password("password", drifted) is True
    assert verify_password("wrong password", drifted) is False


def test_invalid_password_phc_fails_closed() -> None:
    assert password_hash_needs_rehash("not-a-phc") is True
    with pytest.raises(ValueError, match="verification failed"):
        verify_password("password", "not-a-phc")
    with pytest.raises(ValueError, match="exact str"):
        hash_password(b"password")  # type: ignore[arg-type]


def test_access_token_has_exact_header_claims_and_fixed_lifetime(
    private_key: Ed25519PrivateKey,
) -> None:
    token = _access_token(private_key)
    header = jwt.get_unverified_header(token)
    payload = jwt.decode(token, options={"verify_signature": False})

    assert header == {"alg": TOKEN_ALGORITHM, "kid": _KID, "typ": ACCESS_TOKEN_TYPE}
    assert set(payload) == {
        "iss",
        "aud",
        "sub",
        "sid",
        "jti",
        "purpose",
        "iat",
        "nbf",
        "exp",
        "auth_epoch_us",
    }
    assert payload["iss"] == TOKEN_ISSUER
    assert payload["aud"] == ACCESS_TOKEN_AUDIENCE
    assert payload["purpose"] == ACCESS_TOKEN_PURPOSE
    assert payload["iat"] == payload["nbf"] == int(_ISSUED_AT.timestamp())
    assert payload["exp"] - payload["iat"] == int(ACCESS_TOKEN_TTL.total_seconds())

    claims = verify_access_token(
        token,
        public_keys={_KID: private_key.public_key()},
        now=_ISSUED_AT,
    )
    assert claims == AccessTokenClaims(
        subject_id=_SUBJECT_ID,
        session_id=_SESSION_ID,
        token_id=_TOKEN_ID,
        auth_epoch_us=_AUTH_EPOCH_US,
        issued_at=_ISSUED_AT.replace(microsecond=0),
        expires_at=_ISSUED_AT.replace(microsecond=0) + ACCESS_TOKEN_TTL,
    )


def test_password_change_token_has_distinct_audience_type_and_no_session(
    private_key: Ed25519PrivateKey,
) -> None:
    token = _password_change_token(private_key)
    header = jwt.get_unverified_header(token)
    payload = jwt.decode(token, options={"verify_signature": False})

    assert header["typ"] == PASSWORD_CHANGE_TOKEN_TYPE
    assert payload["aud"] == PASSWORD_CHANGE_TOKEN_AUDIENCE
    assert payload["purpose"] == PASSWORD_CHANGE_TOKEN_PURPOSE
    assert "sid" not in payload
    assert payload["exp"] - payload["iat"] == int(PASSWORD_CHANGE_TOKEN_TTL.total_seconds())

    claims = verify_password_change_token(
        token,
        public_keys={_KID: private_key.public_key()},
        now=_ISSUED_AT,
    )
    assert claims == PasswordChangeTokenClaims(
        subject_id=_SUBJECT_ID,
        token_id=_TOKEN_ID,
        auth_epoch_us=_AUTH_EPOCH_US,
        issued_at=_ISSUED_AT.replace(microsecond=0),
        expires_at=_ISSUED_AT.replace(microsecond=0) + PASSWORD_CHANGE_TOKEN_TTL,
    )


def test_token_types_cannot_substitute_for_each_other(private_key: Ed25519PrivateKey) -> None:
    public_keys = {_KID: private_key.public_key()}

    with pytest.raises(TokenValidationError):
        verify_access_token(
            _password_change_token(private_key),
            public_keys=public_keys,
            now=_ISSUED_AT,
        )
    with pytest.raises(TokenValidationError):
        verify_password_change_token(
            _access_token(private_key),
            public_keys=public_keys,
            now=_ISSUED_AT,
        )


def test_unknown_kid_tampering_and_extra_claims_fail_closed(
    private_key: Ed25519PrivateKey,
) -> None:
    token = _access_token(private_key)
    public_keys = {_KID: private_key.public_key()}

    with pytest.raises(TokenValidationError, match="not trusted"):
        verify_access_token(token, public_keys={}, now=_ISSUED_AT)

    tampered = f"{token[:-1]}{'A' if token[-1] != 'A' else 'B'}"
    with pytest.raises(TokenValidationError):
        verify_access_token(tampered, public_keys=public_keys, now=_ISSUED_AT)

    payload = jwt.decode(token, options={"verify_signature": False})
    payload["roles"] = ["system_admin"]
    extra_claim_token = _signed_token(private_key, payload)
    with pytest.raises(TokenValidationError, match="claims"):
        verify_access_token(extra_claim_token, public_keys=public_keys, now=_ISSUED_AT)

    extra_header_token = _signed_token(
        private_key, payload | {"roles": None}, extra_header={"x": 1}
    )
    with pytest.raises(TokenValidationError, match="header"):
        verify_access_token(extra_header_token, public_keys=public_keys, now=_ISSUED_AT)

    wrong_algorithm = jwt.encode(
        payload,
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        algorithm="HS512",
        headers={"kid": _KID, "typ": ACCESS_TOKEN_TYPE},
    )
    with pytest.raises(TokenValidationError, match="type"):
        verify_access_token(wrong_algorithm, public_keys=public_keys, now=_ISSUED_AT)


def test_wrong_audience_purpose_lifetime_and_uuid_fail_closed(
    private_key: Ed25519PrivateKey,
) -> None:
    token = _access_token(private_key)
    payload = jwt.decode(token, options={"verify_signature": False})
    public_keys = {_KID: private_key.public_key()}

    for changes in (
        {"aud": PASSWORD_CHANGE_TOKEN_AUDIENCE},
        {"purpose": PASSWORD_CHANGE_TOKEN_PURPOSE},
        {"exp": payload["exp"] + 1},
        {"sub": "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"},
        {"auth_epoch_us": True},
    ):
        invalid = _signed_token(private_key, payload | changes)
        with pytest.raises(TokenValidationError):
            verify_access_token(invalid, public_keys=public_keys, now=_ISSUED_AT)


def test_validity_window_uses_explicit_clock_and_thirty_second_leeway(
    private_key: Ed25519PrivateKey,
) -> None:
    token = _access_token(private_key)
    public_keys = {_KID: private_key.public_key()}
    issued_at = _ISSUED_AT.replace(microsecond=0)

    verify_access_token(token, public_keys=public_keys, now=issued_at - timedelta(seconds=30))
    verify_access_token(
        token,
        public_keys=public_keys,
        now=issued_at + ACCESS_TOKEN_TTL + timedelta(seconds=29),
    )
    with pytest.raises(TokenValidationError, match="validity window"):
        verify_access_token(
            token,
            public_keys=public_keys,
            now=issued_at + ACCESS_TOKEN_TTL + timedelta(seconds=30),
        )


def test_signing_rejects_invalid_key_id_time_and_auth_epoch(
    private_key: Ed25519PrivateKey,
) -> None:
    arguments = {
        "private_key": private_key,
        "kid": _KID,
        "subject_id": _SUBJECT_ID,
        "session_id": _SESSION_ID,
        "token_id": _TOKEN_ID,
        "auth_epoch_us": _AUTH_EPOCH_US,
        "issued_at": _ISSUED_AT,
    }
    with pytest.raises(ValueError, match="kid"):
        issue_access_token(**(arguments | {"kid": "short"}))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="UTC"):
        issue_access_token(
            **(arguments | {"issued_at": datetime(2026, 8, 12)})  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="auth_epoch_us"):
        issue_access_token(**(arguments | {"auth_epoch_us": -1}))  # type: ignore[arg-type]
