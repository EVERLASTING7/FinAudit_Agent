from sqlalchemy import CHAR, CheckConstraint, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT, INET, ExcludeConstraint

from app.models import (
    BREAK_GLASS_REQUEST_STATUSES,
    ROLE_CODES,
    USER_ROLE_ASSIGNMENT_SOURCES,
    Base,
    BreakGlassRequest,
    UserRole,
)


def test_identity_core_metadata_contains_all_six_identity_tables() -> None:
    assert {
        "break_glass_requests",
        "organizations",
        "users",
        "roles",
        "token_sessions",
        "user_roles",
    } <= set(Base.metadata.tables)


def test_fixed_role_contract_is_exact() -> None:
    assert ROLE_CODES == (
        "system_admin",
        "finance_reviewer",
        "audit_reviewer",
        "contract_admin",
        "read_only",
    )
    role_table = Base.metadata.tables["roles"]
    checks = {
        constraint.name
        for constraint in role_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    uniques = {
        constraint.name
        for constraint in role_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "ck_roles_code_allowed" in checks
    assert "uq_roles_code" in uniques


def test_user_identity_columns_and_active_uniqueness_are_postgresql_native() -> None:
    user_table = Base.metadata.tables["users"]
    assert isinstance(user_table.c.username.type, CITEXT)
    assert isinstance(user_table.c.email.type, CITEXT)
    assert user_table.c.force_change_on_login.nullable is False
    assert str(user_table.c.force_change_on_login.server_default.arg) == "false"
    assert user_table.c.failed_login_count.nullable is False
    indexes = {index.name: index for index in user_table.indexes if isinstance(index, Index)}
    assert set(indexes) == {"uq_users_username_active", "uq_users_email_active"}
    assert all(index.unique for index in indexes.values())


def test_single_organization_and_hashed_session_constraints_are_present() -> None:
    organization_table = Base.metadata.tables["organizations"]
    organization_checks = {
        constraint.name
        for constraint in organization_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_organizations_singleton_key_is_one" in organization_checks
    assert organization_table.c.singleton_key.nullable is False

    session_table = Base.metadata.tables["token_sessions"]
    session_checks = {
        constraint.name
        for constraint in session_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_token_sessions_expires_after_issue" in session_checks
    assert isinstance(session_table.c.refresh_token_hash.type, CHAR)
    assert session_table.c.refresh_token_hash.type.length == 64
    assert isinstance(session_table.c.ip_address.type, INET)


def test_privileged_auth_constants_and_exports_are_exact() -> None:
    assert BREAK_GLASS_REQUEST_STATUSES == (
        "pending",
        "approved",
        "rejected",
        "revoked",
        "expired",
    )
    assert USER_ROLE_ASSIGNMENT_SOURCES == ("bootstrap", "user", "break_glass")
    assert BreakGlassRequest.__table__ is Base.metadata.tables["break_glass_requests"]
    assert UserRole.__table__ is Base.metadata.tables["user_roles"]


def test_break_glass_request_model_contract_is_exact() -> None:
    table = Base.metadata.tables["break_glass_requests"]
    assert list(table.c) == [
        table.c[name]
        for name in (
            "id",
            "organization_id",
            "target_user_id",
            "target_role_code",
            "requested_by",
            "reason",
            "requested_duration_seconds",
            "status",
            "effective_from",
            "expires_at",
            "decided_by",
            "decision_at",
            "decision_reason",
            "revoked_by",
            "revoked_at",
            "revoke_reason",
            "row_version",
            "created_at",
            "updated_at",
            "trace_id",
        )
    ]
    assert "approved_by" not in table.c
    assert isinstance(table.c.row_version.type, Integer)
    assert str(table.c.row_version.server_default.arg) == "1"
    checks = {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert checks == {
        "ck_break_glass_requests_decision_reason_nonempty",
        "ck_break_glass_requests_reason_nonempty",
        "ck_break_glass_requests_requested_duration_bounds",
        "ck_break_glass_requests_revoke_reason_nonempty",
        "ck_break_glass_requests_row_version_positive",
        "ck_break_glass_requests_state_field_matrix",
        "ck_break_glass_requests_status_allowed",
        "ck_break_glass_requests_target_role_code_allowed",
        "ck_break_glass_requests_time_matrix",
    }


def test_user_role_model_contract_uses_half_open_gist_exclusion() -> None:
    table = Base.metadata.tables["user_roles"]
    assert list(table.c.keys()) == [
        "id",
        "user_id",
        "role_id",
        "assigned_by",
        "assignment_source",
        "assigned_at",
        "expires_at",
        "break_glass_request_id",
        "assignment_reason",
        "revoked_at",
        "revoked_by",
        "revoke_reason",
    ]
    assert "uq_user_role_active" not in {index.name for index in table.indexes}
    checks = {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert checks == {
        "ck_user_roles_assignment_reason_nonempty",
        "ck_user_roles_assignment_source_allowed",
        "ck_user_roles_assignment_source_matrix",
        "ck_user_roles_revocation_matrix",
        "ck_user_roles_time_order",
    }
    exclusion = next(
        constraint for constraint in table.constraints if isinstance(constraint, ExcludeConstraint)
    )
    assert exclusion.name == "ex_user_roles_effective_range_no_overlap"
    assert str(exclusion.where) == "revoked_at IS NULL"
    assert [(name, operator) for _, name, operator in exclusion._render_exprs] == [
        ("user_id", "="),
        ("role_id", "="),
        (None, "&&"),
    ]
    assert "'[)'" in str(exclusion._render_exprs[-1][0])
