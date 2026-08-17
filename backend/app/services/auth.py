"""auth-mvp-v1 登录、会话轮换、当前 Actor 与强制换密用例。"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Final, cast
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth_security import (
    AccessTokenClaims,
    TokenValidationError,
    hash_password,
    issue_access_token,
    issue_password_change_token,
    password_hash_needs_rehash,
    verify_access_token,
    verify_password,
    verify_password_change_token,
)
from app.core.errors import AppError
from app.core.password_policy import normalize_password_input, validate_new_password
from app.core.permissions import PermissionCode, RoleCode, derive_permissions
from app.core.refresh_tokens import RefreshToken, issue_refresh_token, parse_refresh_token
from app.models.auth import TokenSession, User
from app.repositories.auth import AuthRepository
from app.repositories.operation_log import OperationLogRepository
from app.schemas.auth import AuthSessionData, CurrentUserData

ACCESS_TOKEN_EXPIRES_SECONDS: Final = 900
PASSWORD_CHANGE_EXPIRES_SECONDS: Final = 300
LOGIN_FAILURE_LIMIT: Final = 5
LOGIN_LOCK_DURATION: Final = timedelta(minutes=15)
REFRESH_SESSION_TTL: Final = timedelta(days=7)
REMEMBERED_REFRESH_SESSION_TTL: Final = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class AuthKeyring:
    active_kid: str
    private_key: Ed25519PrivateKey
    public_keys: dict[str, Ed25519PublicKey]


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    user_id: UUID
    organization_id: UUID
    session_id: UUID
    roles: tuple[RoleCode, ...]
    permissions: tuple[PermissionCode, ...]

    def require(self, permission: PermissionCode) -> None:
        if permission not in self.permissions:
            raise AppError(
                status_code=403,
                code="AUTH_FORBIDDEN",
                message="无权执行该操作",
            )


@dataclass(frozen=True, slots=True)
class AuthSessionResult:
    data: AuthSessionData = field(repr=False)
    refresh: RefreshToken = field(repr=False)
    refresh_expires_at: datetime
    refresh_max_age_seconds: int


@dataclass(frozen=True, slots=True)
class PasswordChangeRequired:
    token: str = field(repr=False)


LoginResult = AuthSessionResult | PasswordChangeRequired


class AuthService:
    """每个公开方法拥有一个数据库事务，Token 不进入持久化明文。"""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        keyring: AuthKeyring,
        dummy_password_hash: str,
    ) -> None:
        self._session_factory = session_factory
        self._keyring = keyring
        self._dummy_password_hash = dummy_password_hash

    def login(
        self,
        username: str,
        password: str,
        *,
        remember_me: bool,
        trace_id: UUID | None = None,
    ) -> LoginResult:
        operation_trace_id = trace_id or uuid4()
        try:
            normalized_password = normalize_password_input(password)
        except ValueError:
            self._dummy_verify("")
            self._append_anonymous_login_failure(operation_trace_id)
            raise _invalid_credentials() from None

        pending_error: AppError | None = None
        result: LoginResult | None = None
        with self._session_factory.begin() as session:
            repository = AuthRepository(session)
            operation_logs = OperationLogRepository(session)
            user = repository.lock_user_by_username(username)
            if user is None:
                self._dummy_verify(normalized_password)
                pending_error = _invalid_credentials()
                operation_logs.append(
                    organization_id=None,
                    actor_kind="anonymous",
                    actor_id=None,
                    action_code="auth.login.failed",
                    outcome="denied",
                    resource_type=None,
                    resource_id=None,
                    trace_id=operation_trace_id,
                    change_summary={"failure_code": "invalid_credentials"},
                )
            else:
                now = repository.database_now()
                password_matches = self._verify_existing_password(
                    normalized_password,
                    user.password_hash,
                )
                login_state_allowed = self._login_state_allows_password(user, now)
                if not login_state_allowed or not password_matches:
                    if login_state_allowed:
                        self._record_login_failure(user, now)
                    pending_error = _invalid_credentials()
                    operation_logs.append(
                        organization_id=None,
                        actor_kind="anonymous",
                        actor_id=None,
                        action_code="auth.login.failed",
                        outcome="denied",
                        resource_type=None,
                        resource_id=None,
                        trace_id=operation_trace_id,
                        change_summary={"failure_code": "invalid_credentials"},
                    )
                else:
                    if password_hash_needs_rehash(user.password_hash):
                        user.password_hash = hash_password(normalized_password)
                        user.password_changed_at = now
                    user.failed_login_count = 0
                    user.locked_until = None
                    user.status = "active"
                    user.updated_at = now
                    user.row_version += 1
                    auth_epoch_us = _epoch_microseconds(user.token_invalid_before)
                    if user.force_change_on_login:
                        result = PasswordChangeRequired(
                            token=issue_password_change_token(
                                private_key=self._keyring.private_key,
                                kid=self._keyring.active_kid,
                                subject_id=user.id,
                                token_id=uuid4(),
                                auth_epoch_us=auth_epoch_us,
                                issued_at=now,
                            )
                        )
                    else:
                        session_id = uuid4()
                        refresh = issue_refresh_token(session_id)
                        refresh_expires_at = now + (
                            REMEMBERED_REFRESH_SESSION_TTL if remember_me else REFRESH_SESSION_TTL
                        )
                        repository.add_token_session(
                            TokenSession(
                                id=session_id,
                                user_id=user.id,
                                refresh_token_hash=refresh.digest,
                                issued_at=now,
                                expires_at=refresh_expires_at,
                                revoked_at=None,
                                revoke_reason=None,
                                ip_address=None,
                                user_agent=None,
                                last_seen_at=now,
                            )
                        )
                        result = self._build_session_result(
                            repository,
                            user,
                            session_id,
                            refresh,
                            refresh_expires_at,
                            now,
                        )
                    operation_logs.append(
                        organization_id=user.organization_id,
                        actor_kind="user",
                        actor_id=user.id,
                        action_code="auth.login.succeeded",
                        outcome="succeeded",
                        resource_type="user",
                        resource_id=user.id,
                        trace_id=operation_trace_id,
                        change_summary={},
                    )
        if pending_error is not None:
            raise pending_error
        if result is None:  # pragma: no cover - closed state table above
            raise RuntimeError("login transaction produced no result")
        return result

    def refresh(self, wire_token: str) -> AuthSessionResult:
        try:
            presented = parse_refresh_token(wire_token)
        except ValueError:
            raise _refresh_error("AUTH_REFRESH_EXPIRED") from None

        pending_error: AppError | None = None
        result: AuthSessionResult | None = None
        with self._session_factory.begin() as session:
            repository = AuthRepository(session)
            session_user_id = repository.find_session_user_id(presented.session_id)
            user = (
                repository.lock_user_by_id(session_user_id) if session_user_id is not None else None
            )
            token_session = repository.lock_token_session(presented.session_id)
            now = repository.database_now()
            if token_session is None or token_session.user_id != session_user_id:
                pending_error = _refresh_error("AUTH_REFRESH_EXPIRED")
            elif token_session.revoked_at is not None:
                pending_error = _refresh_error("AUTH_TOKEN_REVOKED")
            elif not hmac.compare_digest(token_session.refresh_token_hash, presented.digest):
                token_session.revoked_at = now
                token_session.revoke_reason = "refresh_reuse"
                pending_error = _refresh_error("AUTH_REUSE_DETECTED")
            elif token_session.expires_at <= now:
                token_session.revoked_at = now
                token_session.revoke_reason = "expired"
                pending_error = _refresh_error("AUTH_REFRESH_EXPIRED")
            else:
                if user is None or not _user_allows_session(user, token_session, now):
                    token_session.revoked_at = now
                    token_session.revoke_reason = "user_invalid"
                    pending_error = _refresh_error("AUTH_TOKEN_REVOKED")
                else:
                    rotated = issue_refresh_token(token_session.id)
                    token_session.refresh_token_hash = rotated.digest
                    token_session.last_seen_at = now
                    result = self._build_session_result(
                        repository,
                        user,
                        token_session.id,
                        rotated,
                        token_session.expires_at,
                        now,
                    )
        if pending_error is not None:
            raise pending_error
        if result is None:  # pragma: no cover - closed state table above
            raise RuntimeError("refresh transaction produced no result")
        return result

    def logout(self, wire_token: str | None, *, trace_id: UUID | None = None) -> None:
        operation_trace_id = trace_id or uuid4()
        if wire_token is None:
            self._append_anonymous_logout(operation_trace_id)
            return
        try:
            presented = parse_refresh_token(wire_token)
        except ValueError:
            self._append_anonymous_logout(operation_trace_id)
            return
        with self._session_factory.begin() as session:
            repository = AuthRepository(session)
            operation_logs = OperationLogRepository(session)
            token_session = repository.lock_token_session(presented.session_id)
            now = repository.database_now()
            recognized = bool(
                token_session is not None
                and hmac.compare_digest(token_session.refresh_token_hash, presented.digest)
            )
            if token_session is not None and token_session.revoked_at is None:
                token_session.revoked_at = now
                token_session.revoke_reason = "logout" if recognized else "refresh_reuse"
            user = (
                repository.read_user_identity_by_id(token_session.user_id)
                if recognized and token_session is not None
                else None
            )
            operation_logs.append(
                organization_id=user.organization_id if user is not None else None,
                actor_kind="user" if user is not None else "anonymous",
                actor_id=user.id if user is not None else None,
                action_code="auth.logout",
                outcome="succeeded",
                resource_type="user" if user is not None else None,
                resource_id=user.id if user is not None else None,
                trace_id=operation_trace_id,
                change_summary={"session_recognized": user is not None},
            )

    def record_authorization_denied(
        self,
        actor: AuthenticatedActor,
        permission: PermissionCode,
        trace_id: UUID,
    ) -> None:
        with self._session_factory.begin() as session:
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code="authorization.denied",
                outcome="denied",
                resource_type="user",
                resource_id=actor.user_id,
                trace_id=trace_id,
                change_summary={"permission_code": permission},
            )

    def _append_anonymous_login_failure(self, trace_id: UUID) -> None:
        with self._session_factory.begin() as session:
            OperationLogRepository(session).append(
                organization_id=None,
                actor_kind="anonymous",
                actor_id=None,
                action_code="auth.login.failed",
                outcome="denied",
                resource_type=None,
                resource_id=None,
                trace_id=trace_id,
                change_summary={"failure_code": "invalid_credentials"},
            )

    def _append_anonymous_logout(self, trace_id: UUID) -> None:
        with self._session_factory.begin() as session:
            OperationLogRepository(session).append(
                organization_id=None,
                actor_kind="anonymous",
                actor_id=None,
                action_code="auth.logout",
                outcome="succeeded",
                resource_type=None,
                resource_id=None,
                trace_id=trace_id,
                change_summary={"session_recognized": False},
            )

    def authenticate(self, access_token: str) -> tuple[AuthenticatedActor, CurrentUserData]:
        with self._session_factory() as session:
            repository = AuthRepository(session)
            now = repository.database_now()
            try:
                claims = verify_access_token(
                    access_token,
                    public_keys=self._keyring.public_keys,
                    now=now,
                )
            except (TokenValidationError, ValueError):
                raise _access_error("AUTH_ACCESS_EXPIRED") from None
            user = repository.read_user_by_id(claims.subject_id)
            token_session = repository.read_token_session(claims.session_id)
            if not _claims_match_session(claims, user, token_session, now):
                raise _access_error("AUTH_TOKEN_REVOKED")
            assert user is not None
            roles = _typed_roles(repository.active_role_codes(user.id, now))
            permissions = derive_permissions(roles)
            actor = AuthenticatedActor(
                user_id=user.id,
                organization_id=user.organization_id,
                session_id=claims.session_id,
                roles=roles,
                permissions=permissions,
            )
            return actor, _current_user(user, roles, permissions)

    def change_password(self, password_change_token: str, new_password: str) -> None:
        pending_error: AppError | None = None
        with self._session_factory.begin() as session:
            repository = AuthRepository(session)
            prelock_now = repository.database_now()
            try:
                claims = verify_password_change_token(
                    password_change_token,
                    public_keys=self._keyring.public_keys,
                    now=prelock_now,
                )
            except (TokenValidationError, ValueError):
                raise _access_error("AUTH_TOKEN_REVOKED") from None
            user = repository.lock_user_by_id(claims.subject_id)
            now = repository.database_now()
            try:
                claims = verify_password_change_token(
                    password_change_token,
                    public_keys=self._keyring.public_keys,
                    now=now,
                )
            except (TokenValidationError, ValueError):
                raise _access_error("AUTH_TOKEN_REVOKED") from None
            if (
                user is None
                or not user.force_change_on_login
                or user.status != "active"
                or _epoch_microseconds(user.token_invalid_before) != claims.auth_epoch_us
            ):
                pending_error = _access_error("AUTH_TOKEN_REVOKED")
            else:
                try:
                    normalized_password = validate_new_password(new_password)
                except ValueError:
                    raise AppError(
                        status_code=422,
                        code="VALIDATION_ERROR",
                        message="请求参数不符合约束",
                        details=[{"field": "body.new_password", "reason": "invalid"}],
                    ) from None
                user.password_hash = hash_password(normalized_password)
                user.password_changed_at = now
                user.force_change_on_login = False
                user.token_invalid_before = now
                user.failed_login_count = 0
                user.locked_until = None
                user.updated_at = now
                user.row_version += 1
                repository.revoke_all_user_sessions(user.id, now, "password_changed")
        if pending_error is not None:
            raise pending_error

    def _build_session_result(
        self,
        repository: AuthRepository,
        user: User,
        session_id: UUID,
        refresh: RefreshToken,
        refresh_expires_at: datetime,
        now: datetime,
    ) -> AuthSessionResult:
        roles = _typed_roles(repository.active_role_codes(user.id, now))
        permissions = derive_permissions(roles)
        access_token = issue_access_token(
            private_key=self._keyring.private_key,
            kid=self._keyring.active_kid,
            subject_id=user.id,
            session_id=session_id,
            token_id=uuid4(),
            auth_epoch_us=_epoch_microseconds(user.token_invalid_before),
            issued_at=now,
        )
        return AuthSessionResult(
            data=AuthSessionData(
                access_token=access_token,
                user=_current_user(user, roles, permissions),
            ),
            refresh=refresh,
            refresh_expires_at=refresh_expires_at,
            refresh_max_age_seconds=max(
                0,
                int((refresh_expires_at - now).total_seconds()),
            ),
        )

    def _dummy_verify(self, password: str) -> None:
        try:
            verify_password(password, self._dummy_password_hash)
        except ValueError:
            raise RuntimeError("dummy password hash does not match auth-mvp-v1") from None

    @staticmethod
    def _verify_existing_password(password: str, password_hash: str) -> bool:
        try:
            return verify_password(password, password_hash)
        except ValueError:
            return False

    @staticmethod
    def _login_state_allows_password(user: User, now: datetime) -> bool:
        if user.status == "locked":
            if user.locked_until is not None and user.locked_until <= now:
                user.status = "active"
                user.locked_until = None
                user.failed_login_count = 0
                return True
            return False
        if user.status != "active":
            return False
        return True

    @staticmethod
    def _record_login_failure(user: User, now: datetime) -> None:
        user.failed_login_count += 1
        user.updated_at = now
        user.row_version += 1
        if user.failed_login_count >= LOGIN_FAILURE_LIMIT:
            user.failed_login_count = LOGIN_FAILURE_LIMIT
            user.status = "locked"
            user.locked_until = now + LOGIN_LOCK_DURATION


def _current_user(
    user: User,
    roles: tuple[RoleCode, ...],
    permissions: tuple[PermissionCode, ...],
) -> CurrentUserData:
    return CurrentUserData(
        id=user.id,
        display_name=user.display_name,
        roles=roles,
        permissions=permissions,
    )


def _typed_roles(values: tuple[str, ...]) -> tuple[RoleCode, ...]:
    valid = {"system_admin", "finance_reviewer", "audit_reviewer", "contract_admin", "read_only"}
    if any(value not in valid for value in values):
        raise RuntimeError("database contains an unknown enabled role")
    return cast(tuple[RoleCode, ...], values)


def _epoch_microseconds(value: datetime) -> int:
    if value.tzinfo is None:
        raise RuntimeError("authentication timestamp must be timezone-aware")
    utc_value = value.astimezone(timezone.utc)
    delta = utc_value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _user_allows_session(user: User, token_session: TokenSession, now: datetime) -> bool:
    return (
        user.status == "active"
        and user.deleted_at is None
        and token_session.issued_at >= user.token_invalid_before
        and token_session.expires_at > now
    )


def _claims_match_session(
    claims: AccessTokenClaims,
    user: User | None,
    token_session: TokenSession | None,
    now: datetime,
) -> bool:
    return bool(
        user is not None
        and token_session is not None
        and token_session.user_id == claims.subject_id
        and token_session.revoked_at is None
        and token_session.expires_at > now
        and _user_allows_session(user, token_session, now)
        and _epoch_microseconds(user.token_invalid_before) == claims.auth_epoch_us
    )


def _invalid_credentials() -> AppError:
    return AppError(
        status_code=401,
        code="AUTH_INVALID_CREDENTIALS",
        message="用户名或密码错误",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _refresh_error(code: str) -> AppError:
    return AppError(
        status_code=401,
        code=code,
        message="会话已失效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _access_error(code: str) -> AppError:
    return AppError(
        status_code=401,
        code=code,
        message="认证已失效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )


__all__ = [
    "AuthenticatedActor",
    "AuthKeyring",
    "AuthService",
    "AuthSessionResult",
    "PasswordChangeRequired",
]
