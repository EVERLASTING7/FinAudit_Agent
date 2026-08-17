"""p0-permissions-v1 的静态 capability 映射与 deny overrides。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Final, Literal, TypeAlias, cast

RoleCode: TypeAlias = Literal[
    "system_admin",
    "finance_reviewer",
    "audit_reviewer",
    "contract_admin",
    "read_only",
]
PermissionCode: TypeAlias = Literal[
    "users.manage",
    "temporary_roles.request",
    "temporary_roles.decide",
    "system.configure",
    "operations.read",
    "jobs.recover",
    "files.read",
    "files.upload",
    "files.manage",
    "financial.read",
    "contracts.manage",
    "invoices.manage",
    "suppliers.correct",
    "links.suggest",
    "links.manage_primary",
    "knowledge.use",
    "knowledge.submit",
    "knowledge.approve",
    "knowledge.publish",
    "audits.read",
    "audits.create",
    "risks.review_non_high",
    "risks.review_high",
    "audits.complete",
    "reports.read",
    "reports.export",
]

ROLE_CODES: Final[tuple[RoleCode, ...]] = (
    "system_admin",
    "finance_reviewer",
    "audit_reviewer",
    "contract_admin",
    "read_only",
)
PERMISSION_CODES: Final[tuple[PermissionCode, ...]] = (
    "audits.complete",
    "audits.create",
    "audits.read",
    "contracts.manage",
    "files.manage",
    "files.read",
    "files.upload",
    "financial.read",
    "invoices.manage",
    "jobs.recover",
    "knowledge.approve",
    "knowledge.publish",
    "knowledge.submit",
    "knowledge.use",
    "links.manage_primary",
    "links.suggest",
    "operations.read",
    "reports.export",
    "reports.read",
    "risks.review_high",
    "risks.review_non_high",
    "suppliers.correct",
    "system.configure",
    "temporary_roles.decide",
    "temporary_roles.request",
    "users.manage",
)

_ROLE_PERMISSIONS: Final[dict[RoleCode, tuple[PermissionCode, ...]]] = {
    "system_admin": (
        "jobs.recover",
        "knowledge.publish",
        "operations.read",
        "system.configure",
        "temporary_roles.decide",
        "temporary_roles.request",
        "users.manage",
    ),
    "finance_reviewer": (
        "audits.complete",
        "audits.create",
        "audits.read",
        "files.manage",
        "files.read",
        "files.upload",
        "financial.read",
        "invoices.manage",
        "knowledge.use",
        "links.manage_primary",
        "reports.export",
        "reports.read",
        "risks.review_non_high",
        "suppliers.correct",
    ),
    "audit_reviewer": (
        "audits.read",
        "files.manage",
        "files.read",
        "files.upload",
        "financial.read",
        "knowledge.approve",
        "knowledge.submit",
        "knowledge.use",
        "reports.read",
        "risks.review_high",
    ),
    "contract_admin": (
        "audits.read",
        "contracts.manage",
        "files.manage",
        "files.read",
        "files.upload",
        "financial.read",
        "knowledge.use",
        "links.suggest",
        "reports.read",
        "suppliers.correct",
    ),
    "read_only": (
        "audits.read",
        "reports.read",
    ),
}
ROLE_PERMISSIONS: Final[Mapping[RoleCode, tuple[PermissionCode, ...]]] = MappingProxyType(
    _ROLE_PERMISSIONS
)

MUTATING_PERMISSIONS: Final[frozenset[PermissionCode]] = frozenset(
    permission
    for permission in PERMISSION_CODES
    if permission
    not in {
        "operations.read",
        "files.read",
        "financial.read",
        "knowledge.use",
        "audits.read",
        "reports.read",
    }
)

# Service 在锁定对象后比较当前 actor 与前序动作 actor；break-glass 不绕过该映射。
OBJECT_LEVEL_SOD_PREDECESSORS: Final[Mapping[PermissionCode, PermissionCode]] = MappingProxyType(
    {
        "knowledge.approve": "knowledge.submit",
        "risks.review_high": "risks.review_non_high",
    }
)


def derive_permissions(role_codes: Iterable[str]) -> tuple[PermissionCode, ...]:
    """合并当前有效角色，并在合并后应用 system-admin/read-only deny override。"""

    roles = set(role_codes)
    unknown = roles.difference(ROLE_CODES)
    if unknown:
        raise ValueError("unknown role code")
    typed_roles = cast(set[RoleCode], roles)

    if "system_admin" in typed_roles:
        permissions = set(ROLE_PERMISSIONS["system_admin"])
    else:
        permissions = {permission for role in typed_roles for permission in ROLE_PERMISSIONS[role]}
    if "read_only" in typed_roles:
        permissions.difference_update(MUTATING_PERMISSIONS)
    return tuple(sorted(permissions))
