from __future__ import annotations

import pytest

from app.core.permissions import (
    MUTATING_PERMISSIONS,
    OBJECT_LEVEL_SOD_PREDECESSORS,
    PERMISSION_CODES,
    ROLE_CODES,
    ROLE_PERMISSIONS,
    derive_permissions,
)


def test_permission_dictionary_is_exact_sorted_and_unique() -> None:
    assert len(PERMISSION_CODES) == 26
    assert PERMISSION_CODES == tuple(sorted(set(PERMISSION_CODES)))
    assert ROLE_CODES == (
        "system_admin",
        "finance_reviewer",
        "audit_reviewer",
        "contract_admin",
        "read_only",
    )
    assert set(permission for values in ROLE_PERMISSIONS.values() for permission in values) == set(
        PERMISSION_CODES
    )
    assert all(values == tuple(sorted(set(values))) for values in ROLE_PERMISSIONS.values())


def test_five_role_mapping_matches_p0_permissions_v1() -> None:
    assert dict(ROLE_PERMISSIONS) == {
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
        "read_only": ("audits.read", "reports.read"),
    }


def test_each_single_role_derives_its_exact_static_mapping() -> None:
    for role_code, expected in ROLE_PERMISSIONS.items():
        assert derive_permissions([role_code]) == expected


def test_business_roles_union_and_deduplicate_permissions() -> None:
    roles = ("finance_reviewer", "audit_reviewer", "contract_admin")
    expected = tuple(
        sorted({permission for role in roles for permission in ROLE_PERMISSIONS[role]})
    )

    assert derive_permissions(roles) == expected
    assert derive_permissions((*roles, "finance_reviewer")) == expected


def test_system_admin_override_removes_all_business_permissions() -> None:
    assert derive_permissions(("system_admin", "finance_reviewer", "audit_reviewer")) == (
        "jobs.recover",
        "knowledge.publish",
        "operations.read",
        "system.configure",
        "temporary_roles.decide",
        "temporary_roles.request",
        "users.manage",
    )


def test_system_admin_and_read_only_apply_both_deny_overrides() -> None:
    assert derive_permissions(("system_admin", "read_only", "finance_reviewer")) == (
        "operations.read",
    )


def test_read_only_override_removes_mutation_and_export_from_business_roles() -> None:
    permissions = derive_permissions(("read_only", "finance_reviewer", "contract_admin"))

    assert permissions == (
        "audits.read",
        "files.read",
        "financial.read",
        "knowledge.use",
        "reports.read",
    )
    assert MUTATING_PERMISSIONS.isdisjoint(permissions)


def test_break_glass_role_union_cannot_bypass_deny_overrides() -> None:
    # derive_permissions 不按 assignment source 分支，因此 break-glass 与长期角色应用相同 deny。
    assert derive_permissions(("read_only", "audit_reviewer")) == (
        "audits.read",
        "files.read",
        "financial.read",
        "knowledge.use",
        "reports.read",
    )
    assert (
        derive_permissions(("system_admin", "contract_admin")) == ROLE_PERMISSIONS["system_admin"]
    )


def test_unknown_role_fails_closed_and_empty_role_set_has_no_capabilities() -> None:
    assert derive_permissions(()) == ()
    with pytest.raises(ValueError, match="unknown role"):
        derive_permissions(("owner",))


def test_role_and_sod_mappings_are_immutable() -> None:
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS["read_only"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        OBJECT_LEVEL_SOD_PREDECESSORS["knowledge.approve"] = (  # type: ignore[index]
            "risks.review_non_high"
        )


def test_object_level_sod_predecessors_are_explicit_and_not_role_overrides() -> None:
    assert dict(OBJECT_LEVEL_SOD_PREDECESSORS) == {
        "knowledge.approve": "knowledge.submit",
        "risks.review_high": "risks.review_non_high",
    }
    assert "knowledge.approve" in ROLE_PERMISSIONS["audit_reviewer"]
    assert "risks.review_high" in ROLE_PERMISSIONS["audit_reviewer"]
