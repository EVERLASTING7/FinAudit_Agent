"""user-management-write-v1 的事务、CAS、幂等与审计用例。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth_security import hash_password
from app.core.errors import AppError
from app.core.password_policy import validate_new_password
from app.core.permissions import RoleCode
from app.models.auth import Role, User, UserRole
from app.repositories.operation_log import OperationLogRepository
from app.repositories.user_write import IdempotencyClaim, UserWriteRepository
from app.schemas.users import (
    UserCreateRequest,
    UserListItemData,
    UserPasswordResetRequest,
    UserRolesReplaceRequest,
    UserStatus,
    UserStatusUpdateRequest,
)
from app.services.auth import AuthenticatedActor

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_IDEMPOTENCY_TTL = timedelta(hours=24)
_REVIEWER_ROLES = frozenset({"finance_reviewer", "audit_reviewer"})


@dataclass(frozen=True, slots=True)
class UserMutationResult:
    data: UserListItemData
    status_code: int
    replayed: bool


def _request_hash(method: str, path: str, body: dict[str, object]) -> str:
    encoded = json.dumps(
        {"method": method, "path": path, "body": body},
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_idempotency_key(value: str) -> None:
    if type(value) is not str or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": "header.Idempotency-Key", "reason": "invalid"}],
        )


def _hash_new_password(value: str, field_name: str) -> str:
    try:
        normalized = validate_new_password(value)
    except ValueError:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": field_name, "reason": "invalid"}],
        ) from None
    return hash_password(normalized)


def _resource_not_found() -> AppError:
    return AppError(status_code=404, code="RESOURCE_NOT_FOUND", message="资源不存在")


def _conflict(code: str, message: str) -> AppError:
    return AppError(status_code=409, code=code, message=message)


def _project_user(user: User, role_codes: tuple[str, ...]) -> UserListItemData:
    return UserListItemData(
        id=user.id,
        username=str(user.username),
        display_name=user.display_name,
        status=cast(UserStatus, user.status),
        fixed_roles=cast(tuple[RoleCode, ...], role_codes),
        row_version=str(user.row_version),
    )


def _replay_result(claim: IdempotencyClaim, expected_status: int) -> UserMutationResult:
    if claim.replay_status != expected_status or claim.replay_body is None:
        raise RuntimeError("idempotency replay response does not match the endpoint contract")
    encoded = json.dumps(
        claim.replay_body,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return UserMutationResult(
        data=UserListItemData.model_validate_json(encoded),
        status_code=expected_status,
        replayed=True,
    )


def _assert_roles_available(
    repository: UserWriteRepository,
    role_codes: tuple[RoleCode, ...],
) -> dict[str, Role]:
    roles = repository.lock_enabled_roles(role_codes)
    if set(roles) != set(role_codes):
        raise _conflict("ROLE_SET_UNAVAILABLE", "固定角色集合不可用")
    if "system_admin" in role_codes and _REVIEWER_ROLES.intersection(role_codes):
        raise _conflict("ROLE_SEPARATION_CONFLICT", "长期角色违反职责分离")
    return roles


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


class UserManagementService:
    """四个用户管理写动作；每个公开方法拥有一个 PostgreSQL 事务。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_user(
        self,
        actor: AuthenticatedActor,
        payload: UserCreateRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> UserMutationResult:
        _validate_idempotency_key(idempotency_key)
        password_hash = _hash_new_password(payload.initial_password, "body.initial_password")
        path = "/api/v1/users"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository = UserWriteRepository(session)
                claim, now = self._claim(
                    repository,
                    actor,
                    idempotency_key,
                    "POST",
                    path,
                    digest,
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return _replay_result(claim, 201)

                roles = _assert_roles_available(repository, payload.fixed_roles)
                user = User(
                    id=uuid4(),
                    organization_id=actor.organization_id,
                    username=payload.username,
                    display_name=payload.display_name,
                    password_hash=password_hash,
                    status="active",
                    failed_login_count=0,
                    locked_until=None,
                    password_changed_at=now,
                    force_change_on_login=True,
                    token_invalid_before=now,
                    row_version=1,
                    created_at=now,
                    created_by=actor.user_id,
                    updated_at=now,
                    updated_by=actor.user_id,
                )
                repository.add(user)
                repository.flush()
                for role_code in payload.fixed_roles:
                    role = roles[role_code]
                    repository.add(
                        UserRole(
                            id=uuid4(),
                            user_id=user.id,
                            role_id=role.id,
                            assigned_by=actor.user_id,
                            assignment_source="user",
                            assigned_at=now,
                            expires_at=None,
                            break_glass_request_id=None,
                            assignment_reason="fixed_role_replacement",
                        )
                    )
                data = _project_user(user, payload.fixed_roles)
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="users.created",
                    outcome="succeeded",
                    resource_type="user",
                    resource_id=user.id,
                    trace_id=trace_id,
                    change_summary={
                        "fixed_roles": list(payload.fixed_roles),
                        "row_version": data.row_version,
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_status=201,
                    response_body=data.model_dump(mode="json"),
                    resource_id=user.id,
                )
                return UserMutationResult(data=data, status_code=201, replayed=False)
        except IntegrityError as error:
            if _constraint_name(error) == "uq_users_username_active":
                raise _conflict("USERNAME_CONFLICT", "用户名已存在") from None
            raise

    def update_status(
        self,
        actor: AuthenticatedActor,
        user_id: UUID,
        payload: UserStatusUpdateRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> UserMutationResult:
        path = f"/api/v1/users/{user_id}/status"
        return self._mutate_status(
            actor,
            user_id,
            payload,
            idempotency_key,
            trace_id,
            path,
        )

    def reset_password(
        self,
        actor: AuthenticatedActor,
        user_id: UUID,
        payload: UserPasswordResetRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> UserMutationResult:
        _validate_idempotency_key(idempotency_key)
        password_hash = _hash_new_password(payload.new_password, "body.new_password")
        path = f"/api/v1/users/{user_id}/password/reset"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        with self._session_factory.begin() as session:
            repository = UserWriteRepository(session)
            claim, now = self._claim(
                repository,
                actor,
                idempotency_key,
                "POST",
                path,
                digest,
            )
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return _replay_result(claim, 200)
            user = self._lock_target(repository, actor.organization_id, user_id)
            self._assert_row_version(user, payload.row_version)
            assignments = repository.lock_active_fixed_assignments(user.id, now)
            role_codes = tuple(sorted({role_code for _, role_code in assignments}))

            user.password_hash = password_hash
            user.password_changed_at = now
            user.force_change_on_login = True
            user.token_invalid_before = now
            user.failed_login_count = 0
            user.locked_until = None
            if user.status == "locked":
                user.status = "active"
            user.updated_at = now
            user.updated_by = actor.user_id
            user.row_version += 1
            repository.revoke_all_user_sessions(user.id, now, "admin_password_reset")
            data = _project_user(user, role_codes)
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code="users.password_reset",
                outcome="succeeded",
                resource_type="user",
                resource_id=user.id,
                trace_id=trace_id,
                change_summary={"row_version": data.row_version},
            )
            repository.complete_idempotency(
                claim,
                response_status=200,
                response_body=data.model_dump(mode="json"),
                resource_id=user.id,
            )
            return UserMutationResult(data=data, status_code=200, replayed=False)

    def replace_roles(
        self,
        actor: AuthenticatedActor,
        user_id: UUID,
        payload: UserRolesReplaceRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> UserMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/users/{user_id}/roles"
        digest = _request_hash("PUT", path, payload.model_dump(mode="json"))
        with self._session_factory.begin() as session:
            repository = UserWriteRepository(session)
            claim, now = self._claim(
                repository,
                actor,
                idempotency_key,
                "PUT",
                path,
                digest,
            )
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return _replay_result(claim, 200)
            user = self._lock_target(repository, actor.organization_id, user_id)
            self._assert_row_version(user, payload.row_version)
            roles = _assert_roles_available(repository, payload.fixed_roles)
            assignments = repository.lock_active_fixed_assignments(user.id, now)
            current_roles = tuple(sorted({role_code for _, role_code in assignments}))
            if current_roles == payload.fixed_roles:
                raise _conflict("USER_STATE_UNCHANGED", "用户角色未发生变化")
            self._assert_last_admin_preserved(
                repository,
                user,
                current_roles,
                target_will_be_active_admin=(
                    user.status == "active" and "system_admin" in payload.fixed_roles
                ),
                now=now,
            )

            requested = set(payload.fixed_roles)
            for assignment, role_code in assignments:
                if role_code not in requested:
                    assignment.revoked_at = now
                    assignment.revoked_by = actor.user_id
                    assignment.revoke_reason = "fixed_role_replacement"
            current = set(current_roles)
            for role_code in payload.fixed_roles:
                if role_code not in current:
                    role = roles[role_code]
                    repository.add(
                        UserRole(
                            id=uuid4(),
                            user_id=user.id,
                            role_id=role.id,
                            assigned_by=actor.user_id,
                            assignment_source="user",
                            assigned_at=now,
                            expires_at=None,
                            break_glass_request_id=None,
                            assignment_reason="fixed_role_replacement",
                        )
                    )
            user.updated_at = now
            user.updated_by = actor.user_id
            user.row_version += 1
            data = _project_user(user, payload.fixed_roles)
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code="users.roles_replaced",
                outcome="succeeded",
                resource_type="user",
                resource_id=user.id,
                trace_id=trace_id,
                change_summary={
                    "old_roles": list(current_roles),
                    "new_roles": list(payload.fixed_roles),
                    "row_version": data.row_version,
                },
            )
            repository.complete_idempotency(
                claim,
                response_status=200,
                response_body=data.model_dump(mode="json"),
                resource_id=user.id,
            )
            return UserMutationResult(data=data, status_code=200, replayed=False)

    def _mutate_status(
        self,
        actor: AuthenticatedActor,
        user_id: UUID,
        payload: UserStatusUpdateRequest,
        idempotency_key: str,
        trace_id: UUID,
        path: str,
    ) -> UserMutationResult:
        _validate_idempotency_key(idempotency_key)
        digest = _request_hash("PATCH", path, payload.model_dump(mode="json"))
        with self._session_factory.begin() as session:
            repository = UserWriteRepository(session)
            claim, now = self._claim(
                repository,
                actor,
                idempotency_key,
                "PATCH",
                path,
                digest,
            )
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return _replay_result(claim, 200)
            user = self._lock_target(repository, actor.organization_id, user_id)
            self._assert_row_version(user, payload.row_version)
            if user.status == payload.status:
                raise _conflict("USER_STATE_UNCHANGED", "用户状态未发生变化")
            assignments = repository.lock_active_fixed_assignments(user.id, now)
            role_codes = tuple(sorted({role_code for _, role_code in assignments}))
            self._assert_last_admin_preserved(
                repository,
                user,
                role_codes,
                target_will_be_active_admin=(
                    payload.status == "active" and "system_admin" in role_codes
                ),
                now=now,
            )
            previous_status = user.status
            user.status = payload.status
            user.failed_login_count = 0
            user.locked_until = None
            user.token_invalid_before = now
            user.updated_at = now
            user.updated_by = actor.user_id
            user.row_version += 1
            repository.revoke_all_user_sessions(user.id, now, "user_status_changed")
            data = _project_user(user, role_codes)
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code="users.status_changed",
                outcome="succeeded",
                resource_type="user",
                resource_id=user.id,
                trace_id=trace_id,
                change_summary={
                    "from_status": previous_status,
                    "to_status": payload.status,
                    "row_version": data.row_version,
                },
            )
            repository.complete_idempotency(
                claim,
                response_status=200,
                response_body=data.model_dump(mode="json"),
                resource_id=user.id,
            )
            return UserMutationResult(data=data, status_code=200, replayed=False)

    @staticmethod
    def _lock_target(
        repository: UserWriteRepository,
        organization_id: UUID,
        user_id: UUID,
    ) -> User:
        user = repository.lock_user(organization_id, user_id)
        if user is None:
            raise _resource_not_found()
        return user

    @staticmethod
    def _assert_row_version(user: User, expected: str) -> None:
        if user.row_version != int(expected):
            raise _conflict("ROW_VERSION_CONFLICT", "资源版本已变化")

    @staticmethod
    def _assert_last_admin_preserved(
        repository: UserWriteRepository,
        user: User,
        current_roles: tuple[str, ...],
        *,
        target_will_be_active_admin: bool,
        now: datetime,
    ) -> None:
        if (
            user.status == "active"
            and "system_admin" in current_roles
            and not target_will_be_active_admin
            and repository.active_system_admin_count(user.organization_id, now) <= 1
        ):
            raise _conflict("LAST_SYSTEM_ADMIN_REQUIRED", "必须保留一个可用系统管理员")

    @staticmethod
    def _claim(
        repository: UserWriteRepository,
        actor: AuthenticatedActor,
        idempotency_key: str,
        method: str,
        path: str,
        digest: str,
    ) -> tuple[IdempotencyClaim, datetime]:
        repository.acquire_organization_lock(actor.organization_id)
        repository.acquire_idempotency_lock(
            actor.organization_id,
            actor.user_id,
            idempotency_key,
        )
        if repository.lock_active_organization(actor.organization_id) is None:
            raise _resource_not_found()
        now = repository.database_now()
        claim = repository.claim_idempotency(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            idempotency_key=idempotency_key,
            request_method=method,
            request_path=path,
            request_hash=digest,
            now=now,
            expires_at=now + _IDEMPOTENCY_TTL,
        )
        return claim, now


__all__ = ["UserManagementService", "UserMutationResult"]
