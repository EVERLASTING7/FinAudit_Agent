from __future__ import annotations

from uuid import UUID

import pytest

from app.core.errors import AppError
from app.core.permissions import PermissionCode, RoleCode, derive_permissions
from app.schemas.files import IntendedBusinessType
from app.services.auth import AuthenticatedActor
from app.services.file_service import require_file_upload_scope


def _actor(
    *roles: RoleCode,
    permissions: tuple[PermissionCode, ...] | None = None,
) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=UUID(int=1),
        organization_id=UUID(int=2),
        session_id=UUID(int=3),
        roles=roles,
        permissions=derive_permissions(roles) if permissions is None else permissions,
    )


@pytest.mark.parametrize(
    ("roles", "business_type"),
    [
        (("finance_reviewer",), IntendedBusinessType.CONTRACT),
        (("finance_reviewer",), IntendedBusinessType.INVOICE),
        (("audit_reviewer",), IntendedBusinessType.POLICY),
        (("contract_admin",), IntendedBusinessType.CONTRACT),
        (("contract_admin",), IntendedBusinessType.SUPPLEMENTARY_AGREEMENT),
        (
            ("finance_reviewer", "audit_reviewer", "contract_admin"),
            IntendedBusinessType.POLICY,
        ),
        (
            ("finance_reviewer", "audit_reviewer", "contract_admin"),
            IntendedBusinessType.SUPPLEMENTARY_AGREEMENT,
        ),
    ],
)
def test_require_file_upload_scope_allows_approved_role_union(
    roles: tuple[RoleCode, ...],
    business_type: IntendedBusinessType,
) -> None:
    require_file_upload_scope(_actor(*roles), business_type)


@pytest.mark.parametrize(
    ("roles", "business_type"),
    [
        (("finance_reviewer",), IntendedBusinessType.SUPPLEMENTARY_AGREEMENT),
        (("finance_reviewer",), IntendedBusinessType.POLICY),
        (("audit_reviewer",), IntendedBusinessType.CONTRACT),
        (("audit_reviewer",), IntendedBusinessType.INVOICE),
        (("contract_admin",), IntendedBusinessType.INVOICE),
        (("contract_admin",), IntendedBusinessType.POLICY),
        (("read_only",), IntendedBusinessType.CONTRACT),
    ],
)
def test_require_file_upload_scope_rejects_out_of_scope_business_types(
    roles: tuple[RoleCode, ...],
    business_type: IntendedBusinessType,
) -> None:
    _assert_forbidden(_actor(*roles), business_type)


@pytest.mark.parametrize(
    "roles",
    [
        ("read_only", "finance_reviewer"),
        ("system_admin", "finance_reviewer"),
        ("system_admin", "contract_admin"),
    ],
)
def test_require_file_upload_scope_preserves_actor_permission_deny_overrides(
    roles: tuple[RoleCode, ...],
) -> None:
    _assert_forbidden(_actor(*roles), IntendedBusinessType.CONTRACT)


def test_require_file_upload_scope_requires_both_capability_and_role_scope() -> None:
    _assert_forbidden(
        _actor("finance_reviewer", permissions=()),
        IntendedBusinessType.CONTRACT,
    )
    _assert_forbidden(
        _actor("read_only", permissions=("files.upload",)),
        IntendedBusinessType.CONTRACT,
    )


def test_require_file_upload_scope_rejects_non_enum_value_with_same_stable_error() -> None:
    _assert_forbidden(
        _actor("finance_reviewer"),
        "contract",  # type: ignore[arg-type]
    )


def _assert_forbidden(
    actor: AuthenticatedActor,
    business_type: IntendedBusinessType,
) -> None:
    with pytest.raises(AppError) as exc_info:
        require_file_upload_scope(actor, business_type)

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "FILE_UPLOAD_FORBIDDEN"
    assert exc_info.value.message == "无权执行文件上传"
    assert exc_info.value.details == []
    assert exc_info.value.data is None
