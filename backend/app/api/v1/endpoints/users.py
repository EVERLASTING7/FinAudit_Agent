"""Authenticated user-list-read-v1 endpoint."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response

from app.api.dependencies.auth import require_permission
from app.api.dependencies.users import (
    UserManagementServiceDependency,
    UserQueryServiceDependency,
)
from app.core.responses import utc_timestamp
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.users import (
    UserCreateRequest,
    UserListData,
    UserListItemData,
    UserListQuery,
    UserPasswordResetRequest,
    UserRolesReplaceRequest,
    UserStatusUpdateRequest,
    UserWriteQuery,
)
from app.services.auth import AuthenticatedActor
from app.services.user_management import UserMutationResult

router = APIRouter(prefix="/users", tags=["用户管理"])

UserManageActor = Annotated[
    AuthenticatedActor,
    Depends(require_permission("users.manage")),
]
CanonicalUserId = Annotated[
    str,
    Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._~-]+$",
    ),
]
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少用户管理权限", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "用户目录查询服务未配置", "model": ErrorResponse},
}
_WRITE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "认证无效", "model": ErrorResponse},
    403: {"description": "缺少用户管理权限", "model": ErrorResponse},
    404: {"description": "用户不存在或不可见", "model": ErrorResponse},
    409: {"description": "幂等、并发或用户状态冲突", "model": ErrorResponse},
    422: {"description": "请求参数不符合约束", "model": ErrorResponse},
    503: {"description": "用户管理服务未配置", "model": ErrorResponse},
}


def _mutation_response(
    request: Request,
    response: Response,
    result: UserMutationResult,
) -> SuccessResponse[UserListItemData]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    return SuccessResponse[UserListItemData](
        data=result.data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


@router.post(
    "",
    status_code=201,
    operation_id="create_user_v1",
    summary="创建用户",
    response_model=SuccessResponse[UserListItemData],
    responses=_WRITE_ERROR_RESPONSES,
)
def create_user(
    payload: UserCreateRequest,
    query: Annotated[UserWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: UserManageActor,
    service: UserManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[UserListItemData]:
    del query
    result = service.create_user(
        actor,
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    if result.status_code != 201:
        raise RuntimeError("user create service returned an invalid status")
    return _mutation_response(request, response, result)


@router.patch(
    "/{user_id}/status",
    operation_id="update_user_status_v1",
    summary="启用或停用用户",
    response_model=SuccessResponse[UserListItemData],
    responses=_WRITE_ERROR_RESPONSES,
)
def update_user_status(
    user_id: CanonicalUserId,
    payload: UserStatusUpdateRequest,
    query: Annotated[UserWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: UserManageActor,
    service: UserManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[UserListItemData]:
    del query
    result = service.update_status(
        actor,
        UUID(user_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    if result.status_code != 200:
        raise RuntimeError("user status service returned an invalid status")
    return _mutation_response(request, response, result)


@router.post(
    "/{user_id}/password/reset",
    operation_id="reset_user_password_v1",
    summary="重置用户密码",
    response_model=SuccessResponse[UserListItemData],
    responses=_WRITE_ERROR_RESPONSES,
)
def reset_user_password(
    user_id: CanonicalUserId,
    payload: UserPasswordResetRequest,
    query: Annotated[UserWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: UserManageActor,
    service: UserManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[UserListItemData]:
    del query
    result = service.reset_password(
        actor,
        UUID(user_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    if result.status_code != 200:
        raise RuntimeError("password reset service returned an invalid status")
    return _mutation_response(request, response, result)


@router.put(
    "/{user_id}/roles",
    operation_id="replace_user_roles_v1",
    summary="替换用户固定角色",
    response_model=SuccessResponse[UserListItemData],
    responses=_WRITE_ERROR_RESPONSES,
)
def replace_user_roles(
    user_id: CanonicalUserId,
    payload: UserRolesReplaceRequest,
    query: Annotated[UserWriteQuery, Query()],
    request: Request,
    response: Response,
    actor: UserManageActor,
    service: UserManagementServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SuccessResponse[UserListItemData]:
    del query
    result = service.replace_roles(
        actor,
        UUID(user_id),
        payload,
        idempotency_key,
        UUID(request.state.trace_id),
    )
    if result.status_code != 200:
        raise RuntimeError("user role service returned an invalid status")
    return _mutation_response(request, response, result)


@router.get(
    "",
    operation_id="list_users_v1",
    summary="读取用户列表",
    description=(
        "只返回当前 Actor 组织内未软删除用户的最小管理摘要及当前固定角色；"
        "不返回权限推导、break-glass、凭据、会话、组织标识或任何写能力。"
    ),
    response_model=SuccessResponse[UserListData],
    responses=_ERROR_RESPONSES,
)
def list_users(
    query: Annotated[UserListQuery, Query()],
    request: Request,
    response: Response,
    actor: UserManageActor,
    service: UserQueryServiceDependency,
) -> SuccessResponse[UserListData]:
    data = service.list_page(actor.organization_id, query.cursor, query.page_size)
    response.headers["Cache-Control"] = "private, no-store"
    return SuccessResponse[UserListData](
        data=data,
        trace_id=request.state.trace_id,
        timestamp=utc_timestamp(),
    )


__all__ = ["router"]
