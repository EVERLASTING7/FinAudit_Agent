"""break-glass-write-v1 的双人控制事务用例。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.models.auth import BreakGlassRequest, UserRole
from app.repositories.operation_log import OperationLogRepository
from app.repositories.user_write import IdempotencyClaim, UserWriteRepository
from app.schemas.break_glass import (
    BreakGlassCreateRequest,
    BreakGlassData,
    BreakGlassDecisionRequest,
    BreakGlassRevokeRequest,
    BreakGlassRoleCode,
    BreakGlassStatus,
)
from app.services.auth import AuthenticatedActor

_IDEMPOTENCY_KEY_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~-"
)
_IDEMPOTENCY_TTL = timedelta(hours=24)


class BreakGlassMutationResult:
    __slots__ = ("data", "replayed", "status_code")

    def __init__(self, data: BreakGlassData, status_code: int, replayed: bool) -> None:
        self.data = data
        self.status_code = status_code
        self.replayed = replayed


def _validate_key(value: str) -> None:
    if (
        type(value) is not str
        or not 8 <= len(value) <= 128
        or any(char not in _IDEMPOTENCY_KEY_CHARS for char in value)
    ):
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": "header.Idempotency-Key", "reason": "invalid"}],
        )


def _hash_request(method: str, path: str, body: dict[str, object]) -> str:
    encoded = json.dumps(
        {"method": method, "path": path, "body": body},
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _project(request: BreakGlassRequest) -> BreakGlassData:
    return BreakGlassData(
        id=request.id,
        target_user_id=request.target_user_id,
        target_role_code=cast(BreakGlassRoleCode, request.target_role_code),
        requested_duration_seconds=request.requested_duration_seconds,
        status=cast(BreakGlassStatus, request.status),
        effective_from=request.effective_from,
        expires_at=request.expires_at,
        row_version=str(request.row_version),
    )


def _replay(claim: IdempotencyClaim, status_code: int) -> BreakGlassMutationResult:
    if claim.replay_status != status_code or claim.replay_body is None:
        raise RuntimeError("break-glass idempotency replay is incomplete")
    encoded = json.dumps(
        claim.replay_body,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return BreakGlassMutationResult(
        BreakGlassData.model_validate_json(encoded),
        status_code,
        True,
    )


def _sqlstate(error: IntegrityError) -> str | None:
    value = getattr(error.orig, "sqlstate", None)
    return value if isinstance(value, str) else None


class BreakGlassService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        actor: AuthenticatedActor,
        payload: BreakGlassCreateRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> BreakGlassMutationResult:
        _validate_key(idempotency_key)
        path = "/api/v1/break-glass-requests"
        digest = _hash_request("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository = UserWriteRepository(session)
                claim, now = self._claim(repository, actor, idempotency_key, "POST", path, digest)
                if claim.conflict:
                    raise _error(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return _replay(claim, 201)
                if repository.lock_user(actor.organization_id, payload.target_user_id) is None:
                    raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
                if set(repository.lock_enabled_roles((payload.target_role_code,))) != {
                    payload.target_role_code
                }:
                    raise _error(409, "BREAK_GLASS_NOT_ELIGIBLE", "临时授权资格不满足")

                request = BreakGlassRequest(
                    id=uuid4(),
                    organization_id=actor.organization_id,
                    target_user_id=payload.target_user_id,
                    target_role_code=payload.target_role_code,
                    requested_by=actor.user_id,
                    reason=payload.reason,
                    requested_duration_seconds=payload.requested_duration_seconds,
                    status="pending",
                    row_version=1,
                    created_at=now,
                    updated_at=now,
                    trace_id=trace_id,
                )
                repository.add(request)
                repository.flush()
                data = _project(request)
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="break_glass.requested",
                    outcome="succeeded",
                    resource_type="break_glass_request",
                    resource_id=request.id,
                    trace_id=trace_id,
                    change_summary={
                        "target_role_code": payload.target_role_code,
                        "status": "pending",
                        "row_version": data.row_version,
                        "requested_duration_seconds": payload.requested_duration_seconds,
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_status=201,
                    response_body=data.model_dump(mode="json"),
                    resource_id=request.id,
                )
                return BreakGlassMutationResult(data, 201, False)
        except IntegrityError as error:
            if _sqlstate(error) in {"23514", "23P01", "23505"}:
                raise _error(
                    409,
                    "BREAK_GLASS_NOT_ELIGIBLE",
                    "临时授权资格不满足",
                ) from None
            raise

    def decide(
        self,
        actor: AuthenticatedActor,
        request_id: UUID,
        payload: BreakGlassDecisionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> BreakGlassMutationResult:
        _validate_key(idempotency_key)
        path = f"/api/v1/break-glass-requests/{request_id}/decision"
        digest = _hash_request("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository = UserWriteRepository(session)
                claim, _ = self._claim(repository, actor, idempotency_key, "POST", path, digest)
                if claim.conflict:
                    raise _error(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return _replay(claim, 200)
                request = repository.lock_break_glass_request(actor.organization_id, request_id)
                if request is None:
                    raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
                self._assert_version_and_state(request, payload.row_version, "pending")
                if actor.user_id in {request.requested_by, request.target_user_id}:
                    raise _error(
                        409,
                        "BREAK_GLASS_NOT_ELIGIBLE",
                        "临时授权资格不满足",
                    )

                request.status = payload.decision
                request.decided_by = actor.user_id
                request.decision_reason = payload.reason
                request.row_version += 1
                repository.flush()
                repository.refresh(request)
                if payload.decision == "approved":
                    roles = repository.lock_enabled_roles((request.target_role_code,))
                    role = roles.get(request.target_role_code)
                    if role is None or request.effective_from is None or request.expires_at is None:
                        raise _error(
                            409,
                            "BREAK_GLASS_NOT_ELIGIBLE",
                            "临时授权资格不满足",
                        )
                    repository.add(
                        UserRole(
                            id=uuid4(),
                            user_id=request.target_user_id,
                            role_id=role.id,
                            assigned_by=actor.user_id,
                            assignment_source="break_glass",
                            assigned_at=request.effective_from,
                            expires_at=request.expires_at,
                            break_glass_request_id=request.id,
                            assignment_reason=payload.reason,
                        )
                    )
                    repository.flush()
                data = _project(request)
                action = f"break_glass.{payload.decision}"
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code=action,
                    outcome="succeeded",
                    resource_type="break_glass_request",
                    resource_id=request.id,
                    trace_id=trace_id,
                    change_summary={
                        "target_role_code": request.target_role_code,
                        "status": payload.decision,
                        "row_version": data.row_version,
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_status=200,
                    response_body=data.model_dump(mode="json"),
                    resource_id=request.id,
                )
                return BreakGlassMutationResult(data, 200, False)
        except IntegrityError as error:
            if _sqlstate(error) in {"23514", "23P01", "23505"}:
                raise _error(
                    409,
                    "BREAK_GLASS_NOT_ELIGIBLE",
                    "临时授权资格不满足",
                ) from None
            raise

    def revoke(
        self,
        actor: AuthenticatedActor,
        request_id: UUID,
        payload: BreakGlassRevokeRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> BreakGlassMutationResult:
        _validate_key(idempotency_key)
        path = f"/api/v1/break-glass-requests/{request_id}/revoke"
        digest = _hash_request("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository = UserWriteRepository(session)
                claim, _ = self._claim(repository, actor, idempotency_key, "POST", path, digest)
                if claim.conflict:
                    raise _error(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return _replay(claim, 200)
                request = repository.lock_break_glass_request(actor.organization_id, request_id)
                if request is None:
                    raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
                self._assert_version_and_state(request, payload.row_version, "approved")
                assignment = repository.lock_break_glass_assignment(request.id)
                if assignment is None:
                    raise _error(
                        409,
                        "BREAK_GLASS_STATE_CONFLICT",
                        "临时授权状态不允许该操作",
                    )

                request.status = "revoked"
                request.revoked_by = actor.user_id
                request.revoke_reason = payload.reason
                request.row_version += 1
                repository.flush()
                repository.refresh(request)
                if request.revoked_at is None:
                    raise RuntimeError("database did not assign break-glass revocation time")
                assignment.revoked_by = actor.user_id
                assignment.revoked_at = request.revoked_at
                assignment.revoke_reason = payload.reason
                repository.flush()
                data = _project(request)
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="break_glass.revoked",
                    outcome="succeeded",
                    resource_type="break_glass_request",
                    resource_id=request.id,
                    trace_id=trace_id,
                    change_summary={
                        "target_role_code": request.target_role_code,
                        "status": "revoked",
                        "row_version": data.row_version,
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_status=200,
                    response_body=data.model_dump(mode="json"),
                    resource_id=request.id,
                )
                return BreakGlassMutationResult(data, 200, False)
        except IntegrityError as error:
            if _sqlstate(error) in {"23514", "23P01", "23505"}:
                raise _error(
                    409,
                    "BREAK_GLASS_NOT_ELIGIBLE",
                    "临时授权资格不满足",
                ) from None
            raise

    @staticmethod
    def _assert_version_and_state(
        request: BreakGlassRequest,
        row_version: str,
        expected_status: str,
    ) -> None:
        if request.row_version != int(row_version):
            raise _error(409, "ROW_VERSION_CONFLICT", "资源版本已变化")
        if request.status != expected_status:
            raise _error(
                409,
                "BREAK_GLASS_STATE_CONFLICT",
                "临时授权状态不允许该操作",
            )

    @staticmethod
    def _claim(
        repository: UserWriteRepository,
        actor: AuthenticatedActor,
        key: str,
        method: str,
        path: str,
        digest: str,
    ) -> tuple[IdempotencyClaim, datetime]:
        repository.acquire_organization_lock(actor.organization_id)
        repository.acquire_idempotency_lock(actor.organization_id, actor.user_id, key)
        if repository.lock_active_organization(actor.organization_id) is None:
            raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
        now = repository.database_now()
        return (
            repository.claim_idempotency(
                organization_id=actor.organization_id,
                actor_id=actor.user_id,
                idempotency_key=key,
                request_method=method,
                request_path=path,
                request_hash=digest,
                now=now,
                expires_at=now + _IDEMPOTENCY_TTL,
            ),
            now,
        )


__all__ = ["BreakGlassMutationResult", "BreakGlassService"]
